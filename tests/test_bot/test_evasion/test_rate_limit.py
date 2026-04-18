"""Tests for bot/evasion/rate_limit.py (EVASION-T05)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.evasion.rate_limit import (
    RateLimitHandler,
    calculate_backoff,
    get_retry_after_seconds,
    is_rate_limited,
)
import httpx
from httpx import HTTPStatusError


class TestIsRateLimited:
    """Tests for is_rate_limited()."""

    def test_429_returns_true(self) -> None:
        response = MagicMock(spec=httpx.Response)
        response.status_code = 429
        assert is_rate_limited(response) is True

    def test_200_returns_false(self) -> None:
        response = MagicMock(spec=httpx.Response)
        response.status_code = 200
        assert is_rate_limited(response) is False

    def test_500_returns_false(self) -> None:
        response = MagicMock(spec=httpx.Response)
        response.status_code = 500
        assert is_rate_limited(response) is False

    def test_404_returns_false(self) -> None:
        response = MagicMock(spec=httpx.Response)
        response.status_code = 404
        assert is_rate_limited(response) is False


class TestGetRetryAfterSeconds:
    """Tests for get_retry_after_seconds()."""

    def test_integer_retry_after(self) -> None:
        response = MagicMock(spec=httpx.Response)
        response.headers = {"Retry-After": "30"}
        assert get_retry_after_seconds(response) == 30.0

    def test_float_retry_after(self) -> None:
        response = MagicMock(spec=httpx.Response)
        response.headers = {"Retry-After": "1.5"}
        assert get_retry_after_seconds(response) == 1.5

    def test_http_date_retry_after(self) -> None:
        # Fixed date in the future
        response = MagicMock(spec=httpx.Response)
        response.headers = {"Retry-After": "Sat, 01 Jan 2027 00:00:00 GMT"}
        result = get_retry_after_seconds(response)
        assert result is not None
        assert result > 0

    def test_missing_retry_after(self) -> None:
        response = MagicMock(spec=httpx.Response)
        response.headers = {}
        assert get_retry_after_seconds(response) is None

    def test_invalid_retry_after(self) -> None:
        response = MagicMock(spec=httpx.Response)
        response.headers = {"Retry-After": "not-a-number"}
        assert get_retry_after_seconds(response) is None


class TestCalculateBackoff:
    """Tests for calculate_backoff()."""

    def test_exponential_growth(self) -> None:
        # First attempt (attempt=0): base_delay * 2^0 = base_delay
        delay0 = calculate_backoff(0, base_delay=1.0, max_delay=60.0, jitter_percent=0.0)
        assert delay0 == 1.0

        # Second attempt (attempt=1): base_delay * 2^1 = 2 * base_delay
        delay1 = calculate_backoff(1, base_delay=1.0, max_delay=60.0, jitter_percent=0.0)
        assert delay1 == 2.0

        # Third attempt (attempt=2): base_delay * 2^2 = 4 * base_delay
        delay2 = calculate_backoff(2, base_delay=1.0, max_delay=60.0, jitter_percent=0.0)
        assert delay2 == 4.0

    def test_max_delay_cap(self) -> None:
        # Very high attempt would exceed max_delay
        delay = calculate_backoff(10, base_delay=1.0, max_delay=5.0, jitter_percent=0.0)
        assert delay == 5.0

    def test_jitter_with_zero_percent(self) -> None:
        # Zero jitter: delay for attempt=1 should be base_delay * 2^1 = 4.0
        delay = calculate_backoff(1, base_delay=2.0, max_delay=60.0, jitter_percent=0.0)
        assert abs(delay - 4.0) < 0.001

    def test_jitter_range(self) -> None:
        # With jitter_percent=10 and base_delay=1.0, jitter_range = 0.1
        # So delays should vary within [0.9, 1.1]
        delays = [calculate_backoff(0, base_delay=1.0, max_delay=60.0, jitter_percent=10.0) for _ in range(100)]
        assert all(0.9 <= d <= 1.1 for d in delays)
        # Should have some variation (not all the same)
        assert max(delays) != min(delays)

    def test_never_negative(self) -> None:
        # Even with extreme jitter, delay should never be negative
        for attempt in range(5):
            for _ in range(50):
                delay = calculate_backoff(attempt, base_delay=0.1, max_delay=1.0, jitter_percent=50.0)
                assert delay >= 0.0


class TestRateLimitHandler:
    """Tests for RateLimitHandler class."""

    def test_initial_state(self) -> None:
        handler = RateLimitHandler()
        assert handler._max_retries == 5
        assert handler._base_delay == 1.0
        assert handler._max_delay == 60.0
        assert handler._jitter_percent == 15.0

    def test_custom_config(self) -> None:
        handler = RateLimitHandler(max_retries=3, base_delay=2.0, max_delay=30.0, jitter_percent=20.0)
        assert handler._max_retries == 3
        assert handler._base_delay == 2.0
        assert handler._max_delay == 30.0
        assert handler._jitter_percent == 20.0

    @pytest.mark.asyncio
    async def test_non_429_passes_through(self) -> None:
        handler = RateLimitHandler(max_retries=3)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200

        called_count = 0

        async def make_request() -> httpx.Response:
            nonlocal called_count
            called_count += 1
            return mock_response

        result = await handler.handle_and_retry(make_request)
        assert result.status_code == 200
        assert called_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_429(self) -> None:
        mock_logger = MagicMock()
        handler = RateLimitHandler(max_retries=3, base_delay=0.001, jitter_percent=0.0, logger=mock_logger)

        response_429 = MagicMock(spec=httpx.Response)
        response_429.status_code = 429
        response_429.headers = {}
        response_429.raise_for_status.side_effect = httpx.HTTPStatusError(
            "rate limited", request=MagicMock(), response=response_429
        )

        response_200 = MagicMock(spec=httpx.Response)
        response_200.status_code = 200

        called_count = 0

        async def make_request() -> httpx.Response:
            nonlocal called_count
            called_count += 1
            if called_count <= 3:
                return response_429
            return response_200

        result = await handler.handle_and_retry(make_request)
        assert result.status_code == 200
        assert called_count == 4  # 3 failures + 1 success

    @pytest.mark.asyncio
    async def test_exhausts_retries_and_raises(self) -> None:
        mock_logger = MagicMock()
        handler = RateLimitHandler(max_retries=2, base_delay=0.001, jitter_percent=0.0, logger=mock_logger)

        response_429 = MagicMock(spec=httpx.Response)
        response_429.status_code = 429
        response_429.headers = {}
        # Make raise_for_status raise HTTPStatusError
        response_429.raise_for_status.side_effect = httpx.HTTPStatusError(
            "rate limited", request=MagicMock(), response=response_429
        )

        async def make_request() -> httpx.Response:
            return response_429

        with pytest.raises(httpx.HTTPStatusError):
            await handler.handle_and_retry(make_request)

    @pytest.mark.asyncio
    async def test_respects_retry_after_header(self) -> None:
        mock_logger = MagicMock()
        handler = RateLimitHandler(max_retries=2, base_delay=10.0, logger=mock_logger)

        response_429_retry = MagicMock(spec=httpx.Response)
        response_429_retry.status_code = 429
        response_429_retry.headers = {"Retry-After": "0.05"}  # 50ms

        response_200 = MagicMock(spec=httpx.Response)
        response_200.status_code = 200

        called_count = 0

        async def make_request() -> httpx.Response:
            nonlocal called_count
            called_count += 1
            if called_count == 1:
                return response_429_retry
            return response_200

        result = await handler.handle_and_retry(make_request)
        assert result.status_code == 200
        assert called_count == 2


class TestWrapWithRetries:
    """Tests for RateLimitHandler.wrap_with_retries()."""

    @pytest.mark.asyncio
    async def test_wraps_async_function(self) -> None:
        mock_logger = MagicMock()
        handler = RateLimitHandler(max_retries=3, base_delay=0.001, jitter_percent=0.0, logger=mock_logger)

        response_429 = MagicMock(spec=httpx.Response)
        response_429.status_code = 429
        response_429.headers = {}

        response_200 = MagicMock(spec=httpx.Response)
        response_200.status_code = 200

        call_count = 0

        async def my_request() -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return response_429
            return response_200

        wrapped = handler.wrap_with_retries(my_request)
        result = await wrapped()
        assert result.status_code == 200
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_passes_arguments_through(self) -> None:
        mock_logger = MagicMock()
        handler = RateLimitHandler(max_retries=3, base_delay=0.001, jitter_percent=0.0, logger=mock_logger)

        response_200 = MagicMock(spec=httpx.Response)
        response_200.status_code = 200

        received_args: tuple[Any, ...] = ()
        received_kwargs: dict[str, Any] = {}

        async def my_request(a: int, b: str, c: bool = False) -> httpx.Response:
            nonlocal received_args, received_kwargs
            received_args = (a, b)
            received_kwargs = {"c": c}
            return response_200

        wrapped = handler.wrap_with_retries(my_request)
        result = await wrapped(42, "hello", c=True)
        assert received_args == (42, "hello")
        assert received_kwargs == {"c": True}
        assert result.status_code == 200
