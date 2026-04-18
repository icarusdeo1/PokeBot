"""Tests for the Discord webhook notifier."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from src.bot.notifications.discord import DiscordWebhook, _COLOR_MAP, _DEFAULT_COLOR
from src.bot.notifications.webhook import WebhookDeliveryError
from src.shared.models import WebhookEvent


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp.ClientSession that returns a successful response."""
    mock_response = AsyncMock()
    mock_response.status = 200  # Ensure raise_for_status() succeeds
    mock_response.read = AsyncMock(return_value=None)
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.close = MagicMock()
    # Use PropertyMock so that .closed returns False (not a new MagicMock)
    type(mock_session).closed = PropertyMock(return_value=False)

    return mock_session


@pytest.fixture
def discord_webhook(mock_aiohttp_session) -> DiscordWebhook:
    """Create a DiscordWebhook with a mocked session."""
    webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
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
) -> WebhookEvent:
    """Create a WebhookEvent with the given fields."""
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

    def test_stock_found_embed(self):
        """STOCK_FOUND produces a green embed with item/retailer fields."""
        event = make_event(
            event="STOCK_FOUND",
            item="Pikachu VMAX Box",
            retailer="Target",
            sku="123456",
            timestamp="2026-04-18T10:00:00Z",
        )
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
        payload = webhook._build_payload(event)

        assert "embeds" in payload
        assert len(payload["embeds"]) == 1
        embed = payload["embeds"][0]
        assert embed["color"] == _COLOR_MAP["STOCK_FOUND"]
        assert embed["title"] == "Stock Found"
        # Check fields are present
        field_names = [f["name"] for f in embed["fields"]]
        assert "Item" in field_names
        assert "Retailer" in field_names
        assert "SKU" in field_names
        assert embed["timestamp"] == "2026-04-18T10:00:00Z"

    def test_checkout_success_embed(self):
        """CHECKOUT_SUCCESS produces green embed with order_id and total."""
        event = make_event(
            event="CHECKOUT_SUCCESS",
            item="Charizard VMAX Box",
            retailer="Walmart",
            order_id="ORD-12345",
            total="$149.99",
            timestamp="2026-04-18T10:05:00Z",
        )
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
        payload = webhook._build_payload(event)

        embed = payload["embeds"][0]
        assert embed["color"] == _COLOR_MAP["CHECKOUT_SUCCESS"]
        assert embed["title"] == "Checkout Success"
        field_names = [f["name"] for f in embed["fields"]]
        assert "Order ID" in field_names
        assert "Total" in field_names

    def test_checkout_failed_embed(self):
        """CHECKOUT_FAILED produces red embed with error field."""
        event = make_event(
            event="CHECKOUT_FAILED",
            item="Venusaur VMAX",
            retailer="BestBuy",
            error="Payment declined",
            attempt=2,
        )
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
        payload = webhook._build_payload(event)

        embed = payload["embeds"][0]
        assert embed["color"] == _COLOR_MAP["CHECKOUT_FAILED"]
        assert embed["title"] == "Checkout Failed"
        field_names = [f["name"] for f in embed["fields"]]
        assert "Error" in field_names
        assert "Attempt" in field_names

    def test_payment_declined_embed(self):
        """PAYMENT_DECLINED produces red embed with decline_code."""
        event = make_event(
            event="PAYMENT_DECLINED",
            retailer="Target",
            decline_code="insufficient_funds",
        )
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
        payload = webhook._build_payload(event)

        embed = payload["embeds"][0]
        assert embed["color"] == _COLOR_MAP["PAYMENT_DECLINED"]
        field_names = [f["name"] for f in embed["fields"]]
        assert "Decline Code" in field_names

    def test_captcha_pending_manual_embed(self):
        """CAPTCHA_PENDING_MANUAL produces red embed with pause_url."""
        event = make_event(
            event="CAPTCHA_PENDING_MANUAL",
            retailer="BestBuy",
            captcha_type="Turnstile",
            pause_url="https://example.com/captcha",
        )
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
        payload = webhook._build_payload(event)

        embed = payload["embeds"][0]
        assert embed["color"] == _COLOR_MAP["CAPTCHA_PENDING_MANUAL"]
        field_names = [f["name"] for f in embed["fields"]]
        assert "Pause URL" in field_names
        assert "CAPTCHA Type" in field_names

    def test_captcha_solved_embed(self):
        """CAPTCHA_SOLVED produces green embed with solve_time_ms."""
        event = make_event(
            event="CAPTCHA_SOLVED",
            retailer="Target",
            captcha_type="Turnstile",
            solve_time_ms=15230,
        )
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
        payload = webhook._build_payload(event)

        embed = payload["embeds"][0]
        assert embed["color"] == _COLOR_MAP["CAPTCHA_SOLVED"]
        field_names = [f["name"] for f in embed["fields"]]
        assert "Solve Time" in field_names

    def test_captcha_budget_exceeded_embed(self):
        """CAPTCHA_BUDGET_EXCEEDED shows daily spend vs budget."""
        event = make_event(
            event="CAPTCHA_BUDGET_EXCEEDED",
            daily_spent_usd=5.50,
            budget_cap_usd=5.00,
        )
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
        payload = webhook._build_payload(event)

        embed = payload["embeds"][0]
        assert embed["color"] == _COLOR_MAP["CAPTCHA_BUDGET_EXCEEDED"]
        field_names = [f["name"] for f in embed["fields"]]
        assert "Daily Spend" in field_names

    def test_queue_detected_embed(self):
        """QUEUE_DETECTED produces yellow embed with queue_url."""
        event = make_event(
            event="QUEUE_DETECTED",
            retailer="Walmart",
            queue_url="https://walmart.com/queue/abc123",
        )
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
        payload = webhook._build_payload(event)

        embed = payload["embeds"][0]
        assert embed["color"] == _COLOR_MAP["QUEUE_DETECTED"]
        field_names = [f["name"] for f in embed["fields"]]
        assert "Queue URL" in field_names

    def test_unknown_event_color(self):
        """Unknown event types default to grey."""
        event = make_event(event="UNKNOWN_EVENT_XYZ")
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
        payload = webhook._build_payload(event)

        embed = payload["embeds"][0]
        assert embed["color"] == _DEFAULT_COLOR

    def test_no_timestamp_no_timestamp_in_embed(self):
        """Event without timestamp omits timestamp from embed."""
        event = make_event(event="MONITOR_STARTED", item="Test Item")
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
        payload = webhook._build_payload(event)

        embed = payload["embeds"][0]
        assert "timestamp" not in embed

    def test_description_with_order_id(self):
        """Order ID produces description with order confirmation."""
        event = make_event(event="ORDER_PLACED", order_id="ORD-999")
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
        payload = webhook._build_payload(event)

        embed = payload["embeds"][0]
        assert "ORD-999" in embed["description"]

    def test_description_with_error(self):
        """Error produces description with error text."""
        event = make_event(event="CHECKOUT_FAILED", error="Card declined")
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
        payload = webhook._build_payload(event)

        embed = payload["embeds"][0]
        assert "Card declined" in embed["description"]

    def test_description_with_manual_captcha(self):
        """Manual CAPTCHA with pause_url includes link in description."""
        event = make_event(
            event="CAPTCHA_PENDING_MANUAL",
            pause_url="https://example.com/captcha/solve",
        )
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
        payload = webhook._build_payload(event)

        embed = payload["embeds"][0]
        assert "example.com" in embed["description"]

    def test_description_budget_exceeded(self):
        """CAPTCHA_BUDGET_EXCEEDED description includes budget cap."""
        event = make_event(
            event="CAPTCHA_BUDGET_EXCEEDED",
            budget_cap_usd=5.00,
            daily_spent_usd=6.00,
        )
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/webhook")
        payload = webhook._build_payload(event)

        embed = payload["embeds"][0]
        assert "$5.00" in embed["description"]


