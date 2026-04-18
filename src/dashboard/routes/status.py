"""Status route: GET /api/status.

Per PRD Section 9.7 (DSH-2).

Returns daemon state from state.db:
  - Daemon online/offline indicator
  - Active items list
  - Per-retailer session health (green/yellow/red)
  - Last event timestamp
  - Uptime seconds
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.shared.db import DatabaseManager

from fastapi import Depends  # noqa: E402

from src.dashboard.auth import DashboardSession, UserRole, require_auth

# ── Route ──────────────────────────────────────────────────────────────────────


async def status_route(
    session: Any = Depends(require_auth(UserRole.VIEWER)),
) -> dict[str, Any]:
    """Return daemon state from state.db.

    Requires VIEWER role or higher.

    Per PRD Section 9.7 (DSH-2):
      - online: bool — daemon is running and writing events
      - active_items: list[str] — items currently being monitored
      - session_health: dict[str, str] — retailer → green/yellow/red
      - last_event_at: str | None — ISO-8601 timestamp of most recent event
      - uptime_seconds: int — seconds since first MONITOR_STARTED event
    """
    from src.shared.db import DatabaseManager

    state_db = _get_state_db()

    # Fetch recent events (newest first)
    try:
        recent = state_db.get_recent_events(limit=500)
    except Exception:
        recent = []

    # Track active items from monitoring events
    active_items: list[str] = []

    # Track session health per retailer
    session_health: dict[str, str] = {}  # retailer → green/yellow/red

    last_event_at: str | None = None

    for event_row in recent:
        event_type = event_row.get("event", "")
        item = event_row.get("item", "")
        retailer = event_row.get("retailer", "")
        timestamp = event_row.get("timestamp", "")

        # Capture newest event timestamp
        if not last_event_at and timestamp:
            last_event_at = timestamp

        if event_type == "MONITOR_STARTED" and item and item not in active_items:
            active_items.append(item)
        elif event_type == "MONITOR_STOPPED" and item and item in active_items:
            active_items.remove(item)

        # Session health: red for failed sessions
        if event_type in ("SESSION_EXPIRED", "CHECKOUT_FAILED") and retailer:
            session_health[retailer] = "red"

    # Fill in session health for retailers with successful sessions
    # Load sessions from DB for green/yellow health
    try:
        _fill_session_health_from_db(state_db, session_health)
    except Exception:
        pass

    # Compute uptime from earliest MONITOR_STARTED event
    uptime_seconds = 0
    for event_row in reversed(recent):
        if event_row.get("event") == "MONITOR_STARTED":
            try:
                started_ts = event_row["timestamp"].replace("Z", "+00:00")
                started: datetime = datetime.fromisoformat(started_ts)
                uptime_seconds = int((datetime.now(timezone.utc) - started).total_seconds())
                break
            except Exception:
                pass

    # Daemon offline: no events in recent history and no active items
    is_online = len(recent) > 0 or len(active_items) > 0

    return {
        "online": is_online,
        "active_items": active_items,
        "session_health": session_health,
        "last_event_at": last_event_at,
        "uptime_seconds": uptime_seconds,
        "role": session.role.value,
    }


def _fill_session_health_from_db(
    state_db: Any,  # DatabaseManager
    session_health: dict[str, str],
) -> None:
    """Populate session_health with green/yellow/red from DB session records.

    Rules (per PRD Section 9.7 DSH-2):
      - green:  session exists and not expired
      - yellow: session exists and expires within 10 minutes
      - red:    session expired or missing
    """
    # We only have per-retailer session records, not per-account.
    # Check the session_state table for each retailer.
    try:
        from src.shared.models import RetailerName

        retailers = [r.value for r in RetailerName]
    except Exception:
        retailers = ["target", "walmart", "bestbuy"]

    now = datetime.now(timezone.utc)

    for retailer in retailers:
        if retailer in session_health:
            # Already determined red from failure events
            continue

        session = state_db.load_session(retailer)
        if session is None:
            session_health[retailer] = "red"
            continue

        expires_at_str = session.get("expires_at", "")
        if not expires_at_str:
            session_health[retailer] = "yellow"
            continue

        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            delta = (expires_at - now).total_seconds()
            if delta < 0:
                session_health[retailer] = "red"
            elif delta < 600:  # 10 minutes
                session_health[retailer] = "yellow"
            else:
                session_health[retailer] = "green"
        except Exception:
            session_health[retailer] = "yellow"


def _get_state_db() -> Any:  # DatabaseManager
    """Get DatabaseManager for state.db (project root)."""
    repo_root = Path(__file__).parent.parent.parent.parent
    state_db_path = repo_root / "state.db"
    return DatabaseManager(state_db_path).initialize()
