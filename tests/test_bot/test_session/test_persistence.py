"""Tests for src.bot.session.persistence."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.bot.session.persistence import SessionPersistence, _parse_datetime
from src.shared.db import DatabaseManager
from src.shared.models import SessionState


# ─── _parse_datetime ───────────────────────────────────────────────────────

class TestParseDatetime:
    def test_parses_utc_with_z_suffix(self) -> None:
        dt = _parse_datetime("2026-04-18T12:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_parses_iso8601_with_offset(self) -> None:
        dt = _parse_datetime("2026-04-18T12:00:00+00:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_treats_naive_as_utc(self) -> None:
        dt = _parse_datetime("2026-04-18T12:00:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_returns_none_for_empty(self) -> None:
        assert _parse_datetime("") is None

    def test_returns_none_for_invalid(self) -> None:
        assert _parse_datetime("not-a-date") is None


# ─── SessionPersistence ────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_state.db"


@pytest.fixture
def db(db_path: Path) -> DatabaseManager:
    manager = DatabaseManager(db_path)
    manager.initialize()
    return manager


@pytest.fixture
def persistence(db: DatabaseManager) -> SessionPersistence:
    return SessionPersistence(db)


class TestSaveSession:
    def test_save_session_stores_in_db(
        self,
        db: DatabaseManager,
        persistence: SessionPersistence,
    ) -> None:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=2)
        from src.bot.session.prewarmer import PrewarmSession

        session = PrewarmSession(
            retailer="target",
            account_name="primary",
            cookies={"session_id": "abc123"},
            auth_token="auth_token_xyz",
            cart_token="cart_token_xyz",
            prewarmed_at=now.isoformat(),
            expires_at=expires.isoformat(),
            adapter_name="TargetAdapter",
        )

        persistence.save_session("target", session)

        # Verify in DB
        row = db.load_session("target")
        assert row is not None
        assert row["cookies"] == {"session_id": "abc123"}
        assert row["auth_token"] == "auth_token_xyz"
        assert row["cart_token"] == "cart_token_xyz"
        assert row["is_valid"] is True
        assert row["expires_at"] == expires.isoformat()

    def test_save_session_overwrites_existing(
        self,
        db: DatabaseManager,
        persistence: SessionPersistence,
    ) -> None:
        from src.bot.session.prewarmer import PrewarmSession

        session1 = PrewarmSession(
            retailer="target",
            account_name="primary",
            cookies={"v": "1"},
            auth_token="at1",
            cart_token="ct1",
            prewarmed_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            adapter_name="TargetAdapter",
        )
        session2 = PrewarmSession(
            retailer="target",
            account_name="primary",
            cookies={"v": "2"},
            auth_token="at2",
            cart_token="ct2",
            prewarmed_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            adapter_name="TargetAdapter",
        )

        persistence.save_session("target", session1)
        persistence.save_session("target", session2)

        row = db.load_session("target")
        assert row is not None
        assert row["cookies"] == {"v": "2"}
        assert row["auth_token"] == "at2"


class TestLoadSession:
    def test_load_session_returns_none_when_not_found(
        self,
        persistence: SessionPersistence,
    ) -> None:
        assert persistence.load_session("nonexistent") is None

    def test_load_session_returns_none_when_expired(
        self,
        db: DatabaseManager,
        persistence: SessionPersistence,
    ) -> None:
        # Manually insert expired session into DB
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db.save_session(
            retailer="target",
            cookies={"session": "val"},
            auth_token="at",
            cart_token="ct",
            is_valid=True,
            expires_at=past,
        )

        result = persistence.load_session("target")
        assert result is None

        # Should also invalidate in DB
        row = db.load_session("target")
        assert row is not None
        assert row["is_valid"] is False

    def test_load_session_returns_none_when_invalid(
        self,
        db: DatabaseManager,
        persistence: SessionPersistence,
    ) -> None:
        db.save_session(
            retailer="target",
            cookies={"session": "val"},
            auth_token="at",
            cart_token="ct",
            is_valid=False,
            expires_at="",
        )

        result = persistence.load_session("target")
        assert result is None

    def test_load_session_returns_session_when_valid(
        self,
        db: DatabaseManager,
        persistence: SessionPersistence,
    ) -> None:
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        db.save_session(
            retailer="target",
            cookies={"session": "val", "count": "3"},
            auth_token="auth_tok",
            cart_token="cart_tok",
            is_valid=True,
            expires_at=future,
        )

        result = persistence.load_session("target")
        assert result is not None
        assert result.cookies == {"session": "val", "count": "3"}
        assert result.auth_token == "auth_tok"
        assert result.cart_token == "cart_tok"
        assert result.expires_at == future
        assert result.is_valid is True


class TestLoadAllSessions:
    def test_load_all_sessions_returns_all_valid(
        self,
        db: DatabaseManager,
        persistence: SessionPersistence,
    ) -> None:
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        db.save_session("target", {"t": "1"}, auth_token="at1", cart_token="ct1", is_valid=True, expires_at=future)
        db.save_session("walmart", {"w": "2"}, auth_token="at2", cart_token="ct2", is_valid=True, expires_at=future)

        result = persistence.load_all_sessions()
        assert set(result.keys()) == {"target", "walmart"}

    def test_load_all_sessions_skips_invalid_and_expired(
        self,
        db: DatabaseManager,
        persistence: SessionPersistence,
    ) -> None:
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        db.save_session("valid", {"v": "1"}, auth_token="at", cart_token="ct", is_valid=True, expires_at=future)
        db.save_session("invalid", {"i": "2"}, auth_token="at", cart_token="ct", is_valid=False, expires_at=future)
        db.save_session("expired", {"e": "3"}, auth_token="at", cart_token="ct", is_valid=True, expires_at=past)

        result = persistence.load_all_sessions()
        assert set(result.keys()) == {"valid"}


class TestInvalidateSession:
    def test_invalidate_session(
        self,
        db: DatabaseManager,
        persistence: SessionPersistence,
    ) -> None:
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        db.save_session("target", {"s": "v"}, auth_token="at", cart_token="ct", is_valid=True, expires_at=future)

        persistence.invalidate_session("target")

        row = db.load_session("target")
        assert row is not None
        assert row["is_valid"] is False
