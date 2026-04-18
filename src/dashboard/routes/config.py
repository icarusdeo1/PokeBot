"""Config routes: GET /api/config, PATCH /api/config.

Per PRD Sections 9.8 (CFG-9, CFG-10), 9.7 (DSH-7).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from src.bot.config import Config, ConfigError
from src.dashboard.auth import DashboardSession, UserRole, require_auth


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_config_path() -> Path:
    """Return the path to config.yaml (project root)."""
    return Path(__file__).parent.parent.parent.parent / "config.yaml"


def _load_config_for_route() -> Config:
    """Load and validate the current config.yaml for a route handler."""
    config_path = _get_config_path()
    if not config_path.exists():
        raise HTTPException(status_code=500, detail="config.yaml not found")
    try:
        return Config.from_file(config_path)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── Routes ───────────────────────────────────────────────────────────────────────

async def get_config_route(
    _: DashboardSession = Depends(require_auth(UserRole.VIEWER)),
) -> JSONResponse:
    """Return the full config with sensitive fields masked.

    GET /api/config

    Requires VIEWER role or higher.
    Returns the masked config dict as JSON (no敏感 fields visible).
    Per PRD Sections 9.7 (DSH-7), 9.8 (CFG-11).
    """
    config = _load_config_for_route()
    masked = config.mask_secrets()
    return JSONResponse(content=masked)


async def patch_config_route(
    request: Request,
    _: DashboardSession = Depends(require_auth(UserRole.OPERATOR)),
) -> JSONResponse:
    """Update config.yaml from form data, validate, and save.

    PATCH /api/config

    Requires OPERATOR role.
    Per PRD Sections 9.7 (DSH-7), 9.8 (CFG-9, CFG-10).

    Request body (JSON or form-encoded): top-level keys to update.
    Values are merged into existing config. Sensitive fields (card_number,
    cvv, passwords, API keys) are stored but masked on read.

    Returns the updated (masked) config on success.
    Returns field-level validation errors on failure (HTTP 400).
    """
    # Read the incoming update payload
    try:
        body = await request.json()
    except Exception:
        # Fall back to form data
        form = await request.form()
        body = dict(form)

    if not body:
        raise HTTPException(
            status_code=400,
            detail="Request body must contain at least one config field to update",
        )

    config_path = _get_config_path()

    # Load the current full config
    try:
        current_config = Config.from_file(config_path)
    except ConfigError:
        # If there's no valid config yet, start from an empty dict
        current_config = None

    # Merge update into a copy of the current raw config
    if current_config is not None:
        merged = _deep_merge(current_config._raw.copy(), body)
    else:
        merged = body

    # Validate the merged config
    try:
        new_config = Config._from_raw(merged, config_path)
    except ConfigError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Config validation failed — changes were not saved",
                "errors": exc.errors,
            },
        )

    # Persist the merged (but mask-secrets-raw) config
    import yaml
    with config_path.open("w") as f:
        yaml.safe_dump(merged, f, sort_keys=False, default_flow_style=False)

    # Return the newly saved masked config
    return JSONResponse(content=new_config.mask_secrets())


# ── Merge helper ───────────────────────────────────────────────────────────────

def _deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge update dict into base dict.

    Lists are replaced (not appended). None values in update are skipped.
    """
    result = base.copy()
    for k, v in update.items():
        if v is None:
            continue
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
