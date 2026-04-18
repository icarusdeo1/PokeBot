# SPDX-License-Identifier: MIT
"""
Tests for bot.evasion.jitter module (EVASION-T04).
"""

from __future__ import annotations

import pytest

from src.bot.evasion.jitter import (
    apply_jitter,
    jitter_interval_seconds,
    get_jitter_range,
    DEFAULT_JITTER_PERCENT,
)


class TestApplyJitter:
    """Tests for apply_jitter()."""

    def test_returns_float(self) -> None:
        """Must return a float."""
        result = apply_jitter(1000.0, 20)
        assert isinstance(result, float)

    def test_default_jitter_percent_is_20(self) -> None:
        """Default jitter must be 20% when not specified."""
        assert DEFAULT_JITTER_PERCENT == 20

    def test_default_jitter_uses_20_percent(self) -> None:
        """When jitter_percent is None, must use default 20%."""
        result = apply_jitter(1000.0)
        # Should be 1000 * (1 ± 0.2) → 800 to 1200
        assert 800.0 <= result <= 1200.0

    def test_jitter_at_0_percent_returns_exact_value(self) -> None:
        """0% jitter must return exactly the base value."""
        result = apply_jitter(1000.0, 0)
        assert result == 1000.0

    def test_jitter_at_10_percent_within_bounds(self) -> None:
        """10% jitter must stay within ±10% of base."""
        base = 1000.0
        for _ in range(100):
            result = apply_jitter(base, 10)
            assert 900.0 <= result <= 1100.0

    def test_jitter_at_20_percent_within_bounds(self) -> None:
        """20% jitter must stay within ±20% of base."""
        base = 1000.0
        for _ in range(100):
            result = apply_jitter(base, 20)
            assert 800.0 <= result <= 1200.0

    def test_jitter_at_50_percent_within_bounds(self) -> None:
        """50% jitter must stay within ±50% of base."""
        base = 1000.0
        for _ in range(100):
            result = apply_jitter(base, 50)
            assert 500.0 <= result <= 1500.0

    def test_jitter_produces_variation(self) -> None:
        """Multiple calls must produce varying results."""
        results = [apply_jitter(1000.0, 20) for _ in range(50)]
        unique = set(results)
        # Should have multiple distinct values
        assert len(unique) > 1

    def test_jitter_edge_case_zero_base(self) -> None:
        """0ms base must return 0ms regardless of jitter."""
        result = apply_jitter(0.0, 20)
        assert result == 0.0

    def test_negative_jitter_raises(self) -> None:
        """Negative jitter_percent must raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            apply_jitter(1000.0, -10)
        assert "-10" in str(exc_info.value)

    def test_jitter_over_100_raises(self) -> None:
        """jitter_percent > 100 must raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            apply_jitter(1000.0, 101)
        assert "101" in str(exc_info.value)

    def test_negative_base_raises(self) -> None:
        """Negative base_interval_ms must raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            apply_jitter(-100.0, 20)
        assert "-100" in str(exc_info.value)

    def test_fractional_base_works(self) -> None:
        """Fractional base intervals must work correctly."""
        result = apply_jitter(0.5, 20)
        assert 0.4 <= result <= 0.6

    def test_very_small_base(self) -> None:
        """Very small intervals (e.g., 1ms) must work."""
        result = apply_jitter(1.0, 20)
        assert 0.8 <= result <= 1.2


class TestJitterIntervalSeconds:
    """Tests for jitter_interval_seconds()."""

    def test_returns_float(self) -> None:
        """Must return a float in seconds."""
        result = jitter_interval_seconds(1.0, 20)
        assert isinstance(result, float)

    def test_converts_seconds_to_ms_and_back(self) -> None:
        """Must correctly convert from seconds → ms → jittered → seconds."""
        base_seconds = 1.0  # 1000ms
        result = jitter_interval_seconds(base_seconds, 20)
        # 1.0s ±20% → 0.8s to 1.2s
        assert 0.8 <= result <= 1.2

    def test_default_jitter_percent(self) -> None:
        """Must use default 20% when not specified."""
        result = jitter_interval_seconds(1.0)
        assert 0.8 <= result <= 1.2

    def test_zero_seconds(self) -> None:
        """0 seconds must return 0."""
        result = jitter_interval_seconds(0.0, 20)
        assert result == 0.0


class TestGetJitterRange:
    """Tests for get_jitter_range()."""

    def test_returns_tuple(self) -> None:
        """Must return a tuple of (min, max)."""
        result = get_jitter_range(1000.0, 20)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_20_percent_range(self) -> None:
        """20% jitter on 1000ms → (800, 1200)."""
        min_val, max_val = get_jitter_range(1000.0, 20)
        assert min_val == 800.0
        assert max_val == 1200.0

    def test_10_percent_range(self) -> None:
        """10% jitter on 1000ms → (900, 1100)."""
        min_val, max_val = get_jitter_range(1000.0, 10)
        assert min_val == 900.0
        assert max_val == 1100.0

    def test_50_percent_range(self) -> None:
        """50% jitter on 1000ms → (500, 1500)."""
        min_val, max_val = get_jitter_range(1000.0, 50)
        assert min_val == 500.0
        assert max_val == 1500.0

    def test_0_percent_range(self) -> None:
        """0% jitter → (base, base)."""
        min_val, max_val = get_jitter_range(1000.0, 0)
        assert min_val == 1000.0
        assert max_val == 1000.0

    def test_min_less_than_max(self) -> None:
        """min must always be less than or equal to max."""
        for pct in [0, 10, 20, 50, 100]:
            min_val, max_val = get_jitter_range(1000.0, pct)
            assert min_val <= max_val

    def test_range_center_matches_base(self) -> None:
        """The midpoint of the range should equal the base."""
        for pct in [10, 20, 50]:
            min_val, max_val = get_jitter_range(1000.0, pct)
            midpoint = (min_val + max_val) / 2.0
            assert midpoint == 1000.0


class TestJitterDeterminism:
    """Tests that jitter produces non-deterministic but bounded results."""

    def test_repeated_calls_cover_range(self) -> None:
        """Many calls should hit both ends of the expected range."""
        base = 1000.0
        pct = 20
        min_seen = float("inf")
        max_seen = float("-inf")
        for _ in range(1000):
            result = apply_jitter(base, pct)
            min_seen = min(min_seen, result)
            max_seen = max(max_seen, result)
        # With 1000 samples, we should get very close to the edges
        assert min_seen < 820  # near 800
        assert max_seen > 1180  # near 1200

    def test_average_converges_to_base(self) -> None:
        """Mean of many jittered values should converge to the base."""
        base = 1000.0
        samples = [apply_jitter(base, 20) for _ in range(1000)]
        mean = sum(samples) / len(samples)
        # Mean should be very close to base (within 1%)
        assert abs(mean - base) < 10
