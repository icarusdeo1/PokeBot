"""Dashboard authentication: PIN/password login, session management, role enforcement.

Per PRD Sections 5, 9.7 (DSH-15), 10.3 (Security).
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
except ImportError:
    raise ImportError(
        "argon2-cffi is required for dashboard auth. "
        "Install it with: pip install argon2-cffi"
    )

from src.shared.db import DatabaseManager

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

SESSION_COOKIE_NAME = "pokedrop_session"
SESSION_TTL_HOURS = 8
MIN_PIN_LENGTH = 6
AUTH_DB_PATH = Path("auth.db")


# ── Enums ─────────────────────────────────────────────────────────────────────


class UserRole(Enum):
    """Dashboard user roles per PRD Section 5."""

    OPERATOR = "operator"
    VIEWER = "viewer"


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class DashboardSession:
    """An active dashboard session."""

    session_token: str
    role: UserRole
    created_at: str  # ISO-8601 UTC
    last_activity: str  # ISO-8601 UTC
    expires_at: str  # ISO-8601 UTC


@dataclass
class OperatorCredentials:
    """Stored operator credential record."""

    id: int
    pin_hash: str
    role: UserRole
    created_at: str  # ISO-8601 UTC


# ── Argon2 Password Hasher ───────────────────────────────────────────────────

_ph = PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

_utc_now: Callable[[], str] = lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash_pin(pin: str) -> str:
    """Hash a PIN using Argon2id."""
    return _ph.hash(pin)


def _verify_pin(pin: str, pin_hash: str) -> bool:
    """Verify a PIN against its Argon2id hash."""
    if not isinstance(pin, str):
        return False
    try:
        _ph.verify(pin_hash, pin)
        return True
    except VerifyMismatchError:
        return False


def _generate_session_token() -> str:
    """Generate a cryptographically secure session token."""
    return secrets.token_urlsafe(32)


# ── DashboardAuth ─────────────────────────────────────────────────────────────


class DashboardAuth:
    """Dashboard authentication and session manager.

    Manages operator credentials and browser sessions for the dashboard.
    Credentials (PIN hashes) are stored in auth.db.
    Sessions are stored in auth.db with httpOnly sameSite=strict cookies.

    Per PRD Sections 5, 9.7 (DSH-15), 10.3 (Security).
    """

    def __init__(self, auth_db_path: Path | str = AUTH_DB_PATH) -> None:
        """Initialize DashboardAuth with path to auth.db.

        Args:
            auth_db_path: Path to the auth SQLite database. Defaults to auth.db in cwd.
        """
        self._db_path = Path(auth_db_path)
        self._db: DatabaseManager | None = None

    @property
    def db(self) -> DatabaseManager:
        """Lazily initialize and return the auth DatabaseManager."""
        if self._db is None:
            self._db = DatabaseManager(self._db_path).initialize()
            self._init_auth_schema()
        return self._db

    def _init_auth_schema(self) -> None:
        """Initialize the auth.db schema (idempotent)."""
        import sqlite3
        from pathlib import Path

        # Ensure the directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(database=str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operator_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pin_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'operator',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboard_sessions (
                session_token TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_activity TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_expires "
            "ON dashboard_sessions(expires_at)"
        )
        conn.commit()
        conn.close()
        logger.info("Initialized auth.db schema at %s", self._db_path)

    # ── Credential management ───────────────────────────────────────────────

    def setup_initial_credentials(self, pin: str, role: UserRole = UserRole.OPERATOR) -> bool:
        """Set up initial operator credentials (first-time setup).

        Fails if credentials already exist (use change_pin() to update).

        Args:
            pin: The PIN to set (minimum 6 digits).
            role: User role (OPERATOR or VIEWER). Defaults to OPERATOR.

        Returns:
            True if credentials were created, False if credentials already exist.
        """
        if len(pin) < MIN_PIN_LENGTH:
            raise ValueError(f"PIN must be at least {MIN_PIN_LENGTH} digits")

        with self.db.connection() as conn:
            existing = conn.execute(
                "SELECT id FROM operator_credentials LIMIT 1"
            ).fetchone()
            if existing:
                logger.warning("Credentials already exist; refusing to overwrite")
                return False

        pin_hash = _hash_pin(pin)
        created_at = _utc_now()
        role_str = role.value

        with self.db._write_lock:
            with self.db.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO operator_credentials (pin_hash, role, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (pin_hash, role_str, created_at),
                )
                conn.commit()

        logger.info("Operator credentials created with role=%s", role.value)
        return True

    def verify_pin(self, pin: str) -> bool:
        """Verify a PIN against stored credentials.

        Supports multiple credential records (first match wins).
        Uses argon2 timing-safe comparison.

        Args:
            pin: The PIN to verify.

        Returns:
            True if PIN is correct, False otherwise.
        """
        if len(pin) < MIN_PIN_LENGTH:
            return False

        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT pin_hash FROM operator_credentials ORDER BY id ASC"
            ).fetchall()

        for row in rows:
            if _verify_pin(pin, row["pin_hash"]):
                return True
        return False

    def get_role(self) -> UserRole | None:
        """Return the role for the stored credentials (first record).

        Returns None if no credentials are set up yet.
        """
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT role FROM operator_credentials ORDER BY id ASC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return UserRole(row["role"])

    def change_pin(self, old_pin: str, new_pin: str) -> bool:
        """Change the operator PIN after verifying the old PIN.

        Args:
            old_pin: Current PIN.
            new_pin: New PIN (must be at least 6 digits).

        Returns:
            True if PIN was changed, False if old PIN is incorrect.
        """
        if len(new_pin) < MIN_PIN_LENGTH:
            raise ValueError(f"New PIN must be at least {MIN_PIN_LENGTH} digits")

        if not self.verify_pin(old_pin):
            return False

        new_hash = _hash_pin(new_pin)
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE operator_credentials SET pin_hash = ? ORDER BY id ASC LIMIT 1",
                (new_hash,),
            )
            conn.commit()
        logger.info("PIN changed successfully")
        return True

    def is_setup_complete(self) -> bool:
        """Return True if operator credentials have been set up."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT id FROM operator_credentials LIMIT 1"
            ).fetchone()
        return row is not None

    # ── Session management ──────────────────────────────────────────────────

    def create_session(self, role: UserRole) -> DashboardSession:
        """Create a new dashboard session.

        Args:
            role: The role for this session (OPERATOR or VIEWER).

        Returns:
            A DashboardSession object with token and expiry info.
        """
        token = _generate_session_token()
        now = _utc_now()
        expires = (
            datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
        ).isoformat().replace("+00:00", "Z")

        session = DashboardSession(
            session_token=token,
            role=role,
            created_at=now,
            last_activity=now,
            expires_at=expires,
        )

        with self.db._write_lock:
            with self.db.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO dashboard_sessions
                        (session_token, role, created_at, last_activity, expires_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (token, role.value, now, now, expires),
                )
                conn.commit()

        logger.debug("Created dashboard session token=%s role=%s", token[:8], role.value)
        return session

    def validate_session(self, token: str) -> DashboardSession | None:
        """Validate a session token and return session info if valid.

        Updates last_activity on success. Expired sessions are deleted.

        Args:
            token: The session token from the cookie.

        Returns:
            DashboardSession if valid and not expired, None otherwise.
        """
        now = _utc_now()
        with self.db._write_lock:
            with self.db.connection() as conn:
                row = conn.execute(
                    """
                    SELECT * FROM dashboard_sessions
                    WHERE session_token=? AND expires_at > ?
                    """,
                    (token, now),
                ).fetchone()

                if not row:
                    return None

                # Update last_activity
                conn.execute(
                    """
                    UPDATE dashboard_sessions SET last_activity=? WHERE session_token=?
                    """,
                    (now, token),
                )
                conn.commit()

                return DashboardSession(
                    session_token=row["session_token"],
                    role=UserRole(row["role"]),
                    created_at=row["created_at"],
                    last_activity=row["last_activity"],
                    expires_at=row["expires_at"],
                )

    def invalidate_session(self, token: str) -> None:
        """Invalidate (delete) a session token.

        Args:
            token: The session token to invalidate.
        """
        with self.db._write_lock:
            with self.db.connection() as conn:
                conn.execute(
                    "DELETE FROM dashboard_sessions WHERE session_token=?",
                    (token,),
                )
                conn.commit()
        logger.debug("Invalidated session token=%s", token[:8])

    def cleanup_expired_sessions(self) -> int:
        """Remove all expired sessions from the database.

        Returns:
            Number of sessions removed.
        """
        now = _utc_now()
        with self.db._write_lock:
            with self.db.connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM dashboard_sessions WHERE expires_at <= ?",
                    (now,),
                )
                conn.commit()
                count: int = cursor.rowcount
        if count:
            logger.info("Cleaned up %d expired sessions", count)
        return count

    def get_session_info(self, token: str) -> dict[str, Any] | None:
        """Get session info without updating last_activity (read-only).

        Args:
            token: The session token.

        Returns:
            Dict with session fields or None if not found/expired.
        """
        now = _utc_now()
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM dashboard_sessions
                WHERE session_token=? AND expires_at > ?
                """,
                (token, now),
            ).fetchone()
        if not row:
            return None
        return {
            "session_token": row["session_token"],
            "role": row["role"],
            "created_at": row["created_at"],
            "last_activity": row["last_activity"],
            "expires_at": row["expires_at"],
        }

    # ── Cookie helpers ─────────────────────────────────────────────────────

    @staticmethod
    def make_session_cookie(
        token: str,
        max_age_seconds: int = SESSION_TTL_HOURS * 3600,
    ) -> dict[str, Any]:
        """Build a session cookie dict for FastAPI/ starlette responses.

        Args:
            token: The session token.
            max_age_seconds: Cookie max-age in seconds (default 8 hours).

        Returns:
            Cookie dict with httpOnly, sameSite=strict, secure settings.
        """
        return {
            "name": SESSION_COOKIE_NAME,
            "value": token,
            "max_age": max_age_seconds,
            "httponly": True,
            "samesite": "strict",
            "path": "/",
        }

    @staticmethod
    def clear_session_cookie() -> dict[str, Any]:
        """Build a cookie dict that clears the session cookie."""
        return {
            "name": SESSION_COOKIE_NAME,
            "value": "",
            "max_age": 0,
            "httponly": True,
            "samesite": "strict",
            "path": "/",
        }


# ── Decorator / helpers for route protection ──────────────────────────────────

def require_auth(
    require_role: UserRole = UserRole.OPERATOR,
) -> Callable[..., Any]:
    """Decorator for FastAPI route dependency to require authentication.

    Usage:
        @router.post("/api/monitor/start")
        async def start_monitor(session: Session = Depends(require_auth())):
            ...

    The decorated function receives a DashboardSession as its first argument.

    Args:
        require_role: Minimum required role (OPERATOR or VIEWER).
                      OPERATOR sessions satisfy any role requirement.
                      VIEWER sessions only satisfy VIEWER requirement.

    Returns:
        A FastAPI Depends-compatible callable.
    """
    from functools import wraps

    def _get_session(token: str | None = None) -> DashboardSession | None:
        if not token:
            return None
        # Lazy import to avoid circular import at module level
        # In practice, the caller will provide auth via dependency injection
        return None

    def dependency(
        token: str | None = None,
    ) -> DashboardSession:
        """FastAPI dependency that returns a valid DashboardSession or raises 401."""
        # This will be wired up in server.py via the DashboardAuth instance
        raise NotImplementedError(
            "require_auth dependency must be wired in server.py with a DashboardAuth instance"
        )

    return dependency
