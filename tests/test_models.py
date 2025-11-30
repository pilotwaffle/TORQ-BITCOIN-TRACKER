"""
Tests for TBWI Pydantic models.
"""

import pytest
from datetime import datetime
from uuid import UUID

from tbwi.models.schemas import (
    ClassifiedTransaction,
    EntityCategory,
    EntityTag,
    EntityTagCreate,
    NormalizedTransaction,
    TransactionOutput,
    TransactionType,
    WhaleEvent,
    WhaleEventType,
    EventEntity,
    WebhookPayload,
)


class TestNormalizedTransaction:
    """Tests for NormalizedTransaction model."""

    def test_create_basic(self):
        """Test creating a basic normalized transaction."""
        tx = NormalizedTransaction(
            txid="abc123",
            network="testnet",
            total_value_out_btc=10.5,
            vout=[],
            size_bytes=200,
        )
        assert tx.txid == "abc123"
        assert tx.network == "testnet"
        assert tx.total_value_out_btc == 10.5
        assert isinstance(tx.seen_at, datetime)

    def test_with_outputs(self):
        """Test normalized transaction with outputs."""
        tx = NormalizedTransaction(
            txid="abc123",
            network="testnet",
            total_value_out_btc=10.5,
            vout=[
                TransactionOutput(
                    index=0,
                    value_btc=5.0,
                    script_type="p2wpkh",
                    address="tb1q...",
                ),
                TransactionOutput(
                    index=1,
                    value_btc=5.5,
                    script_type="p2pkh",
                    address="m...",
                ),
            ],
            size_bytes=350,
        )
        assert len(tx.vout) == 2
        assert tx.vout[0].value_btc == 5.0


class TestClassifiedTransaction:
    """Tests for ClassifiedTransaction model."""

    def test_create_with_types(self, sample_classified_tx):
        """Test creating a classified transaction."""
        tx = sample_classified_tx
        assert tx.primary_type == TransactionType.EXCHANGE_DEPOSIT_CANDIDATE
        assert TransactionType.LARGE_SINGLE_OUTPUT in tx.types

    def test_json_serialization(self, sample_classified_tx):
        """Test JSON serialization."""
        tx = sample_classified_tx
        data = tx.model_dump(mode="json")
        assert data["txid"] == tx.txid
        assert "total_value_out_btc" in data


class TestWhaleEvent:
    """Tests for WhaleEvent model."""

    def test_create_event(self, sample_whale_event):
        """Test creating a whale event."""
        event = sample_whale_event
        assert isinstance(event.event_id, UUID)
        assert event.event_type == WhaleEventType.WH_EXCHANGE_SINGLE_DEPOSIT
        assert len(event.entities) == 1
        assert event.entities[0].label == "Binance"

    def test_event_serialization(self, sample_whale_event):
        """Test whale event serialization."""
        event = sample_whale_event
        data = event.model_dump(mode="json")
        assert "event_id" in data
        assert "summary" in data
        assert data["total_value_btc"] == 1500.0


class TestEntityTag:
    """Tests for EntityTag model."""

    def test_create_tag(self, sample_entity_tag):
        """Test creating an entity tag."""
        tag = sample_entity_tag
        assert tag.label == "Binance"
        assert tag.category == EntityCategory.EXCHANGE_DEPOSIT
        assert tag.confidence == 0.95

    def test_invalid_confidence(self):
        """Test that invalid confidence raises error."""
        with pytest.raises(ValueError):
            EntityTagCreate(
                address="tb1q...",
                label="Test",
                category=EntityCategory.EXCHANGE_DEPOSIT,
                confidence=1.5,  # Invalid: > 1.0
            )


class TestWebhookPayload:
    """Tests for WebhookPayload model."""

    def test_from_whale_event(self, sample_whale_event):
        """Test creating webhook payload from event."""
        event = sample_whale_event
        payload = WebhookPayload(
            event_id=event.event_id,
            event_type=event.event_type,
            created_at=event.created_at,
            network=event.network,
            summary=event.summary,
            total_value_btc=event.total_value_btc,
            total_value_usd=event.total_value_usd,
            entities=event.entities,
            txids=event.txids,
        )
        assert payload.event_id == event.event_id
        assert payload.summary == event.summary