# ── send Tests ────────────────────────────────────────────────────────────────

class TestSend:
    """Tests for send() with mocked HTTP delivery."""

    @pytest.mark.asyncio
    async def test_send_success(self, discord_webhook, mock_aiohttp_session):
        """send() delivers payload and returns True on success."""
        event = make_event(event="STOCK_FOUND", item="Test Item", retailer="Target")
        result = await discord_webhook.send(event)

        assert result is True
        discord_webhook._client.post.assert_called_once()
        call_args = discord_webhook._client.post.call_args
        assert call_args[0][0] == "https://discord.com/api/webhooks/test/webhook"
        payload_sent = call_args.kwargs["json"]
        assert "embeds" in payload_sent

    @pytest.mark.asyncio
    async def test_send_failure_queues_event(self, discord_webhook, mock_aiohttp_session):
        """send() returns False and enqueues event when delivery fails."""
        with patch.object(
            discord_webhook,
            "_deliver_with_retry",
            side_effect=WebhookDeliveryError(discord_webhook._webhook_url, "connection refused"),
        ):
            event = make_event(event="MONITOR_STARTED")
            result = await discord_webhook.send(event)

        assert result is False
        assert discord_webhook.queue_size == 1

    @pytest.mark.asyncio
    async def test_send_assigns_iso_timestamp(self, discord_webhook, mock_aiohttp_session):
        """send() sets timestamp on event if missing."""
        event = make_event(event="STOCK_CHECK")
        assert not event.timestamp

        await discord_webhook.send(event)

        assert event.timestamp != ""

    @pytest.mark.asyncio
    async def test_flush_queue_delivers_all(self, discord_webhook, mock_aiohttp_session):
        """flush_queue() delivers all queued events."""
        # First, queue some events by making send() fail
        async def fail_then_succeed(*args, **kwargs):
            # First 3 calls fail (events get queued), 4th+ call succeeds
            fail_then_succeed._call_count = getattr(fail_then_succeed, "_call_count", 0)
            fail_then_succeed._call_count += 1
            if fail_then_succeed._call_count <= 3:
                from src.bot.notifications.webhook import WebhookDeliveryError
                raise WebhookDeliveryError(discord_webhook._webhook_url, "transient")
            # Succeed: _deliver_with_retry calls _deliver which uses mock_post

        with patch.object(discord_webhook, "_deliver_with_retry", side_effect=fail_then_succeed):
            await discord_webhook.send(make_event(event="STOCK_CHECK"))
            await discord_webhook.send(make_event(event="MONITOR_STARTED"))
            await discord_webhook.send(make_event(event="MONITOR_STOPPED"))

        assert discord_webhook.queue_size == 3

        delivered = await discord_webhook.flush_queue()

        assert delivered == 3
        assert discord_webhook.queue_size == 0

    @pytest.mark.asyncio
    async def test_flush_queue_empty_returns_zero(self, discord_webhook):
        """flush_queue() on empty queue returns 0."""
        result = await discord_webhook.flush_queue()
        assert result == 0


