"""Retailer adapter plugins.

Per PRD Section 9.15 (ADP-1, ADP-2, ADP-3).
"""

from __future__ import annotations

from src.bot.monitor.retailers.registry import (
    AdapterPlugin,
    AdapterRegistry,
    RETAILER_MODULE_NAMES,
    get_default_registry,
)

__all__ = [
    "AdapterPlugin",
    "AdapterRegistry",
    "RETAILER_MODULE_NAMES",
    "get_default_registry",
]
