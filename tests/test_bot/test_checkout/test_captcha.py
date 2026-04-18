"""Tests for CAPTCHA detection (CAPTCHA-T01).

Per PRD Section 9.4 (CAP-1).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.checkout.captcha import detect_captcha
from src.shared.models import CaptchaType


# ── Helpers ────────────────────────────────────────────────────────────────────


def make_mock_page(url: str, selectors: list[str]) -> AsyncMock:
    """Build a mock Playwright Page that returns given selectors for query_selector.

    Args:
        url: The page URL.
        selectors: List of (selector, src_attr_value) tuples for mock elements.
                   Pass None for no matching element.
    """
    page = AsyncMock()
    page.url = url
    page.query_selector = AsyncMock()

    # Build a mapping of selector → mock element
    async def query_sel(sel: str):
        for stored_sel, src_val in selectors:
            if stored_sel == sel:
                el = MagicMock()
                if src_val is not None and sel.startswith("iframe"):
                    el.get_attribute = AsyncMock(return_value=src_val)
                else:
                    el.get_attribute = AsyncMock(return_value=None)
                return el
        return None

    page.query_selector.side_effect = query_sel
    return page


# ── CaptchaDetectionResult structure ──────────────────────────────────────────


class TestCaptchaDetectionResult:
    def test_dataclass_fields_exist(self) -> None:
        from src.bot.checkout.captcha import CaptchaDetectionResult

        result = CaptchaDetectionResult(
            detected=True,
            captcha_type=CaptchaType.TURNSTILE,
            challenge_url="https://example.com/challenge",
            element_selector="iframe[src*='turnstile']",
        )
        assert result.detected is True
        assert result.captcha_type == CaptchaType.TURNSTILE
        assert result.element_selector == "iframe[src*='turnstile']"


# ── URL-based detection ────────────────────────────────────────────────────────


class TestCaptchaDetectionByURL:
    @pytest.mark.asyncio
    async def test_hcaptcha_url_detected(self) -> None:
        page = make_mock_page(
            "https://hcaptcha.com/siteverify",  # URL triggers detection
            [],  # no DOM elements needed
        )
        result = await detect_captcha(page)
        assert result.detected is True
        assert result.captcha_type == CaptchaType.HCAPTCHA

    @pytest.mark.asyncio
    async def test_h_captcha_url_detected(self) -> None:
        page = make_mock_page(
            "https://js.h-captcha.com/1/api.js",
            [],
        )
        result = await detect_captcha(page)
        assert result.detected is True
        assert result.captcha_type == CaptchaType.HCAPTCHA

    @pytest.mark.asyncio
    async def test_turnstile_url_detected(self) -> None:
        page = make_mock_page(
            "https://challenges.cloudflare.com/turnstile/v1/challenge",
            [],
        )
        result = await detect_captcha(page)
        assert result.detected is True
        assert result.captcha_type == CaptchaType.TURNSTILE

    @pytest.mark.asyncio
    async def test_recaptcha_v2_iframe_url_detected(self) -> None:
        page = make_mock_page(
            "https://www.google.com/recaptcha/api2/demo",
            [
                # query_selector will return the v2 iframe element
                ("iframe[src*='recaptcha/api2/']", "https://www.google.com/recaptcha/api2/anchor"),
            ],
        )
        result = await detect_captcha(page)
        assert result.detected is True
        assert result.captcha_type == CaptchaType.RECAPTCHA_V2

    @pytest.mark.asyncio
    async def test_recaptcha_v3_script_url_detected(self) -> None:
        page = make_mock_page(
            "https://www.google.com/recaptcha/api.js?render=KEY",
            [],
        )
        result = await detect_captcha(page)
        assert result.detected is True
        assert result.captcha_type == CaptchaType.RECAPTCHA_V3

    @pytest.mark.asyncio
    async def test_recaptcha_net_url_detected_as_v3(self) -> None:
        # recaptcha.net/api.js implies v3 (invisible)
        page = make_mock_page(
            "https://recaptcha.net/recaptcha/api.js",
            [],
        )
        result = await detect_captcha(page)
        assert result.detected is True
        assert result.captcha_type == CaptchaType.RECAPTCHA_V3

    @pytest.mark.asyncio
    async def test_no_captcha_url_returns_false(self) -> None:
        page = make_mock_page(
            "https://www.target.com/p/product",
            [],
        )
        result = await detect_captcha(page)
        assert result.detected is False
        assert result.captcha_type == CaptchaType.UNKNOWN


# ── DOM-based detection ──────────────────────────────────────────────────────


class TestCaptchaDetectionByDOM:
    @pytest.mark.asyncio
    async def test_hcaptcha_dom_detected(self) -> None:
        page = make_mock_page(
            "https://www.target.com/checkout",
            [
                (".h-captcha", None),
            ],
        )
        result = await detect_captcha(page)
        assert result.detected is True
        assert result.captcha_type == CaptchaType.HCAPTCHA
        assert result.element_selector == ".h-captcha"

    @pytest.mark.asyncio
    async def test_hcaptcha_iframe_detected(self) -> None:
        page = make_mock_page(
            "https://www.target.com/checkout",
            [
                ("iframe[src*='hcaptcha.com']", "https://js.h-captcha.com/1/api.js"),
            ],
        )
        result = await detect_captcha(page)
        assert result.detected is True
        assert result.captcha_type == CaptchaType.HCAPTCHA
        assert result.element_selector == "iframe[src*='hcaptcha.com']"
        assert result.challenge_url == "https://js.h-captcha.com/1/api.js"

    @pytest.mark.asyncio
    async def test_turnstile_dom_detected(self) -> None:
        page = make_mock_page(
            "https://www.bestbuy.com/checkout",
            [
                ("[data-turnstile-response]", None),
            ],
        )
        result = await detect_captcha(page)
        assert result.detected is True
        assert result.captcha_type == CaptchaType.TURNSTILE
        assert result.element_selector == "[data-turnstile-response]"

    @pytest.mark.asyncio
    async def test_turnstile_iframe_detected(self) -> None:
        page = make_mock_page(
            "https://www.bestbuy.com/checkout",
            [
                ("iframe[src*='turnstile']", "https://challenges.cloudflare.com/turnstile/v0/binding"),
            ],
        )
        result = await detect_captcha(page)
        assert result.detected is True
        assert result.captcha_type == CaptchaType.TURNSTILE
        assert result.element_selector == "iframe[src*='turnstile']"

    @pytest.mark.asyncio
    async def test_recaptcha_v2_dom_detected(self) -> None:
        page = make_mock_page(
            "https://www.walmart.com/checkout",
            [
                (".g-recaptcha", None),
            ],
        )
        result = await detect_captcha(page)
        assert result.detected is True
        assert result.captcha_type == CaptchaType.RECAPTCHA_V2
        assert result.element_selector == ".g-recaptcha"

    @pytest.mark.asyncio
    async def test_recaptcha_v2_iframe_detected(self) -> None:
        page = make_mock_page(
            "https://www.walmart.com/checkout",
            [
                ("iframe[src*='google.com/recaptcha']", "https://www.google.com/recaptcha/api2/anchor"),
            ],
        )
        result = await detect_captcha(page)
        assert result.detected is True
        assert result.captcha_type == CaptchaType.RECAPTCHA_V2

    @pytest.mark.asyncio
    async def test_recaptcha_v3_script_detected(self) -> None:
        page = make_mock_page(
            "https://www.walmart.com/checkout",
            [
                ("script[src*='recaptcha/api.js']", "https://www.google.com/recaptcha/api.js?render=KEY"),
            ],
        )
        result = await detect_captcha(page)
        assert result.detected is True
        assert result.captcha_type == CaptchaType.RECAPTCHA_V3
        assert result.element_selector == "script[src*='recaptcha/api.js']"

    @pytest.mark.asyncio
    async def test_no_captcha_returns_unknown(self) -> None:
        page = make_mock_page(
            "https://www.target.com/p/sku123",
            [],
        )
        result = await detect_captcha(page)
        assert result.detected is False
        assert result.captcha_type == CaptchaType.UNKNOWN
        assert result.challenge_url == "https://www.target.com/p/sku123"


# ── Ordering: URL beats DOM ───────────────────────────────────────────────────


class TestDetectionPriority:
    @pytest.mark.asyncio
    async def test_url_takes_precedence_over_dom(self) -> None:
        """If both URL and DOM indicate CAPTCHA, URL type takes precedence."""
        page = make_mock_page(
            "https://js.h-captcha.com/api.js",  # hCaptcha URL
            [
                # DOM would look like Turnstile, but URL wins
                ("iframe[src*='turnstile']", None),
            ],
        )
        result = await detect_captcha(page)
        assert result.detected is True
        assert result.captcha_type == CaptchaType.HCAPTCHA


# ── Priority order: hCaptcha > Turnstile > reCAPTCHA v2 > reCAPTCHA v3 ─────────


class TestCaptchaTypePriority:
    @pytest.mark.asyncio
    async def test_hcaptcha_detected_before_turnstile(self) -> None:
        """If page URL contains both signals, hCaptcha wins."""
        page = make_mock_page(
            "https://js.h-captcha.com/api.js?sitekey=KEY&challenge=cf-challenge",
            [],
        )
        result = await detect_captcha(page)
        assert result.captcha_type == CaptchaType.HCAPTCHA

    @pytest.mark.asyncio
    async def test_turnstile_detected_before_recaptcha(self) -> None:
        """If page URL contains both Turnstile and reCAPTCHA, Turnstile wins."""
        page = make_mock_page(
            "https://challenges.cloudflare.com/turnstile/v1/challenge?k=TOKEN&render=https://google.com/recaptcha/api.js",
            [],
        )
        result = await detect_captcha(page)
        assert result.captcha_type == CaptchaType.TURNSTILE


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_multiple_challenge_types_first_wins(self) -> None:
        """Multiple DOM selectors match; first captcha type in priority order wins.

        hCaptcha selectors are checked before Turnstile, so hCaptcha wins
        when both are present in the DOM.
        """
        page = make_mock_page(
            "https://www.target.com/checkout",
            [
                (".h-captcha", None),
                ("iframe[src*='turnstile']", "https://challenges.cloudflare.com/"),
            ],
        )
        result = await detect_captcha(page)
        # hCaptcha DOM check comes before Turnstile DOM check
        assert result.captcha_type == CaptchaType.HCAPTCHA

    @pytest.mark.asyncio
    async def test_empty_page_no_captcha(self) -> None:
        page = make_mock_page("https://blank.page/", [])
        result = await detect_captcha(page)
        assert result.detected is False
        assert result.captcha_type == CaptchaType.UNKNOWN

    @pytest.mark.asyncio
    async def test_normal_retailer_page_no_captcha(self) -> None:
        """Regular product page should not trigger any CAPTCHA detection."""
        page = make_mock_page(
            "https://www.bestbuy.com/site/electronics/123.p",
            [
                ("script[src*='analytics']", None),
                ("link[href*='styles']", None),
            ],
        )
        result = await detect_captcha(page)
        assert result.detected is False
        assert result.captcha_type == CaptchaType.UNKNOWN


# ── 2Captcha API Tests (CAPTCHA-T02) ─────────────────────────────────────────

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.checkout.captcha import (
    _build_2captcha_poll_url,
    _build_2captcha_submit_url,
    inject_2captcha_token,
    solve_with_2captcha,
)
from src.shared.models import CaptchaSolveResult, CaptchaType


class TestBuildSubmitUrl:
    """Tests for _build_2captcha_submit_url (CAP-2)."""

    def test_recaptcha_v2_url_format(self) -> None:
        url = _build_2captcha_submit_url(
            api_key="MYKEY",
            captcha_type=CaptchaType.RECAPTCHA_V2,
            site_key="SITEKEY123",
            page_url="https://example.com/checkout",
        )
        assert "key=MYKEY" in url
        assert "method=userrecaptcha" in url
        assert "googlekey=SITEKEY123" in url
        assert "pageurl=" in url
        assert "example.com" in url

    def test_recaptcha_v3_url_format(self) -> None:
        url = _build_2captcha_submit_url(
            api_key="MYKEY",
            captcha_type=CaptchaType.RECAPTCHA_V3,
            site_key="SITEKEY123",
            page_url="https://example.com/page",
        )
        assert "method=userrecaptcha" in url
        assert "googlekey=SITEKEY123" in url

    def test_hcaptcha_uses_hcaptcha_method(self) -> None:
        url = _build_2captcha_submit_url(
            api_key="MYKEY",
            captcha_type=CaptchaType.HCAPTCHA,
            site_key="HCAPTCHAKEY",
            page_url="https://example.com/page",
        )
        assert "method=hcaptcha" in url
        assert "sitekey=HCAPTCHAKEY" in url

    def test_turnstile_uses_userrecaptcha_method(self) -> None:
        url = _build_2captcha_submit_url(
            api_key="MYKEY",
            captcha_type=CaptchaType.TURNSTILE,
            site_key="TURNSTILEKEY",
            page_url="https://example.com/page",
        )
        # Turnstile uses the same API method as reCAPTCHA v2
        assert "method=userrecaptcha" in url
        assert "googlekey=TURNSTILEKEY" in url


class TestBuildPollUrl:
    """Tests for _build_2captcha_poll_url."""

    def test_poll_url_includes_captcha_id(self) -> None:
        url = _build_2captcha_poll_url("MYKEY", "CAPTCHA123")
        assert "key=MYKEY" in url
        assert "action=get" in url
        assert "id=CAPTCHA123" in url


class TestSolveWith2Captcha:
    """Tests for solve_with_2captcha (CAP-2, CAP-3, CAP-5)."""

    @pytest.mark.asyncio
    async def test_returns_error_when_no_api_key(self) -> None:
        result = await solve_with_2captcha(
            api_key="",
            captcha_type=CaptchaType.RECAPTCHA_V2,
            site_key="KEY",
            page_url="https://example.com",
        )
        assert result.success is False
        assert result.token == ""
        assert "not configured" in result.error

    @pytest.mark.asyncio
    async def test_submit_failed_returns_error(self) -> None:
        mock_response = MagicMock()
        mock_response.text = "ERROR_NOT_ACCESSIBLE"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await solve_with_2captcha(
                api_key="BADKEY",
                captcha_type=CaptchaType.RECAPTCHA_V2,
                site_key="KEY",
                page_url="https://example.com",
                timeout_s=5,
            )

        assert result.success is False
        assert result.token == ""
        assert "submit failed" in result.error

    @pytest.mark.asyncio
    async def test_poll_returns_token_on_success(self) -> None:
        # First call (submit): returns OK|CAPTCHA_ID
        submit_response = MagicMock()
        submit_response.text = "OK|CAPTCHA_ID_123"
        # Second call (poll): returns OK|SOLUTION_TOKEN
        poll_response = MagicMock()
        poll_response.text = "OK|g-recaptcha-response-token-xyz"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(side_effect=[submit_response, poll_response])

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await solve_with_2captcha(
                api_key="GOODKEY",
                captcha_type=CaptchaType.RECAPTCHA_V2,
                site_key="KEY",
                page_url="https://example.com",
                timeout_s=10,
            )

        assert result.success is True
        assert result.token == "g-recaptcha-response-token-xyz"
        assert result.solve_time_ms > 0
        assert result.error == ""

    @pytest.mark.asyncio
    async def test_poll_returns_error_on_api_error(self) -> None:
        submit_response = MagicMock()
        submit_response.text = "OK|CAPTCHA_ID"
        error_response = MagicMock()
        error_response.text = "ERROR_IP_NOT_ALLOWED"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(side_effect=[submit_response, error_response])

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await solve_with_2captcha(
                api_key="KEY",
                captcha_type=CaptchaType.RECAPTCHA_V2,
                site_key="KEY",
                page_url="https://example.com",
                timeout_s=10,
            )

        assert result.success is False
        assert "poll error" in result.error

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_error(self) -> None:
        # First call (submit): returns OK|ID
        # Subsequent calls: return NOT_READY until timeout
        submit_response = MagicMock()
        submit_response.text = "OK|CAPTCHA_ID_123"
        not_ready = MagicMock()
        not_ready.text = "CAPCHA_NOT_READY"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        # First call returns OK, subsequent calls return NOT_READY
        mock_client.get = AsyncMock(side_effect=[submit_response, not_ready, not_ready])

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await solve_with_2captcha(
                api_key="KEY",
                captcha_type=CaptchaType.RECAPTCHA_V2,
                site_key="KEY",
                page_url="https://example.com",
                timeout_s=2,  # Very short timeout for test
            )

        assert result.success is False
        assert "timeout" in result.error

    @pytest.mark.asyncio
    async def test_exception_returns_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(side_effect=ConnectionError("network error"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await solve_with_2captcha(
                api_key="KEY",
                captcha_type=CaptchaType.RECAPTCHA_V2,
                site_key="KEY",
                page_url="https://example.com",
                timeout_s=5,
            )

        assert result.success is False
        assert "exception" in result.error


class TestInjectToken:
    """Tests for inject_2captcha_token (CAP-4)."""

    @pytest.mark.asyncio
    async def test_injects_recaptcha_token(self) -> None:
        # Use MagicMock for page so locator() returns mock_locator directly (sync)
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=1)  # await count() → 1
        mock_locator.fill = AsyncMock()
        mock_page = MagicMock()
        mock_page.locator = MagicMock(return_value=mock_locator)

        await inject_2captcha_token(
            mock_page,
            token="RECAPTCHA_TOKEN_ABC",
            captcha_type=CaptchaType.RECAPTCHA_V2,
        )

        mock_page.locator.assert_called_with("textarea[name='g-recaptcha-response']")
        mock_locator.fill.assert_called_once_with("RECAPTCHA_TOKEN_ABC")

    @pytest.mark.asyncio
    async def test_injects_hcaptcha_token(self) -> None:
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=1)
        mock_locator.fill = AsyncMock()
        mock_page = MagicMock()
        mock_page.locator = MagicMock(return_value=mock_locator)

        await inject_2captcha_token(
            mock_page,
            token="HCAPTCHA_TOKEN_XYZ",
            captcha_type=CaptchaType.HCAPTCHA,
        )

        mock_page.locator.assert_called_with("textarea[name='h-captcha-response']")
        mock_locator.fill.assert_called_once_with("HCAPTCHA_TOKEN_XYZ")

    @pytest.mark.asyncio
    async def test_falls_back_to_js_eval_when_no_textarea(self) -> None:
        """If the textarea is not found, uses page.evaluate to set token."""
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=0)  # not found → count=0
        mock_page = MagicMock()
        mock_page.locator = MagicMock(return_value=mock_locator)
        mock_page.evaluate = AsyncMock()

        await inject_2captcha_token(
            mock_page,
            token="TOKEN_VIA_JS",
            captcha_type=CaptchaType.RECAPTCHA_V2,
        )

        mock_page.evaluate.assert_called_once()
