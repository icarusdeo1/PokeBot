"""Tests for TargetAdapter.

Uses mocked Playwright and httpx to test the adapter without
requiring live network calls or browser automation.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.monitor.retailers.target import (
    TargetAdapter,
    _random_locale,
    _random_timezone,
)
from src.shared.models import (
    CaptchaType,
    CaptchaSolveResult,
    ShippingInfo,
    PaymentInfo,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_config() -> MagicMock:
    """Mock Config object."""
    config = MagicMock()
    config.items = [MagicMock(max_cart_quantity=2)]
    config.checkout.retry_attempts = 2
    config.checkout.use_1click_if_available = True
    config.checkout.human_delay_ms = 300
    config.captcha.mode = "smart"
    config.captcha.api_key = ""
    return config


@pytest.fixture
def adapter(mock_config: MagicMock) -> TargetAdapter:
    """Create a TargetAdapter with mocked config."""
    return TargetAdapter(config=mock_config)


# ── Fake Response ─────────────────────────────────────────────────────────────


class FakeResponse:
    """Fake httpx response for mocking."""
    def __init__(self, status_code: int = 200, json_data: dict | None = None) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self) -> dict:
        return self._json_data


def _make_mock_client(response: FakeResponse) -> tuple[MagicMock, MagicMock]:
    """Create a mocked httpx.AsyncClient that returns response for both get/post.

    Returns (mock_async_client, mock_session_instance).
    Usage:
        mock_client, session = _make_mock_client(fake_response)
        with patch("httpx.AsyncClient", return_value=mock_client):
            # session.get(...) will return fake_response
    """
    session = MagicMock()
    session.get = AsyncMock(return_value=response)
    session.post = AsyncMock(return_value=response)

    async def fake_aenter(self: Any) -> MagicMock:
        return session
    async def fake_aexit(self: Any, *args: Any) -> None:
        pass

    mock_client = MagicMock()
    mock_client.return_value = session
    session.__aenter__ = fake_aenter
    session.__aexit__ = fake_aexit
    return mock_client, session


# ── Stock Check Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCheckStock:
    """Tests for check_stock method."""

    async def test_check_stock_api_returns_in_stock(self, adapter: TargetAdapter) -> None:
        """_check_stock_api returns in_stock=True when availability_code is IN_STOCK."""
        api_data = {
            "product": {
                "location_availability": [
                    {"availability_code": "IN_STOCK", "quantity": 5}
                ]
            }
        }
        fake_response = FakeResponse(status_code=200, json_data=api_data)
        mock_client, _session = _make_mock_client(fake_response)

        with patch("httpx.AsyncClient", mock_client):
            status = await adapter._check_stock_api("83821795")

        assert status is not None
        assert status.in_stock is True
        assert status.available_quantity == 5

    async def test_check_stock_api_returns_oos(self, adapter: TargetAdapter) -> None:
        """_check_stock_api returns in_stock=False for out-of-stock items."""
        api_data = {
            "product": {
                "location_availability": [
                    {"availability_code": "OUT_OF_STOCK", "quantity": 0}
                ]
            }
        }
        fake_response = FakeResponse(status_code=200, json_data=api_data)
        mock_client, _session = _make_mock_client(fake_response)

        with patch("httpx.AsyncClient", mock_client):
            status = await adapter._check_stock_api("83821795")

        assert status is not None
        assert status.in_stock is False
        assert status.available_quantity == 0

    async def test_check_stock_api_returns_none_on_network_error(
        self, adapter: TargetAdapter
    ) -> None:
        """_check_stock_api returns None when the API call fails."""
        mock_client = MagicMock()

        async def fake_aenter(self: Any) -> MagicMock:
            m = MagicMock()
            m.get = AsyncMock(side_effect=Exception("Network error"))
            return m
        async def fake_aexit(self: Any, *args: Any) -> None:
            pass

        mock_client.return_value = MagicMock()
        mock_client.return_value.__aenter__ = fake_aenter
        mock_client.return_value.__aexit__ = fake_aexit

        with patch("httpx.AsyncClient", mock_client):
            status = await adapter._check_stock_api("83821795")

        assert status is None

    async def test_check_stock_no_browser_returns_false(self, adapter: TargetAdapter) -> None:
        """check_stock returns in_stock=False when no browser is available."""
        # _page is None
        status = await adapter.check_stock("83821795")
        assert status.in_stock is False

    async def test_check_stock_api_handles_non_200(self, adapter: TargetAdapter) -> None:
        """_check_stock_api returns None when response status is not 200."""
        fake_response = FakeResponse(status_code=429)
        mock_client, _session = _make_mock_client(fake_response)

        with patch("httpx.AsyncClient", mock_client):
            status = await adapter._check_stock_api("83821795")

        assert status is None


# ── Cart Tests ─────────────────────────────────────────────────────────────--


@pytest.mark.asyncio
class TestAddToCart:
    """Tests for add_to_cart method."""

    async def test_add_to_cart_api_success(self, adapter: TargetAdapter) -> None:
        """_add_to_cart_api returns True on HTTP 200."""
        adapter._auth_token = "fake-token"
        fake_response = FakeResponse(status_code=200)
        mock_client, session = _make_mock_client(fake_response)

        with patch("httpx.AsyncClient", mock_client):
            result = await adapter._add_to_cart_api("83821795", 1)

        assert result is True
        session.post.assert_called_once()

    async def test_add_to_cart_api_false_without_auth(self, adapter: TargetAdapter) -> None:
        """_add_to_cart_api returns False when auth token is missing."""
        adapter._auth_token = ""
        result = await adapter._add_to_cart_api("83821795", 1)
        assert result is False

    async def test_add_to_cart_respects_max_quantity(self, adapter: TargetAdapter) -> None:
        """add_to_cart limits quantity to max_cart_quantity from config."""
        adapter._auth_token = "fake-token"
        fake_response = FakeResponse(status_code=200)
        mock_client, session = _make_mock_client(fake_response)

        with patch("httpx.AsyncClient", mock_client):
            # Config has max_cart_quantity=2, but we ask for 5
            result = await adapter.add_to_cart("83821795", quantity=5)

        assert result is True
        # Verify the API was called with quantity=2 (capped)
        call_args = session.post.call_args
        payload = call_args.kwargs.get("json", {})
        assert payload["items"][0]["quantity"] == 2


@pytest.mark.asyncio
class TestGetCart:
    """Tests for get_cart method."""

    async def test_get_cart_api_success(self, adapter: TargetAdapter) -> None:
        """_get_cart_api returns parsed cart items."""
        adapter._auth_token = "fake-token"
        api_data = {
            "cart_items": [
                {"sku_id": "123", "product_title": "Test Item", "quantity": 1, "price": "$10.00"}
            ]
        }
        fake_response = FakeResponse(status_code=200, json_data=api_data)
        mock_client, session = _make_mock_client(fake_response)

        with patch("httpx.AsyncClient", mock_client):
            items = await adapter._get_cart_api()

        assert items is not None
        assert len(items) == 1
        assert items[0]["sku"] == "123"
        assert items[0]["name"] == "Test Item"
        assert items[0]["quantity"] == 1

    async def test_get_cart_api_returns_none_without_auth(self, adapter: TargetAdapter) -> None:
        """_get_cart_api returns None when auth token is missing."""
        adapter._auth_token = ""
        items = await adapter._get_cart_api()
        assert items is None


# ── Checkout Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCheckout:
    """Tests for checkout method."""

    async def test_checkout_retries_on_failure(self, adapter: TargetAdapter) -> None:
        """checkout retries when _run_checkout_flow returns success=False."""
        shipping = ShippingInfo(
            name="Test", address1="123 Main St", city="NYC",
            state="NY", zip_code="10001", phone="555-1234", email="test@test.com"
        )
        payment = PaymentInfo(
            card_number="4111111111111111", expiry_month="12",
            expiry_year="2027", cvv="123"
        )

        call_count = 0

        async def mock_flow(
            _sh: ShippingInfo, _pm: PaymentInfo, _attempt: int
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"success": False, "order_id": "", "error": "Failed"}

        with patch.object(adapter, "_run_checkout_flow", side_effect=mock_flow):
            result = await adapter.checkout(shipping, payment)

        assert result["success"] is False
        assert call_count == 2  # max_attempts=2 from fixture

    async def test_checkout_returns_success_on_first_attempt(self, adapter: TargetAdapter) -> None:
        """checkout returns success when _run_checkout_flow succeeds."""
        shipping = ShippingInfo(
            name="Test", address1="123 Main St", city="NYC",
            state="NY", zip_code="10001", phone="555-1234", email="test@test.com"
        )
        payment = PaymentInfo(
            card_number="4111111111111111", expiry_month="12",
            expiry_year="2027", cvv="123"
        )

        async def mock_flow(
            _sh: ShippingInfo, _pm: PaymentInfo, _attempt: int
        ) -> dict[str, Any]:
            return {"success": True, "order_id": "TEST-ORDER-123", "error": ""}

        with patch.object(adapter, "_run_checkout_flow", side_effect=mock_flow):
            result = await adapter.checkout(shipping, payment)

        assert result["success"] is True
        assert result["order_id"] == "TEST-ORDER-123"


# ── Queue Detection Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCheckQueue:
    """Tests for check_queue method."""

    async def test_check_queue_returns_false_without_page(
        self, adapter: TargetAdapter
    ) -> None:
        """check_queue returns False when _page is None."""
        result = await adapter.check_queue()
        assert result is False

    async def test_check_queue_detects_queue_in_url(self, adapter: TargetAdapter) -> None:
        """check_queue returns True when URL contains queue indicators."""
        mock_page = MagicMock()
        mock_page.url = "https://www.target.com/queue/waiting-room"
        mock_page.title = AsyncMock(return_value="Target - Queue")
        mock_page.inner_text = AsyncMock(return_value="")
        adapter._page = mock_page

        result = await adapter.check_queue()
        assert result is True

    async def test_check_queue_detects_queue_in_page_text(
        self, adapter: TargetAdapter
    ) -> None:
        """check_queue returns True when page text contains queue indicators."""
        mock_page = MagicMock()
        mock_page.url = "https://www.target.com/some/page"
        mock_page.title = AsyncMock(return_value="Target")
        mock_page.inner_text = AsyncMock(
            return_value="You are in a virtual waiting room. Please wait."
        )
        adapter._page = mock_page

        result = await adapter.check_queue()
        assert result is True

    async def test_check_queue_returns_false_when_not_in_queue(
        self, adapter: TargetAdapter
    ) -> None:
        """check_queue returns False when not in a queue."""
        mock_page = MagicMock()
        mock_page.url = "https://www.target.com/p/-/A-123"
        mock_page.title = AsyncMock(return_value="Product Page")
        mock_page.inner_text = AsyncMock(return_value="Add to cart")
        adapter._page = mock_page

        result = await adapter.check_queue()
        assert result is False


# ── CAPTCHA Tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestHandleCaptcha:
    """Tests for handle_captcha method."""

    async def test_handle_captcha_no_page_returns_false(self, adapter: TargetAdapter) -> None:
        """handle_captcha returns success=False when page is None."""
        result = await adapter.handle_captcha(None)
        assert result.success is False
        assert "No page provided" in result.error

    async def test_detect_captcha_type_recaptcha(self, adapter: TargetAdapter) -> None:
        """_detect_captcha_type returns RECAPTCHA_V2 when reCAPTCHA iframe is present."""
        mock_page = MagicMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.query_selector = AsyncMock(
            return_value=MagicMock(is_visible=MagicMock(return_value=True))
        )
        mock_page.content = AsyncMock(return_value="")

        result = await adapter._detect_captcha_type(mock_page)
        assert result == CaptchaType.RECAPTCHA_V2

    async def test_detect_captcha_type_unknown(self, adapter: TargetAdapter) -> None:
        """_detect_captcha_type returns UNKNOWN when no CAPTCHA is detected."""
        mock_page = MagicMock()

        async def mock_wait_for(_selector: str, **kwargs: Any) -> None:
            raise Exception("not found")

        mock_page.wait_for_selector = mock_wait_for
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.content = AsyncMock(return_value="no captcha here")

        result = await adapter._detect_captcha_type(mock_page)
        assert result == CaptchaType.UNKNOWN

    async def test_captcha_manual_mode_pauses_and_resolves(
        self, adapter: TargetAdapter
    ) -> None:
        """In manual mode, handle_captcha resolves when CAPTCHA is cleared."""
        adapter.config.captcha.mode = "manual"

        mock_page = MagicMock()
        mock_page.url = "https://checkout.target.com"

        # CAPTCHA resolves immediately
        async def fake_wait(_page: Any = None) -> None:
            pass

        # Force a non-UNKNOWN captcha type so detection doesn't early-return
        with patch.object(
            adapter,
            "_detect_captcha_type",
            return_value=CaptchaType.RECAPTCHA_V2,
        ):
            with patch.object(adapter, "_wait_for_captcha_resolved", side_effect=fake_wait):
                result = await adapter.handle_captcha(mock_page)

        assert result.success is True
        assert result.solve_time_ms >= 0

    async def test_captcha_smart_mode_turnstile_no_solver(
        self, adapter: TargetAdapter
    ) -> None:
        """In smart mode with Turnstile, returns error when no 2Captcha solver."""
        adapter.config.captcha.mode = "smart"
        mock_page = MagicMock()
        mock_page.url = "https://checkout.target.com"

        call_count = 0

        async def mock_wait_for(selector: str, **kwargs: Any) -> Any:
            nonlocal call_count
            if "google.com/recaptcha" in selector:
                raise Exception("not found")
            if "hcaptcha.com" in selector:
                raise Exception("not found")
            if "challenges.cloudflare.com" in selector:
                # Turnstile found
                return MagicMock()
            raise Exception("not found")

        mock_page.wait_for_selector = mock_wait_for
        # Properly mock Playwright async API: query_selector returns ElementHandle,
        # and ElementHandle.get_attribute is async
        mock_elem = MagicMock(is_visible=MagicMock(return_value=True))
        mock_elem.get_attribute = AsyncMock(return_value="2placeholder0x")
        mock_page.query_selector = AsyncMock(return_value=mock_elem)
        mock_page.content = AsyncMock(return_value="sitekey='2placeholder0x'")

        result = await adapter.handle_captcha(mock_page)
        assert result.success is False
        assert "2Captcha solver not configured" in result.error


# ── Human Delay Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestHumanDelay:
    """Tests for _human_delay method."""

    async def test_human_delay_is_asynchronous(self, adapter: TargetAdapter) -> None:
        """_human_delay is actually async (does not block)."""
        start = time.monotonic()
        await adapter._human_delay(base_ms=100)
        elapsed_ms = (time.monotonic() - start) * 1000
        # Should be approximately 100ms (with ±50ms variation)
        assert 40 < elapsed_ms < 200


# ── Helper Function Tests ────────────────────────────────────────────────────


class TestHelperFunctions:
    """Tests for module-level helper functions."""

    def test_random_locale_returns_valid_locale(self) -> None:
        """_random_locale returns a locale from the predefined list."""
        locales = [
            "en-US", "en-GB", "en-CA", "de-DE", "fr-FR",
            "es-ES", "it-IT", "nl-NL", "pl-PL", "pt-BR",
        ]
        assert _random_locale() in locales

    def test_random_timezone_returns_valid_tz(self) -> None:
        """_random_timezone returns a timezone from the predefined list."""
        timezones = [
            "America/New_York",
            "America/Chicago",
            "America/Denver",
            "America/Los_Angeles",
            "America/Phoenix",
            "Europe/London",
            "Europe/Paris",
            "Europe/Berlin",
            "Europe/Amsterdam",
            "Australia/Sydney",
        ]
        assert _random_timezone() in timezones


# ── Login Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLogin:
    """Tests for login method."""

    async def test_login_no_browser_returns_false(self, adapter: TargetAdapter) -> None:
        """login returns False when browser can't be initialized."""
        with patch("src.bot.monitor.retailers.target.async_playwright") as mock_pw:
            mock_pw.return_value.start = AsyncMock(side_effect=Exception("PW error"))
            result = await adapter.login("test@example.com", "password123")
        assert result is False

    async def test_extract_auth_token_finds_tc_cookie(
        self, adapter: TargetAdapter
    ) -> None:
        """_extract_auth_token finds and returns tc cookie."""
        adapter._context = MagicMock()
        adapter._context.cookies = AsyncMock(return_value=[
            {"name": "tc", "value": "auth-token-abc123"},
            {"name": "other", "value": "value"},
        ])

        token = await adapter._extract_auth_token()
        assert token == "auth-token-abc123"

    async def test_extract_auth_token_returns_empty_when_none(
        self, adapter: TargetAdapter
    ) -> None:
        """_extract_auth_token returns empty string when no auth cookie found."""
        adapter._context = MagicMock()
        adapter._context.cookies = AsyncMock(return_value=[
            {"name": "other", "value": "value"},
        ])

        token = await adapter._extract_auth_token()
        assert token == ""


# ── Close Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestClose:
    """Tests for close method."""

    async def test_close_handles_none_resources(self, adapter: TargetAdapter) -> None:
        """close handles the case where no resources are initialized."""
        await adapter.close()
