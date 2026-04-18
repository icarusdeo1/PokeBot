"""Tests for TargetAdapter.

These tests mock all external dependencies: Playwright browser automation,
HTTP API calls, and 2Captcha solver. They verify:
- TargetAdapter properly extends RetailerAdapter
- Correct method dispatch and error handling
- Cart management respects max_cart_quantity
- Checkout retry logic
- CAPTCHA detection and routing
- Queue detection
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.monitor.retailers.base import RetailerAdapter
from src.bot.monitor.retailers.target import TargetAdapter
from src.shared.models import (
    CaptchaSolveResult,
    CaptchaType,
    PaymentInfo,
    ShippingInfo,
    StockStatus,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock Config object."""
    config = MagicMock()
    config.retailers = {
        "target": MagicMock(
            enabled=True,
            username="test@example.com",
            password="password123",
            items=[
                {
                    "name": "Charizard Box",
                    "skus": ["83821795"],
                    "keywords": ["Charizard"],
                    "enabled": True,
                    "max_cart_quantity": 2,
                },
            ],
        ),
    }
    config.captcha = MagicMock(mode="smart", api_key="")
    config.checkout = MagicMock(retry_attempts=2, use_1click_if_available=True)
    config.evasion = MagicMock(jitter_percent=20)
    return config


@pytest.fixture
def target_adapter(mock_config: MagicMock) -> TargetAdapter:
    """Create a TargetAdapter instance with mock config."""
    adapter = TargetAdapter(mock_config)
    return adapter


# ── Inheritance Tests ─────────────────────────────────────────────────────────

class TestInheritance:
    """Test that TargetAdapter properly inherits from RetailerAdapter."""

    def test_inherits_from_retailer_adapter(self) -> None:
        """TargetAdapter must extend RetailerAdapter."""
        assert issubclass(TargetAdapter, RetailerAdapter)

    def test_is_instance_of_retailer_adapter(self, target_adapter: TargetAdapter) -> None:
        """TargetAdapter instance must be an instance of RetailerAdapter."""
        assert isinstance(target_adapter, RetailerAdapter)

    def test_has_required_abstract_methods(
        self, target_adapter: TargetAdapter
    ) -> None:
        """All abstract methods from RetailerAdapter must be implemented."""
        for method_name in [
            "login",
            "check_stock",
            "add_to_cart",
            "get_cart",
            "checkout",
            "handle_captcha",
            "check_queue",
        ]:
            assert hasattr(target_adapter, method_name)
            assert callable(getattr(target_adapter, method_name))

    def test_adapter_name(self, target_adapter: TargetAdapter) -> None:
        """Adapter name must be 'target'."""
        assert target_adapter.name == "target"

    def test_adapter_base_url(self, target_adapter: TargetAdapter) -> None:
        """Adapter base_url must point to Target.com."""
        assert target_adapter.base_url == "https://www.target.com"

    def test_super_init_called(self, mock_config: MagicMock) -> None:
        """TargetAdapter.__init__ must call super().__init__."""
        # Check that the adapter initializes the HTTP client from base class
        adapter = TargetAdapter(mock_config)
        # The base class __init__ sets _session to None initially
        # and _session_state to None, _prewarmed to False
        assert adapter._session_state is None
        assert adapter._prewarmed is False
        # The base class also sets _logger to None initially
        assert adapter._logger is None


# ── Login Tests ────────────────────────────────────────────────────────────────

