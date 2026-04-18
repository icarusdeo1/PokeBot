"""FastAPI dashboard server.

Per PRD Section 7.
Wires together all route handlers and serves the dashboard SPA.
Entry point: python -m src.dashboard.server
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
)

# Ensure project root is on sys.path
_repo_root = Path(__file__).parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from src.dashboard.auth import DashboardAuth, SessionAuthMiddleware, UserRole
from src.dashboard.routes.status import status_route
from src.dashboard.routes.config import (
    get_config_route,
    patch_config_route,
    config_validate_route,
    config_reload_route,
)
from src.dashboard.routes.events import events_stream_route, events_history_route
from src.dashboard.routes.monitor import monitor_start_route, monitor_stop_route
from src.dashboard.routes.dryrun import dryrun_route
from src.dashboard.routes.health import health_route
from src.dashboard.routes.daemon_restart import daemon_restart_route

# ── Auth DB setup ──────────────────────────────────────────────────────────────
_auth_db_path = Path(__file__).parent.parent.parent / "auth.db"
DashboardAuth(_auth_db_path)  # Creates tables on first init


# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="PokeDrop Bot Dashboard",
    version="1.0.0",
    description="Dashboard for the PokeDrop bot — monitor, configure, and control drops.",
)

# CORS: allow the dashboard to be served from any origin for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session auth middleware (validates cookies on all /api/* routes, excluding public prefixes)
app.add_middleware(SessionAuthMiddleware)


# ── Login routes ──────────────────────────────────────────────────────────────
@app.post("/login", response_class=RedirectResponse, tags=["auth"])
async def login_post(request: Request, pin: str = Form(...)) -> RedirectResponse:
    """Handle PIN/password login. Sets session cookie on success.

    Per PRD Sections 9.7 (DSH-1), 5.
    """
    auth = DashboardAuth(_auth_db_path)
    if not auth.verify_pin(pin):
        return RedirectResponse(url="/login?error=invalid", status_code=302)

    role = auth.get_role() or UserRole.VIEWER
    db_session = auth.create_session(role)
    cookie = auth.make_session_cookie(db_session.session_token)

    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(**cookie)
    return response


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_get(error: str = "") -> HTMLResponse:
    """Serve the login page (fallback if JS auth check fails)."""
    error_html = ""
    if error == "invalid":
        error_html = (
            '<div style="background:rgba(239,68,68,.15);border:1px solid #ef4444;'
            'border-radius:8px;padding:.75rem;margin-bottom:1rem;font-size:.875rem;color:#ef4444;">'
            "Invalid PIN. Please try again.</div>"
        )
    return HTMLResponse(
        content=f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>PokeDrop — Login</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:#0f1117;color:#e2e8f0;display:flex;align-items:center;
  justify-content:center;min-height:100vh;margin:0;padding:1rem;}}
.card{{background:#1a1d27;border:1px solid #2e3347;border-radius:12px;
  padding:2rem;width:100%;max-width:360px;}}
h1{{font-size:1.5rem;margin:0 0 .25rem;}} .subtitle{{color:#94a3b8;margin-bottom:1.5rem;font-size:.875rem;}}
input{{width:100%;padding:.65rem;border-radius:8px;border:1px solid #2e3347;
  background:#0f1117;color:#e2e8f0;font-size:1rem;margin-bottom:1rem;box-sizing:border-box;}}
button{{width:100%;padding:.65rem;border-radius:8px;border:none;
  background:#6366f1;color:#fff;font-size:1rem;font-weight:600;cursor:pointer;}}
button:hover{{background:#818cf8;}}
</style></head>
<body><div class="card"><h1>🪶 PokeDrop Bot</h1>
<p class="subtitle">Enter your PIN to continue</p>
{error_html}
<form method="POST" action="/login">
<input type="password" name="pin" placeholder="••••••••" autofocus required>
<button type="submit">Sign In</button>
</form></div></body></html>"""
    )


# ── Health (public, no auth) ──────────────────────────────────────────────────
@app.get("/health", tags=["health"])
async def health() -> Any:
    """Public health check. No auth required.

    Per PRD Sections 9.14 (OP-3, OP-4), 18.
    """
    return await health_route()


# ── Authenticated API routes ───────────────────────────────────────────────────
@app.get("/api/status", tags=["status"])
async def status(_: Request) -> Any:
    return await status_route()


@app.get("/api/config", tags=["config"])
async def get_config(_: Request) -> Any:
    return await get_config_route()


@app.patch("/api/config", tags=["config"])
async def patch_config(request: Request) -> Any:
    return await patch_config_route(request)


@app.post("/api/config/validate", tags=["config"])
async def validate_config(request: Request) -> Any:
    return await config_validate_route(request)


@app.post("/api/config/reload", tags=["config"])
async def reload_config(_: Request) -> Any:
    return await config_reload_route()


@app.get("/api/events/stream", tags=["events"])
async def events_stream(_: Request) -> Any:
    return await events_stream_route()


@app.get("/api/events/history", tags=["events"])
async def events_history(_: Request) -> Any:
    return await events_history_route()


@app.post("/api/monitor/start", tags=["monitor"])
async def monitor_start(_: Request) -> Any:
    return await monitor_start_route()


@app.post("/api/monitor/stop", tags=["monitor"])
async def monitor_stop(_: Request) -> Any:
    return await monitor_stop_route()


@app.post("/api/dryrun", tags=["dryrun"])
async def dryrun(_: Request) -> Any:
    return await dryrun_route()


@app.post("/api/daemon/restart", tags=["daemon"])
async def daemon_restart(_: Request) -> Any:
    return await daemon_restart_route()


# ── SPA fallback (serve index.html for non-API routes) ────────────────────────
@app.get("/{path:path}", include_in_schema=False, response_model=None)
async def spa_fallback(path: str) -> Response:
    """Serve the dashboard SPA for any non-API, non-public route."""
    index_path = Path(__file__).parent / "templates" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse(content="Dashboard not found.", status_code=404)


@app.get("/", include_in_schema=False, response_model=None)
async def root() -> Response:
    """Serve the dashboard SPA at root."""
    index_path = Path(__file__).parent / "templates" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse(
        content="<html><body><h1>PokeDrop Bot</h1><p>Dashboard not found.</p></body></html>",
        status_code=404,
    )


# ── Entry point ───────────────────────────────────────────────────────────────
def run() -> None:
    """Run the dashboard server via uvicorn."""
    uvicorn.run(
        "src.dashboard.server:app",
        host="0.0.0.0",
        port=8080,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    run()