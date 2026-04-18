"""Events routes: GET /api/events/stream (SSE) and GET /api/events/history.

Per PRD Sections 9.7 (DSH-3), 9.7 (DSH-12).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

from fastapi import Depends, Query
from fastapi.responses import StreamingResponse

from src.dashboard.auth import UserRole, require_auth

from src.shared.db import DatabaseManager

if TYPE_CHECKING:
    pass  # DatabaseManager already imported above for runtime use

# ── SSE Route ─────────────────────────────────────────────────────────────────

EVENTS_POLL_INTERVAL_SEC = 0.2  # 200 ms — well under 500 ms latency target
KEEPALIVE_INTERVAL_SEC = 30


async def _sse_event_generator(
    initial_backlog: list[dict[str, Any]],
) -> AsyncIterator[bytes]:
    """Async generator yielding SSE-formatted event bytes.

    First sends the initial backlog of existing events, then streams
    new events as they appear in the Logger's in-memory queue.

    Each event is formatted as:
        data: {"event": "...", "item": "...", ...}

    Yields a UTF-8 encoded byte string per SSE "data:" line.
    """
    seen_count = len(initial_backlog)

    # Send initial backlog events
    for record in initial_backlog:
        yield b"data: " + json.dumps(record).encode("utf-8") + b"\n\n"

    # Stream new events as they arrive
    while True:
        await asyncio.sleep(EVENTS_POLL_INTERVAL_SEC)

        try:
            from src.bot.logger import Logger

            queue = Logger.get_sse_queue()
        except Exception:
            queue = []

        new_events = queue[seen_count:]
        for record in new_events:
            yield b"data: " + json.dumps(record).encode("utf-8") + b"\n\n"

        if len(queue) >= seen_count:
            seen_count = len(queue)

        # Keepalive: comment line to prevent connection timeout
        yield b": keepalive\n\n"


async def events_stream_route(
    _: Any = Depends(require_auth(UserRole.VIEWER)),
) -> StreamingResponse:
    """Stream real-time bot events via Server-Sent Events (SSE).

    GET /api/events/stream

    Requires VIEWER role or higher.

    Per PRD Section 9.7 (DSH-3):
      - Streams all lifecycle events to the dashboard JS in real time
      - Target latency: < 500 ms from event firing to dashboard display
      - Dashboard SSE consumer updates the live event log panel

    Events are sourced from the Logger's in-memory SSE queue, which is
    populated each time the bot logs at INFO level or above.

    SSE format:
        data: {"event": "STOCK_DETECTED", "item": "...", "retailer": "...", ...}

    The response is a StreamingResponse that stays open until the client
    disconnects. Each event is JSON-serialized and sent as a UTF-8 SSE data
    message.
    """
    from src.bot.logger import Logger

    try:
        initial_backlog = Logger.get_sse_queue()
    except Exception:
        initial_backlog = []

    return StreamingResponse(
        _sse_event_generator(initial_backlog),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering if proxied
        },
    )


# ── Events History Route ───────────────────────────────────────────────────────

async def events_history_route(
    limit: int = Query(default=500, ge=1, le=1000),
    event_type: str | None = Query(default=None),
    retailer: str | None = Query(default=None),
    item: str | None = Query(default=None),
    _: Any = Depends(require_auth(UserRole.VIEWER)),
) -> dict[str, Any]:
    """Return historical events from state.db with optional filters.

    GET /api/events/history

    Requires VIEWER role or higher.

    Per PRD Section 9.7 (DSH-12):
      - Returns last 500 events by default
      - Filter by event type, retailer, and/or item name

    Returns:
        events: list of event dictionaries
        total: total count matching filters
    """
    state_db = _get_state_db()

    try:
        events = state_db.get_recent_events(
            limit=limit,
            event_type=event_type,
            retailer=retailer,
            item=item,
        )
    except Exception:
        events = []

    return {
        "events": events,
        "total": len(events),
    }


def _get_state_db() -> Any:  # DatabaseManager
    """Get DatabaseManager for state.db (project root)."""
    repo_root = Path(__file__).parent.parent.parent.parent
    state_db_path = repo_root / "state.db"
    return DatabaseManager(state_db_path).initialize()
