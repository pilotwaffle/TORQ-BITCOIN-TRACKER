"""
Price oracle service for TBWI.

Fetches and caches BTC/USD price for transaction enrichment.
Includes multiple fallback sources for reliability.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx

from tbwi.config import get_settings
from tbwi.logging import get_logger
from tbwi.services.metrics import (
    CURRENT_BTC_PRICE,
    PRICE_FETCH_ERRORS,
    PRICE_FETCH_TIME,
)

logger = get_logger(__name__)


class PriceSource(str, Enum):
    """Available price data sources."""

    COINGECKO = "coingecko"
    BINANCE = "binance"
    COINBASE = "coinbase"
    KRAKEN = "kraken"
    BITSTAMP = "bitstamp"


@dataclass
class PriceSourceConfig:
    """Configuration for a price source."""

    name: PriceSource
    url: str
    extractor: str  # Method name to extract price from response
    timeout: float = 5.0
    priority: int = 1  # Lower = higher priority


# Default price sources with fallback order
DEFAULT_PRICE_SOURCES = [
    PriceSourceConfig(
        name=PriceSource.COINGECKO,
        url="https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
        extractor="coingecko",
        priority=1,
    ),
    PriceSourceConfig(
        name=PriceSource.BINANCE,
        url="https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
        extractor="binance",
        priority=2,
    ),
    PriceSourceConfig(
        name=PriceSource.COINBASE,
        url="https://api.coinbase.com/v2/prices/BTC-USD/spot",
        extractor="coinbase",
        priority=3,
    ),
    PriceSourceConfig(
        name=PriceSource.KRAKEN,
        url="https://api.kraken.com/0/public/Ticker?pair=XBTUSD",
        extractor="kraken",
        priority=4,
    ),
    PriceSourceConfig(
        name=PriceSource.BITSTAMP,
        url="https://www.bitstamp.net/api/v2/ticker/btcusd/",
        extractor="bitstamp",
        priority=5,
    ),
]


class PriceOracle:
    """
    Price oracle for BTC/USD with multiple fallback sources.

    Fetches price from configured APIs with caching and automatic fallback.
    """

    def __init__(
        self,
        sources: list[PriceSourceConfig] | None = None,
        cache_ttl_seconds: int | None = None,
        enabled: bool | None = None,
    ):
        settings = get_settings()
        self.sources = sources or DEFAULT_PRICE_SOURCES
        self.cache_ttl = cache_ttl_seconds or settings.price_oracle.cache_ttl_seconds
        self.enabled = enabled if enabled is not None else settings.price_oracle.enabled

        self._cached_price: float | None = None
        self._cache_timestamp: float = 0
        self._last_source: PriceSource | None = None
        self._client: httpx.AsyncClient | None = None
        self._source_failures: dict[PriceSource, int] = {}
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": "TBWI/1.0"},
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get_btc_usd_price(self, force_refresh: bool = False) -> float | None:
        """
        Get current BTC/USD price with automatic fallback.

        Args:
            force_refresh: Skip cache and fetch fresh price.

        Returns:
            Current price or None if all sources fail.
        """
        if not self.enabled:
            return None

        # Check cache
        now = time.time()
        if not force_refresh and self._cached_price is not None:
            if (now - self._cache_timestamp) < self.cache_ttl:
                return self._cached_price

        async with self._lock:
            # Double-check cache after acquiring lock
            if not force_refresh and self._cached_price is not None:
                if (now - self._cache_timestamp) < self.cache_ttl:
                    return self._cached_price

            # Sort sources by priority and failure count
            sorted_sources = sorted(
                self.sources,
                key=lambda s: (self._source_failures.get(s.name, 0), s.priority),
            )

            for source in sorted_sources:
                price = await self._fetch_from_source(source)
                if price is not None:
                    self._cached_price = price
                    self._cache_timestamp = time.time()
                    self._last_source = source.name
                    self._source_failures[source.name] = 0

                    # Update Prometheus gauge
                    CURRENT_BTC_PRICE.set(price)

                    logger.info(
                        "Fetched BTC price",
                        price_usd=price,
                        source=source.name.value,
                    )
                    return price

            # All sources failed
            logger.error("All price sources failed")
            return self._cached_price  # Return stale cache if available

    async def _fetch_from_source(self, source: PriceSourceConfig) -> float | None:
        """
        Fetch price from a specific source.

        Args:
            source: Price source configuration.

        Returns:
            Price or None if fetch failed.
        """
        start_time = time.time()

        try:
            client = await self._get_client()
            response = await client.get(
                source.url,
                timeout=source.timeout,
            )
            response.raise_for_status()

            data = response.json()
            price = self._extract_price(data, source.extractor)

            # Record fetch time
            PRICE_FETCH_TIME.observe(time.time() - start_time)

            if price is not None:
                logger.debug(
                    "Price fetched from source",
                    source=source.name.value,
                    price=price,
                    duration_ms=int((time.time() - start_time) * 1000),
                )
            return price

        except httpx.TimeoutException:
            logger.warning(
                "Price fetch timeout",
                source=source.name.value,
                timeout=source.timeout,
            )
            PRICE_FETCH_ERRORS.labels(source=source.name.value).inc()
            self._source_failures[source.name] = (
                self._source_failures.get(source.name, 0) + 1
            )
            return None

        except httpx.HTTPStatusError as e:
            logger.warning(
                "Price fetch HTTP error",
                source=source.name.value,
                status=e.response.status_code,
            )
            PRICE_FETCH_ERRORS.labels(source=source.name.value).inc()
            self._source_failures[source.name] = (
                self._source_failures.get(source.name, 0) + 1
            )
            return None

        except Exception as e:
            logger.warning(
                "Price fetch error",
                source=source.name.value,
                error=str(e),
            )
            PRICE_FETCH_ERRORS.labels(source=source.name.value).inc()
            self._source_failures[source.name] = (
                self._source_failures.get(source.name, 0) + 1
            )
            return None

    def _extract_price(self, data: dict[str, Any], extractor: str) -> float | None:
        """
        Extract price from API response using the appropriate extractor.

        Args:
            data: API response data.
            extractor: Extractor name to use.

        Returns:
            Extracted price or None.
        """
        try:
            if extractor == "coingecko":
                # {"bitcoin": {"usd": 65000}}
                return float(data["bitcoin"]["usd"])

            elif extractor == "binance":
                # {"symbol": "BTCUSDT", "price": "65000.00"}
                return float(data["price"])

            elif extractor == "coinbase":
                # {"data": {"base": "BTC", "currency": "USD", "amount": "65000.00"}}
                return float(data["data"]["amount"])

            elif extractor == "kraken":
                # {"result": {"XXBTZUSD": {"c": ["65000.0", "0.001"]}}}
                # "c" = last trade closed [price, lot volume]
                result = data.get("result", {})
                for key in result:
                    if "XBT" in key or "BTC" in key:
                        return float(result[key]["c"][0])
                return None

            elif extractor == "bitstamp":
                # {"last": "65000.00", ...}
                return float(data["last"])

            else:
                logger.warning(f"Unknown price extractor: {extractor}")
                return None

        except (KeyError, IndexError, TypeError, ValueError) as e:
            logger.warning(
                "Failed to extract price",
                extractor=extractor,
                error=str(e),
                data=str(data)[:200],
            )
            return None

    def btc_to_usd(self, btc_amount: float, price: float | None = None) -> float | None:
        """
        Convert BTC amount to USD.

        Args:
            btc_amount: Amount in BTC.
            price: Price to use (uses cached if not provided).

        Returns:
            USD value or None if price unavailable.
        """
        if price is None:
            price = self._cached_price
        if price is None:
            return None
        return btc_amount * price

    def usd_to_btc(self, usd_amount: float, price: float | None = None) -> float | None:
        """
        Convert USD amount to BTC.

        Args:
            usd_amount: Amount in USD.
            price: Price to use (uses cached if not provided).

        Returns:
            BTC value or None if price unavailable.
        """
        if price is None:
            price = self._cached_price
        if price is None or price == 0:
            return None
        return usd_amount / price

    @property
    def cached_price(self) -> float | None:
        """Get the currently cached price."""
        return self._cached_price

    @property
    def last_source(self) -> PriceSource | None:
        """Get the last successful price source."""
        return self._last_source

    @property
    def cache_age_seconds(self) -> float:
        """Get the age of the cached price in seconds."""
        if self._cache_timestamp == 0:
            return float("inf")
        return time.time() - self._cache_timestamp

    def get_source_health(self) -> dict[str, int]:
        """
        Get failure counts for each source.

        Returns:
            Dictionary mapping source names to failure counts.
        """
        return {
            source.name.value: self._source_failures.get(source.name, 0)
            for source in self.sources
        }

    async def fetch_from_all_sources(self) -> dict[str, float | None]:
        """
        Fetch price from all sources simultaneously for comparison.

        Useful for monitoring price discrepancies.

        Returns:
            Dictionary mapping source names to prices.
        """
        tasks = [
            self._fetch_from_source(source)
            for source in self.sources
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            source.name.value: (
                result if isinstance(result, (float, type(None))) else None
            )
            for source, result in zip(self.sources, results)
        }


# Singleton instance
_price_oracle: PriceOracle | None = None


def get_price_oracle() -> PriceOracle:
    """Get the singleton price oracle instance."""
    global _price_oracle
    if _price_oracle is None:
        _price_oracle = PriceOracle()
    return _price_oracle


async def close_price_oracle() -> None:
    """Close the singleton price oracle."""
    global _price_oracle
    if _price_oracle is not None:
        await _price_oracle.close()
        _price_oracle = None
