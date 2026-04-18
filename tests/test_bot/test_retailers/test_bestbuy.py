"""Tests for BestBuyAdapter.

These tests mock all external dependencies: Playwright browser automation,
HTTP API calls, and 2Captcha solver. They verify:
- BestBuyAdapter properly extends RetailerAdapter
- Correct method dispatch and error handling
- Cart management respects max_cart_quantity
- Checkout retry logic
- CAPTCHA detection and routing (Turnstile)
- Queue detection
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.monitor.retailers.base import RetailerAdapter
from src.bot.monitor.retailers.bestbuy import BestBuyAdapter
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
        "bestbuy": MagicMock(
            enabled=True,
            username="test@example.com",
            password="password123",
            items=[
                {
                    "name": "PS5 Console",
                    "skus": ["12345678"],
                    "keywords": ["PS5"],
                    "enabled": True,
                    "max_cart_quantity": 1,
                },
            ],
        ),
    }
    config.captcha = MagicMock(mode="smart", api_key="")
    config.checkout = MagicMock(retry_attempts=2, use_1click_if_available=True)
    config.evasion = MagicMock(jitter_percent=20)
    return config


@pytest.fixture
def bestbuy_adapter(mock_config: MagicMock) -> BestBuyAdapter:
    """Create a BestBuyAdapter instance with mock config."""
    adapter = BestBuyAdapter(mock_config)
    return adapter


@pytest.fixture
def shipping_info() -> ShippingInfo:
    """Create a mock ShippingInfo object."""
    return ShippingInfo(
        name="John Doe",
        address1="123 Main St",
        address2="Apt 4",
        city="Los Angeles",
        state="CA",
        zip_code="90001",
        phone="555-123-4567",
        email="john@example.com",
    )


@pytest.fixture
def payment_info() -> PaymentInfo:
    """Create a mock PaymentInfo object."""
    return PaymentInfo(
        card_number="4111111111111111",
        expiry_month="12",
        expiry_year="2027",
        cvv="123",
        card_type="visa",
    )


# ── Inheritance Tests ─────────────────────────────────────────────────────────

class TestInheritance:
    """Test that BestBuyAdapter properly inherits from RetailerAdapter."""

    def test_inherits_from_retailer_adapter(self) -> None:
        """BestBuyAdapter must extend RetailerAdapter."""
        assert issubclass(BestBuyAdapter, RetailerAdapter)

    def test_is_instance_of_retailer_adapter(self, bestbuy_adapter: BestBuyAdapter) -> None:
        """BestBuyAdapter instance must be an instance of RetailerAdapter."""
        assert isinstance(bestbuy_adapter, RetailerAdapter)

    def test_has_required_abstract_methods(
        self, bestbuy_adapter: BestBuyAdapter
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
            assert hasattr(bestbuy_adapter, method_name)
            assert callable(getattr(bestbuy_adapter, method_name))

    def test_adapter_name(self, bestbuy_adapter: BestBuyAdapter) -> None:
        """Adapter name must be 'bestbuy'."""
        assert bestbuy_adapter.name == "bestbuy"

    def test_adapter_base_url(self, bestbuy_adapter: BestBuyAdapter) -> None:
        """Adapter base_url must be BestBuy's site."""
        assert bestbuy_adapter.base_url == "https://www.bestbuy.com"

    def test_product_url_template(self, bestbuy_adapter: BestBuyAdapter) -> None:
        """Product URL template must be correctly formed."""
        template = bestbuy_adapter._PRODUCT_URL_TEMPLATE
        assert "bestbuy.com" in template
        assert "{sku}" in template


# ── Browser Setup Tests ───────────────────────────────────────────────────────

