"""CAPTCHA detection, 2Captcha integration, and manual CAPTCHA mode.

Per PRD Section 9.4 (CAP-1 through CAP-9).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote
from datetime import datetime, timezone

import httpx
from playwright.async_api import Page

from src.bot.config import Config
from src.shared.models import CaptchaSolveResult, CaptchaType, WebhookEvent


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


# ── Manual CAPTCHA Mode (CAP-8) ────────────────────────────────────────────────

async def handle_manual_captcha(
    page: Page,
    captcha_type: CaptchaType,
    webhook_callback: Callable[..., Any] | None,
    timeout_seconds: int = 120,
    item: str = "",
    retailer: str = "",
) -> CaptchaSolveResult:
    """Handle CAPTCHA in manual mode: pause, notify operator, wait for solve.

    Fires CAPTCHA_PENDING_MANUAL webhook to Discord/Telegram with pause URL.
    Waits for operator to solve the challenge in-browser.
    Resumes on completion or timeout.

    Per PRD Section 9.4 (CAP-8).

    Args:
        page: Playwright page where CAPTCHA appeared.
        captcha_type: Type of CAPTCHA challenge.
        webhook_callback: Async callable to fire WebhookEvent; may be None.
        timeout_seconds: Max seconds to wait for operator solve (default 120).
        item: Item name for webhook event context.
        retailer: Retailer name for webhook event context.

    Returns:
        CaptchaSolveResult with success=True on solve, success=False on timeout.
    """
    start_time = time.monotonic()
    page_url = str(page.url) if page else ""

    # Fire CAPTCHA_PENDING_MANUAL webhook so operator gets notified
    if webhook_callback is not None:
        webhook_event = WebhookEvent(
            event="CAPTCHA_PENDING_MANUAL",
            item=item,
            retailer=retailer,
            timestamp=datetime.now(timezone.utc).isoformat(),
            captcha_type=captcha_type.value,
            pause_url=page_url,
            error="",
        )
        try:
            await webhook_callback(webhook_event)
        except Exception:  # noqa: BLE001
            pass  # Non-critical: operator may be watching the bot directly

    try:
        await asyncio.wait_for(
            _wait_for_captcha_resolved(page),
            timeout=timeout_seconds,
        )
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        return CaptchaSolveResult(
            success=True,
            token="",
            solve_time_ms=elapsed_ms,
            error="",
        )
    except asyncio.TimeoutError:
        return CaptchaSolveResult(
            success=False,
            token="",
            solve_time_ms=int((time.monotonic() - start_time) * 1000),
            error=f"Manual CAPTCHA timed out after {timeout_seconds}s",
        )


async def _wait_for_captcha_resolved(page: Page) -> None:
    """Poll until the CAPTCHA challenge is no longer visible on the page."""
    while True:
        try:
            el = await page.query_selector(
                'iframe[src*="google.com/recaptcha"], '
                'iframe[src*="hcaptcha.com"], '
                'iframe[src*="challenges.cloudflare.com"]'
            )
            if not el or not await el.is_visible():
                break
            await asyncio.sleep(2)
        except Exception:  # noqa: BLE001
            break


# ── Smart CAPTCHA Routing (CAP-9) ─────────────────────────────────────────────

def get_captcha_mode(config: Config, retailer: str | None = None) -> str:
    """Return the effective CAPTCHA mode, checking per-retailer override.

    Per PRD Section 9.4.1: mode priority is per-retailer override > global mode.

    Args:
        config: Config instance with captcha settings.
        retailer: Optional retailer name for per-retailer override lookup.

    Returns:
        One of "auto", "manual", "smart".
    """
    mode = getattr(config.captcha, "mode", "smart")
    # Per-retailer override not yet implemented in config schema; reserved for future
    return mode


def should_auto_solve(
    captcha_type: CaptchaType,
    mode: str,
    budget_tracker: CaptchaBudgetTracker | None,
    retailer: str | None = None,
) -> bool:
    """Determine whether a CAPTCHA should be auto-solved or routed to manual mode.

    Per PRD Section 9.4 (CAP-9) and Section 9.4.1:
      - auto mode: always auto-solve
      - manual mode: never auto-solve (always manual)
      - smart mode: Turnstile → auto-solve; others → manual (unless budget exceeded)

    Args:
        captcha_type: Type of CAPTCHA detected.
        mode: Global CAPTCHA mode ("auto", "manual", "smart").
        budget_tracker: Optional budget tracker to check daily spend cap.
        retailer: Optional retailer for per-retailer budget check.

    Returns:
        True if the CAPTCHA should be auto-solved via 2Captcha.
    """
    if mode == "manual":
        return False

    if mode == "auto":
        # Check budget cap before auto-solving
        if budget_tracker is not None and not budget_tracker.can_solve(retailer):
            return False
        return True

    # smart mode
    if captcha_type == CaptchaType.TURNSTILE:
        # Turnstile is low-cost, high pass rate → auto-solve
        if budget_tracker is not None and not budget_tracker.can_solve(retailer):
            return False
        return True

    # reCAPTCHA/hCaptcha in smart mode → manual (operator alert)
    return False


# ── CAPTCHA Budget Tracker (CAP-7) ─────────────────────────────────────────────

@dataclass
class CaptchaBudgetTracker:
    """Tracks daily 2Captcha spend against per-day and per-retailer budget caps.

    Per PRD Sections 9.4 (CAP-7) and 9.4.2:
      - Halts 2Captcha auto-solves when daily spend exceeds cap
      - Manual mode always remains available regardless of budget
      - Supports per-retailer cap overrides
      - Logs total spend on shutdown

    Usage::

        tracker = CaptchaBudgetTracker(config.captcha)
        if tracker.can_solve(retailer="target"):
            token = await solve_with_2captcha(...)
            tracker.record_solve(retailer="target", cost_usd=0.002)
        tracker.emit_daily_spend()
    """

    daily_budget_usd: float
    per_retailer_override: dict[str, float]
    solve_time_alert_ms: int
    _log_daily: bool
    _daily_spend_usd: float = field(default=0.0, init=False)
    _last_reset_date: str = field(default="", init=False)

    def __init__(
        self,
        captcha_config: Any,
        daily_budget_usd: float = 5.0,
        per_retailer_override: dict[str, float] | None = None,
        solve_time_alert_ms: int = 60000,
        log_daily: bool = True,
    ) -> None:
        """Initialize tracker with config values.

        Args:
            captcha_config: _CaptchaConfig instance (or duck-typed equivalent).
            daily_budget_usd: Global daily budget cap in USD.
            per_retailer_override: Mapping of retailer name → budget override.
            solve_time_alert_ms: Threshold for solve-time webhook alerts.
            log_daily: Whether to log cumulative spend on shutdown.
        """
        self.daily_budget_usd = daily_budget_usd
        self.per_retailer_override = per_retailer_override or {}
        self.solve_time_alert_ms = solve_time_alert_ms
        self._log_daily = log_daily
        self._daily_spend_usd = 0.0
        self._last_reset_date = self._today_str()

    def _today_str(self) -> str:
        """Return today's date string for daily reset comparison."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _check_daily_reset(self) -> None:
        """Reset daily spend counter if day has rolled over."""
        today = self._today_str()
        if today != self._last_reset_date:
            self._daily_spend_usd = 0.0
            self._last_reset_date = today

    def _get_retailer_budget(self, retailer: str | None) -> float:
        """Return the effective budget for a given retailer."""
        if retailer and retailer in self.per_retailer_override:
            return self.per_retailer_override[retailer]
        return self.daily_budget_usd

    def can_solve(self, retailer: str | None = None) -> bool:
        """Return True if budget allows a solve for the given retailer.

        Args:
            retailer: Optional retailer name for per-retailer budget check.

        Returns:
            True if under budget, False if cap exceeded.
        """
        self._check_daily_reset()
        budget = self._get_retailer_budget(retailer)
        return self._daily_spend_usd < budget

    def record_solve(self, retailer: str | None, cost_usd: float) -> None:
        """Record a completed CAPTCHA solve cost.

        Args:
            retailer: Retailer name (used for per-retailer tracking).
            cost_usd: Cost of the solve in USD.
        """
        self._check_daily_reset()
        self._daily_spend_usd += cost_usd

    def should_alert_solve_time(self, solve_time_ms: int) -> bool:
        """Return True if solve time exceeded the alert threshold.

        Per PRD Section 9.4.2: fire webhook if single solve exceeds threshold.

        Args:
            solve_time_ms: Solve time in milliseconds.

        Returns:
            True if solve time exceeds configured threshold.
        """
        return solve_time_ms > self.solve_time_alert_ms

    def emit_daily_spend(self) -> None:
        """Log total daily spend to console (on bot shutdown)."""
        import logging
        logger = logging.getLogger("pokedrop")
        logger.info(
            "CAPTCHA_DAILY_SPEND",
            extra={
                "daily_spend_usd": round(self._daily_spend_usd, 4),
                "daily_budget_usd": self.daily_budget_usd,
            },
        )


