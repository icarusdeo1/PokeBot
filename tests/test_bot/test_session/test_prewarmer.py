"""Tests for src.bot.session.prewarmer."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.session.prewarmer import (
    PREWARM_SESSION_TTL_HOURS,
    PrewarmResult,
    PrewarmSession,
    SessionCache,
    SessionPrewarmer,
    _parse_datetime,
)


# ─── PrewarmResult ──────────────────────────────────────────────────────────

class TestPrewarmResult:
    def test_creation_success(self) -> None:
        result = PrewarmResult(
            retailer="target",
            account_name="primary",
            success=True,
            prewarmed_at="2026-04-18T12:00:00Z",
            cookies_count=5,
        )
        assert result.success is True
        assert result.retailer == "target"
        assert result.account_name == "primary"
        assert result.prewarmed_at == "2026-04-18T12:00:00Z"
        assert result.cookies_count == 5
        assert result.error == ""

    def test_creation_failure(self) -> None:
        result = PrewarmResult(
            retailer="walmart",
            account_name="secondary",
            success=False,
            error="Login failed",
        )
        assert result.success is False
        assert result.error == "Login failed"

    def test_defaults(self) -> None:
        result = PrewarmResult(retailer="walmart", account_name="acc", success=True)
        assert result.prewarmed_at == ""
        assert result.error == ""
        assert result.cookies_count == 0


# ─── PrewarmSession ─────────────────────────────────────────────────────────

class TestPrewarmSession:
    def test_is_expired_false(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        session = PrewarmSession(
            retailer="target",
            account_name="primary",
            cookies={},
            auth_token="token",
            cart_token="ct",
            prewarmed_at=datetime.now(timezone.utc).isoformat(),
            expires_at=future.isoformat(),
            adapter_name="TargetAdapter",
        )
        assert session.is_expired is False

    def test_is_expired_true(self) -> None:
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        session = PrewarmSession(
            retailer="target",
            account_name="primary",
            cookies={},
            auth_token="token",
            cart_token="ct",
            prewarmed_at=past.isoformat(),
            expires_at=past.isoformat(),
            adapter_name="TargetAdapter",
        )
        assert session.is_expired is True

    def test_is_expired_with_z_suffixed_timestamp(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        session = PrewarmSession(
            retailer="target",
            account_name="primary",
            cookies={},
            auth_token="token",
            cart_token="ct",
            prewarmed_at=datetime.now(timezone.utc).isoformat(),
            expires_at=future.isoformat().replace("+00:00", "Z"),
            adapter_name="TargetAdapter",
        )
        assert session.is_expired is False


# ─── SessionCache ────────────────────────────────────────────────────────────

class TestSessionCache:
    def test_set_and_get(self) -> None:
        cache = SessionCache()
        session = _make_session(retailer="target", account_name="primary")
        cache.set("target", "primary", session)
        retrieved = cache.get("target", "primary")
        assert retrieved is not None
        assert retrieved.retailer == "target"
        assert retrieved.account_name == "primary"

    def test_get_missing_retailer(self) -> None:
        cache = SessionCache()
        assert cache.get("nonexistent", "primary") is None

    def test_get_missing_account(self) -> None:
        cache = SessionCache()
        cache.set("target", "primary", _make_session("target", "primary"))
        assert cache.get("target", "nonexistent") is None

    def test_invalidate(self) -> None:
        cache = SessionCache()
        cache.set("target", "primary", _make_session("target", "primary"))
        cache.invalidate("target", "primary")
        assert cache.get("target", "primary") is None

    def test_invalidate_missing_is_noop(self) -> None:
        cache = SessionCache()
        cache.invalidate("nonexistent", "nonexistent")  # no raise

    def test_get_valid_returns_none_when_missing(self) -> None:
        cache = SessionCache()
        assert cache.get_valid("target", "primary") is None

    def test_get_valid_returns_none_when_expired(self) -> None:
        cache = SessionCache()
        expired = _make_session("target", "primary", expired=True)
        cache.set("target", "primary", expired)
        assert cache.get_valid("target", "primary") is None

    def test_get_valid_returns_session_when_valid(self) -> None:
        cache = SessionCache()
        session = _make_session("target", "primary")
        cache.set("target", "primary", session)
        retrieved = cache.get_valid("target", "primary")
        assert retrieved is not None
        assert retrieved.account_name == "primary"

    def test_get_all_valid(self) -> None:
        cache = SessionCache()
        cache.set("target", "primary", _make_session("target", "primary"))
        cache.set("target", "secondary", _make_session("target", "secondary"))
        cache.set("walmart", "primary", _make_session("walmart", "primary"))
        valid = cache.get_all_valid("target")
        assert len(valid) == 2

    def test_get_all_valid_filters_expired(self) -> None:
        cache = SessionCache()
        cache.set("target", "valid", _make_session("target", "valid"))
        cache.set("target", "expired", _make_session("target", "expired", expired=True))
        valid = cache.get_all_valid("target")
        assert len(valid) == 1
        assert valid[0].account_name == "valid"

    def test_clear(self) -> None:
        cache = SessionCache()
        cache.set("target", "primary", _make_session("target", "primary"))
        cache.set("walmart", "primary", _make_session("walmart", "primary"))
        cache.clear()
        assert cache.get("target", "primary") is None
        assert cache.get("walmart", "primary") is None


# ─── _parse_datetime ─────────────────────────────────────────────────────────

class TestParseDatetime:
    def test_iso8601_with_z_suffix(self) -> None:
        result = _parse_datetime("2026-04-18T12:00:00Z")
        assert result is not None
        assert result.tzinfo is not None

    def test_iso8601_with_offset(self) -> None:
        result = _parse_datetime("2026-04-18T12:00:00+00:00")
        assert result is not None

    def test_naive_iso8601(self) -> None:
        result = _parse_datetime("2026-04-18T12:00:00")
        assert result is not None
        # Naive datetimes are treated as UTC (per PHASE3-T01 spec)
        assert result.tzinfo is not None

    def test_empty_string(self) -> None:
        assert _parse_datetime("") is None

    def test_invalid_format(self) -> None:
        assert _parse_datetime("not-a-date") is None

    def test_future_iso8601(self) -> None:
        result = _parse_datetime("2027-01-01T00:00:00Z")
        assert result is not None
        assert result.year == 2027


# ─── SessionPrewarmer — unit ─────────────────────────────────────────────────

class TestSessionPrewarmerInit:
    def test_init(self) -> None:
        mock_config = MagicMock()
        prewarmer = SessionPrewarmer(mock_config)
        assert prewarmer.config is mock_config
        assert prewarmer.logger is None
        assert prewarmer._running is False
        assert prewarmer._task is None


class TestSessionPrewarmerStatus:
    def test_get_status_empty(self) -> None:
        mock_config = MagicMock()
        prewarmer = SessionPrewarmer(mock_config)
        assert prewarmer.get_status() == {}

    def test_get_status_with_sessions(self) -> None:
        mock_config = MagicMock()
        prewarmer = SessionPrewarmer(mock_config)
        session = _make_session("target", "primary")
        prewarmer._cache.set("target", "primary", session)
        status = prewarmer.get_status()
        assert "target" in status
        assert len(status["target"]) == 1
        assert status["target"][0]["account_name"] == "primary"
        assert status["target"][0]["cookies_count"] == len(session.cookies)


class TestSessionPrewarmerInvalidation:
    def test_invalidate_session(self) -> None:
        mock_config = MagicMock()
        prewarmer = SessionPrewarmer(mock_config)
        session = _make_session("target", "primary")
        prewarmer._cache.set("target", "primary", session)
        assert prewarmer.get_valid_session("target", "primary") is not None
        prewarmer.invalidate_session("target", "primary")
        assert prewarmer.get_valid_session("target", "primary") is None


class TestSessionPrewarmerGetValidSession:
    def test_returns_none_when_no_session(self) -> None:
        mock_config = MagicMock()
        prewarmer = SessionPrewarmer(mock_config)
        assert prewarmer.get_valid_session("target", "primary") is None

    def test_returns_none_when_expired(self) -> None:
        mock_config = MagicMock()
        prewarmer = SessionPrewarmer(mock_config)
        expired = _make_session("target", "primary", expired=True)
        prewarmer._cache.set("target", "primary", expired)
        assert prewarmer.get_valid_session("target", "primary") is None

    def test_returns_session_when_valid(self) -> None:
        mock_config = MagicMock()
        prewarmer = SessionPrewarmer(mock_config)
        session = _make_session("target", "primary")
        prewarmer._cache.set("target", "primary", session)
        result = prewarmer.get_valid_session("target", "primary")
        assert result is not None
        assert result.account_name == "primary"


# ─── SessionPrewarmer — prewarm_now ──────────────────────────────────────────

@pytest.mark.asyncio
class TestPrewarmNow:
    async def test_prewarm_now_missing_retailer_config(self) -> None:
        mock_config = MagicMock()
        mock_config.retailers.get.return_value = None
        prewarmer = SessionPrewarmer(mock_config)

        mock_adapter = MagicMock()
        mock_adapter.name = "unknown_retailer"
        mock_adapter.close = AsyncMock()

        result = await prewarmer.prewarm_now(mock_adapter, "primary")
        assert result.success is False
        assert "No retailer config found" in result.error

    async def test_prewarm_now_missing_credentials(self) -> None:
        mock_config = MagicMock()
        mock_retailer_cfg = MagicMock()
        mock_retailer_cfg.username = ""
        mock_retailer_cfg.password = ""
        mock_config.retailers.get.return_value = mock_retailer_cfg
        prewarmer = SessionPrewarmer(mock_config)

        mock_adapter = MagicMock()
        mock_adapter.name = "target"
        mock_adapter.close = AsyncMock()

        result = await prewarmer.prewarm_now(mock_adapter, "primary")
        assert result.success is False
        assert "Missing credentials" in result.error

    async def test_prewarm_now_login_failure(self) -> None:
        mock_config = MagicMock()
        mock_retailer_cfg = MagicMock()
        mock_retailer_cfg.username = "user"
        mock_retailer_cfg.password = "pass"
        mock_config.retailers.get.return_value = mock_retailer_cfg
        prewarmer = SessionPrewarmer(mock_config)

        mock_adapter = MagicMock()
        mock_adapter.name = "target"
        mock_adapter.login = AsyncMock(return_value=False)
        mock_adapter.session_state = None
        mock_adapter.close = AsyncMock()

        result = await prewarmer.prewarm_now(mock_adapter, "primary")
        assert result.success is False
        assert "Login failed" in result.error

    async def test_prewarm_now_no_session_state(self) -> None:
        mock_config = MagicMock()
        mock_retailer_cfg = MagicMock()
        mock_retailer_cfg.username = "user"
        mock_retailer_cfg.password = "pass"
        mock_config.retailers.get.return_value = mock_retailer_cfg
        prewarmer = SessionPrewarmer(mock_config)

        mock_adapter = MagicMock()
        mock_adapter.name = "target"
        mock_adapter.login = AsyncMock(return_value=True)
        mock_adapter.session_state = None
        mock_adapter.close = AsyncMock()

        result = await prewarmer.prewarm_now(mock_adapter, "primary")
        assert result.success is False
        assert "No session state after login" in result.error

    async def test_prewarm_now_success(self) -> None:
        mock_config = MagicMock()
        mock_retailer_cfg = MagicMock()
        mock_retailer_cfg.username = "user"
        mock_retailer_cfg.password = "pass"
        mock_config.retailers.get.return_value = mock_retailer_cfg
        prewarmer = SessionPrewarmer(mock_config)

        mock_session_state = MagicMock()
        mock_session_state.cookies = {"session_id": "abc123"}
        mock_session_state.auth_token = "auth_token_123"
        mock_session_state.cart_token = "cart_token_456"

        mock_adapter = MagicMock()
        mock_adapter.name = "target"
        mock_adapter.login = AsyncMock(return_value=True)
        mock_adapter.session_state = mock_session_state
        mock_adapter.close = AsyncMock()

        result = await prewarmer.prewarm_now(mock_adapter, "primary")
        assert result.success is True
        assert result.cookies_count == 1
        assert result.prewarmed_at != ""

        # Verify session cached
        cached = prewarmer.get_valid_session("target", "primary")
        assert cached is not None
        assert cached.cookies["session_id"] == "abc123"
        assert cached.auth_token == "auth_token_123"


# ─── SessionPrewarmer — start/stop ──────────────────────────────────────────

@pytest.mark.asyncio
class TestPrewarmerStartStop:
    async def test_start_is_idempotent(self) -> None:
        mock_config = MagicMock()
        prewarmer = SessionPrewarmer(mock_config)
        await prewarmer.start()
        assert prewarmer._running is True
        await prewarmer.start()  # no raise
        await prewarmer.stop()

    async def test_stop_after_start(self) -> None:
        mock_config = MagicMock()
        prewarmer = SessionPrewarmer(mock_config)
        await prewarmer.start()
        assert prewarmer._running is True
        await prewarmer.stop()
        assert prewarmer._running is False
        assert prewarmer._task is None

    async def test_stop_without_start(self) -> None:
        mock_config = MagicMock()
        prewarmer = SessionPrewarmer(mock_config)
        await prewarmer.stop()  # no raise


# ─── SessionPrewarmer — scheduler ────────────────────────────────────────────

@pytest.mark.asyncio
class TestPrewarmerScheduler:
    async def test_check_and_prewarm_no_drop_windows(self) -> None:
        mock_config = MagicMock()
        mock_config.drop_windows = []
        mock_config.get_enabled_retailers.return_value = ["target"]
        prewarmer = SessionPrewarmer(mock_config)

        # Should not raise
        await prewarmer._check_and_prewarm()

    async def test_check_and_prewarm_disabled_window_skipped(self) -> None:
        mock_dw = MagicMock()
        mock_dw.enabled = False
        mock_dw.id = "dw1"

        mock_config = MagicMock()
        mock_config.drop_windows = [mock_dw]
        mock_config.get_enabled_retailers.return_value = ["target"]
        prewarmer = SessionPrewarmer(mock_config)

        await prewarmer._check_and_prewarm()  # no raise

    async def test_check_and_prewarm_window_too_far_in_future(self) -> None:
        future_dt = datetime.now(timezone.utc) + timedelta(hours=5)
        mock_dw = MagicMock()
        mock_dw.enabled = True
        mock_dw.id = "dw1"
        mock_dw.item = "Test Item"
        mock_dw.retailer = "target"
        mock_dw.drop_datetime = future_dt.isoformat()
        mock_dw.prewarm_minutes = 10

        mock_config = MagicMock()
        mock_config.drop_windows = [mock_dw]
        mock_config.get_enabled_retailers.return_value = ["target"]
        prewarmer = SessionPrewarmer(mock_config)

        # Should not trigger pre-warm (5 hours > 10 minutes)
        await prewarmer._check_and_prewarm()
        # No session should be cached for this drop window
        assert prewarmer.get_valid_session("target", f"drop_{mock_dw.id}") is None

    async def test_check_and_prewarm_triggers_prewarm(self) -> None:
        # Drop window is 5 minutes away (within prewarm window)
        soon_dt = datetime.now(timezone.utc) + timedelta(minutes=5)
        mock_dw = MagicMock()
        mock_dw.enabled = True
        mock_dw.id = "dw1"
        mock_dw.item = "Test Item"
        mock_dw.retailer = "target"
        mock_dw.drop_datetime = soon_dt.isoformat()
        mock_dw.prewarm_minutes = 10

        mock_retailer_cfg = MagicMock()
        mock_retailer_cfg.username = "user"
        mock_retailer_cfg.password = "pass"

        mock_config = MagicMock()
        mock_config.drop_windows = [mock_dw]
        mock_config.get_enabled_retailers.return_value = ["target"]
        mock_config.retailers = {"target": mock_retailer_cfg}

        prewarmer = SessionPrewarmer(mock_config)

        # Mock get_default_registry where it's imported (inside the function)
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.name = "target"
        mock_adapter_instance.login = AsyncMock(return_value=True)
        mock_adapter_instance.session_state = MagicMock(
            cookies={"session_id": "abc"},
            auth_token="auth",
            cart_token="cart",
        )
        mock_adapter_instance.close = AsyncMock()

        mock_adapter_cls = MagicMock(return_value=mock_adapter_instance)

        with patch("src.bot.monitor.retailers.get_default_registry") as mock_registry_fn:
            mock_registry = MagicMock()
            mock_registry.get.return_value = mock_adapter_cls
            mock_registry_fn.return_value = mock_registry

            await prewarmer._check_and_prewarm()
            # Should have attempted to prewarm
            mock_adapter_instance.login.assert_called_once()


# ─── prewarm_all_accounts ────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestPrewarmAllAccounts:
    async def test_returns_results_for_each_account(self) -> None:
        mock_config = MagicMock()
        prewarmer = SessionPrewarmer(mock_config)

        mock_retailer_cfg = MagicMock()
        mock_retailer_cfg.username = "user"
        mock_retailer_cfg.password = "pass"
        mock_config.retailers.get.return_value = mock_retailer_cfg

        mock_adapter = MagicMock()
        mock_adapter.name = "target"
        mock_adapter.login = AsyncMock(return_value=False)
        mock_adapter.session_state = None
        mock_adapter.close = AsyncMock()

        results = await prewarmer.prewarm_all_accounts(mock_adapter)
        assert len(results) >= 1
        assert results[0].retailer == "target"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_session(
    retailer: str = "target",
    account_name: str = "primary",
    expired: bool = False,
) -> PrewarmSession:
    """Build a PrewarmSession for testing."""
    now = datetime.now(timezone.utc)
    expires = now - timedelta(hours=1) if expired else now + timedelta(hours=2)
    return PrewarmSession(
        retailer=retailer,
        account_name=account_name,
        cookies={"session_id": "test123", "auth": "token456"},
        auth_token="auth_token",
        cart_token="cart_token",
        prewarmed_at=now.isoformat(),
        expires_at=expires.isoformat(),
        adapter_name="TestAdapter",
    )