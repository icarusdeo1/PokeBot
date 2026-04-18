"""Payment form autofill and decline handling.

Per PRD Sections 9.3 (CO-2, CO-6) and 10.3 (Security).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from src.shared.models import PaymentInfo, WebhookEvent


# ── Card Type Detection ────────────────────────────────────────────────────────

# Common card type patterns (BIN numbers)
_CARD_TYPE_PATTERNS: dict[str, str] = {
    "Visa": r"^4[0-9]{12}(?:[0-9]{3})?$",
    "Mastercard": r"^5[1-5][0-9]{14}$",
    "American Express": r"^3[47][0-9]{13}$",
    "Discover": r"^6(?:011|5[0-9]{2})[0-9]{12}$",
}


def detect_card_type(card_number: str) -> str:
    """Detect the card type from a card number.

    Args:
        card_number: The card number (digits only).

    Returns:
        The card type name, or "Unknown" if not matched.
    """
    digits_only = re.sub(r"\D", "", card_number)
    for card_type, pattern in _CARD_TYPE_PATTERNS.items():
        if re.match(pattern, digits_only):
            return card_type
    return "Unknown"


def mask_card_number(card_number: str, show_last: int = 4) -> str:
    """Mask a card number, showing only the last N digits.

    Args:
        card_number: The full card number.
        show_last: Number of last digits to show (default 4).

    Returns:
        Masked card number like "************1234".
    """
    digits = re.sub(r"\D", "", card_number)
    if len(digits) <= show_last:
        return "*" * len(digits)
    masked = "*" * (len(digits) - show_last) + digits[-show_last:]
    return masked


def format_card_display(card_number: str) -> str:
    """Format card number for display (masked, with spaces every 4 digits).

    Args:
        card_number: The full card number.

    Returns:
        Formatted masked display string like "************1234".
    """
    masked = mask_card_number(card_number)
    # Add spaces for readability (4-digit groups)
    return " ".join(masked[i : i + 4] for i in range(0, len(masked), 4))


# ── Field Mapping Helpers ───────────────────────────────────────────────────────


def build_payment_form_data(
    payment: PaymentInfo,
    field_mapping: dict[str, str],
    card_number: str | None = None,
) -> dict[str, Any]:
    """Build a retailer-specific payment form payload from PaymentInfo.

    Args:
        payment: The PaymentInfo object with payment details.
        field_mapping: Dict mapping PaymentInfo field names to retailer
            form field names. E.g. {"card_number": "cc-number", "expiry_month": "cc-month"}.
        card_number: Optional explicit card number to use instead of payment.card_number.
            Useful when the actual card differs from config (e.g., tokenized).

    Returns:
        A dict of form field names → values suitable for POST submission.
    """
    result: dict[str, Any] = {}

    for info_field, form_field in field_mapping.items():
        value: Any = ""
        if info_field == "card_number" and card_number:
            value = card_number
        else:
            value = getattr(payment, info_field, "")
        if value:  # Skip empty values
            result[form_field] = value

    return result


def get_standard_payment_field_mapping() -> dict[str, str]:
    """Return the standard/common payment field mapping.

    Returns:
        A mapping from PaymentInfo field names to common form field names.
    """
    return {
        "card_number": "cc-number",
        "expiry_month": "cc-month",
        "expiry_year": "cc-year",
        "cvv": "cc-cvv",
        "card_type": "cc-type",
    }


# ── PaymentAutofill ────────────────────────────────────────────────────────────


class PaymentAutofill:
    """Handles payment form autofill during checkout.

    Accepts PaymentInfo from config and applies it to retailer payment forms.
    All card data is masked in logs.

    Per PRD Sections 9.3 (CO-2) and 10.3 (Security).
    """

    def __init__(self, payment_info: PaymentInfo) -> None:
        """Initialize the payment autofill handler.

        Args:
            payment_info: The PaymentInfo object from config.
        """
        self._payment = payment_info

    def build_form_data(
        self,
        field_mapping: dict[str, str],
        card_number: str | None = None,
    ) -> dict[str, Any]:
        """Build the payment form data for retailer-specific submission.

        Args:
            field_mapping: Payment field name mapping for the retailer.
            card_number: Optional card number override (for tokenized cards).

        Returns:
            Form data dict with masked card info in log-safe format.
        """
        return build_payment_form_data(
            self._payment,
            field_mapping,
            card_number=card_number,
        )

    def get_masked_card_display(self, card_number: str | None = None) -> str:
        """Get a log-safe masked card display string.

        Args:
            card_number: Optional card number override.

        Returns:
            Masked card string safe for logging, e.g. "************1234".
        """
        num = card_number or self._payment.card_number
        return format_card_display(num)

    @property
    def payment_info(self) -> PaymentInfo:
        """Return the PaymentInfo object."""
        return self._payment

    @property
    def card_type(self) -> str:
        """Return the detected card type."""
        return detect_card_type(self._payment.card_number)


# ── PaymentDeclineHandler ──────────────────────────────────────────────────────


class PaymentDeclineHandler:
    """Handles payment decline detection and retry logic.

    Retries once after a 2-second delay on decline, aborts on second failure.
    Fires PAYMENT_DECLINED webhook events.

    Per PRD Sections 9.3 (CO-2, CO-6).
    """

    def __init__(
        self,
        max_retries: int = 1,
        retry_delay_seconds: float = 2.0,
    ) -> None:
        """Initialize the decline handler.

        Args:
            max_retries: Maximum retry attempts after decline (default 1).
            retry_delay_seconds: Delay before retry (default 2.0s).
        """
        self._max_retries = max_retries
        self._retry_delay = retry_delay_seconds
        self._attempt_count = 0

    async def handle_decline(
        self,
        decline_code: str,
        retailer: str,
        item: str,
        webhook_callback: Any = None,
    ) -> bool:
        """Handle a payment decline with retry logic.

        If attempts remain, waits retry_delay_seconds and returns True to retry.
        If attempts exhausted, fires PAYMENT_DECLINED webhook and returns False.

        Args:
            decline_code: The decline code from the retailer.
            retailer: The retailer name.
            item: The item being purchased.
            webhook_callback: Optional callable that fires a WebhookEvent.
                Called with a PAYMENT_DECLINED WebhookEvent.

        Returns:
            True if a retry will be attempted (caller should retry checkout).
            False if no retries remain (caller should abort).
        """
        self._attempt_count += 1

        if self._attempt_count <= self._max_retries:
            # Retry after delay
            await asyncio.sleep(self._retry_delay)
            return True

        # Exhausted retries — fire webhook and abort
        if webhook_callback is not None:
            event = WebhookEvent(
                event="PAYMENT_DECLINED",
                item=item,
                retailer=retailer,
                decline_code=decline_code,
            )
            if asyncio.iscoroutinefunction(webhook_callback):
                await webhook_callback(event)
            else:
                webhook_callback(event)

        return False

    def reset(self) -> None:
        """Reset the attempt counter for a new checkout attempt."""
        self._attempt_count = 0

    @property
    def attempt_count(self) -> int:
        """Return the current attempt count."""
        return self._attempt_count


__all__ = [
    "PaymentAutofill",
    "PaymentDeclineHandler",
    "build_payment_form_data",
    "get_standard_payment_field_mapping",
    "detect_card_type",
    "mask_card_number",
    "format_card_display",
]
