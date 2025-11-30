"""
ZMQ Listener Service for Bitcoin Core.

Subscribes to Bitcoin Core's ZMQ stream for raw transactions and blocks.
"""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime
from typing import Any

import zmq
import zmq.asyncio

from tbwi.config import get_settings
from tbwi.logging import get_logger, setup_logging
from tbwi.models.schemas import NormalizedTransaction, TransactionOutput
from tbwi.services.message_queue import MessageQueue, get_message_queue

logger = get_logger(__name__)


# Satoshis per Bitcoin
SATOSHI_PER_BTC = 100_000_000


def parse_raw_transaction(raw_bytes: bytes, network: str) -> NormalizedTransaction | None:
    """
    Parse a raw transaction from bytes.

    Args:
        raw_bytes: Raw transaction bytes from ZMQ
        network: Bitcoin network (mainnet, testnet, regtest)

    Returns:
        NormalizedTransaction if parsing succeeds, None otherwise
    """
    try:
        # Import bitcoin library for parsing
        from bitcoin.core import CTransaction
        from bitcoin.core.script import CScript

        # Parse the transaction
        tx = CTransaction.deserialize(raw_bytes)
        txid = tx.GetTxid()[::-1].hex()  # Reverse for display format

        # Parse outputs
        vout: list[TransactionOutput] = []
        total_value_satoshi = 0

        for idx, output in enumerate(tx.vout):
            value_satoshi = output.nValue
            total_value_satoshi += value_satoshi

            # Try to extract address from script
            address = None
            script_type = None
            try:
                script = CScript(output.scriptPubKey)
                script_type = _get_script_type(script)
                address = _extract_address(script, network)
            except Exception:
                pass

            vout.append(
                TransactionOutput(
                    index=idx,
                    value_btc=value_satoshi / SATOSHI_PER_BTC,
                    script_type=script_type,
                    address=address,
                )
            )

        return NormalizedTransaction(
            txid=txid,
            seen_at=datetime.utcnow(),
            network=network,
            total_value_out_btc=total_value_satoshi / SATOSHI_PER_BTC,
            vout=vout,
            size_bytes=len(raw_bytes),
            raw_hex=raw_bytes.hex(),
        )
    except Exception as e:
        logger.warning("Failed to parse raw transaction", error=str(e))
        return None


def _get_script_type(script: Any) -> str | None:
    """Determine script type."""
    try:
        from bitcoin.core.script import (
            OP_0,
            OP_DUP,
            OP_HASH160,
        )

        script_bytes = bytes(script)

        # P2PKH: OP_DUP OP_HASH160 <20 bytes> OP_EQUALVERIFY OP_CHECKSIG
        if len(script_bytes) == 25 and script_bytes[0] == OP_DUP:
            return "p2pkh"

        # P2SH: OP_HASH160 <20 bytes> OP_EQUAL
        if len(script_bytes) == 23 and script_bytes[0] == OP_HASH160:
            return "p2sh"

        # P2WPKH: OP_0 <20 bytes>
        if len(script_bytes) == 22 and script_bytes[0] == OP_0:
            return "p2wpkh"

        # P2WSH: OP_0 <32 bytes>
        if len(script_bytes) == 34 and script_bytes[0] == OP_0:
            return "p2wsh"

        # P2TR (Taproot): OP_1 <32 bytes>
        if len(script_bytes) == 34 and script_bytes[0] == 0x51:
            return "p2tr"

        return "unknown"
    except Exception:
        return None


def _extract_address(script: Any, network: str) -> str | None:
    """Extract address from script."""
    try:
        # Use bitcoin library's address extraction

        # This is simplified - in production you'd want more robust address extraction
        # For now, we rely on the enricher service to get addresses via RPC
        return None
    except Exception:
        return None


