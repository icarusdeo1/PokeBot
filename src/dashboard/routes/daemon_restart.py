"""Daemon control routes: POST /api/daemon/restart.

Per PRD Section 9.7 (DSH-16).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends
from fastapi.responses import JSONResponse

from src.dashboard.auth import DashboardSession, UserRole, require_auth
from src.shared.db import DatabaseManager


def _get_state_db() -> DatabaseManager:
    """Get DatabaseManager for state.db (project root)."""
    repo_root = Path(__file__).parent.parent.parent.parent
    state_db_path = repo_root / "state.db"
    return DatabaseManager(state_db_path).initialize()


async def daemon_restart_route(
    session: DashboardSession = Depends(require_auth(UserRole.OPERATOR)),
) -> JSONResponse:
    """Signal the daemon to restart.

    POST /api/daemon/restart

    Requires OPERATOR role.

    Per PRD Section 9.7 (DSH-16):
      - Writes "restart" command to state.db command queue
      - Dashboard shows "Daemon Offline" banner while daemon restarts
      - Daemon polls command queue and exits on restart command (supervisor restarts it)
    """
    db = _get_state_db()
    command_id = db.enqueue_command(command="restart", args={})
    return JSONResponse(
        content={
            "status": "ok",
            "message": "Daemon restart command enqueued",
            "command_id": command_id,
        },
        status_code=200,
    )