"""Monitor routes: POST /api/monitor/start and POST /api/monitor/stop.

Per PRD Section 9.7 (DSH-4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse

from src.dashboard.auth import DashboardSession, UserRole, require_auth
from src.shared.db import DatabaseManager


def _get_state_db() -> DatabaseManager:
    """Get DatabaseManager for state.db (project root)."""
    repo_root = Path(__file__).parent.parent.parent.parent
    state_db_path = repo_root / "state.db"
    return DatabaseManager(state_db_path).initialize()


async def monitor_start_route(
    session: DashboardSession = Depends(require_auth(UserRole.OPERATOR)),
) -> JSONResponse:
    """Enqueue a monitor start command for the daemon.

    POST /api/monitor/start

    Requires OPERATOR role.

    Per PRD Section 9.7 (DSH-4):
      - Writes "start" command to state.db command queue
      - Returns confirmation JSON immediately (daemon processes asynchronously)
      - Both start and stop require confirmation dialog on frontend
    """
    db = _get_state_db()
    command_id = db.enqueue_command(command="start", args={})
    return JSONResponse(
        content={
            "status": "ok",
            "message": "Monitor start command enqueued",
            "command_id": command_id,
        },
        status_code=200,
    )


async def monitor_stop_route(
    session: DashboardSession = Depends(require_auth(UserRole.OPERATOR)),
) -> JSONResponse:
    """Enqueue a monitor stop command for the daemon.

    POST /api/monitor/stop

    Requires OPERATOR role.

    Per PRD Section 9.7 (DSH-4):
      - Writes "stop" command to state.db command queue
      - Returns confirmation JSON immediately (daemon processes asynchronously)
      - Both start and stop require confirmation dialog on frontend
    """
    db = _get_state_db()
    command_id = db.enqueue_command(command="stop", args={})
    return JSONResponse(
        content={
            "status": "ok",
            "message": "Monitor stop command enqueued",
            "command_id": command_id,
        },
        status_code=200,
    )