"""Tests for shared/models.py (SHARED-T03: Shared dataclasses/models)."""

from __future__ import annotations

import json

import pytest

from src.shared.models import (
    CaptchaMode,
    CaptchaType,
    CheckoutStage,
    DropWindow,
    MonitoredItem,
    PaymentInfo,
    RetailerAdapterConfig,
    SessionState,
    ShippingInfo,
    StockStatus,
    WebhookEvent,
)


class TestEnums:
    """Test enum values."""

    def test_captcha_mode_values(self) -> None:
        """CaptchaMode should have auto, manual, smart values."""
        assert CaptchaMode.AUTO.value == "auto"
        assert CaptchaMode.MANUAL.value == "manual"
        assert CaptchaMode.SMART.value == "smart"

    def test_captcha_type_values(self) -> None:
        """CaptchaType should cover all expected challenge types."""
        assert CaptchaType.RECAPTCHA_V2.value == "recaptcha_v2"
        assert CaptchaType.HCAPTCHA.value == "hcaptcha"
        assert CaptchaType.TURNSTILE.value == "turnstile"

    def test_checkout_stage_values(self) -> None:
        """CheckoutStage should have all expected stages."""
        stages = [s.value for s in CheckoutStage]
        assert "shipping" in stages
        assert "payment" in stages
        assert "submit" in stages


class TestMonitoredItem:
    """Test MonitoredItem dataclass."""

    def test_creation(self) -> None:
        """MonitoredItem should be created with all required fields."""
        item = MonitoredItem(
            id="uuid-123",
            name="Pikachu Plush",
            retailers=["target"],
            skus=["123456"],
            keywords=["pikachu", "plush"],
        )
        assert item.id == "uuid-123"
        assert item.name == "Pikachu Plush"
        assert item.max_cart_quantity == 1  # default

    def test_enabled_default_true(self) -> None:
        """enabled should default to True."""
        item = MonitoredItem(
            id="1", name="X", retailers=[], skus=[], keywords=[]
        )
        assert item.enabled is True

    def test_max_cart_quantity_default(self) -> None:
        """max_cart_quantity should default to 1."""
        item = MonitoredItem(
            id="1", name="X", retailers=[], skus=[], keywords=[]
        )
        assert item.max_cart_quantity == 1


class TestShippingInfo:
    """Test ShippingInfo dataclass."""

    def test_required_fields(self) -> None:
        """ShippingInfo should require all address fields."""
        info = ShippingInfo(
            name="Jane Doe",
            address1="123 Main St",
            city="Portland",
            state="OR",
            zip_code="97201",
            phone="555-1234",
        )
        assert info.name == "Jane Doe"
        assert info.address2 == ""  # default
        assert info.email == ""  # default


class TestPaymentInfo:
    """Test PaymentInfo dataclass."""

    def test_card_type_empty_by_default(self) -> None:
        """card_type should default to empty string."""
        p = PaymentInfo(
            card_number="4111111111111111",
            expiry_month="12",
            expiry_year="2027",
            cvv="123",
        )
        assert p.card_type == ""

    def test_all_fields_set(self) -> None:
        """PaymentInfo should accept all fields."""
        p = PaymentInfo(
            card_number="4111111111111111",
            expiry_month="06",
            expiry_year="2026",
            cvv="456",
            card_type="visa",
        )
        assert p.card_type == "visa"


