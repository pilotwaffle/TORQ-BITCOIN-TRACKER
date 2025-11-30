"""
Database repository for TBWI.

Provides high-level database operations for transactions, events, and entity tags.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from tbwi.db.models import (
    ClassifiedTransactionModel,
    EntityTagModel,
    WhaleEventModel,
    WebhookDeliveryModel,
)
from tbwi.models.schemas import (
    ClassifiedTransaction,
    EntityTag,
    EntityTagCreate,
    WhaleEvent,
    WhaleEventType,
)


class EntityTagRepository:
    """Repository for entity tag operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_address(self, address: str) -> EntityTag | None:
        """Get entity tag by address."""
        result = await self.session.execute(
            select(EntityTagModel).where(EntityTagModel.address == address)
        )
        model = result.scalar_one_or_none()
        if model:
            return EntityTag.model_validate(model)
        return None

    async def get_by_addresses(self, addresses: list[str]) -> dict[str, EntityTag]:
        """Get entity tags for multiple addresses."""
        if not addresses:
            return {}
        result = await self.session.execute(
            select(EntityTagModel).where(EntityTagModel.address.in_(addresses))
        )
        models = result.scalars().all()
        return {m.address: EntityTag.model_validate(m) for m in models}

    async def get_by_label(self, label: str) -> list[EntityTag]:
        """Get all entity tags for a label."""
        result = await self.session.execute(
            select(EntityTagModel).where(EntityTagModel.label == label)
        )
        return [EntityTag.model_validate(m) for m in result.scalars().all()]

    async def create(self, tag: EntityTagCreate) -> EntityTag:
        """Create a new entity tag."""
        model = EntityTagModel(
            address=tag.address,
            label=tag.label,
            category=tag.category.value,
            confidence=tag.confidence,
            source=tag.source,
        )
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return EntityTag.model_validate(model)

    async def upsert(self, tag: EntityTagCreate) -> EntityTag:
        """Create or update an entity tag."""
        result = await self.session.execute(
            select(EntityTagModel).where(EntityTagModel.address == tag.address)
        )
        model = result.scalar_one_or_none()

        if model:
            model.label = tag.label
            model.category = tag.category.value
            model.confidence = tag.confidence
            model.source = tag.source
            model.updated_at = datetime.utcnow()
        else:
            model = EntityTagModel(
                address=tag.address,
                label=tag.label,
                category=tag.category.value,
                confidence=tag.confidence,
                source=tag.source,
            )
            self.session.add(model)

        await self.session.flush()
        await self.session.refresh(model)
        return EntityTag.model_validate(model)

    async def list_all(
        self, category: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[EntityTag]:
        """List entity tags with optional filtering."""
        query = select(EntityTagModel)
        if category:
            query = query.where(EntityTagModel.category == category)
        query = query.order_by(EntityTagModel.label).limit(limit).offset(offset)
        result = await self.session.execute(query)
        return [EntityTag.model_validate(m) for m in result.scalars().all()]


class TransactionRepository:
    """Repository for classified transaction operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_txid(self, txid: str) -> ClassifiedTransaction | None:
        """Get transaction by txid."""
        result = await self.session.execute(
            select(ClassifiedTransactionModel).where(
                ClassifiedTransactionModel.txid == txid
            )
        )
        model = result.scalar_one_or_none()
        if model:
            return ClassifiedTransaction.model_validate(model.raw_json)
        return None

    async def exists(self, txid: str) -> bool:
        """Check if a transaction exists."""
        result = await self.session.execute(
            select(func.count()).where(ClassifiedTransactionModel.txid == txid)
        )
        return result.scalar() > 0

    async def create(self, tx: ClassifiedTransaction) -> ClassifiedTransaction:
        """Create a new classified transaction."""
        model = ClassifiedTransactionModel(
            txid=tx.txid,
            seen_at=tx.seen_at,
            network=tx.network,
            total_value_out_btc=tx.total_value_out_btc,
            total_value_usd=tx.total_value_usd,
            primary_type=tx.primary_type.value,
            raw_json=tx.model_dump(mode="json"),
        )
        self.session.add(model)
        await self.session.flush()
        return tx

    async def get_recent(
        self,
        network: str | None = None,
        primary_type: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ClassifiedTransaction]:
        """Get recent classified transactions."""
        query = select(ClassifiedTransactionModel)

        conditions = []
        if network:
            conditions.append(ClassifiedTransactionModel.network == network)
        if primary_type:
            conditions.append(ClassifiedTransactionModel.primary_type == primary_type)
        if since:
            conditions.append(ClassifiedTransactionModel.seen_at >= since)

        if conditions:
            query = query.where(and_(*conditions))

        query = (
            query.order_by(ClassifiedTransactionModel.seen_at.desc())
            .limit(limit)
            .offset(offset)
        )

        result = await self.session.execute(query)
        return [
            ClassifiedTransaction.model_validate(m.raw_json)
            for m in result.scalars().all()
        ]

    async def get_for_clustering(
        self,
        network: str,
        since: datetime,
        until: datetime,
        min_value_btc: float | None = None,
    ) -> list[ClassifiedTransaction]:
        """Get transactions for clustering within a time window."""
        query = select(ClassifiedTransactionModel).where(
            and_(
                ClassifiedTransactionModel.network == network,
                ClassifiedTransactionModel.seen_at >= since,
                ClassifiedTransactionModel.seen_at <= until,
            )
        )

        if min_value_btc:
            query = query.where(
                ClassifiedTransactionModel.total_value_out_btc >= min_value_btc
            )

        query = query.order_by(ClassifiedTransactionModel.seen_at)
        result = await self.session.execute(query)
        return [
            ClassifiedTransaction.model_validate(m.raw_json)
            for m in result.scalars().all()
        ]


class WhaleEventRepository:
    """Repository for whale event operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, event_id: str | UUID) -> WhaleEvent | None:
        """Get whale event by ID."""
        event_id_str = str(event_id)
        result = await self.session.execute(
            select(WhaleEventModel).where(WhaleEventModel.id == event_id_str)
        )
        model = result.scalar_one_or_none()
        if model:
            return self._model_to_schema(model)
        return None

    async def create(self, event: WhaleEvent) -> WhaleEvent:
        """Create a new whale event."""
        model = WhaleEventModel(
            id=str(event.event_id),
            network=event.network,
            event_type=event.event_type.value,
            window_start=event.window_start,
            window_end=event.window_end,
            total_value_btc=event.total_value_btc,
            total_value_usd=event.total_value_usd,
            entities_json=[e.model_dump() for e in event.entities],
            txids_json=event.txids,
            summary=event.summary,
        )
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return self._model_to_schema(model)

    async def get_recent(
        self,
        network: str | None = None,
        event_type: str | None = None,
        entity_label: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WhaleEvent]:
        """Get recent whale events with filtering."""
        query = select(WhaleEventModel)

        conditions = []
        if network:
            conditions.append(WhaleEventModel.network == network)
        if event_type:
            conditions.append(WhaleEventModel.event_type == event_type)
        if since:
            conditions.append(WhaleEventModel.created_at >= since)

        if conditions:
            query = query.where(and_(*conditions))

        query = (
            query.order_by(WhaleEventModel.created_at.desc()).limit(limit).offset(offset)
        )

        result = await self.session.execute(query)
        events = [self._model_to_schema(m) for m in result.scalars().all()]

        # Filter by entity label if specified (requires post-query filtering due to JSONB)
        if entity_label:
            events = [
                e
                for e in events
                if any(ent.label == entity_label for ent in e.entities)
            ]

        return events

    async def count(
        self,
        network: str | None = None,
        event_type: str | None = None,
        since: datetime | None = None,
    ) -> int:
        """Count whale events with filtering."""
        query = select(func.count(WhaleEventModel.id))

        conditions = []
        if network:
            conditions.append(WhaleEventModel.network == network)
        if event_type:
            conditions.append(WhaleEventModel.event_type == event_type)
        if since:
            conditions.append(WhaleEventModel.created_at >= since)

        if conditions:
            query = query.where(and_(*conditions))

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def check_duplicate(
        self,
        event_type: WhaleEventType,
        network: str,
        window_start: datetime,
        window_end: datetime,
        txids: list[str],
    ) -> bool:
        """Check if a similar event already exists (deduplication)."""
        # Check for events with overlapping time windows and any shared txids
        result = await self.session.execute(
            select(WhaleEventModel).where(
                and_(
                    WhaleEventModel.event_type == event_type.value,
                    WhaleEventModel.network == network,
                    or_(
                        and_(
                            WhaleEventModel.window_start <= window_end,
                            WhaleEventModel.window_end >= window_start,
                        )
                    ),
                )
            )
        )
        existing = result.scalars().all()

        for e in existing:
            # Check for txid overlap
            existing_txids = set(e.txids_json or [])
            if existing_txids.intersection(txids):
                return True

        return False

    def _model_to_schema(self, model: WhaleEventModel) -> WhaleEvent:
        """Convert database model to Pydantic schema."""
        from tbwi.models.schemas import EventEntity

        return WhaleEvent(
            event_id=UUID(model.id),
            created_at=model.created_at,
            window_start=model.window_start,
            window_end=model.window_end,
            network=model.network,
            event_type=WhaleEventType(model.event_type),
            entities=[EventEntity(**e) for e in (model.entities_json or [])],
            total_value_btc=model.total_value_btc,
            total_value_usd=model.total_value_usd,
            txids=model.txids_json or [],
            summary=model.summary,
        )


class WebhookDeliveryRepository:
    """Repository for webhook delivery tracking."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, event_id: str | UUID, webhook_url: str
    ) -> WebhookDeliveryModel:
        """Create a new delivery record."""
        model = WebhookDeliveryModel(
            event_id=str(event_id),
            webhook_url=webhook_url,
            status="pending",
        )
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return model

    async def update_status(
        self,
        delivery_id: int,
        status: str,
        response_code: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update delivery status."""
        result = await self.session.execute(
            select(WebhookDeliveryModel).where(WebhookDeliveryModel.id == delivery_id)
        )
        model = result.scalar_one_or_none()
        if model:
            model.status = status
            model.attempts += 1
            model.last_attempt_at = datetime.utcnow()
            model.response_code = response_code
            model.error_message = error_message
            await self.session.flush()

    async def get_pending(self, limit: int = 100) -> list[WebhookDeliveryModel]:
        """Get pending deliveries for retry."""
        result = await self.session.execute(
            select(WebhookDeliveryModel)
            .where(WebhookDeliveryModel.status == "pending")
            .order_by(WebhookDeliveryModel.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())
