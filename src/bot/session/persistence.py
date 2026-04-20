"""Session persistence layer: saves/loads pre-warmed sessions to state.db.

Ensures sessions survive bot restarts and supports TTL-based expiry checking
with automatic re-authentication when sessions expire.

Per PRD Sections 9.1 (MON-8, MON-10).
"""

from __future__ import annotations

import json as json_module
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.shared.db import DatabaseManager
from src.shared.models import SessionState

if TYPE_CHECKING:
    from src.bot.session.prewarmer import PrewarmSession


class SessionPersistence:
    """Handles persisting pre-warmed sessions to SQLite and loading them back.

    This class bridges the in-memory :class:`SessionPrewarmer` and the
    :class:`DatabaseManager`. After a successful pre-warm, the session is
    saved to ``state.db``. On startup, sessions are loaded from the DB
    and injected into the prewarmer's cache so they're immediately available
    without re-authenticating.

    TTL-based expiry is checked on load: if ``expires_at`` has passed, the
    session is considered stale and re-authentication will be triggered.
    """

    def __init__(self, db: DatabaseManager) -> None:
        """Initialize persistence layer.

        Args:
            db: DatabaseManager instance for state.db.
        """
        self._db = db

    def save_session(
        self,
        retailer: str,
        session: PrewarmSession,
        account_name: str | None = None,
    ) -> None:
        """Persist a pre-warmed session to the database.

        Args:
            retailer: Retailer name.
            session: PrewarmSession instance to persist.
            account_name: If provided, persists to the account_sessions table
                keyed by (retailer, username). Otherwise falls back to the legacy
                retailer-keyed session_state table.
        """
        if account_name is not None:
            self._db.save_account_session(
                retailer=retailer,
                username=account_name,
                cookies=session.cookies,
                auth_token=session.auth_token,
                cart_token=session.cart_token,
                is_valid=True,
                expires_at=session.expires_at,
            )
            # Also save to legacy retailer-keyed table for backwards compat
            # with code/tests that read via load_session(retailer).
            self._db.save_session(
                retailer=retailer,
                cookies=session.cookies,
                auth_token=session.auth_token,
                cart_token=session.cart_token,
                is_valid=True,
                expires_at=session.expires_at,
            )
        else:
            self._db.save_session(
                retailer=retailer,
                cookies=session.cookies,
                auth_token=session.auth_token,
                cart_token=session.cart_token,
                is_valid=True,
                expires_at=session.expires_at,
            )

    def load_session(
        self, retailer: str, account_name: str | None = None
    ) -> SessionState | None:
        """Load a persisted session and check if it's still valid.

        If account_name is provided, looks up the account-keyed record first
        (account_sessions table). Falls back to the retailer-keyed record
        (session_state table) for backwards compat.

        The session is considered valid only if:
        1. A record exists in the database.
        2. ``is_valid`` is True in the database.
        3. ``expires_at`` has not passed (UTC).

        Args:
            retailer: Retailer name.
            account_name: If provided, load from account_sessions keyed by
                (retailer, username); otherwise use retailer-keyed session_state.

        Returns:
            SessionState if the session is valid and not expired, else None.
        """
        row: dict[str, Any] | None = None
        if account_name is not None:
            row = self._db.load_account_session(retailer, account_name)
        if row is None:
            row = self._db.load_session(retailer)
        if row is None:
            return None

        # Check is_valid flag from DB
        if not row["is_valid"]:
            return None

        # Check TTL expiry
        expires_at_str = row.get("expires_at", "")
        if expires_at_str:
            expires_at = _parse_datetime(expires_at_str)
            if expires_at is not None and datetime.now(timezone.utc) >= expires_at:
                # Session expired — mark invalid and return None
                if account_name is not None:
                    self._db.invalidate_account_session(retailer, account_name)
                else:
                    self._db.invalidate_session(retailer)
                return None

        return SessionState(
            cookies=row["cookies"],
            auth_token=row["auth_token"],
            cart_token=row["cart_token"],
            prewarmed_at=row.get("prewarmed_at", ""),
            expires_at=expires_at_str,
            is_valid=True,
        )

    def invalidate_session(self, retailer: str) -> None:
        """Mark a retailer's persisted session as invalid."""
        self._db.invalidate_session(retailer)

    def load_all_sessions(self) -> dict[str, SessionState]:
        """Load all valid, non-expired sessions from the database.

        Loads from the account_sessions table first (keyed by
        "retailer:username"), then supplements with retailer-keyed
        session_state records that have no corresponding account entry
        (backwards compat — keyed by bare retailer name).

        Returns:
            Dict mapping key → SessionState.
            - "retailer:username" for account-keyed sessions
            - bare "retailer" for legacy retailer-keyed records
        """
        result: dict[str, SessionState] = {}
        now = datetime.now(timezone.utc)

        # ── 1. Account-keyed sessions (primary path) ──────────────────────
        rows = self._db.load_all_account_sessions()
        for row in rows:
            expires_at_str = row.get("expires_at", "")
            is_valid = row["is_valid"]
            if expires_at_str:
                expires_at = _parse_datetime(expires_at_str)
                if expires_at is not None and now >= expires_at:
                    self._db.invalidate_account_session(row["retailer"], row["username"])
                    continue
            if not is_valid:
                continue
            key = f"{row['retailer']}:{row['username']}"
            result[key] = SessionState(
                cookies=row["cookies"],
                auth_token=row["auth_token"],
                cart_token=row["cart_token"],
                prewarmed_at=row["prewarmed_at"],
                expires_at=expires_at_str,
                is_valid=True,
            )

        # ── 2. Legacy retailer-keyed records (fallback only) ───────────────
        # Only expose bare-retailer keys for retailers that have NO entry in
        # result yet (i.e. session_state existed before account_sessions).
        # This prevents the legacy path from shadowing real per-account data.
        with self._db.connection() as conn:
            retailer_rows_raw = conn.execute(
                """SELECT retailer, cookies_json, auth_token, cart_token,
                          prewarmed_at, expires_at, is_valid
                   FROM session_state"""
            ).fetchall()
        retailer_rows = [dict(r) for r in retailer_rows_raw]

        for row in retailer_rows:
            retailer = row["retailer"]
            # Skip if we already have an account-keyed entry for this retailer
            if any(k.startswith(f"{retailer}:") for k in result):
                continue
            is_valid = bool(row["is_valid"])
            expires_at_str = row.get("expires_at", "") or ""
            if expires_at_str:
                expires_at = _parse_datetime(expires_at_str)
                if expires_at is not None and now >= expires_at:
                    self._db.invalidate_session(retailer)
                    continue
            if not is_valid:
                continue
            # Use bare retailer name as key (no trailing colon) for compat
            result[retailer] = SessionState(
                cookies=json_module.loads(row["cookies_json"]),
                auth_token=row["auth_token"],
                cart_token=row["cart_token"],
                prewarmed_at=row.get("prewarmed_at", ""),
                expires_at=expires_at_str,
                is_valid=True,
            )

        return result


def _parse_datetime(value: str) -> datetime | None:
    """Parse an ISO-8601 datetime string, treating naive as UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None
