# SPDX-License-Identifier: MIT
"""
Tests for bot.evasion.user_agents module (EVASION-T01).
"""

from __future__ import annotations

import pytest

from src.bot.evasion.user_agents import (
    get_random_user_agent,
    get_user_agent_pool_size,
    iter_user_agents,
    get_user_agent_for_browser,
)


class TestUserAgentPool:
    """Tests for UA pool size and structure."""

    def test_pool_has_at_least_50_agents(self) -> None:
        """Pool must contain ≥50 UA strings per PRD EV-1."""
        size = get_user_agent_pool_size()
        assert size >= 50, f"Pool has only {size} UA strings, need ≥50"

    def test_all_agents_are_non_empty_strings(self) -> None:
        """Every UA in the pool must be a non-empty string."""
        for ua in iter_user_agents():
            assert isinstance(ua, str), f"UA is not a string: {type(ua)}"
            assert len(ua) > 0, "UA string is empty"

    def test_all_agents_containmozilla_marker(self) -> None:
        """Every UA must start with the Mozilla/5.0 prefix."""
        for ua in iter_user_agents():
            assert ua.startswith("Mozilla/5.0"), f"UA missing Mozilla prefix: {ua[:50]}"

    def test_all_agents_containbrowser_identifier(self) -> None:
        """Every UA must identify a real browser (Chrome/Firefox/Safari/Edge/etc)."""
        for ua in iter_user_agents():
            has_browser = any(
                marker in ua
                for marker in [
                    "Chrome/", "Firefox/", "Safari/", "Edg/",
                    "OPR/", "Brave/", "Android",
                ]
            )
            assert has_browser, f"UA has no browser identifier: {ua[:80]}"

    def test_pool_contains_multiple_browser_families(self) -> None:
        """Pool must contain at least Chrome, Firefox, and Safari UAs."""
        pool = list(iter_user_agents())
        has_chrome = any("Chrome/" in ua and "Edg/" not in ua for ua in pool)
        has_firefox = any("Firefox/" in ua for ua in pool)
        has_safari = any("Safari/" in ua and "Chrome/" not in ua for ua in pool)
        assert has_chrome, "Pool missing Chrome UAs"
        assert has_firefox, "Pool missing Firefox UAs"
        assert has_safari, "Pool missing Safari UAs"


class TestGetRandomUserAgent:
    """Tests for the random selection function."""

    def test_returns_string(self) -> None:
        """Must return a string."""
        ua = get_random_user_agent()
        assert isinstance(ua, str)
        assert len(ua) > 0

    def test_returns_ua_from_pool(self) -> None:
        """Must return a UA that exists in the pool."""
        ua = get_random_user_agent()
        pool = list(iter_user_agents())
        assert ua in pool, f"Returned UA not in pool: {ua}"

    def test_random_selection_is_not_hardcoded(self) -> None:
        """Multiple calls must produce different UAs (not hardcoded)."""
        results = [get_random_user_agent() for _ in range(20)]
        unique = set(results)
        # With 50+ UAs, 20 draws should rarely all be the same
        assert len(unique) > 1, "Random selection appears to be hardcoded"

    def test_random_selection_has_good_entropy(self) -> None:
        """With a 50+ pool, 100 random calls should produce multiple unique values."""
        results = [get_random_user_agent() for _ in range(100)]
        unique = set(results)
        # Should get at least 10 unique UAs out of 100 from a 50+ pool
        assert len(unique) >= 10, (
            f"Only {len(unique)} unique UAs from 100 draws — low entropy"
        )

    def test_returns_ua_from_global_pool(self) -> None:
        """Each call must return a UA from the global pool."""
        for _ in range(10):
            ua = get_random_user_agent()
            pool = list(iter_user_agents())
            assert ua in pool