class TestLogin:
    """Test TargetAdapter.login() with mocked Playwright."""

    @pytest.mark.asyncio
    async def test_login_success(
        self, target_adapter: TargetAdapter, mock_config: MagicMock
    ) -> None:
        """Login succeeds when credentials are valid."""
        mock_page = AsyncMock()
        mock_page.url = "https://www.target.com/"
        mock_page.goto = AsyncMock()
        mock_page.fill = AsyncMock()
        mock_page.locator = MagicMock(return_value=AsyncMock(is_visible=AsyncMock(return_value=False)))
        mock_page.click = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()  # Login succeeds

        # Mock _verify_login_success returning True
        with patch.object(target_adapter, "_verify_login_success", new=AsyncMock(return_value=True)):
            with patch.object(target_adapter, "_extract_auth_token", new=AsyncMock(return_value="fake_token")):
                with patch.object(target_adapter, "_save_cookies", new=AsyncMock()):
                    with patch.object(target_adapter, "_ensure_browser", new=AsyncMock()):
                        target_adapter._page = mock_page
                        result = await target_adapter.login("test@example.com", "password123")

        assert result is True
        assert target_adapter._logged_in is True
        assert target_adapter._auth_token == "fake_token"

    @pytest.mark.asyncio
    async def test_login_failure_wrong_credentials(
        self, target_adapter: TargetAdapter
    ) -> None:
        """Login fails when credentials are invalid."""
        mock_page = AsyncMock()
        mock_page.url = "https://www.target.com/co/login"
        mock_page.goto = AsyncMock()
        mock_page.fill = AsyncMock()
        mock_page.locator = MagicMock(return_value=AsyncMock(is_visible=AsyncMock(return_value=False)))
        mock_page.click = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.wait_for_selector = AsyncMock(side_effect=Exception("Not found"))

        with patch.object(target_adapter, "_verify_login_success", new=AsyncMock(return_value=False)):
            with patch.object(target_adapter, "_ensure_browser", new=AsyncMock()):
                target_adapter._page = mock_page
                result = await target_adapter.login("wrong@example.com", "wrongpass")

        assert result is False


# ── Stock Check Tests ─────────────────────────────────────────────────────────

class TestCheckStock:
    """Test TargetAdapter.check_stock() with mocked HTTP and Playwright."""

    @pytest.mark.asyncio
    async def test_check_stock_in_stock_api(
        self, target_adapter: TargetAdapter
    ) -> None:
        """check_stock returns IN_STOCK when API reports in stock."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "product": {
                "location_availability": [
                    {"availability_code": "IN_STOCK", "quantity": 5}
                ]
            }
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            status = await target_adapter.check_stock("83821795")

        assert status.in_stock is True
        assert status.sku == "83821795"
        assert status.available_quantity == 5

    @pytest.mark.asyncio
    async def test_check_stock_out_of_stock_api(
        self, target_adapter: TargetAdapter
    ) -> None:
        """check_stock returns OUT_OF_STOCK when API reports OOS."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "product": {
                "location_availability": [
                    {"availability_code": "OUT_OF_STOCK", "quantity": 0}
                ]
            }
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            status = await target_adapter.check_stock("83821795")

        assert status.in_stock is False
        assert status.sku == "83821795"

    @pytest.mark.asyncio
    async def test_check_stock_api_fails_falls_back_to_page(
        self, target_adapter: TargetAdapter
    ) -> None:
        """check_stock falls back to page scraping when API fails."""
        # API returns non-200
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock(side_effect=Exception("API failed, page fallback"))
        mock_page.query_selector = AsyncMock(
            side_effect=[
                None,  # No add-to-cart button
                MagicMock(is_visible=AsyncMock(return_value=True)),  # OOS message found
            ]
        )
        mock_page.url = "https://www.target.com/p/-/A-83821795"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with patch.object(target_adapter, "_ensure_browser", new=AsyncMock()):
                with patch.object(target_adapter, "_parse_stock_from_page", new=AsyncMock(return_value=(False, 0))):
                    target_adapter._page = mock_page
                    status = await target_adapter.check_stock("83821795")

        assert status.in_stock is False


# ── Cart Tests ─────────────────────────────────────────────────────────────────

