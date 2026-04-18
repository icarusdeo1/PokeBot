"""Telegram webhook notifier.

Sends formatted messages to a Telegram chat via the Bot API.
Inherits retry, queuing, and HTTPS validation from WebhookClient.

Per PRD Sections 9.6 (NOT-2, NOT-3, NOT-4, NOT-6) and 10.3 (SEC-T03).
"""

from __future__ import annotations

import re
from typing import Any

from src.bot.notifications.webhook import WebhookClient
from src.shared.models import WebhookEvent


# ── Emoji Map ─────────────────────────────────────────────────────────────────

_EVENT_EMOJI: dict[str, str] = {
    "STOCK_FOUND": "🟢",
    "STOCK_OOS": "⚫",
    "STOCK_CHECK": "🔍",
    "CART_ADDED": "🛒",
    "CART_FAILED": "❌",
    "CART_CLEARED": "🗑️",
    "CART_VERIFIED": "✅",
    "CHECKOUT_STARTED": "🚚",
    "CHECKOUT_SUCCESS": "🎉",
    "CHECKOUT_FAILED": "💳",
    "ORDER_PLACED": "📦",
    "PAYMENT_DECLINED": "🚫",
    "CAPTCHA_PENDING_AUTO": "🔐",
    "CAPTCHA_PENDING_MANUAL": "⏸️",
    "CAPTCHA_SOLVED": "🔓",
    "CAPTCHA_FAILED": "❌",
    "CAPTCHA_BUDGET_EXCEEDED": "💰",
    "SESSION_PREWARMED": "♨️",
    "SESSION_EXPIRED": "⏰",
    "QUEUE_DETECTED": "⏳",
    "QUEUE_CLEARED": "🚀",
    "MONITOR_STARTED": "▶️",
    "MONITOR_STOPPED": "⏹️",
    "DROP_WINDOW_APPROACHING": "⏰",
    "DROP_WINDOW_OPEN": "🚨",
    "SOCIAL_SIGNAL": "📡",
    "PREWARM_URGENT": "🔥",
    "DAEMON_STARTED": "🖥️",
    "DAEMON_STOPPED": "🔴",
    "DAEMON_ERROR": "⚠️",
}

_DEFAULT_EMOJI = "📋"


# ── Title Map ─────────────────────────────────────────────────────────────────

_EVENT_TITLES: dict[str, str] = {
    "STOCK_FOUND": "Stock Found!",
    "STOCK_OOS": "Out of Stock",
    "STOCK_CHECK": "Stock Check",
    "CART_ADDED": "Added to Cart",
    "CART_FAILED": "Cart Failed",
    "CART_CLEARED": "Cart Cleared",
    "CART_VERIFIED": "Cart Verified",
    "CHECKOUT_STARTED": "Checkout Started",
    "CHECKOUT_SUCCESS": "Order Confirmed!",
    "CHECKOUT_FAILED": "Checkout Failed",
    "ORDER_PLACED": "Order Placed",
    "PAYMENT_DECLINED": "Payment Declined",
    "CAPTCHA_PENDING_AUTO": "CAPTCHA Required (Auto)",
    "CAPTCHA_PENDING_MANUAL": "CAPTCHA — Manual Solve Needed",
    "CAPTCHA_SOLVED": "CAPTCHA Solved",
    "CAPTCHA_FAILED": "CAPTCHA Failed",
    "CAPTCHA_BUDGET_EXCEEDED": "CAPTCHA Budget Exceeded",
    "SESSION_PREWARMED": "Session Pre-warmed",
    "SESSION_EXPIRED": "Session Expired",
    "QUEUE_DETECTED": "Queue Detected",
    "QUEUE_CLEARED": "Queue Cleared",
    "MONITOR_STARTED": "Monitor Started",
    "MONITOR_STOPPED": "Monitor Stopped",
    "DROP_WINDOW_APPROACHING": "Drop Window Approaching",
    "DROP_WINDOW_OPEN": "Drop Window Open!",
    "SOCIAL_SIGNAL": "Social Signal",
    "PREWARM_URGENT": "⚡ Prewarm Urgent!",
    "DAEMON_STARTED": "Daemon Started",
    "DAEMON_STOPPED": "Daemon Stopped",
    "DAEMON_ERROR": "Daemon Error",
}


# ── TelegramWebhook ────────────────────────────────────────────────────────────