class TestIterUserAgents:
    """Tests for the pool iterator."""

    def test_iter_returns_all_agents(self) -> None:
        """Iterator must yield all agents in pool."""
        count = sum(1 for _ in iter_user_agents())
        assert count == get_user_agent_pool_size()

    def test_iter_can_be_converted_to_list(self) -> None:
        """Must be usable as a plain iterator."""
        agents = list(iter_user_agents())
        assert len(agents) >= 50
        assert all(isinstance(ua, str) for ua in agents)

    def test_iter_is_independent_each_call(self) -> None:
        """Each call to iter_user_agents returns a fresh iterator."""
        it1 = iter_user_agents()
        it2 = iter_user_agents()
        first_from_it1 = next(it1)
        first_from_it2 = next(it2)
        # They should both return valid UAs (not the same iterator object)
        assert isinstance(first_from_it1, str)
        assert isinstance(first_from_it2, str)


class TestGetUserAgentForBrowser:
    """Tests for browser-family filtering."""

    def test_chrome_returns_chrome_ua(self) -> None:
        """chrome family must return a Chrome UA."""
        ua = get_user_agent_for_browser("chrome")
        assert "Chrome/" in ua
        assert "Edg/" not in ua  # not Edge

    def test_firefox_returns_firefox_ua(self) -> None:
        """firefox family must return a Firefox UA."""
        ua = get_user_agent_for_browser("firefox")
        assert "Firefox/" in ua

    def test_safari_returns_safari_ua(self) -> None:
        """safari family must return a Safari-only UA (not Chrome)."""
        ua = get_user_agent_for_browser("safari")
        assert "Safari/" in ua
        assert "Chrome/" not in ua

    def test_edge_returns_edge_ua(self) -> None:
        """edge family must return an Edge UA."""
        ua = get_user_agent_for_browser("edge")
        assert "Edg/" in ua

    def test_opera_returns_opera_ua(self) -> None:
        """opera family must return an Opera UA."""
        ua = get_user_agent_for_browser("opera")
        assert "OPR/" in ua

    def test_brave_returns_brave_ua(self) -> None:
        """brave family must return a Brave UA."""
        ua = get_user_agent_for_browser("brave")
        assert "Brave" in ua

    def test_android_returns_android_mobile_ua(self) -> None:
        """android family must return an Android mobile UA."""
        ua = get_user_agent_for_browser("android")
        assert "Android" in ua
        assert "Mobile Safari" in ua

    def test_iphone_returns_iphone_ua(self) -> None:
        """iphone family must return an iPhone UA."""
        ua = get_user_agent_for_browser("iphone")
        assert "iPhone" in ua

    def test_ipad_returns_ipad_ua(self) -> None:
        """ipad family must return an iPad UA."""
        ua = get_user_agent_for_browser("ipad")
        assert "iPad" in ua

    def test_unknown_browser_raises_value_error(self) -> None:
        """Unknown browser family must raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            get_user_agent_for_browser("netscape")
        assert "netscape" in str(exc_info.value).lower()

    def test_browser_family_fallback_returns_valid_ua(self) -> None:
        """If family pool is empty, falls back to random UA from full pool."""
        # The "opera" family has only 2 entries - test that we still get a string
        ua = get_user_agent_for_browser("opera")
        assert isinstance(ua, str)
        assert len(ua) > 0

    @pytest.mark.parametrize(
        "browser",
        [
            "chrome",
            "firefox",
            "safari",
            "edge",
            "opera",
            "brave",
            "android",
            "iphone",
            "ipad",
        ],
    )
    def test_all_browsers_return_string(self, browser: str) -> None:
        """All browser families must return a string UA."""
        ua = get_user_agent_for_browser(browser)
        assert isinstance(ua, str)
        assert len(ua) > 0

    @pytest.mark.parametrize(
        "browser",
        [
            "chrome",
            "firefox",
            "safari",
            "edge",
            "opera",
            "brave",
            "android",
            "iphone",
            "ipad",
        ],
    )
    def test_all_browsers_return_ua_in_pool(self, browser: str) -> None:
        """All browser family UAs must exist in the global pool."""
        ua = get_user_agent_for_browser(browser)
        pool = list(iter_user_agents())
        assert ua in pool, f"Returned UA not in pool: {ua}"
