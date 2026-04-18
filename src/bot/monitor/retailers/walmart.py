"""Walmart.com retailer adapter.

Implements full checkout flow for walmart.com using Playwright headless
browser automation and direct HTTP API calls where available.

Per PRD Sections 9.1 (MON-1 to MON-11), 9.2 (CART-1 to CART-8),
9.3 (CO-1 to CO-10).
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Any, TYPE_CHECKING

import httpx
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

from src.bot.monitor.retailers.base import RetailerAdapter
from src.shared.models import (
    CaptchaSolveResult,
    CaptchaType,
    PaymentInfo,
    ShippingInfo,
    StockStatus,
)

if TYPE_CHECKING:
    from src.bot.logger import Logger


class WalmartAdapter(RetailerAdapter):
    """Walmart.com retailer adapter.

    Implements login, stock detection, cart management, and full checkout
    flow using Playwright for browser automation with anti-detection
    measures (UA rotation, fingerprint randomization, proxy support).

    Per PRD Sections 9.1, 9.2, 9.3.
    """

    name: str = "walmart"
    base_url: str = "https://www.walmart.com"

    # Walmart API endpoints
    _API_BASE = "https://www.walmart.com"
    _CART_URL = "https://www.walmart.com/api/shopping-cart"
    _CHECKOUT_URL = "https://www.walmart.com/checkout"

    def __init__(self, config: Any) -> None:
        """Initialize the Walmart adapter.

        Args:
            config: Validated Config instance.
        """
        super().__init__(config)
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._playwright: Playwright | None = None
        self._logged_in: bool = False
        self._auth_token: str = ""
        self._cart_token: str = ""
        self._proxy: dict[str, str] | None = None

    # ── Logger ───────────────────────────────────────────────────────────────

    def _set_logger(self, logger: Logger) -> None:
        """Inject logger instance.

        Args:
            logger: Logger instance for structured logging.
        """
        self._logger = logger

    def _log(self, level: str, event: str, **kwargs: Any) -> None:
        """Log an event via the injected logger or fallback to print.

        Args:
            level: Log level (DEBUG, INFO, WARNING, ERROR).
            event: Event name string.
            **kwargs: Additional event data.
        """
        if self._logger:
            getattr(self._logger, level.lower())(event, retailer="walmart", **kwargs)
        else:
            print(f"[{level}] {event} | {kwargs}")

    # ── Browser Setup ──────────────────────────────────────────────────────

    async def _ensure_browser(self) -> BrowserContext:
        """Ensure Playwright browser is initialized with anti-detection.

        Returns:
            BrowserContext ready for use.
        """
        if self._context is not None:
            return self._context

        self._playwright = await async_playwright().start()

        # Import evasion modules lazily
        get_random_fingerprint: Any = None
        get_random_user_agent: Any = None
        try:
            from src.bot.evasion.fingerprint import get_random_fingerprint
            from src.bot.evasion.user_agents import get_random_user_agent
        except ImportError:
            pass

        # Build launch args for anti-detection
        launch_args: list[str] = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ]

        # Build proxy URL string for Playwright
        proxy_url_str: str | None = None
        if self._proxy:
            auth = (
                f"{self._proxy['username']}:{self._proxy['password']}@"
                if self._proxy.get("username") and self._proxy.get("password")
                else ""
            )
            proxy_url_str = f"http://{auth}{self._proxy['host']}:{self._proxy['port']}"

        # Randomize viewport
        viewport_width = random.randint(1280, 1920)
        viewport_height = random.randint(720, 1080)

        # Get user agent
        ua: str
        if get_random_user_agent is not None:
            ua = get_random_user_agent()
        else:
            ua = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )

        # Get fingerprint
        fp: Any = None
        if get_random_fingerprint is not None:
            fp = get_random_fingerprint(ua)

        # Proxy config for Playwright
        browser_proxy: dict[str, str] | None = (
            {"server": proxy_url_str} if proxy_url_str else None
        )

        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=launch_args,
            proxy=browser_proxy,  # type: ignore[arg-type]
        )

        # Build context options
        context_options: dict[str, Any] = {
            "viewport": {"width": viewport_width, "height": viewport_height},
            "locale": _random_locale(),
            "timezone_id": _random_timezone(),
            "user_agent": ua,
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
            },
        }

        # Apply fingerprint properties if available
        if fp is not None:
            context_options["device_scale_factor"] = fp.device_scale_factor
            context_options["has_touch"] = False

        self._context = await self._browser.new_context(**context_options)

        # Inject automation masking scripts
        await self._context.add_init_script(_STEALTH_SCRIPT)

        self._page = await self._context.new_page()
        return self._context

    async def _close_browser(self) -> None:
        """Close Playwright browser and release resources."""
        if self._page:
            await self._page.close()
            self._page = None
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    # ── Login ──────────────────────────────────────────────────────────────

    async def login(self, username: str, password: str) -> bool:
        """Authenticate with walmart.com using Playwright.

        Args:
            username: Walmart.com account email.
            password: Walmart.com account password.

        Returns:
            True on successful login, False otherwise.
        """
        try:
            await self._ensure_browser()
            if self._page is None:
                return False

            self._log("INFO", "LOGIN_STARTED", username=username[:3] + "***")

            # Navigate to sign-in page
            await self._page.goto(
                "https://www.walmart.com/account/login",
                wait_until="networkidle",
                timeout=30000,
            )

            # Fill email field
            await self._page.fill('input[id="email"]', username, timeout=10000)
            await asyncio.sleep(random.uniform(0.3, 0.7))

            # Click continue or submit button
            submit_btn = self._page.locator('button[type="submit"], button:has-text("Continue")')
            try:
                await submit_btn.first.click()
                await self._page.wait_for_load_state("networkidle", timeout=10000)
                await asyncio.sleep(random.uniform(0.3, 0.7))
            except Exception:  # noqa: BLE001
                pass

            # Fill password field
            await self._page.fill('input[id="password"]', password, timeout=10000)
            await asyncio.sleep(random.uniform(0.2, 0.5))

            # Submit the form
            await self._page.click('button[type="submit"]:has-text("Sign In"), button:has-text("Sign in")')
            await self._page.wait_for_load_state("networkidle", timeout=30000)

            # Verify login success
            logged_in = await self._verify_login_success()
            if logged_in:
                self._logged_in = True
                self._auth_token = await self._extract_auth_token()
                await self._save_cookies()
                self._log("INFO", "LOGIN_SUCCESS")
                return True
            else:
                self._logged_in = False
                self._log("WARNING", "LOGIN_FAILED_VERIFICATION")
                return False

        except Exception as exc:  # noqa: BLE001
            self._log("ERROR", "LOGIN_ERROR", error=str(exc))
            return False

    async def _verify_login_success(self) -> bool:
        """Check if current page reflects a successful login."""
        if self._page is None:
            return False
        try:
            # Look for account button/header which indicates logged-in state
            await self._page.wait_for_selector(
                '[data-automation-id="account-button"], '
                'button:has-text("Account"), '
                '[data-automation-id="user-nav"]',
                timeout=5000,
            )
            return True
        except Exception:  # noqa: BLE001
            pass
        # Check URL - should not contain 'login'
        url = self._page.url.lower()
        return "login" not in url or "/account/" not in url

    async def _extract_auth_token(self) -> str:
        """Extract authentication token from cookies."""
        if self._context is None:
            return ""
        for cookie in await self._context.cookies():
            if cookie["name"] in ("t", "token", "sessionId", "auth", "pdsession"):
                return cookie["value"]
        return ""

    async def _save_cookies(self) -> None:
        """Persist current browser cookies to session state."""
        if self._context is None:
            return
        cookies = await self._context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}
        await self.save_session_state(
            cookies=cookie_dict,
            auth_token=self._auth_token,
            cart_token=self._cart_token,
        )

    # ── Stock Check ────────────────────────────────────────────────────────

    async def check_stock(self, sku: str) -> StockStatus:
        """Check if a SKU is in stock at Walmart.com.

        Args:
            sku: Walmart.com product SKU (usually numeric, e.g., "12345678").

        Returns:
            StockStatus indicating whether the item is available.
        """
        try:
            await self._ensure_browser()
            if self._page is None:
                return StockStatus(in_stock=False, sku=sku)

            product_url = f"https://www.walmart.com/ip/{sku}"

            self._log("DEBUG", "STOCK_CHECK", sku=sku, url=product_url)

            # Try API first (faster)
            api_status = await self._check_stock_api(sku)
            if api_status is not None:
                return api_status

            # Fall back to page scraping via Playwright
            await self._page.goto(
                product_url,
                wait_until="domcontentloaded",
                timeout=20000,
            )

            try:
                await self._page.wait_for_selector(
                    '[data-automation-id="product-title"], h1[itemprop="name"]',
                    timeout=10000,
                )
            except Exception:  # noqa: BLE001
                pass

            in_stock, available_qty = await self._parse_stock_from_page(sku)

            self._log(
                "DEBUG",
                "STOCK_CHECK_RESULT",
                sku=sku,
                in_stock=in_stock,
                quantity=available_qty,
            )

            return StockStatus(
                in_stock=in_stock,
                sku=sku,
                url=product_url,
                available_quantity=available_qty,
            )

        except Exception as exc:  # noqa: BLE001
            self._log("ERROR", "STOCK_CHECK_ERROR", sku=sku, error=str(exc))
            return StockStatus(in_stock=False, sku=sku)

    async def _check_stock_api(self, sku: str) -> StockStatus | None:
        """Query Walmart's API for stock status."""
        try:
            # Walmart uses a product API endpoint
            api_url = (
                f"https://www.walmart.com/api/product/v3/items/{sku}"
                f"?fields=buyability,availability,price,quantity"
            )
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Referer": "https://www.walmart.com/",
            }
            timeout = httpx.Timeout(10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(api_url, headers=headers)
                if resp.status_code != 200:
                    return None

                data = resp.json()

                # Parse availability from response
                status = data.get("product", {}).get("availability", "UNAVAILABLE")
                in_stock = status in ("AVAILABLE", "LIMITED_SUPPLY")
                available_qty = data.get("product", {}).get("quantity", 0)

                return StockStatus(
                    in_stock=in_stock,
                    sku=sku,
                    available_quantity=available_qty,
                )
        except Exception:  # noqa: BLE001
            return None

    async def check_stock_by_keyword(self, keyword: str) -> StockStatus:
        """Check for in-stock items matching a keyword at Walmart.com.

        Navigates to the Walmart search page for the keyword, collects product
        links from search results, and checks each product page for stock.
        Returns the first in-stock match.

        Args:
            keyword: Search keyword (e.g., "Charizard Elite Trainer Box").

        Returns:
            StockStatus with in_stock=True and matched item details, or
            in_stock=False if no matching in-stock item found.
        """
        try:
            await self._ensure_browser()
            if self._page is None:
                return StockStatus(in_stock=False, sku="")

            search_url = (
                f"https://www.walmart.com/search?q="
                f"{keyword.replace(' ', '+')}"
            )

            self._log("DEBUG", "KEYWORD_SEARCH_START", keyword=keyword, url=search_url)

            await self._page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=20000,
            )

            # Wait for search results
            try:
                await self._page.wait_for_selector(
                    '[data-automation-id="product-list"] a[href*="/ip/"]',
                    timeout=15000,
                )
            except Exception:  # noqa: BLE001:
                pass

            # Collect product links
            product_links: list[str] = []
            try:
                link_els = await self._page.query_selector_all(
                    'a[href*="/ip/"][href*="/dp/"]'
                )
                seen: set[str] = set()
                for el in link_els[:10]:
                    href = await el.get_attribute("href")
                    if href and "/ip/" in href:
                        # Extract product ID for SKU
                        match = self._extract_sku_from_url(href)
                        if match and match not in seen:
                            seen.add(match)
                            full_url = (
                                href
                                if href.startswith("http")
                                else f"https://www.walmart.com{href}"
                            )
                            product_links.append(full_url)
            except Exception:  # noqa: BLE001:
                pass

            self._log(
                "DEBUG",
                "KEYWORD_SEARCH_RESULTS",
                keyword=keyword,
                product_count=len(product_links),
            )

            for product_url in product_links:
                try:
                    sku_from_url = self._extract_sku_from_url(product_url)
                    if not sku_from_url:
                        continue

                    await self._page.goto(
                        product_url,
                        wait_until="domcontentloaded",
                        timeout=15000,
                    )

                    try:
                        await self._page.wait_for_selector(
                            '[data-automation-id="product-title"], h1[itemprop="name"]',
                            timeout=8000,
                        )
                    except Exception:  # noqa: BLE001:
                        pass

                    in_stock, available_qty = await self._parse_stock_from_page(
                        sku_from_url
                    )

                    if in_stock:
                        self._log(
                            "DEBUG",
                            "KEYWORD_MATCH_FOUND",
                            keyword=keyword,
                            sku=sku_from_url,
                            url=product_url,
                            quantity=available_qty,
                        )
                        return StockStatus(
                            in_stock=True,
                            sku=sku_from_url,
                            url=product_url,
                            available_quantity=available_qty,
                        )

                except Exception:  # noqa: BLE001:
                    continue

            return StockStatus(in_stock=False, sku="")

        except Exception as exc:  # noqa: BLE001
            self._log(
                "ERROR",
                "KEYWORD_SEARCH_ERROR",
                keyword=keyword,
                error=str(exc),
            )
            return StockStatus(in_stock=False, sku="")

    @staticmethod
    def _extract_sku_from_url(url: str) -> str:
        """Extract SKU/product ID from a Walmart product URL.

        Args:
            url: Walmart product URL (e.g., https://www.walmart.com/ip/.../dp/12345678).

        Returns:
            Product ID string or empty string if not found.
        """
        import re

        # Pattern: /ip/name/dp/SKU or /ip/name/prodId/sku
        match = re.search(r"/(?:dp|prodId)/([0-9]+)", url)
        if match:
            return match.group(1)
        # Fallback: /ip/name/sku
        match = re.search(r"/ip/[^/]+/([0-9]+)", url)
        if match:
            return match.group(1)
        return ""

    async def _parse_stock_from_page(
        self,
        sku: str,
    ) -> tuple[bool, int]:
        """Parse stock status from product page DOM."""
        if self._page is None:
            return False, 0

        in_stock = False
        qty = 1

        try:
            # Look for Add to Cart button which indicates in-stock
            add_to_cart_selectors = [
                '[data-automation-id="add-to-cart"]',
                'button:has-text("Add to cart")',
                'button:has-text("Add to Cart")',
                '[data-automation-id="addToCartButton"]',
                'button:has-text("Pickup")',
                '[data-automation-id="fulfillment"]',
            ]
            for selector in add_to_cart_selectors:
                try:
                    el = await self._page.wait_for_selector(
                        selector,
                        timeout=3000,
                    )
                    if el and await el.is_enabled() and await el.is_visible():
                        btn_text = await el.inner_text()
                        if "out of stock" not in btn_text.lower():
                            in_stock = True
                            break
                except Exception:  # noqa: BLE001:
                    continue

            # Check for out of stock indicators
            if not in_stock:
                oos_selectors = [
                    '[data-automation-id="out-of-stock"]',
                    'span:has-text("Out of stock")',
                    'div:has-text("Out of Stock")',
                    'span:has-text("Sold out")',
                ]
                for selector in oos_selectors:
                    try:
                        el = await self._page.wait_for_selector(
                            selector,
                            timeout=2000,
                        )
                        if el and await el.is_visible():
                            in_stock = False
                            break
                    except Exception:  # noqa: BLE001:
                        continue

            # Try to get quantity input
            try:
                qty_el = await self._page.query_selector('input[id="quantity"]')
                if qty_el:
                    qty_str = await qty_el.get_attribute("value") or "1"
                    qty = max(1, int(qty_str.strip()))
            except Exception:  # noqa: BLE001:
                qty = 1

        except Exception:  # noqa: BLE001:
            pass

        return in_stock, qty

    # ── Cart ───────────────────────────────────────────────────────────────

    async def add_to_cart(self, sku: str, quantity: int = 1) -> bool:
        """Add a SKU to the cart.

        Args:
            sku: Product SKU to add.
            quantity: Number of items to add.

        Returns:
            True on success, False on failure.
        """
        try:
            self._log("DEBUG", "CART_ADD_ATTEMPT", sku=sku, quantity=quantity)

            # Respect max_cart_quantity from retailer config
            max_qty = 1
            retailer_cfg = self.get_retailer_config()
            if retailer_cfg is not None:
                retailer_items = getattr(retailer_cfg, "items", None)
                if isinstance(retailer_items, list) and retailer_items:
                    for item in retailer_items:
                        item_skus = item.get("skus", []) if isinstance(item, dict) else getattr(item, "skus", [])
                        if sku in item_skus:
                            max_qty = item.get("max_cart_quantity", 1) if isinstance(item, dict) else getattr(item, "max_cart_quantity", 1)
                            break
            if max_qty == 1:
                config_items = getattr(self.config, "items", None)
                if isinstance(config_items, list) and config_items:
                    first_item = config_items[0]
                    max_qty = getattr(first_item, "max_cart_quantity", 1)
            quantity = min(quantity, max_qty)

            # Try API first
            api_success = await self._add_to_cart_api(sku, quantity)
            if api_success:
                self._log("INFO", "CART_ADD_SUCCESS_API", sku=sku, quantity=quantity)
                return True

            # Fall back to UI automation
            ui_success = await self._add_to_cart_ui(sku, quantity)
            if ui_success:
                self._log(
                    "INFO",
                    "CART_ADD_SUCCESS_UI",
                    sku=sku,
                    quantity=quantity,
                )
                return True

            self._log("WARNING", "CART_ADD_FAILED", sku=sku)
            return False

        except Exception as exc:  # noqa: BLE001
            self._log("ERROR", "CART_ADD_ERROR", sku=sku, error=str(exc))
            return False

    async def _add_to_cart_api(
        self,
        sku: str,
        quantity: int,
    ) -> bool:
        """Add item via Walmart's cart API."""
        if not self._auth_token:
            return False

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._auth_token}",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": f"https://www.walmart.com/ip/{sku}",
                "Accept": "application/json",
            }
            payload = {
                "sku": str(sku),
                "quantity": quantity,
            }
            timeout = httpx.Timeout(10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    self._CART_URL,
                    headers=headers,
                    json=payload,
                )
                return resp.status_code in (200, 201, 202, 204)
        except Exception:  # noqa: BLE001
            return False

    async def _add_to_cart_ui(
        self,
        sku: str,
        quantity: int,
    ) -> bool:
        """Add item to cart via Playwright UI automation."""
        if self._page is None:
            return False

        try:
            product_url = f"https://www.walmart.com/ip/{sku}"
            await self._page.goto(
                product_url,
                wait_until="networkidle",
                timeout=20000,
            )

            await asyncio.sleep(random.uniform(0.5, 1.0))

            # Select quantity if available
            try:
                qty_select = await self._page.query_selector('select[id="quantity"]')
                if qty_select:
                    await qty_select.select_option(str(quantity))
            except Exception:  # noqa: BLE001:
                pass

            add_btn_selectors = [
                '[data-automation-id="add-to-cart"]',
                'button:has-text("Add to cart")',
                'button:has-text("Add to Cart")',
                '[data-automation-id="addToCartButton"]',
                'button:has-text("Pickup")',
            ]

            added = False
            for selector in add_btn_selectors:
                try:
                    btn = await self._page.wait_for_selector(
                        selector,
                        timeout=5000,
                    )
                    if btn and await btn.is_enabled():
                        await btn.click()
                        added = True
                        await asyncio.sleep(1.0)
                        break
                except Exception:  # noqa: BLE001:
                    continue

            return added

        except Exception:  # noqa: BLE001
            return False

    async def get_cart(self) -> list[dict[str, Any]]:
        """Return current cart contents.

        Returns:
            List of cart item dicts with sku, name, quantity, price keys.
        """
        try:
            api_items = await self._get_cart_api()
            if api_items is not None:
                return api_items
            return await self._get_cart_ui()

        except Exception as exc:  # noqa: BLE001
            self._log("ERROR", "CART_GET_ERROR", error=str(exc))
            return []

    async def _get_cart_api(self) -> list[dict[str, Any]] | None:
        """Fetch cart via Walmart's API."""
        if not self._auth_token:
            return None
        try:
            headers = {
                "Authorization": f"Bearer {self._auth_token}",
                "Accept": "application/json",
            }
            timeout = httpx.Timeout(10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(self._CART_URL, headers=headers)
                if resp.status_code != 200:
                    return None

                data = resp.json()
                items: list[dict[str, Any]] = []
                for item in data.get("items", []):
                    items.append({
                        "sku": item.get("sku", ""),
                        "name": item.get("title", ""),
                        "quantity": item.get("quantity", 1),
                        "price": item.get("price", ""),
                    })
                return items
        except Exception:  # noqa: BLE001
            return None

    async def _get_cart_ui(self) -> list[dict[str, Any]]:
        """Navigate to cart page and scrape items via Playwright."""
        if self._page is None:
            return []
        try:
            await self._page.goto(
                "https://www.walmart.com/cart",
                wait_until="networkidle",
                timeout=20000,
            )
            await asyncio.sleep(1.0)

            items: list[dict[str, Any]] = []
            # Walmart cart items are in list items with data-automation-id
            item_rows = await self._page.query_selector_all(
                '[data-automation-id="cart-item"]',
            )
            for row in item_rows:
                try:
                    name_el = await row.query_selector('[data-automation-id="product-title"], h4 a')
                    qty_el = await row.query_selector('select[id="quantity"]')
                    price_el = await row.query_selector('[data-automation-id="product-price"]')
                    sku_el = await row.query_selector('[data-automation-id="product-sku"]')
                    items.append({
                        "sku": await sku_el.get_attribute("data-sku") if sku_el else "",
                        "name": await name_el.inner_text() if name_el else "",
                        "quantity": int(
                            (await qty_el.get_attribute("value") or "1") if qty_el else "1"
                        ),
                        "price": await price_el.inner_text() if price_el else "",
                    })
                except Exception:  # noqa: BLE001:
                    continue
            return items

        except Exception:  # noqa: BLE001
            return []

    # ── Checkout ───────────────────────────────────────────────────────────

    async def checkout(
        self,
        shipping: ShippingInfo,
        payment: PaymentInfo,
    ) -> dict[str, Any]:
        """Complete checkout for the current cart.

        Args:
            shipping: Shipping address from config.
            payment: Payment card from config.

        Returns:
            Dict with keys: success (bool), order_id (str), error (str).
        """
        max_attempts = getattr(
            self.config.checkout,
            "retry_attempts",
            2,
        )

        for attempt in range(1, max_attempts + 1):
            try:
                self._log(
                    "INFO",
                    "CHECKOUT_ATTEMPT",
                    attempt=attempt,
                    max_attempts=max_attempts,
                )

                result = await self._run_checkout_flow(shipping, payment, attempt)
                if result.get("success"):
                    return result

                if not result.get("success") and attempt < max_attempts:
                    await self._clear_cart()
                    await asyncio.sleep(2.0)

            except Exception as exc:  # noqa: BLE001
                self._log(
                    "ERROR",
                    "CHECKOUT_ERROR",
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt == max_attempts:
                    return {
                        "success": False,
                        "order_id": "",
                        "error": f"Checkout failed after {max_attempts} attempts: {exc}",
                    }

        return {
            "success": False,
            "order_id": "",
            "error": f"Checkout failed after {max_attempts} attempts",
        }

    async def _run_checkout_flow(
        self,
        shipping: ShippingInfo,
        payment: PaymentInfo,
        attempt: int,
    ) -> dict[str, Any]:
        """Execute the multi-step checkout flow."""
        if self._page is None:
            return {"success": False, "order_id": "", "error": "No browser session"}

        try:
            self._log("DEBUG", "CHECKOUT_NAVIGATE")
            await self._page.goto(
                "https://www.walmart.com/checkout",
                wait_until="networkidle",
                timeout=30000,
            )
            await self._human_delay()

            checkout_result = await self._handle_checkout_page(shipping, payment)
            if not checkout_result["success"]:
                return checkout_result

            review_result = await self._handle_review_step()
            if not review_result["success"]:
                return review_result

            submit_result = await self._submit_order()
            return submit_result

        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "order_id": "",
                "error": str(exc),
            }

    async def _handle_checkout_page(
        self,
        shipping: ShippingInfo,
        payment: PaymentInfo,
    ) -> dict[str, Any]:
        """Fill shipping and payment on checkout page."""
        if self._page is None:
            return {"success": False, "order_id": "", "error": "No page"}

        try:
            await self._fill_shipping(shipping)
            await self._human_delay()

            await self._fill_payment(payment)
            await self._human_delay()

            return {"success": True, "order_id": "", "error": ""}

        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "order_id": "",
                "error": f"Shipping/payment fill failed: {exc}",
            }

    async def _fill_shipping(self, shipping: ShippingInfo) -> None:
        """Fill shipping address form fields."""
        if self._page is None:
            return

        field_mapping: list[tuple[str, str]] = [
            ('input[id="firstName"]', shipping.name.split()[0] if shipping.name else ""),
            ('input[id="lastName"]', " ".join(shipping.name.split()[1:]) if shipping.name else ""),
            ('input[id="addressLineOne"]', shipping.address1),
            ('input[id="addressLineTwo"]', shipping.address2 or ""),
            ('input[id="city"]', shipping.city),
            ('select[id="state"]', shipping.state),
            ('input[id="postalCode"]', shipping.zip_code),
            ('input[id="phone"]', shipping.phone),
            ('input[id="email"]', shipping.email),
        ]

        for selector, value in field_mapping:
            if not value:
                continue
            try:
                el = await self._page.query_selector(selector)
                if el:
                    await el.fill(value)
                    await asyncio.sleep(random.uniform(0.1, 0.3))
            except Exception:  # noqa: BLE001:
                pass

        # Check "billing same as shipping" if billing fields are separate
        try:
            same_as_shipping = await self._page.query_selector(
                'input[id="billingAddressSameAsShipping"]'
            )
            if same_as_shipping:
                await same_as_shipping.check()
        except Exception:  # noqa: BLE001:
            pass

    async def _fill_payment(self, payment: PaymentInfo) -> None:
        """Fill payment card form fields."""
        if self._page is None:
            return

        try:
            # Card number
            card_field = await self._page.query_selector('input[id="cardNumber"]')
            if card_field:
                await card_field.fill(payment.card_number)
                await asyncio.sleep(random.uniform(0.15, 0.35))
        except Exception:  # noqa: BLE001:
            pass

        # Expiry month/year
        for mm_sel, yy_sel in [
            ('select[id="expiryMonth"]', 'select[id="expiryYear"]'),
            ('select[id="cardExpiryMonth"]', 'select[id="cardExpiryYear"]'),
        ]:
            try:
                mm_el = await self._page.query_selector(mm_sel)
                yy_el = await self._page.query_selector(yy_sel)
                if mm_el and payment.expiry_month:
                    await mm_el.select_option(payment.expiry_month)
                if yy_el and payment.expiry_year:
                    await yy_el.select_option(payment.expiry_year)
                break
            except Exception:  # noqa: BLE001:
                continue

        # CVV
        try:
            cvv_field = await self._page.query_selector('input[id="cvv"]')
            if cvv_field:
                await cvv_field.fill(payment.cvv)
        except Exception:  # noqa: BLE001:
            pass

    async def _handle_review_step(self) -> dict[str, Any]:
        """Handle order review / terms acknowledgement step."""
        if self._page is None:
            return {"success": False, "order_id": "", "error": "No page"}

        try:
            # Look for and check terms checkbox if present
            terms_selectors = [
                'input[id="terms"]',
                'input[id="agreedToTerms"]',
                'input[data-automation-id="terms-checkbox"]',
            ]
            for selector in terms_selectors:
                try:
                    terms_cb = await self._page.query_selector(selector)
                    if terms_cb and not await terms_cb.is_checked():
                        await terms_cb.check()
                        await asyncio.sleep(0.2)
                        break
                except Exception:  # noqa: BLE001:
                    continue

            # Find and click Place Order button
            place_order_selectors = [
                'button:has-text("Place order")',
                'button:has-text("Submit Order")',
                '[data-automation-id="place-order"]',
                'button:has-text("Place Order")',
            ]
            for selector in place_order_selectors:
                try:
                    btn = await self._page.wait_for_selector(
                        selector,
                        timeout=5000,
                    )
                    if btn and await btn.is_enabled():
                        async with self._page.expect_navigation(
                            timeout=30000,
                        ):
                            await btn.click()
                        return {"success": True, "order_id": "", "error": ""}
                except Exception:  # noqa: BLE001:
                    continue

            return {
                "success": False,
                "order_id": "",
                "error": "Could not find Place Order button",
            }

        except Exception as exc:  # noqa: BLE001
            return {"success": False, "order_id": "", "error": f"Review step failed: {exc}"}

    async def _submit_order(self) -> dict[str, Any]:
        """Submit the order and capture confirmation number."""
        if self._page is None:
            return {"success": False, "order_id": "", "error": "No page"}

        try:
            # Wait for confirmation page
            try:
                await self._page.wait_for_selector(
                    '[data-automation-id="confirmation-number"], '
                    '[data-automation-id="order-confirmation"]',
                    timeout=30000,
                )
            except Exception:  # noqa: BLE001:
                pass

            order_id = ""
            confirmation_selectors = [
                '[data-automation-id="confirmation-number"]',
                'p:has-text("Confirmation")',
                'h1:has-text("Thank you for your order")',
                '[data-automation-id="order-number"]',
            ]
            for selector in confirmation_selectors:
                try:
                    el = await self._page.query_selector(selector)
                    if el:
                        text = await el.inner_text()
                        match = re.search(r"[A-Z0-9]{8,}", text)
                        if match:
                            order_id = match.group(0)
                            break
                except Exception:  # noqa: BLE001:
                    continue

            total = ""
            try:
                total_el = await self._page.query_selector(
                    '[data-automation-id="order-total"]'
                )
                if total_el:
                    total = await total_el.inner_text()
            except Exception:  # noqa: BLE001:
                pass

            self._log(
                "INFO",
                "CHECKOUT_SUCCESS",
                order_id=order_id,
                total=total,
            )

            return {
                "success": bool(order_id),
                "order_id": order_id,
                "total": total,
                "error": "" if order_id else "Order submitted but confirmation not found",
            }

        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "order_id": "",
                "error": f"Order submission failed: {exc}",
            }

    async def _clear_cart(self) -> bool:
        """Clear all items from cart."""
        try:
            if self._page:
                await self._page.goto(
                    "https://www.walmart.com/cart",
                    wait_until="networkidle",
                    timeout=15000,
                )
                remove_btns = await self._page.query_selector_all(
                    'button:has-text("Remove"), button:has-text("Delete")'
                )
                for btn in remove_btns:
                    try:
                        await btn.click()
                        await asyncio.sleep(0.5)
                    except Exception:  # noqa: BLE001:
                        continue
            return True
        except Exception:  # noqa: BLE001
            return False

    async def _human_delay(self, base_ms: int = 300) -> None:
        """Inject human-like delay between checkout steps.

        Args:
            base_ms: Base delay in milliseconds (default 300).
        """
        delay = base_ms + random.randint(-50, 50)
        await asyncio.sleep(delay / 1000.0)

    # ── CAPTCHA ─────────────────────────────────────────────────────────────

    async def handle_captcha(self, page: Any) -> CaptchaSolveResult:
        """Detect and handle any CAPTCHA challenge on the given page.

        Args:
            page: Playwright Page instance.

        Returns:
            CaptchaSolveResult with success, token, solve_time_ms.
        """
        if page is None:
            return CaptchaSolveResult(success=False, error="No page provided")

        start_time = time.monotonic()

        try:
            captcha_type = await self._detect_captcha_type(page)

            if captcha_type == CaptchaType.UNKNOWN:
                return CaptchaSolveResult(
                    success=False,
                    error="No CAPTCHA detected or unknown type",
                )

            captcha_mode = getattr(self.config.captcha, "mode", "smart")
            self._log(
                "INFO",
                "CAPTCHA_DETECTED",
                type=captcha_type.value,
                mode=captcha_mode,
            )

            if captcha_mode == "manual":
                return await self._handle_manual_captcha(page, captcha_type, start_time)
            elif captcha_mode == "auto":
                return await self._handle_auto_captcha(
                    page, captcha_type, start_time
                )
            elif captcha_mode == "smart":
                if captcha_type == CaptchaType.TURNSTILE:
                    return await self._handle_auto_captcha(
                        page, captcha_type, start_time
                    )
                else:
                    return await self._handle_manual_captcha(
                        page, captcha_type, start_time
                    )

            return CaptchaSolveResult(
                success=False,
                error=f"Unknown CAPTCHA mode: {captcha_mode}",
            )

        except Exception as exc:  # noqa: BLE001
            return CaptchaSolveResult(success=False, error=str(exc))

    async def _detect_captcha_type(self, page: Any) -> CaptchaType:
        """Detect CAPTCHA type on the current page."""
        try:
            # Check for reCAPTCHA
            try:
                await page.wait_for_selector(
                    'iframe[src*="google.com/recaptcha"]',
                    timeout=2000,
                )
                return CaptchaType.RECAPTCHA_V2
            except Exception:  # noqa: BLE001:
                pass

            # Check for hCaptcha
            try:
                await page.wait_for_selector(
                    'iframe[src*="hcaptcha.com"]',
                    timeout=2000,
                )
                return CaptchaType.HCAPTCHA
            except Exception:  # noqa: BLE001:
                pass

            # Check for Turnstile
            try:
                await page.wait_for_selector(
                    'iframe[src*="challenges.cloudflare.com"]',
                    timeout=2000,
                )
                return CaptchaType.TURNSTILE
            except Exception:  # noqa: BLE001:
                pass

            return CaptchaType.UNKNOWN

        except Exception:  # noqa: BLE001
            return CaptchaType.UNKNOWN

    async def _handle_manual_captcha(
        self,
        page: Any,
        captcha_type: CaptchaType,
        start_time: float,
    ) -> CaptchaSolveResult:
        """Handle CAPTCHA in manual mode: pause and notify operator."""
        timeout_seconds = 120
        self._log(
            "WARNING",
            "CAPTCHA_PENDING_MANUAL",
            retailer="walmart",
            captcha_type=captcha_type.value,
            pause_url=str(page.url) if page else "",
            timeout_seconds=timeout_seconds,
        )

        try:
            await asyncio.wait_for(
                self._wait_for_captcha_resolved(page),
                timeout=timeout_seconds,
            )
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return CaptchaSolveResult(
                success=True,
                token="",
                solve_time_ms=elapsed_ms,
            )
        except asyncio.TimeoutError:
            return CaptchaSolveResult(
                success=False,
                error=f"Manual CAPTCHA timed out after {timeout_seconds}s",
            )

    async def _wait_for_captcha_resolved(self, page: Any) -> None:
        """Wait until CAPTCHA challenge is no longer visible on page."""
        while True:
            try:
                el = await page.query_selector(
                    'iframe[src*="google.com/recaptcha"], '
                    'iframe[src*="hcaptcha.com"], '
                    'iframe[src*="challenges.cloudflare.com"]'
                )
                if not el or not await el.is_visible():
                    break
                await asyncio.sleep(2)
            except Exception:  # noqa: BLE001:
                break

    async def _handle_auto_captcha(
        self,
        page: Any,
        captcha_type: CaptchaType,
        start_time: float,
    ) -> CaptchaSolveResult:
        """Handle CAPTCHA in auto mode via 2Captcha."""
        try:
            site_key = await self._extract_site_key(page, captcha_type)
            page_url = page.url

            if not site_key:
                return CaptchaSolveResult(
                    success=False,
                    error=f"Could not extract site key for {captcha_type.value}",
                )

            self._log("INFO", "CAPTCHA_2CAPTCHA_SUBMIT", site_key=site_key)

            solver = self._get_2captcha_solver()
            if solver is None:
                return CaptchaSolveResult(
                    success=False,
                    error="2Captcha solver not configured",
                )

            token = await solver.solve(site_key, page_url, captcha_type.value)

            solve_time_ms = int((time.monotonic() - start_time) * 1000)
            self._log(
                "INFO",
                "CAPTCHA_2CAPTCHA_SOLVED",
                solve_time_ms=solve_time_ms,
            )

            await self._inject_captcha_token(page, captcha_type, token)

            return CaptchaSolveResult(
                success=True,
                token=token,
                solve_time_ms=solve_time_ms,
            )

        except Exception as exc:  # noqa: BLE001
            return CaptchaSolveResult(success=False, error=str(exc))

    async def _extract_site_key(
        self,
        page: Any,
        captcha_type: CaptchaType,
    ) -> str:
        """Extract CAPTCHA site key from page."""
        try:
            if captcha_type in (CaptchaType.RECAPTCHA_V2, CaptchaType.HCAPTCHA):
                selectors = ['[data-sitekey]']
                for selector in selectors:
                    el = await page.query_selector(selector)
                    if el:
                        key = await el.get_attribute("data-sitekey")
                        if key:
                            return key  # type: ignore[no-any-return]
                page_content = await page.content()
                pattern = r"data-sitekey\s*[=:]\s*['\"']([A-Za-z0-9_-]+)['\"']"
                match = re.search(pattern, page_content)
                if match:
                    g1: str | None = match.group(1)
                    if g1 is not None:
                        return g1

            elif captcha_type == CaptchaType.TURNSTILE:
                selectors = ['[data-sitekey]']
                for selector in selectors:
                    el = await page.query_selector(selector)
                    if el:
                        key = await el.get_attribute("data-sitekey")
                        if key:
                            return key  # type: ignore[no-any-return]
                page_content = await page.content()
                pattern = r"sitekey\s*[=:]\s*['\"']([A-Za-z0-9_-]+)['\"']"
                match = re.search(pattern, page_content)
                if match:
                    g2: str | None = match.group(1)
                    if g2 is not None:
                        return g2
            return ""
        except Exception:  # noqa: BLE001
            return ""

    async def _inject_captcha_token(
        self,
        page: Any,
        captcha_type: CaptchaType,
        token: str,
    ) -> None:
        """Inject CAPTCHA solution token into the page."""
        try:
            if captcha_type == CaptchaType.RECAPTCHA_V2:
                await page.evaluate(
                    f"""
                    document.querySelectorAll('textarea[name="g-recaptcha-response"]')
                        .forEach(el => el.value = "{token}");
                    """
                )
            elif captcha_type == CaptchaType.TURNSTILE:
                await page.evaluate(
                    f"""
                    document.querySelectorAll('[name="cf-turnstile-response"]')
                        .forEach(el => el.value = "{token}");
                    document.dispatchEvent(new Event('turnstileSuccess'));
                    """
                )
        except Exception:  # noqa: BLE001:
            pass

    # ── Queue Detection ───────────────────────────────────────────────────

    async def check_queue(self) -> bool:
        """Return True if currently in a queue/waiting room.

        Returns:
            True if queue/waiting room detected, False otherwise.
        """
        if self._page is None:
            return False

        try:
            url = self._page.url.lower()
            page_title = (await self._page.title()).lower()

            queue_indicators = [
                "queue",
                "waiting",
                "virtual wait",
                "waitlist",
                "please wait",
            ]

            for indicator in queue_indicators:
                if indicator in url or indicator in page_title:
                    return True

            try:
                body_text = await self._page.inner_text("body")
                for indicator in queue_indicators:
                    if indicator in body_text.lower():
                        return True
            except Exception:  # noqa: BLE001:
                pass

            return False

        except Exception:  # noqa: BLE001
            return False

    # ── Close ─────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Close all browser resources."""
        await self._close_browser()
        await super().close()

    # ── 2Captcha helper ─────────────────────────────────────────────────

    def _get_2captcha_solver(self) -> Any | None:
        """Return 2Captcha solver instance if configured."""
        api_key = getattr(self.config.captcha, "api_key", "") or ""
        if not api_key:
            import os
            api_key = os.getenv("POKEDROP_2CAPTCHA_KEY", "")

        if not api_key:
            return None

        try:
            from twocaptcha import TwoCaptcha
            return TwoCaptcha(api_key)
        except ImportError:
            return None


