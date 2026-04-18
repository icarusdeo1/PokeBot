"""Session persistence layer: saves/loads pre-warmed sessions to state.db.

Ensures sessions survive bot restarts and supports TTL-based expiry checking
with automatic re-authentication when sessions expire.

Per PRD Sections 9.1 (MON-8, MON-10).
"""

from __future__ import annotations

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
    ) -> None:
        """Persist a pre-warmed session to the database.

        Args:
            retailer: Retailer name (used as the DB key).
            session: PrewarmSession instance to persist.
        """
        self._db.save_session(
            retailer=retailer,
            cookies=session.cookies,
            auth_token=session.auth_token,
            cart_token=session.cart_token,
            is_valid=True,
            expires_at=session.expires_at,
        )

    def load_session(self, retailer: str) -> SessionState | None:
        """Load a persisted session and check if it's still valid.

        The session is considered valid only if:
        1. A record exists in the database.
        2. ``is_valid`` is True in the database.
        3. ``expires_at`` has not passed (UTC).

        Args:
            retailer: Retailer name.

        Returns:
            SessionState if the session is valid and not expired, else None.
        """
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
        """Mark a retailer's persisted session as invalid.

        Args:
            retailer: Retailer name.
        """
        self._db.invalidate_session(retailer)

    def load_all_sessions(self) -> dict[str, SessionState]:
        """Load all valid, non-expired sessions from the database.

        Returns:
            Dict mapping retailer name → SessionState.
        """
        result: dict[str, SessionState] = {}
        # We need to iterate over all retailers with stored sessions.
        # Query the DB directly for all rows.
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT retailer FROM session_state"
            ).fetchall()

        for row in rows:
            retailer = row["retailer"]
            session = self.load_session(retailer)
            if session is not None:
                result[retailer] = session

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
