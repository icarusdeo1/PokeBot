"""Discord webhook notifier.

Sends formatted embed payloads to a Discord webhook URL.
Inherits retry, queuing, and HTTPS validation from WebhookClient.

Per PRD Sections 9.6 (NOT-1, NOT-3, NOT-4, NOT-6) and 10.3 (SEC-T03).
"""

from __future__ import annotations

from typing import Any

from src.bot.notifications.webhook import WebhookClient
from src.shared.models import WebhookEvent


# ── Color Palette ──────────────────────────────────────────────────────────────

# Discord embed colors (integer RGB values)
_COLOR_MAP: dict[str, int] = {
    # Success / positive
    "STOCK_FOUND": 0x57F287,       # Green
    "CART_ADDED": 0x57F287,        # Green
    "CART_VERIFIED": 0x57F287,     # Green
    "CHECKOUT_SUCCESS": 0x57F287,  # Green
    "ORDER_PLACED": 0x57F287,      # Green
    "CAPTCHA_SOLVED": 0x57F287,   # Green
    "SESSION_PREWARMED": 0x57F287,  # Green
    "QUEUE_CLEARED": 0x57F287,    # Green
    "DROP_WINDOW_OPEN": 0x57F287,  # Green
    "MONITOR_STARTED": 0x57F287,  # Green
    "DAEMON_STARTED": 0x57F287,   # Green
    # Danger / failure
    "STOCK_OOS": 0xED4245,        # Red
    "CART_FAILED": 0xED4245,      # Red
    "CHECKOUT_FAILED": 0xED4245,  # Red
    "PAYMENT_DECLINED": 0xED4245,  # Red
    "CAPTCHA_PENDING_MANUAL": 0xED4245,  # Red
    "CAPTCHA_FAILED": 0xED4245,    # Red
    "CAPTCHA_BUDGET_EXCEEDED": 0xED4245,  # Red
    "SESSION_EXPIRED": 0xED4245,   # Red
    "MONITOR_STOPPED": 0xED4245,  # Red (treated as failure/alert)
    "DAEMON_STOPPED": 0xED4245,   # Red
    "DAEMON_ERROR": 0xED4245,     # Red
    # Warning / attention
    "CAPTCHA_PENDING_AUTO": 0xFEE75C,  # Yellow
    "QUEUE_DETECTED": 0xFEE75C,   # Yellow
    "DROP_WINDOW_APPROACHING": 0xFEE75C,  # Yellow
    "PREWARM_URGENT": 0xFEE75C,   # Yellow
    "SOCIAL_SIGNAL": 0xFEE75C,    # Yellow
    # Informational
    "STOCK_CHECK": 0x5865F2,      # Blurple
    "CART_CLEARED": 0x5865F2,     # Blurple
    "CHECKOUT_STARTED": 0x5865F2,  # Blurple
    "MONITOR_STOPPED": 0xED4245,  # Red
}

# Default color for unknown event types (grey)
_DEFAULT_COLOR: int = 0x949697


# ── Event Title Map ────────────────────────────────────────────────────────────

_TITLE_MAP: dict[str, str] = {
    "STOCK_FOUND": "Stock Found",
    "STOCK_OOS": "Out of Stock",
    "STOCK_CHECK": "Stock Check",
    "CART_ADDED": "Added to Cart",
    "CART_FAILED": "Cart Failed",
    "CART_CLEARED": "Cart Cleared",
    "CART_VERIFIED": "Cart Verified",
    "CHECKOUT_STARTED": "Checkout Started",
    "CHECKOUT_SUCCESS": "Checkout Success",
    "CHECKOUT_FAILED": "Checkout Failed",
    "ORDER_PLACED": "Order Placed",
    "PAYMENT_DECLINED": "Payment Declined",
    "CAPTCHA_PENDING_AUTO": "CAPTCHA Required (Auto)",
    "CAPTCHA_PENDING_MANUAL": "CAPTCHA Pending Manual",
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
    "DROP_WINDOW_OPEN": "Drop Window Open",
    "SOCIAL_SIGNAL": "Social Signal Detected",
    "PREWARM_URGENT": "Prewarm Urgent",
    "DAEMON_STARTED": "Daemon Started",
    "DAEMON_STOPPED": "Daemon Stopped",
    "DAEMON_ERROR": "Daemon Error",
}


# ── DiscordWebhook ─────────────────────────────────────────────────────────────


