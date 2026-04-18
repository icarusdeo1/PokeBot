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
