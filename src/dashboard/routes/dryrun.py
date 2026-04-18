"""Dryrun route: POST /api/dryrun.

Per PRD Sections 9.7 (DSH-6), 14 (Phase 1 exit criteria).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.bot.config import Config, ConfigError
from src.dashboard.auth import DashboardSession, UserRole, require_auth
from src.shared.db import DatabaseManager


def _get_state_db() -> DatabaseManager:
    """Get DatabaseManager for state.db (project root)."""
    repo_root = Path(__file__).parent.parent.parent.parent
    state_db_path = repo_root / "state.db"
    return DatabaseManager(state_db_path).initialize()


def _get_config_path() -> Path:
    """Return the path to config.yaml (project root)."""
    return Path(__file__).parent.parent.parent.parent / "config.yaml"


async def _dryrun_sse_generator(
    dryrun_command_id: int,
) -> AsyncIterator[bytes]:
    """Async generator that streams dryrun output as SSE data events.

    Polls the command queue for completion or output events.
    Each line is formatted as:
        data: {"type": "output", "text": "...", ...}
    """
    import time

    # The daemon processes the dryrun command and logs progress events.
    # We poll the events queue for DRYRUN_* events related to this command.
    poll_interval = 0.5  # 500 ms
    max_wait = 600  # 10 minutes max

    for _ in range(int(max_wait / poll_interval)):
        await asyncio.sleep(poll_interval)

        # Check if command has been completed/failed
        db = _get_state_db()
        with db.connection() as conn:
            row = conn.execute(
                "SELECT status, processed_at FROM command_queue WHERE id=?",
                (dryrun_command_id,),
            ).fetchone()

        if row and row["status"] in ("completed", "failed"):
            status = row["status"]
            processed_at = row["processed_at"] or "unknown"
            yield b"data: " + json.dumps({
                "type": "done",
                "status": status,
                "processed_at": processed_at,
            }).encode("utf-8") + b"\n\n"
            break

        # Stream any new DRYRUN_* events from the logger queue
        try:
            from src.bot.logger import Logger

            queue = Logger.get_sse_queue()
            new_dryrun_events = [
                ev for ev in queue
                if isinstance(ev, dict) and ev.get("event", "").startswith("DRYRUN")
            ]
            for ev in new_dryrun_events[-10:]:  # last 10
                yield b"data: " + json.dumps({
                    "type": "output",
                    "event": ev.get("event"),
                    "text": ev.get("text", ""),
                    "item": ev.get("item", ""),
                    "retailer": ev.get("retailer", ""),
                    "timestamp": ev.get("timestamp", ""),
                }).encode("utf-8") + b"\n\n"
        except Exception:
            pass

        yield b": keepalive\n\n"

    # Timeout
    yield b"data: " + json.dumps({
        "type": "done",
        "status": "timeout",
        "message": "Dryrun exceeded maximum wait time (10 minutes)",
    }).encode("utf-8") + b"\n\n"


async def dryrun_route(
    session: DashboardSession = Depends(require_auth(UserRole.OPERATOR)),
) -> StreamingResponse:
    """Trigger a full checkout flow dry-run without placing an order.

    POST /api/dryrun

    Requires OPERATOR role.

    Per PRD Sections 9.7 (DSH-6), 14 (Phase 1 exit criteria):
      - Validates config before running
      - Enqueues 'dryrun' command for daemon to process asynchronously
      - Returns an SSE stream of dryrun output events
      - Daemon processes CheckoutFlow with dry_run=True (no order placed)

    SSE stream format:
        data: {"type": "output", "event": "DRYRUN_STARTED", "text": "...", ...}
        data: {"type": "done", "status": "completed"|"failed"|"timeout", ...}

    The dashboard frontend connects to this SSE endpoint and displays
    the streaming output in a terminal-style panel.
    """
    config_path = _get_config_path()

    # Validate config before running dryrun
    try:
        Config.from_file(config_path)
    except ConfigError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Config validation failed — cannot run dryrun",
                "errors": exc.errors,
            },
        )

    # Enqueue dryrun command for the daemon
    db = _get_state_db()
    command_id = db.enqueue_command(command="dryrun", args={})

    return StreamingResponse(
        _dryrun_sse_generator(command_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )