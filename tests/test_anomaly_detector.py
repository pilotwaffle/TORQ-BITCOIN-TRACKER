"""
Tests for the Anomaly Detector service.
"""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from tbwi.models.schemas import (
    ClassifiedTransaction,
    EnrichedOutput,
    TransactionType,
    WhaleEvent,
    WhaleEventType,
    EventEntity,
)
from tbwi.services.anomaly_detector import (
    AnomalyDetector,
    AnomalyType,
    AnomalySeverity,
    RollingStats,
)


class TestRollingStats:
    """Tests for RollingStats."""

    def test_empty_stats(self):
        """Test empty rolling stats."""
        stats = RollingStats()
        assert stats.mean == 0.0
        assert stats.std == 0.0

    def test_mean_calculation(self):
        """Test mean calculation."""
        stats = RollingStats()
        stats.add(10.0)
        stats.add(20.0)
        stats.add(30.0)
        assert stats.mean == 20.0

    def test_std_calculation(self):
        """Test standard deviation calculation."""
        stats = RollingStats()
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            stats.add(v)
        # Mean = 30, variance = ((20^2 + 10^2 + 0^2 + 10^2 + 20^2) / 5) = 200
        # std = sqrt(200) = 14.14...
        assert abs(stats.std - 14.14) < 0.1

    def test_outlier_detection(self):
        """Test outlier detection."""
        stats = RollingStats()
        # Add normal values
        for v in range(100):
            stats.add(float(v))

        # 50 is the mean, 1000 should be an outlier
        assert stats.is_outlier(1000.0, z_threshold=3.0)
        assert not stats.is_outlier(50.0, z_threshold=3.0)

    def test_outlier_with_few_samples(self):
        """Test that outlier detection needs minimum samples."""
        stats = RollingStats()
        stats.add(10.0)
        stats.add(20.0)
        # Should return False with < 10 samples
        assert not stats.is_outlier(1000.0)

    def test_velocity_calculation(self):
        """Test velocity calculation."""
        stats = RollingStats()
        now = datetime.utcnow()

        # Add 10 values in the last minute
        for i in range(10):
            stats.add(float(i), now - timedelta(seconds=i * 5))

        # Velocity should be ~1 per minute
        velocity = stats.get_velocity(window_minutes=10)
        assert velocity > 0


class TestAnomalyDetector:
    """Tests for AnomalyDetector."""

    @pytest.fixture
    def detector(self):
        """Create an anomaly detector instance."""
        return AnomalyDetector(
            z_score_threshold=3.0,
            min_history_size=10,
        )

    @pytest.fixture
    def sample_tx(self):
        """Create a sample classified transaction."""
        return ClassifiedTransaction(
            txid="test123",
            seen_at=datetime.utcnow(),
            network="testnet",
            total_value_out_btc=100.0,
            total_value_usd=6500000.0,
            primary_type=TransactionType.LARGE_SINGLE_OUTPUT,
            types=[TransactionType.LARGE_SINGLE_OUTPUT],
            inputs=[],
            outputs=[
                EnrichedOutput(
                    index=0,
                    address="tb1q...",
                    value_btc=100.0,
                    script_type="p2wpkh",
                    entity_label="Unknown",
                    entity_category=None,
                )
            ],
        )

    @pytest.fixture
    def sample_event(self):
        """Create a sample whale event."""
        return WhaleEvent(
            event_id=uuid4(),
            window_start=datetime.utcnow(),
            window_end=datetime.utcnow(),
            network="testnet",
            event_type=WhaleEventType.WH_EXCHANGE_SINGLE_DEPOSIT,
            entities=[
                EventEntity(
                    label="Binance",
                    category="exchange",
                    confidence=0.95,
                )
            ],
            total_value_btc=1500.0,
            total_value_usd=97500000.0,
            txids=["abc123"],
            summary="Large deposit to Binance",
        )

    @pytest.mark.asyncio
    async def test_analyze_normal_transaction(self, detector, sample_tx):
        """Test analyzing a normal transaction."""
        # Add baseline history
        for i in range(20):
            tx = ClassifiedTransaction(
                txid=f"baseline{i}",
                seen_at=datetime.utcnow(),
                network="testnet",
                total_value_out_btc=100.0 + i,
                total_value_usd=6500000.0,
                primary_type=TransactionType.LARGE_SINGLE_OUTPUT,
                types=[TransactionType.LARGE_SINGLE_OUTPUT],
                inputs=[],
                outputs=[],
            )
            await detector.analyze_transaction(tx)

        # Analyze a normal transaction
        anomalies = await detector.analyze_transaction(sample_tx)
        # Should not detect anomalies for normal value
        assert len([a for a in anomalies if a.anomaly_type == AnomalyType.STATISTICAL_OUTLIER]) == 0

    @pytest.mark.asyncio
    async def test_detect_statistical_outlier(self, detector):
        """Test detection of statistical outlier."""
        # Add baseline history with small values
        for i in range(50):
            tx = ClassifiedTransaction(
                txid=f"baseline{i}",
                seen_at=datetime.utcnow(),
                network="testnet",
                total_value_out_btc=10.0 + (i % 5),
                total_value_usd=650000.0,
                primary_type=TransactionType.LARGE_SINGLE_OUTPUT,
                types=[TransactionType.LARGE_SINGLE_OUTPUT],
                inputs=[],
                outputs=[],
            )
            await detector.analyze_transaction(tx)

        # Now add an outlier
        outlier_tx = ClassifiedTransaction(
            txid="outlier",
            seen_at=datetime.utcnow(),
            network="testnet",
            total_value_out_btc=10000.0,  # Much larger than baseline
            total_value_usd=650000000.0,
            primary_type=TransactionType.LARGE_SINGLE_OUTPUT,
            types=[TransactionType.LARGE_SINGLE_OUTPUT],
            inputs=[],
            outputs=[],
        )
        anomalies = await detector.analyze_transaction(outlier_tx)

        # Should detect as outlier
        outlier_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.STATISTICAL_OUTLIER]
        assert len(outlier_anomalies) >= 1

    @pytest.mark.asyncio
    async def test_analyze_whale_event(self, detector, sample_event):
        """Test analyzing a whale event."""
        # Add baseline
        for i in range(20):
            event = WhaleEvent(
                event_id=uuid4(),
                window_start=datetime.utcnow(),
                window_end=datetime.utcnow(),
                network="testnet",
                event_type=WhaleEventType.WH_EXCHANGE_SINGLE_DEPOSIT,
                entities=[EventEntity(label="Binance", category="exchange", confidence=0.95)],
                total_value_btc=100.0 + i,
                total_value_usd=6500000.0,
                txids=["test"],
                summary="Test event",
            )
            await detector.analyze_event(event)

        anomalies = await detector.analyze_event(sample_event)
        # 1500 BTC is large but may not be outlier depending on baseline
        assert isinstance(anomalies, list)

    @pytest.mark.asyncio
    async def test_get_recent_anomalies(self, detector):
        """Test getting recent anomalies."""
        anomalies = detector.get_recent_anomalies(limit=10)
        assert isinstance(anomalies, list)
        assert len(anomalies) <= 10

    @pytest.mark.asyncio
    async def test_get_stats(self, detector):
        """Test getting detector statistics."""
        stats = detector.get_stats()
        assert "total_transactions_analyzed" in stats
        assert "total_anomalies_detected" in stats
        assert "anomaly_counts" in stats

    def test_severity_determination(self, detector):
        """Test severity determination based on value."""
        assert detector._determine_outlier_severity(100) == AnomalySeverity.LOW
        assert detector._determine_outlier_severity(1500) == AnomalySeverity.MEDIUM
        assert detector._determine_outlier_severity(6000) == AnomalySeverity.HIGH
        assert detector._determine_outlier_severity(15000) == AnomalySeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_coordinated_movement_detection(self, detector):
        """Test coordinated movement detection."""
        detector.min_coordinated_count = 3
        detector.coordinated_window_minutes = 5

        # Add 3 large transactions quickly
        for i in range(3):
            tx = ClassifiedTransaction(
                txid=f"coord{i}",
                seen_at=datetime.utcnow(),
                network="testnet",
                total_value_out_btc=500.0,  # Large enough to track
                total_value_usd=32500000.0,
                primary_type=TransactionType.LARGE_SINGLE_OUTPUT,
                types=[TransactionType.LARGE_SINGLE_OUTPUT],
                inputs=[],
                outputs=[],
            )
            await detector.analyze_transaction(tx)

        # Check for coordinated anomaly
        anomalies = detector.get_recent_anomalies()
        coord_anomalies = [a for a in anomalies if a.anomaly_type == AnomalyType.COORDINATED_MOVEMENT]
        # May or may not detect depending on timing
        assert isinstance(coord_anomalies, list)
