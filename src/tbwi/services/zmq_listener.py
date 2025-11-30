"""
ZMQ Listener Service for Bitcoin Core.

Subscribes to Bitcoin Core's ZMQ stream for raw transactions and blocks.
Includes sequence number tracking, address extraction, and metrics.
"""

from __future__ import annotations

import asyncio
import hashlib
import signal
from datetime import datetime
from typing import Any

import zmq
import zmq.asyncio

from tbwi.config import get_settings
from tbwi.logging import get_logger, setup_logging
from tbwi.models.schemas import NormalizedTransaction, TransactionOutput
from tbwi.services.message_queue import MessageQueue, get_message_queue
from tbwi.services.metrics import (
    ZMQ_CONNECTION_STATUS,
    ZMQ_MESSAGES_RECEIVED,
    ZMQ_MESSAGES_MISSED,
    TX_PROCESSED,
    TX_FILTERED,
    TX_PARSE_ERRORS,
    TX_PROCESSING_TIME,
)

logger = get_logger(__name__)


# Satoshis per Bitcoin
SATOSHI_PER_BTC = 100_000_000

# Bech32 character set
BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

# Base58 character set
BASE58_CHARSET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _bech32_polymod(values: list[int]) -> int:
    """Internal function for bech32 checksum."""
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ value
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
    return chk


def _bech32_hrp_expand(hrp: str) -> list[int]:
    """Expand the HRP into values for checksum computation."""
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_create_checksum(hrp: str, data: list[int], spec: int) -> list[int]:
    """Compute the checksum values given HRP and data."""
    const = 0x2BC830A3 if spec else 1
    values = _bech32_hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ const
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def _convertbits(data: bytes, frombits: int, tobits: int, pad: bool = True) -> list[int] | None:
    """General power-of-2 base conversion."""
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def encode_bech32(hrp: str, witver: int, witprog: bytes) -> str | None:
    """Encode a segwit address."""
    spec = 1 if witver > 0 else 0  # bech32m for v1+, bech32 for v0
    five_bit = _convertbits(witprog, 8, 5)
    if five_bit is None:
        return None
    data = [witver] + five_bit
    checksum = _bech32_create_checksum(hrp, data, spec)
    return hrp + "1" + "".join([BECH32_CHARSET[d] for d in data + checksum])


def encode_base58check(payload: bytes) -> str:
    """Encode bytes to base58check."""
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    data = payload + checksum

    # Convert to base58
    n = int.from_bytes(data, "big")
    result = ""
    while n > 0:
        n, remainder = divmod(n, 58)
        result = BASE58_CHARSET[remainder] + result

    # Add leading zeros
    for byte in data:
        if byte == 0:
            result = "1" + result
        else:
            break

    return result


def extract_address_from_script(script_bytes: bytes, network: str) -> str | None:
    """
    Extract Bitcoin address from output script.

    Supports P2PKH, P2SH, P2WPKH, P2WSH, and P2TR (Taproot).

    Args:
        script_bytes: Raw script bytes
        network: Network name (mainnet, testnet, regtest)

    Returns:
        Bitcoin address string or None if extraction fails
    """
    if not script_bytes:
        return None

    # Determine network prefixes
    if network == "mainnet":
        hrp = "bc"
        p2pkh_prefix = b"\x00"
        p2sh_prefix = b"\x05"
    elif network == "testnet":
        hrp = "tb"
        p2pkh_prefix = b"\x6f"
        p2sh_prefix = b"\xc4"
    else:  # regtest
        hrp = "bcrt"
        p2pkh_prefix = b"\x6f"
        p2sh_prefix = b"\xc4"

    try:
        # P2PKH: OP_DUP OP_HASH160 <20 bytes> OP_EQUALVERIFY OP_CHECKSIG
        # 76 a9 14 <20 bytes> 88 ac
        if len(script_bytes) == 25 and script_bytes[0] == 0x76 and script_bytes[1] == 0xa9:
            pubkey_hash = script_bytes[3:23]
            return encode_base58check(p2pkh_prefix + pubkey_hash)

        # P2SH: OP_HASH160 <20 bytes> OP_EQUAL
        # a9 14 <20 bytes> 87
        if len(script_bytes) == 23 and script_bytes[0] == 0xa9 and script_bytes[1] == 0x14:
            script_hash = script_bytes[2:22]
            return encode_base58check(p2sh_prefix + script_hash)

        # P2WPKH: OP_0 <20 bytes>
        # 00 14 <20 bytes>
        if len(script_bytes) == 22 and script_bytes[0] == 0x00 and script_bytes[1] == 0x14:
            witprog = script_bytes[2:22]
            return encode_bech32(hrp, 0, witprog)

        # P2WSH: OP_0 <32 bytes>
        # 00 20 <32 bytes>
        if len(script_bytes) == 34 and script_bytes[0] == 0x00 and script_bytes[1] == 0x20:
            witprog = script_bytes[2:34]
            return encode_bech32(hrp, 0, witprog)

        # P2TR (Taproot): OP_1 <32 bytes>
        # 51 20 <32 bytes>
        if len(script_bytes) == 34 and script_bytes[0] == 0x51 and script_bytes[1] == 0x20:
            witprog = script_bytes[2:34]
            return encode_bech32(hrp, 1, witprog)

        return None
    except Exception:
        return None


