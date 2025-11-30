"""
Anomaly detection service for TBWI.

Detects unusual patterns in Bitcoin whale activity including:
- Statistical outliers in transaction values
- Unusual exchange deposit/withdrawal patterns
- Sudden activity spikes
- Coordinated large movements
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Deque
from uuid import uuid4

from tbwi.logging import get_logger
from tbwi.models.schemas import ClassifiedTransaction, WhaleEvent, WhaleEventType
from tbwi.services.metrics import ANOMALIES_DETECTED

logger = get_logger(__name__)


class AnomalyType(str, Enum):
    """Types of anomalies detected."""

    STATISTICAL_OUTLIER = "statistical_outlier"  # Transaction value is extreme outlier
    DEPOSIT_SPIKE = "deposit_spike"  # Unusual spike in exchange deposits
    WITHDRAWAL_SPIKE = "withdrawal_spike"  # Unusual spike in exchange withdrawals
    VELOCITY_ANOMALY = "velocity_anomaly"  # Unusual transaction velocity
    COORDINATED_MOVEMENT = "coordinated_movement"  # Multiple large txs in short window
    DORMANT_WALLET_ACTIVATION = "dormant_wallet_activation"  # Large wallet wakes up
    UNUSUAL_TIME_PATTERN = "unusual_time_pattern"  # Activity at unusual times


class AnomalySeverity(str, Enum):
    """Severity levels for detected anomalies."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Anomaly:
    """Detected anomaly."""

    anomaly_id: str
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    detected_at: datetime
    description: str
    value_btc: float
    related_txids: list[str]
    related_events: list[str]
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "anomaly_id": self.anomaly_id,
            "anomaly_type": self.anomaly_type.value,
            "severity": self.severity.value,
            "detected_at": self.detected_at.isoformat(),
            "description": self.description,
            "value_btc": self.value_btc,
            "related_txids": self.related_txids,
            "related_events": self.related_events,
            "metadata": self.metadata,
        }


@dataclass
class RollingStats:
    """Rolling statistics for anomaly detection."""

    values: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    timestamps: Deque[datetime] = field(default_factory=lambda: deque(maxlen=1000))

    @property
    def mean(self) -> float:
        """Calculate mean of values."""
        if not self.values:
            return 0.0
        return sum(self.values) / len(self.values)

    @property
    def std(self) -> float:
        """Calculate standard deviation of values."""
        if len(self.values) < 2:
            return 0.0
        mean = self.mean
        variance = sum((x - mean) ** 2 for x in self.values) / len(self.values)
        return variance ** 0.5

    def add(self, value: float, timestamp: datetime | None = None) -> None:
        """Add a value to the rolling window."""
        self.values.append(value)
        self.timestamps.append(timestamp or datetime.utcnow())

    def is_outlier(self, value: float, z_threshold: float = 3.0) -> bool:
        """Check if value is a statistical outlier."""
        if len(self.values) < 10:
            return False
        std = self.std
        if std == 0:
            return False
        z_score = abs(value - self.mean) / std
        return z_score > z_threshold

    def get_velocity(self, window_minutes: int = 10) -> float:
        """Calculate transaction velocity (count per minute) in recent window."""
        if not self.timestamps:
            return 0.0
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        recent = sum(1 for ts in self.timestamps if ts > cutoff)
        return recent / window_minutes


