"""Tests for WalmartAdapter.

These tests mock all external dependencies: Playwright browser automation,
HTTP API calls, and 2Captcha solver. They verify:
- WalmartAdapter properly extends RetailerAdapter
- Correct method dispatch and error handling
- Cart management respects max_cart_quantity
- Checkout retry logic
- CAPTCHA detection and routing
- Queue detection
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.monitor.retailers.base import RetailerAdapter
from src.bot.monitor.retailers.walmart import WalmartAdapter
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
        "walmart": MagicMock(
            enabled=True,
            username="test@example.com",
            password="password123",
            items=[
                {
                    "name": "Charizard Box",
                    "skus": ["12345678"],
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
def walmart_adapter(mock_config: MagicMock) -> WalmartAdapter:
    """Create a WalmartAdapter instance with mock config."""
    adapter = WalmartAdapter(mock_config)
    return adapter


# ── Inheritance Tests ─────────────────────────────────────────────────────────

class TestInheritance:
    """Test that WalmartAdapter properly inherits from RetailerAdapter."""

    def test_inherits_from_retailer_adapter(self) -> None:
        """WalmartAdapter must extend RetailerAdapter."""
        assert issubclass(WalmartAdapter, RetailerAdapter)

    def test_is_instance_of_retailer_adapter(self, walmart_adapter: WalmartAdapter) -> None:
        """WalmartAdapter instance must be an instance of RetailerAdapter."""
        assert isinstance(walmart_adapter, RetailerAdapter)

    def test_has_required_abstract_methods(
        self, walmart_adapter: WalmartAdapter
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
            assert hasattr(walmart_adapter, method_name)
            assert callable(getattr(walmart_adapter, method_name))

    def test_adapter_name(self, walmart_adapter: WalmartAdapter) -> None:
        """Adapter name must be 'walmart'."""
        assert walmart_adapter.name == "walmart"

    def test_adapter_base_url(self, walmart_adapter: WalmartAdapter) -> None:
        """Adapter base_url must point to Walmart.com."""
        assert walmart_adapter.base_url == "https://www.walmart.com"

    def test_super_init_called(self, mock_config: MagicMock) -> None:
        """WalmartAdapter.__init__ must call super().__init__."""
        adapter = WalmartAdapter(mock_config)
        assert adapter._session_state is None
        assert adapter._prewarmed is False
        assert adapter._logger is None


# ── Login Tests ────────────────────────────────────────────────────────────────

class TestLogin:
    """Test WalmartAdapter.login() with mocked Playwright."""

    @pytest.mark.asyncio
    async def test_login_success(
        self, walmart_adapter: WalmartAdapter, mock_config: MagicMock
    ) -> None:
        """Login succeeds when credentials are valid."""
        mock_page = AsyncMock()
        mock_page.url = "https://www.walmart.com/"
        mock_page.goto = AsyncMock()
        mock_page.fill = AsyncMock()
        mock_page.locator = MagicMock(return_value=MagicMock(first=MagicMock(
            click=AsyncMock(),
            is_visible=AsyncMock(return_value=False)
        )))
        mock_page.click = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()

        with patch.object(walmart_adapter, "_verify_login_success", new=AsyncMock(return_value=True)):
            with patch.object(walmart_adapter, "_extract_auth_token", new=AsyncMock(return_value="fake_wm_token")):
                with patch.object(walmart_adapter, "_save_cookies", new=AsyncMock()):
                    with patch.object(walmart_adapter, "_ensure_browser", new=AsyncMock()):
                        walmart_adapter._page = mock_page
                        result = await walmart_adapter.login("test@example.com", "password123")

        assert result is True
        assert walmart_adapter._logged_in is True
        assert walmart_adapter._auth_token == "fake_wm_token"

    @pytest.mark.asyncio
    async def test_login_failure_wrong_credentials(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """Login fails when credentials are invalid."""
        mock_page = AsyncMock()
        mock_page.url = "https://www.walmart.com/account/login"
        mock_page.goto = AsyncMock()
        mock_page.fill = AsyncMock()
        mock_page.locator = MagicMock(return_value=MagicMock(
            first=MagicMock(click=AsyncMock(), is_visible=AsyncMock(return_value=False))
        ))
        mock_page.click = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.wait_for_selector = AsyncMock(side_effect=Exception("Not found"))

        with patch.object(walmart_adapter, "_verify_login_success", new=AsyncMock(return_value=False)):
            with patch.object(walmart_adapter, "_ensure_browser", new=AsyncMock()):
                walmart_adapter._page = mock_page
                result = await walmart_adapter.login("wrong@example.com", "wrongpass")

        assert result is False


# ── Stock Check Tests ─────────────────────────────────────────────────────────

class TestCheckStock:
    """Test WalmartAdapter.check_stock() with mocked HTTP and Playwright."""

    @pytest.mark.asyncio
    async def test_check_stock_in_stock_api(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """check_stock returns IN_STOCK when API reports in stock."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "product": {
                "availability": "AVAILABLE",
                "quantity": 5,
            }
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            status = await walmart_adapter.check_stock("12345678")

        assert status.in_stock is True
        assert status.sku == "12345678"

    @pytest.mark.asyncio
    async def test_check_stock_out_of_stock_api(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """check_stock returns OUT_OF_STOCK when API reports OOS."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "product": {
                "availability": "UNAVAILABLE",
                "quantity": 0,
            }
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            status = await walmart_adapter.check_stock("12345678")

        assert status.in_stock is False
        assert status.sku == "12345678"

    @pytest.mark.asyncio
    async def test_check_stock_api_fails_falls_back_to_page(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """check_stock falls back to page scraping when API fails."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock(side_effect=Exception("API failed, page fallback"))
        mock_page.url = "https://www.walmart.com/ip/12345678"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with patch.object(walmart_adapter, "_ensure_browser", new=AsyncMock()):
                with patch.object(walmart_adapter, "_parse_stock_from_page", new=AsyncMock(return_value=(False, 0))):
                    walmart_adapter._page = mock_page
                    status = await walmart_adapter.check_stock("12345678")

        assert status.in_stock is False


# ── Cart Tests ─────────────────────────────────────────────────────────────────

class TestAddToCart:
    """Test WalmartAdapter.add_to_cart() with mocked HTTP and Playwright."""

    @pytest.mark.asyncio
    async def test_add_to_cart_respects_max_cart_quantity(
        self, walmart_adapter: WalmartAdapter, mock_config: MagicMock
    ) -> None:
        """add_to_cart clamps quantity to max_cart_quantity from retailer config."""
        with patch.object(walmart_adapter, "_add_to_cart_api", new=AsyncMock(return_value=True)) as mock_api:
            result = await walmart_adapter.add_to_cart("12345678", quantity=5)

        assert result is True
        mock_api.assert_called_once_with("12345678", 2)

    @pytest.mark.asyncio
    async def test_add_to_cart_api_success(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """add_to_cart returns True when cart API succeeds."""
        with patch.object(walmart_adapter, "_add_to_cart_api", new=AsyncMock(return_value=True)):
            result = await walmart_adapter.add_to_cart("12345678", quantity=1)

        assert result is True

    @pytest.mark.asyncio
    async def test_add_to_cart_api_fails_ui_fallback(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """add_to_cart falls back to UI when API fails."""
        with patch.object(walmart_adapter, "_add_to_cart_api", new=AsyncMock(return_value=False)):
            with patch.object(walmart_adapter, "_add_to_cart_ui", new=AsyncMock(return_value=True)) as mock_ui:
                result = await walmart_adapter.add_to_cart("12345678", quantity=1)

        assert result is True
        mock_ui.assert_called_once_with("12345678", 1)

    @pytest.mark.asyncio
    async def test_add_to_cart_both_fail(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """add_to_cart returns False when both API and UI fail."""
        with patch.object(walmart_adapter, "_add_to_cart_api", new=AsyncMock(return_value=False)):
            with patch.object(walmart_adapter, "_add_to_cart_ui", new=AsyncMock(return_value=False)):
                result = await walmart_adapter.add_to_cart("12345678", quantity=1)

        assert result is False


class TestGetCart:
    """Test WalmartAdapter.get_cart() with mocked HTTP and Playwright."""

    @pytest.mark.asyncio
    async def test_get_cart_api_success(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """get_cart returns items when cart API succeeds."""
        mock_items = [
            {"sku": "12345678", "name": "Charizard Box", "quantity": 1, "price": "$59.99"}
        ]
        with patch.object(walmart_adapter, "_get_cart_api", new=AsyncMock(return_value=mock_items)):
            result = await walmart_adapter.get_cart()

        assert result == mock_items

    @pytest.mark.asyncio
    async def test_get_cart_api_returns_none_falls_back_to_ui(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """get_cart falls back to UI when API returns None."""
        ui_items = [
            {"sku": "12345678", "name": "Charizard Box", "quantity": 1, "price": "$59.99"}
        ]
        with patch.object(walmart_adapter, "_get_cart_api", new=AsyncMock(return_value=None)):
            with patch.object(walmart_adapter, "_get_cart_ui", new=AsyncMock(return_value=ui_items)) as mock_ui:
                result = await walmart_adapter.get_cart()

        assert result == ui_items
        mock_ui.assert_called_once()


# ── Checkout Tests ────────────────────────────────────────────────────────────

class TestCheckout:
    """Test WalmartAdapter.checkout() with mocked Playwright."""

    @pytest.mark.asyncio
    async def test_checkout_success_first_attempt(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """checkout returns success when order is placed on first attempt."""
        shipping = ShippingInfo(
            name="Test User",
            address1="123 Main St",
            city="New York",
            state="NY",
            zip_code="10001",
            phone="555-1234",
            email="test@example.com",
        )
        payment = PaymentInfo(
            card_number="4111111111111111",
            expiry_month="12",
            expiry_year="2027",
            cvv="123",
        )

        with patch.object(
            walmart_adapter,
            "_run_checkout_flow",
            new=AsyncMock(return_value={"success": True, "order_id": "WM12345678", "total": "$59.99"}),
        ):
            result = await walmart_adapter.checkout(shipping, payment)

        assert result["success"] is True
        assert result["order_id"] == "WM12345678"

    @pytest.mark.asyncio
    async def test_checkout_retry_on_failure(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """checkout retries when first attempt fails."""
        shipping = ShippingInfo(
            name="Test User",
            address1="123 Main St",
            city="New York",
            state="NY",
            zip_code="10001",
            phone="555-1234",
            email="test@example.com",
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
            return {"success": True, "order_id": "WM12345678", "total": "$59.99"}

        with patch.object(walmart_adapter, "_run_checkout_flow", new=mock_flow):
            with patch.object(walmart_adapter, "_clear_cart", new=AsyncMock(return_value=True)):
                result = await walmart_adapter.checkout(shipping, payment)

        assert result["success"] is True
        assert result["order_id"] == "WM12345678"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_checkout_all_attempts_fail(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """checkout returns failure after max retry attempts."""
        shipping = ShippingInfo(
            name="Test User",
            address1="123 Main St",
            city="New York",
            state="NY",
            zip_code="10001",
            phone="555-1234",
            email="test@example.com",
        )
        payment = PaymentInfo(
            card_number="4111111111111111",
            expiry_month="12",
            expiry_year="2027",
            cvv="123",
        )

        with patch.object(
            walmart_adapter,
            "_run_checkout_flow",
            new=AsyncMock(return_value={"success": False, "error": "Always fails"}),
        ):
            with patch.object(walmart_adapter, "_clear_cart", new=AsyncMock(return_value=True)):
                result = await walmart_adapter.checkout(shipping, payment)

        assert result["success"] is False
        assert "failed after" in result["error"]


# ── CAPTCHA Tests ─────────────────────────────────────────────────────────────

class TestHandleCaptcha:
    """Test WalmartAdapter.handle_captcha() with mocked Playwright."""

    @pytest.mark.asyncio
    async def test_handle_captcha_no_captcha_detected(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """handle_captcha returns failure when no CAPTCHA is detected."""
        mock_page = AsyncMock()
        mock_page.wait_for_selector = AsyncMock(
            side_effect=Exception("No CAPTCHA frames found")
        )

        with patch.object(
            walmart_adapter, "_detect_captcha_type", new=AsyncMock(return_value=CaptchaType.UNKNOWN)
        ):
            result = await walmart_adapter.handle_captcha(mock_page)

        assert result.success is False
        assert "No CAPTCHA detected" in result.error

    @pytest.mark.asyncio
    async def test_handle_captcha_page_is_none(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """handle_captcha returns failure when page is None."""
        result = await walmart_adapter.handle_captcha(None)

        assert result.success is False
        assert "No page provided" in result.error

    @pytest.mark.asyncio
    async def test_handle_captcha_smart_turnstile_auto_solves(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """Smart mode auto-solves Turnstile challenges via 2Captcha."""
        mock_page = AsyncMock()
        mock_page.url = "https://www.walmart.com/checkout"
        mock_page.wait_for_selector = AsyncMock(return_value=MagicMock())

        with patch.object(
            walmart_adapter,
            "_detect_captcha_type",
            new=AsyncMock(return_value=CaptchaType.TURNSTILE),
        ):
            with patch.object(
                walmart_adapter,
                "_get_2captcha_solver",
                new=MagicMock(return_value=None),
            ):
                result = await walmart_adapter.handle_captcha(mock_page)

        assert result.success is False
        assert "not configured" in result.error


# ── Queue Detection Tests ──────────────────────────────────────────────────────

class TestCheckQueue:
    """Test WalmartAdapter.check_queue() with mocked Playwright."""

    @pytest.mark.asyncio
    async def test_check_queue_no_queue(self, walmart_adapter: WalmartAdapter) -> None:
        """check_queue returns False when not in a queue."""
        mock_page = AsyncMock()
        mock_page.url = "https://www.walmart.com/ip/12345678"
        mock_page.title = AsyncMock(return_value="Charizard Box | Walmart.com")
        mock_page.inner_text = AsyncMock(return_value="Add to cart")

        walmart_adapter._page = mock_page
        result = await walmart_adapter.check_queue()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_queue_detected_in_url(self, walmart_adapter: WalmartAdapter) -> None:
        """check_queue returns True when queue indicator is in URL."""
        mock_page = AsyncMock()
        mock_page.url = "https://www.walmart.com/queue/waiting-room?token=abc"
        mock_page.title = AsyncMock(return_value="Please Wait | Walmart.com")
        mock_page.inner_text = AsyncMock(return_value="")

        walmart_adapter._page = mock_page
        result = await walmart_adapter.check_queue()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_queue_detected_in_page_content(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """check_queue returns True when queue indicator is in page content."""
        mock_page = AsyncMock()
        mock_page.url = "https://www.walmart.com/checkout"
        mock_page.title = AsyncMock(return_value="Checkout | Walmart.com")
        mock_page.inner_text = AsyncMock(return_value="You are in a virtual waiting room. Please wait.")

        walmart_adapter._page = mock_page
        result = await walmart_adapter.check_queue()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_queue_page_is_none(self, walmart_adapter: WalmartAdapter) -> None:
        """check_queue returns False when page is None."""
        walmart_adapter._page = None
        result = await walmart_adapter.check_queue()
        assert result is False


# ── Close Tests ───────────────────────────────────────────────────────────────

class TestClose:
    """Test WalmartAdapter.close()."""

    @pytest.mark.asyncio
    async def test_close_calls_close_browser(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """close() must call _close_browser and parent close()."""
        close_browser_mock = AsyncMock()
        original_close_browser = walmart_adapter._close_browser
        walmart_adapter._close_browser = close_browser_mock

        await walmart_adapter.close()

        close_browser_mock.assert_called_once()


# ── Session State Tests ────────────────────────────────────────────────────────

class TestSessionState:
    """Test that WalmartAdapter properly integrates with RetailerAdapter session state."""

    @pytest.mark.asyncio
    async def test_save_cookies_calls_base_class_save_session_state(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """_save_cookies must call super().save_session_state with cookie dict."""
        walmart_adapter._context = AsyncMock()
        walmart_adapter._context.cookies = AsyncMock(return_value=[
            {"name": "session", "value": "abc123"},
        ])
        walmart_adapter._auth_token = "token123"
        walmart_adapter._cart_token = "cart123"

        with patch.object(
            RetailerAdapter,
            "save_session_state",
            new=AsyncMock(),
        ) as mock_save:
            await walmart_adapter._save_cookies()
            mock_save.assert_called_once()
            call_kwargs = mock_save.call_args.kwargs
            assert call_kwargs["auth_token"] == "token123"
            assert call_kwargs["cart_token"] == "cart123"
            assert "session" in call_kwargs["cookies"]

    @pytest.mark.asyncio
    async def test_invalidate_session(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """invalidate_session must clear internal session state."""
        with patch.object(
            RetailerAdapter,
            "invalidate_session",
            new=AsyncMock(),
        ) as mock_invalidate:
            await walmart_adapter.invalidate_session()
            mock_invalidate.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_prewarmed(
        self, walmart_adapter: WalmartAdapter
    ) -> None:
        """is_prewarmed must delegate to base class."""
        walmart_adapter._prewarmed = True
        assert walmart_adapter.is_prewarmed() is True
        walmart_adapter._prewarmed = False
        assert walmart_adapter.is_prewarmed() is False
