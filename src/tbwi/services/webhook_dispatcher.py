"""
Webhook Dispatcher Service for TBWI.

Delivers whale events to configured webhook endpoints with retry logic.
"""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime
from typing import Any

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from tbwi.config import get_settings
from tbwi.db.repository import WebhookDeliveryRepository
from tbwi.db.session import get_db_session, init_db
from tbwi.logging import get_logger, setup_logging
from tbwi.models.schemas import WebhookPayload, WhaleEvent
from tbwi.services.message_queue import get_message_queue, close_message_queue

logger = get_logger(__name__)


class WebhookDispatcher:
    """
    Webhook dispatcher for whale events.

    Delivers events to configured webhook URLs with retry logic
    and delivery tracking.
    """

    def __init__(
        self,
        webhook_urls: list[str] | None = None,
        max_retries: int | None = None,
        base_delay: float | None = None,
    ):
        settings = get_settings()
        self.enabled = settings.webhook.enabled
        self.webhook_urls = webhook_urls or settings.webhook.urls
        self.max_retries = max_retries or settings.webhook.retry_max_attempts
        self.base_delay = base_delay or settings.webhook.retry_base_delay_seconds

        self._running = False
        self._client: httpx.AsyncClient | None = None
        self._delivery_count = 0
        self._failure_count = 0

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def start(self) -> None:
        """Start the webhook dispatcher."""
        if not self.enabled:
            logger.info("Webhook dispatcher disabled")
            return

        if not self.webhook_urls:
            logger.warning("No webhook URLs configured")
            return

        logger.info(
            "Starting Webhook Dispatcher",
            webhook_count=len(self.webhook_urls),
            max_retries=self.max_retries,
        )

        # Initialize database
        await init_db()

        # Connect to message queue
        mq = await get_message_queue()

        # Subscribe to whale events
        await mq.subscribe("whale_event", self._process_event)

        self._running = True

        # Start consuming
        await mq.consume(
            "whale_event",
            consumer_group="webhook-dispatcher",
            consumer_name="dispatcher-1",
        )

    async def stop(self) -> None:
        """Stop the webhook dispatcher."""
        logger.info("Stopping Webhook Dispatcher")
        self._running = False

        mq = await get_message_queue()
        mq.stop()

        await self.close()
        await close_message_queue()

        logger.info(
            "Webhook Dispatcher stopped",
            deliveries=self._delivery_count,
            failures=self._failure_count,
        )

    async def _process_event(self, message: dict[str, Any]) -> None:
        """Process a whale event and dispatch to webhooks."""
        try:
            event = WhaleEvent.model_validate(message)

            # Create webhook payload
            payload = WebhookPayload(
                event_id=event.event_id,
                event_type=event.event_type,
                created_at=event.created_at,
                network=event.network,
                summary=event.summary,
                total_value_btc=event.total_value_btc,
                total_value_usd=event.total_value_usd,
                entities=event.entities,
                txids=event.txids,
            )

            # Dispatch to all webhook URLs
            await asyncio.gather(
                *[
                    self._deliver_webhook(url, payload)
                    for url in self.webhook_urls
                ],
                return_exceptions=True,
            )

        except Exception as e:
            logger.error("Error processing whale event for webhook", error=str(e))

    async def _deliver_webhook(
        self, url: str, payload: WebhookPayload
    ) -> None:
        """Deliver webhook with retry logic."""
        # Create delivery record
        async with get_db_session() as session:
            repo = WebhookDeliveryRepository(session)
            delivery = await repo.create(str(payload.event_id), url)
            delivery_id = delivery.id

        try:
            await self._send_with_retry(url, payload)

            # Update delivery status
            async with get_db_session() as session:
                repo = WebhookDeliveryRepository(session)
                await repo.update_status(delivery_id, "delivered", response_code=200)

            self._delivery_count += 1
            logger.info(
                "Webhook delivered",
                url=url,
                event_id=str(payload.event_id),
            )

        except Exception as e:
            # Update delivery status
            async with get_db_session() as session:
                repo = WebhookDeliveryRepository(session)
                await repo.update_status(
                    delivery_id,
                    "failed",
                    error_message=str(e),
                )

            self._failure_count += 1
            logger.error(
                "Webhook delivery failed",
                url=url,
                event_id=str(payload.event_id),
                error=str(e),
            )

    async def _send_with_retry(
        self, url: str, payload: WebhookPayload
    ) -> None:
        """Send webhook with exponential backoff retry."""

        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(
                multiplier=self.base_delay, min=1, max=60
            ),
            retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        )
        async def _send() -> None:
            client = await self._get_client()
            response = await client.post(
                url,
                json=payload.model_dump(mode="json"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "TBWI-Webhook/1.0",
                    "X-TBWI-Event-Type": payload.event_type.value,
                    "X-TBWI-Event-ID": str(payload.event_id),
                },
            )
            response.raise_for_status()

        await _send()

    async def dispatch_event(self, event: WhaleEvent) -> None:
        """
        Manually dispatch an event (for API use).

        Args:
            event: WhaleEvent to dispatch
        """
        if not self.enabled or not self.webhook_urls:
            return

        payload = WebhookPayload(
            event_id=event.event_id,
            event_type=event.event_type,
            created_at=event.created_at,
            network=event.network,
            summary=event.summary,
            total_value_btc=event.total_value_btc,
            total_value_usd=event.total_value_usd,
            entities=event.entities,
            txids=event.txids,
        )

        await asyncio.gather(
            *[
                self._deliver_webhook(url, payload)
                for url in self.webhook_urls
            ],
            return_exceptions=True,
        )


# Singleton instance
_dispatcher: WebhookDispatcher | None = None


def get_webhook_dispatcher() -> WebhookDispatcher:
    """Get the singleton webhook dispatcher instance."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = WebhookDispatcher()
    return _dispatcher


def main() -> None:
    """Main entry point for the webhook dispatcher service."""
    settings = get_settings()
    setup_logging(settings.log_level, json_output=settings.environment != "development")

    logger.info("Starting TBWI Webhook Dispatcher Service")

    dispatcher = WebhookDispatcher()

    # Handle shutdown signals
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown(sig: signal.Signals) -> None:
        logger.info("Received shutdown signal", signal=sig.name)
        loop.create_task(dispatcher.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: shutdown(s))

    try:
        loop.run_until_complete(dispatcher.start())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        loop.run_until_complete(dispatcher.stop())
        loop.close()


if __name__ == "__main__":
    main()
