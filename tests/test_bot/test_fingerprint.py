# SPDX-License-Identifier: MIT
"""
Tests for bot.evasion.fingerprint module (EVASION-T02).
"""

from __future__ import annotations

import pytest

from src.bot.evasion.fingerprint import (
    BrowserFingerprint,
    get_random_fingerprint,
    get_automation_mask_script,
    get_viewport,
    get_locale,
    get_timezone_id,
    get_hardware_concurrency,
    get_device_memory,
    get_device_scale_factor,
    _VIEWPORTS,
    _LOCALES,
    _TIMEZONES,
    _HARDWARE_CONCURRENCIES,
    _DEVICE_MEMORIES,
    _DEVICE_SCALE_FACTORS,
)


class TestBrowserFingerprint:
    """Tests for the BrowserFingerprint dataclass."""

    def test_fingerprint_is_dataclass(self) -> None:
        """Must be a proper dataclass."""
        fp = get_random_fingerprint("Mozilla/5.0 (Windows NT 10.0) Chrome/120.0")
        assert isinstance(fp, BrowserFingerprint)

    def test_fingerprint_fields_present(self) -> None:
        """Must have all required fields."""
        fp = get_random_fingerprint("test-ua")
        assert hasattr(fp, "viewport")
        assert hasattr(fp, "locale")
        assert hasattr(fp, "timezone_id")
        assert hasattr(fp, "user_agent")
        assert hasattr(fp, "hardware_concurrency")
        assert hasattr(fp, "device_memory")
        assert hasattr(fp, "device_scale_factor")

    def test_fingerprint_accepts_user_agent(self) -> None:
        """user_agent must be stored correctly."""
        ua = "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0"
        fp = get_random_fingerprint(ua)
        assert fp.user_agent == ua

    def test_fingerprint_viewport_has_keys(self) -> None:
        """viewport must have width and height."""
        fp = get_random_fingerprint("ua")
        assert "width" in fp.viewport
        assert "height" in fp.viewport
        assert isinstance(fp.viewport["width"], int)
        assert isinstance(fp.viewport["height"], int)
        assert fp.viewport["width"] > 0
        assert fp.viewport["height"] > 0

    def test_fingerprint_locale_is_string(self) -> None:
        """locale must be a non-empty string."""
        fp = get_random_fingerprint("ua")
        assert isinstance(fp.locale, str)
        assert len(fp.locale) > 0

    def test_fingerprint_timezone_is_string(self) -> None:
        """timezone_id must be a non-empty string."""
        fp = get_random_fingerprint("ua")
        assert isinstance(fp.timezone_id, str)
        assert len(fp.timezone_id) > 0
        assert "/" in fp.timezone_id  # IANA format

    def test_fingerprint_hardware_concurrency_is_positive_int(self) -> None:
        """hardware_concurrency must be a positive integer."""
        fp = get_random_fingerprint("ua")
        assert isinstance(fp.hardware_concurrency, int)
        assert fp.hardware_concurrency >= 1

    def test_fingerprint_device_memory_is_positive(self) -> None:
        """device_memory must be a positive float."""
        fp = get_random_fingerprint("ua")
        assert isinstance(fp.device_memory, float)
        assert fp.device_memory > 0

    def test_fingerprint_device_scale_factor_is_positive(self) -> None:
        """device_scale_factor must be a positive float."""
        fp = get_random_fingerprint("ua")
        assert isinstance(fp.device_scale_factor, float)
        assert fp.device_scale_factor > 0


class TestAutomationMaskScript:
    """Tests for the automation masking JavaScript injection."""

    def test_returns_string(self) -> None:
        """Must return a non-empty JavaScript string."""
        fp = get_random_fingerprint("Mozilla/5.0 Chrome/120.0")
        script = get_automation_mask_script(fp)
        assert isinstance(script, str)
        assert len(script) > 0

    def test_contains_webdriver_spoof(self) -> None:
        """Script must contain webdriver=false patch."""
        fp = get_random_fingerprint("ua")
        script = get_automation_mask_script(fp)
        # webdriver property is present in the script (check both quote styles)
        assert "webdriver" in script
        # Must set it to false (not true/undefined)
        assert "=> false" in script or "get: () => false" in script

    def test_contains_hardware_concurrency_spoof(self) -> None:
        """Script must spoof hardwareConcurrency from fingerprint."""
        fp = get_random_fingerprint("ua")
        script = get_automation_mask_script(fp)
        assert "hardwareConcurrency" in script
        assert str(fp.hardware_concurrency) in script

    def test_contains_device_memory_spoof(self) -> None:
        """Script must spoof deviceMemory from fingerprint."""
        fp = get_random_fingerprint("ua")
        script = get_automation_mask_script(fp)
        assert "deviceMemory" in script
        assert str(fp.device_memory) in script

    def test_script_is_valid_javascript_syntax(self) -> None:
        """The generated JS must be syntactically valid (basic check)."""
        fp = get_random_fingerprint("ua")
        script = get_automation_mask_script(fp)
        # Basic checks: balanced braces, no obvious syntax errors
        assert script.count("{") == script.count("}")
        assert script.count("(") == script.count(")")
        assert not script.strip().endswith("{")  # shouldn't end mid-block

    def test_different_fingerprints_produce_different_scripts(self) -> None:
        """Different fingerprints must produce different scripts."""
        fp1 = get_random_fingerprint("ua1")
        fp2 = get_random_fingerprint("ua2")
        script1 = get_automation_mask_script(fp1)
        script2 = get_automation_mask_script(fp2)
        # Scripts should differ when fingerprints differ
        assert script1 != script2


