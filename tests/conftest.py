"""
Pytest configuration and fixtures for TBWI tests.
"""

import asyncio
from datetime import datetime
from typing import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from tbwi.db.models import Base
from tbwi.models.schemas import (
    ClassifiedTransaction,
    EnrichedOutput,
    EntityCategory,
    EntityTagCreate,
    NormalizedTransaction,
    TransactionOutput,
    TransactionType,
    WhaleEvent,
    WhaleEventType,
    EventEntity,
)


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session with in-memory SQLite."""
    # Use SQLite for testing
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def sample_normalized_tx() -> NormalizedTransaction:
    """Create a sample normalized transaction."""
    return NormalizedTransaction(
        txid="abc123def456",
        seen_at=datetime.utcnow(),
        network="testnet",
        total_value_out_btc=100.5,
        vout=[
            TransactionOutput(
                index=0,
                value_btc=100.5,
                script_type="p2wpkh",
                address="tb1qtest123",
            )
        ],
        size_bytes=250,
        raw_hex="0100000001...",
    )


@pytest.fixture
def sample_classified_tx() -> ClassifiedTransaction:
    """Create a sample classified transaction."""
    return ClassifiedTransaction(
        txid="abc123def456",
        seen_at=datetime.utcnow(),
        network="testnet",
        total_value_out_btc=100.5,
        total_value_usd=6500000.0,
        primary_type=TransactionType.EXCHANGE_DEPOSIT_CANDIDATE,
        types=[
            TransactionType.EXCHANGE_DEPOSIT_CANDIDATE,
            TransactionType.LARGE_SINGLE_OUTPUT,
        ],
        inputs=[],
        outputs=[
            EnrichedOutput(
                index=0,
                address="tb1qtest123",
                value_btc=100.5,
                script_type="p2wpkh",
                entity_label="Binance",
                entity_category="exchange_deposit",
            )
        ],
        raw_hex="0100000001...",
    )


@pytest.fixture
def sample_whale_event() -> WhaleEvent:
    """Create a sample whale event."""
    return WhaleEvent(
        event_id=uuid4(),
        window_start=datetime.utcnow(),
        window_end=datetime.utcnow(),
        network="testnet",
        event_type=WhaleEventType.WH_EXCHANGE_SINGLE_DEPOSIT,
        entities=[
            EventEntity(
                label="Binance",
                category="exchange",
                confidence=0.95,
            )
        ],
        total_value_btc=1500.0,
        total_value_usd=97500000.0,
        txids=["abc123def456"],
        summary="Massive deposit of 1,500 BTC to Binance",
    )


@pytest.fixture
def sample_entity_tag() -> EntityTagCreate:
    """Create a sample entity tag."""
    return EntityTagCreate(
        address="tb1qtest123",
        label="Binance",
        category=EntityCategory.EXCHANGE_DEPOSIT,
        confidence=0.95,
        source="test",
    )
