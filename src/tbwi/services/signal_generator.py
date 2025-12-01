"""
Trading Signal Generator for TBWI.

Transforms raw whale events and classified transactions into actionable
trading signals with clear BULLISH/BEARISH/NEUTRAL direction.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from uuid import uuid4

import structlog

from tbwi.models.schemas import (
    ClassifiedTransaction,
    SignalDirection,
    SignalSeverity,
    TradingSignal,
    TransactionType,
    WhaleEvent,
    WhaleEventType,
)

logger = structlog.get_logger(__name__)


# Signal interpretation templates
INTERPRETATIONS = {
    "exchange_deposit": (
        "Large deposit to {entity} exchange - whale likely preparing to sell. "
        "Historical data shows 70% of large exchange deposits result in sells within 24-72h."
    ),
    "exchange_deposit_burst": (
        "Multiple large deposits to {entity} in {minutes} minutes - coordinated sell preparation. "
        "This pattern often precedes significant price drops within 6-24h."
    ),
    "exchange_withdrawal": (
        "Large withdrawal from {entity} - whale moving to cold storage. "
        "This indicates accumulation/HODL behavior, reducing exchange supply."
    ),
    "exchange_bulk_outflow": (
        "Mass withdrawals from {entity} - significant supply leaving exchange. "
        "Reduced exchange supply typically supports price stability or increases."
    ),
    "otc_move": (
        "Large OTC-style transfer detected - off-exchange transaction. "
        "These don't directly impact order books but indicate institutional activity."
    ),
    "programmatic_split": (
        "Programmatic distribution detected - {count} identical outputs of {amount} BTC. "
        "Likely institutional allocation, custodial restructuring, or payout preparation."
    ),
    "consolidation": (
        "Wallet consolidation - {inputs} inputs merged. "
        "Often precedes large moves; watch for follow-up transactions."
    ),
    "unknown_large": (
        "Large unidentified whale movement. Unable to determine intent without "
        "entity identification. Monitor for follow-up activity."
    ),
}

# Suggested actions
ACTIONS = {
    "bearish_high": "Consider reducing long exposure or tightening stop-losses. High-confidence sell signal.",
    "bearish_medium": "Monitor closely. Consider partial position reduction if price confirms weakness.",
    "bearish_low": "Note the activity. No immediate action required unless combined with other signals.",
    "bullish_high": "Supply leaving exchanges - supports price. Consider maintaining or adding to positions.",
    "bullish_medium": "Accumulation signal. Watch for confirmation before adding exposure.",
    "bullish_low": "Minor positive signal. Continue monitoring.",
    "neutral": "Off-book activity. No direct order book impact. Continue normal monitoring.",
}


class SignalGenerator:
    """
    Generates actionable trading signals from whale activity.

    Analyzes:
    - Individual classified transactions
    - Clustered whale events
    - Time-windowed patterns (deposit bursts, etc.)
    """

    def __init__(
        self,
        burst_window_minutes: int = 15,
        high_value_threshold_btc: float = 1000,
        critical_value_threshold_btc: float = 5000,
    ):
        self.burst_window_minutes = burst_window_minutes
        self.high_value_threshold = high_value_threshold_btc
        self.critical_value_threshold = critical_value_threshold_btc

        # Track recent transactions for burst detection
        self.recent_deposits: dict[str, list[ClassifiedTransaction]] = defaultdict(list)
        self.recent_withdrawals: dict[str, list[ClassifiedTransaction]] = defaultdict(list)

    def generate_signal_from_transaction(
        self, tx: ClassifiedTransaction
    ) -> TradingSignal | None:
        """
        Generate a trading signal from a single classified transaction.

        Returns None if the transaction doesn't warrant a signal.
        """
        if not tx.types:
            return None

        primary_type = tx.primary_type
        btc_value = tx.total_value_out_btc
        usd_value = tx.total_value_usd

        # Determine primary entity
        primary_entity = self._get_primary_entity(tx)

        # Track for burst detection
        self._track_transaction(tx, primary_entity)

        # Check for burst patterns first (higher priority)
        burst_signal = self._check_for_burst(tx, primary_entity)
        if burst_signal:
            return burst_signal

        # Generate signal based on transaction type
        if primary_type == TransactionType.EXCHANGE_DEPOSIT_CANDIDATE:
            return self._create_deposit_signal(tx, primary_entity)

        elif primary_type == TransactionType.EXCHANGE_WITHDRAWAL_CANDIDATE:
            return self._create_withdrawal_signal(tx, primary_entity)

        elif primary_type == TransactionType.PROGRAMMATIC_SPLIT:
            return self._create_programmatic_signal(tx, primary_entity)

        elif primary_type == TransactionType.CONSOLIDATION:
            return self._create_consolidation_signal(tx, primary_entity)

        elif primary_type == TransactionType.OTC_LIKE_MOVE_CANDIDATE:
            return self._create_otc_signal(tx, primary_entity)

        elif primary_type in (TransactionType.LARGE_SINGLE_OUTPUT, TransactionType.LARGE_MULTI_OUTPUT):
            # Only signal if value is significant
            if btc_value >= self.high_value_threshold:
                return self._create_unknown_signal(tx, primary_entity)

        return None

    def generate_signal_from_event(self, event: WhaleEvent) -> TradingSignal:
        """Generate a trading signal from a whale event."""
        event_type = event.event_type
        btc_value = event.total_value_btc
        usd_value = event.total_value_usd

        # Get primary entity from event
        primary_entity = event.entities[0].label if event.entities else "Unknown"

        if event_type == WhaleEventType.WH_EXCHANGE_SINGLE_DEPOSIT:
            return self._signal_from_deposit_event(event, primary_entity)

        elif event_type == WhaleEventType.WH_EXCHANGE_DEPOSIT_BURST:
            return self._signal_from_burst_event(event, primary_entity)

        elif event_type == WhaleEventType.WH_EXCHANGE_SINGLE_WITHDRAWAL:
            return self._signal_from_withdrawal_event(event, primary_entity)

        elif event_type == WhaleEventType.WH_EXCHANGE_BULK_OUTFLOW:
            return self._signal_from_outflow_event(event, primary_entity)

        elif event_type == WhaleEventType.WH_OTC_LARGE_MOVE:
            return self._signal_from_otc_event(event, primary_entity)

        else:
            return self._signal_from_unknown_event(event, primary_entity)

    def _get_primary_entity(self, tx: ClassifiedTransaction) -> str:
        """Extract primary entity from transaction."""
        # Check outputs first (for deposits)
        for out in tx.outputs:
            if out.entity_label and out.entity_label != "Unknown":
                return out.entity_label

        # Check inputs (for withdrawals)
        for inp in tx.inputs:
            if inp.entity_label and inp.entity_label != "Unknown":
                return inp.entity_label

        return "Unknown"

    def _track_transaction(self, tx: ClassifiedTransaction, entity: str) -> None:
        """Track transaction for burst detection."""
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=self.burst_window_minutes)

        if tx.primary_type == TransactionType.EXCHANGE_DEPOSIT_CANDIDATE:
            # Clean old entries
            self.recent_deposits[entity] = [
                t for t in self.recent_deposits[entity]
                if t.timestamp > cutoff
            ]
            self.recent_deposits[entity].append(tx)

        elif tx.primary_type == TransactionType.EXCHANGE_WITHDRAWAL_CANDIDATE:
            self.recent_withdrawals[entity] = [
                t for t in self.recent_withdrawals[entity]
                if t.timestamp > cutoff
            ]
            self.recent_withdrawals[entity].append(tx)

    def _check_for_burst(
        self, tx: ClassifiedTransaction, entity: str
    ) -> TradingSignal | None:
        """Check if this transaction is part of a burst pattern."""
        if tx.primary_type == TransactionType.EXCHANGE_DEPOSIT_CANDIDATE:
            recent = self.recent_deposits.get(entity, [])
            if len(recent) >= 3:  # Burst threshold
                return self._create_burst_signal(recent, entity, "deposit")

        elif tx.primary_type == TransactionType.EXCHANGE_WITHDRAWAL_CANDIDATE:
            recent = self.recent_withdrawals.get(entity, [])
            if len(recent) >= 3:
                return self._create_burst_signal(recent, entity, "withdrawal")

        return None

    def _create_deposit_signal(
        self, tx: ClassifiedTransaction, entity: str
    ) -> TradingSignal:
        """Create bearish signal for exchange deposit."""
        btc = tx.total_value_out_btc
        usd = tx.total_value_usd
        severity = self._calculate_severity(btc)
        confidence = self._calculate_confidence(tx, "deposit")

        usd_str = f" (${usd/1e6:.1f}M)" if usd else ""

        return TradingSignal(
            signal=SignalDirection.BEARISH,
            confidence=confidence,
            severity=severity,
            summary=f"{btc:,.0f} BTC{usd_str} deposited to {entity}",
            interpretation=INTERPRETATIONS["exchange_deposit"].format(entity=entity),
            suggested_action=ACTIONS[f"bearish_{severity.value.lower()}"],
            total_btc=btc,
            total_usd=usd,
            time_window_minutes=0,
            event_count=1,
            primary_entity=entity,
            txids=[tx.txid],
        )

    def _create_withdrawal_signal(
        self, tx: ClassifiedTransaction, entity: str
    ) -> TradingSignal:
        """Create bullish signal for exchange withdrawal."""
        btc = tx.total_value_out_btc
        usd = tx.total_value_usd
        severity = self._calculate_severity(btc)
        confidence = self._calculate_confidence(tx, "withdrawal")

        usd_str = f" (${usd/1e6:.1f}M)" if usd else ""

        return TradingSignal(
            signal=SignalDirection.BULLISH,
            confidence=confidence,
            severity=severity,
            summary=f"{btc:,.0f} BTC{usd_str} withdrawn from {entity}",
            interpretation=INTERPRETATIONS["exchange_withdrawal"].format(entity=entity),
            suggested_action=ACTIONS[f"bullish_{severity.value.lower()}"],
            total_btc=btc,
            total_usd=usd,
            time_window_minutes=0,
            event_count=1,
            primary_entity=entity,
            txids=[tx.txid],
        )

    def _create_burst_signal(
        self, transactions: list[ClassifiedTransaction], entity: str, direction: str
    ) -> TradingSignal:
        """Create high-severity signal for burst pattern."""
        total_btc = sum(t.total_value_out_btc for t in transactions)
        total_usd = sum(t.total_value_usd or 0 for t in transactions) or None

        timestamps = [t.timestamp for t in transactions]
        minutes = int((max(timestamps) - min(timestamps)).total_seconds() / 60) + 1

        usd_str = f" (${total_usd/1e9:.2f}B)" if total_usd and total_usd >= 1e9 else \
                  f" (${total_usd/1e6:.0f}M)" if total_usd else ""

        if direction == "deposit":
            return TradingSignal(
                signal=SignalDirection.BEARISH,
                confidence=0.90,  # High confidence for burst
                severity=SignalSeverity.CRITICAL if total_btc >= self.critical_value_threshold else SignalSeverity.HIGH,
                summary=f"{total_btc:,.0f} BTC{usd_str} moved to {entity} in {minutes} min ({len(transactions)} txs)",
                interpretation=INTERPRETATIONS["exchange_deposit_burst"].format(
                    entity=entity, minutes=minutes
                ),
                suggested_action=ACTIONS["bearish_high"],
                total_btc=total_btc,
                total_usd=total_usd,
                time_window_minutes=minutes,
                event_count=len(transactions),
                primary_entity=entity,
                txids=[t.txid for t in transactions],
            )
        else:  # withdrawal burst
            return TradingSignal(
                signal=SignalDirection.BULLISH,
                confidence=0.85,
                severity=SignalSeverity.HIGH if total_btc >= self.high_value_threshold else SignalSeverity.MEDIUM,
                summary=f"{total_btc:,.0f} BTC{usd_str} withdrawn from {entity} in {minutes} min ({len(transactions)} txs)",
                interpretation=INTERPRETATIONS["exchange_bulk_outflow"].format(entity=entity),
                suggested_action=ACTIONS["bullish_high"],
                total_btc=total_btc,
                total_usd=total_usd,
                time_window_minutes=minutes,
                event_count=len(transactions),
                primary_entity=entity,
                txids=[t.txid for t in transactions],
            )

    def _create_programmatic_signal(
        self, tx: ClassifiedTransaction, entity: str
    ) -> TradingSignal:
        """Create signal for programmatic split pattern."""
        btc = tx.total_value_out_btc
        usd = tx.total_value_usd

        # Count identical outputs
        from collections import Counter
        values = [round(o.value_btc, 8) for o in tx.outputs]
        value_counts = Counter(values)
        most_common_value, count = value_counts.most_common(1)[0]

        usd_str = f" (${usd/1e6:.1f}M)" if usd else ""

        return TradingSignal(
            signal=SignalDirection.NEUTRAL,
            confidence=0.75,
            severity=SignalSeverity.MEDIUM if btc >= self.high_value_threshold else SignalSeverity.LOW,
            summary=f"Programmatic split: {count}x {most_common_value:.2f} BTC outputs{usd_str}",
            interpretation=INTERPRETATIONS["programmatic_split"].format(
                count=count, amount=most_common_value
            ),
            suggested_action=ACTIONS["neutral"],
            total_btc=btc,
            total_usd=usd,
            time_window_minutes=0,
            event_count=1,
            primary_entity=entity if entity != "Unknown" else "Institutional",
            txids=[tx.txid],
        )

    def _create_consolidation_signal(
        self, tx: ClassifiedTransaction, entity: str
    ) -> TradingSignal:
        """Create signal for consolidation pattern."""
        btc = tx.total_value_out_btc
        usd = tx.total_value_usd
        input_count = len(tx.inputs) if tx.inputs else "multiple"

        usd_str = f" (${usd/1e6:.1f}M)" if usd else ""

        return TradingSignal(
            signal=SignalDirection.NEUTRAL,
            confidence=0.65,
            severity=SignalSeverity.LOW,
            summary=f"Wallet consolidation: {input_count} inputs → {len(tx.outputs)} outputs{usd_str}",
            interpretation=INTERPRETATIONS["consolidation"].format(inputs=input_count),
            suggested_action="Watch for follow-up large transaction within 24h.",
            total_btc=btc,
            total_usd=usd,
            time_window_minutes=0,
            event_count=1,
            primary_entity=entity,
            txids=[tx.txid],
        )

    def _create_otc_signal(
        self, tx: ClassifiedTransaction, entity: str
    ) -> TradingSignal:
        """Create signal for OTC-like move."""
        btc = tx.total_value_out_btc
        usd = tx.total_value_usd

        usd_str = f" (${usd/1e6:.1f}M)" if usd else ""

        return TradingSignal(
            signal=SignalDirection.NEUTRAL,
            confidence=0.70,
            severity=SignalSeverity.MEDIUM if btc >= self.high_value_threshold else SignalSeverity.LOW,
            summary=f"OTC-style move: {btc:,.0f} BTC{usd_str} single-output transfer",
            interpretation=INTERPRETATIONS["otc_move"],
            suggested_action=ACTIONS["neutral"],
            total_btc=btc,
            total_usd=usd,
            time_window_minutes=0,
            event_count=1,
            primary_entity="OTC/Unknown",
            txids=[tx.txid],
        )

    def _create_unknown_signal(
        self, tx: ClassifiedTransaction, entity: str
    ) -> TradingSignal:
        """Create signal for unidentified large move."""
        btc = tx.total_value_out_btc
        usd = tx.total_value_usd

        usd_str = f" (${usd/1e6:.1f}M)" if usd else ""

        return TradingSignal(
            signal=SignalDirection.NEUTRAL,
            confidence=0.50,
            severity=SignalSeverity.LOW,
            summary=f"Large whale move: {btc:,.0f} BTC{usd_str} - entity unknown",
            interpretation=INTERPRETATIONS["unknown_large"],
            suggested_action="Monitor for follow-up activity or entity identification.",
            total_btc=btc,
            total_usd=usd,
            time_window_minutes=0,
            event_count=1,
            primary_entity="Unknown",
            txids=[tx.txid],
        )

    def _signal_from_deposit_event(
        self, event: WhaleEvent, entity: str
    ) -> TradingSignal:
        """Convert deposit whale event to signal."""
        severity = self._calculate_severity(event.total_value_btc)

        return TradingSignal(
            signal=SignalDirection.BEARISH,
            confidence=0.80,
            severity=severity,
            summary=event.summary,
            interpretation=INTERPRETATIONS["exchange_deposit"].format(entity=entity),
            suggested_action=ACTIONS[f"bearish_{severity.value.lower()}"],
            total_btc=event.total_value_btc,
            total_usd=event.total_value_usd,
            time_window_minutes=int(
                (event.window_end - event.window_start).total_seconds() / 60
            ),
            event_count=len(event.txids),
            primary_entity=entity,
            raw_event_ids=[str(event.event_id)],
            txids=event.txids,
        )

    def _signal_from_burst_event(
        self, event: WhaleEvent, entity: str
    ) -> TradingSignal:
        """Convert burst whale event to high-severity signal."""
        minutes = int((event.window_end - event.window_start).total_seconds() / 60)

        return TradingSignal(
            signal=SignalDirection.BEARISH,
            confidence=0.90,
            severity=SignalSeverity.CRITICAL,
            summary=event.summary,
            interpretation=INTERPRETATIONS["exchange_deposit_burst"].format(
                entity=entity, minutes=minutes
            ),
            suggested_action=ACTIONS["bearish_high"],
            total_btc=event.total_value_btc,
            total_usd=event.total_value_usd,
            time_window_minutes=minutes,
            event_count=len(event.txids),
            primary_entity=entity,
            raw_event_ids=[str(event.event_id)],
            txids=event.txids,
        )

    def _signal_from_withdrawal_event(
        self, event: WhaleEvent, entity: str
    ) -> TradingSignal:
        """Convert withdrawal whale event to bullish signal."""
        severity = self._calculate_severity(event.total_value_btc)

        return TradingSignal(
            signal=SignalDirection.BULLISH,
            confidence=0.80,
            severity=severity,
            summary=event.summary,
            interpretation=INTERPRETATIONS["exchange_withdrawal"].format(entity=entity),
            suggested_action=ACTIONS[f"bullish_{severity.value.lower()}"],
            total_btc=event.total_value_btc,
            total_usd=event.total_value_usd,
            time_window_minutes=int(
                (event.window_end - event.window_start).total_seconds() / 60
            ),
            event_count=len(event.txids),
            primary_entity=entity,
            raw_event_ids=[str(event.event_id)],
            txids=event.txids,
        )

    def _signal_from_outflow_event(
        self, event: WhaleEvent, entity: str
    ) -> TradingSignal:
        """Convert bulk outflow event to bullish signal."""
        return TradingSignal(
            signal=SignalDirection.BULLISH,
            confidence=0.85,
            severity=SignalSeverity.HIGH,
            summary=event.summary,
            interpretation=INTERPRETATIONS["exchange_bulk_outflow"].format(entity=entity),
            suggested_action=ACTIONS["bullish_high"],
            total_btc=event.total_value_btc,
            total_usd=event.total_value_usd,
            time_window_minutes=int(
                (event.window_end - event.window_start).total_seconds() / 60
            ),
            event_count=len(event.txids),
            primary_entity=entity,
            raw_event_ids=[str(event.event_id)],
            txids=event.txids,
        )

    def _signal_from_otc_event(
        self, event: WhaleEvent, entity: str
    ) -> TradingSignal:
        """Convert OTC event to neutral signal."""
        return TradingSignal(
            signal=SignalDirection.NEUTRAL,
            confidence=0.70,
            severity=SignalSeverity.MEDIUM,
            summary=event.summary,
            interpretation=INTERPRETATIONS["otc_move"],
            suggested_action=ACTIONS["neutral"],
            total_btc=event.total_value_btc,
            total_usd=event.total_value_usd,
            time_window_minutes=int(
                (event.window_end - event.window_start).total_seconds() / 60
            ),
            event_count=len(event.txids),
            primary_entity="OTC/Unknown",
            raw_event_ids=[str(event.event_id)],
            txids=event.txids,
        )

    def _signal_from_unknown_event(
        self, event: WhaleEvent, entity: str
    ) -> TradingSignal:
        """Convert unknown whale event to neutral signal."""
        return TradingSignal(
            signal=SignalDirection.NEUTRAL,
            confidence=0.50,
            severity=SignalSeverity.LOW,
            summary=event.summary,
            interpretation=INTERPRETATIONS["unknown_large"],
            suggested_action="Monitor for follow-up activity.",
            total_btc=event.total_value_btc,
            total_usd=event.total_value_usd,
            time_window_minutes=int(
                (event.window_end - event.window_start).total_seconds() / 60
            ),
            event_count=len(event.txids),
            primary_entity=entity,
            raw_event_ids=[str(event.event_id)],
            txids=event.txids,
        )

    def _calculate_severity(self, btc_value: float) -> SignalSeverity:
        """Calculate severity based on BTC value."""
        if btc_value >= self.critical_value_threshold:
            return SignalSeverity.CRITICAL
        elif btc_value >= self.high_value_threshold:
            return SignalSeverity.HIGH
        elif btc_value >= 500:
            return SignalSeverity.MEDIUM
        else:
            return SignalSeverity.LOW

    def _calculate_confidence(
        self, tx: ClassifiedTransaction, signal_type: str
    ) -> float:
        """Calculate confidence based on entity identification and pattern clarity."""
        base_confidence = 0.70

        # Boost for known entity
        has_known_entity = any(
            o.entity_label != "Unknown" for o in tx.outputs
        ) or any(
            i.entity_label != "Unknown" for i in tx.inputs
        )
        if has_known_entity:
            base_confidence += 0.15

        # Boost for larger transactions (more likely intentional)
        if tx.total_value_out_btc >= 1000:
            base_confidence += 0.05

        # Boost for clear exchange category
        has_exchange_tag = any(
            o.entity_category and "exchange" in o.entity_category.lower()
            for o in tx.outputs
        ) or any(
            i.entity_category and "exchange" in i.entity_category.lower()
            for i in tx.inputs
        )
        if has_exchange_tag:
            base_confidence += 0.05

        return min(base_confidence, 0.95)