class DiscordWebhook(WebhookClient):
    """Discord webhook notifier.

    Formats ``WebhookEvent`` objects as Discord embed payloads and delivers
    them via POST requests to a Discord webhook URL.

    Features (inherited from WebhookClient):
    - HTTPS URL validation
    - Exponential backoff retry (up to 3 attempts)
    - Event queuing for network outages
    - ISO-8601 timestamp injection

    Per PRD Sections 9.6 (NOT-1, NOT-3, NOT-4, NOT-6) and 10.3 (SEC-T03).
    """

    def _build_payload(self, event: WebhookEvent) -> dict[str, Any]:
        """Build a Discord embed payload for the given event.

        Produces a Discord webhook payload with an ``embeds`` array containing
        a single embed with color, title, description, timestamp, and fields.

        Args:
            event: The WebhookEvent to format.

        Returns:
            A Discord webhook payload dict suitable for ``aiohttp.ClientSession.post``.
        """
        color = _COLOR_MAP.get(event.event, _DEFAULT_COLOR)
        title = _TITLE_MAP.get(event.event, event.event.replace("_", " ").title())
        description = self._build_description(event)
        timestamp = event.timestamp if event.timestamp else None

        embed: dict[str, Any] = {
            "title": title,
            "color": color,
        }

        if description:
            embed["description"] = description

        if timestamp:
            embed["timestamp"] = timestamp

        # Build fields list — only include non-empty relevant fields
        fields = self._build_fields(event)
        if fields:
            embed["fields"] = fields

        # Add footer with event type
        embed["footer"] = {"text": f"Event: {event.event}"}

        return {"embeds": [embed]}

    def _build_description(self, event: WebhookEvent) -> str:
        """Build the embed description text based on event data.

        Args:
            event: The WebhookEvent to describe.

        Returns:
            A human-readable description string, or empty string if no
            meaningful description can be generated.
        """
        if event.event == "CHECKOUT_SUCCESS" and event.order_id:
            return f"Order confirmed: **{event.order_id}**"
        if event.event == "CHECKOUT_FAILED" and event.error:
            return f"Error: {event.error}"
        if event.event == "PAYMENT_DECLINED" and event.decline_code:
            return f"Decline code: `{event.decline_code}`"
        if event.event == "CAPTCHA_PENDING_MANUAL" and event.pause_url:
            return f"Solve the CAPTCHA: {event.pause_url}"
        if event.event == "CAPTCHA_BUDGET_EXCEEDED":
            return (
                f"Daily budget cap of **${event.budget_cap_usd:.2f}** exceeded. "
                f"Spent: **${event.daily_spent_usd:.2f}**"
            )
        if event.event == "QUEUE_DETECTED" and event.queue_url:
            return f"Queue URL: {event.queue_url}"
        if event.event == "ORDER_PLACED" and event.order_id:
            return f"Order placed: **{event.order_id}**"
        if event.event == "SESSION_EXPIRED" and event.reason:
            return f"Reason: {event.reason}"
        if event.event == "DAEMON_ERROR" and event.error:
            return f"Error: {event.error}"
        return ""

    def _build_fields(self, event: WebhookEvent) -> list[dict[str, str]]:
        """Build the embed fields list for the given event.

        Args:
            event: The WebhookEvent to build fields from.

        Returns:
            A list of Discord embed field dicts. Empty list if no relevant
            fields are present.
        """
        fields: list[dict[str, Any]] = []

        if event.item:
            fields.append({"name": "Item", "value": str(event.item), "inline": True})
        if event.retailer:
            fields.append({"name": "Retailer", "value": str(event.retailer), "inline": True})
        if event.order_id:
            fields.append({"name": "Order ID", "value": str(event.order_id), "inline": True})
        if event.total:
            fields.append({"name": "Total", "value": str(event.total), "inline": True})
        if event.error:
            fields.append({"name": "Error", "value": str(event.error), "inline": False})
        if event.attempt > 1:
            fields.append({"name": "Attempt", "value": str(event.attempt), "inline": True})
        if event.sku:
            fields.append({"name": "SKU", "value": str(event.sku), "inline": True})
        if event.cart_url:
            fields.append({"name": "Cart URL", "value": str(event.cart_url), "inline": False})
        if event.url:
            fields.append({"name": "URL", "value": str(event.url), "inline": False})
        if event.captcha_type:
            fields.append({"name": "CAPTCHA Type", "value": str(event.captcha_type), "inline": True})
        if event.solve_time_ms > 0:
            solve_time_s = event.solve_time_ms / 1000.0
            fields.append({"name": "Solve Time", "value": f"{solve_time_s:.2f}s", "inline": True})
        if event.pause_url:
            fields.append({"name": "Pause URL", "value": str(event.pause_url), "inline": False})
        if event.timeout_seconds > 0:
            fields.append({"name": "Timeout", "value": f"{event.timeout_seconds}s", "inline": True})
        if event.daily_spent_usd > 0:
            fields.append({"name": "Daily Spend", "value": f"${event.daily_spent_usd:.2f}", "inline": True})
        if event.budget_cap_usd > 0:
            fields.append({"name": "Budget Cap", "value": f"${event.budget_cap_usd:.2f}", "inline": True})
        if event.queue_url:
            fields.append({"name": "Queue URL", "value": str(event.queue_url), "inline": False})
        if event.decline_code:
            fields.append({"name": "Decline Code", "value": str(event.decline_code), "inline": True})
        if event.reason:
            fields.append({"name": "Reason", "value": str(event.reason), "inline": False})

        return fields


__all__ = ["DiscordWebhook", "_COLOR_MAP", "_DEFAULT_COLOR"]
