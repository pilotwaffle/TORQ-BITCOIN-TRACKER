"""
Whale event endpoints for TBWI API.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from tbwi.api.deps import APIKey, DBSession
from tbwi.db.repository import WhaleEventRepository
from tbwi.logging import get_logger
from tbwi.models.schemas import WhaleEvent, WhaleEventType

logger = get_logger(__name__)
router = APIRouter()


@router.get("/whale-events", response_model=list[WhaleEvent])
async def get_whale_events(
    db: DBSession,
    api_key: APIKey,
    since: datetime | None = Query(
        None, description="Filter events since this timestamp (ISO8601)"
    ),
    event_type: WhaleEventType | None = Query(
        None, description="Filter by event type"
    ),
    entity_label: str | None = Query(
        None, description="Filter by entity label (e.g., 'Binance')"
    ),
    network: str | None = Query(
        None, description="Filter by network (mainnet, testnet, regtest)"
    ),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of events"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> list[WhaleEvent]:
    """
    Get whale events with optional filtering.

    Returns a list of whale events sorted by creation time (newest first).
    """
    repo = WhaleEventRepository(db)

    events = await repo.get_recent(
        network=network,
        event_type=event_type.value if event_type else None,
        entity_label=entity_label,
        since=since,
        limit=limit,
        offset=offset,
    )

    return events


@router.get("/whale-events/{event_id}", response_model=WhaleEvent)
async def get_whale_event(
    event_id: UUID,
    db: DBSession,
    api_key: APIKey,
) -> WhaleEvent:
    """
    Get a specific whale event by ID.
    """
    repo = WhaleEventRepository(db)
    event = await repo.get_by_id(event_id)

    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found",
        )

    return event


@router.get("/whale-events/stats/summary")
async def get_event_stats(
    db: DBSession,
    api_key: APIKey,
    network: str | None = Query(None, description="Filter by network"),
    since: datetime | None = Query(None, description="Stats since this timestamp"),
) -> dict:
    """
    Get summary statistics for whale events.
    """
    repo = WhaleEventRepository(db)

    # Get counts by event type
    stats = {}
    for event_type in WhaleEventType:
        count = await repo.count(
            network=network,
            event_type=event_type.value,
            since=since,
        )
        stats[event_type.value] = count

    total = sum(stats.values())

    return {
        "total_events": total,
        "by_type": stats,
        "network": network or "all",
        "since": since.isoformat() if since else None,
    }


# Agent-friendly endpoints
@router.get("/agent/whale_events/latest", response_model=list[WhaleEvent])
async def get_latest_whale_events_for_agent(
    db: DBSession,
    api_key: APIKey,
    count: int = Query(10, ge=1, le=100, description="Number of events"),
) -> list[WhaleEvent]:
    """
    Get the latest whale events (agent-friendly endpoint).

    This endpoint is designed for AI trading/analytics agents.
    """
    repo = WhaleEventRepository(db)
    return await repo.get_recent(limit=count)


@router.get("/agent/whale_events/{event_id}/details")
async def get_whale_event_details_for_agent(
    event_id: UUID,
    db: DBSession,
    api_key: APIKey,
) -> dict:
    """
    Get detailed whale event information (agent-friendly endpoint).

    Returns enriched information suitable for AI agent processing.
    """
    repo = WhaleEventRepository(db)
    event = await repo.get_by_id(event_id)

    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found",
        )

    # Return agent-friendly format
    return {
        "event_id": str(event.event_id),
        "type": event.event_type.value,
        "summary": event.summary,
        "network": event.network,
        "timestamp": event.created_at.isoformat(),
        "window": {
            "start": event.window_start.isoformat(),
            "end": event.window_end.isoformat(),
            "duration_seconds": (event.window_end - event.window_start).total_seconds(),
        },
        "value": {
            "btc": event.total_value_btc,
            "usd": event.total_value_usd,
        },
        "entities": [
            {
                "name": e.label,
                "type": e.category,
                "confidence": e.confidence,
            }
            for e in event.entities
        ],
        "transaction_count": len(event.txids),
        "transactions": event.txids,
    }
