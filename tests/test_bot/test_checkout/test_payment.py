"""Tests for payment autofill and decline handling."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.checkout.payment import (
    PaymentAutofill,
    PaymentDeclineHandler,
    build_payment_form_data,
    detect_card_type,
    format_card_display,
    get_standard_payment_field_mapping,
    mask_card_number,
)
from src.shared.models import PaymentInfo


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_payment() -> PaymentInfo:
    """Sample payment info for tests."""
    return PaymentInfo(
        card_number="4111111111111111",
        expiry_month="12",
        expiry_year="2027",
        cvv="123",
        card_type="Visa",
    )


@pytest.fixture
def standard_payment_mapping() -> dict[str, str]:
    """Standard payment field mapping."""
    return {
        "card_number": "cc-number",
        "expiry_month": "cc-month",
        "expiry_year": "cc-year",
        "cvv": "cc-cvv",
        "card_type": "cc-type",
    }


# ── Card Type Detection ────────────────────────────────────────────────────────


class TestDetectCardType:
    """Tests for detect_card_type()."""

    @pytest.mark.parametrize(
        "card_number,expected",
        [
            ("4111111111111111", "Visa"),
            ("4242424242424242", "Visa"),
            ("5555555555554444", "Mastercard"),
            ("5105105105105100", "Mastercard"),
            ("378282246310005", "American Express"),
            ("371449635398431", "American Express"),
            ("6011111111111117", "Discover"),
            ("6011000990139424", "Discover"),
            ("1234567890", "Unknown"),
            ("", "Unknown"),
        ],
    )
    def test_detects_card_types(self, card_number: str, expected: str):
        """Correct card types are detected from card numbers."""
        assert detect_card_type(card_number) == expected


# ── Card Number Masking ────────────────────────────────────────────────────────


class TestMaskCardNumber:
    """Tests for mask_card_number()."""

    def test_masks_all_but_last_4(self):
        """Only last 4 digits are visible."""
        result = mask_card_number("4111111111111111")
        assert result == "************1111"

    def test_shows_last_4_by_default(self):
        """Default show_last is 4 digits."""
        assert mask_card_number("4111111111111111") == "************1111"

    def test_shows_custom_digit_count(self):
        """Custom show_last works correctly."""
        assert mask_card_number("4111111111111111", show_last=6) == "**********111111"

    def test_handles_short_numbers(self):
        """Short numbers are fully masked."""
        assert mask_card_number("123") == "***"

    def test_strips_non_digits(self):
        """Non-digit characters are stripped before processing."""
        result = mask_card_number("4111-1111-1111-1111")
        assert result == "************1111"

    def test_empty_string(self):
        """Empty string returns empty."""
        assert mask_card_number("") == ""


class TestFormatCardDisplay:
    """Tests for format_card_display()."""

    def test_formats_with_spaces(self):
        """Card number is formatted with spaces every 4 digits."""
        result = format_card_display("4111111111111111")
        assert result == "**** **** **** 1111"

    def test_masks_full_number(self):
        """The formatted display shows all masked digits."""
        result = format_card_display("4111111111111111")
        assert "4111" not in result  # No unmasked leading digits


# ── build_payment_form_data ────────────────────────────────────────────────────


class TestBuildPaymentFormData:
    """Tests for build_payment_form_data()."""

    def test_maps_all_fields(self, sample_payment, standard_payment_mapping):
        """All non-empty fields are included."""
        result = build_payment_form_data(sample_payment, standard_payment_mapping)

        assert result["cc-number"] == "4111111111111111"
        assert result["cc-month"] == "12"
        assert result["cc-year"] == "2027"
        assert result["cc-cvv"] == "123"
        assert result["cc-type"] == "Visa"

    def test_skips_empty_fields(self, standard_payment_mapping):
        """Empty fields are not included in output."""
        payment = PaymentInfo(
            card_number="4111111111111111",
            expiry_month="12",
        )
        result = build_payment_form_data(payment, standard_payment_mapping)

        assert result["cc-number"] == "4111111111111111"
        assert result["cc-month"] == "12"
        assert "cc-year" not in result
        assert "cc-cvv" not in result

    def test_card_number_override(self, sample_payment, standard_payment_mapping):
        """Card number override takes precedence over PaymentInfo card_number."""
        result = build_payment_form_data(
            sample_payment,
            standard_payment_mapping,
            card_number="5555555555554444",
        )

        assert result["cc-number"] == "5555555555554444"

    def test_empty_payment_info(self, standard_payment_mapping):
        """Empty PaymentInfo produces empty form data."""
        result = build_payment_form_data(PaymentInfo(), standard_payment_mapping)
        assert result == {}

    def test_custom_field_mapping(self, sample_payment):
        """Custom retailer field names work correctly."""
        mapping = {
            "card_number": "card_num",
            "expiry_month": "exp_mo",
        }
        result = build_payment_form_data(sample_payment, mapping)

        assert result["card_num"] == "4111111111111111"
        assert result["exp_mo"] == "12"
        # Fields not in mapping are excluded
        assert "cc-year" not in result


# ── PaymentAutofill ────────────────────────────────────────────────────────────


class TestPaymentAutofill:
    """Tests for PaymentAutofill class."""

    def test_build_form_data(self, sample_payment):
        """build_form_data() produces correct payment form data."""
        autofill = PaymentAutofill(sample_payment)
        mapping = {
            "card_number": "cc-number",
            "expiry_month": "cc-month",
            "expiry_year": "cc-year",
            "cvv": "cc-cvv",
        }

        result = autofill.build_form_data(mapping)

        assert result["cc-number"] == "4111111111111111"
        assert result["cc-month"] == "12"
        assert result["cc-year"] == "2027"
        assert result["cc-cvv"] == "123"

    def test_get_masked_card_display(self, sample_payment):
        """Masked card display returns a safe-for-logging string."""
        autofill = PaymentAutofill(sample_payment)
        result = autofill.get_masked_card_display()

        assert "4111111111111111" not in result
        assert "1111" in result  # Last 4 visible
        assert "****" in result

    def test_card_type_property(self, sample_payment):
        """card_type property returns detected card type."""
        autofill = PaymentAutofill(sample_payment)
        assert autofill.card_type == "Visa"

    def test_payment_info_property(self, sample_payment):
        """payment_info property returns the PaymentInfo object."""
        autofill = PaymentAutofill(sample_payment)
        assert autofill.payment_info == sample_payment


# ── PaymentDeclineHandler ──────────────────────────────────────────────────────


class TestPaymentDeclineHandler:
    """Tests for PaymentDeclineHandler retry logic."""

    def test_initial_state(self):
        """Handler starts with attempt_count=0."""
        handler = PaymentDeclineHandler()
        assert handler.attempt_count == 0

    def test_reset(self):
        """reset() resets attempt count."""
        handler = PaymentDeclineHandler()
        # Simulate attempts
        handler._attempt_count = 3
        handler.reset()
        assert handler.attempt_count == 0

    @pytest.mark.asyncio
    async def test_first_decline_retries(self):
        """First decline triggers retry (returns True after delay)."""
        handler = PaymentDeclineHandler(max_retries=1, retry_delay_seconds=0.01)

        result = await handler.handle_decline(
            decline_code="insufficient_funds",
            retailer="Target",
            item="Charizard Box",
        )

        assert result is True
        assert handler.attempt_count == 1

    @pytest.mark.asyncio
    async def test_second_decline_aborts(self):
        """Second decline (after exhausted retries) returns False."""
        handler = PaymentDeclineHandler(max_retries=1, retry_delay_seconds=0.01)

        # First decline — retries
        result1 = await handler.handle_decline(
            decline_code="insufficient_funds",
            retailer="Target",
            item="Charizard Box",
        )
        # Second decline — exhausted retries, aborts
        result2 = await handler.handle_decline(
            decline_code="insufficient_funds",
            retailer="Target",
            item="Charizard Box",
        )

        assert result1 is True
        assert result2 is False
        assert handler.attempt_count == 2

    @pytest.mark.asyncio
    async def test_fires_webhook_on_abort(self):
        """PAYMENT_DECLINED webhook is fired when retries exhausted."""
        handler = PaymentDeclineHandler(max_retries=1, retry_delay_seconds=0.01)
        mock_callback = AsyncMock()

        # Exhaust retries
        await handler.handle_decline(
            decline_code="card_declined",
            retailer="Target",
            item="Charizard Box",
            webhook_callback=mock_callback,
        )
        await handler.handle_decline(
            decline_code="card_declined",
            retailer="Target",
            item="Charizard Box",
            webhook_callback=mock_callback,
        )

        # Webhook should have been called once (on the abort)
        mock_callback.assert_called_once()
        event = mock_callback.call_args[0][0]
        assert event.event == "PAYMENT_DECLINED"
        assert event.decline_code == "card_declined"
        assert event.retailer == "Target"
        assert event.item == "Charizard Box"

    @pytest.mark.asyncio
    async def test_no_webhook_on_retry(self):
        """Webhook is NOT fired on retry (only on abort)."""
        handler = PaymentDeclineHandler(max_retries=1, retry_delay_seconds=0.01)
        mock_callback = AsyncMock()

        await handler.handle_decline(
            decline_code="insufficient_funds",
            retailer="Target",
            item="Charizard Box",
            webhook_callback=mock_callback,
        )

        # No webhook on retry
        mock_callback.assert_not_called()
        assert handler.attempt_count == 1

    @pytest.mark.asyncio
    async def test_no_retry_when_max_retries_0(self):
        """max_retries=0 means immediate abort without delay."""
        handler = PaymentDeclineHandler(max_retries=0)

        result = await handler.handle_decline(
            decline_code="declined",
            retailer="Target",
            item="Test Item",
        )

        assert result is False
        assert handler.attempt_count == 1

    @pytest.mark.asyncio
    async def test_multiple_retries(self):
        """max_retries=2 allows two retries before aborting."""
        handler = PaymentDeclineHandler(max_retries=2, retry_delay_seconds=0.01)

        result1 = await handler.handle_decline(decline_code="x", retailer="R", item="I")
        result2 = await handler.handle_decline(decline_code="x", retailer="R", item="I")
        result3 = await handler.handle_decline(decline_code="x", retailer="R", item="I")

        assert result1 is True
        assert result2 is True
        assert result3 is False


# ── get_standard_payment_field_mapping ─────────────────────────────────────────


class TestGetStandardPaymentFieldMapping:
    """Tests for get_standard_payment_field_mapping()."""

    def test_returns_all_fields(self):
        """Standard mapping includes all expected fields."""
        mapping = get_standard_payment_field_mapping()

        assert mapping["card_number"] == "cc-number"
        assert mapping["expiry_month"] == "cc-month"
        assert mapping["expiry_year"] == "cc-year"
        assert mapping["cvv"] == "cc-cvv"
        assert mapping["card_type"] == "cc-type"
