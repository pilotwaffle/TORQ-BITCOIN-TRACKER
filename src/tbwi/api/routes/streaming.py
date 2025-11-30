"""
Real-time streaming endpoints for TBWI API.

Provides WebSocket and Server-Sent Events (SSE) endpoints for
real-time whale event notifications.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.responses import StreamingResponse
from starlette.websockets import WebSocketState

from tbwi.logging import get_logger
from tbwi.services.message_queue import get_message_queue
from tbwi.services.metrics import WEBSOCKET_CONNECTIONS, API_ACTIVE_CONNECTIONS

logger = get_logger(__name__)
router = APIRouter()


# =============================================================================
# WebSocket Connection Manager
# =============================================================================

class ConnectionManager:
    """Manages WebSocket connections for broadcasting whale events."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and store a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
            WEBSOCKET_CONNECTIONS.set(len(self.active_connections))
        logger.info(
            "WebSocket client connected",
            total_connections=len(self.active_connections),
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
                WEBSOCKET_CONNECTIONS.set(len(self.active_connections))
        logger.info(
            "WebSocket client disconnected",
            total_connections=len(self.active_connections),
        )

    async def broadcast(self, message: dict) -> None:
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return

        disconnected = []
        async with self._lock:
            for connection in self.active_connections:
                try:
                    if connection.client_state == WebSocketState.CONNECTED:
                        await connection.send_json(message)
                except Exception as e:
                    logger.warning("Failed to send to WebSocket", error=str(e))
                    disconnected.append(connection)

            # Remove disconnected clients
            for conn in disconnected:
                if conn in self.active_connections:
                    self.active_connections.remove(conn)
            if disconnected:
                WEBSOCKET_CONNECTIONS.set(len(self.active_connections))

    async def send_personal(self, websocket: WebSocket, message: dict) -> None:
        """Send a message to a specific client."""
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(message)
        except Exception as e:
            logger.warning("Failed to send personal WebSocket message", error=str(e))


# Global connection manager
manager = ConnectionManager()


# =============================================================================
# WebSocket Endpoint
# =============================================================================

@router.websocket("/ws/whale-events")
async def websocket_whale_events(
    websocket: WebSocket,
    event_types: str | None = Query(
        None, description="Comma-separated event types to filter"
    ),
    min_btc: float | None = Query(
        None, description="Minimum BTC value to receive"
    ),
):
    """
    WebSocket endpoint for real-time whale events.

    Connect to receive whale events as they occur.

    Filters (optional query params):
    - event_types: Comma-separated list of event types
    - min_btc: Minimum BTC value threshold

    Message format:
    ```json
    {
        "type": "whale_event",
        "data": {
            "event_id": "uuid",
            "event_type": "WH_EXCHANGE_SINGLE_DEPOSIT",
            "total_value_btc": 1500.0,
            ...
        }
    }
    ```
    """
    await manager.connect(websocket)

    # Parse filters
    filter_types = None
    if event_types:
        filter_types = set(t.strip() for t in event_types.split(","))

    try:
        # Send welcome message
        await manager.send_personal(websocket, {
            "type": "connected",
            "message": "Connected to TBWI whale event stream",
            "filters": {
                "event_types": list(filter_types) if filter_types else None,
                "min_btc": min_btc,
            },
            "timestamp": datetime.utcnow().isoformat(),
        })

        # Subscribe to whale events from message queue
        mq = await get_message_queue()

        # Create a task to consume whale events
        async def event_consumer():
            """Consume whale events and send to this WebSocket."""
            while websocket.client_state == WebSocketState.CONNECTED:
                try:
                    # Get recent messages (polling approach)
                    messages = await mq.get_recent_messages("whale_event", count=1)
                    for msg in messages:
                        # Apply filters
                        if filter_types and msg.get("event_type") not in filter_types:
                            continue
                        if min_btc and msg.get("total_value_btc", 0) < min_btc:
                            continue

                        await manager.send_personal(websocket, {
                            "type": "whale_event",
                            "data": msg,
                            "timestamp": datetime.utcnow().isoformat(),
                        })

                    await asyncio.sleep(0.5)  # Poll every 500ms
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Error in WebSocket event consumer", error=str(e))
                    await asyncio.sleep(1)

        consumer_task = asyncio.create_task(event_consumer())

        try:
            # Keep connection alive and handle client messages
            while True:
                data = await websocket.receive_text()
                try:
                    message = json.loads(data)

                    # Handle ping/pong
                    if message.get("type") == "ping":
                        await manager.send_personal(websocket, {
                            "type": "pong",
                            "timestamp": datetime.utcnow().isoformat(),
                        })

                    # Handle filter updates
                    elif message.get("type") == "update_filters":
                        new_filters = message.get("filters", {})
                        if "event_types" in new_filters:
                            filter_types = set(new_filters["event_types"]) if new_filters["event_types"] else None
                        if "min_btc" in new_filters:
                            min_btc = new_filters.get("min_btc")
                        await manager.send_personal(websocket, {
                            "type": "filters_updated",
                            "filters": {
                                "event_types": list(filter_types) if filter_types else None,
                                "min_btc": min_btc,
                            },
                            "timestamp": datetime.utcnow().isoformat(),
                        })

                except json.JSONDecodeError:
                    await manager.send_personal(websocket, {
                        "type": "error",
                        "message": "Invalid JSON",
                    })

        finally:
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)


