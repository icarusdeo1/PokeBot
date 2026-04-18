"""Adapter info route — backend for dashboard About page.

Per PRD Section 9.15 (ADP-5).
"""

from __future__ import annotations

from fastapi import APIRouter

from src.bot.monitor.retailers import get_default_registry

router = APIRouter(prefix="/api/adapters", tags=["adapters"])


@router.get("/")
async def adapters_list_route() -> dict[str, list[dict[str, str]]]:
    """Return list of loaded adapter plugins for the About page.

    Returns:
        {"adapters": [{"name": "...", "version": "...", "enabled": "true"}, ...]}
    """
    registry = get_default_registry()
    adapters = []

    for name in registry.retailer_names:
        plugin = registry._adapters.get(name)
        if plugin is None:
            continue

        adapter_cls = plugin.cls
        version = getattr(adapter_cls, "VERSION", plugin.version) or "1.0"

        # Adapters are "enabled" if they're loaded in the registry
        enabled = True

        adapters.append({
            "name": name,
            "version": version,
            "enabled": "true" if enabled else "false",
            "module": plugin.module_name,
        })

    return {"adapters": adapters}