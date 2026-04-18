"""Tests for dashboard authentication (src/dashboard/auth.py)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from src.dashboard.auth import (
    MIN_PIN_LENGTH,
    SESSION_COOKIE_NAME,
    SESSION_TTL_HOURS,
    UserRole,
    DashboardAuth,
    _hash_pin,
    _verify_pin,
    _generate_session_token,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def auth_db(tmp_path: Path) -> DashboardAuth:
    """Provide a DashboardAuth instance backed by a temp auth.db."""
    db_path = tmp_path / "auth.db"
    auth = DashboardAuth(db_path)
    # Ensure schema is initialized
    auth.db
    return auth


# ── PIN hashing ────────────────────────────────────────────────────────────────

class TestPinHashing:
    def test_hash_pin_produces_str(self) -> None:
        result = _hash_pin("123456")
        assert isinstance(result, str)
        assert result.startswith("$argon2")

    def test_hash_pin_different_for_same_input(self) -> None:
        """Argon2 uses a random salt, so hashes differ each time."""
        h1 = _hash_pin("123456")
        h2 = _hash_pin("123456")
        assert h1 != h2

    def test_verify_pin_correct(self) -> None:
        pin_hash = _hash_pin("123456")
        assert _verify_pin("123456", pin_hash) is True

    def test_verify_pin_incorrect(self) -> None:
        pin_hash = _hash_pin("123456")
        assert _verify_pin("000000", pin_hash) is False

    def test_verify_pin_wrong_type(self) -> None:
        """Non-string PIN returns False."""
        assert _verify_pin(123456, "$argon2id$v=19$m=65536$") is False

    def test_generate_session_token_unique(self) -> None:
        tokens = {_generate_session_token() for _ in range(100)}
        assert len(tokens) == 100


# ── DashboardAuth initialization ─────────────────────────────────────────────

class TestDashboardAuthInit:
    def test_auth_db_path_set(self, tmp_path: Path) -> None:
        auth = DashboardAuth(tmp_path / "auth.db")
        assert auth._db_path == tmp_path / "auth.db"

    def test_lazily_initializes_db(self, tmp_path: Path) -> None:
        auth = DashboardAuth(tmp_path / "auth.db")
        assert auth._db is None
        _ = auth.db
        assert auth._db is not None

    def test_schema_tables_created(self, auth_db: DashboardAuth) -> None:
        with auth_db.db.connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        table_names = {row["name"] for row in tables}
        assert "operator_credentials" in table_names
        assert "dashboard_sessions" in table_names


# ── Credential setup ──────────────────────────────────────────────────────────

class TestCredentialSetup:
    def test_setup_initial_credentials_success(self, auth_db: DashboardAuth) -> None:
        result = auth_db.setup_initial_credentials("123456")
        assert result is True
        assert auth_db.is_setup_complete() is True

    def test_setup_twice_fails(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        result = auth_db.setup_initial_credentials("654321")
        assert result is False

    def test_setup_short_pin_raises(self, auth_db: DashboardAuth) -> None:
        with pytest.raises(ValueError, match=f"at least {MIN_PIN_LENGTH}"):
            auth_db.setup_initial_credentials("12345")

    def test_get_role_after_setup(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456", role=UserRole.OPERATOR)
        assert auth_db.get_role() == UserRole.OPERATOR

    def test_get_role_viewer(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456", role=UserRole.VIEWER)
        assert auth_db.get_role() == UserRole.VIEWER

    def test_get_role_none_before_setup(self, auth_db: DashboardAuth) -> None:
        assert auth_db.get_role() is None


# ── PIN verification ──────────────────────────────────────────────────────────

class TestPinVerification:
    def test_verify_pin_correct(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        assert auth_db.verify_pin("123456") is True

    def test_verify_pin_incorrect(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        assert auth_db.verify_pin("000000") is False

    def test_verify_pin_too_short(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        assert auth_db.verify_pin("12345") is False

    def test_verify_pin_no_setup(self, auth_db: DashboardAuth) -> None:
        assert auth_db.verify_pin("123456") is False


# ── PIN change ────────────────────────────────────────────────────────────────

class TestPinChange:
    def test_change_pin_success(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        result = auth_db.change_pin("123456", "654321")
        assert result is True
        assert auth_db.verify_pin("654321") is True
        assert auth_db.verify_pin("123456") is False

    def test_change_pin_wrong_old_pin(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        result = auth_db.change_pin("000000", "654321")
        assert result is False
        assert auth_db.verify_pin("654321") is False

    def test_change_pin_new_too_short(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        with pytest.raises(ValueError, match=f"at least {MIN_PIN_LENGTH}"):
            auth_db.change_pin("123456", "12345")


# ── Session management ────────────────────────────────────────────────────────

class TestSessionManagement:
    def test_create_session_returns_session(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        session = auth_db.create_session(UserRole.OPERATOR)
        assert session.session_token is not None
        assert len(session.session_token) > 20
        assert session.role == UserRole.OPERATOR
        assert session.created_at.endswith("Z")
        assert session.expires_at.endswith("Z")

    def test_create_session_expires_in_future(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        before = time.time()
        session = auth_db.create_session(UserRole.OPERATOR)
        after = time.time()
        # expires_at should be ~8 hours from now
        from datetime import datetime, timezone
        exp_ts = datetime.fromisoformat(session.expires_at.replace("Z", "+00:00"))
        exp_unix = exp_ts.timestamp()
        assert SESSION_TTL_HOURS * 3600 - 5 < (exp_unix - before) < (exp_unix - before) + 1

    def test_validate_session_valid(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        session = auth_db.create_session(UserRole.OPERATOR)
        validated = auth_db.validate_session(session.session_token)
        assert validated is not None
        assert validated.role == UserRole.OPERATOR

    def test_validate_session_invalid_token(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        result = auth_db.validate_session("invalid_token")
        assert result is None

    def test_invalidate_session(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        session = auth_db.create_session(UserRole.OPERATOR)
        auth_db.invalidate_session(session.session_token)
        result = auth_db.validate_session(session.session_token)
        assert result is None

    def test_get_session_info(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        session = auth_db.create_session(UserRole.VIEWER)
        info = auth_db.get_session_info(session.session_token)
        assert info is not None
        assert info["role"] == "viewer"
        assert info["session_token"] == session.session_token

    def test_get_session_info_invalid(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        info = auth_db.get_session_info("invalid")
        assert info is None


# ── Cookie helpers ────────────────────────────────────────────────────────────

class TestSessionCookie:
    def test_make_session_cookie(self) -> None:
        cookie = DashboardAuth.make_session_cookie("test_token_abc")
        assert cookie["name"] == SESSION_COOKIE_NAME
        assert cookie["value"] == "test_token_abc"
        assert cookie["httponly"] is True
        assert cookie["samesite"] == "strict"
        assert cookie["max_age"] == SESSION_TTL_HOURS * 3600

    def test_clear_session_cookie(self) -> None:
        cookie = DashboardAuth.clear_session_cookie()
        assert cookie["name"] == SESSION_COOKIE_NAME
        assert cookie["value"] == ""
        assert cookie["max_age"] == 0


# ── Role enforcement ───────────────────────────────────────────────────────────

class TestRoleEnforcement:
    def test_operator_role_default(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456", role=UserRole.OPERATOR)
        assert auth_db.get_role() == UserRole.OPERATOR

    def test_viewer_role(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456", role=UserRole.VIEWER)
        assert auth_db.get_role() == UserRole.VIEWER


# ── Cleanup ───────────────────────────────────────────────────────────────────

class TestSessionCleanup:
    def test_cleanup_expired_sessions(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        session = auth_db.create_session(UserRole.OPERATOR)
        # Manually expire the session in the DB
        with auth_db.db._write_lock:
            with auth_db.db.connection() as conn:
                conn.execute(
                    "UPDATE dashboard_sessions SET expires_at='2020-01-01T00:00:00Z' "
                    "WHERE session_token=?",
                    (session.session_token,),
                )
                conn.commit()
        count = auth_db.cleanup_expired_sessions()
        assert count == 1

    def test_cleanup_none_expired(self, auth_db: DashboardAuth) -> None:
        auth_db.setup_initial_credentials("123456")
        auth_db.create_session(UserRole.OPERATOR)
        count = auth_db.cleanup_expired_sessions()
        assert count == 0
