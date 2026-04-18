"""Tests for monitor routes: POST /api/monitor/start, POST /api/monitor/stop.

Per ROUTE-T04.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

import pytest

from src.dashboard.routes.monitor import (
    monitor_start_route,
    monitor_stop_route,
    _get_state_db,
)
from src.shared.db import DatabaseManager


@pytest.fixture
def mock_db(tmp_path: Path) -> DatabaseManager:
    """Return a real DatabaseManager backed by a temp file."""
    db_path = tmp_path / "test_state.db"
    db = DatabaseManager(db_path)
    db.initialize()
    return db


@pytest.fixture
def mock_session() -> MagicMock:
    """Return a mock DashboardSession with OPERATOR role."""
    session = MagicMock()
    session.role = "OPERATOR"
    return session


# ── _get_state_db tests ───────────────────────────────────────────────────────

class TestGetStateDb:
    def test_returns_database_manager(self) -> None:
        db = _get_state_db()
        assert isinstance(db, DatabaseManager)


# ── monitor_start_route tests ─────────────────────────────────────────────────

class TestMonitorStartRoute:
    @pytest.mark.asyncio
    async def test_enqueues_start_command(self, mock_db: DatabaseManager, mock_session: MagicMock) -> None:
        """POST /api/monitor/start enqueues a 'start' command."""
        with patch(
            "src.dashboard.routes.monitor._get_state_db",
            return_value=mock_db,
        ):
            response = await monitor_start_route(session=mock_session)

        assert response.status_code == 200
        body = response.body.decode()
        assert '"status": "ok"' in body or '"status":"ok"' in body
        assert "start" in body.lower()

    @pytest.mark.asyncio
    async def test_returns_command_id(self, mock_db: DatabaseManager, mock_session: MagicMock) -> None:
        """Response includes the enqueued command's row ID."""
        with patch(
            "src.dashboard.routes.monitor._get_state_db",
            return_value=mock_db,
        ):
            response = await monitor_start_route(session=mock_session)

        body = response.body.decode()
        assert "command_id" in body
        # command_id should be a positive integer (rowid)
        import json
        data = json.loads(response.body.decode())
        assert data["command_id"] >= 1

    @pytest.mark.asyncio
    async def test_command_is_in_queue(self, mock_db: DatabaseManager, mock_session: MagicMock) -> None:
        """The enqueued command appears in the pending commands list."""
        with patch(
            "src.dashboard.routes.monitor._get_state_db",
            return_value=mock_db,
        ):
            await monitor_start_route(session=mock_session)

        pending = mock_db.get_pending_commands()
        assert len(pending) >= 1
        assert pending[-1]["command"] == "start"


# ── monitor_stop_route tests ──────────────────────────────────────────────────

class TestMonitorStopRoute:
    @pytest.mark.asyncio
    async def test_enqueues_stop_command(self, mock_db: DatabaseManager, mock_session: MagicMock) -> None:
        """POST /api/monitor/stop enqueues a 'stop' command."""
        with patch(
            "src.dashboard.routes.monitor._get_state_db",
            return_value=mock_db,
        ):
            response = await monitor_stop_route(session=mock_session)

        assert response.status_code == 200
        body = response.body.decode()
        assert "stop" in body.lower()

    @pytest.mark.asyncio
    async def test_returns_command_id(self, mock_db: DatabaseManager, mock_session: MagicMock) -> None:
        """Response includes the enqueued command's row ID."""
        with patch(
            "src.dashboard.routes.monitor._get_state_db",
            return_value=mock_db,
        ):
            response = await monitor_stop_route(session=mock_session)

        import json
        data = json.loads(response.body.decode())
        assert data["command_id"] >= 1

    @pytest.mark.asyncio
    async def test_command_is_in_queue(self, mock_db: DatabaseManager, mock_session: MagicMock) -> None:
        """The enqueued command appears in the pending commands list."""
        with patch(
            "src.dashboard.routes.monitor._get_state_db",
            return_value=mock_db,
        ):
            await monitor_stop_route(session=mock_session)

        pending = mock_db.get_pending_commands()
        assert len(pending) >= 1
        assert pending[-1]["command"] == "stop"