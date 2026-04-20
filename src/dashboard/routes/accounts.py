"""Accounts routes: GET /api/accounts, PATCH /api/accounts/{retailer}/{username}/toggle.

Per PRD Sections 9.7 (DSH-11), 9.10 (MAC-T02, MAC-T04).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from src.bot.config import Config, ConfigError
from src.dashboard.auth import DashboardSession, UserRole, require_auth


def _get_config_path() -> Path:
    """Return the path to config.yaml (project root)."""
    return Path(__file__).parent.parent.parent.parent / "config.yaml"


def _get_state_db_path() -> Path:
    """Return the path to state.db (project root)."""
    return Path(__file__).parent.parent.parent.parent / "state.db"


async def accounts_list_route(
    _: DashboardSession = Depends(require_auth(UserRole.VIEWER)),
) -> JSONResponse:
    """Return all configured accounts with session state.

    GET /api/accounts

    Requires VIEWER role or higher.
    Merges config-defined accounts with live session state from the prewarmer.

    Response shape:
        {
          "retailers": {
            "target": [
              {
                "username": "user@example.com",
                "enabled": true,
                "session": {
                  "prewarmed_at": "2026-04-20T10:00:00Z",
                  "expires_at": "2026-04-20T12:00:00Z",
                  "is_valid": true,
                  "cookies_count": 12
                }
              },
              ...
            ],
            ...
          }
        }
    """
    from src.bot.session.prewarmer import SessionPrewarmer
    from src.shared.db import DatabaseManager

    config = Config.from_file(_get_config_path())
    session_status: dict[str, list[dict[str, Any]]] = {}

    # Load session state from the prewarmer (in-memory + DB-backed)
    db_path = _get_state_db_path()
    if db_path.exists():
        db = DatabaseManager(db_path).initialize()
        prewarmer = SessionPrewarmer(config, db=db)
        prewarmer.load_from_db()
        session_status = prewarmer.get_status()

    # Build the accounts response from config + live session data
    retailers: dict[str, list[dict[str, Any]]] = {}
    for retailer, account_list in config.accounts.items():
        retailers[retailer] = []
        for acct in account_list:
            session_data = session_status.get(retailer, [])
            session_map = {s["account_name"]: s for s in session_data}
            sess = session_map.get(acct.username, {})

            retailers[retailer].append({
                "username": acct.username,
                "enabled": acct.enabled,
                "session": {
                    "prewarmed_at": sess.get("prewarmed_at", ""),
                    "expires_at": sess.get("expires_at", ""),
                    "is_valid": sess.get("is_valid", False),
                    "cookies_count": sess.get("cookies_count", 0),
                },
            })

    return JSONResponse(content={"retailers": retailers})


async def accounts_toggle_route(
    request: Request,
    retailer: str,
    username: str,
    _: DashboardSession = Depends(require_auth(UserRole.OPERATOR)),
) -> JSONResponse:
    """Toggle the enabled state of a specific account.

    PATCH /api/accounts/{retailer}/{username}/toggle

    Requires OPERATOR role.
    Loads config.yaml, finds the account under retailers[retailer],
    flips its enabled flag, validates, and saves.

    Returns the updated account object on success.
    Raises HTTP 400 if the retailer or username is not found.
    """
    # Read the incoming body (expecting {"enabled": bool} or no body = toggle)
    try:
        body = await request.json()
    except Exception:
        body = {}

    enabled = body.get("enabled")
    if enabled is None:
        # No body provided — treat as toggle: read current, invert
        current = Config.from_file(_get_config_path())
        accounts_for_retailer = current.accounts.get(retailer, [])
        for acct in accounts_for_retailer:
            if acct.username == username:
                enabled = not acct.enabled
                break
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Account '{username}' not found for retailer '{retailer}'",
            )
    elif not isinstance(enabled, bool):
        raise HTTPException(
            status_code=400,
            detail="'enabled' field must be a boolean",
        )

    config_path = _get_config_path()
    current = Config.from_file(config_path)

    # Locate account and flip enabled
    found = False
    accounts_for_retailer = current.accounts.get(retailer, [])
    for acct in accounts_for_retailer:
        if acct.username == username:
            acct.enabled = enabled
            found = True
            break

    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"Account '{username}' not found for retailer '{retailer}'",
        )

    # Re-serialize the merged config back to disk
    import yaml
    merged = current._raw.copy()
    merged["accounts"] = current.accounts  # re-serialize from Config.accounts

    try:
        Config._from_raw(merged, config_path)
    except ConfigError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Config validation failed — changes were not saved",
                "errors": exc.errors,
            },
        )

    with config_path.open("w") as f:
        yaml.safe_dump(merged, f, sort_keys=False, default_flow_style=False)

    return JSONResponse(content={
        "retailer": retailer,
        "username": username,
        "enabled": enabled,
    })