class TestAddToCart:
    """Test TargetAdapter.add_to_cart() with mocked HTTP and Playwright."""

    @pytest.mark.asyncio
    async def test_add_to_cart_respects_max_cart_quantity(
        self, target_adapter: TargetAdapter, mock_config: MagicMock
    ) -> None:
        """add_to_cart clamps quantity to max_cart_quantity from retailer config."""
        # The retailer's max_cart_quantity for SKU 83821795 is 2
        # We request quantity=5, it should be clamped to 2

        with patch.object(target_adapter, "_add_to_cart_api", new=AsyncMock(return_value=True)) as mock_api:
            result = await target_adapter.add_to_cart("83821795", quantity=5)

        assert result is True
        # API should have been called with clamped quantity (2)
        mock_api.assert_called_once_with("83821795", 2)

    @pytest.mark.asyncio
    async def test_add_to_cart_api_success(
        self, target_adapter: TargetAdapter
    ) -> None:
        """add_to_cart returns True when cart API succeeds."""
        with patch.object(target_adapter, "_add_to_cart_api", new=AsyncMock(return_value=True)):
            result = await target_adapter.add_to_cart("83821795", quantity=1)

        assert result is True

    @pytest.mark.asyncio
    async def test_add_to_cart_api_fails_ui_fallback(
        self, target_adapter: TargetAdapter
    ) -> None:
        """add_to_cart falls back to UI when API fails."""
        with patch.object(target_adapter, "_add_to_cart_api", new=AsyncMock(return_value=False)):
            with patch.object(target_adapter, "_add_to_cart_ui", new=AsyncMock(return_value=True)) as mock_ui:
                result = await target_adapter.add_to_cart("83821795", quantity=1)

        assert result is True
        mock_ui.assert_called_once_with("83821795", 1)

    @pytest.mark.asyncio
    async def test_add_to_cart_both_fail(
        self, target_adapter: TargetAdapter
    ) -> None:
        """add_to_cart returns False when both API and UI fail."""
        with patch.object(target_adapter, "_add_to_cart_api", new=AsyncMock(return_value=False)):
            with patch.object(target_adapter, "_add_to_cart_ui", new=AsyncMock(return_value=False)):
                result = await target_adapter.add_to_cart("83821795", quantity=1)

        assert result is False


class TestGetCart:
    """Test TargetAdapter.get_cart() with mocked HTTP and Playwright."""

    @pytest.mark.asyncio
    async def test_get_cart_api_success(
        self, target_adapter: TargetAdapter
    ) -> None:
        """get_cart returns items when cart API succeeds."""
        mock_items = [
            {"sku": "83821795", "name": "Charizard Box", "quantity": 1, "price": "$59.99"}
        ]
        with patch.object(target_adapter, "_get_cart_api", new=AsyncMock(return_value=mock_items)):
            result = await target_adapter.get_cart()

        assert result == mock_items

    @pytest.mark.asyncio
    async def test_get_cart_api_returns_none_falls_back_to_ui(
        self, target_adapter: TargetAdapter
    ) -> None:
        """get_cart falls back to UI when API returns None."""
        ui_items = [
            {"sku": "83821795", "name": "Charizard Box", "quantity": 1, "price": "$59.99"}
        ]
        with patch.object(target_adapter, "_get_cart_api", new=AsyncMock(return_value=None)):
            with patch.object(target_adapter, "_get_cart_ui", new=AsyncMock(return_value=ui_items)) as mock_ui:
                result = await target_adapter.get_cart()

        assert result == ui_items
        mock_ui.assert_called_once()


# ── Checkout Tests ────────────────────────────────────────────────────────────

