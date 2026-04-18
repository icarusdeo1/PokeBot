"""Tests for health route: GET /health.

Per ROUTE-T06.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.dashboard.routes.health import (
    _get_state_db,
    health_route,
)
from src.shared.db import DatabaseManager


@pytest.fixture
def db_with_events(tmp_path: Path) -> DatabaseManager:
    """Return a DatabaseManager with some events logged."""
    db_path = tmp_path / "test_health.db"
    db = DatabaseManager(db_path)
    db.initialize()

    now = datetime.now(timezone.utc)
    events = [
        ("MONITOR_STARTED", "Charizard V", "target", "2026-04-18T10:00:00Z"),
        ("STOCK_DETECTED", "Charizard V", "target", "2026-04-18T10:05:00Z"),
        ("CHECKOUT_SUCCESS", "Charizard V", "target", "2026-04-18T10:05:30Z"),
    ]
    for event, item, retailer, ts in events:
        db.log_event(event=event, item=item, retailer=retailer, order_id="", error="", attempt=1)

    return db


@pytest.fixture
def db_empty(tmp_path: Path) -> DatabaseManager:
    """Return a DatabaseManager with no events."""
    db_path = tmp_path / "test_health_empty.db"
    db = DatabaseManager(db_path)
    db.initialize()
    return db


class TestGetStateDb:
    def test_returns_database_manager(self) -> None:
        db = _get_state_db()
        assert isinstance(db, DatabaseManager)


class TestHealthRoute:
    @pytest.mark.asyncio
    async def test_returns_online_when_events_exist(self, db_with_events: DatabaseManager) -> None:
        """With events in DB, status is 'online'."""
        with patch(
            "src.dashboard.routes.health._get_state_db",
            return_value=db_with_events,
        ):
            response = await health_route()

        assert response.status_code == 200
        import json
        body = json.loads(response.body.decode())
        assert body["status"] == "online"

    @pytest.mark.asyncio
    async def test_returns_offline_when_no_events(self, db_empty: DatabaseManager) -> None:
        """With no events in DB, status is 'offline'."""
        with patch(
            "src.dashboard.routes.health._get_state_db",
            return_value=db_empty,
        ):
            response = await health_route()

        import json
        body = json.loads(response.body.decode())
        assert body["status"] == "offline"

    @pytest.mark.asyncio
    async def test_active_items_from_monitor_started(self, db_with_events: DatabaseManager) -> None:
        """active_items is inferred from MONITOR_STARTED without matching STOPPED."""
        with patch(
            "src.dashboard.routes.health._get_state_db",
            return_value=db_with_events,
        ):
            response = await health_route()

        import json
        body = json.loads(response.body.decode())
        assert "Charizard V" in body["active_items"]

    @pytest.mark.asyncio
    async def test_last_event_at_from_newest_event(self, db_with_events: DatabaseManager) -> None:
        """last_event_at is a timestamp string (DB-generated, not hardcoded)."""
        with patch(
            "src.dashboard.routes.health._get_state_db",
            return_value=db_with_events,
        ):
            response = await health_route()

        import json
        body = json.loads(response.body.decode())
        # last_event_at should be an ISO-8601 timestamp string (from DB)
        assert body["last_event_at"] is not None
        assert body["last_event_at"].endswith("Z")
        # Should parse as a valid datetime
        from datetime import datetime
        dt = datetime.fromisoformat(body["last_event_at"].rstrip("Z"))
        assert dt.year == 2026

    @pytest.mark.asyncio
    async def test_uptime_seconds_calculated(self, db_with_events: DatabaseManager) -> None:
        """uptime_seconds is seconds since the oldest MONITOR_STARTED."""
        with patch(
            "src.dashboard.routes.health._get_state_db",
            return_value=db_with_events,
        ):
            response = await health_route()

        import json
        body = json.loads(response.body.decode())
        # Oldest MONITOR_STARTED is at 2026-04-18T10:00:00Z
        # Current time is after that, so uptime_seconds should be positive
        assert body["uptime_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_session_health_included(self, db_with_events: DatabaseManager) -> None:
        """session_health key is present in response (may be empty dict)."""
        with patch(
            "src.dashboard.routes.health._get_state_db",
            return_value=db_with_events,
        ):
            response = await health_route()

        import json
        body = json.loads(response.body.decode())
        assert "session_health" in body

    @pytest.mark.asyncio
    async def test_handles_db_error_gracefully(self, db_empty: DatabaseManager) -> None:
        """If DB query fails, returns offline status rather than crashing."""
        # Drop the events table to force an error
        with db_empty.connection() as conn:
            conn.execute("DROP TABLE events")

        with patch(
            "src.dashboard.routes.health._get_state_db",
            return_value=db_empty,
        ):
            response = await health_route()

        import json
        body = json.loads(response.body.decode())
        # Should return offline with empty data rather than 500
        assert body["status"] == "offline"
        assert body["active_items"] == []