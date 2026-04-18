"""Tests for the webhook base client (WebhookClient).

Per PRD Sections 9.6 (NOT-3, NOT-4, NOT-5) and 10.3 (SEC-T03).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import aiohttp

from src.bot.notifications.webhook import (
    WebhookClient,
    WebhookDeliveryError,
    validate_https_url,
)
from src.shared.models import WebhookEvent


# ── Concrete test subclass ─────────────────────────────────────────────────


class ConcreteWebhookClient(WebhookClient):
    """Concrete implementation of WebhookClient for testing."""

    def _build_payload(self, event: WebhookEvent) -> dict[str, Any]:
        return {
            "event": event.event,
            "item": event.item,
            "retailer": event.retailer,
            "timestamp": event.timestamp,
        }


# ── validate_https_url ──────────────────────────────────────────────────────


class TestValidateHttpsUrl:
    """Tests for HTTPS URL validation (SEC-T03)."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://discord.com/api/webhooks/123",
            "HTTPS://discord.com/api/webhooks/123",
            "https://api.telegram.org/bot123",
            "https://example.com/",
            "https://a.b.c.d/e/f?x=1#anchor",
        ],
    )
    def test_valid_https(self, url: str) -> None:
        assert validate_https_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "http://discord.com/api/webhooks/123",
            "http://localhost:8080/webhook",
            "ftp://example.com/file",
            "://missing-scheme.com",
            "",
            "not-a-url",
        ],
    )
    def test_invalid_not_https(self, url: str) -> None:
        assert validate_https_url(url) is False


# ── WebhookClient init ─────────────────────────────────────────────────────


class TestWebhookClientInit:
    """Tests for WebhookClient initialization."""

    def test_raises_on_http_url(self) -> None:
        with pytest.raises(ValueError, match="must use HTTPS"):
            ConcreteWebhookClient(
                "http://discord.com/api/webhooks/123",
            )

    def test_raises_on_localhost_http(self) -> None:
        with pytest.raises(ValueError, match="must use HTTPS"):
            ConcreteWebhookClient("http://localhost:8080/webhook")

    def test_accepts_https_url(self) -> None:
        client = ConcreteWebhookClient("https://discord.com/api/webhooks/123")
        assert client._webhook_url == "https://discord.com/api/webhooks/123"
        assert client._max_retries == 3

    def test_custom_max_retries(self) -> None:
        client = ConcreteWebhookClient(
            "https://discord.com/api/webhooks/123",
            max_retries=5,
        )
        assert client._max_retries == 5

    def test_custom_queue_size(self) -> None:
        client = ConcreteWebhookClient(
            "https://discord.com/api/webhooks/123",
            max_queue_size=100,
        )
        assert client._max_queue_size == 100


# ── WebhookClient.send ─────────────────────────────────────────────────────


class TestWebhookClientSend:
    """Tests for WebhookClient.send()."""

    @pytest.fixture
    def client(self) -> ConcreteWebhookClient:
        return ConcreteWebhookClient("https://discord.com/api/webhooks/test123")

    @pytest.fixture
    def sample_event(self) -> WebhookEvent:
        return WebhookEvent(
            event="STOCK_DETECTED",
            item="Pikachu Plush",
            retailer="target",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    @pytest.mark.asyncio
    async def test_send_success(self, client: ConcreteWebhookClient, sample_event: WebhookEvent) -> None:
        """Successful delivery returns True without queuing."""
        mock_response = AsyncMock()
        mock_response.read = AsyncMock()
        mock_response.status = 200

        mock_post = AsyncMock()
        mock_post.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post)

        with patch.object(client, "_get_client", AsyncMock(return_value=mock_session)):
            result = await client.send(sample_event)

        assert result is True
        assert client.queue_size == 0

    @pytest.mark.asyncio
    async def test_send_sets_timestamp(self, client: ConcreteWebhookClient) -> None:
        """If event has no timestamp, send() sets one."""
        event = WebhookEvent(event="STOCK_DETECTED", item="Test", retailer="target")

        mock_response = AsyncMock()
        mock_response.read = AsyncMock()
        mock_response.status = 200

        mock_post = AsyncMock()
        mock_post.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post)

        with patch.object(client, "_get_client", AsyncMock(return_value=mock_session)):
            await client.send(event)

        assert event.timestamp != ""

    @pytest.mark.asyncio
    async def test_send_failure_queues_event(self, client: ConcreteWebhookClient, sample_event: WebhookEvent) -> None:
        """Failed delivery queues the event and returns False."""
        with patch.object(
            client,
            "_deliver_with_retry",
            side_effect=WebhookDeliveryError(client._webhook_url, "connection refused"),
        ):
            result = await client.send(sample_event)

        assert result is False
        assert client.queue_size == 1


# ── WebhookClient._deliver_with_retry ─────────────────────────────────────