def parse_raw_transaction(raw_bytes: bytes, network: str) -> NormalizedTransaction | None:
    """
    Parse a raw transaction from bytes.

    Args:
        raw_bytes: Raw transaction bytes from ZMQ
        network: Bitcoin network (mainnet, testnet, regtest)

    Returns:
        NormalizedTransaction if parsing succeeds, None otherwise
    """
    import time
    start_time = time.perf_counter()

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

            # Extract address from script
            script_bytes = bytes(output.scriptPubKey)
            script_type = _get_script_type(script_bytes)
            address = extract_address_from_script(script_bytes, network)

            vout.append(
                TransactionOutput(
                    index=idx,
                    value_btc=value_satoshi / SATOSHI_PER_BTC,
                    script_type=script_type,
                    address=address,
                )
            )

        elapsed = time.perf_counter() - start_time
        TX_PROCESSING_TIME.observe(elapsed)

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
        TX_PARSE_ERRORS.inc()
        logger.warning("Failed to parse raw transaction", error=str(e))
        return None


def _get_script_type(script_bytes: bytes) -> str | None:
    """Determine script type from raw bytes."""
    if not script_bytes:
        return None

    try:
        # P2PKH: OP_DUP OP_HASH160 <20 bytes> OP_EQUALVERIFY OP_CHECKSIG
        if len(script_bytes) == 25 and script_bytes[0] == 0x76:
            return "p2pkh"

        # P2SH: OP_HASH160 <20 bytes> OP_EQUAL
        if len(script_bytes) == 23 and script_bytes[0] == 0xa9:
            return "p2sh"

        # P2WPKH: OP_0 <20 bytes>
        if len(script_bytes) == 22 and script_bytes[0] == 0x00:
            return "p2wpkh"

        # P2WSH: OP_0 <32 bytes>
        if len(script_bytes) == 34 and script_bytes[0] == 0x00:
            return "p2wsh"

        # P2TR (Taproot): OP_1 <32 bytes>
        if len(script_bytes) == 34 and script_bytes[0] == 0x51:
            return "p2tr"

        return "unknown"
    except Exception:
        return None


