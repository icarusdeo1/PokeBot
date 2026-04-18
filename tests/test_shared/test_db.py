"""Tests for shared/db.py (SHARED-T02: SQLite state.db schema)."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.shared.db import DatabaseManager


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Provide a temporary DB path for each test."""
    return tmp_path / "test_state.db"


@pytest.fixture
def db(db_path: Path) -> DatabaseManager:
    """Provide an initialized DatabaseManager backed by a temp DB."""
    manager = DatabaseManager(db_path).initialize()
    yield manager
    manager.close()


class TestDatabaseManagerInit:
    """Test DatabaseManager initialization and schema creation."""

    def test_initialize_creates_tables(self, db_path: Path) -> None:
        """initialize() should create all required tables."""
        db = DatabaseManager(db_path).initialize()
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        conn.close()
        db.close()
        assert "events" in tables
        assert "command_queue" in tables
        assert "session_state" in tables
        assert "drop_windows" in tables
        assert "captcha_spend" in tables

    def test_initialize_idempotent(self, db_path: Path) -> None:
        """Calling initialize() twice should not raise."""
        db = DatabaseManager(db_path).initialize()
        db.initialize()  # should not raise
        db.close()

    def test_default_path_is_state_db(self) -> None:
        """Default path should be state.db."""
        manager = DatabaseManager()
        assert manager.path == Path("state.db")

    def test_custom_path(self, tmp_path: Path) -> None:
        """Custom path should be respected."""
        manager = DatabaseManager(tmp_path / "my.db")
        assert manager.path == tmp_path / "my.db"


class TestEventsTable:
    """Test events table operations."""

    def test_log_event_inserts_row(self, db: DatabaseManager) -> None:
        """log_event should insert a row and return its id."""
        event_id = db.log_event(
            event="STOCK_DETECTED",
            item="Pikachu Plush",
            retailer="target",
            attempt=1,
        )
        assert event_id is not None
        assert event_id > 0

    def test_log_event_captures_fields(self, db: DatabaseManager) -> None:
        """log_event should store all provided fields correctly."""
        db.log_event(
            event="CHECKOUT_SUCCESS",
            item="Charizard Box",
            retailer="walmart",
            order_id="ORDER-123",
            attempt=2,
        )
        events = db.get_recent_events(limit=1)
        assert len(events) == 1
        ev = events[0]
        assert ev["event"] == "CHECKOUT_SUCCESS"
        assert ev["item"] == "Charizard Box"
        assert ev["retailer"] == "walmart"
        assert ev["order_id"] == "ORDER-123"
        assert ev["attempt"] == 2
        assert ev["error"] == ""

    def test_log_event_with_error(self, db: DatabaseManager) -> None:
        """log_event should store error field correctly."""
        db.log_event(
            event="CHECKOUT_FAILED",
            item="Bulbasaur",
            retailer="bestbuy",
            error="Payment declined",
            attempt=1,
        )
        events = db.get_recent_events(limit=1)
        assert events[0]["error"] == "Payment declined"

    def test_get_recent_events_order(self, db: DatabaseManager) -> None:
        """get_recent_events should return events in DESC timestamp order."""
        db.log_event(event="FIRST", item="X", retailer="t")
        db.log_event(event="SECOND", item="X", retailer="t")
        events = db.get_recent_events(limit=5)
        assert events[0]["event"] == "SECOND"
        assert events[1]["event"] == "FIRST"

    def test_get_recent_events_filter_event_type(self, db: DatabaseManager) -> None:
        """Filter by event_type should work."""
        db.log_event(event="STOCK_DETECTED", item="A", retailer="t")
        db.log_event(event="CHECKOUT_FAILED", item="B", retailer="t")
        filtered = db.get_recent_events(event_type="STOCK_DETECTED")
        assert len(filtered) == 1
        assert filtered[0]["event"] == "STOCK_DETECTED"

    def test_get_recent_events_filter_retailer(self, db: DatabaseManager) -> None:
        """Filter by retailer should work."""
        db.log_event(event="E1", item="X", retailer="target")
        db.log_event(event="E2", item="X", retailer="walmart")
        filtered = db.get_recent_events(retailer="walmart")
        assert len(filtered) == 1
        assert filtered[0]["retailer"] == "walmart"

    def test_get_recent_events_filter_item(self, db: DatabaseManager) -> None:
        """Filter by item should work."""
        db.log_event(event="E1", item="pikachu", retailer="t")
        db.log_event(event="E2", item="charizard", retailer="t")
        filtered = db.get_recent_events(item="pikachu")
        assert len(filtered) == 1
        assert filtered[0]["item"] == "pikachu"

    def test_get_recent_events_respects_limit(self, db: DatabaseManager) -> None:
        """Limit parameter should be respected."""
        for i in range(10):
            db.log_event(event=f"E{i}", item="X", retailer="t")
        events = db.get_recent_events(limit=3)
        assert len(events) == 3