class TestWebhookClientRetry:
    """Tests for exponential backoff retry logic (NOT-3)."""

    @pytest.fixture
    def client(self) -> ConcreteWebhookClient:
        return ConcreteWebhookClient(
            "https://discord.com/api/webhooks/test",
            max_retries=3,
        )

    @pytest.mark.asyncio
    async def test_retries_up_to_max(self, client: ConcreteWebhookClient) -> None:
        """Retries up to max_retries before raising WebhookDeliveryError."""
        call_count = 0

        async def fail_once(payload: dict[str, Any], timeout: float = 10.0) -> None:
            nonlocal call_count
            call_count += 1
            raise aiohttp.ClientError("test error")

        with patch.object(client, "_deliver", side_effect=fail_once):
            with pytest.raises(WebhookDeliveryError) as exc_info:
                await client._deliver_with_retry({})

        assert call_count == 3
        assert "test error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt(self, client: ConcreteWebhookClient) -> None:
        """Delivery succeeds if one retry succeeds."""
        call_count = 0

        async def succeed_on_second(payload: dict[str, Any], timeout: float = 10.0) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise aiohttp.ClientError("transient error")

        with patch.object(client, "_deliver", side_effect=succeed_on_second):
            # Should not raise
            await client._deliver_with_retry({})

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_triggers_retry(self, client: ConcreteWebhookClient) -> None:
        """Timeout errors trigger retry just like ClientErrors."""
        call_count = 0

        async def timeout_once(payload: dict[str, Any], timeout: float = 10.0) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError()

        with patch.object(client, "_deliver", side_effect=timeout_once):
            await client._deliver_with_retry({})

        assert call_count == 2


# ── WebhookClient queue ─────────────────────────────────────────────────────


class TestWebhookClientQueue:
    """Tests for event queuing (NOT-5)."""

    @pytest.fixture
    def client(self) -> ConcreteWebhookClient:
        return ConcreteWebhookClient(
            "https://discord.com/api/webhooks/test",
            max_queue_size=3,
        )

    def test_queue_starts_empty(self, client: ConcreteWebhookClient) -> None:
        assert client.queue_size == 0

    def test_clear_queue(self, client: ConcreteWebhookClient) -> None:
        client._enqueue_raw({"test": "payload"})
        assert client.queue_size == 1
        client.clear_queue()
        assert client.queue_size == 0

    def test_queue_respects_max_size(self, client: ConcreteWebhookClient) -> None:
        """Oldest events are dropped when queue exceeds max size."""
        for i in range(5):
            client._enqueue_raw({"event": f"event_{i}"})

        assert client.queue_size == 3
        # First two events should have been dropped
        events = [item["payload"]["event"] for item in client._queue]
        assert events == ["event_2", "event_3", "event_4"]

    @pytest.mark.asyncio
    async def test_flush_queue_delivers_all(self, client: ConcreteWebhookClient) -> None:
        """flush_queue() delivers all queued events in FIFO order."""
        delivered: list[dict[str, Any]] = []

        async def mock_deliver(payload: dict[str, Any], timeout: float = 10.0) -> None:
            delivered.append(payload)

        with patch.object(client, "_deliver", side_effect=mock_deliver):
            client._enqueue_raw({"event": "event_1"})
            client._enqueue_raw({"event": "event_2"})
            delivered_count = await client.flush_queue()

        assert delivered_count == 2
        assert delivered[0]["event"] == "event_1"
        assert delivered[1]["event"] == "event_2"

    @pytest.mark.asyncio
    async def test_flush_queue_events_retried_and_delivered(self, client: ConcreteWebhookClient) -> None:
        """Events that fail once but succeed on retry are delivered."""
        failed_events: set[str] = set()

        async def fail_once_then_succeed(
            payload: dict[str, Any], timeout: float = 10.0
        ) -> None:
            event_name = payload.get("event", "")
            if event_name not in failed_events:
                failed_events.add(event_name)
                raise aiohttp.ClientError("transient failure")

        with patch.object(client, "_deliver", side_effect=fail_once_then_succeed):
            client._enqueue_raw({"event": "event_1"})
            client._enqueue_raw({"event": "event_2"})
            delivered_count = await client.flush_queue()

        # event_1: fails once, succeeds on retry
        # event_2: fails once, succeeds on retry
        assert delivered_count == 2
        assert client.queue_size == 0

    @pytest.mark.asyncio
    async def test_flush_queue_drops_permanently_failing(self, client: ConcreteWebhookClient) -> None:
        """Events that always fail after retries are dropped (not re-enqueued)."""

        async def always_fail(payload: dict[str, Any], timeout: float = 10.0) -> None:
            raise aiohttp.ClientError("permanent failure")

        with patch.object(client, "_deliver", side_effect=always_fail):
            client._enqueue_raw({"event": "event_1"})
            client._enqueue_raw({"event": "event_2"})
            delivered_count = await client.flush_queue()

        # All events dropped after exhausting retries
        assert delivered_count == 0
        assert client.queue_size == 0

    @pytest.mark.asyncio
    async def test_flush_empty_queue(self, client: ConcreteWebhookClient) -> None:
        """Flushing an empty queue returns 0."""
        delivered_count = await client.flush_queue()
        assert delivered_count == 0


# ── WebhookClient.close ─────────────────────────────────────────────────────


class TestWebhookClientClose:
    """Tests for WebhookClient.close()."""

    @pytest.mark.asyncio
    async def test_close_without_session(self) -> None:
        """close() is safe to call without ever opening a session."""
        client = ConcreteWebhookClient("https://discord.com/api/webhooks/test")
        await client.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_close_with_open_session(self) -> None:
        """close() closes the aiohttp session."""
        client = ConcreteWebhookClient("https://discord.com/api/webhooks/test")
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.closed = False
        client._client = mock_session

        await client.close()

        mock_session.close.assert_called_once()
        assert client._client is None