class ZMQListener:
    """
    ZMQ Listener for Bitcoin Core.

    Subscribes to raw transaction and block topics and processes them.
    Includes sequence number tracking for message loss detection.
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

        # Sequence number tracking for message loss detection
        self._last_tx_seq: int | None = None
        self._last_block_seq: int | None = None
        self._missed_tx_count = 0
        self._missed_block_count = 0

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

        # Subscribe to raw transactions with optimized buffer settings
        self._tx_socket = self._context.socket(zmq.SUB)

        # Set high water mark for receive buffer (number of messages)
        self._tx_socket.setsockopt(zmq.RCVHWM, 100000)
        # Set receive buffer size (1MB)
        self._tx_socket.setsockopt(zmq.RCVBUF, 1024 * 1024)
        # Enable TCP keepalive
        self._tx_socket.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self._tx_socket.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 60)

        self._tx_socket.connect(self.tx_endpoint)
        self._tx_socket.setsockopt(zmq.SUBSCRIBE, b"rawtx")

        # Subscribe to raw blocks with optimized settings
        self._block_socket = self._context.socket(zmq.SUB)
        self._block_socket.setsockopt(zmq.RCVHWM, 1000)
        self._block_socket.setsockopt(zmq.RCVBUF, 4 * 1024 * 1024)  # 4MB for blocks
        self._block_socket.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self._block_socket.connect(self.block_endpoint)
        self._block_socket.setsockopt(zmq.SUBSCRIBE, b"rawblock")

        self._running = True
        ZMQ_CONNECTION_STATUS.labels(endpoint="tx").set(1)
        ZMQ_CONNECTION_STATUS.labels(endpoint="block").set(1)
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

        ZMQ_CONNECTION_STATUS.labels(endpoint="tx").set(0)
        ZMQ_CONNECTION_STATUS.labels(endpoint="block").set(0)

        if self._tx_socket:
            self._tx_socket.close()
        if self._block_socket:
            self._block_socket.close()
        if self._context:
            self._context.term()

        logger.info(
            "ZMQ listener stopped",
            total_tx=self._tx_count,
            filtered_tx=self._filtered_count,
            missed_tx=self._missed_tx_count,
            missed_blocks=self._missed_block_count,
        )

    async def _listen_transactions(self) -> None:
        """Listen for raw transactions with sequence tracking."""
        while self._running:
            try:
                # Non-blocking receive with timeout
                if self._tx_socket.poll(timeout=1000):
                    msg = await self._tx_socket.recv_multipart()

                    # Bitcoin Core sends: [topic, body, sequence]
                    if len(msg) >= 3:
                        topic = msg[0]
                        raw_tx = msg[1]
                        seq_bytes = msg[2]

                        # Parse sequence number (4-byte little-endian)
                        seq_num = int.from_bytes(seq_bytes, "little")

                        # Check for missed messages
                        if self._last_tx_seq is not None:
                            expected = (self._last_tx_seq + 1) & 0xFFFFFFFF
                            if seq_num != expected:
                                missed = (seq_num - expected) & 0xFFFFFFFF
                                self._missed_tx_count += missed
                                ZMQ_MESSAGES_MISSED.labels(topic="rawtx").inc(missed)
                                logger.warning(
                                    "Missed ZMQ transaction messages",
                                    expected_seq=expected,
                                    received_seq=seq_num,
                                    missed_count=missed,
                                )
                        self._last_tx_seq = seq_num

                        if topic == b"rawtx":
                            ZMQ_MESSAGES_RECEIVED.labels(topic="rawtx").inc()
                            await self._process_raw_transaction(raw_tx)
                    elif len(msg) >= 2:
                        # Fallback for older Bitcoin Core versions without sequence
                        topic = msg[0]
                        raw_tx = msg[1]
                        if topic == b"rawtx":
                            ZMQ_MESSAGES_RECEIVED.labels(topic="rawtx").inc()
                            await self._process_raw_transaction(raw_tx)

            except zmq.ZMQError as e:
                if self._running:
                    ZMQ_CONNECTION_STATUS.labels(endpoint="tx").set(0)
                    logger.error("ZMQ error receiving transaction", error=str(e))
                    await asyncio.sleep(1)
                    ZMQ_CONNECTION_STATUS.labels(endpoint="tx").set(1)
            except Exception as e:
                logger.error("Error processing transaction", error=str(e))

    async def _listen_blocks(self) -> None:
        """Listen for raw blocks with sequence tracking."""
        while self._running:
            try:
                if self._block_socket.poll(timeout=1000):
                    msg = await self._block_socket.recv_multipart()

                    if len(msg) >= 3:
                        topic = msg[0]
                        raw_block = msg[1]
                        seq_bytes = msg[2]

                        seq_num = int.from_bytes(seq_bytes, "little")

                        if self._last_block_seq is not None:
                            expected = (self._last_block_seq + 1) & 0xFFFFFFFF
                            if seq_num != expected:
                                missed = (seq_num - expected) & 0xFFFFFFFF
                                self._missed_block_count += missed
                                ZMQ_MESSAGES_MISSED.labels(topic="rawblock").inc(missed)
                                logger.warning(
                                    "Missed ZMQ block messages",
                                    expected_seq=expected,
                                    received_seq=seq_num,
                                    missed_count=missed,
                                )
                        self._last_block_seq = seq_num

                        if topic == b"rawblock":
                            ZMQ_MESSAGES_RECEIVED.labels(topic="rawblock").inc()
                            await self._process_raw_block(raw_block)
                    elif len(msg) >= 2:
                        topic = msg[0]
                        raw_block = msg[1]
                        if topic == b"rawblock":
                            ZMQ_MESSAGES_RECEIVED.labels(topic="rawblock").inc()
                            await self._process_raw_block(raw_block)

            except zmq.ZMQError as e:
                if self._running:
                    ZMQ_CONNECTION_STATUS.labels(endpoint="block").set(0)
                    logger.error("ZMQ error receiving block", error=str(e))
                    await asyncio.sleep(1)
                    ZMQ_CONNECTION_STATUS.labels(endpoint="block").set(1)
            except Exception as e:
                logger.error("Error processing block", error=str(e))

    async def _process_raw_transaction(self, raw_bytes: bytes) -> None:
        """Process a raw transaction."""
        self._tx_count += 1
        TX_PROCESSED.inc()

        # Parse the transaction
        tx = parse_raw_transaction(raw_bytes, self.network)
        if tx is None:
            return

        # Apply minimum threshold filter
        if tx.total_value_out_btc < self.min_tx_threshold_btc:
            return

        self._filtered_count += 1
        TX_FILTERED.inc()

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
                missed_tx_messages=self._missed_tx_count,
                missed_block_messages=self._missed_block_count,
            )


def main() -> None:
    """Main entry point for the ZMQ listener service."""
    settings = get_settings()
    setup_logging(settings.log_level, json_output=settings.environment != "development")

    logger.info("Starting TBWI ZMQ Listener Service")

    # Start metrics server
    from tbwi.services.metrics import start_metrics_server
    start_metrics_server(port=9090)

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