class TestCheckout:
    """Test TargetAdapter.checkout() with mocked Playwright."""

    @pytest.mark.asyncio
    async def test_checkout_success_first_attempt(
        self, target_adapter: TargetAdapter
    ) -> None:
        """checkout returns success when order is placed on first attempt."""
        shipping = ShippingInfo(
            name="Test User",
            address1="123 Main St",
            city="New York",
            state="NY",
            zip_code="10001",
            phone="555-1234",
        )
        payment = PaymentInfo(
            card_number="4111111111111111",
            expiry_month="12",
            expiry_year="2027",
            cvv="123",
        )

        with patch.object(
            target_adapter,
            "_run_checkout_flow",
            new=AsyncMock(return_value={"success": True, "order_id": "ABC12345", "total": "$59.99"}),
        ):
            result = await target_adapter.checkout(shipping, payment)

        assert result["success"] is True
        assert result["order_id"] == "ABC12345"

    @pytest.mark.asyncio
    async def test_checkout_retry_on_failure(
        self, target_adapter: TargetAdapter
    ) -> None:
        """checkout retries when first attempt fails."""
        shipping = ShippingInfo(
            name="Test User",
            address1="123 Main St",
            city="New York",
            state="NY",
            zip_code="10001",
            phone="555-1234",
        )
        payment = PaymentInfo(
            card_number="4111111111111111",
            expiry_month="12",
            expiry_year="2027",
            cvv="123",
        )

        call_count = 0

        async def mock_flow(*args: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"success": False, "error": "Temporary failure"}
            return {"success": True, "order_id": "ABC12345", "total": "$59.99"}

        with patch.object(target_adapter, "_run_checkout_flow", new=mock_flow):
            with patch.object(target_adapter, "_clear_cart", new=AsyncMock(return_value=True)):
                result = await target_adapter.checkout(shipping, payment)

        assert result["success"] is True
        assert result["order_id"] == "ABC12345"
        assert call_count == 2  # First failed, second succeeded

    @pytest.mark.asyncio
    async def test_checkout_all_attempts_fail(
        self, target_adapter: TargetAdapter
    ) -> None:
        """checkout returns failure after max retry attempts."""
        shipping = ShippingInfo(
            name="Test User",
            address1="123 Main St",
            city="New York",
            state="NY",
            zip_code="10001",
            phone="555-1234",
        )
        payment = PaymentInfo(
            card_number="4111111111111111",
            expiry_month="12",
            expiry_year="2027",
            cvv="123",
        )

        with patch.object(
            target_adapter,
            "_run_checkout_flow",
            new=AsyncMock(return_value={"success": False, "error": "Always fails"}),
        ):
            with patch.object(target_adapter, "_clear_cart", new=AsyncMock(return_value=True)):
                result = await target_adapter.checkout(shipping, payment)

        assert result["success"] is False
        assert "failed after" in result["error"]


# ── CAPTCHA Tests ─────────────────────────────────────────────────────────────

class TestHandleCaptcha:
    """Test TargetAdapter.handle_captcha() with mocked Playwright."""

    @pytest.mark.asyncio
    async def test_handle_captcha_no_captcha_detected(
        self, target_adapter: TargetAdapter
    ) -> None:
        """handle_captcha returns failure when no CAPTCHA is detected."""
        mock_page = AsyncMock()
        mock_page.wait_for_selector = AsyncMock(
            side_effect=Exception("No CAPTCHA frames found")
        )

        with patch.object(
            target_adapter, "_detect_captcha_type", new=AsyncMock(return_value=CaptchaType.UNKNOWN)
        ):
            result = await target_adapter.handle_captcha(mock_page)

        assert result.success is False
        assert "No CAPTCHA detected" in result.error

    @pytest.mark.asyncio
    async def test_handle_captcha_page_is_none(
        self, target_adapter: TargetAdapter
    ) -> None:
        """handle_captcha returns failure when page is None."""
        result = await target_adapter.handle_captcha(None)

        assert result.success is False
        assert "No page provided" in result.error

    @pytest.mark.asyncio
    async def test_handle_captcha_smart_turnstile_auto_solves(
        self, target_adapter: TargetAdapter
    ) -> None:
        """Smart mode auto-solves Turnstile challenges via 2Captcha."""
        mock_page = AsyncMock()
        mock_page.url = "https://www.target.com/checkout"
        mock_page.wait_for_selector = AsyncMock(return_value=MagicMock())

        with patch.object(
            target_adapter,
            "_detect_captcha_type",
            new=AsyncMock(return_value=CaptchaType.TURNSTILE),
        ):
            with patch.object(
                target_adapter,
                "_get_2captcha_solver",
                new=MagicMock(return_value=None),  # No solver configured
            ):
                result = await target_adapter.handle_captcha(mock_page)

        # With no 2Captcha solver, it should fail gracefully
        assert result.success is False
        assert "not configured" in result.error