class TestIndividualGetters:
    """Tests for individual fingerprint parameter getters."""

    def test_get_viewport_returns_valid_dict(self) -> None:
        """get_viewport must return a viewport from the pool."""
        viewport = get_viewport()
        assert isinstance(viewport, dict)
        assert viewport in _VIEWPORTS

    def test_get_locale_returns_from_pool(self) -> None:
        """get_locale must return a locale from the pool."""
        locale = get_locale()
        assert locale in _LOCALES

    def test_get_timezone_id_returns_from_pool(self) -> None:
        """get_timezone_id must return a timezone from the pool."""
        tz = get_timezone_id()
        assert tz in _TIMEZONES

    def test_get_hardware_concurrency_returns_from_pool(self) -> None:
        """get_hardware_concurrency must return from the pool."""
        hc = get_hardware_concurrency()
        assert hc in _HARDWARE_CONCURRENCIES

    def test_get_device_memory_returns_from_pool(self) -> None:
        """get_device_memory must return from the pool."""
        dm = get_device_memory()
        assert dm in _DEVICE_MEMORIES

    def test_get_device_scale_factor_returns_from_pool(self) -> None:
        """get_device_scale_factor must return from the pool."""
        dsf = get_device_scale_factor()
        assert dsf in _DEVICE_SCALE_FACTORS


class TestPoolSizes:
    """Tests that pools have sufficient diversity."""

    def test_viewports_pool_has_multiple_values(self) -> None:
        """Viewport pool must have at least 5 options."""
        assert len(_VIEWPORTS) >= 5

    def test_locales_pool_has_multiple_values(self) -> None:
        """Locale pool must have at least 5 options."""
        assert len(_LOCALES) >= 5

    def test_timezones_pool_has_multiple_values(self) -> None:
        """Timezone pool must have at least 5 options."""
        assert len(_TIMEZONES) >= 5

    def test_hardware_concurrency_pool_has_multiple_values(self) -> None:
        """Hardware concurrency pool must have at least 3 options."""
        assert len(_HARDWARE_CONCURRENCIES) >= 3

    def test_device_memory_pool_has_multiple_values(self) -> None:
        """Device memory pool must have at least 3 options."""
        assert len(_DEVICE_MEMORIES) >= 3

    def test_device_scale_factor_pool_has_multiple_values(self) -> None:
        """Device scale factor pool must have at least 3 options."""
        assert len(_DEVICE_SCALE_FACTORS) >= 3


class TestRandomFingerprintVariety:
    """Tests that get_random_fingerprint produces varied results."""

    def test_multiple_calls_produce_different_fingerprints(self) -> None:
        """Multiple calls should produce at least some variation."""
        ua = "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0"
        results = [get_random_fingerprint(ua) for _ in range(20)]
        # At least the viewports should vary across 20 calls
        viewports = [fp.viewport for fp in results]
        unique_viewports = set(tuple(v.items()) for v in viewports)
        assert len(unique_viewports) > 1, "No variation in viewports across 20 calls"

    def test_viewport_from_pool(self) -> None:
        """Generated fingerprints must use viewports from the pool."""
        ua = "test"
        for _ in range(10):
            fp = get_random_fingerprint(ua)
            assert fp.viewport in _VIEWPORTS

    def test_locale_from_pool(self) -> None:
        """Generated fingerprints must use locales from the pool."""
        ua = "test"
        for _ in range(10):
            fp = get_random_fingerprint(ua)
            assert fp.locale in _LOCALES

    def test_timezone_from_pool(self) -> None:
        """Generated fingerprints must use timezones from the pool."""
        ua = "test"
        for _ in range(10):
            fp = get_random_fingerprint(ua)
            assert fp.timezone_id in _TIMEZONES
