"""
Transaction Classifier Service for TBWI.

Enriches and classifies normalized transactions from the ZMQ listener.
"""

from __future__ import annotations

import asyncio
import signal
from typing import Any

from tbwi.config import get_settings
from tbwi.db.repository import EntityTagRepository, TransactionRepository
from tbwi.db.session import get_db_session, init_db
from tbwi.logging import get_logger, setup_logging
from tbwi.models.schemas import (
    ClassifiedTransaction,
    EnrichedInput,
    EnrichedOutput,
    NormalizedTransaction,
    TransactionType,
)
from tbwi.services.bitcoin_rpc import close_rpc_client
from tbwi.services.message_queue import close_message_queue, get_message_queue
from tbwi.services.price_oracle import close_price_oracle, get_price_oracle

logger = get_logger(__name__)


class TransactionClassifier:
    """
    Transaction classifier and enricher.

    Takes normalized transactions, enriches them with entity tags and
    price data, then classifies them by type.
    """

    def __init__(self, large_tx_threshold_btc: float | None = None):
        settings = get_settings()
        self.large_tx_threshold = (
            large_tx_threshold_btc
            if large_tx_threshold_btc is not None
            else settings.thresholds.large_tx_btc
        )
        self.network = settings.bitcoin.network

        self._running = False
        self._processed_count = 0

    async def start(self) -> None:
        """Start the classifier service."""
        logger.info("Starting Transaction Classifier", threshold_btc=self.large_tx_threshold)

        # Initialize database
        await init_db()

        # Connect to message queue
        mq = await get_message_queue()

        # Subscribe to normalized transactions
        await mq.subscribe("normalized_tx", self._process_transaction)

        self._running = True

        # Start consuming
        await mq.consume(
            "normalized_tx",
            consumer_group="classifier",
            consumer_name="classifier-1",
        )

    async def stop(self) -> None:
        """Stop the classifier service."""
        logger.info("Stopping Transaction Classifier")
        self._running = False

        mq = await get_message_queue()
        mq.stop()

        await close_message_queue()
        await close_rpc_client()
        await close_price_oracle()

        logger.info(
            "Classifier stopped",
            processed_count=self._processed_count,
        )

    async def _process_transaction(self, message: dict[str, Any]) -> None:
        """Process a normalized transaction message."""
        try:
            # Parse normalized transaction
            tx = NormalizedTransaction.model_validate(message)

            # Classify the transaction
            classified = await self.classify(tx)

            if classified:
                # Store in database
                async with get_db_session() as session:
                    repo = TransactionRepository(session)

                    # Check if already processed
                    if not await repo.exists(classified.txid):
                        await repo.create(classified)
                        logger.info(
                            "Transaction classified",
                            txid=classified.txid,
                            type=classified.primary_type.value,
                            value_btc=classified.total_value_out_btc,
                            value_usd=classified.total_value_usd,
                        )

                        # Publish to classified_tx channel for event engine
                        mq = await get_message_queue()
                        await mq.publish(
                            "classified_tx",
                            classified.model_dump(mode="json"),
                        )

                self._processed_count += 1

        except Exception as e:
            logger.error("Error processing transaction", error=str(e))

    async def classify(
        self, tx: NormalizedTransaction
    ) -> ClassifiedTransaction | None:
        """
        Classify a normalized transaction.

        Args:
            tx: Normalized transaction from ZMQ listener

        Returns:
            Classified transaction or None if classification fails
        """
        try:
            # Get price for USD conversion
            price_oracle = get_price_oracle()
            btc_price = await price_oracle.get_btc_usd_price()
            total_value_usd = price_oracle.btc_to_usd(tx.total_value_out_btc, btc_price)

            # Enrich outputs with entity tags
            enriched_outputs = await self._enrich_outputs(tx)

            # Enrich inputs (requires RPC call)
            enriched_inputs = await self._enrich_inputs(tx)

            # Determine transaction types
            types = self._determine_types(
                tx, enriched_inputs, enriched_outputs
            )

            # Primary type is the first (most specific) type
            primary_type = types[0] if types else TransactionType.UNKNOWN_LARGE

            return ClassifiedTransaction(
                txid=tx.txid,
                seen_at=tx.seen_at,
                network=tx.network,
                total_value_out_btc=tx.total_value_out_btc,
                total_value_usd=total_value_usd,
                primary_type=primary_type,
                types=types,
                inputs=enriched_inputs,
                outputs=enriched_outputs,
                raw_hex=tx.raw_hex,
            )

        except Exception as e:
            logger.error("Classification failed", txid=tx.txid, error=str(e))
            return None

    async def _enrich_outputs(
        self, tx: NormalizedTransaction
    ) -> list[EnrichedOutput]:
        """Enrich transaction outputs with entity tags."""
        enriched: list[EnrichedOutput] = []

        # Collect addresses for batch lookup
        addresses = [
            out.address for out in tx.vout if out.address is not None
        ]

        # Batch lookup entity tags
        entity_tags: dict = {}
        if addresses:
            async with get_db_session() as session:
                repo = EntityTagRepository(session)
                entity_tags = await repo.get_by_addresses(addresses)

        for out in tx.vout:
            entity_label = "Unknown"
            entity_category = None

            if out.address and out.address in entity_tags:
                tag = entity_tags[out.address]
                entity_label = tag.label
                entity_category = tag.category.value

            enriched.append(
                EnrichedOutput(
                    index=out.index,
                    address=out.address,
                    value_btc=out.value_btc,
                    script_type=out.script_type,
                    entity_label=entity_label,
                    entity_category=entity_category,
                )
            )

        return enriched

    async def _enrich_inputs(
        self, tx: NormalizedTransaction
    ) -> list[EnrichedInput]:
        """
        Enrich transaction inputs.

        Note: This requires RPC calls to get input details.
        In high-volume scenarios, consider batching or caching.
        """
        enriched: list[EnrichedInput] = []

        # For V1, we skip deep input enrichment to avoid RPC overload
        # The event engine can request full enrichment when needed
        # This is a tradeoff between completeness and performance

        # If raw_hex is available, we could parse inputs locally
        # For now, just return empty inputs (will be enriched on demand)

        return enriched

    def _determine_types(
        self,
        tx: NormalizedTransaction,
        inputs: list[EnrichedInput],
        outputs: list[EnrichedOutput],
    ) -> list[TransactionType]:
        """
        Determine transaction classification types.

        Returns types in order of specificity (most specific first).
        """
        types: list[TransactionType] = []

        is_large = tx.total_value_out_btc >= self.large_tx_threshold

        # Check for exchange-related transactions
        has_exchange_output = any(
            out.entity_category
            and "exchange" in out.entity_category.lower()
            for out in outputs
        )
        has_exchange_input = any(
            inp.entity_category
            and "exchange" in inp.entity_category.lower()
            for inp in inputs
        )

        # Exchange deposit candidate
        if is_large and has_exchange_output and not has_exchange_input:
            types.append(TransactionType.EXCHANGE_DEPOSIT_CANDIDATE)

        # Exchange withdrawal candidate
        if is_large and has_exchange_input and not has_exchange_output:
            types.append(TransactionType.EXCHANGE_WITHDRAWAL_CANDIDATE)

        # OTC-like move (large, single output, no exchange tags)
        if is_large and len(outputs) == 1 and not has_exchange_output:
            types.append(TransactionType.OTC_LIKE_MOVE_CANDIDATE)

        # Large single output
        if is_large and len(outputs) == 1:
            types.append(TransactionType.LARGE_SINGLE_OUTPUT)

        # Large multi-output
        if is_large and len(outputs) > 1:
            types.append(TransactionType.LARGE_MULTI_OUTPUT)

        # Programmatic split detection (institutional pattern)
        # Triggered by: multiple identical output amounts OR multiple outputs to same address
        if is_large and len(outputs) >= 3:
            output_values = [round(out.value_btc, 8) for out in outputs]
            output_addresses = [out.address for out in outputs if out.address]

            # Check for identical output amounts (3+ outputs with same value)
            from collections import Counter

            value_counts = Counter(output_values)
            max_identical = max(value_counts.values()) if value_counts else 0

            # Check for same-address outputs (3+ outputs to same address)
            addr_counts = Counter(output_addresses)
            max_same_addr = max(addr_counts.values()) if addr_counts else 0

            if max_identical >= 3 or max_same_addr >= 3:
                types.insert(0, TransactionType.PROGRAMMATIC_SPLIT)  # High priority

        # Consolidation detection (many inputs → few outputs)
        if is_large and len(tx.outputs) <= 2 and len(inputs) >= 5:
            types.append(TransactionType.CONSOLIDATION)

        # Default for large transactions
        if is_large and not types:
            types.append(TransactionType.UNKNOWN_LARGE)

        return types


def main() -> None:
    """Main entry point for the classifier service."""
    settings = get_settings()
    setup_logging(settings.log_level, json_output=settings.environment != "development")

    logger.info("Starting TBWI Transaction Classifier Service")

    classifier = TransactionClassifier()

    # Handle shutdown signals
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown(sig: signal.Signals) -> None:
        logger.info("Received shutdown signal", signal=sig.name)
        loop.create_task(classifier.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: shutdown(s))

    try:
        loop.run_until_complete(classifier.start())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        loop.run_until_complete(classifier.stop())
        loop.close()


if __name__ == "__main__":
    main()