# ── HTTPS Validation ───────────────────────────────────────────────────────────

class TestHttpsValidation:
    """Tests for HTTPS URL validation on init."""

    def test_rejects_http_url(self):
        """Non-HTTPS URLs raise ValueError."""
        with pytest.raises(ValueError, match="HTTPS"):
            DiscordWebhook("http://discord.com/api/webhooks/test/webhook")

    def test_rejects_ftp_url(self):
        """FTP URLs raise ValueError."""
        with pytest.raises(ValueError, match="HTTPS"):
            DiscordWebhook("ftp://discord.com/api/webhooks/test/webhook")

    def test_accepts_https_webhook_url(self):
        """Valid HTTPS Discord webhook URLs are accepted."""
        webhook = DiscordWebhook("https://discord.com/api/webhooks/test/token")
        assert webhook._webhook_url == "https://discord.com/api/webhooks/test/token"


# ── Color Map Coverage ─────────────────────────────────────────────────────────

class TestColorMap:
    """Verify all documented event types have a color mapping."""

    def test_all_stocumented_events_have_colors(self):
        """All webhook event types from PRD Section 8.2 have a color."""
        documented_events = [
            "STOCK_CHECK",
            "STOCK_FOUND",
            "STOCK_OOS",
            "CART_ADDED",
            "CART_FAILED",
            "CART_CLEARED",
            "CART_VERIFIED",
            "CHECKOUT_STARTED",
            "CHECKOUT_SUCCESS",
            "CHECKOUT_FAILED",
            "ORDER_PLACED",
            "PAYMENT_DECLINED",
            "CAPTCHA_PENDING_AUTO",
            "CAPTCHA_PENDING_MANUAL",
            "CAPTCHA_SOLVED",
            "CAPTCHA_FAILED",
            "CAPTCHA_BUDGET_EXCEEDED",
            "SESSION_PREWARMED",
            "SESSION_EXPIRED",
            "QUEUE_DETECTED",
            "QUEUE_CLEARED",
            "MONITOR_STARTED",
            "MONITOR_STOPPED",
            "DROP_WINDOW_APPROACHING",
            "DROP_WINDOW_OPEN",
            "SOCIAL_SIGNAL",
            "PREWARM_URGENT",
            "DAEMON_STARTED",
            "DAEMON_STOPPED",
            "DAEMON_ERROR",
        ]
        for event in documented_events:
            assert event in _COLOR_MAP, f"Missing color for {event}"