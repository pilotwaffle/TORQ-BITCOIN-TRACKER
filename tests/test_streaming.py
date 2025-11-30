"""
Tests for the Streaming API (WebSocket and SSE).
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.websockets import WebSocketState

from tbwi.api.routes.streaming import (
    ConnectionManager,
    get_active_connections_count,
)


class TestConnectionManager:
    """Tests for ConnectionManager."""

    @pytest.fixture
    def manager(self):
        """Create a connection manager instance."""
        return ConnectionManager()

    @pytest.fixture
    def mock_websocket(self):
        """Create a mock WebSocket."""
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        return ws

    @pytest.mark.asyncio
    async def test_connect(self, manager, mock_websocket):
        """Test WebSocket connection."""
        await manager.connect(mock_websocket)

        mock_websocket.accept.assert_called_once()
        assert mock_websocket in manager.active_connections
        assert len(manager.active_connections) == 1

    @pytest.mark.asyncio
    async def test_disconnect(self, manager, mock_websocket):
        """Test WebSocket disconnection."""
        await manager.connect(mock_websocket)
        await manager.disconnect(mock_websocket)

        assert mock_websocket not in manager.active_connections
        assert len(manager.active_connections) == 0

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self, manager, mock_websocket):
        """Test disconnecting a WebSocket that wasn't connected."""
        # Should not raise
        await manager.disconnect(mock_websocket)
        assert len(manager.active_connections) == 0

    @pytest.mark.asyncio
    async def test_broadcast_empty(self, manager):
        """Test broadcast with no connections."""
        # Should not raise
        await manager.broadcast({"type": "test"})

    @pytest.mark.asyncio
    async def test_broadcast_to_connected(self, manager, mock_websocket):
        """Test broadcast to connected clients."""
        await manager.connect(mock_websocket)

        message = {"type": "whale_event", "data": {"value": 100}}
        await manager.broadcast(message)

        mock_websocket.send_json.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_broadcast_handles_failed_send(self, manager):
        """Test that broadcast handles failed sends gracefully."""
        ws1 = MagicMock()
        ws1.accept = AsyncMock()
        ws1.send_json = AsyncMock(side_effect=Exception("Connection lost"))
        ws1.client_state = WebSocketState.CONNECTED

        ws2 = MagicMock()
        ws2.accept = AsyncMock()
        ws2.send_json = AsyncMock()
        ws2.client_state = WebSocketState.CONNECTED

        await manager.connect(ws1)
        await manager.connect(ws2)

        await manager.broadcast({"type": "test"})

        # ws1 should be removed due to error
        assert ws1 not in manager.active_connections
        # ws2 should still be connected
        assert ws2 in manager.active_connections
        ws2.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_personal(self, manager, mock_websocket):
        """Test sending personal message."""
        await manager.connect(mock_websocket)

        message = {"type": "pong"}
        await manager.send_personal(mock_websocket, message)

        mock_websocket.send_json.assert_called_with(message)

    @pytest.mark.asyncio
    async def test_send_personal_disconnected(self, manager):
        """Test sending to disconnected WebSocket."""
        ws = MagicMock()
        ws.client_state = WebSocketState.DISCONNECTED
        ws.send_json = AsyncMock()

        # Should not raise and should not send
        await manager.send_personal(ws, {"type": "test"})
        ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_connections(self, manager):
        """Test multiple WebSocket connections."""
        connections = []
        for i in range(5):
            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.send_json = AsyncMock()
            ws.client_state = WebSocketState.CONNECTED
            connections.append(ws)
            await manager.connect(ws)

        assert len(manager.active_connections) == 5

        # Broadcast
        await manager.broadcast({"type": "test"})

        for ws in connections:
            ws.send_json.assert_called_once()

        # Disconnect all
        for ws in connections:
            await manager.disconnect(ws)

        assert len(manager.active_connections) == 0


class TestActiveConnectionsCount:
    """Tests for get_active_connections_count."""

    def test_initial_count(self):
        """Test initial connection count is 0."""
        # Note: This tests the global manager, which may have state from other tests
        count = get_active_connections_count()
        assert isinstance(count, int)
        assert count >= 0
