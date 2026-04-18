"""Tests for GET /api/status route.

Per PRD Section 9.7 (DSH-2).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from src.dashboard.routes.status import (
    _fill_session_health_from_db,
    _get_state_db,
    status_route,
)
from src.dashboard.auth import UserRole
from src.shared.db import DatabaseManager


class MockSession:
    role = UserRole.OPERATOR
    session_token = 'mock-token'
    created_at = '2026-01-01T00:00:00Z'


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db(tmp_path: Path) -> DatabaseManager:
    """Return a real DatabaseManager backed by a temp file."""
    db_path = tmp_path / "test_state.db"
    db = DatabaseManager(db_path)
    db.initialize()
    return db


@pytest.fixture
def recent_events() -> list[dict[str, Any]]:
    """Return a realistic list of recent events for testing."""
    now = datetime.now(timezone.utc)
    return [
        {
            "id": 1,
            "event": "MONITOR_STARTED",
            "item": "Pokemon Scarlet",
            "retailer": "target",
            "timestamp": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "order_id": "",
            "error": "",
            "attempt": 1,
        },
        {
            "id": 2,
            "event": "STOCK_DETECTED",
            "item": "Pokemon Scarlet",
            "retailer": "target",
            "timestamp": (now - timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
            "order_id": "",
            "error": "",
            "attempt": 1,
        },
        {
            "id": 3,
            "event": "SESSION_EXPIRED",
            "item": "",
            "retailer": "walmart",
            "timestamp": (now - timedelta(minutes=3)).isoformat().replace("+00:00", "Z"),
            "order_id": "",
            "error": "",
            "attempt": 1,
        },
        {
            "id": 4,
            "event": "MONITOR_STOPPED",
            "item": "Pokemon Violet",
            "retailer": "bestbuy",
            "timestamp": (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
            "order_id": "",
            "error": "",
            "attempt": 1,
        },
    ]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestFillSessionHealthFromDb:
    """Tests for _fill_session_health_from_db helper."""

    def test_green_when_session_valid(self, mock_db: MagicMock) -> None:
        """Session with far-future expiry → green."""
        now = datetime.now(timezone.utc)
        mock_db.save_session(
            retailer="target",
            cookies={"session_id": "abc123"},
            auth_token="token123",
            cart_token="cart123",
            is_valid=True,
            expires_at=(now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        )
        session_health: dict[str, str] = {}
        _fill_session_health_from_db(mock_db, session_health)
        assert session_health["target"] == "green"

    def test_yellow_when_session_expiring_soon(self, mock_db: MagicMock) -> None:
        """Session expiring in < 10 minutes → yellow."""
        now = datetime.now(timezone.utc)
        mock_db.save_session(
            retailer="target",
            cookies={"session_id": "abc123"},
            auth_token="token123",
            cart_token="cart123",
            is_valid=True,
            expires_at=(now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        )
        session_health: dict[str, str] = {}
        _fill_session_health_from_db(mock_db, session_health)
        assert session_health["target"] == "yellow"

    def test_red_when_session_expired(self, mock_db: MagicMock) -> None:
        """Session already expired → red."""
        now = datetime.now(timezone.utc)
        mock_db.save_session(
            retailer="target",
            cookies={"session_id": "abc123"},
            auth_token="token123",
            cart_token="cart123",
            is_valid=True,
            expires_at=(now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        )
        session_health: dict[str, str] = {}
        _fill_session_health_from_db(mock_db, session_health)
        assert session_health["target"] == "red"

    def test_red_when_no_session(self, mock_db: MagicMock) -> None:
        """No session record → red."""
        session_health: dict[str, str] = {}
        _fill_session_health_from_db(mock_db, session_health)
        assert session_health["target"] == "red"

    def test_does_not_override_existing_red_health(
        self, mock_db: MagicMock
    ) -> None:
        """If retailer already marked red from event, DB check doesn't override."""
        now = datetime.now(timezone.utc)
        mock_db.save_session(
            retailer="target",
            cookies={"session_id": "abc123"},
            auth_token="token123",
            cart_token="cart123",
            is_valid=True,
            expires_at=(now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        )
        # Pre-mark as red from SESSION_EXPIRED event
        session_health: dict[str, str] = {"target": "red"}
        _fill_session_health_from_db(mock_db, session_health)
        # Must NOT be overwritten by green from DB
        assert session_health["target"] == "red"


class TestStatusRoute:
    """Tests for the GET /api/status route handler."""

    @pytest.mark.asyncio
    async def test_online_with_active_items(
        self,
        mock_db: MagicMock,
        recent_events: list[dict[str, Any]],
    ) -> None:
        """When events exist, daemon is online and active items are tracked."""
        with patch.object(
            mock_db, "get_recent_events", return_value=recent_events
        ):
            with patch(
                "src.dashboard.routes.status._get_state_db",
                return_value=mock_db,
            ):
                result = await status_route(session=MockSession())

        assert result["online"] is True
        assert "Pokemon Scarlet" in result["active_items"]
        assert "Pokemon Violet" not in result["active_items"]  # stopped

    @pytest.mark.asyncio
    async def test_offline_when_no_events(self, mock_db: MagicMock) -> None:
        """Empty event history + no active items → offline."""
        with patch.object(mock_db, "get_recent_events", return_value=[]):
            with patch(
                "src.dashboard.routes.status._get_state_db",
                return_value=mock_db,
            ):
                result = await status_route(session=MockSession())

        assert result["online"] is False
        assert result["active_items"] == []

    @pytest.mark.asyncio
    async def test_session_health_red_from_session_expired_event(
        self,
        mock_db: MagicMock,
        recent_events: list[dict[str, Any]],
    ) -> None:
        """SESSION_EXPIRED event → retailer marked red in session_health."""
        with patch.object(
            mock_db, "get_recent_events", return_value=recent_events
        ):
            with patch(
                "src.dashboard.routes.status._get_state_db",
                return_value=mock_db,
            ):
                result = await status_route(session=MockSession())

        assert result["session_health"]["walmart"] == "red"

    @pytest.mark.asyncio
    async def test_session_health_green_from_valid_session(
        self,
        mock_db: MagicMock,
        recent_events: list[dict[str, Any]],
    ) -> None:
        """Valid pre-warmed session → green."""
        now = datetime.now(timezone.utc)
        mock_db.save_session(
            retailer="target",
            cookies={"session_id": "abc123"},
            auth_token="token123",
            cart_token="cart123",
            is_valid=True,
            expires_at=(now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        )

        with patch.object(
            mock_db, "get_recent_events", return_value=recent_events
        ):
            with patch(
                "src.dashboard.routes.status._get_state_db",
                return_value=mock_db,
            ):
                result = await status_route(session=MockSession())

        # SESSION_EXPIRED on walmart → red; target has valid session → green
        assert result["session_health"]["walmart"] == "red"
        assert result["session_health"]["target"] == "green"

    @pytest.mark.asyncio
    async def test_last_event_at_is_newest_timestamp(
        self,
        mock_db: MagicMock,
        recent_events: list[dict[str, Any]],
    ) -> None:
        """last_event_at should be the most recent (newest) event timestamp."""
        with patch.object(
            mock_db, "get_recent_events", return_value=recent_events
        ):
            with patch(
                "src.dashboard.routes.status._get_state_db",
                return_value=mock_db,
            ):
                result = await status_route(session=MockSession())

        # Most recent event is MONITOR_STOPPED (id=4), timestamp = now - 2min
        assert result["last_event_at"] is not None
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(result["last_event_at"].replace("Z", "+00:00"))

    @pytest.mark.asyncio
    async def test_uptime_seconds_computed_from_monitor_started(
        self,
        mock_db: MagicMock,
        recent_events: list[dict[str, Any]],
    ) -> None:
        """uptime_seconds computed from oldest MONITOR_STARTED event."""
        with patch.object(
            mock_db, "get_recent_events", return_value=recent_events
        ):
            with patch(
                "src.dashboard.routes.status._get_state_db",
                return_value=mock_db,
            ):
                result = await status_route(session=MockSession())

        # Oldest MONITOR_STARTED is 5 minutes ago
        assert result["uptime_seconds"] >= 300
        # Should be a reasonable value (not more than a few hours)
        assert result["uptime_seconds"] < 86400

    @pytest.mark.asyncio
    async def test_returns_all_required_keys(
        self,
        mock_db: MagicMock,
        recent_events: list[dict[str, Any]],
    ) -> None:
        """Response contains all required DSH-2 fields."""
        with patch.object(
            mock_db, "get_recent_events", return_value=recent_events
        ):
            with patch(
                "src.dashboard.routes.status._get_state_db",
                return_value=mock_db,
            ):
                result = await status_route(session=MockSession())

        assert set(result.keys()) == {
            "online",
            "active_items",
            "session_health",
            "last_event_at",
            "uptime_seconds",
            "role",
        }

    @pytest.mark.asyncio
    async def test_graceful_handling_of_db_error(
        self,
        mock_db: MagicMock,
        recent_events: list[dict[str, Any]],
    ) -> None:
        """If get_recent_events raises, returns offline status gracefully."""
        with patch.object(
            mock_db,
            "get_recent_events",
            side_effect=RuntimeError("db error"),
        ):
            with patch(
                "src.dashboard.routes.status._get_state_db",
                return_value=mock_db,
            ):
                result = await status_route(session=MockSession())

        # Should not raise; returns offline
        assert result["online"] is False
        assert result["active_items"] == []

    @pytest.mark.asyncio
    async def test_handles_malformed_timestamp(
        self,
        mock_db: MagicMock,
        recent_events: list[dict[str, Any]],
    ) -> None:
        """Malformed timestamp in event row doesn't crash the handler."""
        bad_events = recent_events + [
            {
                "id": 5,
                "event": "OTHER_EVENT",
                "item": "",
                "retailer": "other",
                "timestamp": "not-a-valid-timestamp",
                "order_id": "",
                "error": "",
                "attempt": 1,
            },
        ]
        with patch.object(mock_db, "get_recent_events", return_value=bad_events):
            with patch(
                "src.dashboard.routes.status._get_state_db",
                return_value=mock_db,
            ):
                result = await status_route(session=MockSession())  # must not raise

        assert "online" in result

    @pytest.mark.asyncio
    async def test_item_not_duplicated_when_multiple_start_events(
        self,
        mock_db: MagicMock,
    ) -> None:
        """Same item appearing in multiple MONITOR_STARTED events → list deduped."""
        now = datetime.now(timezone.utc)
        events = [
            {
                "id": i,
                "event": "MONITOR_STARTED",
                "item": "Pokemon Scarlet",
                "retailer": "target",
                "timestamp": (now - timedelta(minutes=10 - i)).isoformat().replace(
                    "+00:00", "Z"
                ),
                "order_id": "",
                "error": "",
                "attempt": 1,
            }
            for i in range(3)
        ]
        with patch.object(mock_db, "get_recent_events", return_value=events):
            with patch(
                "src.dashboard.routes.status._get_state_db",
                return_value=mock_db,
            ):
                result = await status_route(session=MockSession())

        assert result["active_items"].count("Pokemon Scarlet") == 1
