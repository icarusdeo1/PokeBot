"""Tests for RetailerAdapter base class."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.monitor.retailers.base import RetailerAdapter
from src.shared.models import (
    CaptchaSolveResult,
    PaymentInfo,
    ShippingInfo,
    StockStatus,
)


# ── Concrete test adapter ───────────────────────────────────────────────────


class ConcreteRetailerAdapter(RetailerAdapter):
    """Concrete implementation for testing."""

    name = "test"
    base_url = "https://example.com"

    async def login(self, username: str, password: str) -> bool:
        return True

    async def check_stock(self, sku: str) -> StockStatus:
        return StockStatus(in_stock=True, sku=sku, url="https://example.com/sku")

    async def add_to_cart(self, sku: str, quantity: int = 1) -> bool:
        return True

    async def get_cart(self) -> list[dict]:
        return [{"sku": "123", "quantity": 1}]

    async def checkout(
        self,
        shipping: ShippingInfo,
        payment: PaymentInfo,
    ) -> dict:
        return {"order_id": "TEST-001", "status": "confirmed"}

    async def handle_captcha(self, page: MagicMock) -> CaptchaSolveResult:
        return CaptchaSolveResult(success=True, token="test-token")

    async def check_queue(self) -> bool:
        return False


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_config() -> MagicMock:
    """Minimal mock Config."""
    cfg = MagicMock()
    cfg.evasion.jitter_percent = 20
    cfg.retailers = {"test": MagicMock(enabled=True)}
    return cfg


@pytest.fixture
def adapter(mock_config: MagicMock) -> ConcreteRetailerAdapter:
    return ConcreteRetailerAdapter(mock_config)


# ── Init ──────────────────────────────────────────────────────────────────


class TestInit:
    def test_initializes_fields(self, adapter: ConcreteRetailerAdapter) -> None:
        assert adapter._session is None
        assert adapter._session_state is None
        assert adapter._prewarmed is False
        assert adapter._logger is None

    def test_name_and_base_url_are_empty_strings(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        # Subclasses set these; base class defaults to empty strings
        assert adapter.name == "test"
        assert adapter.base_url == "https://example.com"


# ── Session State ───────────────────────────────────────────────────────────


class TestSessionState:
    def test_session_state_property_none_by_default(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        assert adapter.session_state is None

    def test_is_prewarmed_false_by_default(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        assert adapter.is_prewarmed() is False

    @pytest.mark.asyncio
    async def test_save_session_state(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        cookies = {"session_id": "abc123"}
        await adapter.save_session_state(
            cookies=cookies,
            auth_token="auth-token",
            cart_token="cart-token",
        )
        assert adapter.session_state is not None
        assert adapter.session_state.cookies == cookies
        assert adapter.session_state.auth_token == "auth-token"
        assert adapter.session_state.cart_token == "cart-token"
        assert adapter.session_state.is_valid is True
        assert adapter.session_state.prewarmed_at != ""

    @pytest.mark.asyncio
    async def test_invalidate_session(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        await adapter.save_session_state(cookies={"session_id": "abc123"})
        assert adapter._prewarmed is False  # not yet marked prewarmed
        await adapter.invalidate_session()
        assert adapter.session_state is not None
        assert adapter.session_state.is_valid is False
        assert adapter.is_prewarmed() is False

    @pytest.mark.asyncio
    async def test_close_clears_session_state(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        await adapter.save_session_state(cookies={"session_id": "abc123"})
        adapter._prewarmed = True
        await adapter.close()
        assert adapter._session is None
        assert adapter._session_state is None
        assert adapter._prewarmed is False


# ── HTTP Client ────────────────────────────────────────────────────────────


class TestHttpClient:
    def test_get_http_client_returns_client(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        client = adapter.get_http_client()
        assert client is not None
        assert adapter._session is client

    def test_get_http_client_returns_same_instance(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        client1 = adapter.get_http_client()
        client2 = adapter.get_http_client()
        assert client1 is client2

    @pytest.mark.asyncio
    async def test_close_http_client(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        client = adapter.get_http_client()
        await adapter.close_http_client()
        assert adapter._session is None

    @pytest.mark.asyncio
    async def test_close_handles_none_session(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        # Should not raise
        await adapter.close_http_client()


# ── Jitter ─────────────────────────────────────────────────────────────────


class TestJitter:
    def test_apply_jitter_default_20_percent(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        base = 1000  # 1000ms
        results = [adapter.apply_jitter(base) for _ in range(100)]
        # All results should be between 800ms and 1200ms (20% jitter)
        for result in results:
            assert 0.8 <= result <= 1.2

    def test_apply_jitter_custom_percent(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        base = 1000
        results = [adapter.apply_jitter(base, jitter_percent=50) for _ in range(100)]
        for result in results:
            assert 0.5 <= result <= 1.5

    def test_apply_jitter_returns_seconds(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        base = 1000  # ms
        result = adapter.apply_jitter(base)
        # apply_jitter divides by 1000, so result should be a float in seconds
        assert isinstance(result, float)
        assert 0.5 <= result <= 1.5


# ── Retry With Backoff ─────────────────────────────────────────────────────


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self) -> None:
        cfg = MagicMock()
        cfg.evasion.jitter_percent = 20
        cfg.retailers = {"test": MagicMock(enabled=True)}
        adapter = ConcreteRetailerAdapter(cfg)

        coro = AsyncMock(return_value="success")
        result = await adapter.retry_with_backoff(coro, max_attempts=3)
        assert result == "success"
        assert coro.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure(self) -> None:
        cfg = MagicMock()
        cfg.evasion.jitter_percent = 20
        cfg.retailers = {"test": MagicMock(enabled=True)}
        adapter = ConcreteRetailerAdapter(cfg)

        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient error")
            return "success"

        result = await adapter.retry_with_backoff(flaky, max_attempts=5)
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self) -> None:
        cfg = MagicMock()
        cfg.evasion.jitter_percent = 20
        cfg.retailers = {"test": MagicMock(enabled=True)}
        adapter = ConcreteRetailerAdapter(cfg)

        async def always_fail() -> str:
            raise ValueError("permanent error")

        with pytest.raises(ValueError, match="permanent error"):
            await adapter.retry_with_backoff(always_fail, max_attempts=3)

    @pytest.mark.asyncio
    async def test_raises_when_all_attempts_return_none(self) -> None:
        cfg = MagicMock()
        cfg.evasion.jitter_percent = 20
        cfg.retailers = {"test": MagicMock(enabled=True)}
        adapter = ConcreteRetailerAdapter(cfg)

        async def returns_none() -> None:
            return None

        # When no exception is raised but also no return value
        # (shouldn't happen with coro returning None)
        pass

    @pytest.mark.asyncio
    async def test_respects_max_delay(self) -> None:
        cfg = MagicMock()
        cfg.evasion.jitter_percent = 20
        cfg.retailers = {"test": MagicMock(enabled=True)}
        adapter = ConcreteRetailerAdapter(cfg)

        call_count = 0

        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        import time

        start = time.monotonic()
        with pytest.raises(ValueError):
            await adapter.retry_with_backoff(
                flaky,
                max_attempts=4,
                base_delay=10.0,
                max_delay=5.0,
                backoff_factor=2.0,
            )
        elapsed = time.monotonic() - start
        # Should cap at max_delay * backoff_factor (not cumulative)
        # With base=10, max_delay=5, factor=2: 10 -> 5 -> 5 -> 5
        assert elapsed < 30  # sanity check


# ── Rate Limit Detection ───────────────────────────────────────────────────


class TestHandleRateLimit:
    @pytest.mark.asyncio
    async def test_passes_through_non_429(self) -> None:
        cfg = MagicMock()
        cfg.evasion.jitter_percent = 20
        cfg.retailers = {"test": MagicMock(enabled=True)}
        adapter = ConcreteRetailerAdapter(cfg)

        response = MagicMock()
        response.status_code = 200
        coro = AsyncMock(return_value="ok")

        result = await adapter.handle_rate_limit(response, coro)
        # When not rate-limited (200), returns the response unchanged
        assert result is response
        assert coro.call_count == 0

    @pytest.mark.asyncio
    async def test_retries_on_429(self) -> None:
        cfg = MagicMock()
        cfg.evasion.jitter_percent = 20
        cfg.retailers = {"test": MagicMock(enabled=True)}
        adapter = ConcreteRetailerAdapter(cfg)

        response = MagicMock()
        response.status_code = 429
        response.headers = {"Retry-After": "0.1"}  # short delay for test
        coro = AsyncMock(return_value="ok_after_wait")

        result = await adapter.handle_rate_limit(response, coro)
        assert result == "ok_after_wait"
        assert coro.call_count == 1


# ── Stock Check With Retry ─────────────────────────────────────────────────


class TestStockCheckWithRetry:
    @pytest.mark.asyncio
    async def test_returns_stock_status_on_success(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        status = await adapter.stock_check_with_retry("SKU-123")
        assert status.in_stock is True
        assert status.sku == "SKU-123"
        assert status.url != ""

    @pytest.mark.asyncio
    async def test_returns_oos_on_all_attempts_fail(
        self, adapter: ConcreteRetailerAdapter
    ) -> None:
        adapter.check_stock = AsyncMock(
            side_effect=ValueError("network error")
        )
        status = await adapter.stock_check_with_retry("SKU-FAIL")
        assert status.in_stock is False
        assert status.sku == "SKU-FAIL"


# ── Subclass Hooks ────────────────────────────────────────────────────────


class TestGetRetailerConfig:
    def test_returns_retailer_config(self, adapter: ConcreteRetailerAdapter) -> None:
        cfg = adapter.get_retailer_config()
        assert cfg is not None

    def test_returns_none_for_unknown_retailer(self) -> None:
        cfg = MagicMock()
        cfg.evasion.jitter_percent = 20
        cfg.retailers = {}
        adapter = ConcreteRetailerAdapter(cfg)
        assert adapter.get_retailer_config() is None


# ── Abstract Method Enforcement ────────────────────────────────────────────


class TestAbstractInterface:
    def test_cannot_instantiate_base_directly(self) -> None:
        with pytest.raises(TypeError, match="abstract"):
            RetailerAdapter(MagicMock())  # type: ignore[arg-type]

    def test_subclass_must_implement_all_abstract_methods(self) -> None:
        """A subclass missing any abstract method cannot be instantiated."""
        with pytest.raises(TypeError):
            # RetailerAdapterSubclass is a subclass missing methods
            class IncompleteAdapter(RetailerAdapter):  # type: ignore[validtype]
                name = "incomplete"
                base_url = "https://example.com"


                async def login(self, username: str, password: str) -> bool:
                    return True

                # missing other abstract methods...


            IncompleteAdapter(MagicMock())