class TestCommandQueue:
    """Test command queue operations."""

    def test_enqueue_command(self, db: DatabaseManager) -> None:
        """enqueue_command should insert a pending command."""
        cmd_id = db.enqueue_command("start", {"items": ["pikachu"]})
        assert cmd_id is not None
        assert cmd_id > 0

    def test_claim_pending_command_returns_oldest(self, db: DatabaseManager) -> None:
        """claim_pending_command should return the oldest pending command."""
        db.enqueue_command("stop")
        db.enqueue_command("start")  # second, younger
        # First command should be claimed
        claimed = db.claim_pending_command()
        assert claimed is not None
        assert claimed["command"] == "stop"
        assert claimed["status"] == "processing"

    def test_claim_pending_command_returns_none_when_empty(self, db: DatabaseManager) -> None:
        """claim_pending_command should return None when queue is empty."""
        result = db.claim_pending_command()
        assert result is None

    def test_claim_pending_command_marks_as_processing(self, db: DatabaseManager) -> None:
        """claim_pending_command should atomically set status to 'processing'."""
        db.enqueue_command("dryrun")
        claimed = db.claim_pending_command()
        assert claimed["status"] == "processing"
        # Second claim should return None (already claimed)
        assert db.claim_pending_command() is None

    def test_complete_command(self, db: DatabaseManager) -> None:
        """complete_command should update command status."""
        cmd_id = db.enqueue_command("start")
        db.claim_pending_command()
        db.complete_command(cmd_id, "completed")
        # Verify it's no longer claimable
        assert db.claim_pending_command() is None

    def test_get_pending_commands(self, db: DatabaseManager) -> None:
        """get_pending_commands should return all pending entries."""
        db.enqueue_command("a")
        db.enqueue_command("b")
        pending = db.get_pending_commands()
        assert len(pending) == 2

    def test_enqueue_command_with_args(self, db: DatabaseManager) -> None:
        """enqueue_command should serialize args as JSON."""
        db.enqueue_command("start", {"retailer": "target", "items": ["sku1", "sku2"]})
        pending = db.get_pending_commands()
        args = json.loads(pending[0]["args"])
        assert args["retailer"] == "target"
        assert args["items"] == ["sku1", "sku2"]


class TestSessionState:
    """Test session state persistence."""

    def test_save_and_load_session(self, db: DatabaseManager) -> None:
        """save_session + load_session should round-trip correctly."""
        cookies = {"session_id": "abc123", "auth_token": "xyz"}
        db.save_session(
            retailer="target",
            cookies=cookies,
            auth_token="auth123",
            cart_token="cart456",
            is_valid=True,
        )
        session = db.load_session("target")
        assert session is not None
        assert session["cookies"]["session_id"] == "abc123"
        assert session["auth_token"] == "auth123"
        assert session["cart_token"] == "cart456"
        assert session["is_valid"] is True

    def test_load_session_returns_none_for_unknown_retailer(self, db: DatabaseManager) -> None:
        """load_session should return None for retailers not in DB."""
        result = db.load_session("unknown")
        assert result is None

    def test_save_session_replaces_existing(self, db: DatabaseManager) -> None:
        """Saving a session for a retailer should replace existing data."""
        db.save_session(retailer="target", cookies={"a": "1"}, auth_token="old")
        db.save_session(retailer="target", cookies={"b": "2"}, auth_token="new")
        session = db.load_session("target")
        assert session["cookies"]["b"] == "2"
        assert session["auth_token"] == "new"

    def test_invalidate_session(self, db: DatabaseManager) -> None:
        """invalidate_session should set is_valid to False."""
        db.save_session(retailer="target", cookies={}, is_valid=True)
        db.invalidate_session("target")
        session = db.load_session("target")
        assert session is not None
        assert session["is_valid"] is False

    def test_save_session_with_expires_at(self, db: DatabaseManager) -> None:
        """save_session should persist expires_at field."""
        future = "2026-04-20T15:00:00+00:00"
        db.save_session(
            retailer="target",
            cookies={"s": "v"},
            auth_token="at",
            cart_token="ct",
            is_valid=True,
            expires_at=future,
        )
        session = db.load_session("target")
        assert session is not None
        assert session["expires_at"] == future

    def test_load_session_expires_at_empty_string_when_not_set(self, db: DatabaseManager) -> None:
        """load_session should return empty string for expires_at when not set."""
        db.save_session(retailer="target", cookies={}, is_valid=True)
        session = db.load_session("target")
        assert session is not None
        assert session["expires_at"] == ""


