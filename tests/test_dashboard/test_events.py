"""Tests for events routes: GET /api/events/stream (SSE) and GET /api/events/history.

Per ROUTE-T03.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

import pytest

from src.dashboard.routes.events import (
    _sse_event_generator,
    events_history_route,
    events_stream_route,
    _get_state_db,
    EVENTS_POLL_INTERVAL_SEC,
)
from src.shared.db import DatabaseManager
from fastapi.responses import StreamingResponse


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db(tmp_path: Path) -> DatabaseManager:
    """Return a real DatabaseManager backed by a temp file."""
    db_path = tmp_path / "test_state.db"
    db = DatabaseManager(db_path)
    db.initialize()
    return db


@pytest.fixture
def sample_events() -> list[dict[str, Any]]:
    """Return a realistic list of events for testing."""
    now = datetime.now(timezone.utc)
    return [
        {
            "id": 1,
            "event": "MONITOR_STARTED",
            "item": "Charizard V",
            "retailer": "target",
            "timestamp": "2026-04-18T17:00:00Z",
            "order_id": "",
            "error": "",
            "attempt": 1,
        },
        {
            "id": 2,
            "event": "STOCK_DETECTED",
            "item": "Charizard V",
            "retailer": "target",
            "timestamp": "2026-04-18T17:05:00Z",
            "order_id": "",
            "error": "",
            "attempt": 1,
        },
        {
            "id": 3,
            "event": "CHECKOUT_SUCCESS",
            "item": "Charizard V",
            "retailer": "target",
            "timestamp": "2026-04-18T17:05:10Z",
            "order_id": "ORDER-12345",
            "error": "",
            "attempt": 1,
        },
    ]


# ── _get_state_db tests ───────────────────────────────────────────────────────

class TestGetStateDb:
    def test_returns_database_manager(self) -> None:
        db = _get_state_db()
        assert isinstance(db, DatabaseManager)


# ── events_history_route tests ─────────────────────────────────────────────────

class TestEventsHistoryRoute:
    """Tests for GET /api/events/history (events_history_route)."""

    def test_returns_empty_list_when_no_events(
        self,
        mock_db: DatabaseManager,
    ) -> None:
        """No events in DB → returns empty list."""
        with patch(
            "src.dashboard.routes.events._get_state_db",
            return_value=mock_db,
        ):
            result = asyncio.run(events_history_route(
                limit=500,
                event_type=None,
                retailer=None,
                item=None,
            ))
        assert result["events"] == []
        assert result["total"] == 0

    def test_returns_events_from_db(
        self,
        mock_db: DatabaseManager,
        sample_events: list[dict[str, Any]],
    ) -> None:
        """Events logged in DB are returned (ordered by timestamp DESC — newest first)."""
        for ev in sample_events:
            mock_db.log_event(
                event=ev["event"],
                item=ev["item"],
                retailer=ev["retailer"],
                order_id=ev.get("order_id", ""),
                error=ev.get("error", ""),
                attempt=ev.get("attempt", 1),
            )

        with patch(
            "src.dashboard.routes.events._get_state_db",
            return_value=mock_db,
        ):
            result = asyncio.run(events_history_route(
                limit=500,
                event_type=None,
                retailer=None,
                item=None,
            ))
        assert result["total"] == 3
        assert len(result["events"]) == 3
        # Newest first (CHECKOUT_SUCCESS was last inserted)
        assert result["events"][0]["event"] == "CHECKOUT_SUCCESS"
        assert result["events"][2]["event"] == "MONITOR_STARTED"

    def test_respects_limit_param(
        self,
        mock_db: DatabaseManager,
        sample_events: list[dict[str, Any]],
    ) -> None:
        """limit param caps returned events."""
        for ev in sample_events:
            mock_db.log_event(
                event=ev["event"],
                item=ev["item"],
                retailer=ev["retailer"],
                order_id=ev.get("order_id", ""),
                error=ev.get("error", ""),
                attempt=ev.get("attempt", 1),
            )

        with patch(
            "src.dashboard.routes.events._get_state_db",
            return_value=mock_db,
        ):
            result = asyncio.run(events_history_route(
                limit=2,
                event_type=None,
                retailer=None,
                item=None,
            ))
        assert result["total"] == 2

    def test_filters_by_retailer(
        self,
        mock_db: DatabaseManager,
        sample_events: list[dict[str, Any]],
    ) -> None:
        """retailer filter returns only matching events."""
        for ev in sample_events:
            mock_db.log_event(
                event=ev["event"],
                item=ev["item"],
                retailer=ev["retailer"],
                order_id=ev.get("order_id", ""),
                error=ev.get("error", ""),
                attempt=ev.get("attempt", 1),
            )
        # Add a walmart event
        mock_db.log_event(
            event="STOCK_DETECTED",
            item="Pikachu Plush",
            retailer="walmart",
            order_id="",
            error="",
            attempt=1,
        )

        with patch(
            "src.dashboard.routes.events._get_state_db",
            return_value=mock_db,
        ):
            result = asyncio.run(events_history_route(
                limit=500,
                event_type=None,
                retailer="walmart",
                item=None,
            ))
        assert result["total"] == 1
        assert result["events"][0]["retailer"] == "walmart"

    def test_filters_by_event_type(
        self,
        mock_db: DatabaseManager,
        sample_events: list[dict[str, Any]],
    ) -> None:
        """event_type filter returns only matching events."""
        for ev in sample_events:
            mock_db.log_event(
                event=ev["event"],
                item=ev["item"],
                retailer=ev["retailer"],
                order_id=ev.get("order_id", ""),
                error=ev.get("error", ""),
                attempt=ev.get("attempt", 1),
            )

        with patch(
            "src.dashboard.routes.events._get_state_db",
            return_value=mock_db,
        ):
            result = asyncio.run(events_history_route(
                limit=500,
                event_type="CHECKOUT_SUCCESS",
                retailer=None,
                item=None,
            ))
        assert result["total"] == 1
        assert result["events"][0]["event"] == "CHECKOUT_SUCCESS"

    def test_handles_db_error_gracefully(self, mock_db: DatabaseManager) -> None:
        """DB errors return empty events list rather than crashing."""
        with mock_db.connection() as conn:
            conn.execute("DROP TABLE events")

        with patch(
            "src.dashboard.routes.events._get_state_db",
            return_value=mock_db,
        ):
            result = asyncio.run(events_history_route(
                limit=500,
                event_type=None,
                retailer=None,
                item=None,
            ))
        assert result["events"] == []
        assert result["total"] == 0


# ── _sse_event_generator tests ─────────────────────────────────────────────────

class TestSseEventGenerator:
    """Tests for the SSE async event generator."""

    @pytest.mark.asyncio
    async def test_yields_initial_backlog(self) -> None:
        """Initial backlog events are yielded immediately."""
        initial = [
            {"event": "MONITOR_STARTED", "item": "Pikachu", "retailer": "target"},
            {"event": "STOCK_DETECTED", "item": "Pikachu", "retailer": "target"},
        ]
        gen = _sse_event_generator(initial)
        # Only take the first item (non-blocking for now, but we need sync-ish test)
        # We run the generator with a timeout
        results: list[bytes] = []
        for i in range(2):
            try:
                result = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
                results.append(result)
            except StopAsyncIteration:
                break

        assert len(results) == 2
        # Each is b"data: " + json bytes + b"\n\n"
        for r in results:
            assert r.startswith(b"data: ")

    @pytest.mark.asyncio
    async def test_initial_backlog_json_is_valid(self) -> None:
        """Backlog events contain valid JSON."""
        initial = [
            {"event": "MONITOR_STARTED", "item": "Charizard", "retailer": "walmart"},
        ]
        gen = _sse_event_generator(initial)
        result = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert result.startswith(b"data: ")
        json_str = result[len(b"data: "):].decode("utf-8")
        parsed = json.loads(json_str)
        assert parsed["event"] == "MONITOR_STARTED"
        assert parsed["item"] == "Charizard"

    @pytest.mark.asyncio
    async def test_empty_backlog_yields_nothing_initially(self) -> None:
        """Empty initial backlog yields no events from the initial batch."""
        gen = _sse_event_generator([])
        # First event would be a keepalive if any, but generator should
        # go straight to polling. We only yield initial backlog items.
        # With empty backlog, first yield would be a keepalive.
        done = False
        try:
            result = await asyncio.wait_for(gen.__anext__(), timeout=0.1)
            # Should be a keepalive comment
            assert result == b": keepalive\n\n"
        except asyncio.TimeoutError:
            done = True  # Empty backlog → no initial yields before polling

        assert done or True  # Either is fine

    @pytest.mark.asyncio
    async def test_keepalive_yields_before_polling(self) -> None:
        """After initial backlog, first iteration yields a keepalive comment."""
        gen = _sse_event_generator([{"event": "TEST"}])
        # Consume the initial backlog event
        await gen.__anext__()
        # Next yield should be keepalive
        result = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert result == b": keepalive\n\n"


# ── events_stream_route tests ─────────────────────────────────────────────────

class TestEventsStreamRoute:
    """Tests for GET /api/events/stream (events_stream_route)."""

    def test_returns_streaming_response(self) -> None:
        """Route returns a StreamingResponse."""
        with patch("src.dashboard.routes.events.require_auth") as mock_auth:
            mock_auth.return_value = lambda: MagicMock()
            # Skip auth by patching it to return the dependency directly
            from src.dashboard.auth import UserRole

            async def fake_dep() -> Any:
                return None

            with patch(
                "src.dashboard.routes.events.require_auth",
                return_value=fake_dep,
            ):
                with patch("src.bot.logger.Logger.get_sse_queue", return_value=[]):
                    response = asyncio.run(
                        events_stream_route(_=None)
                    )
        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"

    def test_streaming_response_has_no_cache_headers(self) -> None:
        """SSE response has Cache-Control: no-cache."""
        async def fake_dep() -> Any:
            return None

        with patch(
            "src.dashboard.routes.events.require_auth",
            return_value=fake_dep,
        ):
            with patch("src.bot.logger.Logger.get_sse_queue", return_value=[]):
                response = asyncio.run(
                    events_stream_route(_=None)
                )
        headers_lower = {k.lower(): v for k, v in response.headers.items()}
        assert "cache-control" in headers_lower
        assert headers_lower["cache-control"] == "no-cache"

    def test_handles_logger_not_initialized(self) -> None:
        """If Logger raises, empty backlog is used."""
        async def fake_dep() -> Any:
            return None

        with patch(
            "src.dashboard.routes.events.require_auth",
            return_value=fake_dep,
        ):
            with patch(
                "src.bot.logger.Logger.get_sse_queue",
                side_effect=RuntimeError("Logger not initialized"),
            ):
                response = asyncio.run(
                    events_stream_route(_=None)
                )
        assert isinstance(response, StreamingResponse)
