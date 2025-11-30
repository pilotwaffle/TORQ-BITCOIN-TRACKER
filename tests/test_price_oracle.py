"""
Tests for the Price Oracle service with fallback sources.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from tbwi.services.price_oracle import (
    PriceOracle,
    PriceSource,
    PriceSourceConfig,
    DEFAULT_PRICE_SOURCES,
)


class TestPriceOracle:
    """Tests for PriceOracle."""

    @pytest.fixture
    def oracle(self):
        """Create a price oracle instance."""
        return PriceOracle(enabled=True, cache_ttl_seconds=60)

    def test_default_sources_configured(self):
        """Test that default price sources are configured."""
        assert len(DEFAULT_PRICE_SOURCES) >= 3
        source_names = [s.name for s in DEFAULT_PRICE_SOURCES]
        assert PriceSource.COINGECKO in source_names
        assert PriceSource.BINANCE in source_names
        assert PriceSource.COINBASE in source_names

    def test_extract_coingecko_price(self, oracle):
        """Test CoinGecko price extraction."""
        data = {"bitcoin": {"usd": 65000.50}}
        price = oracle._extract_price(data, "coingecko")
        assert price == 65000.50

    def test_extract_binance_price(self, oracle):
        """Test Binance price extraction."""
        data = {"symbol": "BTCUSDT", "price": "65123.45"}
        price = oracle._extract_price(data, "binance")
        assert price == 65123.45

    def test_extract_coinbase_price(self, oracle):
        """Test Coinbase price extraction."""
        data = {"data": {"base": "BTC", "currency": "USD", "amount": "64999.99"}}
        price = oracle._extract_price(data, "coinbase")
        assert price == 64999.99

    def test_extract_kraken_price(self, oracle):
        """Test Kraken price extraction."""
        data = {"result": {"XXBTZUSD": {"c": ["65500.00", "0.001"]}}}
        price = oracle._extract_price(data, "kraken")
        assert price == 65500.00

    def test_extract_bitstamp_price(self, oracle):
        """Test Bitstamp price extraction."""
        data = {"last": "65200.00", "volume": "1000"}
        price = oracle._extract_price(data, "bitstamp")
        assert price == 65200.00

    def test_extract_invalid_format(self, oracle):
        """Test handling of invalid response format."""
        data = {"invalid": "data"}
        price = oracle._extract_price(data, "coingecko")
        assert price is None

    def test_btc_to_usd_conversion(self, oracle):
        """Test BTC to USD conversion."""
        oracle._cached_price = 65000.0
        usd = oracle.btc_to_usd(1.5)
        assert usd == 97500.0

    def test_btc_to_usd_no_price(self, oracle):
        """Test BTC to USD when no price available."""
        oracle._cached_price = None
        usd = oracle.btc_to_usd(1.5)
        assert usd is None

    def test_usd_to_btc_conversion(self, oracle):
        """Test USD to BTC conversion."""
        oracle._cached_price = 65000.0
        btc = oracle.usd_to_btc(65000.0)
        assert btc == 1.0

    def test_source_health_tracking(self, oracle):
        """Test source health/failure tracking."""
        health = oracle.get_source_health()
        assert isinstance(health, dict)
        for source in DEFAULT_PRICE_SOURCES:
            assert source.name.value in health

    def test_cache_age(self, oracle):
        """Test cache age calculation."""
        # Initially should be infinity
        assert oracle.cache_age_seconds == float("inf")

        # After setting cache
        import time
        oracle._cache_timestamp = time.time()
        assert oracle.cache_age_seconds < 1.0

    @pytest.mark.asyncio
    async def test_disabled_oracle_returns_none(self):
        """Test that disabled oracle returns None."""
        oracle = PriceOracle(enabled=False)
        price = await oracle.get_btc_usd_price()
        assert price is None

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """Test that cached price is returned within TTL."""
        oracle = PriceOracle(enabled=True, cache_ttl_seconds=300)
        oracle._cached_price = 65000.0
        import time
        oracle._cache_timestamp = time.time()

        # Should return cached value without making HTTP call
        price = await oracle.get_btc_usd_price()
        assert price == 65000.0


class TestPriceSourceConfig:
    """Tests for PriceSourceConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = PriceSourceConfig(
            name=PriceSource.COINGECKO,
            url="https://example.com",
            extractor="test",
        )
        assert config.timeout == 5.0
        assert config.priority == 1

    def test_custom_values(self):
        """Test custom configuration values."""
        config = PriceSourceConfig(
            name=PriceSource.BINANCE,
            url="https://example.com",
            extractor="test",
            timeout=10.0,
            priority=5,
        )
        assert config.timeout == 10.0
        assert config.priority == 5
