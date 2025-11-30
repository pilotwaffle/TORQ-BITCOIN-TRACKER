"""
Configuration management for TBWI.

Loads configuration from YAML files and environment variables.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BitcoinCoreConfig(BaseSettings):
    """Bitcoin Core connection settings."""

    model_config = SettingsConfigDict(env_prefix="BITCOIN_")

    rpc_host: str = Field(default="localhost", description="Bitcoin Core RPC host")
    rpc_port: int = Field(default=18332, description="Bitcoin Core RPC port (18332 for testnet)")
    rpc_user: str = Field(default="btcuser", description="Bitcoin Core RPC username")
    rpc_password: str = Field(default="btcpass", description="Bitcoin Core RPC password")
    zmq_tx_endpoint: str = Field(
        default="tcp://localhost:28332", description="ZMQ raw transaction endpoint"
    )
    zmq_block_endpoint: str = Field(
        default="tcp://localhost:28333", description="ZMQ raw block endpoint"
    )
    network: str = Field(default="testnet", description="Bitcoin network: mainnet, testnet, regtest")

    @field_validator("network")
    @classmethod
    def validate_network(cls, v: str) -> str:
        allowed = {"mainnet", "testnet", "regtest"}
        if v not in allowed:
            raise ValueError(f"network must be one of {allowed}")
        return v


class DatabaseConfig(BaseSettings):
    """Database connection settings."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    host: str = Field(default="localhost", description="PostgreSQL host")
    port: int = Field(default=5432, description="PostgreSQL port")
    name: str = Field(default="tbwi", description="Database name")
    user: str = Field(default="tbwi", description="Database user")
    password: str = Field(default="tbwi_secret", description="Database password")

    @property
    def url(self) -> str:
        """Get async database URL."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_url(self) -> str:
        """Get sync database URL for migrations."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class RedisConfig(BaseSettings):
    """Redis connection settings for internal messaging."""

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    host: str = Field(default="localhost", description="Redis host")
    port: int = Field(default=6379, description="Redis port")
    db: int = Field(default=0, description="Redis database number")
    password: str | None = Field(default=None, description="Redis password")

    @property
    def url(self) -> str:
        """Get Redis URL."""
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class ThresholdsConfig(BaseSettings):
    """Transaction and event thresholds."""

    model_config = SettingsConfigDict(env_prefix="THRESHOLD_")

    min_tx_btc: float = Field(
        default=10.0, description="Minimum transaction value in BTC to process"
    )
    large_tx_btc: float = Field(
        default=50.0, description="Threshold for classifying a transaction as 'large'"
    )
    single_deposit_btc: float = Field(
        default=1000.0, description="Threshold for single massive deposit event"
    )
    deposit_burst_min_count: int = Field(
        default=10, description="Minimum transactions for deposit burst event"
    )
    deposit_burst_min_btc: float = Field(
        default=1000.0, description="Minimum total BTC for deposit burst event"
    )
    deposit_burst_window_minutes: int = Field(
        default=10, description="Time window for deposit burst detection"
    )
    outflow_min_count: int = Field(
        default=3, description="Minimum transactions for bulk outflow event"
    )
    outflow_min_btc: float = Field(
        default=10000.0, description="Minimum total BTC for bulk outflow event"
    )
    outflow_window_minutes: int = Field(
        default=30, description="Time window for outflow detection"
    )


class PriceOracleConfig(BaseSettings):
    """Price oracle settings."""

    model_config = SettingsConfigDict(env_prefix="PRICE_")

    enabled: bool = Field(default=True, description="Enable price enrichment")
    url: str = Field(
        default="https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
        description="Price oracle URL",
    )
    cache_ttl_seconds: int = Field(default=60, description="Price cache TTL in seconds")


class WebhookConfig(BaseSettings):
    """Webhook dispatcher settings."""

    model_config = SettingsConfigDict(env_prefix="WEBHOOK_")

    enabled: bool = Field(default=True, description="Enable webhook dispatching")
    urls: list[str] = Field(default_factory=list, description="Webhook URLs to notify")
    retry_max_attempts: int = Field(default=3, description="Maximum retry attempts")
    retry_base_delay_seconds: float = Field(default=1.0, description="Base delay for retries")

    @field_validator("urls", mode="before")
    @classmethod
    def parse_urls(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [url.strip() for url in v.split(",") if url.strip()]
        return v or []


class APIConfig(BaseSettings):
    """API server settings."""

    model_config = SettingsConfigDict(env_prefix="API_")

    host: str = Field(default="0.0.0.0", description="API server host")
    port: int = Field(default=8000, description="API server port")
    api_key: str | None = Field(default=None, description="API key for authentication")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"], description="CORS allowed origins"
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v or ["*"]


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Sub-configs
    bitcoin: BitcoinCoreConfig = Field(default_factory=BitcoinCoreConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    price_oracle: PriceOracleConfig = Field(default_factory=PriceOracleConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    api: APIConfig = Field(default_factory=APIConfig)

    # General
    log_level: str = Field(default="INFO", description="Logging level")
    environment: str = Field(default="development", description="Environment name")

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Settings":
        """Load settings from a YAML file, with env overrides."""
        path = Path(path)
        if not path.exists():
            return cls()

        with open(path) as f:
            yaml_config = yaml.safe_load(f) or {}

        # Flatten nested config for pydantic
        flat_config: dict[str, Any] = {}

        # Map YAML structure to Settings fields
        if "network" in yaml_config:
            flat_config["bitcoin"] = {"network": yaml_config["network"]}

        if "min_tx_threshold_btc" in yaml_config:
            flat_config.setdefault("thresholds", {})["min_tx_btc"] = yaml_config[
                "min_tx_threshold_btc"
            ]

        if "large_tx_threshold_btc" in yaml_config:
            flat_config.setdefault("thresholds", {})["large_tx_btc"] = yaml_config[
                "large_tx_threshold_btc"
            ]

        if "whale_event_thresholds" in yaml_config:
            wet = yaml_config["whale_event_thresholds"]
            thresholds = flat_config.setdefault("thresholds", {})
            if "single_deposit_btc" in wet:
                thresholds["single_deposit_btc"] = wet["single_deposit_btc"]
            if "deposit_burst" in wet:
                db = wet["deposit_burst"]
                if "min_tx_count" in db:
                    thresholds["deposit_burst_min_count"] = db["min_tx_count"]
                if "min_total_btc" in db:
                    thresholds["deposit_burst_min_btc"] = db["min_total_btc"]
                if "window_minutes" in db:
                    thresholds["deposit_burst_window_minutes"] = db["window_minutes"]
            if "exchange_outflow" in wet:
                eo = wet["exchange_outflow"]
                if "min_tx_count" in eo:
                    thresholds["outflow_min_count"] = eo["min_tx_count"]
                if "min_total_btc" in eo:
                    thresholds["outflow_min_btc"] = eo["min_total_btc"]
                if "window_minutes" in eo:
                    thresholds["outflow_window_minutes"] = eo["window_minutes"]

        if "price_oracle" in yaml_config:
            flat_config["price_oracle"] = yaml_config["price_oracle"]

        if "webhook" in yaml_config:
            flat_config["webhook"] = yaml_config["webhook"]

        return cls(**flat_config)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    config_path = os.getenv("TBWI_CONFIG_PATH", "config.yaml")
    if Path(config_path).exists():
        return Settings.from_yaml(config_path)
    return Settings()
