"""CAPTCHA detection for retailer pages.

Detects reCAPTCHA, hCaptcha, and Cloudflare Turnstile challenges on retailer
pages using Playwright. Used as the first step in the CAPTCHA handling pipeline
per PRD Section 9.4 (CAP-1).

This module is intentionally retailer-agnostic. It inspects page content to
identify which challenge type (if any) is present, and can be called from any
adapter's flow.
"""

from __future__ import annotations

from dataclasses import dataclass

from playwright.async_api import Page

from src.shared.models import CaptchaType


@dataclass
class CaptchaDetectionResult:
    """Result of a CAPTCHA detection scan."""

    detected: bool
    """True if a CAPTCHA challenge was found on the page."""

    captcha_type: CaptchaType
    """The type of CAPTCHA detected, or UNKNOWN if none found."""

    challenge_url: str
    """URL of the challenge frame/page, if determinable."""

    element_selector: str | None
    """CSS selector for the challenge element, if found."""


# ── Detection selectors ───────────────────────────────────────────────────────

# Google reCAPTCHA v2 (checkbox style)
_RECAPTCHA_V2_SELECTORS = [
    "#recaptcha",
    "[data-callback][src*='recaptcha']",
    ".g-recaptcha",
    "iframe[src*='google.com/recaptcha']",
    "iframe[src*='recaptcha/api2/']",
]

# Google reCAPTCHA v3 (invisible, embedded via API)
_RECAPTCHA_V3_SELECTORS = [
    "script[src*='recaptcha/api.js']",
    "script[src*='recaptcha/api2/component']",
]

# hCaptcha
_HCAPTCHA_SELECTORS = [
    ".h-captcha",
    "[data-sitekey]",
    "iframe[src*='hcaptcha.com']",
    "iframe[src*='h-captcha.com']",
]

# Cloudflare Turnstile
_TURNSTILE_SELECTORS = [
    "[data-turnstile-response]",
    "iframe[src*='turnstile']",
    "iframe[src*='challenges.cloudflare.com']",
    "#cf-challenge",
]


async def detect_captcha(page: Page) -> CaptchaDetectionResult:
    """Scan a Playwright page for any known CAPTCHA challenge type.

    Inspects DOM elements, iframes, and script tags to determine whether a
    CAPTCHA challenge is currently rendered. Call this after page navigation or
    form interaction to check if a challenge has appeared.

    Args:
        page: A Playwright async page object.

    Returns:
        CaptchaDetectionResult with detection outcome and challenge metadata.
    """
    # Check URL-based indicators first (fastest path)
    url = page.url.lower()

    if "hcaptcha.com" in url or "h-captcha.com" in url:
        return CaptchaDetectionResult(
            detected=True,
            captcha_type=CaptchaType.HCAPTCHA,
            challenge_url=url,
            element_selector=None,
        )

    if "turnst" in url or "cloudflare" in url:
        return CaptchaDetectionResult(
            detected=True,
            captcha_type=CaptchaType.TURNSTILE,
            challenge_url=url,
            element_selector=None,
        )

    if "recaptcha.net" in url or "google.com/recaptcha" in url:
        # Distinguish v2 vs v3 by presence of visible checkbox iframe
        has_v2 = await page.query_selector("iframe[src*='recaptcha/api2/']") is not None
        captcha_type = CaptchaType.RECAPTCHA_V2 if has_v2 else CaptchaType.RECAPTCHA_V3
        return CaptchaDetectionResult(
            detected=True,
            captcha_type=captcha_type,
            challenge_url=url,
            element_selector=None,
        )

    # DOM-based detection (covers rendered challenges)
    # hCaptcha — always has a visible iframe
    for selector in _HCAPTCHA_SELECTORS:
        element = await page.query_selector(selector)
        if element is not None:
            src = await element.get_attribute("src") if selector.startswith("iframe") else None
            return CaptchaDetectionResult(
                detected=True,
                captcha_type=CaptchaType.HCAPTCHA,
                challenge_url=src or url,
                element_selector=selector,
            )

    # Turnstile — has a visible widget iframe or data attribute
    for selector in _TURNSTILE_SELECTORS:
        element = await page.query_selector(selector)
        if element is not None:
            src = await element.get_attribute("src") if selector.startswith("iframe") else None
            return CaptchaDetectionResult(
                detected=True,
                captcha_type=CaptchaType.TURNSTILE,
                challenge_url=src or url,
                element_selector=selector,
            )

    # reCAPTCHA v2 — visible checkbox iframe
    for selector in _RECAPTCHA_V2_SELECTORS:
        element = await page.query_selector(selector)
        if element is not None:
            src = await element.get_attribute("src") if selector.startswith("iframe") else None
            return CaptchaDetectionResult(
                detected=True,
                captcha_type=CaptchaType.RECAPTCHA_V2,
                challenge_url=src or url,
                element_selector=selector,
            )

    # reCAPTCHA v3 — invisible, but script tag is always present
    for selector in _RECAPTCHA_V3_SELECTORS:
        element = await page.query_selector(selector)
        if element is not None:
            src = await element.get_attribute("src")
            return CaptchaDetectionResult(
                detected=True,
                captcha_type=CaptchaType.RECAPTCHA_V3,
                challenge_url=src or url,
                element_selector=selector,
            )

    return CaptchaDetectionResult(
        detected=False,
        captcha_type=CaptchaType.UNKNOWN,
        challenge_url=url,
        element_selector=None,
    )
