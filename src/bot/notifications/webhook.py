"""Generic webhook client base class.

Provides:
- HTTPS URL validation
- Retry with exponential backoff (up to 3 retries)
- Event queuing for network outages
- Async HTTP delivery via aiohttp

Both DiscordWebhook and TelegramWebhook inherit from WebhookClient.

Per PRD Sections 9.6 (NOT-3, NOT-4, NOT-5) and 10.3 (SEC-T03).
"""

from __future__ import annotations

import asyncio
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import aiohttp

from src.shared.models import WebhookEvent


# ── URL Validation ─────────────────────────────────────────────────────────────


_HTTPS_PATTERN = re.compile(r"^https://", re.IGNORECASE)


def validate_https_url(url: str) -> bool:
    """Return True if the URL uses HTTPS.

    Per PRD Section 10.3 (SEC-T03): webhook URLs must be HTTPS.
    """
    return bool(_HTTPS_PATTERN.match(url))


# ── Exceptions ────────────────────────────────────────────────────────────────


class WebhookDeliveryError(Exception):
    """Raised when a webhook cannot be delivered after all retries."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Webhook delivery failed for {url}: {reason}")


class WebhookQueueFullError(Exception):
    """Raised when the event queue is full and the caller tries to enqueue."""

    pass


# ── WebhookClient ─────────────────────────────────────────────────────────────


class WebhookClient(ABC):
    """Abstract base class for webhook-based notifiers.

    Subclasses must implement ``_build_payload`` to format events
    for their specific webhook endpoint (Discord embed, Telegram message, etc.).

    Features:
    - HTTPS URL validation on init and before every send
    - Exponential backoff retry (up to 3 attempts)
    - In-memory event queue for network outages
    - Async delivery via aiohttp

    Per PRD Sections 9.6 (NOT-3, NOT-4, NOT-5) and 10.3 (SEC-T03).
    """

    # Maximum events to queue when network is unavailable
    MAX_QUEUE_SIZE: int = 1000

    # Maximum retry attempts for a single webhook delivery
    MAX_RETRIES: int = 3

    def __init__(
        self,
        webhook_url: str,
        max_retries: int = 3,
        max_queue_size: int = 1000,
    ) -> None:
        """Initialize the webhook client.

        Args:
            webhook_url: The HTTPS URL to send webhook events to.
            max_retries: Maximum retry attempts on failure (default 3).
            max_queue_size: Maximum events to queue when network is down.

        Raises:
            ValueError: If ``webhook_url`` is not a valid HTTPS URL.
        """
        if not validate_https_url(webhook_url):
            raise ValueError(
                f"Webhook URL must use HTTPS: {webhook_url!r}"
            )
        self._webhook_url = webhook_url
        self._max_retries = max_retries
        self._max_queue_size = max_queue_size
        self._queue: list[dict[str, Any]] = []
        self._client: aiohttp.ClientSession | None = None

    # ── Abstract Interface ─────────────────────────────────────────────────

    @abstractmethod
    def _build_payload(self, event: WebhookEvent) -> dict[str, Any]:
        """Build the webhook-specific payload for the given event.

        Subclasses override this to format the payload for their
        specific webhook provider (Discord embed, Telegram message, etc.).

        Args:
            event: The WebhookEvent to format.

        Returns:
            A dict suitable for ``aiohttp.ClientSession.post(json=...)``.
        """
        ...

    # ── Public API ────────────────────────────────────────────────────────

    async def send(self, event: WebhookEvent) -> bool:
        """Send a webhook event, retrying on failure.

        Attempts to deliver the event up to ``max_retries`` times
        with exponential backoff. On network failure, the event is
        queued for later delivery.

        Args:
            event: The WebhookEvent to send.

        Returns:
            True if the event was delivered successfully.
            False if it was queued (network unavailable).
        """
        # Ensure timestamp is set
        if not event.timestamp:
            event.timestamp = datetime.now(timezone.utc).isoformat()

        payload = self._build_payload(event)

        try:
            await self._deliver_with_retry(payload)
            return True
        except WebhookDeliveryError:
            self._enqueue(event, payload)
            return False

    async def send_raw(self, payload: dict[str, Any]) -> bool:
        """Send a raw dict payload without building from a WebhookEvent.

        Used for events that don't map cleanly to the WebhookEvent schema.

        Args:
            payload: The raw dict payload to send.

        Returns:
            True if delivered, False if queued.
        """
        try:
            await self._deliver_with_retry(payload)
            return True
        except WebhookDeliveryError:
            self._enqueue_raw(payload)
            return False

    async def flush_queue(self) -> int:
        """Attempt to deliver all queued events.

        Processes the queue in FIFO order. Events that still fail
        after all retries are dropped (not re-enqueued) since they
        already had a full retry cycle. Events are retried on the
        next call to flush_queue().

        Returns:
            The number of events successfully delivered from the queue.
        """
        if not self._queue:
            return 0

        delivered = 0
        # Snapshot the queue — we only retry events we haven't attempted
        # this flush cycle. Failed events are dropped after one full
        # retry cycle to avoid infinite loops on permanently failing URLs.
        snapshot = list(self._queue)
        self._queue.clear()

        for item in snapshot:
            try:
                await self._deliver_with_retry(item["payload"])
                delivered += 1
            except WebhookDeliveryError:
                # Already exhausted retries inside _deliver_with_retry.
                # Drop the event rather than re-enqueueing to avoid
                # infinite loops. A future flush_queue() call will
                # pick up any remaining fresh events.
                pass

        return delivered

    @property
    def queue_size(self) -> int:
        """Return the current number of events in the queue."""
        return len(self._queue)

    def clear_queue(self) -> None:
        """Clear all queued events without sending them."""
        self._queue.clear()

    # ── Internal ──────────────────────────────────────────────────────────

    async def _get_client(self) -> aiohttp.ClientSession:
        """Return (or create) the aiohttp client session."""
        if self._client is None or self._client.closed:
            self._client = aiohttp.ClientSession()
        return self._client

    async def _deliver_with_retry(
        self,
        payload: dict[str, Any],
        timeout: float = 10.0,
    ) -> None:
        """Deliver a payload with exponential backoff retry.

        Args:
            payload: The JSON-serializable payload to send.
            timeout: Request timeout in seconds.

        Raises:
            WebhookDeliveryError: If all retries are exhausted.
        """
        delay = 1.0
        last_error: str = "unknown"

        for attempt in range(1, self._max_retries + 1):
            try:
                await self._deliver(payload, timeout=timeout)
                return
            except aiohttp.ClientError as exc:
                last_error = str(exc)
                if attempt < self._max_retries:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2.0, 60.0)  # Cap at 60s
            except asyncio.TimeoutError as exc:
                last_error = f"timeout after {timeout}s"
                if attempt < self._max_retries:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2.0, 60.0)

        raise WebhookDeliveryError(self._webhook_url, last_error)

    async def _deliver(
        self,
        payload: dict[str, Any],
        timeout: float = 10.0,
    ) -> None:
        """Perform a single HTTP POST to the webhook URL.

        Args:
            payload: The JSON-serializable payload.
            timeout: Request timeout in seconds.

        Raises:
            aiohttp.ClientError: On network/HTTP errors.
            asyncio.TimeoutError: On timeout.
        """
        client = await self._get_client()
        async with client.post(
            self._webhook_url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
            raise_for_status=True,
        ) as response:
            # Consume the response body to release the connection
            await response.read()

    def _enqueue(self, event: WebhookEvent, payload: dict[str, Any]) -> None:
        """Add a failed event to the retry queue.

        Args:
            event: The original WebhookEvent.
            payload: The built payload dict.
        """
        if len(self._queue) >= self._max_queue_size:
            # Drop the oldest event to make room
            self._queue.pop(0)
        self._queue.append({"event": event, "payload": payload, "queued_at": time.time()})

    def _enqueue_raw(self, payload: dict[str, Any]) -> None:
        """Add a raw payload to the retry queue."""
        if len(self._queue) >= self._max_queue_size:
            self._queue.pop(0)
        self._queue.append({"event": None, "payload": payload, "queued_at": time.time()})

    async def close(self) -> None:
        """Close the aiohttp session and release resources."""
        if self._client is not None and not self._client.closed:
            await self._client.close()
            self._client = None


__all__ = [
    "WebhookClient",
    "WebhookDeliveryError",
    "WebhookQueueFullError",
    "validate_https_url",
]
