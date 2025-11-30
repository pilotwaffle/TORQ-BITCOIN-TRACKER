"""
Message queue abstraction for TBWI.

Provides a simple interface for publishing and subscribing to messages
using Redis streams.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as redis

from tbwi.config import get_settings
from tbwi.logging import get_logger

logger = get_logger(__name__)


class MessageQueue:
    """
    Message queue using Redis streams.

    Provides publish/subscribe functionality for internal communication
    between TBWI services.
    """

    def __init__(self, redis_url: str | None = None):
        settings = get_settings()
        self.redis_url = redis_url or settings.redis.url
        self._client: redis.Redis | None = None
        self._subscriptions: dict[str, list[Callable[[dict], Awaitable[None]]]] = {}
        self._running = False

    async def connect(self) -> None:
        """Connect to Redis."""
        if self._client is None:
            self._client = redis.from_url(self.redis_url, decode_responses=True)
            await self._client.ping()
            logger.info("Connected to Redis", url=self.redis_url)

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis connection closed")

    async def publish(self, channel: str, message: dict[str, Any]) -> str:
        """
        Publish a message to a channel.

        Args:
            channel: Channel name (stream key)
            message: Message data as dictionary

        Returns:
            Message ID from Redis stream
        """
        if self._client is None:
            await self.connect()

        # Convert message to Redis-compatible format
        # Redis streams require string values
        flat_message = {"data": json.dumps(message)}

        message_id = await self._client.xadd(
            f"tbwi:{channel}",
            flat_message,
            maxlen=10000,  # Keep last 10k messages
        )
        logger.debug("Message published", channel=channel, message_id=message_id)
        return message_id

    async def subscribe(
        self,
        channel: str,
        callback: Callable[[dict], Awaitable[None]],
        consumer_group: str = "default",
        consumer_name: str = "worker",
    ) -> None:
        """
        Subscribe to a channel with a callback.

        Args:
            channel: Channel name (stream key)
            callback: Async function to call for each message
            consumer_group: Consumer group name
            consumer_name: Consumer name within the group
        """
        stream_key = f"tbwi:{channel}"

        # Create consumer group if it doesn't exist
        try:
            await self._client.xgroup_create(
                stream_key, consumer_group, id="0", mkstream=True
            )
            logger.info(
                "Created consumer group",
                channel=channel,
                group=consumer_group,
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

        if channel not in self._subscriptions:
            self._subscriptions[channel] = []
        self._subscriptions[channel].append(callback)

    async def consume(
        self,
        channel: str,
        consumer_group: str = "default",
        consumer_name: str = "worker",
        batch_size: int = 10,
    ) -> None:
        """
        Start consuming messages from a channel.

        Args:
            channel: Channel name
            consumer_group: Consumer group name
            consumer_name: Consumer name
            batch_size: Number of messages to read at once
        """
        if self._client is None:
            await self.connect()

        stream_key = f"tbwi:{channel}"
        self._running = True

        # Create consumer group if needed
        try:
            await self._client.xgroup_create(
                stream_key, consumer_group, id="0", mkstream=True
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

        logger.info(
            "Starting consumer",
            channel=channel,
            group=consumer_group,
            consumer=consumer_name,
        )

        while self._running:
            try:
                # Read new messages
                messages = await self._client.xreadgroup(
                    consumer_group,
                    consumer_name,
                    {stream_key: ">"},
                    count=batch_size,
                    block=1000,  # 1 second timeout
                )

                if not messages:
                    continue

                for stream, stream_messages in messages:
                    for message_id, data in stream_messages:
                        try:
                            # Parse message data
                            message = json.loads(data.get("data", "{}"))

                            # Call all callbacks for this channel
                            for callback in self._subscriptions.get(channel, []):
                                await callback(message)

                            # Acknowledge message
                            await self._client.xack(stream_key, consumer_group, message_id)

                        except Exception as e:
                            logger.error(
                                "Error processing message",
                                channel=channel,
                                message_id=message_id,
                                error=str(e),
                            )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Consumer error", channel=channel, error=str(e))
                await asyncio.sleep(1)

        logger.info("Consumer stopped", channel=channel)

    def stop(self) -> None:
        """Stop consuming messages."""
        self._running = False

    async def get_recent_messages(
        self, channel: str, count: int = 100
    ) -> list[dict[str, Any]]:
        """
        Get recent messages from a channel.

        Args:
            channel: Channel name
            count: Number of messages to retrieve

        Returns:
            List of messages (newest last)
        """
        if self._client is None:
            await self.connect()

        stream_key = f"tbwi:{channel}"
        messages = await self._client.xrevrange(stream_key, count=count)

        result = []
        for message_id, data in reversed(messages):
            try:
                result.append(json.loads(data.get("data", "{}")))
            except json.JSONDecodeError:
                pass

        return result

    async def health_check(self) -> bool:
        """Check if Redis is healthy."""
        try:
            if self._client is None:
                await self.connect()
            await self._client.ping()
            return True
        except Exception as e:
            logger.error("Redis health check failed", error=str(e))
            return False


# Singleton instance
_message_queue: MessageQueue | None = None


async def get_message_queue() -> MessageQueue:
    """Get the singleton message queue instance."""
    global _message_queue
    if _message_queue is None:
        _message_queue = MessageQueue()
        await _message_queue.connect()
    return _message_queue


async def close_message_queue() -> None:
    """Close the singleton message queue."""
    global _message_queue
    if _message_queue is not None:
        await _message_queue.close()
        _message_queue = None