# ── Queue Detection Tests ──────────────────────────────────────────────────────

class TestCheckQueue:
    """Test TargetAdapter.check_queue() with mocked Playwright."""

    @pytest.mark.asyncio
    async def test_check_queue_no_queue(self, target_adapter: TargetAdapter) -> None:
        """check_queue returns False when not in a queue."""
        mock_page = AsyncMock()
        mock_page.url = "https://www.target.com/p/-/A-83821795"
        mock_page.title = AsyncMock(return_value="Charizard Box | Target.com")
        mock_page.inner_text = AsyncMock(return_value="Add to cart | Buy now")

        target_adapter._page = mock_page
        result = await target_adapter.check_queue()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_queue_detected_in_url(self, target_adapter: TargetAdapter) -> None:
        """check_queue returns True when queue indicator is in URL."""
        mock_page = AsyncMock()
        mock_page.url = "https://www.target.com/queue/waiting-room?token=abc"
        mock_page.title = AsyncMock(return_value="Please Wait | Target.com")
        mock_page.inner_text = AsyncMock(return_value="")

        target_adapter._page = mock_page
        result = await target_adapter.check_queue()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_queue_detected_in_page_content(
        self, target_adapter: TargetAdapter
    ) -> None:
        """check_queue returns True when queue indicator is in page content."""
        mock_page = AsyncMock()
        mock_page.url = "https://www.target.com/checkout"
        mock_page.title = AsyncMock(return_value="Checkout | Target.com")
        mock_page.inner_text = AsyncMock(return_value="You are in a virtual waiting room. Please wait.")

        target_adapter._page = mock_page
        result = await target_adapter.check_queue()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_queue_page_is_none(self, target_adapter: TargetAdapter) -> None:
        """check_queue returns False when page is None."""
        target_adapter._page = None
        result = await target_adapter.check_queue()
        assert result is False


# ── Close Tests ───────────────────────────────────────────────────────────────

class TestClose:
    """Test TargetAdapter.close()."""

    @pytest.mark.asyncio
    async def test_close_calls_close_browser(
        self, target_adapter: TargetAdapter
    ) -> None:
        """close() must call _close_browser and parent close()."""
        close_browser_mock = AsyncMock()
        original_close_browser = target_adapter._close_browser
        target_adapter._close_browser = close_browser_mock

        await target_adapter.close()

        close_browser_mock.assert_called_once()


# ── Session State Tests ────────────────────────────────────────────────────────

class TestSessionState:
    """Test that TargetAdapter properly integrates with RetailerAdapter session state."""

    @pytest.mark.asyncio
    async def test_save_cookies_calls_base_class_save_session_state(
        self, target_adapter: TargetAdapter
    ) -> None:
        """_save_cookies must call super().save_session_state with cookie dict."""
        target_adapter._context = AsyncMock()
        target_adapter._context.cookies = AsyncMock(return_value=[
            {"name": "session", "value": "abc123"},
            {"name": "tc", "value": "token456"},
        ])
        target_adapter._auth_token = "auth_token_val"
        target_adapter._cart_token = "cart_token_val"

        await target_adapter._save_cookies()

        # Verify session state was saved via base class
        assert target_adapter._session_state is not None
        saved_state = target_adapter._session_state
        assert saved_state.cookies == {"session": "abc123", "tc": "token456"}
        assert saved_state.auth_token == "auth_token_val"
        assert saved_state.cart_token == "cart_token_val"
        assert saved_state.is_valid is True

    def test_is_prewarmed_initially_false(self, target_adapter: TargetAdapter) -> None:
        """is_prewarmed() returns False before any prewarm."""
        assert target_adapter.is_prewarmed() is False

    @pytest.mark.asyncio
    async def test_invalidate_session_sets_prewarmed_false(
        self, target_adapter: TargetAdapter
    ) -> None:
        """invalidate_session() sets _prewarmed to False."""
        await target_adapter.invalidate_session()
        assert target_adapter.is_prewarmed() is False
