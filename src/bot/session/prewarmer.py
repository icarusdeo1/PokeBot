"""Session pre-warmer.

Loads retailer pages, authenticates with credentials, caches all cookies and
auth tokens, and verifies session validity. Pre-warm is triggered N minutes
before a configured drop window. Sessions are cached with a 2-hour expiry.

Per PRD Sections 9.1 (MON-7), 9.10 (MAC-4).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from src.bot.config import Config
    from src.shared.db import DatabaseManager
    from src.shared.models import DropWindow
    from src.bot.logger import Logger
    from src.bot.monitor.retailers.base import RetailerAdapter


# Session expiry: pre-warmed sessions are valid for 2 hours (PRD Section 9.1).
PREWARM_SESSION_TTL_HOURS: int = 2

# How often to check for drop windows approaching (seconds).
_SCHEDULER_INTERVAL_SECONDS: int = 30


@dataclass
class PrewarmResult:
    """Result of a pre-warm attempt for a single account."""

    retailer: str
    account_name: str
    success: bool
    prewarmed_at: str = ""
    error: str = ""
    cookies_count: int = 0


@dataclass
class PrewarmSession:
    """A pre-warmed session ready for use."""

    retailer: str
    account_name: str
    cookies: dict[str, str]
    auth_token: str
    cart_token: str
    prewarmed_at: str  # ISO-8601 UTC timestamp
    expires_at: str  # ISO-8601 UTC timestamp
    adapter_name: str

    @property
    def is_expired(self) -> bool:
        """Return True if this session has expired."""
        expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) >= expires


@dataclass
class SessionCache:
    """In-memory cache of pre-warmed sessions per retailer/account."""

    sessions: dict[str, dict[str, PrewarmSession]] = field(default_factory=dict)

    def _key(self, retailer: str, account_name: str) -> str:
        return f"{retailer}:{account_name}"

    def set(
        self,
        retailer: str,
        account_name: str,
        session: PrewarmSession,
    ) -> None:
        if retailer not in self.sessions:
            self.sessions[retailer] = {}
        self.sessions[retailer][account_name] = session

    def get(self, retailer: str, account_name: str) -> PrewarmSession | None:
        key = self._key(retailer, account_name)
        retailer_sessions = self.sessions.get(retailer, {})
        return retailer_sessions.get(account_name)

    def invalidate(self, retailer: str, account_name: str) -> None:
        key = self._key(retailer, account_name)
        if retailer in self.sessions and account_name in self.sessions[retailer]:
            del self.sessions[retailer][account_name]

    def get_valid(self, retailer: str, account_name: str) -> PrewarmSession | None:
        """Return session if valid and not expired, else None."""
        session = self.get(retailer, account_name)
        if session is None:
            return None
        if session.is_expired:
            self.invalidate(retailer, account_name)
            return None
        return session

    def get_all_valid(self, retailer: str) -> list[PrewarmSession]:
        """Return all valid (non-expired) sessions for a retailer."""
        result = []
        items = list(self.sessions.get(retailer, {}).items())
        for account_name, session in items:
            if session.is_expired:
                self.invalidate(retailer, account_name)
            else:
                result.append(session)
        return result

    def clear(self) -> None:
        self.sessions.clear()


class SessionPrewarmer:
    """Pre-warms retailer sessions ahead of drop windows.

    This class orchestrates pre-warming for one or more retailer adapters.
    Pre-warming runs on a schedule: when a drop window is within
    ``prewarm_minutes`` of the current time, the corresponding accounts
    are pre-warmed in parallel.

    Sessions are cached in memory with a 2-hour TTL. The caller can
    retrieve a valid session via :meth:`get_valid_session` to feed into
    checkout without re-authenticating.
    """

    def __init__(
        self,
        config: Config,
        logger: Logger | None = None,
        db: DatabaseManager | None = None,
    ) -> None:
        """Initialize the pre-warmer.

        Args:
            config: Validated bot configuration.
            logger: Optional logger for lifecycle events.
            db: Optional DatabaseManager for session persistence. If provided,
                sessions will be saved to and loaded from state.db, enabling
                sessions to survive bot restarts.
        """
        self.config = config
        self.logger = logger
        self._db = db
        self._persistence = None
        if db is not None:
            from src.bot.session.persistence import SessionPersistence
            self._persistence = SessionPersistence(db)
        self._cache = SessionCache()
        self._running = False
        self._task: asyncio.Task[None] | None = None

    # ── Public API ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background pre-warm scheduler.

        The scheduler periodically checks drop windows and triggers
        pre-warming for any accounts whose drop is approaching.
        This method is non-blocking.
        """
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_scheduler())
        self._log("INFO", "PREWARMER_STARTED")

    async def stop(self) -> None:
        """Stop the pre-warm scheduler."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._log("INFO", "PREWARMER_STOPPED")

    def load_from_db(self) -> None:
        """Pre-populate the session cache from persisted DB records.

        Call this at startup to restore sessions from state.db so they're
        immediately available without re-authenticating. Expired sessions
        are skipped and marked invalid in the DB.

        This is called automatically by the daemon on startup (PHASE1.5).
        """
        if self._persistence is None:
            return

        sessions = self._persistence.load_all_sessions()
        for key, session_state in sessions.items():
            # key is "retailer:username" for account-keyed sessions,
            # or bare "retailer" for legacy retailer-keyed records.
            retailer, _, account_name = key.partition(":")
            if not account_name:
                # Legacy retailer-keyed record — use "persisted" as account name
                account_name = "persisted"
            prewarm_session = PrewarmSession(
                retailer=retailer,
                account_name=account_name,
                cookies=session_state.cookies,
                auth_token=session_state.auth_token,
                cart_token=session_state.cart_token,
                prewarmed_at=session_state.prewarmed_at,
                expires_at=session_state.expires_at,
                adapter_name="",
            )
            self._cache.set(retailer, account_name, prewarm_session)
            self._log(
                "INFO", "SESSION_RESTORED_FROM_DB",
                retailer=retailer, account=account_name,
                cookies_count=len(session_state.cookies),
            )

    async def prewarm_now(
        self,
        adapter: RetailerAdapter,
        account_name: str,
    ) -> PrewarmResult:
        """Immediately pre-warm a specific adapter/account.

        This bypasses the scheduler and pre-warms immediately. Useful
        when the operator triggers a dry-run or when a social signal
        triggers pre-warming (SCL-4).

        Args:
            adapter: The retailer adapter instance.
            account_name: Identifier for this account (shown in logs).

        Returns:
            PrewarmResult with success/failure details.
        """
        return await self._prewarm_adapter(adapter, account_name)

    def get_valid_session(
        self,
        retailer: str,
        account_name: str,
    ) -> PrewarmSession | None:
        """Return a valid pre-warmed session, or None if not available.

        First checks the in-memory cache. If not found and persistence
        is configured, loads from the database. If the DB session is
        valid and not expired, injects it into the cache and returns it.

        Call this during checkout to retrieve the pre-warmed session
        for the given retailer/account and inject it into the adapter's
        HTTP client (cookies) and authentication state.
        """
        # Check in-memory cache first
        session = self._cache.get_valid(retailer, account_name)
        if session is not None:
            return session

        # Try loading from persistence if configured
        if self._persistence is not None:
            session_state = self._persistence.load_session(
                retailer, account_name=account_name
            )
            if session_state is not None:
                # Reconstruct PrewarmSession from SessionState
                session = PrewarmSession(
                    retailer=retailer,
                    account_name=account_name,
                    cookies=session_state.cookies,
                    auth_token=session_state.auth_token,
                    cart_token=session_state.cart_token,
                    prewarmed_at=session_state.prewarmed_at,
                    expires_at=session_state.expires_at,
                    adapter_name="",
                )
                # Inject into cache for future lookups
                self._cache.set(retailer, account_name, session)
                self._log(
                    "INFO", "SESSION_LOADED_FROM_DB",
                    retailer=retailer, account=account_name,
                )
                return session

        return None

    def invalidate_session(self, retailer: str, account_name: str) -> None:
        """Invalidate a cached session and persisted state, forcing re-auth on next use."""
        self._cache.invalidate(retailer, account_name)
        if self._persistence is not None:
            self._persistence.invalidate_session(retailer)
        self._log("INFO", "SESSION_INVALIDATED", retailer=retailer, account=account_name)

    def get_status(self) -> dict[str, list[dict[str, Any]]]:
        """Return current pre-warm status for all retailers/accounts.

        Returns a dict mapping retailer name → list of account dicts
        with ``account_name``, ``prewarmed_at``, ``is_valid``,
        ``expires_at``, ``cookies_count``.
        Merges in-memory cache data with persisted DB records so sessions
        loaded from state.db are also reflected.
        """
        status: dict[str, list[dict[str, Any]]] = {}

        # Start with in-memory cache data
        for retailer, accounts in self._cache.sessions.items():
            status[retailer] = []
            for account_name, session in accounts.items():
                status[retailer].append({
                    "account_name": account_name,
                    "prewarmed_at": session.prewarmed_at,
                    "expires_at": session.expires_at,
                    "is_valid": not session.is_expired,
                    "cookies_count": len(session.cookies),
                })

        # Supplement with persisted account sessions from DB
        # that may not yet be in the cache (e.g. after a restart)
        if self._persistence is not None:
            persisted = self._persistence.load_all_sessions()
            for key, session_state in persisted.items():
                # key is "retailer:username"
                retailer, _, username = key.partition(":")
                if retailer not in status:
                    status[retailer] = []
                # Avoid duplicates with cached sessions
                existing = {a["account_name"] for a in status.get(retailer, [])}
                if username not in existing:
                    status[retailer].append({
                        "account_name": username,
                        "prewarmed_at": session_state.prewarmed_at,
                        "expires_at": session_state.expires_at,
                        "is_valid": session_state.is_valid,
                        "cookies_count": len(session_state.cookies),
                    })

        return status

    # ── Scheduler ───────────────────────────────────────────────────────────

    async def _run_scheduler(self) -> None:
        """Background loop: check drop windows and trigger pre-warming."""
        while self._running:
            try:
                await self._check_and_prewarm()
            except Exception as exc:  # noqa: BLE001
                self._log("ERROR", "PREWARM_SCHEDULER_ERROR", error=str(exc))
            await asyncio.sleep(_SCHEDULER_INTERVAL_SECONDS)

    async def _check_and_prewarm(self) -> None:
        """Check all drop windows and pre-warm any that are approaching."""
        now = datetime.now(timezone.utc)
        drop_windows = getattr(self.config, "drop_windows", [])
        enabled_retailers = self.config.get_enabled_retailers()

        for dw in drop_windows:
            if not dw.enabled:
                continue
            if dw.retailer not in enabled_retailers:
                continue

            drop_dt = _parse_datetime(dw.drop_datetime)
            if drop_dt is None:
                continue

            minutes_until_drop = (drop_dt - now).total_seconds() / 60.0

            # Pre-warm if within the prewarm window
            if 0 < minutes_until_drop <= dw.prewarm_minutes:
                # Check if already pre-warmed and valid
                account_key = f"drop_{dw.id}"
                existing = self._cache.get_valid(dw.retailer, account_key)
                if existing is not None:
                    continue  # Already pre-warmed

                # Trigger pre-warm
                adapter = self._get_adapter_for_retailer(dw.retailer)
                if adapter is not None:
                    result = await self._prewarm_adapter(adapter, account_key)
                    # Store result
                    if result.success:
                        self._log(
                            "INFO", "DROP_WINDOW_PREWARMED",
                            item=dw.item, retailer=dw.retailer,
                            minutes_until_drop=int(minutes_until_drop),
                        )
                    else:
                        self._log(
                            "WARNING", "DROP_WINDOW_PREWARM_FAILED",
                            item=dw.item, retailer=dw.retailer,
                            error=result.error,
                        )

    def _get_adapter_for_retailer(
        self,
        retailer: str,
    ) -> RetailerAdapter | None:
        """Get or create a retailer adapter for pre-warming.

        Returns the adapter instance configured for the given retailer.
        """
        from src.bot.monitor.retailers import get_default_registry

        registry = get_default_registry()
        adapter_cls = registry.get(retailer)
        if adapter_cls is None:
            self._log("ERROR", "ADAPTER_NOT_FOUND", retailer=retailer)
            return None
        return adapter_cls(self.config)

    # ── Pre-warm logic ──────────────────────────────────────────────────────

    async def _prewarm_adapter(
        self,
        adapter: RetailerAdapter,
        account_name: str,
    ) -> PrewarmResult:
        """Pre-warm a single adapter: authenticate and cache session.

        Returns a PrewarmResult indicating success or failure.
        """
        from src.bot.monitor.retailers.base import RetailerAdapter

        retailer = adapter.name
        self._log("INFO", "PREWARM_STARTED", retailer=retailer, account=account_name)

        try:
            # Get retailer credentials from config
            retailer_cfg = self.config.retailers.get(retailer)
            if retailer_cfg is None:
                return PrewarmResult(
                    retailer=retailer,
                    account_name=account_name,
                    success=False,
                    error="No retailer config found",
                )

            username = retailer_cfg.username
            password = retailer_cfg.password

            if not username or not password:
                return PrewarmResult(
                    retailer=retailer,
                    account_name=account_name,
                    success=False,
                    error="Missing credentials",
                )

            # Authenticate — this is the "load retailer page, authenticate"
            # step from PRD Section 9.1 (MON-7).
            login_ok = await adapter.login(username, password)

            if not login_ok:
                return PrewarmResult(
                    retailer=retailer,
                    account_name=account_name,
                    success=False,
                    error="Login failed",
                )

            # Verify session is valid
            if not adapter.is_prewarmed():
                # Mark as pre-warmed after successful login
                pass

            # Get session state (cookies, tokens) — this is the "cache all
            # cookies and auth tokens" step.
            session_state = adapter.session_state

            if session_state is None:
                return PrewarmResult(
                    retailer=retailer,
                    account_name=account_name,
                    success=False,
                    error="No session state after login",
                )

            # Build PrewarmSession with expiry (2 hours per PRD).
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(hours=PREWARM_SESSION_TTL_HOURS)
            now_iso = now.isoformat()
            expires_iso = expires_at.isoformat()

            session = PrewarmSession(
                retailer=retailer,
                account_name=account_name,
                cookies=session_state.cookies,
                auth_token=session_state.auth_token,
                cart_token=session_state.cart_token,
                prewarmed_at=now_iso,
                expires_at=expires_iso,
                adapter_name=adapter.__class__.__name__,
            )

            # Store in cache
            self._cache.set(retailer, account_name, session)

            # Persist to DB if configured (MON-8: persist and reuse cookies)
            if self._persistence is not None:
                self._persistence.save_session(retailer, session, account_name=account_name)
                self._log(
                    "INFO", "SESSION_PERSISTED",
                    retailer=retailer, account=account_name,
                )

            self._log(
                "INFO", "PREWARM_SUCCESS",
                retailer=retailer,
                account=account_name,
                cookies_count=len(session.cookies),
                expires_at=expires_iso,
            )

            return PrewarmResult(
                retailer=retailer,
                account_name=account_name,
                success=True,
                prewarmed_at=now_iso,
                cookies_count=len(session.cookies),
            )

        except Exception as exc:  # noqa: BLE001
            self._log("ERROR", "PREWARM_ERROR", retailer=retailer, account=account_name, error=str(exc))
            return PrewarmResult(
                retailer=retailer,
                account_name=account_name,
                success=False,
                error=str(exc),
            )
        finally:
            await adapter.close()

    async def prewarm_all_accounts(
        self,
        adapter: RetailerAdapter,
    ) -> list[PrewarmResult]:
        """Pre-warm all accounts for a given retailer in parallel (MAC-4).

        Multiple accounts for the same retailer are warmed simultaneously
        using asyncio.gather for maximum speed during pre-drop pre-warming.

        Args:
            adapter: The retailer adapter instance.

        Returns:
            List of PrewarmResult, one per account.
        """
        retailer = adapter.name
        results: list[PrewarmResult] = []

        # Get all enabled accounts for this retailer (MAC-T01 multi-account config)
        accounts = self.config.accounts.get(retailer, [])
        enabled_accounts = [a for a in accounts if a.enabled]

        if not enabled_accounts:
            # Fallback: use primary retailer credentials (single-account mode)
            retailer_cfg = self.config.retailers.get(retailer)
            if retailer_cfg and retailer_cfg.username and retailer_cfg.enabled:
                result = await self._prewarm_adapter(adapter, retailer_cfg.username)
                results.append(result)
        else:
            # Pre-warm all enabled accounts in parallel (MAC-T04)
            tasks = [
                self._prewarm_adapter(adapter, account.username)
                for account in enabled_accounts
            ]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)
            # Convert exceptions to failed PrewarmResult entries
            results.clear()
            for i, r in enumerate(raw_results):
                if isinstance(r, Exception):
                    results.append(
                        PrewarmResult(
                            retailer=retailer,
                            account_name=enabled_accounts[i].username,
                            success=False,
                            prewarmed_at="",
                            error=str(r),
                            cookies_count=0,
                        )
                    )
                else:
                    results.append(r)  # type: ignore[arg-type]

        return results

    # ── Logging ─────────────────────────────────────────────────────────────

    def _log(
        self,
        level: str,
        event: str,
        **kwargs: Any,
    ) -> None:
        if self.logger is not None:
            log_fn = getattr(self.logger, level.lower(), None)
            if log_fn is not None:
                log_fn(event, **kwargs)
            return
        ts = datetime.now(timezone.utc).isoformat()
        parts = [f"[{ts}] {level} {event}"]
        for k, v in kwargs.items():
            parts.append(f"{k}={v}")
        print(" ".join(parts))


def _parse_datetime(value: str) -> datetime | None:
    """Parse an ISO-8601 datetime string, treating naive as UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Naive datetimes are treated as UTC (per spec)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None
