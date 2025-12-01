"""
Mempool.space WebSocket Listener for TBWI.

Alternative to ZMQ listener - connects to mempool.space's free API
for real-time Bitcoin mainnet transactions without running a local node.

Zero storage required!
"""

from __future__ import annotations

import asyncio
import json
import signal
from datetime import datetime
from typing import Any

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from tbwi.config import get_settings
from tbwi.logging import get_logger, setup_logging
from tbwi.models.schemas import NormalizedTransaction, TransactionOutput
from tbwi.services.message_queue import MessageQueue, get_message_queue
from tbwi.services.metrics import (
    TX_PROCESSED,
    TX_FILTERED,
    TX_PARSE_ERRORS,
)

logger = get_logger(__name__)

# Mempool.space API endpoints
MEMPOOL_WS_URL = "wss://mempool.space/api/v1/ws"
MEMPOOL_API_URL = "https://mempool.space/api"

# Satoshis per Bitcoin
SATOSHI_PER_BTC = 100_000_000


class MempoolListener:
    """
    Mempool.space WebSocket listener for real-time Bitcoin transactions.

    Subscribes to the mempool feed and filters for large transactions,
    then publishes them to the same Redis channel as the ZMQ listener.
    """

    def __init__(
        self,
        min_tx_threshold_btc: float | None = None,
        message_queue: MessageQueue | None = None,
    ):
        settings = get_settings()
        self.min_tx_threshold_btc = (
            min_tx_threshold_btc
            if min_tx_threshold_btc is not None
            else settings.thresholds.min_tx_btc
        )
        self.message_queue = message_queue
        self.network = "mainnet"  # Mempool.space is mainnet only

        self._running = False
        self._tx_count = 0
        self._filtered_count = 0
        self._ws: Any = None
        self._http_client: httpx.AsyncClient | None = None

        # Rate limiting for API calls
        self._last_api_call = 0.0
        self._api_call_interval = 0.1  # 100ms between API calls (10 req/sec)

        # Track recent txids to avoid duplicates
        self._recent_txids: set[str] = set()
        self._max_recent_txids = 10000

    async def start(self) -> None:
        """Start the mempool.space listener."""
        logger.info(
            "Starting Mempool.space listener",
            ws_url=MEMPOOL_WS_URL,
            min_threshold_btc=self.min_tx_threshold_btc,
        )

        # Get message queue if not provided
        if self.message_queue is None:
            self.message_queue = await get_message_queue()

        # Create HTTP client for REST API calls
        self._http_client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "TBWI/1.0"},
        )

        self._running = True

        # Start with retry logic
        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                if self._running:
                    logger.error(
                        "WebSocket connection failed, retrying in 5s",
                        error=str(e),
                    )
                    await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the listener."""
        logger.info("Stopping Mempool.space listener")
        self._running = False

        if self._ws:
            await self._ws.close()

        if self._http_client:
            await self._http_client.aclose()

        logger.info(
            "Mempool listener stopped",
            total_tx=self._tx_count,
            filtered_tx=self._filtered_count,
        )

    async def _connect_and_listen(self) -> None:
        """Connect to WebSocket and start listening."""
        async with websockets.connect(
            MEMPOOL_WS_URL,
            ping_interval=30,
            ping_timeout=10,
        ) as ws:
            self._ws = ws
            logger.info("Connected to mempool.space WebSocket")

            # Subscribe to new transactions
            # The mempool.space WebSocket sends transactions automatically
            # We can also request specific data
            subscribe_msg = json.dumps({
                "action": "want",
                "data": ["mempool-blocks", "stats"],
            })
            await ws.send(subscribe_msg)

            # Also subscribe to live transaction tracking
            track_msg = json.dumps({
                "action": "init",
            })
            await ws.send(track_msg)

            # Start listening tasks
            await asyncio.gather(
                self._listen_websocket(ws),
                self._log_stats(),
            )

    async def _listen_websocket(self, ws: Any) -> None:
        """Listen for WebSocket messages."""
        while self._running:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=60)
                data = json.loads(msg)

                # Handle different message types
                if "mempoolInfo" in data:
                    info = data["mempoolInfo"]
                    logger.debug(
                        "Mempool stats",
                        size=info.get("size", 0),
                        vsize=info.get("vsize", 0),
                    )

                # Handle transactions from mempool-blocks
                if "transactions" in data:
                    for tx_data in data["transactions"]:
                        await self._process_tx_preview(tx_data)

                # Handle individual transaction added
                if "tx" in data:
                    await self._process_tx_preview(data["tx"])

                # Handle mempool block projections (contains fee estimates)
                if "mempool-blocks" in data:
                    for block in data["mempool-blocks"]:
                        if "transactions" in block:
                            for tx_data in block["transactions"]:
                                await self._process_tx_preview(tx_data)

            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    pong = await ws.ping()
                    await asyncio.wait_for(pong, timeout=10)
                except Exception:
                    logger.warning("WebSocket ping failed, reconnecting...")
                    return
            except ConnectionClosed:
                logger.warning("WebSocket connection closed")
                return
            except Exception as e:
                logger.error("Error processing WebSocket message", error=str(e))

    async def _process_tx_preview(self, tx_preview: dict) -> None:
        """
        Process a transaction preview from the WebSocket.

        The WebSocket provides limited data, so we fetch full details
        via REST API for large transactions.
        """
        self._tx_count += 1
        TX_PROCESSED.inc()

        txid = tx_preview.get("txid")
        if not txid:
            return

        # Skip if we've seen this recently
        if txid in self._recent_txids:
            return

        # Add to recent set (with cleanup)
        self._recent_txids.add(txid)
        if len(self._recent_txids) > self._max_recent_txids:
            # Remove oldest entries (convert to list, slice, back to set)
            self._recent_txids = set(list(self._recent_txids)[-5000:])

        # Get value from preview (in satoshis or BTC depending on field)
        value_sat = tx_preview.get("value", 0)
        if value_sat == 0:
            # Try fee + vsize estimate
            fee = tx_preview.get("fee", 0)
            # Skip low-fee transactions (likely small)
            if fee < 10000:  # Less than 10k sats fee = probably small tx
                return
            # Fetch full tx to get value
            value_btc = 0
        else:
            value_btc = value_sat / SATOSHI_PER_BTC

        # Quick filter: skip if clearly below threshold
        if value_btc > 0 and value_btc < self.min_tx_threshold_btc:
            return

        # Fetch full transaction details for potential whale txs
        try:
            tx = await self._fetch_full_transaction(txid)
            if tx:
                await self._process_full_transaction(tx)
        except Exception as e:
            TX_PARSE_ERRORS.inc()
            logger.debug("Failed to fetch transaction", txid=txid, error=str(e))

    async def _fetch_full_transaction(self, txid: str) -> dict | None:
        """Fetch full transaction details from REST API."""
        if not self._http_client:
            return None

        # Rate limiting
        import time
        now = time.time()
        elapsed = now - self._last_api_call
        if elapsed < self._api_call_interval:
            await asyncio.sleep(self._api_call_interval - elapsed)
        self._last_api_call = time.time()

        try:
            response = await self._http_client.get(f"{MEMPOOL_API_URL}/tx/{txid}")
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logger.debug("API request failed", txid=txid, error=str(e))
            return None

    async def _process_full_transaction(self, tx_data: dict) -> None:
        """Process a full transaction from the REST API."""
        try:
            txid = tx_data.get("txid", "")

            # Parse outputs
            vout: list[TransactionOutput] = []
            total_value_sat = 0

            for idx, out in enumerate(tx_data.get("vout", [])):
                value_sat = out.get("value", 0)
                total_value_sat += value_sat

                # Extract address from scriptpubkey
                scriptpubkey = out.get("scriptpubkey_address")
                script_type = out.get("scriptpubkey_type", "unknown")

                vout.append(
                    TransactionOutput(
                        index=idx,
                        value_btc=value_sat / SATOSHI_PER_BTC,
                        script_type=script_type,
                        address=scriptpubkey,
                    )
                )

            total_value_btc = total_value_sat / SATOSHI_PER_BTC

            # Apply threshold filter
            if total_value_btc < self.min_tx_threshold_btc:
                return

            self._filtered_count += 1
            TX_FILTERED.inc()

            # Calculate size
            size_bytes = tx_data.get("size", tx_data.get("weight", 0) // 4)

            # Create normalized transaction
            normalized = NormalizedTransaction(
                txid=txid,
                seen_at=datetime.utcnow(),
                network=self.network,
                total_value_out_btc=total_value_btc,
                vout=vout,
                size_bytes=size_bytes,
                raw_hex=None,  # Not available from mempool.space
            )

            logger.info(
                "🐋 Large transaction detected",
                txid=txid[:16] + "...",
                value_btc=f"{total_value_btc:.2f}",
                outputs=len(vout),
            )

            # Publish to message queue (same channel as ZMQ listener)
            if self.message_queue:
                await self.message_queue.publish(
                    "normalized_tx",
                    normalized.model_dump(mode="json"),
                )

        except Exception as e:
            TX_PARSE_ERRORS.inc()
            logger.error("Error processing transaction", error=str(e))

    async def _log_stats(self) -> None:
        """Periodically log statistics."""
        while self._running:
            await asyncio.sleep(60)
            logger.info(
                "Mempool listener stats",
                total_tx_seen=self._tx_count,
                filtered_large_tx=self._filtered_count,
                threshold_btc=self.min_tx_threshold_btc,
            )


def main() -> None:
    """Main entry point for the mempool listener service."""
    settings = get_settings()
    setup_logging(settings.log_level, json_output=settings.environment != "development")

    logger.info("Starting TBWI Mempool.space Listener Service")
    logger.info("🌐 No Bitcoin node required - using mempool.space API")

    # Start metrics server
    from tbwi.services.metrics import start_metrics_server
    start_metrics_server(port=9090)

    listener = MempoolListener()

    # Handle shutdown signals
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown(sig: signal.Signals) -> None:
        logger.info("Received shutdown signal", signal=sig.name)
        loop.create_task(listener.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: shutdown(s))

    try:
        loop.run_until_complete(listener.start())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        loop.run_until_complete(listener.stop())
        loop.close()


if __name__ == "__main__":
    main()
