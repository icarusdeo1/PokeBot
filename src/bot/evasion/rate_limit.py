"""IP rate limit detection and backoff for retailer HTTP requests.

Per PRD Section 9.5 (EV-5).

Detects HTTP 429 responses from retailers, applies exponential backoff retry,
and logs rate limit events. Designed to be used by retailer adapters and
any module making HTTP requests to retailer endpoints.
"""

from __future__ import annotations

import asyncio
import random
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Coroutine, Optional, TypeVar, Union

import httpx

from src.bot.logger import Logger

T = TypeVar("T")


def is_rate_limited(response: httpx.Response) -> bool:
    """Return True if the response indicates a rate limit (HTTP 429).

    Args:
        response: An httpx.Response object.

    Returns:
        True if status code is 429, False otherwise.
    """
    return response.status_code == 429


def get_retry_after_seconds(response: httpx.Response) -> Optional[float]:
    """Extract Retry-After seconds from a 429 response.

    Supports both:
    - Integer seconds: Retry-After: 30
    - HTTP date: Retry-After: Sat, 01 Jan 2026 00:00:00 GMT

    Args:
        response: An httpx.Response with 429 status.

    Returns:
        Retry-After in seconds as a float, or None if absent/invalid.
    """
    retry_after = response.headers.get("Retry-After")
    if not retry_after:
        return None

    # Try as integer seconds first
    try:
        seconds_val: float = float(retry_after)
        return seconds_val
    except ValueError:
        pass

    # Try as HTTP-date (RFC 7231)
    try:
        dt = parsedate_to_datetime(retry_after)
        if dt is None:
            return None
        loop_time: float = 0.0
        try:
            loop_time = asyncio.get_running_loop().time()
        except RuntimeError:
            pass
        ts: float = dt.timestamp()
        delta = ts - loop_time
        return max(delta, 0.0)
    except Exception:
        return None


def calculate_backoff(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter_percent: float = 15.0,
) -> float:
    """Calculate exponential backoff delay for a given attempt.

    Args:
        attempt: Zero-indexed retry attempt number.
        base_delay: Initial delay in seconds (default 1.0).
        max_delay: Maximum delay cap in seconds (default 60.0).
        jitter_percent: Random jitter ±N% (default 15%).

    Returns:
        Delay in seconds to wait before retry.
    """
    exp_delay = base_delay * (2 ** attempt)
    capped_delay = min(exp_delay, max_delay)
    jitter_range = capped_delay * (jitter_percent / 100.0)
    jitter_value: float = random.uniform(-jitter_range, jitter_range)
    result: float = capped_delay + jitter_value
    if result < 0.0:
        return 0.0
    return result


class RateLimitHandler:
    """Handles HTTP 429 rate limit detection and exponential backoff retry.

    Applies exponential backoff on HTTP 429 responses. Supports:
    - Retry-After header extraction (integer or HTTP-date)
    - Exponential backoff with jitter
    - Configurable max retries, base delay, and max delay
    - Logging of all rate limit events

    Per PRD Section 9.5 (EV-5).
    """

    def __init__(
        self,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter_percent: float = 15.0,
        logger: Logger | None = None,
    ) -> None:
        """Initialize the rate limit handler.

        Args:
            max_retries: Maximum retry attempts after rate limit (default 5).
            base_delay: Initial backoff delay in seconds (default 1.0).
            max_delay: Maximum backoff delay cap in seconds (default 60.0).
            jitter_percent: Random jitter ±N% added to delay (default 15%).
            logger: Optional Logger instance. If None, uses Logger.get_instance().
        """
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._jitter_percent = jitter_percent
        self._logger = logger

    @property
    def _log(self) -> Logger:
        """Return the logger instance (uses global singleton if not set)."""
        if self._logger is not None:
            return self._logger
        return Logger.get_instance()

    async def _sleep(self, seconds: float) -> None:
        """Sleep for the given number of seconds (async).

        Args:
            seconds: Number of seconds to sleep.
        """
        if seconds <= 0:
            return
        await asyncio.sleep(seconds)

    async def handle_and_retry(
        self,
        coro: Callable[[], Coroutine[Any, Any, httpx.Response]],
    ) -> httpx.Response:
        """Execute an HTTP coroutine with rate limit handling and retry.

        On HTTP 429, waits Retry-After (or exponential backoff) and retries.
        Logs each rate limit event. Raises after exhausting retries.

        Args:
            coro: An async callable that returns an httpx.Response.

        Returns:
            The successful httpx.Response.

        Raises:
            httpx.HTTPStatusError: If the final attempt gets a non-429 error.
            httpx.ReadTimeout: On timeout after retries exhausted.
        """
        attempt = 0

        while True:
            response = await coro()

            if not is_rate_limited(response):
                return response

            if attempt >= self._max_retries:
                self._log.warning(
                    "rate_limit_exhausted",
                    attempt=attempt,
                    max_retries=self._max_retries,
                    status_code=429,
                )
                response.raise_for_status()
                return response

            retry_after = get_retry_after_seconds(response)
            if retry_after is not None and retry_after > 0:
                wait_time = retry_after
                source = "retry-after"
            else:
                wait_time = calculate_backoff(
                    attempt,
                    base_delay=self._base_delay,
                    max_delay=self._max_delay,
                    jitter_percent=self._jitter_percent,
                )
                source = "backoff"

            self._log.warning(
                "rate_limit_detected",
                attempt=attempt + 1,
                max_retries=self._max_retries,
                wait_seconds=round(wait_time, 2),
                wait_source=source,
                retry_after_header=response.headers.get("Retry-After"),
                status_code=429,
            )

            await self._sleep(wait_time)
            attempt += 1

    def wrap_with_retries(
        self,
        func: Callable[..., Coroutine[Any, Any, httpx.Response]],
    ) -> Callable[..., Coroutine[Any, Any, httpx.Response]]:
        """Wrap an async HTTP function with rate limit retry logic.

        Args:
            func: An async function that takes arbitrary args/kwargs and
                returns an httpx.Response.

        Returns:
            A wrapped function with the same signature that auto-retries on 429.
        """
        handler = self

        async def wrapped(*args: Any, **kwargs: Any) -> httpx.Response:
            async def make_request() -> httpx.Response:
                return await func(*args, **kwargs)

            return await handler.handle_and_retry(make_request)

        return wrapped


__all__ = [
    "RateLimitHandler",
    "is_rate_limited",
    "get_retry_after_seconds",
    "calculate_backoff",
]