# ── Helper functions ──────────────────────────────────────────────────────────


def _random_locale() -> str:
    """Return a random realistic browser locale."""
    locales = [
        "en-US", "en-GB", "en-CA", "de-DE", "fr-FR",
        "es-ES", "it-IT", "nl-NL", "pl-PL", "pt-BR",
    ]
    return random.choice(locales)


def _random_timezone() -> str:
    """Return a random IANA timezone ID."""
    timezones = [
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "America/Phoenix",
        "Europe/London",
        "Europe/Paris",
        "Europe/Berlin",
        "Europe/Amsterdam",
        "Australia/Sydney",
    ]
    return random.choice(timezones)


_STEALTH_SCRIPT = """
// Remove webdriver property
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true
});

// Spoof hardware concurrency
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => navigator.hardwareConcurrency || 8,
    configurable: true
});

// Spoof device memory
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => navigator.deviceMemory || 8,
    configurable: true
});

// Remove automation-related permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);

// Block automation-related property access
try {
    window.navigator.connection = undefined;
} catch(e) {}

// Spoof canvas noise (fingerprint resistance)
const originalGetImageData = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function(type, ...args) {
    const context = originalGetImageData.call(this, type, ...args);
    if (type === '2d') {
        const origGetImageData = context.getImageData;
        context.getImageData = function(sx, sy, sw, sh) {
            const imageData = origGetImageData.call(this, sx, sy, sw, sh);
            const data = imageData.data;
            for (let i = 0; i < data.length; i += 4) {
                data[i] = data[i] ^ (Math.random() * 2);
            }
            return imageData;
        };
    }
    return context;
};
"""
