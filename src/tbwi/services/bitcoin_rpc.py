"""
Bitcoin Core RPC client for TBWI.

Provides async interface to Bitcoin Core JSON-RPC API.
"""

from __future__ import annotations

from typing import Any

import httpx
from cachetools import TTLCache
from tenacity import retry, stop_after_attempt, wait_exponential

from tbwi.config import get_settings
from tbwi.logging import get_logger

logger = get_logger(__name__)


class BitcoinRPCError(Exception):
    """Bitcoin RPC error."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"RPC Error {code}: {message}")


class BitcoinRPCClient:
    """
    Async Bitcoin Core RPC client.

    Provides methods for common RPC calls with caching and retry logic.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        settings = get_settings()
        self.host = host or settings.bitcoin.rpc_host
        self.port = port or settings.bitcoin.rpc_port
        self.user = user or settings.bitcoin.rpc_user
        self.password = password or settings.bitcoin.rpc_password

        self.url = f"http://{self.host}:{self.port}"
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0

        # Cache for frequently accessed data
        self._cache: TTLCache = TTLCache(maxsize=1000, ttl=60)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                auth=(self.user, self.password),
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def _call(self, method: str, params: list[Any] | None = None) -> Any:
        """Make an RPC call."""
        self._request_id += 1
        payload = {
            "jsonrpc": "1.0",
            "id": self._request_id,
            "method": method,
            "params": params or [],
        }

        client = await self._get_client()
        try:
            response = await client.post(self.url, json=payload)
            response.raise_for_status()
            data = response.json()

            if "error" in data and data["error"] is not None:
                raise BitcoinRPCError(
                    data["error"].get("code", -1),
                    data["error"].get("message", "Unknown error"),
                )

            return data.get("result")
        except httpx.HTTPStatusError as e:
            logger.error("RPC HTTP error", status=e.response.status_code, method=method)
            raise
        except httpx.RequestError as e:
            logger.error("RPC request error", error=str(e), method=method)
            raise

    async def get_blockchain_info(self) -> dict[str, Any]:
        """Get blockchain info."""
        cache_key = "blockchain_info"
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = await self._call("getblockchaininfo")
        self._cache[cache_key] = result
        return result

    async def get_network_info(self) -> dict[str, Any]:
        """Get network info."""
        return await self._call("getnetworkinfo")

    async def get_mempool_info(self) -> dict[str, Any]:
        """Get mempool info."""
        return await self._call("getmempoolinfo")

    async def get_raw_transaction(
        self, txid: str, verbose: bool = True
    ) -> dict[str, Any] | str:
        """
        Get raw transaction details.

        Args:
            txid: Transaction ID
            verbose: If True, return decoded transaction; otherwise hex

        Returns:
            Transaction data (dict if verbose, hex string otherwise)
        """
        cache_key = f"tx:{txid}:{verbose}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = await self._call("getrawtransaction", [txid, verbose])
        self._cache[cache_key] = result
        return result

    async def decode_raw_transaction(self, hex_string: str) -> dict[str, Any]:
        """Decode a raw transaction hex."""
        return await self._call("decoderawtransaction", [hex_string])

    async def get_block(self, blockhash: str, verbosity: int = 1) -> dict[str, Any]:
        """Get block by hash."""
        cache_key = f"block:{blockhash}:{verbosity}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = await self._call("getblock", [blockhash, verbosity])
        self._cache[cache_key] = result
        return result

    async def get_block_count(self) -> int:
        """Get current block height."""
        return await self._call("getblockcount")

    async def get_best_block_hash(self) -> str:
        """Get the hash of the best block."""
        return await self._call("getbestblockhash")

    async def validate_address(self, address: str) -> dict[str, Any]:
        """Validate a Bitcoin address."""
        cache_key = f"addr:{address}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = await self._call("validateaddress", [address])
        self._cache[cache_key] = result
        return result

    async def test_connection(self) -> bool:
        """Test RPC connection."""
        try:
            await self.get_blockchain_info()
            return True
        except Exception as e:
            logger.error("RPC connection test failed", error=str(e))
            return False


# Singleton instance
_rpc_client: BitcoinRPCClient | None = None


def get_rpc_client() -> BitcoinRPCClient:
    """Get the singleton RPC client instance."""
    global _rpc_client
    if _rpc_client is None:
        _rpc_client = BitcoinRPCClient()
    return _rpc_client


async def close_rpc_client() -> None:
    """Close the singleton RPC client."""
    global _rpc_client
    if _rpc_client is not None:
        await _rpc_client.close()
        _rpc_client = None