# ── 2Captcha API ─────────────────────────────────────────────────────────────

_TWOCAPTCHA_BASE = "https://2captcha.com"
_SUBMIT_TIMEOUT_S = 120  # max time to wait for solve (CAP-3)
_POLL_INTERVAL_S = 5  # initial poll interval in seconds
_TWOCAPTCHA_COST_PER_SOLVE_USD = 0.0025  # approximate cost per solve


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
    budget_tracker: CaptchaBudgetTracker | None = None,
    retailer: str | None = None,
    webhook_callback: Callable[..., Any] | None = None,
) -> CaptchaSolveResult:
    """Submit a CAPTCHA to 2Captcha and poll until solved or timeout.

    Per PRD Sections 9.4 (CAP-2, CAP-3, CAP-5):
      - Submits challenge with site key and page URL
      - Polls with exponential backoff (max 120s)
      - Logs solve time in milliseconds
      - Checks budget tracker before solving (CAP-7)
      - Fires CAPTCHA_BUDGET_EXCEEDED webhook if budget is exceeded (CAP-7)

    Args:
        api_key: 2Captcha API key from config.
        captcha_type: Type of CAPTCHA (reCAPTCHA v2, hCaptcha, Turnstile).
        site_key: The site/key published by the CAPTCHA provider.
        page_url: Full URL of the page showing the CAPTCHA.
        timeout_s: Maximum seconds to wait for a solution (default 120).
        budget_tracker: Optional budget tracker for CAP-7 budget enforcement.
        retailer: Optional retailer name for per-retailer budget tracking.
        webhook_callback: Optional async callable to fire WebhookEvent.

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

    # CAP-7: Check budget before solving
    if budget_tracker is not None and not budget_tracker.can_solve(retailer):
        if webhook_callback is not None:
            webhook_event = WebhookEvent(
                event="CAPTCHA_BUDGET_EXCEEDED",
                retailer=retailer or "",
                timestamp=datetime.now(timezone.utc).isoformat(),
                error=f"Daily budget exceeded: ${budget_tracker.daily_budget_usd}",
            )
            try:
                await webhook_callback(webhook_event)
            except Exception:  # noqa: BLE001
                pass
        return CaptchaSolveResult(
            success=False,
            token="",
            solve_time_ms=0,
            error="CAPTCHA budget exceeded",
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

                    # Record cost in budget tracker
                    if budget_tracker is not None:
                        budget_tracker.record_solve(retailer, _TWOCAPTCHA_COST_PER_SOLVE_USD)
                        # CAP-7: Alert if solve time exceeded threshold
                        if budget_tracker.should_alert_solve_time(solve_time_ms):
                            if webhook_callback is not None:
                                webhook_event = WebhookEvent(
                                    event="CAPTCHA_SOLVE_TIME_ALERT",
                                    timestamp=datetime.now(timezone.utc).isoformat(),
                                    error=f"Solve time {solve_time_ms}ms exceeded alert threshold {budget_tracker.solve_time_alert_ms}ms",
                                )
                                try:
                                    await webhook_callback(webhook_event)
                                except Exception:  # noqa: BLE001
                                    pass

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


# Silence import warnings for type checking
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.bot.config import Config