# =============================================================================
# Server-Sent Events (SSE) Endpoint
# =============================================================================

async def event_generator(
    request: Request,
    event_types: set[str] | None = None,
    min_btc: float | None = None,
) -> AsyncGenerator[str, None]:
    """
    Generate SSE events for whale activity.

    Args:
        request: FastAPI request object
        event_types: Set of event types to filter
        min_btc: Minimum BTC value threshold

    Yields:
        SSE formatted event strings
    """
    API_ACTIVE_CONNECTIONS.inc()

    try:
        # Send initial connection event
        yield f"event: connected\ndata: {json.dumps({'message': 'Connected to TBWI event stream', 'timestamp': datetime.utcnow().isoformat()})}\n\n"

        mq = await get_message_queue()
        last_event_id: str | None = None

        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            try:
                # Get recent whale events
                messages = await mq.get_recent_messages("whale_event", count=10)

                for msg in messages:
                    # Skip if already sent
                    event_id = msg.get("event_id")
                    if event_id and event_id == last_event_id:
                        continue

                    # Apply filters
                    if event_types and msg.get("event_type") not in event_types:
                        continue
                    if min_btc and msg.get("total_value_btc", 0) < min_btc:
                        continue

                    last_event_id = event_id

                    # Format as SSE
                    event_data = json.dumps(msg)
                    yield f"id: {event_id}\nevent: whale_event\ndata: {event_data}\n\n"

                # Send heartbeat every 15 seconds to keep connection alive
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.utcnow().isoformat()})}\n\n"

                await asyncio.sleep(1)  # Poll every second

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in SSE generator", error=str(e))
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                await asyncio.sleep(5)

    finally:
        API_ACTIVE_CONNECTIONS.dec()


@router.get("/events/stream")
async def stream_whale_events(
    request: Request,
    event_types: str | None = Query(
        None, description="Comma-separated event types to filter"
    ),
    min_btc: float | None = Query(
        None, ge=0, description="Minimum BTC value to receive"
    ),
):
    """
    Server-Sent Events (SSE) endpoint for whale events.

    Returns a stream of whale events as they occur.
    This is a lighter-weight alternative to WebSocket.

    Usage with curl:
    ```
    curl -N http://localhost:8000/api/v1/events/stream
    ```

    Usage with JavaScript:
    ```javascript
    const evtSource = new EventSource('/api/v1/events/stream');
    evtSource.addEventListener('whale_event', (event) => {
        const data = JSON.parse(event.data);
        console.log('Whale event:', data);
    });
    ```

    Event types:
    - connected: Initial connection confirmation
    - whale_event: Whale activity event
    - heartbeat: Keep-alive signal (every 15s)
    - error: Error notification
    """
    # Parse filters
    filter_types = None
    if event_types:
        filter_types = set(t.strip() for t in event_types.split(","))

    return StreamingResponse(
        event_generator(request, filter_types, min_btc),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# =============================================================================
# Broadcast Function (for use by other services)
# =============================================================================

async def broadcast_whale_event(event: dict) -> None:
    """
    Broadcast a whale event to all connected WebSocket clients.

    Args:
        event: Whale event data to broadcast
    """
    await manager.broadcast({
        "type": "whale_event",
        "data": event,
        "timestamp": datetime.utcnow().isoformat(),
    })


def get_active_connections_count() -> int:
    """Get the number of active WebSocket connections."""
    return len(manager.active_connections)