class AnomalyDetector:
    """
    Detects anomalies in whale transaction and event patterns.

    Uses statistical methods and heuristics to identify unusual activity.
    """

    def __init__(
        self,
        z_score_threshold: float = 3.0,
        velocity_spike_multiplier: float = 3.0,
        coordinated_window_minutes: int = 5,
        min_coordinated_count: int = 3,
        min_history_size: int = 50,
    ):
        """
        Initialize anomaly detector.

        Args:
            z_score_threshold: Z-score threshold for statistical outliers.
            velocity_spike_multiplier: Multiplier for velocity spike detection.
            coordinated_window_minutes: Window for coordinated movement detection.
            min_coordinated_count: Min transactions for coordinated movement.
            min_history_size: Minimum history before detecting anomalies.
        """
        self.z_score_threshold = z_score_threshold
        self.velocity_spike_multiplier = velocity_spike_multiplier
        self.coordinated_window_minutes = coordinated_window_minutes
        self.min_coordinated_count = min_coordinated_count
        self.min_history_size = min_history_size

        # Rolling statistics for different metrics
        self._tx_values = RollingStats()
        self._deposit_values = RollingStats()
        self._withdrawal_values = RollingStats()
        self._event_values = RollingStats()

        # Recent transaction buffer for coordinated movement detection
        self._recent_large_txs: Deque[tuple[datetime, str, float]] = deque(maxlen=100)

        # Detected anomalies
        self._detected_anomalies: Deque[Anomaly] = deque(maxlen=1000)

        # Lock for thread safety
        self._lock = asyncio.Lock()

    async def analyze_transaction(
        self, tx: ClassifiedTransaction
    ) -> list[Anomaly]:
        """
        Analyze a classified transaction for anomalies.

        Args:
            tx: Classified transaction to analyze.

        Returns:
            List of detected anomalies (may be empty).
        """
        anomalies = []
        async with self._lock:
            now = datetime.utcnow()
            value = tx.total_value_out_btc

            # Add to rolling stats
            self._tx_values.add(value, now)

            # Check for statistical outlier
            if self._tx_values.is_outlier(value, self.z_score_threshold):
                if len(self._tx_values.values) >= self.min_history_size:
                    severity = self._determine_outlier_severity(value)
                    anomaly = Anomaly(
                        anomaly_id=str(uuid4()),
                        anomaly_type=AnomalyType.STATISTICAL_OUTLIER,
                        severity=severity,
                        detected_at=now,
                        description=f"Transaction of {value:.2f} BTC is a statistical outlier "
                        f"(mean: {self._tx_values.mean:.2f}, std: {self._tx_values.std:.2f})",
                        value_btc=value,
                        related_txids=[tx.txid],
                        related_events=[],
                        metadata={
                            "z_score": (value - self._tx_values.mean) / self._tx_values.std,
                            "mean": self._tx_values.mean,
                            "std": self._tx_values.std,
                        },
                    )
                    anomalies.append(anomaly)
                    ANOMALIES_DETECTED.labels(anomaly_type=AnomalyType.STATISTICAL_OUTLIER.value).inc()

            # Track for coordinated movement detection
            if value >= 100:  # Only track large transactions (100+ BTC)
                self._recent_large_txs.append((now, tx.txid, value))

                # Check for coordinated movement
                coordinated = await self._check_coordinated_movement(now)
                if coordinated:
                    anomalies.append(coordinated)

            # Check for velocity anomaly
            velocity_anomaly = await self._check_velocity_anomaly()
            if velocity_anomaly:
                anomalies.append(velocity_anomaly)

            # Store anomalies
            for anomaly in anomalies:
                self._detected_anomalies.append(anomaly)
                logger.warning(
                    "Anomaly detected",
                    anomaly_type=anomaly.anomaly_type.value,
                    severity=anomaly.severity.value,
                    value_btc=anomaly.value_btc,
                    description=anomaly.description,
                )

        return anomalies

    async def analyze_event(self, event: WhaleEvent) -> list[Anomaly]:
        """
        Analyze a whale event for anomalies.

        Args:
            event: Whale event to analyze.

        Returns:
            List of detected anomalies (may be empty).
        """
        anomalies = []
        async with self._lock:
            now = datetime.utcnow()
            value = event.total_value_btc

            # Add to event stats
            self._event_values.add(value, now)

            # Track deposits and withdrawals separately
            if event.event_type in (
                WhaleEventType.WH_EXCHANGE_SINGLE_DEPOSIT,
                WhaleEventType.WH_EXCHANGE_DEPOSIT_BURST,
            ):
                self._deposit_values.add(value, now)

                # Check for deposit spike
                if self._deposit_values.is_outlier(value, self.z_score_threshold):
                    if len(self._deposit_values.values) >= self.min_history_size:
                        anomaly = Anomaly(
                            anomaly_id=str(uuid4()),
                            anomaly_type=AnomalyType.DEPOSIT_SPIKE,
                            severity=self._determine_outlier_severity(value),
                            detected_at=now,
                            description=f"Exchange deposit of {value:.2f} BTC is unusually large",
                            value_btc=value,
                            related_txids=event.txids,
                            related_events=[str(event.event_id)],
                            metadata={
                                "event_type": event.event_type.value,
                                "entities": [e.label for e in event.entities],
                            },
                        )
                        anomalies.append(anomaly)
                        ANOMALIES_DETECTED.labels(anomaly_type=AnomalyType.DEPOSIT_SPIKE.value).inc()

            elif event.event_type in (
                WhaleEventType.WH_EXCHANGE_SINGLE_WITHDRAWAL,
                WhaleEventType.WH_EXCHANGE_BULK_OUTFLOW,
            ):
                self._withdrawal_values.add(value, now)

                # Check for withdrawal spike
                if self._withdrawal_values.is_outlier(value, self.z_score_threshold):
                    if len(self._withdrawal_values.values) >= self.min_history_size:
                        anomaly = Anomaly(
                            anomaly_id=str(uuid4()),
                            anomaly_type=AnomalyType.WITHDRAWAL_SPIKE,
                            severity=self._determine_outlier_severity(value),
                            detected_at=now,
                            description=f"Exchange withdrawal of {value:.2f} BTC is unusually large",
                            value_btc=value,
                            related_txids=event.txids,
                            related_events=[str(event.event_id)],
                            metadata={
                                "event_type": event.event_type.value,
                                "entities": [e.label for e in event.entities],
                            },
                        )
                        anomalies.append(anomaly)
                        ANOMALIES_DETECTED.labels(anomaly_type=AnomalyType.WITHDRAWAL_SPIKE.value).inc()

            # Store anomalies
            for anomaly in anomalies:
                self._detected_anomalies.append(anomaly)
                logger.warning(
                    "Event anomaly detected",
                    anomaly_type=anomaly.anomaly_type.value,
                    severity=anomaly.severity.value,
                    value_btc=anomaly.value_btc,
                )

        return anomalies

    async def _check_coordinated_movement(self, now: datetime) -> Anomaly | None:
        """Check for coordinated large transactions."""
        cutoff = now - timedelta(minutes=self.coordinated_window_minutes)
        recent = [
            (ts, txid, value)
            for ts, txid, value in self._recent_large_txs
            if ts > cutoff
        ]

        if len(recent) >= self.min_coordinated_count:
            total_value = sum(value for _, _, value in recent)
            txids = [txid for _, txid, _ in recent]

            # Only trigger if we haven't already detected this pattern recently
            # (check if any of these txids are already in a coordinated anomaly)
            for anomaly in self._detected_anomalies:
                if anomaly.anomaly_type == AnomalyType.COORDINATED_MOVEMENT:
                    if set(txids) == set(anomaly.related_txids):
                        return None

            anomaly = Anomaly(
                anomaly_id=str(uuid4()),
                anomaly_type=AnomalyType.COORDINATED_MOVEMENT,
                severity=AnomalySeverity.HIGH if total_value > 1000 else AnomalySeverity.MEDIUM,
                detected_at=now,
                description=f"{len(recent)} large transactions totaling {total_value:.2f} BTC "
                f"detected within {self.coordinated_window_minutes} minutes",
                value_btc=total_value,
                related_txids=txids,
                related_events=[],
                metadata={
                    "transaction_count": len(recent),
                    "window_minutes": self.coordinated_window_minutes,
                },
            )
            ANOMALIES_DETECTED.labels(anomaly_type=AnomalyType.COORDINATED_MOVEMENT.value).inc()
            return anomaly

        return None

    async def _check_velocity_anomaly(self) -> Anomaly | None:
        """Check for unusual transaction velocity."""
        if len(self._tx_values.values) < self.min_history_size:
            return None

        current_velocity = self._tx_values.get_velocity(window_minutes=10)

        # Calculate baseline velocity from longer window
        if len(self._tx_values.timestamps) < 100:
            return None

        # Get velocity from older data
        older_cutoff = datetime.utcnow() - timedelta(minutes=60)
        older_count = sum(
            1 for ts in list(self._tx_values.timestamps)[:-10]  # Exclude recent
            if ts < older_cutoff
        )
        if older_count == 0:
            return None

        baseline_velocity = older_count / 60  # per minute

        if baseline_velocity > 0 and current_velocity > baseline_velocity * self.velocity_spike_multiplier:
            anomaly = Anomaly(
                anomaly_id=str(uuid4()),
                anomaly_type=AnomalyType.VELOCITY_ANOMALY,
                severity=AnomalySeverity.MEDIUM,
                detected_at=datetime.utcnow(),
                description=f"Transaction velocity spike: {current_velocity:.2f}/min "
                f"vs baseline {baseline_velocity:.2f}/min",
                value_btc=0,
                related_txids=[],
                related_events=[],
                metadata={
                    "current_velocity": current_velocity,
                    "baseline_velocity": baseline_velocity,
                    "multiplier": current_velocity / baseline_velocity,
                },
            )
            ANOMALIES_DETECTED.labels(anomaly_type=AnomalyType.VELOCITY_ANOMALY.value).inc()
            return anomaly

        return None

    def _determine_outlier_severity(self, value: float) -> AnomalySeverity:
        """Determine severity based on transaction value."""
        if value >= 10000:
            return AnomalySeverity.CRITICAL
        elif value >= 5000:
            return AnomalySeverity.HIGH
        elif value >= 1000:
            return AnomalySeverity.MEDIUM
        else:
            return AnomalySeverity.LOW

    def get_recent_anomalies(
        self,
        limit: int = 100,
        anomaly_type: AnomalyType | None = None,
        min_severity: AnomalySeverity | None = None,
    ) -> list[Anomaly]:
        """
        Get recent detected anomalies.

        Args:
            limit: Maximum number of anomalies to return.
            anomaly_type: Filter by anomaly type.
            min_severity: Filter by minimum severity.

        Returns:
            List of recent anomalies.
        """
        severity_order = {
            AnomalySeverity.LOW: 0,
            AnomalySeverity.MEDIUM: 1,
            AnomalySeverity.HIGH: 2,
            AnomalySeverity.CRITICAL: 3,
        }

        result = list(self._detected_anomalies)

        if anomaly_type:
            result = [a for a in result if a.anomaly_type == anomaly_type]

        if min_severity:
            min_level = severity_order[min_severity]
            result = [a for a in result if severity_order[a.severity] >= min_level]

        # Sort by detected_at descending
        result.sort(key=lambda a: a.detected_at, reverse=True)

        return result[:limit]

    def get_stats(self) -> dict:
        """Get current detector statistics."""
        return {
            "total_transactions_analyzed": len(self._tx_values.values),
            "total_anomalies_detected": len(self._detected_anomalies),
            "tx_mean_btc": self._tx_values.mean,
            "tx_std_btc": self._tx_values.std,
            "deposit_mean_btc": self._deposit_values.mean,
            "withdrawal_mean_btc": self._withdrawal_values.mean,
            "current_tx_velocity": self._tx_values.get_velocity(),
            "anomaly_counts": {
                atype.value: sum(
                    1 for a in self._detected_anomalies if a.anomaly_type == atype
                )
                for atype in AnomalyType
            },
        }


# Singleton instance
_anomaly_detector: AnomalyDetector | None = None


def get_anomaly_detector() -> AnomalyDetector:
    """Get the singleton anomaly detector instance."""
    global _anomaly_detector
    if _anomaly_detector is None:
        _anomaly_detector = AnomalyDetector()
    return _anomaly_detector