class ZMQListener:
    """
    ZMQ Listener for Bitcoin Core.

    Subscribes to raw transaction and block topics and processes them.
    """

    def __init__(
        self,
        tx_endpoint: str | None = None,
        block_endpoint: str | None = None,
        min_tx_threshold_btc: float | None = None,
        network: str | None = None,
        message_queue: MessageQueue | None = None,
    ):
        settings = get_settings()
        self.tx_endpoint = tx_endpoint or settings.bitcoin.zmq_tx_endpoint
        self.block_endpoint = block_endpoint or settings.bitcoin.zmq_block_endpoint
        self.min_tx_threshold_btc = (
            min_tx_threshold_btc
            if min_tx_threshold_btc is not None
            else settings.thresholds.min_tx_btc
        )
        self.network = network or settings.bitcoin.network
        self.message_queue = message_queue

        self._context: zmq.asyncio.Context | None = None
        self._tx_socket: zmq.asyncio.Socket | None = None
        self._block_socket: zmq.asyncio.Socket | None = None
        self._running = False
        self._tx_count = 0
        self._filtered_count = 0

    async def start(self) -> None:
        """Start the ZMQ listener."""
        logger.info(
            "Starting ZMQ listener",
            tx_endpoint=self.tx_endpoint,
            block_endpoint=self.block_endpoint,
            network=self.network,
            min_threshold_btc=self.min_tx_threshold_btc,
        )

        # Get message queue if not provided
        if self.message_queue is None:
            self.message_queue = await get_message_queue()

        # Create ZMQ context
        self._context = zmq.asyncio.Context()

        # Subscribe to raw transactions
        self._tx_socket = self._context.socket(zmq.SUB)
        self._tx_socket.connect(self.tx_endpoint)
        self._tx_socket.setsockopt(zmq.SUBSCRIBE, b"rawtx")

        # Subscribe to raw blocks (optional, for block height tracking)
        self._block_socket = self._context.socket(zmq.SUB)
        self._block_socket.connect(self.block_endpoint)
        self._block_socket.setsockopt(zmq.SUBSCRIBE, b"rawblock")

        self._running = True
        logger.info("ZMQ listener connected and subscribed")

        # Start listening tasks
        await asyncio.gather(
            self._listen_transactions(),
            self._listen_blocks(),
            self._log_stats(),
        )

    async def stop(self) -> None:
        """Stop the ZMQ listener."""
        logger.info("Stopping ZMQ listener")
        self._running = False

        if self._tx_socket:
            self._tx_socket.close()
        if self._block_socket:
            self._block_socket.close()
        if self._context:
            self._context.term()

        logger.info("ZMQ listener stopped")

    async def _listen_transactions(self) -> None:
        """Listen for raw transactions."""
        while self._running:
            try:
                # Non-blocking receive with timeout
                if self._tx_socket.poll(timeout=1000):
                    msg = await self._tx_socket.recv_multipart()

                    if len(msg) >= 2:
                        topic = msg[0]
                        raw_tx = msg[1]

                        if topic == b"rawtx":
                            await self._process_raw_transaction(raw_tx)
            except zmq.ZMQError as e:
                if self._running:
                    logger.error("ZMQ error receiving transaction", error=str(e))
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error("Error processing transaction", error=str(e))

    async def _listen_blocks(self) -> None:
        """Listen for raw blocks."""
        while self._running:
            try:
                if self._block_socket.poll(timeout=1000):
                    msg = await self._block_socket.recv_multipart()

                    if len(msg) >= 2:
                        topic = msg[0]
                        raw_block = msg[1]

                        if topic == b"rawblock":
                            await self._process_raw_block(raw_block)
            except zmq.ZMQError as e:
                if self._running:
                    logger.error("ZMQ error receiving block", error=str(e))
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error("Error processing block", error=str(e))

    async def _process_raw_transaction(self, raw_bytes: bytes) -> None:
        """Process a raw transaction."""
        self._tx_count += 1

        # Parse the transaction
        tx = parse_raw_transaction(raw_bytes, self.network)
        if tx is None:
            return

        # Apply minimum threshold filter
        if tx.total_value_out_btc < self.min_tx_threshold_btc:
            return

        self._filtered_count += 1
        logger.debug(
            "Large transaction detected",
            txid=tx.txid,
            value_btc=tx.total_value_out_btc,
            outputs=len(tx.vout),
        )

        # Publish to message queue
        if self.message_queue:
            await self.message_queue.publish(
                "normalized_tx",
                tx.model_dump(mode="json"),
            )

    async def _process_raw_block(self, raw_bytes: bytes) -> None:
        """Process a raw block (for logging/tracking)."""
        # Just log that a new block was received
        # Full block parsing is expensive and not needed for V1
        logger.info("New block received", size_bytes=len(raw_bytes))

    async def _log_stats(self) -> None:
        """Periodically log statistics."""
        while self._running:
            await asyncio.sleep(60)
            logger.info(
                "ZMQ listener stats",
                total_tx_seen=self._tx_count,
                filtered_large_tx=self._filtered_count,
                threshold_btc=self.min_tx_threshold_btc,
            )


def main() -> None:
    """Main entry point for the ZMQ listener service."""
    settings = get_settings()
    setup_logging(settings.log_level, json_output=settings.environment != "development")

    logger.info("Starting TBWI ZMQ Listener Service")

    listener = ZMQListener()

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
