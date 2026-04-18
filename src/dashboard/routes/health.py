"""Health check route: GET /health.

Per PRD Sections 9.14 (OP-3, OP-4), 18.
No authentication required — used for daemon offline detection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse

from src.shared.db import DatabaseManager


def _get_state_db() -> DatabaseManager:
    """Get DatabaseManager for state.db (project root)."""
    repo_root = Path(__file__).parent.parent.parent.parent
    state_db_path = repo_root / "state.db"
    return DatabaseManager(state_db_path).initialize()


async def health_route() -> JSONResponse:
    """Return daemon health status.

    GET /health

    No authentication required (public endpoint for monitoring tools).

    Per PRD Section 9.14 (OP-3, OP-4):
      - Returns HTTP 200 + JSON with health indicators
      - Used by dashboard to detect daemon offline state
      - Dashboard polls this endpoint every 5 seconds

    Response body:
        status: "online" or "offline"
        active_items: number of items currently being monitored
        session_health: dict of retailer → health color (green/yellow/red)
        last_event_at: ISO-8601 timestamp of most recent event or null
        uptime_seconds: seconds since first monitor start event or 0
    """
    db = _get_state_db()

    try:
        recent_events = db.get_recent_events(limit=500)
    except Exception:
        recent_events = []

    # Determine if daemon is online
    # Online = has events OR has active items tracked
    online = len(recent_events) > 0

    # Count active items from MONITOR_STARTED/MONITOR_STOPPED event pairs
    active_items: set[str] = set()
    monitor_starts: dict[str, str] = {}
    for ev in reversed(recent_events):  # oldest first
        item = ev.get("item", "") or ""
        if ev["event"] == "MONITOR_STARTED" and item:
            monitor_starts[item] = ev["timestamp"]
        elif ev["event"] == "MONITOR_STOPPED" and item in monitor_starts:
            del monitor_starts[item]
    active_items = set(monitor_starts.keys())

    # Session health per retailer
    session_health: dict[str, str] = {}
    try:
        with db.connection() as conn:
            rows = conn.execute(
                "SELECT retailer, is_valid, expires_at FROM session_state"
            ).fetchall()
        for row in rows:
            retailer = row["retailer"]
            is_valid = bool(row["is_valid"])
            expires_at = row["expires_at"] or ""
            if not is_valid:
                session_health[retailer] = "red"
            elif expires_at:
                from datetime import datetime, timezone

                try:
                    exp_ts = datetime.fromisoformat(expires_at.rstrip("Z"))
                    if expires_at.endswith("Z"):
                        exp_ts = exp_ts.replace(tzinfo=timezone.utc)
                    remaining = (exp_ts - datetime.now(timezone.utc)).total_seconds()
                    if remaining <= 0:
                        session_health[retailer] = "red"
                    elif remaining <= 600:  # ≤10 min
                        session_health[retailer] = "yellow"
                    else:
                        session_health[retailer] = "green"
                except Exception:
                    session_health[retailer] = "green"
            else:
                session_health[retailer] = "green"
    except Exception:
        session_health = {}

    # Last event timestamp
    last_event_at = recent_events[0]["timestamp"] if recent_events else None

    # Uptime: seconds since oldest MONITOR_STARTED event
    uptime_seconds = 0
    if monitor_starts:
        from datetime import datetime, timezone

        oldest_ts = min(
            datetime.fromisoformat(ts.rstrip("Z")).replace(tzinfo=timezone.utc)
            for ts in monitor_starts.values()
        )
        uptime_seconds = int(
            (datetime.now(timezone.utc) - oldest_ts).total_seconds()
        )

    return JSONResponse(
        content={
            "status": "online" if online else "offline",
            "active_items": list(active_items),
            "session_health": session_health,
            "last_event_at": last_event_at,
            "uptime_seconds": uptime_seconds,
        },
        status_code=200,
    )