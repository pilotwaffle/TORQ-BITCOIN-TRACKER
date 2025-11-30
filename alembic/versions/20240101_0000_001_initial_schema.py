"""Initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Entity tags table
    op.create_table(
        "entity_tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("address", sa.String(100), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True, default=1.0),
        sa.Column("source", sa.String(50), nullable=True, default="manual"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address"),
    )
    op.create_index("ix_entity_tags_address", "entity_tags", ["address"])
    op.create_index("ix_entity_tags_label", "entity_tags", ["label"])
    op.create_index("ix_entity_tags_category", "entity_tags", ["category"])

    # Classified transactions table
    op.create_table(
        "classified_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("txid", sa.String(64), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("network", sa.String(20), nullable=False),
        sa.Column("total_value_out_btc", sa.Float(), nullable=False),
        sa.Column("total_value_usd", sa.Float(), nullable=True),
        sa.Column("primary_type", sa.String(50), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("txid"),
    )
    op.create_index("ix_classified_tx_txid", "classified_transactions", ["txid"])
    op.create_index("ix_classified_tx_seen_at", "classified_transactions", ["seen_at"])
    op.create_index("ix_classified_tx_network", "classified_transactions", ["network"])
    op.create_index(
        "ix_classified_tx_primary_type", "classified_transactions", ["primary_type"]
    )
    op.create_index(
        "ix_classified_tx_value", "classified_transactions", ["total_value_out_btc"]
    )
    op.create_index(
        "ix_classified_tx_network_seen",
        "classified_transactions",
        ["network", "seen_at"],
    )
    op.create_index(
        "ix_classified_tx_type_value",
        "classified_transactions",
        ["primary_type", "total_value_out_btc"],
    )

    # Whale events table
    op.create_table(
        "whale_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("network", sa.String(20), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_value_btc", sa.Float(), nullable=False),
        sa.Column("total_value_usd", sa.Float(), nullable=True),
        sa.Column("entities_json", postgresql.JSONB(), nullable=True, default=[]),
        sa.Column("txids_json", postgresql.JSONB(), nullable=True, default=[]),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_whale_events_network", "whale_events", ["network"])
    op.create_index("ix_whale_events_event_type", "whale_events", ["event_type"])
    op.create_index("ix_whale_events_created_at", "whale_events", ["created_at"])
    op.create_index("ix_whale_events_value", "whale_events", ["total_value_btc"])
    op.create_index(
        "ix_whale_events_network_created", "whale_events", ["network", "created_at"]
    )
    op.create_index(
        "ix_whale_events_type_created", "whale_events", ["event_type", "created_at"]
    )

    # Webhook deliveries table
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("webhook_url", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=True, default=0),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_deliveries_event_id", "webhook_deliveries", ["event_id"])
    op.create_index("ix_webhook_deliveries_status", "webhook_deliveries", ["status"])
    op.create_index(
        "ix_webhook_deliveries_event_status",
        "webhook_deliveries",
        ["event_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("whale_events")
    op.drop_table("classified_transactions")
    op.drop_table("entity_tags")
