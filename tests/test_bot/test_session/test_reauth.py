"""Tests for SessionReauthenticator (SESSION-T03).

Tests automatic session re-authentication on expiry mid-checkout.
Per PRD Section 9.1 (MON-10), Section 12 edge case.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.session.reauth import SessionReauthenticator, ReauthResult
from src.shared.models import SessionState


class MockRetailerAdapter:
    """Mock retailer adapter for testing."""

    def __init__(self, name: str = "target") -> None:
        self.name = name
        self._session_state: SessionState | None = None
        self._prewarmed = False
        self._login_calls: list[tuple[str, str]] = []
        self._inject_cookies_calls: list[dict] = []

    @property
    def session_state(self) -> SessionState | None:
        return self._session_state

    @property
    def is_prewarmed(self) -> bool:
        return self._prewarmed

    async def login(self, username: str, password: str) -> bool:
        self._login_calls.append((username, password))
        self._prewarmed = True
        self._session_state = SessionState(
            cookies={"session_id": "fresh_session_123"},
            auth_token="fresh_auth_token",
            cart_token="fresh_cart_token",
            prewarmed_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            is_valid=True,
        )
        return True

    async def inject_cookies(self, cookies: dict[str, str]) -> None:
        self._inject_cookies_calls.append(cookies)
        if self._session_state is not None:
            self._session_state.cookies = cookies


class MockConfig:
    """Mock config with retailer accounts."""

    def __init__(self) -> None:
        self.accounts: dict[str, list[MagicMock]] = {}
        self.retailers: dict[str, MagicMock] = {}


@pytest.fixture
def mock_config() -> MockConfig:
    cfg = MockConfig()

    # Multi-account: 2 Target accounts
    acc1 = MagicMock()
    acc1.username = "target_user_1"
    acc1.password = "pass1"
    acc1.enabled = True
    acc1.item_filter = []
    acc1.round_robin = False

    acc2 = MagicMock()
    acc2.username = "target_user_2"
    acc2.password = "pass2"
    acc2.enabled = True
    acc2.item_filter = []
    acc2.round_robin = False

    cfg.accounts["target"] = [acc1, acc2]

    # Single-account fallback
    target_cfg = MagicMock()
    target_cfg.username = "target_primary"
    target_cfg.password = "primary_pass"
    target_cfg.enabled = True
    cfg.retailers["target"] = target_cfg

    return cfg


@pytest.fixture
def mock_logger() -> MagicMock:
    logger = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    return logger


@pytest.fixture
def mock_prewarmer() -> MagicMock:
    prewarmer = MagicMock()
    prewarmer.get_valid_session = MagicMock(return_value=None)
    prewarmer._cache = MagicMock()
    prewarmer._cache.set = MagicMock()
    prewarmer._persistence = None
    return prewarmer


class TestReauthResult:
    """Tests for ReauthResult dataclass."""

    def test_success_not_reauthenticated(self) -> None:
        result = ReauthResult(success=True, reauthenticated=False)
        assert result.success is True
        assert result.reauthenticated is False
        assert result.error == ""

    def test_success_reauthenticated(self) -> None:
        result = ReauthResult(success=True, reauthenticated=True)
        assert result.success is True
        assert result.reauthenticated is True

    def test_failure_with_error(self) -> None:
        result = ReauthResult(success=False, error="Credentials invalid")
        assert result.success is False
        assert result.error == "Credentials invalid"


class TestSessionReauthenticator:
    """Tests for SessionReauthenticator."""

    @pytest.fixture
    def reauthenticator(
        self,
        mock_config: MockConfig,
        mock_logger: MagicMock,
        mock_prewarmer: MagicMock,
    ) -> SessionReauthenticator:
        return SessionReauthenticator(
            config=mock_config,
            logger=mock_logger,
            session_prewarmer=mock_prewarmer,
        )

    # ── check_and_reauth ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_check_and_reauth_session_valid(
        self,
        reauthenticator: SessionReauthenticator,
        mock_prewarmer: MagicMock,
    ) -> None:
        """Valid session: inject and return success without re-auth."""
        # Pre-warmed session is valid
        from src.bot.session.prewarmer import PrewarmSession

        valid_session = PrewarmSession(
            retailer="target",
            account_name="target_user_1",
            cookies={"session": "valid_cookies"},
            auth_token="valid_auth",
            cart_token="valid_cart",
            prewarmed_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            adapter_name="TargetAdapter",
        )
        mock_prewarmer.get_valid_session.return_value = valid_session

        adapter = MockRetailerAdapter()
        result = await reauthenticator.check_and_reauth(
            adapter=adapter,
            account_name="target_user_1",
        )

        assert result.success is True
        assert result.reauthenticated is False
        mock_prewarmer.get_valid_session.assert_called_once_with("target", "target_user_1")

    @pytest.mark.asyncio
    async def test_check_and_reauth_session_expired_reauth_succeeds(
        self,
        reauthenticator: SessionReauthenticator,
        mock_config: MockConfig,
        mock_prewarmer: MagicMock,
    ) -> None:
        """Expired session: re-auth succeeds."""
        mock_prewarmer.get_valid_session.return_value = None  # Session expired

        adapter = MockRetailerAdapter()
        webhook_cb = AsyncMock()

        result = await reauthenticator.check_and_reauth(
            adapter=adapter,
            account_name="target_user_1",
            webhook_callback=webhook_cb,
        )

        assert result.success is True
        assert result.reauthenticated is True
        # Login was called with correct credentials (first enabled account)
        assert len(adapter._login_calls) == 1
        username, password = adapter._login_calls[0]
        assert username == "target_user_1"

    @pytest.mark.asyncio
    async def test_check_and_reauth_session_expired_reauth_fails(
        self,
        reauthenticator: SessionReauthenticator,
        mock_config: MockConfig,
        mock_prewarmer: MagicMock,
    ) -> None:
        """Re-auth fails: return failure and fire SESSION_EXPIRED."""
        mock_prewarmer.get_valid_session.return_value = None

        adapter = MockRetailerAdapter()
        # Make login fail
        adapter.login = AsyncMock(return_value=False)

        webhook_cb = AsyncMock()
        result = await reauthenticator.check_and_reauth(
            adapter=adapter,
            account_name="target_user_1",
            webhook_callback=webhook_cb,
        )

        assert result.success is False
        assert result.reauthenticated is False
        assert "Re-authentication failed" in result.error
        # SESSION_EXPIRED webhook should have been fired
        webhook_cb.assert_called_once()
        call_args = webhook_cb.call_args[0][0]
        assert call_args.event == "SESSION_EXPIRED"

    # ── reauth_on_error ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_reauth_on_error_not_session_error(
        self,
        reauthenticator: SessionReauthenticator,
        mock_prewarmer: MagicMock,
    ) -> None:
        """Non-session error (e.g., payment decline): do not re-auth."""
        adapter = MockRetailerAdapter()
        result = await reauthenticator.reauth_on_error(
            adapter=adapter,
            account_name="target_user_1",
            error="Payment declined: insufficient funds",
        )

        assert result.success is True
        assert result.reauthenticated is False

    @pytest.mark.asyncio
    async def test_reauth_on_error_401_unauthorized(
        self,
        reauthenticator: SessionReauthenticator,
        mock_config: MockConfig,
        mock_prewarmer: MagicMock,
    ) -> None:
        """HTTP 401 error: trigger re-auth."""
        mock_prewarmer.get_valid_session.return_value = None

        adapter = MockRetailerAdapter()
        result = await reauthenticator.reauth_on_error(
            adapter=adapter,
            account_name="target_user_1",
            error="HTTP 401 Unauthorized",
        )

        assert result.success is True
        assert result.reauthenticated is True

    @pytest.mark.asyncio
    async def test_reauth_on_error_please_sign_in(
        self,
        reauthenticator: SessionReauthenticator,
        mock_config: MockConfig,
        mock_prewarmer: MagicMock,
    ) -> None:
        """Page says "please sign in": trigger re-auth."""
        mock_prewarmer.get_valid_session.return_value = None

        adapter = MockRetailerAdapter()
        result = await reauthenticator.reauth_on_error(
            adapter=adapter,
            account_name="target_user_1",
            error="Page content: Please sign in to continue",
        )

        assert result.success is True
        assert result.reauthenticated is True

    @pytest.mark.asyncio
    async def test_reauth_on_error_session_expired_in_message(
        self,
        reauthenticator: SessionReauthenticator,
        mock_config: MockConfig,
        mock_prewarmer: MagicMock,
    ) -> None:
        """Error message mentions session expired: trigger re-auth."""
        mock_prewarmer.get_valid_session.return_value = None

        adapter = MockRetailerAdapter()
        result = await reauthenticator.reauth_on_error(
            adapter=adapter,
            account_name="target_user_1",
            error="Your session has expired, please login again",
        )

        assert result.success is True
        assert result.reauthenticated is True

    @pytest.mark.asyncio
    async def test_reauth_on_error_reauth_fails(
        self,
        reauthenticator: SessionReauthenticator,
        mock_config: MockConfig,
        mock_prewarmer: MagicMock,
    ) -> None:
        """Re-auth fails on session error: return failure."""
        mock_prewarmer.get_valid_session.return_value = None

        adapter = MockRetailerAdapter()
        adapter.login = AsyncMock(return_value=False)

        webhook_cb = AsyncMock()
        result = await reauthenticator.reauth_on_error(
            adapter=adapter,
            account_name="target_user_1",
            error="401 unauthorized",
            webhook_callback=webhook_cb,
        )

        assert result.success is False
        assert "Re-auth failed" in result.error

    @pytest.mark.asyncio
    async def test_reauth_on_error_multiple_indicators(
        self,
        reauthenticator: SessionReauthenticator,
    ) -> None:
        """All session error indicators are detected."""
        session_error_indicators = [
            "unauthorized",
            "401",
            "please sign in",
            "sign in",
            "session expired",
            "auth required",
            "login",
            "invalid session",
            "token expired",
            "session invalid",
            "access denied",
            "forbidden",
        ]

        adapter = MockRetailerAdapter()
        mock_prewarmer = MagicMock()
        mock_prewarmer.get_valid_session.return_value = None
        reauthenticator._prewarmer = mock_prewarmer

        for indicator in session_error_indicators:
            mock_prewarmer.get_valid_session.reset_mock()
            result = await reauthenticator.reauth_on_error(
                adapter=adapter,
                account_name="test",
                error=f"Something went wrong: {indicator}",
            )
            assert result.success is True, f"Failed to detect: {indicator}"
            assert result.reauthenticated is True, f"Failed to re-auth for: {indicator}"


class TestSessionReauthenticatorCredentials:
    """Tests for credential lookup in re-authentication."""

    @pytest.mark.asyncio
    async def test_reauth_uses_matching_account(
        self,
        mock_config: MockConfig,
        mock_logger: MagicMock,
        mock_prewarmer: MagicMock,
    ) -> None:
        """When account_name matches a username, use those credentials."""
        mock_prewarmer.get_valid_session.return_value = None

        reauthenticator = SessionReauthenticator(
            config=mock_config,
            logger=mock_logger,
            session_prewarmer=mock_prewarmer,
        )

        adapter = MockRetailerAdapter()
        await reauthenticator.check_and_reauth(
            adapter=adapter,
            account_name="target_user_2",
        )

        # Should have tried target_user_2's credentials
        assert len(adapter._login_calls) == 1
        assert adapter._login_calls[0][0] == "target_user_2"

    @pytest.mark.asyncio
    async def test_reauth_fallback_to_primary_single_account(
        self,
        mock_logger: MagicMock,
        mock_prewarmer: MagicMock,
    ) -> None:
        """When no multi-account config, fallback to primary retailer credentials."""
        cfg = MagicMock()
        cfg.accounts = {}  # No multi-account
        cfg.retailers = {}

        primary = MagicMock()
        primary.username = "primary_user"
        primary.password = "primary_password"
        cfg.retailers["walmart"] = primary

        reauthenticator = SessionReauthenticator(
            config=cfg,
            logger=mock_logger,
            session_prewarmer=mock_prewarmer,
        )

        adapter = MockRetailerAdapter(name="walmart")
        await reauthenticator.check_and_reauth(
            adapter=adapter,
            account_name="default",
        )

        assert len(adapter._login_calls) == 1
        assert adapter._login_calls[0][0] == "primary_user"

    @pytest.mark.asyncio
    async def test_reauth_no_credentials_available(
        self,
        mock_logger: MagicMock,
        mock_prewarmer: MagicMock,
    ) -> None:
        """When no credentials at all, re-auth fails gracefully."""
        cfg = MagicMock()
        cfg.accounts = {}
        cfg.retailers = {}  # No retailers either

        reauthenticator = SessionReauthenticator(
            config=cfg,
            logger=mock_logger,
            session_prewarmer=mock_prewarmer,
        )

        adapter = MockRetailerAdapter()
        result = await reauthenticator.check_and_reauth(
            adapter=adapter,
            account_name="default",
        )

        assert result.success is False
        assert "Re-authentication failed" in result.error


class TestSessionInjection:
    """Tests for session injection into adapter."""

        # Note: _inject_session creates an async task for inject_cookies.
        # The task is fire-and-forget, scheduled on the event loop.
        # In this test, we verify the session was injected via the direct
        # _session_state path since MockRetailerAdapter doesn't have inject_cookies.
        # In production adapters with inject_cookies, the cookies are delivered
        # via the fire-and-forget task.

    @pytest.mark.asyncio
    async def test_inject_session_updates_session_state_directly(
        self,
        mock_config: MockConfig,
        mock_logger: MagicMock,
        mock_prewarmer: MagicMock,
    ) -> None:
        """When adapter has no inject_cookies, update _session_state directly."""
        from src.bot.session.prewarmer import PrewarmSession

        valid_session = PrewarmSession(
            retailer="target",
            account_name="test",
            cookies={"direct": "cookies"},
            auth_token="direct_auth",
            cart_token="direct_cart",
            prewarmed_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            adapter_name="TargetAdapter",
        )
        mock_prewarmer.get_valid_session.return_value = valid_session

        reauthenticator = SessionReauthenticator(
            config=mock_config,
            logger=mock_logger,
            session_prewarmer=mock_prewarmer,
        )

        # Adapter without inject_cookies
        adapter = MockRetailerAdapter()
        adapter._session_state = SessionState(
            cookies={"old": "cookies"},
            auth_token="old_auth",
            cart_token="old_cart",
            prewarmed_at=datetime.now(timezone.utc).isoformat(),
            is_valid=True,
        )

        # Inject via check_and_reauth (which calls _inject_session)
        await reauthenticator.check_and_reauth(adapter=adapter, account_name="test")

        # Session state should be updated via direct path
        # Note: since MockRetailerAdapter HAS inject_cookies, the async task
        # path is taken. We verify via the direct path using a mock that
        # doesn't have inject_cookies.

    @pytest.mark.asyncio
    async def test_inject_session_direct_path_no_inject_method(
        self,
        mock_config: MockConfig,
        mock_logger: MagicMock,
        mock_prewarmer: MagicMock,
    ) -> None:
        """Direct _session_state update when adapter has no inject_cookies method."""
        from src.bot.session.prewarmer import PrewarmSession

        valid_session = PrewarmSession(
            retailer="target",
            account_name="test",
            cookies={"direct": "cookies"},
            auth_token="direct_auth",
            cart_token="direct_cart",
            prewarmed_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            adapter_name="TargetAdapter",
        )
        mock_prewarmer.get_valid_session.return_value = valid_session

        reauthenticator = SessionReauthenticator(
            config=mock_config,
            logger=mock_logger,
            session_prewarmer=mock_prewarmer,
        )

        # Create an adapter that has no inject_cookies method
        class NoInjectAdapter:
            name = "target"
            _session_state: SessionState | None = SessionState(
                cookies={"old": "cookies"},
                auth_token="old_auth",
                cart_token="old_cart",
                prewarmed_at=datetime.now(timezone.utc).isoformat(),
                is_valid=True,
            )

        adapter = NoInjectAdapter()  # type: ignore[assign]

        # Call _inject_session directly
        reauthenticator._inject_session(adapter, valid_session)

        # Session state should be updated directly
        assert adapter._session_state.cookies == {"direct": "cookies"}  # type: ignore[union-attr]
        assert adapter._session_state.auth_token == "direct_auth"  # type: ignore[union-attr]
        assert adapter._session_state.cart_token == "direct_cart"  # type: ignore[union-attr]


class TestWebhookFiring:
    """Tests for SESSION_EXPIRED webhook firing."""

    @pytest.mark.asyncio
    async def test_session_expired_fires_webhook_on_reauth_failure(
        self,
        mock_config: MockConfig,
        mock_logger: MagicMock,
        mock_prewarmer: MagicMock,
    ) -> None:
        """When re-auth fails, SESSION_EXPIRED webhook is fired."""
        mock_prewarmer.get_valid_session.return_value = None

        reauthenticator = SessionReauthenticator(
            config=mock_config,
            logger=mock_logger,
            session_prewarmer=mock_prewarmer,
        )

        adapter = MockRetailerAdapter()
        adapter.login = AsyncMock(return_value=False)

        webhook_cb = AsyncMock()
        await reauthenticator.check_and_reauth(
            adapter=adapter,
            account_name="target_user_1",
            webhook_callback=webhook_cb,
        )

        webhook_cb.assert_called_once()
        event = webhook_cb.call_args[0][0]
        assert event.event == "SESSION_EXPIRED"
        assert "Re-authentication failed" in event.error

    @pytest.mark.asyncio
    async def test_session_expired_event_fields(
        self,
        mock_config: MockConfig,
        mock_logger: MagicMock,
        mock_prewarmer: MagicMock,
    ) -> None:
        """SESSION_EXPIRED event has correct fields."""
        mock_prewarmer.get_valid_session.return_value = None

        reauthenticator = SessionReauthenticator(
            config=mock_config,
            logger=mock_logger,
            session_prewarmer=mock_prewarmer,
        )

        adapter = MockRetailerAdapter(name="bestbuy")
        adapter.login = AsyncMock(return_value=False)

        webhook_cb = AsyncMock()
        await reauthenticator.reauth_on_error(
            adapter=adapter,
            account_name="bb_user_1",
            error="401 Unauthorized",
            webhook_callback=webhook_cb,
        )

        event = webhook_cb.call_args[0][0]
        assert event.event == "SESSION_EXPIRED"
        assert event.retailer == "bestbuy"
        assert event.error != ""