"""Tests for src.bot.evasion.robots — robots.txt fetcher and parser."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.evasion.robots import (
    RobotsDotTxt,
    RobotsDotTxtManager,
    parse_robots_txt,
)


# ── parse_robots_txt ────────────────────────────────────────────────────────


class TestParseRobotsDotTxt:
    def test_empty_raw(self) -> None:
        rt = parse_robots_txt("", "target.com")
        assert rt.host == "target.com"
        assert rt.rules == {}
        assert rt.is_allowed("/any/path") is True

    def test_basic_disallow(self) -> None:
        raw = "User-agent: *\nDisallow: /checkout\n"
        rt = parse_robots_txt(raw, "target.com")
        assert rt.is_allowed("/checkout") is False
        assert rt.is_allowed("/product/123") is True
        assert rt.is_allowed("/") is True

    def test_basic_allow(self) -> None:
        raw = "User-agent: *\nDisallow: /\nAllow: /public\n"
        rt = parse_robots_txt(raw, "target.com")
        assert rt.is_allowed("/public") is True
        assert rt.is_allowed("/private") is False

    def test_specific_user_agent_rules(self) -> None:
        raw = (
            "User-agent: Googlebot\n"
            "Disallow: /secret\n"
            "User-agent: *\n"
            "Disallow: /internal\n"
        )
        rt = parse_robots_txt(raw, "walmart.com")
        assert rt.is_allowed("/secret", "Googlebot") is False
        assert rt.is_allowed("/internal", "OtherBot") is False
        assert rt.is_allowed("/secret", "OtherBot") is True
        assert rt.is_allowed("/other", "OtherBot") is True

    def test_crawl_delay(self) -> None:
        raw = (
            "User-agent: *\n"
            "Crawl-delay: 5\n"
            "User-agent: Googlebot\n"
            "Crawl-delay: 1\n"
        )
        rt = parse_robots_txt(raw, "bestbuy.com")
        assert rt.get_crawl_delay() == 5.0
        assert rt.get_crawl_delay("Googlebot") == 1.0
        assert rt.get_crawl_delay("UnknownBot") == 5.0

    def test_crawl_delay_default_when_no_directive(self) -> None:
        raw = "User-agent: *\nDisallow: /x\n"
        rt = parse_robots_txt(raw, "target.com")
        assert rt.get_crawl_delay() is None

    def test_wildcard_pattern_asterisk_single(self) -> None:
        raw = "User-agent: *\nDisallow: /api/*/delete\n"
        rt = parse_robots_txt(raw, "target.com")
        assert rt.is_allowed("/api/v1/delete") is False
        assert rt.is_allowed("/api/v2/update") is True
        assert rt.is_allowed("/api/v1/delete/extra") is False

    def test_wildcard_pattern_double_asterisk(self) -> None:
        raw = "User-agent: *\nDisallow: /private/**\n"
        rt = parse_robots_txt(raw, "target.com")
        assert rt.is_allowed("/private/foo") is False
        assert rt.is_allowed("/private/foo/bar/baz") is False
        assert rt.is_allowed("/public/foo") is True

    def test_ignore_sitemap_and_host_directives(self) -> None:
        raw = (
            "User-agent: *\n"
            "Disallow: /admin\n"
            "Sitemap: https://example.com/sitemap.xml\n"
            "Host: example.com\n"
        )
        rt = parse_robots_txt(raw, "example.com")
        assert rt.is_allowed("/admin") is False
        assert rt.is_allowed("/other") is True

    def test_ignore_comments(self) -> None:
        raw = "# This is a comment\nUser-agent: *\nDisallow: /secret\n# Another comment\n"
        rt = parse_robots_txt(raw, "target.com")
        assert rt.is_allowed("/secret") is False
        assert rt.is_allowed("/other") is True

    def test_empty_disallow_means_allow_all(self) -> None:
        raw = "User-agent: *\nDisallow:\n"
        rt = parse_robots_txt(raw, "target.com")
        assert rt.is_allowed("/") is True
        assert rt.is_allowed("/anything") is True

    def test_case_insensitive_directive_names(self) -> None:
        # Directive names are case-insensitive per robots.txt spec
        raw = "USER-AGENT: *\nDISALLOW: /api\n"
        rt = parse_robots_txt(raw, "target.com")
        assert rt.is_allowed("/api") is False
        # Path matching is case-sensitive (robots.txt is case-sensitive)
        assert rt.is_allowed("/API") is True

    def test_dollar_sign_end_of_path(self) -> None:
        raw = "User-agent: *\nDisallow: /api/$\n"
        rt = parse_robots_txt(raw, "target.com")
        assert rt.is_allowed("/api/") is False
        assert rt.is_allowed("/api/v2") is True

    def test_multiple_user_agents_no_crossover(self) -> None:
        raw = (
            "User-agent: bot1\n"
            "Disallow: /a\n"
            "User-agent: bot2\n"
            "Disallow: /b\n"
        )
        rt = parse_robots_txt(raw, "target.com")
        assert rt.is_allowed("/a", "bot1") is False
        assert rt.is_allowed("/a", "bot2") is True
        assert rt.is_allowed("/b", "bot2") is False
        assert rt.is_allowed("/a", "bot3") is True
        assert "bot1" in rt.user_agents
        assert "bot2" in rt.user_agents

    def test_same_ua_multiple_blocks_merged(self) -> None:
        raw = (
            "User-agent: *\n"
            "Disallow: /a\n"
            "User-agent: *\n"
            "Disallow: /b\n"
        )
        rt = parse_robots_txt(raw, "target.com")
        assert rt.is_allowed("/a") is False
        assert rt.is_allowed("/b") is False
        assert rt.is_allowed("/c") is True

    def test_most_specific_match_wins(self) -> None:
        raw = (
            "User-agent: *\n"
            "Disallow: /api\n"
            "Allow: /api/public\n"
        )
        rt = parse_robots_txt(raw, "target.com")
        assert rt.is_allowed("/api") is False
        assert rt.is_allowed("/api/public") is True


# ── RobotsDotTxt.is_allowed cache ────────────────────────────────────────────


class TestIsAllowedCaching:
    def test_caches_result_per_ua(self) -> None:
        raw = "User-agent: *\nDisallow: /secret\n"
        rt = parse_robots_txt(raw, "target.com")
        assert rt.is_allowed("/secret") is False
        # Cache key includes (path, user_agent)
        assert ("/secret", "*") in rt._allow_cache


# ── RobotsDotTxtManager ──────────────────────────────────────────────────────


class TestRobotsDotTxtManager:
    @pytest.fixture
    def manager(self) -> RobotsDotTxtManager:
        return RobotsDotTxtManager()

    @pytest.mark.asyncio
    async def test_get_returns_none_for_invalid_url(self, manager: RobotsDotTxtManager) -> None:
        result = await manager.get("not-a-url")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_parsed_on_success(
        self, manager: RobotsDotTxtManager
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "User-agent: *\nDisallow: /admin\n"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        manager._client = mock_client
        result = await manager.get("https://target.com")
        assert result is not None
        assert result.is_allowed("/admin") is False
        assert result.is_allowed("/shop") is True

    @pytest.mark.asyncio
    async def test_404_returns_empty_rules(
        self, manager: RobotsDotTxtManager
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        manager._client = mock_client
        result = await manager.get("https://target.com")
        assert result is not None
        assert result.rules == {}
        assert result.is_allowed("/any/path") is True

    @pytest.mark.asyncio
    async def test_caches_within_ttl(self, manager: RobotsDotTxtManager) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "User-agent: *\nDisallow: /x\n"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        manager._client = mock_client

        result1 = await manager.get("https://target.com")
        result2 = await manager.get("https://target.com")
        assert result1 is result2
        assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_is_url_allowed_fail_open(
        self, manager: RobotsDotTxtManager
    ) -> None:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("network error"))
        mock_client.aclose = AsyncMock()

        manager._client = mock_client
        result = await manager.is_url_allowed("https://target.com/api/product")
        assert result is True  # Fail open

    @pytest.mark.asyncio
    async def test_is_url_allowed_respects_rules(
        self, manager: RobotsDotTxtManager
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "User-agent: *\nDisallow: /api\n"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        manager._client = mock_client
        assert await manager.is_url_allowed("https://target.com/api") is False
        assert await manager.is_url_allowed("https://target.com/shop") is True

    @pytest.mark.asyncio
    async def test_get_crawl_delay(
        self, manager: RobotsDotTxtManager
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "User-agent: *\nCrawl-delay: 3\n"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        manager._client = mock_client
        delay = await manager.get_crawl_delay("https://target.com")
        assert delay == 3.0

    @pytest.mark.asyncio
    async def test_invalidate_clears_cache(
        self, manager: RobotsDotTxtManager
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "User-agent: *\nDisallow: /x\n"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        manager._client = mock_client

        await manager.get("https://target.com")
        await manager._invalidate("https://target.com")

        assert "target.com" not in manager._cache
        await manager.get("https://target.com")
        assert mock_client.get.call_count == 2
