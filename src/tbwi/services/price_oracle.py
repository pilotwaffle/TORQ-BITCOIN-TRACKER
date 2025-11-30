"""
Price oracle service for TBWI.

Fetches and caches BTC/USD price for transaction enrichment.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from tbwi.config import get_settings
from tbwi.logging import get_logger

logger = get_logger(__name__)


class PriceOracle:
    """
    Price oracle for BTC/USD.

    Fetches price from configured API with caching.
    """

    def __init__(
        self,
        url: str | None = None,
        cache_ttl_seconds: int | None = None,
        enabled: bool | None = None,
    ):
        settings = get_settings()
        self.url = url or settings.price_oracle.url
        self.cache_ttl = cache_ttl_seconds or settings.price_oracle.cache_ttl_seconds
        self.enabled = enabled if enabled is not None else settings.price_oracle.enabled

        self._cached_price: float | None = None
        self._cache_timestamp: float = 0
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get_btc_usd_price(self) -> float | None:
        """
        Get current BTC/USD price.

        Returns:
            Current price or None if unavailable/disabled
        """
        if not self.enabled:
            return None

        # Check cache
        now = time.time()
        if self._cached_price is not None and (now - self._cache_timestamp) < self.cache_ttl:
            return self._cached_price

        try:
            client = await self._get_client()
            response = await client.get(self.url)
            response.raise_for_status()

            data = response.json()

            # Handle different API response formats
            price = self._extract_price(data)

            if price is not None:
                self._cached_price = price
                self._cache_timestamp = now
                logger.debug("Fetched BTC price", price_usd=price)

            return price

        except Exception as e:
            logger.warning("Failed to fetch BTC price", error=str(e))
            # Return cached value if available, even if stale
            return self._cached_price

    def _extract_price(self, data: dict[str, Any]) -> float | None:
        """Extract price from API response."""
        # CoinGecko format
        if "bitcoin" in data and "usd" in data["bitcoin"]:
            return float(data["bitcoin"]["usd"])

        # Simple {"price": X} format
        if "price" in data:
            return float(data["price"])

        # {"btc_usd": X} format
        if "btc_usd" in data:
            return float(data["btc_usd"])

        # Binance format {"price": "X"}
        if "price" in data and isinstance(data["price"], str):
            return float(data["price"])

        logger.warning("Unknown price API response format", data=data)
        return None

    def btc_to_usd(self, btc_amount: float, price: float | None = None) -> float | None:
        """
        Convert BTC amount to USD.

        Args:
            btc_amount: Amount in BTC
            price: Price to use (uses cached if not provided)

        Returns:
            USD value or None if price unavailable
        """
        if price is None:
            price = self._cached_price
        if price is None:
            return None
        return btc_amount * price


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