class TestWebhookEvent:
    """Test WebhookEvent dataclass."""

    def test_minimal_event(self) -> None:
        """Minimal event with just event name."""
        ev = WebhookEvent(event="MONITOR_STARTED")
        assert ev.event == "MONITOR_STARTED"
        assert ev.item == ""

    def test_full_event_with_all_fields(self) -> None:
        """Full event with all optional fields populated."""
        ev = WebhookEvent(
            event="CHECKOUT_SUCCESS",
            item="Charizard Box",
            retailer="walmart",
            timestamp="2026-04-20T10:00:00Z",
            order_id="ORDER-999",
            attempt=1,
            total="$149.99",
        )
        assert ev.order_id == "ORDER-999"
        assert ev.total == "$149.99"

    def test_to_dict_excludes_empty_fields(self) -> None:
        """to_dict should exclude fields with empty string values."""
        ev = WebhookEvent(event="STOCK_DETECTED", item="X", retailer="t")
        d = ev.to_dict()
        assert "event" in d
        assert "order_id" not in d  # empty
        assert "error" not in d  # empty

    def test_to_dict_includes_non_empty_fields(self) -> None:
        """to_dict should include fields with non-empty values."""
        ev = WebhookEvent(
            event="CHECKOUT_FAILED",
            item="Y",
            retailer="b",
            error="Payment declined",
            attempt=2,
        )
        d = ev.to_dict()
        assert d["event"] == "CHECKOUT_FAILED"
        assert d["item"] == "Y"
        assert d["error"] == "Payment declined"
        assert d["attempt"] == 2

    def test_to_dict_numeric_zeros_excluded(self) -> None:
        """Zero-valued numeric fields should be excluded."""
        ev = WebhookEvent(event="E", item="X", solve_time_ms=0, attempt=0)
        d = ev.to_dict()
        assert "solve_time_ms" not in d
        assert "attempt" not in d  # explicitly set to 0

    def test_to_dict_numeric_non_zeros_included(self) -> None:
        """Non-zero numeric fields should be included."""
        ev = WebhookEvent(event="E", item="X", attempt=1, solve_time_ms=5000)
        d = ev.to_dict()
        assert d["attempt"] == 1
        assert d["solve_time_ms"] == 5000

    def test_json_serializable(self) -> None:
        """to_dict output should be JSON serializable."""
        ev = WebhookEvent(
            event="CHECKOUT_SUCCESS",
            item="Z",
            retailer="t",
            timestamp="2026-04-20T10:00:00Z",
            order_id="ORD-1",
            total="$99.99",
        )
        json_str = json.dumps(ev.to_dict())
        parsed = json.loads(json_str)
        assert parsed["event"] == "CHECKOUT_SUCCESS"
        assert parsed["order_id"] == "ORD-1"


class TestSessionState:
    """Test SessionState dataclass."""

    def test_default_values(self) -> None:
        """SessionState should have sensible defaults."""
        state = SessionState()
        assert state.cookies == {}
        assert state.auth_token == ""
        assert state.is_valid is True

    def test_with_values(self) -> None:
        """SessionState should accept all fields."""
        state = SessionState(
            cookies={"session_id": "abc"},
            auth_token="tok123",
            cart_token="cart456",
            prewarmed_at="2026-04-20T09:00:00Z",
            is_valid=True,
        )
        assert state.cookies["session_id"] == "abc"
        assert state.is_valid is True


class TestDropWindow:
    """Test DropWindow dataclass."""

    def test_defaults(self) -> None:
        """DropWindow should have sensible defaults."""
        dw = DropWindow()
        assert dw.id == 0
        assert dw.prewarm_minutes == 15
        assert dw.enabled is True
        assert dw.max_cart_quantity == 1

    def test_full_values(self) -> None:
        """DropWindow should accept all fields."""
        dw = DropWindow(
            id=5,
            item="Pikachu Plush",
            retailer="target",
            drop_datetime="2026-04-20T09:00:00-07:00",
            prewarm_minutes=20,
            enabled=True,
            max_cart_quantity=2,
        )
        assert dw.id == 5
        assert dw.max_cart_quantity == 2


class TestRetailerAdapterConfig:
    """Test RetailerAdapterConfig dataclass."""

    def test_defaults(self) -> None:
        """RetailerAdapterConfig should have sensible defaults."""
        cfg = RetailerAdapterConfig(name="target", base_url="https://target.com")
        assert cfg.enabled is True
        assert cfg.check_interval_ms == 500
        assert cfg.prewarm_minutes == 15
        assert cfg.requires_login is True
        assert cfg.has_queue is False


class TestStockStatus:
    """Test StockStatus dataclass."""

    def test_in_stock_true(self) -> None:
        """StockStatus with in_stock=True."""
        status = StockStatus(
            in_stock=True,
            sku="123456",
            url="https://target.com/p/123456",
            price="$29.99",
            available_quantity=5,
        )
        assert status.in_stock is True
        assert status.available_quantity == 5

    def test_in_stock_false(self) -> None:
        """StockStatus with in_stock=False."""
        status = StockStatus(in_stock=False, sku="999999")
        assert status.in_stock is False
        assert status.url == ""
        assert status.available_quantity == 0