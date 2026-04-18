"""CAPTCHA detection, 2Captcha integration, and manual CAPTCHA mode.

Per PRD Section 9.4 (CAP-1 through CAP-9).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from playwright.async_api import Page

from src.bot.config import Config
from src.shared.models import CaptchaSolveResult, CaptchaType


# ── Detection result ───────────────────────────────────────────────────────────

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


# ── Detection ──────────────────────────────────────────────────────────────────

async def detect_captcha(page: Page) -> CaptchaDetectionResult:
    """Scan a Playwright page for any known CAPTCHA challenge type.

    Inspects DOM elements, iframes, and script tags to determine whether a
    CAPTCHA challenge is currently rendered. Call this after page navigation or
    form interaction to check if a challenge has appeared.

    Per PRD Section 9.4 (CAP-1).

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


# ── 2Captcha API ─────────────────────────────────────────────────────────────

_TWOCAPTCHA_BASE = "https://2captcha.com"
_SUBMIT_TIMEOUT_S = 120  # max time to wait for solve (CAP-3)
_POLL_INTERVAL_S = 5  # initial poll interval in seconds


def _build_2captcha_submit_url(
    api_key: str,
    captcha_type: CaptchaType,
    site_key: str,
    page_url: str,
) -> str:
    """Build the 2Captcha CAPTCHA submission URL.

    Per PRD Section 9.4 (CAP-2): Submit challenge to 2Captcha API with
    site key and page URL.

    Args:
        api_key: 2Captcha API key.
        captcha_type: Type of CAPTCHA (hCaptcha uses different method).
        site_key: The site key published by the CAPTCHA provider.
        page_url: Full URL of the page containing the CAPTCHA.

    Returns:
        Fully-qualified 2Captcha in.php URL.
    """
    encoded_url = quote(page_url, safe="")
    if captcha_type == CaptchaType.HCAPTCHA:
        return (
            f"{_TWOCAPTCHA_BASE}/in.php"
            f"?key={api_key}"
            f"&method=hcaptcha"
            f"&sitekey={site_key}"
            f"&pageurl={encoded_url}"
        )
    # reCAPTCHA v2, v3, and Turnstile all use userrecaptcha method
    return (
        f"{_TWOCAPTCHA_BASE}/in.php"
        f"?key={api_key}"
        f"&method=userrecaptcha"
        f"&googlekey={site_key}"
        f"&pageurl={encoded_url}"
    )


def _build_2captcha_poll_url(api_key: str, captcha_id: str) -> str:
    """Build the 2Captcha result-polling URL."""
    return (
        f"{_TWOCAPTCHA_BASE}/res.php"
        f"?key={api_key}"
        f"&action=get"
        f"&id={captcha_id}"
    )


async def solve_with_2captcha(
    api_key: str,
    captcha_type: CaptchaType,
    site_key: str,
    page_url: str,
    timeout_s: int = _SUBMIT_TIMEOUT_S,
) -> CaptchaSolveResult:
    """Submit a CAPTCHA to 2Captcha and poll until solved or timeout.

    Per PRD Sections 9.4 (CAP-2, CAP-3, CAP-5):
      - Submits challenge with site key and page URL
      - Polls with exponential backoff (max 120s)
      - Logs solve time in milliseconds

    Args:
        api_key: 2Captcha API key from config.
        captcha_type: Type of CAPTCHA (reCAPTCHA v2, hCaptcha, Turnstile).
        site_key: The site/key published by the CAPTCHA provider.
        page_url: Full URL of the page showing the CAPTCHA.
        timeout_s: Maximum seconds to wait for a solution (default 120).

    Returns:
        CaptchaSolveResult with token on success, error message on failure.
    """
    if not api_key:
        return CaptchaSolveResult(
            success=False,
            token="",
            solve_time_ms=0,
            error="2Captcha API key not configured",
        )

    submit_url = _build_2captcha_submit_url(api_key, captcha_type, site_key, page_url)
    start_ms = int(time.time() * 1000)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Submit the CAPTCHA challenge (CAP-2)
            submit_resp = await client.get(submit_url)
            submit_text = submit_resp.text.strip()

            if not submit_text.startswith("OK|"):
                return CaptchaSolveResult(
                    success=False,
                    token="",
                    solve_time_ms=int(time.time() * 1000) - start_ms,
                    error=f"2Captcha submit failed: {submit_text}",
                )

            captcha_id = submit_text.split("|", 1)[1]

            # Step 2: Poll for solution with exponential backoff (CAP-3)
            poll_url_base = _build_2captcha_poll_url(api_key, captcha_id)
            elapsed = 0
            interval = _POLL_INTERVAL_S

            while elapsed < timeout_s:
                await asyncio.sleep(interval)
                elapsed += interval

                poll_resp = await client.get(poll_url_base)
                poll_text = poll_resp.text.strip()

                if poll_text.startswith("OK|"):
                    token = poll_text.split("|", 1)[1]
                    solve_time_ms = int(time.time() * 1000) - start_ms
                    return CaptchaSolveResult(
                        success=True,
                        token=token,
                        solve_time_ms=solve_time_ms,
                        error="",
                    )

                if "NOT_READY" not in poll_text:
                    # Genuine error (not just "not ready yet")
                    return CaptchaSolveResult(
                        success=False,
                        token="",
                        solve_time_ms=int(time.time() * 1000) - start_ms,
                        error=f"2Captcha poll error: {poll_text}",
                    )

                # Exponential backoff: double interval each time, cap at 30s
                interval = min(interval * 2, 30)

            # Timeout exceeded
            return CaptchaSolveResult(
                success=False,
                token="",
                solve_time_ms=int(time.time() * 1000) - start_ms,
                error=f"2Captcha timeout after {timeout_s}s",
            )

    except Exception as exc:  # noqa: BLE
        return CaptchaSolveResult(
            success=False,
            token="",
            solve_time_ms=int(time.time() * 1000) - start_ms,
            error=f"2Captcha exception: {exc}",
        )


async def inject_2captcha_token(
    page: Page,
    token: str,
    captcha_type: CaptchaType,
) -> None:
    """Inject a CAPTCHA solution token into the page.

    Per PRD Section 9.4 (CAP-4): Inject solution token into page and
    resubmit the form.

    For reCAPTCHA v2 / Turnstile: fills `g-recaptcha-response` textarea.
    For hCaptcha: fills `h-captcha-response` textarea.
    """
    if captcha_type == CaptchaType.HCAPTCHA:
        selector = "textarea[name='h-captcha-response']"
    else:
        selector = "textarea[name='g-recaptcha-response']"

    textarea = page.locator(selector)
    if await textarea.count() > 0:
        await textarea.fill(token)
    else:
        # Fallback: evaluate JS to set the token
        escaped_selector = selector.replace("'", "\\'")
        await page.evaluate(
            f"""(token) => {{
                var el = document.querySelector('{escaped_selector}');
                if (el) {{
                    el.textContent = token;
                    el.innerHTML = token;
                }}
            }}""",
            token,
        )
