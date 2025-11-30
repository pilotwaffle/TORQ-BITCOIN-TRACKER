"""
Event Engine for TBWI.

Clusters classified transactions into whale events based on
time windows, entity grouping, and transaction types.
"""

from __future__ import annotations

import asyncio
import signal
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from tbwi.config import get_settings
from tbwi.db.repository import TransactionRepository, WhaleEventRepository
from tbwi.db.session import get_db_session, init_db
from tbwi.logging import get_logger, setup_logging
from tbwi.models.schemas import (
    ClassifiedTransaction,
    EventEntity,
    TransactionType,
    WhaleEvent,
    WhaleEventType,
)
from tbwi.services.message_queue import get_message_queue, close_message_queue
from tbwi.services.price_oracle import get_price_oracle, close_price_oracle

logger = get_logger(__name__)


class EventEngine:
    """
    Event engine for whale detection.

    Monitors classified transactions and generates whale events
    when clustering criteria are met.
    """

    def __init__(self):
        settings = get_settings()
        self.network = settings.bitcoin.network

        # Thresholds from config
        self.single_deposit_btc = settings.thresholds.single_deposit_btc
        self.deposit_burst_min_count = settings.thresholds.deposit_burst_min_count
        self.deposit_burst_min_btc = settings.thresholds.deposit_burst_min_btc
        self.deposit_burst_window = timedelta(
            minutes=settings.thresholds.deposit_burst_window_minutes
        )
        self.outflow_min_count = settings.thresholds.outflow_min_count
        self.outflow_min_btc = settings.thresholds.outflow_min_btc
        self.outflow_window = timedelta(
            minutes=settings.thresholds.outflow_window_minutes
        )

        self._running = False
        self._event_count = 0

        # In-memory buffer for clustering
        # Key: (entity_label, tx_type) -> list of transactions
        self._tx_buffer: dict[tuple[str, str], list[ClassifiedTransaction]] = defaultdict(list)
        self._buffer_lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the event engine."""
        logger.info(
            "Starting Event Engine",
            network=self.network,
            single_deposit_threshold=self.single_deposit_btc,
            deposit_burst_window_minutes=self.deposit_burst_window.total_seconds() / 60,
        )

        # Initialize database
        await init_db()

        # Connect to message queue
        mq = await get_message_queue()

        # Subscribe to classified transactions
        await mq.subscribe("classified_tx", self._process_transaction)

        self._running = True

        # Start tasks
        await asyncio.gather(
            mq.consume(
                "classified_tx",
                consumer_group="event-engine",
                consumer_name="engine-1",
            ),
            self._periodic_clustering(),
        )

    async def stop(self) -> None:
        """Stop the event engine."""
        logger.info("Stopping Event Engine")
        self._running = False

        mq = await get_message_queue()
        mq.stop()

        await close_message_queue()
        await close_price_oracle()

        logger.info("Event Engine stopped", event_count=self._event_count)

    async def _process_transaction(self, message: dict[str, Any]) -> None:
        """Process a classified transaction message."""
        try:
            tx = ClassifiedTransaction.model_validate(message)

            # Check for single large events first
            event = await self._check_single_event(tx)
            if event:
                await self._save_and_publish_event(event)

            # Add to buffer for burst/cluster detection
            await self._add_to_buffer(tx)

        except Exception as e:
            logger.error("Error processing transaction", error=str(e))

    async def _check_single_event(
        self, tx: ClassifiedTransaction
    ) -> WhaleEvent | None:
        """Check if transaction alone triggers a whale event."""
        # Single massive deposit
        if (
            TransactionType.EXCHANGE_DEPOSIT_CANDIDATE in tx.types
            and tx.total_value_out_btc >= self.single_deposit_btc
        ):
            # Find the exchange entity
            exchange_entities = [
                EventEntity(
                    label=out.entity_label,
                    category=out.entity_category or "exchange",
                    confidence=1.0,
                )
                for out in tx.outputs
                if out.entity_category and "exchange" in out.entity_category.lower()
            ]

            if exchange_entities:
                entity_names = ", ".join(e.label for e in exchange_entities)
                return WhaleEvent(
                    event_id=uuid4(),
                    window_start=tx.seen_at,
                    window_end=tx.seen_at,
                    network=tx.network,
                    event_type=WhaleEventType.WH_EXCHANGE_SINGLE_DEPOSIT,
                    entities=exchange_entities,
                    total_value_btc=tx.total_value_out_btc,
                    total_value_usd=tx.total_value_usd,
                    txids=[tx.txid],
                    summary=f"Massive deposit of {tx.total_value_out_btc:,.2f} BTC to {entity_names}",
                )

        # Single massive withdrawal
        if (
            TransactionType.EXCHANGE_WITHDRAWAL_CANDIDATE in tx.types
            and tx.total_value_out_btc >= self.single_deposit_btc
        ):
            exchange_entities = [
                EventEntity(
                    label=inp.entity_label,
                    category=inp.entity_category or "exchange",
                    confidence=1.0,
                )
                for inp in tx.inputs
                if inp.entity_category and "exchange" in inp.entity_category.lower()
            ]

            if exchange_entities:
                entity_names = ", ".join(e.label for e in exchange_entities)
                return WhaleEvent(
                    event_id=uuid4(),
                    window_start=tx.seen_at,
                    window_end=tx.seen_at,
                    network=tx.network,
                    event_type=WhaleEventType.WH_EXCHANGE_SINGLE_WITHDRAWAL,
                    entities=exchange_entities,
                    total_value_btc=tx.total_value_out_btc,
                    total_value_usd=tx.total_value_usd,
                    txids=[tx.txid],
                    summary=f"Massive withdrawal of {tx.total_value_out_btc:,.2f} BTC from {entity_names}",
                )

        # Large OTC move
        if (
            TransactionType.OTC_LIKE_MOVE_CANDIDATE in tx.types
            and tx.total_value_out_btc >= self.single_deposit_btc
        ):
            return WhaleEvent(
                event_id=uuid4(),
                window_start=tx.seen_at,
                window_end=tx.seen_at,
                network=tx.network,
                event_type=WhaleEventType.WH_OTC_LARGE_MOVE,
                entities=[],
                total_value_btc=tx.total_value_out_btc,
                total_value_usd=tx.total_value_usd,
                txids=[tx.txid],
                summary=f"Large OTC-like movement of {tx.total_value_out_btc:,.2f} BTC",
            )

        return None

    async def _add_to_buffer(self, tx: ClassifiedTransaction) -> None:
        """Add transaction to clustering buffer."""
        async with self._buffer_lock:
            # Group by entity and type
            for out in tx.outputs:
                if out.entity_label != "Unknown":
                    for tx_type in tx.types:
                        key = (out.entity_label, tx_type.value)
                        self._tx_buffer[key].append(tx)

            # Also group by primary type for unknown entities
            if all(out.entity_label == "Unknown" for out in tx.outputs):
                key = ("Unknown", tx.primary_type.value)
                self._tx_buffer[key].append(tx)

    async def _periodic_clustering(self) -> None:
        """Periodically check for burst events."""
        while self._running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                await self._check_bursts()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in periodic clustering", error=str(e))

    async def _check_bursts(self) -> None:
        """Check for burst events in the buffer."""
        now = datetime.utcnow()

        async with self._buffer_lock:
            keys_to_clean = []

            for key, transactions in self._tx_buffer.items():
                entity_label, tx_type = key

                # Filter to transactions within the window
                window_start = now - self.deposit_burst_window
                recent_txs = [
                    tx for tx in transactions if tx.seen_at >= window_start
                ]

                # Clean old transactions
                self._tx_buffer[key] = recent_txs

                if not recent_txs:
                    keys_to_clean.append(key)
                    continue

                # Check for deposit burst
                if tx_type == TransactionType.EXCHANGE_DEPOSIT_CANDIDATE.value:
                    event = self._check_deposit_burst(
                        entity_label, recent_txs, window_start, now
                    )
                    if event:
                        # Check for duplicates
                        async with get_db_session() as session:
                            repo = WhaleEventRepository(session)
                            is_dup = await repo.check_duplicate(
                                event.event_type,
                                event.network,
                                event.window_start,
                                event.window_end,
                                event.txids,
                            )
                            if not is_dup:
                                await self._save_and_publish_event(event)
                                # Clear processed transactions
                                self._tx_buffer[key] = []

                # Check for outflow burst
                if tx_type == TransactionType.EXCHANGE_WITHDRAWAL_CANDIDATE.value:
                    window_start_outflow = now - self.outflow_window
                    outflow_txs = [
                        tx for tx in recent_txs if tx.seen_at >= window_start_outflow
                    ]
                    event = self._check_outflow_burst(
                        entity_label, outflow_txs, window_start_outflow, now
                    )
                    if event:
                        async with get_db_session() as session:
                            repo = WhaleEventRepository(session)
                            is_dup = await repo.check_duplicate(
                                event.event_type,
                                event.network,
                                event.window_start,
                                event.window_end,
                                event.txids,
                            )
                            if not is_dup:
                                await self._save_and_publish_event(event)
                                self._tx_buffer[key] = []

            # Clean empty keys
            for key in keys_to_clean:
                del self._tx_buffer[key]

    def _check_deposit_burst(
        self,
        entity_label: str,
        transactions: list[ClassifiedTransaction],
        window_start: datetime,
        window_end: datetime,
    ) -> WhaleEvent | None:
        """Check if transactions form a deposit burst."""
        if len(transactions) < self.deposit_burst_min_count:
            return None

        total_btc = sum(tx.total_value_out_btc for tx in transactions)
        if total_btc < self.deposit_burst_min_btc:
            return None

        total_usd = sum(
            tx.total_value_usd for tx in transactions if tx.total_value_usd
        ) or None

        return WhaleEvent(
            event_id=uuid4(),
            window_start=min(tx.seen_at for tx in transactions),
            window_end=max(tx.seen_at for tx in transactions),
            network=self.network,
            event_type=WhaleEventType.WH_EXCHANGE_DEPOSIT_BURST,
            entities=[
                EventEntity(
                    label=entity_label,
                    category="exchange",
                    confidence=0.9,
                )
            ],
            total_value_btc=total_btc,
            total_value_usd=total_usd,
            txids=[tx.txid for tx in transactions],
            summary=f"{entity_label} received {total_btc:,.2f} BTC across {len(transactions)} whale-sized deposits in {int((window_end - window_start).total_seconds() / 60)} minutes",
        )

    def _check_outflow_burst(
        self,
        entity_label: str,
        transactions: list[ClassifiedTransaction],
        window_start: datetime,
        window_end: datetime,
    ) -> WhaleEvent | None:
        """Check if transactions form an outflow burst."""
        if len(transactions) < self.outflow_min_count:
            return None

        total_btc = sum(tx.total_value_out_btc for tx in transactions)
        if total_btc < self.outflow_min_btc:
            return None

        total_usd = sum(
            tx.total_value_usd for tx in transactions if tx.total_value_usd
        ) or None

        return WhaleEvent(
            event_id=uuid4(),
            window_start=min(tx.seen_at for tx in transactions),
            window_end=max(tx.seen_at for tx in transactions),
            network=self.network,
            event_type=WhaleEventType.WH_EXCHANGE_BULK_OUTFLOW,
            entities=[
                EventEntity(
                    label=entity_label,
                    category="exchange",
                    confidence=0.9,
                )
            ],
            total_value_btc=total_btc,
            total_value_usd=total_usd,
            txids=[tx.txid for tx in transactions],
            summary=f"Bulk outflow of {total_btc:,.2f} BTC from {entity_label} across {len(transactions)} transactions in {int((window_end - window_start).total_seconds() / 60)} minutes",
        )

    async def _save_and_publish_event(self, event: WhaleEvent) -> None:
        """Save event to database and publish to queue."""
        try:
            # Save to database
            async with get_db_session() as session:
                repo = WhaleEventRepository(session)
                saved_event = await repo.create(event)

            self._event_count += 1
            logger.info(
                "Whale event created",
                event_id=str(event.event_id),
                event_type=event.event_type.value,
                total_btc=event.total_value_btc,
                tx_count=len(event.txids),
            )

            # Publish to event channel for webhook dispatcher
            mq = await get_message_queue()
            await mq.publish("whale_event", event.model_dump(mode="json"))

        except Exception as e:
            logger.error(
                "Failed to save/publish whale event",
                event_id=str(event.event_id),
                error=str(e),
            )


def main() -> None:
    """Main entry point for the event engine service."""
    settings = get_settings()
    setup_logging(settings.log_level, json_output=settings.environment != "development")

    logger.info("Starting TBWI Event Engine Service")

    engine = EventEngine()

    # Handle shutdown signals
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown(sig: signal.Signals) -> None:
        logger.info("Received shutdown signal", signal=sig.name)
        loop.create_task(engine.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: shutdown(s))

    try:
        loop.run_until_complete(engine.start())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        loop.run_until_complete(engine.stop())
        loop.close()


if __name__ == "__main__":
    main()
