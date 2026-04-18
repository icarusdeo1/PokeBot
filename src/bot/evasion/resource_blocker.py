"""Ad network and tracking resource blocking for Playwright.

Configures route handlers to block non-essential resources: ads, analytics,
tracking pixels, and other third-party scripts that are not needed for checkout.

Per PRD Section 9.5 (EV-6): Block non-essential JS (ads, analytics, tracking).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Route, Request


# Domains and URL patterns for non-essential resources to block
_AD_TRACKING_DOMAINS: set[str] = {
    # Ad networks
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "googletagmanager.com",
    "googletagservices.com",
    "facebook.net",
    "facebook.com/tr",
    "connect.facebook.net",
    "ads.twitter.com",
    "ads-api.twitter.com",
    "amazon-adsystem.com",
    "advertising.com",
    "adnxs.com",
    "criteo.com",
    "criteo.net",
    "outbrain.com",
    "taboola.com",
    "scorecardresearch.com",
    "quantserve.com",
    "bluekai.com",
    "krxd.net",
    "moatads.com",
    "hotjar.com",
    "mixpanel.com",
    "segment.io",
    "segment.com",
    "amplitude.com",
    "optimizely.com",
    "fullstory.com",
    "mouseflow.com",
    "crazyegg.com",
    "inspectlet.com",
    # Analytics
    "google-analytics.com",
    "analytics.google.com",
    "gtagmanager.com",
    "omtrdc.net",
    "omniture.com",
    "demdex.net",
    # Tracking pixels / beacons
    "pixel.facebook.com",
    "pixel.wp.com",
    "pixel.snapchat.com",
    "tr.snapchat.com",
    # Tag managers (non-critical)
    "tags.tiktok.com",
    "analytics.tiktok.com",
}


async def _block_route(route: "Route", request: "Request") -> None:
    """Abort routes to known ad/analytics/tracking domains."""
    url = request.url.lower()

    # Check if any blocked domain appears in the URL
    for domain in _AD_TRACKING_DOMAINS:
        if domain in url:
            await route.abort()
            return

    # Allow all other requests
    await route.continue_()


async def apply_resource_blocking(context: "BrowserContext") -> None:
    """Apply resource blocking to a Playwright browser context.

    Configures route handlers to block ads, analytics, tracking pixels,
    and other non-essential resources that are not needed for checkout.

    Args:
        context: Playwright BrowserContext to configure.

    Usage:
        context = await browser.new_context(...)
        await apply_resource_blocking(context)
        # All ad/analytics/tracking requests will be blocked

    Per PRD Section 9.5 (EV-6).
    """
    # Route handler to block ads and tracking across all resource types
    await context.route(
        "**/*",
        _block_route,
    )


async def apply_resource_blocking_middleware(context: "BrowserContext") -> None:
    """Alias for apply_resource_blocking for clearer naming in monitor contexts."""
    await apply_resource_blocking(context)


__all__ = [
    "apply_resource_blocking",
    "apply_resource_blocking_middleware",
]