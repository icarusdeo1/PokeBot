"""Automatic session re-authentication.

Handles detecting session expiration mid-checkout and automatically
re-authenticating using pre-warmed credentials, then resuming checkout
from the cart step.

Per PRD Section 9.1 (MON-10), Section 12 edge case "Session cookie expires mid-checkout".
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.shared.models import WebhookEvent

if TYPE_CHECKING:
    from src.bot.config import Config
    from src.bot.logger import Logger
    from src.bot.monitor.retailers.base import RetailerAdapter
    from src.bot.session.prewarmer import SessionPrewarmer, PrewarmSession


class ReauthResult:
    """Result of a re-authentication attempt."""

    def __init__(
        self,
        success: bool,
        reauthenticated: bool = False,
        error: str = "",
    ) -> None:
        self.success = success
        self.reauthenticated = reauthenticated
        self.error = error


class SessionReauthenticator:
    """Handles automatic session re-authentication on expiry.

    When a session expires mid-checkout, this class:
    1. Detects the expired/invalid session via the prewarmer
    2. Re-authenticates using stored credentials
    3. Updates the adapter with fresh session state
    4. Fires SESSION_EXPIRED webhook on failure

    The re-auth flow is used at two points:
    - Before checkout: proactively verify session is valid
    - During checkout: on session-related HTTP errors, re-auth and retry

    Per PRD Section 9.1 (MON-10), Section 12 edge case.
    """

    def __init__(
        self,
        config: Config,
        logger: Logger,
        session_prewarmer: SessionPrewarmer,
    ) -> None:
        """Initialize the re-authenticator.

        Args:
            config: Validated bot configuration (contains retailer credentials).
            logger: Logger instance for structured event logging.
            session_prewarmer: SessionPrewarmer for session management and re-prewarm.
        """
        self.config = config
        self.logger = logger
        self._prewarmer = session_prewarmer

    async def check_and_reauth(
        self,
        adapter: RetailerAdapter,
        account_name: str,
        webhook_callback: Any = None,
    ) -> ReauthResult:
        """Check if a session is valid and re-authenticate if expired.

        This is called proactively before checkout to ensure the session
        is still valid. If expired, triggers re-authentication.

        Args:
            adapter: The retailer adapter whose session to check/reauth.
            account_name: Identifier for the account (used for prewarmer lookup).
            webhook_callback: Optional async callable for SESSION_EXPIRED events.

        Returns:
            ReauthResult with success status and whether re-auth happened.
        """
        # Check if session is valid via prewarmer
        session = self._prewarmer.get_valid_session(adapter.name, account_name)

        if session is not None:
            # Session still valid — inject into adapter
            self._inject_session(adapter, session)
            return ReauthResult(success=True, reauthenticated=False)

        # Session expired or missing — attempt re-auth
        self.logger.warning(
            "SESSION_EXPIRED_DETECTED",
            retailer=adapter.name,
            account=account_name,
            message="Session invalid or expired, attempting re-authentication",
        )

        reauth_ok = await self._reauthenticate(adapter, account_name)

        if reauth_ok:
            return ReauthResult(success=True, reauthenticated=True)

        # Re-auth failed
        await self._fire_session_expired_event(
            adapter=adapter,
            account_name=account_name,
            reason="Re-authentication failed — credentials may be invalid",
            webhook_callback=webhook_callback,
        )
        return ReauthResult(success=False, reauthenticated=False, error="Re-authentication failed")

    async def reauth_on_error(
        self,
        adapter: RetailerAdapter,
        account_name: str,
        error: str,
        webhook_callback: Any = None,
    ) -> ReauthResult:
        """Handle session error during checkout: re-auth and return result.

        Called when a checkout step fails with a session-related error
        (e.g., HTTP 401, auth redirect, "Please sign in" in page body).

        Args:
            adapter: The retailer adapter.
            account_name: Account identifier.
            error: The error message from the failed checkout step.
            webhook_callback: Optional webhook callback for SESSION_EXPIRED events.

        Returns:
            ReauthResult indicating whether re-auth succeeded.
        """
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
            "redirect.*login",
            "access denied",
            "forbidden",
        ]

        is_session_error = any(
            indicator.lower() in error.lower()
            for indicator in session_error_indicators
        )

        if not is_session_error:
            return ReauthResult(success=True, reauthenticated=False)

        self.logger.warning(
            "SESSION_ERROR_DURING_CHECKOUT",
            retailer=adapter.name,
            account=account_name,
            error=error,
            message="Session error detected, attempting re-authentication",
        )

        reauth_ok = await self._reauthenticate(adapter, account_name)

        if reauth_ok:
            return ReauthResult(success=True, reauthenticated=True)

        # Re-auth failed
        await self._fire_session_expired_event(
            adapter=adapter,
            account_name=account_name,
            reason=f"Checkout session error: {error}",
            webhook_callback=webhook_callback,
        )
        return ReauthResult(success=False, reauthenticated=False, error=f"Re-auth failed after session error: {error}")

    def _inject_session(self, adapter: RetailerAdapter, session: PrewarmSession) -> None:
        """Inject a valid session's cookies and tokens into an adapter.

        This makes the adapter use the pre-warmed session for subsequent
        HTTP requests, bypassing the need for a fresh login.

        Args:
            adapter: The retailer adapter to update.
            session: The valid PrewarmSession to inject.
        """
        import asyncio

        if hasattr(adapter, "inject_cookies"):
            # Adapter has a dedicated injection method
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(adapter.inject_cookies(session.cookies))
            except RuntimeError:
                asyncio.create_task(adapter.inject_cookies(session.cookies))
        else:
            # Update session state directly
            if hasattr(adapter, "_session_state") and adapter._session_state is not None:
                adapter._session_state.cookies = session.cookies
                adapter._session_state.auth_token = session.auth_token
                adapter._session_state.cart_token = session.cart_token
                adapter._session_state.is_valid = True

    async def _reauthenticate(
        self,
        adapter: RetailerAdapter,
        account_name: str,
    ) -> bool:
        """Re-authenticate using stored credentials from config.

        Gets credentials from config and runs login via the adapter.
        On success, injects the new session into the adapter and caches it.

        Args:
            adapter: The retailer adapter.
            account_name: Account identifier (used for cache key).

        Returns:
            True if re-auth succeeded, False otherwise.
        """
        retailer = adapter.name

        # Get credentials from config (try multi-account first, then single-account)
        username: str | None = None
        password: str | None = None

        # Multi-account path (MAC-T01)
        accounts = self.config.accounts.get(retailer, [])
        enabled_accounts = [a for a in accounts if a.enabled]

        if enabled_accounts:
            # Find matching account by username (account_name may be username or identifier)
            matched_account = None
            for acc in enabled_accounts:
                if acc.username == account_name or acc.username in account_name:
                    matched_account = acc
                    break
            if matched_account is None:
                matched_account = enabled_accounts[0]  # Fallback to first enabled

            if matched_account:
                username = matched_account.username
                password = matched_account.password
        else:
            # Single-account path
            retailer_cfg = self.config.retailers.get(retailer)
            if retailer_cfg:
                username = retailer_cfg.username
                password = retailer_cfg.password

        if not username or not password:
            self.logger.error(
                "REAUTH_NO_CREDENTIALS",
                retailer=retailer,
                account=account_name,
            )
            return False

        self.logger.info(
            "REAUTH_ATTEMPT",
            retailer=retailer,
            account=username,
        )

        try:
            # Run login via adapter — this re-authenticates
            login_ok = await adapter.login(username, password)

            if not login_ok:
                self.logger.error(
                    "REAUTH_LOGIN_FAILED",
                    retailer=retailer,
                    account=username,
                )
                return False

            # Login succeeded — get session state from adapter
            session_state = adapter.session_state
            if session_state is None:
                self.logger.error(
                    "REAUTH_NO_SESSION_STATE",
                    retailer=retailer,
                    account=username,
                )
                return False

            # Build PrewarmSession for caching
            from datetime import datetime, timezone, timedelta
            from src.bot.session.prewarmer import PrewarmSession as PSPrewarmSession

            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(hours=2)

            new_session = PSPrewarmSession(
                retailer=retailer,
                account_name=account_name,
                cookies=session_state.cookies,
                auth_token=session_state.auth_token,
                cart_token=session_state.cart_token,
                prewarmed_at=now.isoformat(),
                expires_at=expires_at.isoformat(),
                adapter_name=adapter.__class__.__name__,
            )

            # Update in-memory cache and persist to DB
            self._prewarmer._cache.set(retailer, account_name, new_session)

            if self._prewarmer._persistence is not None:
                self._prewarmer._persistence.save_session(retailer, new_session)

            self.logger.info(
                "REAUTH_SUCCESS",
                retailer=retailer,
                account=username,
                cookies_count=len(session_state.cookies),
            )

            return True

        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "REAUTH_ERROR",
                retailer=retailer,
                account=account_name,
                error=str(exc),
            )
            return False

    async def _fire_session_expired_event(
        self,
        adapter: RetailerAdapter,
        account_name: str,
        reason: str,
        webhook_callback: Any,
    ) -> None:
        """Fire SESSION_EXPIRED webhook event.

        Args:
            adapter: The retailer adapter.
            account_name: Account identifier.
            reason: Why session expired / re-auth failed.
            webhook_callback: Optional async callable.
        """
        event = WebhookEvent(
            event="SESSION_EXPIRED",
            item="",
            retailer=adapter.name,
            timestamp="",
            order_id="",
            error=reason,
        )

        self.logger.error(
            "SESSION_EXPIRED",
            retailer=adapter.name,
            account=account_name,
            reason=reason,
        )

        if webhook_callback is None:
            return

        try:
            if asyncio.iscoroutinefunction(webhook_callback):
                await webhook_callback(event)
            else:
                webhook_callback(event)
        except Exception:  # noqa: BLE001
            pass


__all__ = ["SessionReauthenticator", "ReauthResult"]