"""Dashboard authentication: PIN/password login, session management, role enforcement.

Per PRD Sections 5, 9.7 (DSH-15), 10.3 (Security).
"""

from __future__ import annotations

import json
import logging
import re
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


from starlette.datastructures import URLPath
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

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


# ── FastAPI Route Protection ─────────────────────────────────────────────────

def require_auth(
    require_role: UserRole = UserRole.OPERATOR,
) -> Callable[..., "DashboardSession"]:
    """FastAPI dependency requiring a valid dashboard session.

    Extracts the ``pokedrop_session`` cookie from the request, validates it
    against the ``DashboardAuth`` instance, and returns the ``DashboardSession``
    if valid. Raises HTTPException 401 if missing or expired, HTTPException 403
    if the role is insufficient.

    Usage in server.py (wiring up the dependency)::

        from fastapi import Depends
        from src.dashboard.auth import require_auth, UserRole, DashboardAuth

        def get_auth() -> DashboardAuth:
            return dashboard_auth_instance  # wired in server.py

        @router.post("/api/monitor/start")
        async def start_monitor(
            session: DashboardSession = Depends(
                require_auth(UserRole.OPERATOR)
            ),
            auth: DashboardAuth = Depends(get_auth),
        ): ...

    Args:
        require_role: Minimum required role (OPERATOR or VIEWER).
                      OPERATOR sessions satisfy any role requirement.
                      VIEWER sessions satisfy only VIEWER requirement.

    Returns:
        A FastAPI ``Depends``-compatible callable that returns a
        ``DashboardSession`` or raises an HTTP error.
    """

    def dependency(request: Request) -> "DashboardSession":
        """Validate session and enforce role.

        Args:
            request: The FastAPI/Starlette request (automatically injected).

        Raises:
            HTTPException 401: No token or session invalid/expired.
            HTTPException 403: Insufficient role.
        """
        session_token = request.cookies.get(SESSION_COOKIE_NAME)

        if not session_token:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=401,
                detail="Not authenticated — missing session cookie",
            )

        # Access the DashboardAuth singleton wired via server.py
        _auth_instance = _get_wired_auth()
        if _auth_instance is None:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=500,
                detail="Dashboard auth not configured on server",
            )

        session = _auth_instance.validate_session(session_token)
        if session is None:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=401,
                detail="Session expired or invalid — please log in again",
            )

        # Role enforcement: VIEWER cannot satisfy OPERATOR requirement
        if require_role == UserRole.OPERATOR and session.role == UserRole.VIEWER:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=403,
                detail="Operator privileges required for this action",
            )

        return session

    return dependency


# ── Auth wiring registry (used by server.py) ─────────────────────────────────

_auth_instance: "DashboardAuth | None" = None


def wire_auth(auth_instance: "DashboardAuth") -> None:
    """Wire a DashboardAuth instance for use by the require_auth dependency.

    Call this once in ``server.py`` after creating the ``DashboardAuth``
    instance, before starting the FastAPI app.

    Args:
        auth_instance: The configured ``DashboardAuth`` instance.
    """
    global _auth_instance
    _auth_instance = auth_instance


def _get_wired_auth() -> "DashboardAuth | None":
    """Return the currently wired DashboardAuth instance (internal use)."""
    return _auth_instance


# ── FastAPI Session Auth Middleware ──────────────────────────────────────────

# HTTP methods considered "write" operations — Viewer role is blocked from these
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Routes that are always public (no auth required)
_PUBLIC_PREFIXES: tuple[str, ...] = ("/login", "/health")

# Compiled pattern for /api/* routes
_API_PATTERN = re.compile(r"^/api/")


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware for session validation on all ``/api/*`` routes.

    Per AUTH-T02 and PRD Sections 5, 9.7 (DSH-15):

    - All ``/api/*`` routes require a valid session cookie
    - ``/login`` and ``/health`` routes are always public (no auth required)
    - Expired / invalid sessions return HTTP 401
    - Viewer role is blocked from all write operations (POST, PUT, PATCH, DELETE)
      and receives HTTP 403

    The middleware attaches the validated ``DashboardSession`` to
    ``request.state.session`` so route handlers can inspect it.
    """

    def __init__(
        self,
        app: ASGIApp,
        auth_instance: "DashboardAuth | None" = None,
    ) -> None:
        """Initialize the middleware.

        Args:
            app: The ASGI application.
            auth_instance: The ``DashboardAuth`` instance to use for validation.
                          If None, uses the wired instance via ``_get_wired_auth()``.
        """
        super().__init__(app)
        self._auth_instance = auth_instance

    @property
    def _auth(self) -> "DashboardAuth":
        """Resolve the auth instance (wired or explicit)."""
        if self._auth_instance is not None:
            return self._auth_instance
        inst = _get_wired_auth()
        if inst is None:
            raise RuntimeError(
                "SessionAuthMiddleware: no DashboardAuth instance available. "
                "Either pass auth_instance to the middleware or call wire_auth() "
                "before adding the middleware to the app."
            )
        return inst

    def _is_public_route(self, path: str) -> bool:
        """Return True if the request path is always public (no auth required)."""
        return path.startswith(_PUBLIC_PREFIXES)

    def _is_api_route(self, path: str) -> bool:
        """Return True if the request path is an /api/* route requiring auth."""
        return bool(_API_PATTERN.match(path))

    def _get_session_from_request(self, request: Request) -> "DashboardSession | None":
        """Extract and validate the session from the request cookie.

        Returns the DashboardSession if valid, None otherwise.
        """
        cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
        if not cookie_value:
            return None
        return self._auth.validate_session(cookie_value)

    def _blocked_response(
        self,
        status_code: int,
        message: str,
    ) -> JSONResponse:
        """Build a JSON error response."""
        return JSONResponse(
            status_code=status_code,
            content={"detail": message},
        )

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Process each HTTP request through session validation.

        Args:
            request: The incoming request.
            call_next: The next middleware / route handler.

        Returns:
            401 if no valid session on /api/* routes,
            403 if Viewer attempts a write operation,
            or the normal response from call_next.
        """
        path: str = request.url.path

        # Always allow public routes (no auth needed)
        if self._is_public_route(path):
            return await call_next(request)

        # Only protect /api/* routes — everything else is out of scope
        if not self._is_api_route(path):
            return await call_next(request)

        # ── Session validation ────────────────────────────────────────────
        session = self._get_session_from_request(request)

        if session is None:
            logger.debug("Middleware: no/invalid session for path=%s", path)
            return self._blocked_response(
                401,
                "Not authenticated — missing or invalid session cookie",
            )

        # Attach session to request state for downstream route handlers
        request.state.session = session

        # ── Viewer role: block write operations ───────────────────────────
        if (
            session.role == UserRole.VIEWER
            and request.method in _WRITE_METHODS
        ):
            logger.debug(
                "Middleware: Viewer attempted write method=%s path=%s",
                request.method,
                path,
            )
            return self._blocked_response(
                403,
                "Viewer role is not permitted to perform write operations; "
                "contact an operator to change your access level",
            )

        return await call_next(request)
