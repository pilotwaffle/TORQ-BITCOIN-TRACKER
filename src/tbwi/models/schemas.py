"""
Pydantic schemas for TBWI data models.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TransactionOutput(BaseModel):
    """A single transaction output."""

    index: int = Field(..., description="Output index in the transaction")
    value_btc: float = Field(..., description="Value in BTC")
    script_type: str | None = Field(None, description="Script type (p2pkh, p2wpkh, etc.)")
    address: str | None = Field(None, description="Output address if extractable")


class TransactionInput(BaseModel):
    """A single transaction input (enriched)."""

    txid: str | None = Field(None, description="Previous transaction ID")
    vout: int | None = Field(None, description="Previous output index")
    address: str | None = Field(None, description="Input address if known")
    value_btc: float | None = Field(None, description="Input value in BTC if known")


class NormalizedTransaction(BaseModel):
    """
    Normalized transaction from ZMQ listener.

    This is the initial parsed form before enrichment.
    """

    txid: str = Field(..., description="Transaction ID (hash)")
    seen_at: datetime = Field(
        default_factory=datetime.utcnow, description="When the transaction was seen"
    )
    network: str = Field(..., description="Network: mainnet, testnet, or regtest")
    total_value_out_btc: float = Field(..., description="Total output value in BTC")
    vout: list[TransactionOutput] = Field(default_factory=list, description="Transaction outputs")
    size_bytes: int = Field(..., description="Transaction size in bytes")
    raw_hex: str | None = Field(None, description="Raw transaction hex")


class TransactionType(str, Enum):
    """Classification types for transactions."""

    EXCHANGE_DEPOSIT_CANDIDATE = "EXCHANGE_DEPOSIT_CANDIDATE"
    EXCHANGE_WITHDRAWAL_CANDIDATE = "EXCHANGE_WITHDRAWAL_CANDIDATE"
    OTC_LIKE_MOVE_CANDIDATE = "OTC_LIKE_MOVE_CANDIDATE"
    LARGE_SINGLE_OUTPUT = "LARGE_SINGLE_OUTPUT"
    LARGE_MULTI_OUTPUT = "LARGE_MULTI_OUTPUT"
    PROGRAMMATIC_SPLIT = "PROGRAMMATIC_SPLIT"  # Identical outputs - institutional prep
    CONSOLIDATION = "CONSOLIDATION"  # Many inputs → few outputs
    UNKNOWN_LARGE = "UNKNOWN_LARGE"


class EnrichedInput(BaseModel):
    """Enriched transaction input with entity information."""

    address: str | None = Field(None, description="Input address")
    value_btc: float | None = Field(None, description="Input value in BTC")
    entity_label: str = Field(default="Unknown", description="Entity label if known")
    entity_category: str | None = Field(None, description="Entity category")


class EnrichedOutput(BaseModel):
    """Enriched transaction output with entity information."""

    index: int = Field(..., description="Output index")
    address: str | None = Field(None, description="Output address")
    value_btc: float = Field(..., description="Output value in BTC")
    script_type: str | None = Field(None, description="Script type")
    entity_label: str = Field(default="Unknown", description="Entity label if known")
    entity_category: str | None = Field(None, description="Entity category")


class ClassifiedTransaction(BaseModel):
    """
    Classified and enriched transaction.

    Contains entity tagging and classification information.
    """

    txid: str = Field(..., description="Transaction ID")
    seen_at: datetime = Field(..., description="When the transaction was seen")
    network: str = Field(..., description="Network: mainnet, testnet, or regtest")
    total_value_out_btc: float = Field(..., description="Total output value in BTC")
    total_value_usd: float | None = Field(None, description="Total value in USD if available")
    primary_type: TransactionType = Field(..., description="Primary classification type")
    types: list[TransactionType] = Field(
        default_factory=list, description="All applicable classification types"
    )
    inputs: list[EnrichedInput] = Field(default_factory=list, description="Enriched inputs")
    outputs: list[EnrichedOutput] = Field(default_factory=list, description="Enriched outputs")
    raw_hex: str | None = Field(None, description="Raw transaction hex")

    model_config = {"from_attributes": True}


class EntityCategory(str, Enum):
    """Categories for entity tags."""

    EXCHANGE_DEPOSIT = "exchange_deposit"
    EXCHANGE_HOT = "exchange_hot"
    EXCHANGE_COLD = "exchange_cold"
    EXCHANGE_COLD_STORAGE = "exchange_cold_storage"
    ETF_CUSTODY = "etf_custody"
    OTC_ENTITY = "otc_entity"
    OTC_DESK = "otc_desk"
    MINING_POOL = "mining_pool"
    CUSTODIAN = "custodian"
    GOVERNMENT = "government"
    UNKNOWN = "unknown"


class EntityTag(BaseModel):
    """Entity tag for address identification."""

    id: int | None = Field(None, description="Database ID")
    address: str = Field(..., description="Bitcoin address")
    label: str = Field(..., description="Entity label (e.g., 'Binance')")
    category: EntityCategory = Field(..., description="Entity category")
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Confidence score 0-1"
    )
    source: str = Field(default="manual", description="Source of the tag")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"from_attributes": True}


class EntityTagCreate(BaseModel):
    """Schema for creating a new entity tag."""

    address: str = Field(..., description="Bitcoin address")
    label: str = Field(..., description="Entity label")
    category: EntityCategory = Field(..., description="Entity category")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str = Field(default="manual")


class WhaleEventType(str, Enum):
    """Types of whale events."""

    WH_EXCHANGE_SINGLE_DEPOSIT = "WH_EXCHANGE_SINGLE_DEPOSIT"
    WH_EXCHANGE_DEPOSIT_BURST = "WH_EXCHANGE_DEPOSIT_BURST"
    WH_EXCHANGE_BULK_OUTFLOW = "WH_EXCHANGE_BULK_OUTFLOW"
    WH_EXCHANGE_SINGLE_WITHDRAWAL = "WH_EXCHANGE_SINGLE_WITHDRAWAL"
    WH_OTC_LARGE_MOVE = "WH_OTC_LARGE_MOVE"
    WH_UNKNOWN_LARGE_ACTIVITY = "WH_UNKNOWN_LARGE_ACTIVITY"


class EventEntity(BaseModel):
    """Entity involved in a whale event."""

    label: str = Field(..., description="Entity label")
    category: str = Field(..., description="Entity category")
    confidence: float = Field(default=1.0, description="Confidence score")


class WhaleEvent(BaseModel):
    """
    A whale event representing significant blockchain activity.

    Events are clustered from one or more classified transactions.
    """

    event_id: UUID = Field(default_factory=uuid4, description="Unique event ID")
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="When the event was created"
    )
    window_start: datetime = Field(..., description="Start of the event window")
    window_end: datetime = Field(..., description="End of the event window")
    network: str = Field(..., description="Network: mainnet, testnet, or regtest")
    event_type: WhaleEventType = Field(..., description="Type of whale event")
    entities: list[EventEntity] = Field(
        default_factory=list, description="Entities involved in the event"
    )
    total_value_btc: float = Field(..., description="Total value in BTC")
    total_value_usd: float | None = Field(None, description="Total value in USD")
    txids: list[str] = Field(default_factory=list, description="Transaction IDs in this event")
    summary: str = Field(..., description="Human-readable summary of the event")

    model_config = {"from_attributes": True}


class WebhookPayload(BaseModel):
    """Payload sent to webhook subscribers."""

    event_id: UUID = Field(..., description="Event ID")
    event_type: WhaleEventType = Field(..., description="Event type")
    created_at: datetime = Field(..., description="Creation timestamp")
    network: str = Field(..., description="Network")
    summary: str = Field(..., description="Event summary")
    total_value_btc: float = Field(..., description="Total BTC value")
    total_value_usd: float | None = Field(None, description="Total USD value")
    entities: list[EventEntity] = Field(default_factory=list)
    txids: list[str] = Field(default_factory=list)


class HealthStatus(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Service status")
    version: str = Field(..., description="Application version")
    database: str = Field(..., description="Database connection status")
    redis: str = Field(..., description="Redis connection status")
    zmq: str = Field(default="unknown", description="ZMQ connection status")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper."""

    items: list[Any] = Field(..., description="List of items")
    total: int = Field(..., description="Total number of items")
    limit: int = Field(..., description="Items per page")
    offset: int = Field(..., description="Current offset")