class TestDropWindows:
    """Test drop windows CRUD operations."""

    def test_save_and_get_drop_windows(self, db: DatabaseManager) -> None:
        """save_drop_window + get_drop_windows should round-trip."""
        db.save_drop_window(
            item="Pikachu Plush",
            retailer="target",
            drop_datetime="2026-04-20T09:00:00Z",
            prewarm_minutes=15,
            enabled=True,
            max_cart_quantity=2,
        )
        windows = db.get_drop_windows()
        assert len(windows) == 1
        w = windows[0]
        assert w["item"] == "Pikachu Plush"
        assert w["retailer"] == "target"
        assert w["prewarm_minutes"] == 15
        assert w["enabled"] == 1
        assert w["max_cart_quantity"] == 2

    def test_get_drop_windows_enabled_only(self, db: DatabaseManager) -> None:
        """enabled_only filter should work."""
        db.save_drop_window(item="A", retailer="t", drop_datetime="2030-01-01T00:00:00Z", enabled=True)
        db.save_drop_window(item="B", retailer="t", drop_datetime="2030-01-02T00:00:00Z", enabled=False)
        enabled = db.get_drop_windows(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0]["item"] == "A"

    def test_delete_drop_window(self, db: DatabaseManager) -> None:
        """delete_drop_window should remove the entry."""
        window_id = db.save_drop_window(
            item="X", retailer="t", drop_datetime="2030-01-01T00:00:00Z"
        )
        db.delete_drop_window(window_id)
        windows = db.get_drop_windows()
        assert all(w["item"] != "X" for w in windows)

    def test_prune_past_drop_windows(self, db: DatabaseManager) -> None:
        """prune_past_drop_windows should remove windows with past datetimes."""
        # Past window
        db.save_drop_window(
            item="PAST", retailer="t", drop_datetime="2020-01-01T00:00:00Z"
        )
        # Future window
        db.save_drop_window(
            item="FUTURE", retailer="t", drop_datetime="2099-01-01T00:00:00Z"
        )
        pruned = db.prune_past_drop_windows()
        assert pruned >= 1
        windows = db.get_drop_windows()
        assert all(w["item"] != "PAST" for w in windows)


class TestCaptchaBudget:
    """Test CAPTCHA budget tracking."""

    def test_log_captcha_spend(self, db: DatabaseManager) -> None:
        """log_captcha_spend should insert a row."""
        db.log_captcha_spend(
            amount_usd=0.50,
            solve_time_ms=5000,
            retailer="target",
            captcha_type="turnstile",
        )
        spend = db.get_daily_captcha_spend()
        assert spend == 0.50

    def test_get_daily_captcha_spend_accumulates(self, db: DatabaseManager) -> None:
        """Multiple logs should accumulate correctly."""
        db.log_captcha_spend(amount_usd=0.50, solve_time_ms=5000, retailer="t")
        db.log_captcha_spend(amount_usd=0.75, solve_time_ms=8000, retailer="t")
        spend = db.get_daily_captcha_spend()
        assert spend == 1.25

    def test_get_daily_captcha_spend_none_returns_zero(self, db: DatabaseManager) -> None:
        """get_daily_captcha_spend should return 0.0 when no records."""
        spend = db.get_daily_captcha_spend()
        assert spend == 0.0


class TestThreadSafety:
    """Test thread-safety of DatabaseManager."""

    def test_concurrent_writes(self, db_path: Path) -> None:
        """Concurrent writes from multiple threads should not corrupt DB."""
        manager = DatabaseManager(db_path).initialize()
        errors: list[Exception] = []
        barrier = threading.Barrier(5)

        def writer(thread_id: int) -> None:
            try:
                barrier.wait()
                for i in range(50):
                    manager.log_event(
                        event=f"T{thread_id}_E{i}",
                        item="X",
                        retailer="t",
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        manager.close()
        assert not errors, f"Thread errors: {errors}"
        # Should have 250 events
        manager2 = DatabaseManager(db_path).initialize()
        events = manager2.get_recent_events(limit=1000)
        manager2.close()
        assert len(events) == 250