class TelegramWebhook(WebhookClient):
    """Telegram Bot API webhook notifier.

    Formats ``WebhookEvent`` objects as Telegram HTML messages and delivers
    them via POST to the Bot API ``sendMessage`` endpoint.

    The ``webhook_url`` is the Telegram Bot API endpoint URL:
        https://api.telegram.org/bot<token>/sendMessage

    The ``chat_id`` is passed as a separate constructor argument and included
    in every sendMessage API call.

    Features (inherited from WebhookClient):
    - HTTPS URL validation
    - Exponential backoff retry (up to 3 attempts)
    - Event queuing for network outages
    - ISO-8601 timestamp injection

    Per PRD Sections 9.6 (NOT-2, NOT-3, NOT-4, NOT-6) and 10.3 (SEC-T03).
    """

    def __init__(
        self,
        webhook_url: str,
        chat_id: str,
        max_retries: int = 3,
        max_queue_size: int = 1000,
    ) -> None:
        """Initialize the Telegram webhook client.

        Args:
            webhook_url: Telegram Bot API sendMessage URL.
                e.g. https://api.telegram.org/bot<token>/sendMessage
            chat_id: The Telegram chat ID to send messages to.
            max_retries: Maximum retry attempts on failure (default 3).
            max_queue_size: Maximum events to queue when network is down.

        Raises:
            ValueError: If ``webhook_url`` is not a valid HTTPS URL.
        """
        super().__init__(webhook_url, max_retries, max_queue_size)
        if not chat_id:
            raise ValueError("chat_id is required for TelegramWebhook")
        self._chat_id = chat_id

    def _build_payload(self, event: WebhookEvent) -> dict[str, Any]:
        """Build a Telegram sendMessage payload for the given event.

        Produces a Telegram API payload with HTML-formatted message text.

        Args:
            event: The WebhookEvent to format.

        Returns:
            A Telegram API payload dict suitable for ``aiohttp.ClientSession.post``.
        """
        text = self._format_message(event)

        return {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

    def _format_message(self, event: WebhookEvent) -> str:
        """Format the Telegram message text for the given event.

        Uses HTML formatting for bold, italic, and code elements.

        Args:
            event: The WebhookEvent to format.

        Returns:
            HTML-formatted message string.
        """
        emoji = _EVENT_EMOJI.get(event.event, _DEFAULT_EMOJI)
        title = _EVENT_TITLES.get(event.event, event.event.replace("_", " ").title())

        # Build the header line
        header = f"{emoji} <b>{title}</b>"
        if event.timestamp:
            header += f"\n🕐 {event.timestamp}"

        # Build details lines
        lines: list[str] = []

        if event.item:
            lines.append(f"  • <b>Item:</b> {event.item}")
        if event.retailer:
            lines.append(f"  • <b>Retailer:</b> {event.retailer}")
        if event.order_id:
            lines.append(f"  • <b>Order ID:</b> <code>{event.order_id}</code>")
        if event.total:
            lines.append(f"  • <b>Total:</b> {event.total}")
        if event.error:
            lines.append(f"  • <b>Error:</b> {event.error}")
        if event.attempt > 1:
            lines.append(f"  • <b>Attempt:</b> {event.attempt}")
        if event.sku:
            lines.append(f"  • <b>SKU:</b> <code>{event.sku}</code>")
        if event.cart_url:
            lines.append(f"  • <b>Cart:</b> {event.cart_url}")
        if event.url:
            lines.append(f"  • <b>URL:</b> {event.url}")
        if event.captcha_type:
            lines.append(f"  • <b>CAPTCHA Type:</b> {event.captcha_type}")
        if event.solve_time_ms > 0:
            solve_time_s = event.solve_time_ms / 1000.0
            lines.append(f"  • <b>Solve Time:</b> {solve_time_s:.2f}s")
        if event.pause_url:
            lines.append(f"  • <b>Solve Here:</b> {event.pause_url}")
        if event.timeout_seconds > 0:
            lines.append(f"  • <b>Timeout:</b> {event.timeout_seconds}s")
        if event.daily_spent_usd > 0:
            lines.append(f"  • <b>Daily Spend:</b> ${event.daily_spent_usd:.2f}")
        if event.budget_cap_usd > 0:
            lines.append(f"  • <b>Budget Cap:</b> ${event.budget_cap_usd:.2f}")
        if event.queue_url:
            lines.append(f"  • <b>Queue:</b> {event.queue_url}")
        if event.decline_code:
            lines.append(f"  • <b>Decline Code:</b> <code>{event.decline_code}</code>")
        if event.reason:
            lines.append(f"  • <b>Reason:</b> {event.reason}")

        # Footer with event type
        footer = f"\n📌 <i>{event.event}</i>"

        # Combine
        details = "\n".join(lines) if lines else ""
        message = header
        if details:
            message += "\n" + details
        message += footer

        return message


__all__ = ["TelegramWebhook"]
