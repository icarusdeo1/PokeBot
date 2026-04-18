# SPDX-License-Identifier: MIT
"""
Jitter module for adding randomized variance to stock check intervals.

Adds ±N% random variance to each check interval to avoid predictable
request patterns that retailers can detect and rate-limit.
Implements EV-4 from PRD Section 9.5 (MON-6).

The jitter percentage is configurable per retailer in config.yaml
under `evasion.jitter_percent`.
"""

from __future__ import annotations

import random
from typing import Optional


DEFAULT_JITTER_PERCENT: int = 20
"""Default jitter percentage (20%) applied when not specified."""


def apply_jitter(base_interval_ms: float, jitter_percent: Optional[int] = None) -> float:
    """Apply random jitter ±N% to a base interval in milliseconds.

    Applies symmetric random variance: the resulting interval is uniformly
    distributed between (base * (1 - p/100)) and (base * (1 + p/100)).

    Args:
        base_interval_ms: Base interval in milliseconds.
        jitter_percent: Jitter percentage to apply (default: 20).
                        E.g., 20 means ±20% variance.

    Returns:
        The jittered interval in milliseconds as a float.

    Examples:
        >>> apply_jitter(1000, 20)   # 1000ms ±20% → 800–1200ms
        >>> apply_jitter(500, 10)    # 500ms ±10% → 450–550ms
        >>> apply_jitter(1000)      # uses default 20% jitter
    """
    if jitter_percent is None:
        jitter_percent = DEFAULT_JITTER_PERCENT

    if jitter_percent < 0:
        raise ValueError(f"jitter_percent must be non-negative, got {jitter_percent}")
    if jitter_percent > 100:
        raise ValueError(f"jitter_percent must be ≤ 100, got {jitter_percent}")
    if base_interval_ms < 0:
        raise ValueError(f"base_interval_ms must be non-negative, got {base_interval_ms}")

    jitter_fraction = jitter_percent / 100.0
    min_val = base_interval_ms * (1 - jitter_fraction)
    max_val = base_interval_ms * (1 + jitter_fraction)

    jittered_ms = random.uniform(min_val, max_val)
    return jittered_ms


def jitter_interval_seconds(
    base_interval_seconds: float,
    jitter_percent: Optional[int] = None,
) -> float:
    """Apply jitter to an interval given in seconds.

    Convenience wrapper that converts to milliseconds, applies jitter,
    and returns the result in seconds.

    Args:
        base_interval_seconds: Base interval in seconds.
        jitter_percent: Jitter percentage to apply (default: 20).

    Returns:
        The jittered interval in seconds as a float.
    """
    base_ms = base_interval_seconds * 1000.0
    jittered_ms = apply_jitter(base_ms, jitter_percent)
    return jittered_ms / 1000.0


def get_jitter_range(
    base_interval_ms: float,
    jitter_percent: int,
) -> tuple[float, float]:
    """Return the (min, max) jittered interval range without randomizing.

    Useful for documentation and testing.

    Args:
        base_interval_ms: Base interval in milliseconds.
        jitter_percent: Jitter percentage.

    Returns:
        A tuple (min_ms, max_ms) representing the jittered range.
    """
    jitter_fraction = jitter_percent / 100.0
    min_val = base_interval_ms * (1 - jitter_fraction)
    max_val = base_interval_ms * (1 + jitter_fraction)
    return (min_val, max_val)