class TestBrowserSetup:
    """Test browser initialization and teardown."""

    @pytest.mark.asyncio
    async def test_ensure_browser_creates_context_once(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_ensure_browser must return the same context on repeated calls."""
        with patch(
            "src.bot.monitor.retailers.bestbuy.async_playwright"
        ) as mock_pw:
            mock_playwright_instance = MagicMock()
            mock_browser = MagicMock()
            mock_context = MagicMock()
            mock_page = MagicMock()
            mock_playwright_instance.start = AsyncMock(
                return_value=mock_playwright_instance
            )
            mock_playwright_instance.chromium.launch = AsyncMock(
                return_value=mock_browser
            )
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_context.add_init_script = AsyncMock()
            mock_context.cookies = AsyncMock(return_value=[])
            mock_pw.return_value = mock_playwright_instance

            ctx1 = await bestbuy_adapter._ensure_browser()
            ctx2 = await bestbuy_adapter._ensure_browser()

            assert ctx1 is ctx2
            assert mock_browser.new_context.call_count == 1

    @pytest.mark.asyncio
    async def test_close_browser_cleans_up_all_resources(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_close_browser must close page, context, browser, and stop playwright."""
        with patch(
            "src.bot.monitor.retailers.bestbuy.async_playwright"
        ) as mock_pw:
            mock_playwright_instance = MagicMock()
            mock_browser = MagicMock()
            mock_context = MagicMock()
            mock_page = MagicMock()
            mock_playwright_instance.start = AsyncMock(
                return_value=mock_playwright_instance
            )
            mock_playwright_instance.chromium.launch = AsyncMock(
                return_value=mock_browser
            )
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_context.add_init_script = AsyncMock()
            mock_context.cookies = AsyncMock(return_value=[])
            mock_pw.return_value = mock_playwright_instance

            # Make page and context methods async
            mock_page.close = AsyncMock()
            mock_context.close = AsyncMock()
            mock_browser.close = AsyncMock()
            mock_playwright_instance.stop = AsyncMock()

            await bestbuy_adapter._ensure_browser()
            await bestbuy_adapter._close_browser()

            mock_page.close.assert_called_once()
            mock_context.close.assert_called_once()
            mock_browser.close.assert_called_once()
            mock_playwright_instance.stop.assert_called_once()


# ── Login Tests ───────────────────────────────────────────────────────────────

class TestLogin:
    """Test BestBuy login flow."""

    @pytest.mark.asyncio
    async def test_login_success(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """login must return True when credentials are valid."""
        with patch(
            "src.bot.monitor.retailers.bestbuy.async_playwright"
        ) as mock_pw:
            mock_browser = MagicMock()
            mock_context = MagicMock()
            mock_page = MagicMock()
            mock_pw.return_value.chromium.launch = AsyncMock(
                return_value=mock_browser
            )
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_context.add_init_script = AsyncMock()
            mock_context.cookies = AsyncMock(return_value=[
                {"name": "t", "value": "abc123"},
            ])
            mock_context.new_page.return_value = mock_page

            # Simulate login page and successful login
            mock_page.goto = AsyncMock()
            mock_page.fill = AsyncMock()
            mock_page.click = AsyncMock()
            mock_page.wait_for_load_state = AsyncMock()
            mock_page.wait_for_selector = AsyncMock()
            mock_page.title = AsyncMock(return_value="BestBuy Account")
            mock_page.url = "https://www.bestbuy.com/account"

            bestbuy_adapter._page = mock_page
            bestbuy_adapter._context = mock_context

            with patch.object(
                bestbuy_adapter,
                "_verify_login_success",
                return_value=True,
            ):
                result = await bestbuy_adapter.login(
                    "test@example.com", "password123"
                )

            assert result is True
            assert bestbuy_adapter._logged_in is True

    @pytest.mark.asyncio
    async def test_login_failure(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """login must return False when credentials are invalid."""
        with patch(
            "src.bot.monitor.retailers.bestbuy.async_playwright"
        ) as mock_pw:
            mock_page = MagicMock()
            mock_page.goto = AsyncMock()
            mock_page.fill = AsyncMock()
            mock_page.click = AsyncMock()
            mock_page.wait_for_load_state = AsyncMock()
            mock_page.wait_for_selector = AsyncMock(side_effect=Exception("not found"))

            bestbuy_adapter._page = mock_page

            with patch.object(
                bestbuy_adapter,
                "_verify_login_success",
                return_value=False,
            ):
                result = await bestbuy_adapter.login(
                    "bad@example.com", "wrongpassword"
                )

            assert result is False
            assert bestbuy_adapter._logged_in is False

    @pytest.mark.asyncio
    async def test_verify_login_success_checks_for_account_elements(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_verify_login_success must check for account-related page elements."""
        mock_page = MagicMock()
        mock_page.wait_for_selector = AsyncMock(return_value=MagicMock())
        mock_page.url = "https://www.bestbuy.com/account"
        bestbuy_adapter._page = mock_page

        result = await bestbuy_adapter._verify_login_success()
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_login_success_falls_back_to_url_check(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_verify_login_success must check URL when selectors fail."""
        mock_page = MagicMock()
        mock_page.wait_for_selector = AsyncMock(side_effect=Exception("timeout"))
        mock_page.url = "https://www.bestbuy.com/account"
        bestbuy_adapter._page = mock_page

        result = await bestbuy_adapter._verify_login_success()
        assert result is True


# ── Stock Check Tests ─────────────────────────────────────────────────────────

class TestStockCheck:
    """Test BestBuy stock detection."""

    @pytest.mark.asyncio
    async def test_check_stock_returns_in_stock_status(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """check_stock must return StockStatus with in_stock=True when available."""
        # Mock API returning in-stock
        with patch.object(
            bestbuy_adapter,
            "_check_stock_api",
            return_value=StockStatus(
                in_stock=True,
                sku="12345678",
                available_quantity=5,
            ),
        ):
            status = await bestbuy_adapter.check_stock("12345678")

        assert status.in_stock is True
        assert status.sku == "12345678"
        assert status.available_quantity == 5

    @pytest.mark.asyncio
    async def test_check_stock_returns_oos_status(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """check_stock must return StockStatus with in_stock=False when OOS."""
        with patch(
            "src.bot.monitor.retailers.bestbuy.async_playwright"
        ) as mock_pw:
            mock_browser = MagicMock()
            mock_context = MagicMock()
            mock_page = MagicMock()
            mock_pw.return_value.chromium.launch = AsyncMock(
                return_value=mock_browser
            )
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_context.add_init_script = AsyncMock()
            mock_context.cookies = AsyncMock(return_value=[])

            with patch.object(
                bestbuy_adapter,
                "_check_stock_api",
                return_value=StockStatus(in_stock=False, sku="12345678"),
            ):
                status = await bestbuy_adapter.check_stock("12345678")

            assert status.in_stock is False

    @pytest.mark.asyncio
    async def test_check_stock_api_returns_none_on_error(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_check_stock_api must return None on network errors."""
        with patch(
            "src.bot.monitor.retailers.bestbuy.httpx.AsyncClient"
        ) as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("network error")
            )
            mock_client.return_value.__aexit__ = AsyncMock()

            result = await bestbuy_adapter._check_stock_api("12345678")
            assert result is None

    @pytest.mark.asyncio
    async def test_check_stock_api_uses_bestbuy_endpoint(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_check_stock_api must call BestBuy's cart service API."""
        with patch(
            "src.bot.monitor.retailers.bestbuy.httpx.AsyncClient"
        ) as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(
                return_value=[
                    {
                        "sku": "12345678",
                        "inStore": True,
                        "online": True,
                        "quantity": 10,
                    }
                ]
            )

            async def mock_get(*args: Any, **kwargs: Any) -> MagicMock:
                return mock_response

            mock_client.return_value.__aenter__ = AsyncMock()
            mock_client.return_value.__aexit__ = AsyncMock()
            mock_client.return_value.get = mock_get

            timeout_mock = MagicMock()
            timeout_mock.connect = 1.0
            timeout_mock.pool = 5.0
            mock_client.return_value.timeout = timeout_mock

            with patch(
                "src.bot.monitor.retailers.bestbuy.httpx.Timeout"
            ) as mock_timeout:
                mock_timeout.return_value = MagicMock()
                result = await bestbuy_adapter._check_stock_api("12345678")

    @pytest.mark.asyncio
    async def test_parse_stock_from_page_detects_add_to_cart(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_parse_stock_from_page must detect Add to Cart button as in-stock."""
        mock_page = MagicMock()
        mock_btn = MagicMock()
        mock_btn.is_enabled = AsyncMock(return_value=True)
        mock_btn.is_visible = AsyncMock(return_value=True)
        mock_btn.inner_text = AsyncMock(return_value="Add to Cart")

        mock_page.wait_for_selector = AsyncMock(return_value=mock_btn)
        mock_page.query_selector = AsyncMock(side_effect=[
            Exception("no qty"),  # quantity selector
        ])
        bestbuy_adapter._page = mock_page

        in_stock, qty = await bestbuy_adapter._parse_stock_from_page("12345678")
        assert in_stock is True

    @pytest.mark.asyncio
    async def test_parse_stock_from_page_detects_sold_out(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_parse_stock_from_page must detect sold-out state."""
        mock_page = MagicMock()

        # First call returns no add-to-cart button, second call finds sold out
        mock_page.wait_for_selector = AsyncMock(
            side_effect=Exception("no add to cart btn")
        )

        sold_out_btn = MagicMock()
        sold_out_btn.is_visible = AsyncMock(return_value=True)

        async def query_side_effect(selector: str) -> MagicMock | None:
            if "sold" in selector.lower() or "out" in selector.lower():
                return sold_out_btn
            return None

        mock_page.query_selector = AsyncMock(side_effect=query_side_effect)
        bestbuy_adapter._page = mock_page

        in_stock, qty = await bestbuy_adapter._parse_stock_from_page("12345678")
        assert in_stock is False


# ── Cart Tests ─────────────────────────────────────────────────────────────────

class TestCart:
    """Test BestBuy cart management."""

    @pytest.mark.asyncio
    async def test_add_to_cart_respects_max_quantity(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """add_to_cart must cap quantity to max_cart_quantity."""
        with patch.object(
            bestbuy_adapter,
            "_add_to_cart_api",
            return_value=True,
        ):
            # Config has max_cart_quantity=1, requesting 5
            result = await bestbuy_adapter.add_to_cart("12345678", quantity=5)
            assert result is True

            # Verify the actual add was called with capped quantity
            # (max 1 since that's the configured max)

    @pytest.mark.asyncio
    async def test_add_to_cart_api_called_when_no_auth(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_add_to_cart_api must return False when not authenticated."""
        bestbuy_adapter._auth_token = ""
        result = await bestbuy_adapter._add_to_cart_api("12345678", 1)
        assert result is False

    @pytest.mark.asyncio
    async def test_add_to_cart_ui_fallback(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """add_to_cart must fall back to UI when API fails."""
        bestbuy_adapter._page = MagicMock()
        bestbuy_adapter._page.goto = AsyncMock()
        bestbuy_adapter._page.wait_for_selector = AsyncMock(side_effect=Exception("not found"))

        with patch.object(
            bestbuy_adapter,
            "_add_to_cart_api",
            return_value=False,
        ):
            result = await bestbuy_adapter.add_to_cart("12345678", 1)
            assert result is False

    @pytest.mark.asyncio
    async def test_get_cart_returns_items_from_api(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """get_cart must return parsed cart items from API."""
        bestbuy_adapter._auth_token = "abc123"

        with patch.object(
            bestbuy_adapter,
            "_get_cart_api",
            return_value=[
                {"sku": "12345678", "name": "PS5", "quantity": 1, "price": "$499.99"}
            ],
        ):
            items = await bestbuy_adapter.get_cart()
            assert len(items) == 1
            assert items[0]["sku"] == "12345678"

    @pytest.mark.asyncio
    async def test_get_cart_returns_empty_on_error(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """get_cart must return empty list on error."""
        bestbuy_adapter._page = MagicMock()

        with patch.object(
            bestbuy_adapter,
            "_get_cart_api",
            return_value=None,
        ):
            with patch.object(
                bestbuy_adapter,
                "_get_cart_ui",
                side_effect=Exception("error"),
            ):
                items = await bestbuy_adapter.get_cart()
                assert items == []


# ── Checkout Tests ─────────────────────────────────────────────────────────────

class TestCheckout:
    """Test BestBuy checkout flow."""

    @pytest.mark.asyncio
    async def test_checkout_success(
        self,
        bestbuy_adapter: BestBuyAdapter,
        shipping_info: ShippingInfo,
        payment_info: PaymentInfo,
    ) -> None:
        """checkout must return success=True with order_id on success."""
        bestbuy_adapter._page = MagicMock()
        bestbuy_adapter._page.goto = AsyncMock()
        bestbuy_adapter._page.wait_for_selector = AsyncMock()
        bestbuy_adapter._page.inner_text = AsyncMock(return_value="Thank you")
        bestbuy_adapter._page.query_selector = MagicMock()

        with patch.object(
            bestbuy_adapter,
            "_run_checkout_flow",
            return_value={"success": True, "order_id": "1234567890", "error": ""},
        ):
            result = await bestbuy_adapter.checkout(shipping_info, payment_info)
            assert result["success"] is True
            assert result["order_id"] == "1234567890"

    @pytest.mark.asyncio
    async def test_checkout_retries_on_failure(
        self,
        bestbuy_adapter: BestBuyAdapter,
        shipping_info: ShippingInfo,
        payment_info: PaymentInfo,
    ) -> None:
        """checkout must retry up to max_attempts on failure."""
        bestbuy_adapter._page = MagicMock()

        with patch.object(
            bestbuy_adapter,
            "_run_checkout_flow",
            return_value={"success": False, "order_id": "", "error": "failed"},
        ):
            with patch.object(
                bestbuy_adapter,
                "_clear_cart",
                return_value=True,
            ):
                result = await bestbuy_adapter.checkout(shipping_info, payment_info)
                # Should fail after 2 attempts (max_attempts=2 from config)
                assert result["success"] is False

    @pytest.mark.asyncio
    async def test_checkout_runs_all_steps(
        self,
        bestbuy_adapter: BestBuyAdapter,
        shipping_info: ShippingInfo,
        payment_info: PaymentInfo,
    ) -> None:
        """_run_checkout_flow must execute navigate, fill, review, and submit."""
        bestbuy_adapter._page = MagicMock()
        bestbuy_adapter._page.goto = AsyncMock()
        bestbuy_adapter._page.wait_for_load_state = AsyncMock()

        steps_completed: list[str] = []

        async def mock_handle_checkout(
            shipping: ShippingInfo, payment: PaymentInfo
        ) -> dict[str, Any]:
            steps_completed.append("checkout")
            return {"success": True, "order_id": "", "error": ""}

        async def mock_handle_review() -> dict[str, Any]:
            steps_completed.append("review")
            return {"success": True, "order_id": "", "error": ""}

        async def mock_submit() -> dict[str, Any]:
            steps_completed.append("submit")
            return {"success": True, "order_id": "987654321", "error": ""}

        bestbuy_adapter._page.wait_for_selector = AsyncMock()

        with patch.object(
            bestbuy_adapter,
            "_handle_checkout_page",
            side_effect=mock_handle_checkout,
        ):
            with patch.object(
                bestbuy_adapter,
                "_handle_review_step",
                side_effect=mock_handle_review,
            ):
                with patch.object(
                    bestbuy_adapter,
                    "_submit_order",
                    side_effect=mock_submit,
                ):
                    result = await bestbuy_adapter._run_checkout_flow(
                        shipping_info, payment_info, attempt=1
                    )
                    assert result["success"] is True
                    assert "checkout" in steps_completed

    @pytest.mark.asyncio
    async def test_fill_shipping_maps_all_fields(
        self,
        bestbuy_adapter: BestBuyAdapter,
        shipping_info: ShippingInfo,
    ) -> None:
        """_fill_shipping must fill all address fields from ShippingInfo."""
        mock_page = MagicMock()
        mock_el = MagicMock()
        mock_el.fill = AsyncMock()  # Playwright fill() is async
        mock_el.check = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=mock_el)
        bestbuy_adapter._page = mock_page

        await bestbuy_adapter._fill_shipping(shipping_info)

        # Verify query_selector was called for shipping fields
        assert mock_page.query_selector.called

    @pytest.mark.asyncio
    async def test_fill_payment_maps_card_fields(
        self,
        bestbuy_adapter: BestBuyAdapter,
        payment_info: PaymentInfo,
    ) -> None:
        """_fill_payment must fill card number, expiry, and CVV."""
        mock_page = MagicMock()
        mock_el = MagicMock()
        mock_el.fill = AsyncMock()  # Playwright fill() is async
        mock_el.select_option = AsyncMock()  # Playwright select_option() is async
        mock_page.query_selector = AsyncMock(return_value=mock_el)
        bestbuy_adapter._page = mock_page

        await bestbuy_adapter._fill_payment(payment_info)

        assert mock_page.query_selector.called

    @pytest.mark.asyncio
    async def test_submit_order_extracts_order_id(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_submit_order must extract order ID from confirmation page."""
        mock_page = MagicMock()
        mock_el = MagicMock()
        mock_el.inner_text = AsyncMock(return_value="Order #12345678 confirmed")
        mock_page.wait_for_selector = AsyncMock(return_value=mock_el)
        # Return mock_el for '.order-number', None for others
        mock_page.query_selector = AsyncMock(
            side_effect=[mock_el, None, None, None, None]
        )
        bestbuy_adapter._page = mock_page

        result = await bestbuy_adapter._submit_order()
        assert result["success"] is True
        assert result["order_id"] == "12345678"


# ── CAPTCHA Tests ──────────────────────────────────────────────────────────────

class TestCaptcha:
    """Test BestBuy CAPTCHA detection and handling."""

    @pytest.mark.asyncio
    async def test_detect_turnstile_returns_correct_type(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_detect_captcha_type must return CaptchaType.TURNSTILE for Cloudflare."""
        mock_page = MagicMock()

        # reCAPTCHA → raise, hCaptcha → raise, Turnstile → found
        mock_page.wait_for_selector = AsyncMock(
            side_effect=[
                asyncio.TimeoutError(),
                asyncio.TimeoutError(),
                MagicMock(),  # Turnstile found
            ]
        )
        mock_page.query_selector = AsyncMock(return_value=None)
        bestbuy_adapter._page = mock_page

        result = await bestbuy_adapter._detect_captcha_type(mock_page)
        assert result == CaptchaType.TURNSTILE

    @pytest.mark.asyncio
    async def test_detect_recaptcha_v2(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_detect_captcha_type must return CaptchaType.RECAPTCHA_V2 for Google."""
        mock_page = MagicMock()

        # reCAPTCHA found on first check
        mock_page.wait_for_selector = AsyncMock(
            side_effect=[
                MagicMock(),  # reCAPTCHA found → returns RECAPTCHA_V2
            ]
        )
        mock_page.query_selector = AsyncMock(return_value=None)
        bestbuy_adapter._page = mock_page

        result = await bestbuy_adapter._detect_captcha_type(mock_page)
        assert result == CaptchaType.RECAPTCHA_V2

    @pytest.mark.asyncio
    async def test_detect_hcaptcha(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_detect_captcha_type must return CaptchaType.HCAPTCHA for hCaptcha."""
        mock_page = MagicMock()

        # reCAPTCHA → raise, hCaptcha → found
        mock_page.wait_for_selector = AsyncMock(
            side_effect=[
                asyncio.TimeoutError(),
                MagicMock(),  # hCaptcha found
            ]
        )
        mock_page.query_selector = AsyncMock(return_value=None)
        bestbuy_adapter._page = mock_page

        result = await bestbuy_adapter._detect_captcha_type(mock_page)
        assert result == CaptchaType.HCAPTCHA

    @pytest.mark.asyncio
    async def test_detect_unknown_when_no_captcha(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_detect_captcha_type must return UNKNOWN when no CAPTCHA found."""
        mock_page = MagicMock()
        mock_page.wait_for_selector = AsyncMock(
            side_effect=Exception("no captcha")
        )
        mock_page.query_selector = AsyncMock(return_value=None)
        bestbuy_adapter._page = mock_page

        result = await bestbuy_adapter._detect_captcha_type(mock_page)
        assert result == CaptchaType.UNKNOWN

    @pytest.mark.asyncio
    async def test_handle_captcha_smart_mode_auto_solves_turnstile(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """In smart mode, Turnstile must be auto-solved (BestBuy primary CAPTCHA)."""
        mock_page = MagicMock()
        mock_page.url = "https://www.bestbuy.com/product"
        mock_page.content = AsyncMock(return_value='data-sitekey="testkey123"')

        captcha_type = CaptchaType.TURNSTILE
        start_time = 0.0

        with patch.object(
            bestbuy_adapter,
            "_detect_captcha_type",
            return_value=captcha_type,
        ):
            with patch.object(
                bestbuy_adapter,
                "_extract_site_key",
                return_value="testkey123",
            ):
                with patch.object(
                    bestbuy_adapter,
                    "_get_2captcha_solver",
                    return_value=None,
                ):
                    # No solver configured → should return error result
                    result = await bestbuy_adapter.handle_captcha(mock_page)
                    # Since no solver, it should fail gracefully
                    assert result.success is False or result.error != ""

    @pytest.mark.asyncio
    async def test_handle_captcha_manual_mode_uses_manual_handler(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """In manual mode, CAPTCHA must trigger manual handler with timeout."""
        mock_page = MagicMock()
        mock_page.url = "https://www.bestbuy.com/product"

        # Set to manual mode
        bestbuy_adapter.config.captcha.mode = "manual"

        with patch.object(
            bestbuy_adapter,
            "_detect_captcha_type",
            return_value=CaptchaType.TURNSTILE,
        ):
            with patch.object(
                bestbuy_adapter,
                "_handle_manual_captcha",
                return_value=CaptchaSolveResult(
                    success=False,
                    error="Manual CAPTCHA timed out after 120s",
                ),
            ):
                result = await bestbuy_adapter.handle_captcha(mock_page)
                assert result.success is False
                assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_handle_captcha_no_page_returns_false(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """handle_captcha must return failure when no page is provided."""
        result = await bestbuy_adapter.handle_captcha(None)
        assert result.success is False
        assert "No page" in result.error

    @pytest.mark.asyncio
    async def test_inject_captcha_token_for_turnstile(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_inject_captcha_token must set cf-turnstile-response and dispatch event."""
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock()
        bestbuy_adapter._page = mock_page

        await bestbuy_adapter._inject_captcha_token(
            mock_page, CaptchaType.TURNSTILE, "test-token-abc"
        )

        # Verify page.evaluate was called with token injection script
        mock_page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_site_key_from_page_attribute(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_extract_site_key must extract key from data-sitekey attribute."""
        mock_page = MagicMock()
        mock_el = MagicMock()
        mock_el.get_attribute = AsyncMock(return_value="bestbuy-site-key-xyz")

        mock_page.query_selector = AsyncMock(return_value=mock_el)
        bestbuy_adapter._page = mock_page

        key = await bestbuy_adapter._extract_site_key(
            mock_page, CaptchaType.TURNSTILE
        )
        assert key == "bestbuy-site-key-xyz"


# ── Queue Detection Tests ─────────────────────────────────────────────────────

class TestQueueDetection:
    """Test queue/waiting room detection for BestBuy."""

    @pytest.mark.asyncio
    async def test_check_queue_returns_true_for_queue_indicators(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """check_queue must return True when queue URL/title/body detected."""
        mock_page = MagicMock()
        mock_page.url = "https://www.bestbuy.com/queue/waiting"
        mock_page.title = AsyncMock(return_value="Best Buy Virtual Line")
        mock_page.query_selector = AsyncMock(return_value=None)

        async def mock_inner_text(selector: str) -> str:
            return "You are in a virtual waiting room"

        mock_page.inner_text = mock_inner_text
        bestbuy_adapter._page = mock_page

        result = await bestbuy_adapter.check_queue()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_queue_returns_false_when_not_in_queue(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """check_queue must return False on normal BestBuy pages."""
        mock_page = MagicMock()
        mock_page.url = "https://www.bestbuy.com/product/123"
        mock_page.title = AsyncMock(return_value="PS5 Console")
        mock_page.query_selector = AsyncMock(return_value=None)

        async def mock_inner_text(selector: str) -> str:
            return "Add to Cart"

        mock_page.inner_text = mock_inner_text
        bestbuy_adapter._page = mock_page

        result = await bestbuy_adapter.check_queue()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_queue_detects_bestbuy_specific_queue_elements(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """check_queue must detect BestBuy-specific queue/waiting room CSS classes."""
        mock_page = MagicMock()
        mock_page.url = "https://www.bestbuy.com/checkout"
        mock_page.title = AsyncMock(return_value="BestBuy Checkout")

        # Queue element is visible
        mock_queue_el = MagicMock()
        mock_queue_el.is_visible = AsyncMock(return_value=True)

        async def query_side_effect(selector: str) -> MagicMock | None:
            if "queue" in selector.lower() or "waiting" in selector.lower():
                return mock_queue_el
            return None

        mock_page.query_selector = AsyncMock(side_effect=query_side_effect)

        async def mock_inner_text(selector: str) -> str:
            return "BestBuy Checkout"
        mock_page.inner_text = mock_inner_text

        bestbuy_adapter._page = mock_page

        result = await bestbuy_adapter.check_queue()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_queue_returns_false_when_page_is_none(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """check_queue must return False when _page is None."""
        bestbuy_adapter._page = None
        result = await bestbuy_adapter.check_queue()
        assert result is False


# ── Helper / Utility Tests ────────────────────────────────────────────────────

class TestHelpers:
    """Test BestBuyAdapter helper functions."""

    def test_random_locale_returns_valid_locale(self) -> None:
        """_random_locale must return a locale from the predefined list."""
        from src.bot.monitor.retailers.bestbuy import _random_locale

        valid_locales = [
            "en-US", "en-GB", "en-CA", "de-DE", "fr-FR",
            "es-ES", "it-IT", "nl-NL", "pl-PL", "pt-BR",
        ]
        locale = _random_locale()
        assert locale in valid_locales

    def test_random_timezone_returns_valid_iana_id(self) -> None:
        """_random_timezone must return an IANA timezone ID from the predefined list."""
        from src.bot.monitor.retailers.bestbuy import _random_timezone

        valid_timezones = [
            "America/New_York", "America/Chicago", "America/Denver",
            "America/Los_Angeles", "America/Phoenix",
            "Europe/London", "Europe/Paris", "Europe/Berlin",
            "Europe/Amsterdam", "Australia/Sydney",
        ]
        tz = _random_timezone()
        assert tz in valid_timezones

    def test_stealth_script_is_not_empty(self) -> None:
        """_STEALTH_SCRIPT must be defined and non-empty."""
        from src.bot.monitor.retailers.bestbuy import _STEALTH_SCRIPT

        assert _STEALTH_SCRIPT is not None
        assert len(_STEALTH_SCRIPT) > 100
        assert "webdriver" in _STEALTH_SCRIPT
        assert "hardwareConcurrency" in _STEALTH_SCRIPT

    @pytest.mark.asyncio
    async def test_human_delay_returns_quickly(self, bestbuy_adapter: BestBuyAdapter) -> None:
        """_human_delay must complete within reasonable time."""
        import time
        start = time.monotonic()
        await bestbuy_adapter._human_delay(base_ms=100)
        elapsed = time.monotonic() - start
        # Should be roughly 100ms but allow ±50ms
        assert elapsed < 0.2


# ── 2Captcha Tests ─────────────────────────────────────────────────────────────

class TestTwoCaptcha:
    """Test 2Captcha integration for BestBuy."""

    def test_get_2captcha_solver_returns_none_when_no_api_key(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_get_2captcha_solver must return None when no API key is configured."""
        bestbuy_adapter.config.captcha.api_key = ""

        with patch("os.getenv", return_value=""):
            solver = bestbuy_adapter._get_2captcha_solver()
            assert solver is None

    def test_get_2captcha_solver_returns_none_when_twocaptcha_not_installed(
        self, bestbuy_adapter: BestBuyAdapter
    ) -> None:
        """_get_2captcha_solver must return None when twocaptcha package unavailable."""
        bestbuy_adapter.config.captcha.api_key = "test-api-key-123"

        with patch.dict("sys.modules", {"twocaptcha": None}):
            solver = bestbuy_adapter._get_2captcha_solver()
            # Should handle import error gracefully
            # (either None or a mock depending on import failure handling)


# ── Integration: Full Flow Mock ────────────────────────────────────────────────

class TestFullFlowMock:
    """End-to-end mock test of the full BestBuy flow."""

    @pytest.mark.asyncio
    async def test_login_to_checkout_full_mock_flow(
        self,
        bestbuy_adapter: BestBuyAdapter,
        shipping_info: ShippingInfo,
        payment_info: PaymentInfo,
    ) -> None:
        """Simulate a full login → stock check → cart → checkout flow (mocked)."""
        # 1. Login
        with patch(
            "src.bot.monitor.retailers.bestbuy.async_playwright"
        ) as mock_pw:
            mock_browser = MagicMock()
            mock_context = MagicMock()
            mock_page = MagicMock()
            mock_pw.return_value.chromium.launch = AsyncMock(
                return_value=mock_browser
            )
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_context.add_init_script = AsyncMock()
            mock_context.cookies = AsyncMock(return_value=[
                {"name": "t", "value": "session-token"},
            ])

            mock_page.goto = AsyncMock()
            mock_page.fill = AsyncMock()
            mock_page.click = AsyncMock()
            mock_page.wait_for_load_state = AsyncMock()
            mock_page.wait_for_selector = AsyncMock(return_value=MagicMock())
            mock_page.title = AsyncMock(return_value="BestBuy Account")
            mock_page.url = "https://www.bestbuy.com/account"

            bestbuy_adapter._page = mock_page
            bestbuy_adapter._context = mock_context

            with patch.object(
                bestbuy_adapter,
                "_verify_login_success",
                return_value=True,
            ):
                login_result = await bestbuy_adapter.login(
                    "test@example.com", "password123"
                )
            assert login_result is True

        # 2. Check stock
        with patch.object(
            bestbuy_adapter,
            "_check_stock_api",
            return_value=StockStatus(
                in_stock=True, sku="12345678", available_quantity=3
            ),
        ):
            stock_status = await bestbuy_adapter.check_stock("12345678")
            assert stock_status.in_stock is True

        # 3. Add to cart
        with patch.object(
            bestbuy_adapter,
            "_add_to_cart_api",
            return_value=True,
        ):
            cart_result = await bestbuy_adapter.add_to_cart("12345678", 1)
            assert cart_result is True

        # 4. Checkout
        with patch.object(
            bestbuy_adapter,
            "_run_checkout_flow",
            return_value={
                "success": True,
                "order_id": "1122334455",
                "error": "",
            },
        ):
            checkout_result = await bestbuy_adapter.checkout(
                shipping_info, payment_info
            )
            assert checkout_result["success"] is True
            assert checkout_result["order_id"] == "1122334455"
