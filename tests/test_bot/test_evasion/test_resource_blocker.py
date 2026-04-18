"""Tests for resource_blocker — blocking ads/analytics/tracking.

Per PRD Section 9.5 (EV-6).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestResourceBlocker:
    """Tests for apply_resource_blocking."""

    @pytest.mark.asyncio
    async def test_block_route_aborts_matching_domain(self) -> None:
        """_block_route() aborts requests to blocked ad/analytics domains."""
        from src.bot.evasion.resource_blocker import _block_route

        route = MagicMock()
        route.abort = AsyncMock()
        route.continue_ = AsyncMock()

        request = MagicMock()
        request.url = "https://www.google-analytics.com/analytics.js"

        await _block_route(route, request)

        route.abort.assert_awaited_once()
        route.continue_.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_block_route_continues_non_blocked_domain(self) -> None:
        """_block_route() allows non-blocked requests to proceed."""
        from src.bot.evasion.resource_blocker import _block_route

        route = MagicMock()
        route.abort = AsyncMock()
        route.continue_ = AsyncMock()

        request = MagicMock()
        request.url = "https://www.target.com/api/products"

        await _block_route(route, request)

        route.continue_.assert_awaited_once()
        route.abort.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_block_route_handles_facebook_tracking(self) -> None:
        """_block_route() blocks pixel tracking from facebook.net."""
        from src.bot.evasion.resource_blocker import _block_route

        route = MagicMock()
        route.abort = AsyncMock()
        route.continue_ = AsyncMock()

        request = MagicMock()
        request.url = "https://pixel.facebook.com/tr?id=123456"

        await _block_route(route, request)

        route.abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_block_route_handles_doubleclick(self) -> None:
        """_block_route() blocks doubleclick ad requests."""
        from src.bot.evasion.resource_blocker import _block_route

        route = MagicMock()
        route.abort = AsyncMock()
        route.continue_ = AsyncMock()

        request = MagicMock()
        request.url = "https://securepubads.doubleclick.net/gampad/ads"

        await _block_route(route, request)

        route.abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_block_route_handles_criteo(self) -> None:
        """_block_route() blocks criteo tracking."""
        from src.bot.evasion.resource_blocker import _block_route

        route = MagicMock()
        route.abort = AsyncMock()
        route.continue_ = AsyncMock()

        request = MagicMock()
        request.url = "https://dis.criteo.com/dis/ulink/track"

        await _block_route(route, request)

        route.abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_block_route_case_insensitive(self) -> None:
        """_block_route() matches domains case-insensitively."""
        from src.bot.evasion.resource_blocker import _block_route

        route = MagicMock()
        route.abort = AsyncMock()
        route.continue_ = AsyncMock()

        request = MagicMock()
        request.url = "https://GOOGLE-ANALYTICS.COM/collect"

        await _block_route(route, request)

        route.abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_apply_resource_blocking_uses_wildcard(self) -> None:
        """apply_resource_blocking() routes all URLs through _block_route."""
        from src.bot.evasion.resource_blocker import apply_resource_blocking

        context = MagicMock()
        context.route = AsyncMock()

        await apply_resource_blocking(context)

        # Should have registered one route handler with wildcard pattern
        context.route.assert_awaited_once()
        call_args = context.route.call_args
        assert call_args[0][0] == "**/*"
        assert call_args[0][1] is not None

    @pytest.mark.asyncio
    async def test_apply_resource_blocking_alias_works(self) -> None:
        """apply_resource_blocking_middleware is an alias that works."""
        from src.bot.evasion.resource_blocker import (
            apply_resource_blocking,
            apply_resource_blocking_middleware,
        )

        context = MagicMock()
        context.route = AsyncMock()

        await apply_resource_blocking_middleware(context)

        context.route.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_block_route_allows_normal_retailer_urls(self) -> None:
        """Normal retailer API requests are not blocked."""
        from src.bot.evasion.resource_blocker import _block_route

        allowed_urls = [
            "https://redsky.target.com/v3/pdp/",
            "https://api.walmart.com/items",
            "https://api.bestbuy.com/products",
            "https://www.target.com/cart",
            "https://www.walmart.com/checkout",
            "https://www.bestbuy.com/cart",
        ]

        for url in allowed_urls:
            route = MagicMock()
            route.abort = AsyncMock()
            route.continue_ = AsyncMock()
            request = MagicMock()
            request.url = url

            await _block_route(route, request)

            route.continue_.assert_awaited_once()
            route.abort.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_block_list_has_expected_domains(self) -> None:
        """Verify the block list contains expected ad networks."""
        from src.bot.evasion.resource_blocker import _AD_TRACKING_DOMAINS

        expected_domains = {
            "doubleclick.net",
            "google-analytics.com",
            "facebook.net",
            "criteo.com",
            "hotjar.com",
            "mixpanel.com",
            "segment.io",
            "optimizely.com",
        }

        for domain in expected_domains:
            assert domain in _AD_TRACKING_DOMAINS, f"Missing domain: {domain}"