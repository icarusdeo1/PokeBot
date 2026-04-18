"""Tests for the Telegram webhook notifier."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from src.bot.notifications.telegram import TelegramWebhook
from src.bot.notifications.webhook import WebhookDeliveryError


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp.ClientSession that returns a successful response."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.read = AsyncMock(return_value=None)
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.close = MagicMock()
    type(mock_session).closed = PropertyMock(return_value=False)

    return mock_session


@pytest.fixture
def telegram_webhook(mock_aiohttp_session) -> TelegramWebhook:
    """Create a TelegramWebhook with a mocked session."""
    webhook = TelegramWebhook("https://api.telegram.org/bot123456:ABC-DEF1234/sendMessage", "123456")
    webhook._client = mock_aiohttp_session
    return webhook


def make_event(
    event: str,
    item: str = "",
    retailer: str = "",
    order_id: str = "",
    error: str = "",
    url: str = "",
    sku: str = "",
    cart_url: str = "",
    captcha_type: str = "",
    solve_time_ms: int = 0,
    pause_url: str = "",
    timeout_seconds: int = 0,
    daily_spent_usd: float = 0.0,
    budget_cap_usd: float = 0.0,
    queue_url: str = "",
    decline_code: str = "",
    total: str = "",
    reason: str = "",
    attempt: int = 1,
    timestamp: str = "",
) -> Any:
    """Create a WebhookEvent with the given fields."""
    from src.shared.models import WebhookEvent
    return WebhookEvent(
        event=event,
        item=item,
        retailer=retailer,
        order_id=order_id,
        error=error,
        url=url,
        sku=sku,
        cart_url=cart_url,
        captcha_type=captcha_type,
        solve_time_ms=solve_time_ms,
        pause_url=pause_url,
        timeout_seconds=timeout_seconds,
        daily_spent_usd=daily_spent_usd,
        budget_cap_usd=budget_cap_usd,
        queue_url=queue_url,
        decline_code=decline_code,
        total=total,
        reason=reason,
        attempt=attempt,
        timestamp=timestamp,
    )


# ── _build_payload Tests ───────────────────────────────────────────────────────

class TestBuildPayload:
    """Tests for _build_payload()."""

    def test_stock_found_message(self):
        """STOCK_FOUND produces a message with item, retailer, SKU."""
        event = make_event(
            event="STOCK_FOUND",
            item="Pikachu VMAX Box",
            retailer="Target",
            sku="123456",
            timestamp="2026-04-18T10:00:00Z",
        )
        webhook = TelegramWebhook("https://api.telegram.org/bot123456:ABC-DEF1234/sendMessage", "123456")
        payload = webhook._build_payload(event)

        assert "chat_id" in payload
        assert "text" in payload
        assert "parse_mode" in payload
        assert payload["parse_mode"] == "HTML"
        assert "Pikachu VMAX Box" in payload["text"]
        assert "Target" in payload["text"]
        assert "STOCK_FOUND" in payload["text"]

    def test_checkout_success_message(self):
        """CHECKOUT_SUCCESS includes order ID and total."""
        event = make_event(
            event="CHECKOUT_SUCCESS",
            item="Charizard VMAX Box",
            retailer="Walmart",
            order_id="ORD-12345",
            total="$149.99",
        )
        webhook = TelegramWebhook("https://api.telegram.org/bot123456:ABC-DEF1234/sendMessage", "123456")
        payload = webhook._build_payload(event)

        assert "ORD-12345" in payload["text"]
        assert "$149.99" in payload["text"]
        assert "Charizard VMAX Box" in payload["text"]

    def test_checkout_failed_message(self):
        """CHECKOUT_FAILED includes error and attempt."""
        event = make_event(
            event="CHECKOUT_FAILED",
            item="Venusaur VMAX",
            retailer="BestBuy",
            error="Payment declined",
            attempt=2,
        )
        webhook = TelegramWebhook("https://api.telegram.org/bot123456:ABC-DEF1234/sendMessage", "123456")
        payload = webhook._build_payload(event)

        assert "Payment declined" in payload["text"]
        assert "BestBuy" in payload["text"]
        assert "Venusaur VMAX" in payload["text"]

    def test_payment_declined_message(self):
        """PAYMENT_DECLINED includes decline code."""
        event = make_event(
            event="PAYMENT_DECLINED",
            retailer="Target",
            decline_code="insufficient_funds",
        )
        webhook = TelegramWebhook("https://api.telegram.org/bot123456:ABC-DEF1234/sendMessage", "123456")
        payload = webhook._build_payload(event)

        assert "insufficient_funds" in payload["text"]

    def test_captcha_pending_manual_message(self):
        """CAPTCHA_PENDING_MANUAL includes pause URL."""
        event = make_event(
            event="CAPTCHA_PENDING_MANUAL",
            retailer="BestBuy",
            captcha_type="Turnstile",
            pause_url="https://example.com/captcha",
        )
        webhook = TelegramWebhook("https://api.telegram.org/bot123456:ABC-DEF1234/sendMessage", "123456")
        payload = webhook._build_payload(event)

        assert "CAPTCHA_PENDING_MANUAL" in payload["text"]
        assert "Turnstile" in payload["text"]
        assert "example.com" in payload["text"]

    def test_captcha_budget_exceeded_message(self):
        """CAPTCHA_BUDGET_EXCEEDED shows daily spend vs budget."""
        event = make_event(
            event="CAPTCHA_BUDGET_EXCEEDED",
            daily_spent_usd=5.50,
            budget_cap_usd=5.00,
        )
        webhook = TelegramWebhook("https://api.telegram.org/bot123456:ABC-DEF1234/sendMessage", "123456")
        payload = webhook._build_payload(event)

        assert "$5.50" in payload["text"]
        assert "$5.00" in payload["text"]

    def test_queue_detected_message(self):
        """QUEUE_DETECTED includes queue URL."""
        event = make_event(
            event="QUEUE_DETECTED",
            retailer="Walmart",
            queue_url="https://walmart.com/queue/abc123",
        )
        webhook = TelegramWebhook("https://api.telegram.org/bot123456:ABC-DEF1234/sendMessage", "123456")
        payload = webhook._build_payload(event)

        assert "QUEUE_DETECTED" in payload["text"]
        assert "walmart.com/queue" in payload["text"]

    def test_unknown_event_message(self):
        """Unknown event types still produce a valid message."""
        event = make_event(event="UNKNOWN_EVENT_XYZ", item="Test Item")
        webhook = TelegramWebhook("https://api.telegram.org/bot123456:ABC-DEF1234/sendMessage", "123456")
        payload = webhook._build_payload(event)

        assert "text" in payload
        assert "UNKNOWN_EVENT_XYZ" in payload["text"]

    def test_no_timestamp_no_timestamp_in_message(self):
        """Event without timestamp still sends message."""
        event = make_event(event="MONITOR_STARTED", item="Test Item")
        webhook = TelegramWebhook("https://api.telegram.org/bot123456:ABC-DEF1234/sendMessage", "123456")
        payload = webhook._build_payload(event)

        assert "text" in payload


# ── send Tests ────────────────────────────────────────────────────────────────

class TestSend:
    """Tests for send() with mocked HTTP delivery."""

    @pytest.mark.asyncio
    async def test_send_success(self, telegram_webhook, mock_aiohttp_session):
        """send() delivers payload and returns True on success."""
        event = make_event(event="STOCK_FOUND", item="Test Item", retailer="Target")
        result = await telegram_webhook.send(event)

        assert result is True
        telegram_webhook._client.post.assert_called_once()
        call_args = telegram_webhook._client.post.call_args
        assert "sendMessage" in call_args[0][0]

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_failure_queues_event(self, telegram_webhook, mock_aiohttp_session):
        """send() returns False and enqueues event when delivery fails."""
        with patch.object(
            telegram_webhook,
            "_deliver_with_retry",
            side_effect=WebhookDeliveryError(telegram_webhook._webhook_url, "connection refused"),
        ):
            event = make_event(event="MONITOR_STARTED")
            result = await telegram_webhook.send(event)

        assert result is False
        assert telegram_webhook.queue_size == 1

    @pytest.mark.asyncio
    async def test_send_assigns_iso_timestamp(self, telegram_webhook, mock_aiohttp_session):
        """send() sets timestamp on event if missing."""
        event = make_event(event="STOCK_CHECK")
        assert not event.timestamp

        await telegram_webhook.send(event)

        assert event.timestamp != ""

    @pytest.mark.asyncio
    async def test_flush_queue_delivers_all(self, telegram_webhook, mock_aiohttp_session):
        """flush_queue() delivers all queued events."""
        async def fail_then_succeed(*args, **kwargs):
            fail_then_succeed._call_count = getattr(fail_then_succeed, "_call_count", 0)
            fail_then_succeed._call_count += 1
            if fail_then_succeed._call_count <= 3:
                from src.bot.notifications.webhook import WebhookDeliveryError
                raise WebhookDeliveryError(telegram_webhook._webhook_url, "transient")
            # Succeeds

        with patch.object(telegram_webhook, "_deliver_with_retry", side_effect=fail_then_succeed):
            await telegram_webhook.send(make_event(event="STOCK_CHECK"))
            await telegram_webhook.send(make_event(event="MONITOR_STARTED"))
            await telegram_webhook.send(make_event(event="MONITOR_STOPPED"))

        assert telegram_webhook.queue_size == 3

        delivered = await telegram_webhook.flush_queue()

        assert delivered == 3
        assert telegram_webhook.queue_size == 0

    @pytest.mark.asyncio
    async def test_flush_queue_empty_returns_zero(self, telegram_webhook):
        """flush_queue() on empty queue returns 0."""
        result = await telegram_webhook.flush_queue()
        assert result == 0


# ── HTTPS Validation ───────────────────────────────────────────────────────────

class TestHttpsValidation:
    """Tests for HTTPS URL validation on init."""

    def test_rejects_http_url(self):
        """Non-HTTPS URLs raise ValueError."""
        with pytest.raises(ValueError, match="HTTPS"):
            TelegramWebhook("http://api.telegram.org/bot123456:ABC-DEF1234/sendMessage", "123456")

    def test_rejects_ftp_url(self):
        """FTP URLs raise ValueError."""
        with pytest.raises(ValueError, match="HTTPS"):
            TelegramWebhook("ftp://api.telegram.org/bot123456:ABC-DEF1234/sendMessage", "123456")

    def test_accepts_https_webhook_url(self):
        """Valid HTTPS Telegram webhook URLs are accepted."""
        webhook = TelegramWebhook("https://api.telegram.org/bot123456:ABC-DEF1234/sendMessage", "123456")
        assert "api.telegram.org" in webhook._webhook_url
