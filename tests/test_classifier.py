"""
Tests for the Transaction Classifier service.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from tbwi.models.schemas import (
    NormalizedTransaction,
    TransactionOutput,
    TransactionType,
    EnrichedOutput,
)
from tbwi.services.classifier import TransactionClassifier


class TestTransactionClassifier:
    """Tests for TransactionClassifier."""

    @pytest.fixture
    def classifier(self):
        """Create a classifier instance."""
        return TransactionClassifier(large_tx_threshold_btc=50.0)

    def test_determine_types_large_single_output(self, classifier):
        """Test classification of large single output transaction."""
        tx = NormalizedTransaction(
            txid="test123",
            network="testnet",
            total_value_out_btc=100.0,
            vout=[
                TransactionOutput(
                    index=0,
                    value_btc=100.0,
                    script_type="p2wpkh",
                    address="tb1q...",
                )
            ],
            size_bytes=200,
        )
        outputs = [
            EnrichedOutput(
                index=0,
                address="tb1q...",
                value_btc=100.0,
                script_type="p2wpkh",
                entity_label="Unknown",
                entity_category=None,
            )
        ]

        types = classifier._determine_types(tx, [], outputs)

        assert TransactionType.LARGE_SINGLE_OUTPUT in types
        assert TransactionType.OTC_LIKE_MOVE_CANDIDATE in types

    def test_determine_types_exchange_deposit(self, classifier):
        """Test classification of exchange deposit."""
        tx = NormalizedTransaction(
            txid="test123",
            network="testnet",
            total_value_out_btc=100.0,
            vout=[
                TransactionOutput(
                    index=0,
                    value_btc=100.0,
                    script_type="p2wpkh",
                    address="tb1qbinance...",
                )
            ],
            size_bytes=200,
        )
        outputs = [
            EnrichedOutput(
                index=0,
                address="tb1qbinance...",
                value_btc=100.0,
                script_type="p2wpkh",
                entity_label="Binance",
                entity_category="exchange_deposit",
            )
        ]

        types = classifier._determine_types(tx, [], outputs)

        assert TransactionType.EXCHANGE_DEPOSIT_CANDIDATE in types

    def test_determine_types_below_threshold(self, classifier):
        """Test that small transactions get fewer classifications."""
        tx = NormalizedTransaction(
            txid="test123",
            network="testnet",
            total_value_out_btc=10.0,  # Below 50 BTC threshold
            vout=[
                TransactionOutput(
                    index=0,
                    value_btc=10.0,
                    script_type="p2wpkh",
                    address="tb1q...",
                )
            ],
            size_bytes=200,
        )
        outputs = [
            EnrichedOutput(
                index=0,
                address="tb1q...",
                value_btc=10.0,
                script_type="p2wpkh",
                entity_label="Unknown",
                entity_category=None,
            )
        ]

        types = classifier._determine_types(tx, [], outputs)

        # Should not include "large" classifications
        assert TransactionType.LARGE_SINGLE_OUTPUT not in types
        assert TransactionType.EXCHANGE_DEPOSIT_CANDIDATE not in types

    def test_determine_types_multi_output(self, classifier):
        """Test classification of multi-output transaction."""
        tx = NormalizedTransaction(
            txid="test123",
            network="testnet",
            total_value_out_btc=100.0,
            vout=[
                TransactionOutput(index=0, value_btc=50.0, script_type="p2wpkh", address="tb1q1..."),
                TransactionOutput(index=1, value_btc=50.0, script_type="p2wpkh", address="tb1q2..."),
            ],
            size_bytes=300,
        )
        outputs = [
            EnrichedOutput(index=0, address="tb1q1...", value_btc=50.0, script_type="p2wpkh", entity_label="Unknown", entity_category=None),
            EnrichedOutput(index=1, address="tb1q2...", value_btc=50.0, script_type="p2wpkh", entity_label="Unknown", entity_category=None),
        ]

        types = classifier._determine_types(tx, [], outputs)

        assert TransactionType.LARGE_MULTI_OUTPUT in types
        assert TransactionType.LARGE_SINGLE_OUTPUT not in types
