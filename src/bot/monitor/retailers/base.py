"""Retailer adapter base class and common utilities.

Provides the concrete RetailerAdapter implementation with shared
session management, HTTP client setup, pre-warm logic, and common
utilities used by all retailer-specific adapters.

Per PRD Sections 9.1, 9.2, 9.3.
"""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

import httpx

from src.shared.models import (
    CaptchaSolveResult,
    ShippingInfo,
    PaymentInfo,
    StockStatus,
    SessionState,
)

if TYPE_CHECKING:
    from src.bot.config import Config
    from src.bot.logger import Logger


class RetailerAdapter(ABC):
    """Abstract base class for all retailer adapters.

    Subclasses must implement all abstract methods. This class provides
    shared utilities: session cookie management, pre-warm logic,
    HTTP client setup, jitter, and common retry/backoff helpers.

    Per PRD Sections 9.1, 9.2, 9.3.
    """

    name: str = ""
    base_url: str = ""

    def __init__(self, config: Config) -> None:
        """Initialize the adapter with bot configuration.

        Args:
            config: Validated Config instance.
        """
        self.config = config
        self._session: httpx.AsyncClient | None = None
        self._session_state: SessionState | None = None
        self._prewarmed: bool = False
        self._logger: Logger | None = None

    # ── Abstract Interface ──────────────────────────────────────────────────

    @abstractmethod
    async def login(self, username: str, password: str) -> bool:
        """Authenticate with the retailer. Returns True on success."""
        ...

    @abstractmethod
    async def check_stock(self, sku: str) -> StockStatus:
        """Check if a SKU is in stock at this retailer."""
        ...

    @abstractmethod
    async def add_to_cart(self, sku: str, quantity: int = 1) -> bool:
        """Add a SKU to the cart. Returns True on success."""
        ...

    @abstractmethod
    async def get_cart(self) -> list[dict[str, Any]]:
        """Return current cart contents as list of item dicts."""
        ...

    @abstractmethod
    async def checkout(
        self,
        shipping: ShippingInfo,
        payment: PaymentInfo,
    ) -> dict[str, Any]:
        """Complete checkout. Returns dict with order confirmation or error."""
        ...

    @abstractmethod
    async def handle_captcha(self, page: Any) -> CaptchaSolveResult:
        """Detect and handle any CAPTCHA challenge on the given page."""
        ...

    @abstractmethod
    async def check_queue(self) -> bool:
        """Return True if currently in a queue/waiting room."""
        ...

    # ── HTTP Client ───────────────────────────────────────────────────────

    def get_http_client(self) -> httpx.AsyncClient:
        """Return a reusable async HTTP client with connection pooling.

        The client is configured with:
        - 30s connect timeout, 60s read timeout
        - httpx.HTTPTransport with connection pooling
        - Default headers (User-Agent rotated externally via evasion)
        """
        if self._session is None:
            self._session = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=30.0,
                    read=60.0,
                    write=30.0,
                    pool=10.0,
                ),
                headers={
                    "Accept": "application/json, text/html, */*",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        return self._session

    async def close_http_client(self) -> None:
        """Close the HTTP client and release connections."""
        if self._session is not None:
            await self._session.aclose()
            self._session = None

    # ── Session Management ──────────────────────────────────────────────────

    @property
    def session_state(self) -> SessionState | None:
        """Return the current session state, or None if not pre-warmed."""
        return self._session_state

    def is_prewarmed(self) -> bool:
        """Return True if this adapter's session has been pre-warmed."""
        return self._prewarmed

    async def save_session_state(
        self,
        cookies: dict[str, str],
        auth_token: str = "",
        cart_token: str = "",
    ) -> None:
        """Persist the current session state for reuse across checks.

        Args:
            cookies: Browser cookie dict.
            auth_token: Auth token string.
            cart_token: Cart token string.
        """
        from datetime import datetime, timezone

        self._session_state = SessionState(
            cookies=cookies,
            auth_token=auth_token,
            cart_token=cart_token,
            prewarmed_at=datetime.now(timezone.utc).isoformat(),
            is_valid=True,
        )

    async def invalidate_session(self) -> None:
        """Mark the current session as invalid. Triggers re-auth on next use."""
        if self._session_state is not None:
            self._session_state.is_valid = False
        self._prewarmed = False

    async def close(self) -> None:
        """Close all resources: HTTP client, browser, etc."""
        await self.close_http_client()
        self._session_state = None
        self._prewarmed = False

    # ── Jitter ──────────────────────────────────────────────────────────────

    def apply_jitter(
        self,
        base_interval_ms: int,
        jitter_percent: int | None = None,
    ) -> float:
        """Apply random jitter ±N% to a base interval.

        Args:
            base_interval_ms: Base interval in milliseconds.
            jitter_percent: Jitter percentage (default from config, 20%).

        Returns:
            Interval in seconds as a float with jitter applied.
        """
        if jitter_percent is None:
            jitter_percent = self.config.evasion.jitter_percent
        jitter_fraction = jitter_percent / 100.0
        min_val = base_interval_ms * (1 - jitter_fraction)
        max_val = base_interval_ms * (1 + jitter_fraction)
        jittered_ms = random.uniform(min_val, max_val)
        return jittered_ms / 1000.0

    # ── Retry / Backoff ─────────────────────────────────────────────────────

    async def retry_with_backoff(
        self,
        coro: Any,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
    ) -> Any:
        """Retry an async coroutine with exponential backoff.

        Args:
            coro: Zero-argument async coroutine to retry.
            max_attempts: Maximum number of attempts.
            base_delay: Initial delay in seconds.
            max_delay: Maximum delay in seconds.
            backoff_factor: Multiplier for delay after each attempt.

        Returns:
            The coroutine's return value on success.

        Raises:
            The last exception if all attempts fail.
        """
        last_error: BaseException | None = None
        delay = base_delay
        for attempt in range(1, max_attempts + 1):
            try:
                return await coro()
            except BaseException as exc:  # noqa: BLE001
                last_error = exc
                if attempt < max_attempts:
                    await asyncio.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)
        if last_error is not None:
            raise last_error
        msg = "retry_with_backoff: all attempts failed without exception"
        raise RuntimeError(msg)

    # ── Rate Limit Detection ───────────────────────────────────────────────

    async def handle_rate_limit(
        self,
        response: httpx.Response,
        coro: Any,
    ) -> Any:
        """Detect rate limit (HTTP 429) and apply exponential backoff.

        Args:
            response: The HTTP response to inspect.
            coro: Async coroutine to retry.

        Returns:
            The coroutine's return value on success.

        Raises:
            The rate limit exception if non-retryable.
        """
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 60))
            await asyncio.sleep(retry_after)
            return await coro()
        return response

    # ── Stock Check Helpers ─────────────────────────────────────────────────

    async def stock_check_with_retry(
        self,
        sku: str,
        max_attempts: int = 2,
    ) -> StockStatus:
        """Check stock with retry on transient failures.

        Args:
            sku: Product SKU to check.
            max_attempts: Number of retry attempts.

        Returns:
            StockStatus for the given SKU.
        """
        last_error: BaseException | None = None
        delay = 0.5
        for attempt in range(1, max_attempts + 1):
            try:
                return await self.check_stock(sku)
            except BaseException as exc:  # noqa: BLE001
                last_error = exc
                if attempt < max_attempts:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2.0, 30.0)
        return StockStatus(in_stock=False, sku=sku)

    # ── Subclass Hooks ──────────────────────────────────────────────────────

    def get_retailer_config(self) -> Any:
        """Return the retailer-specific config block.

        Returns the config dict for this adapter's retailer,
        or None if not found.
        """
        return self.config.retailers.get(self.name)


# ── Re-export abstract interface for use by adapters ─────────────────────────

__all__ = ["RetailerAdapter"]
