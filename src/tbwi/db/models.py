"""
SQLAlchemy database models for TBWI.
"""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class EntityTagModel(Base):
    """
    Entity tags for address identification.

    Maps Bitcoin addresses to known entities (exchanges, custodians, etc.).
    """

    __tablename__ = "entity_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(50), default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Indexes for common queries
    __table_args__ = (
        Index("ix_entity_tags_label", "label"),
        Index("ix_entity_tags_category", "category"),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "address": self.address,
            "label": self.label,
            "category": self.category,
            "confidence": self.confidence,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ClassifiedTransactionModel(Base):
    """
    Classified transactions that have been enriched and categorized.

    Stores transactions that meet the minimum threshold and have been processed.
    """

    __tablename__ = "classified_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    txid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    network: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    total_value_out_btc: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    total_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    primary_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Composite indexes for common query patterns
    __table_args__ = (
        Index("ix_classified_tx_network_seen", "network", "seen_at"),
        Index("ix_classified_tx_type_value", "primary_type", "total_value_out_btc"),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "txid": self.txid,
            "seen_at": self.seen_at.isoformat() if self.seen_at else None,
            "network": self.network,
            "total_value_out_btc": self.total_value_out_btc,
            "total_value_usd": self.total_value_usd,
            "primary_type": self.primary_type,
            "raw_json": self.raw_json,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class WhaleEventModel(Base):
    """
    Whale events representing significant blockchain activity.

    Events are aggregated from one or more classified transactions.
    """

    __tablename__ = "whale_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    network: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_value_btc: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    total_value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    entities_json: Mapped[list] = mapped_column(JSONB, default=list)
    txids_json: Mapped[list] = mapped_column(JSONB, default=list)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # Composite indexes for common query patterns
    __table_args__ = (
        Index("ix_whale_events_network_created", "network", "created_at"),
        Index("ix_whale_events_type_created", "event_type", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "event_id": self.id,
            "network": self.network,
            "event_type": self.event_type,
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "total_value_btc": self.total_value_btc,
            "total_value_usd": self.total_value_usd,
            "entities": self.entities_json,
            "txids": self.txids_json,
            "summary": self.summary,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class WebhookDeliveryModel(Base):
    """
    Webhook delivery tracking for retry and audit purposes.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    webhook_url: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_webhook_deliveries_status", "status"),
        Index("ix_webhook_deliveries_event_status", "event_id", "status"),
    )
