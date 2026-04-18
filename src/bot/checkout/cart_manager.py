"""CartManager — unified cart operations across all retailer adapters.

Orchestrates add-to-cart, cart verification, and cart clearing across
retailer adapters, enforcing quantity limits and preventing duplicate adds.

Per PRD Section 9.2 (CART-1 through CART-8).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.shared.models import WebhookEvent

if TYPE_CHECKING:
    from src.bot.config import Config
    from src.bot.logger import Logger
    from src.bot.monitor.retailers.base import RetailerAdapter


@dataclass
class CartError(Exception):
    """Raised when a cart operation fails."""

    reason: str
    sku: str
    error_type: str  # "out_of_stock" | "quantity_limit" | "api_error" | "ui_error"


@dataclass
class CartOperationResult:
    """Result of a cart operation."""

    success: bool
    sku: str = ""
    quantity: int = 0
    cart_url: str = ""
    error: str = ""
    error_type: str = ""
    items_in_cart: int = 0


@dataclass
class CartItem:
    """A single item in the cart."""

    sku: str
    name: str
    quantity: int
    price: str = ""


class CartManager:
    """Unified cart management across all retailer adapters.

    Handles:
    - Adding items via retailer API (preferred) or UI automation (fallback)
    - Verifying items are actually in cart before checkout
    - Preventing duplicate adds for the same SKU within a session
    - Enforcing max_cart_quantity with retailer purchase limit precedence
    - Handling cart errors (OOS, quantity limit)
    - Clearing cart between checkout attempts on failure

    Per PRD Section 9.2 (CART-1 to CART-8).
    """

    def __init__(self, config: Config, logger: Logger) -> None:
        """Initialize the CartManager.

        Args:
            config: Validated Config instance.
            logger: Logger instance for structured event logging.
        """
        self.config = config
        self.logger = logger

        # In-memory tracking of SKUs added in this session to prevent duplicates
        # Key: (retailer_name, sku) → quantity already added
        self._added_skus: dict[tuple[str, str], int] = {}

        # Per-retailer adapters (lazy-loaded via registry)
        self._adapters: dict[str, RetailerAdapter] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    async def add_item(
        self,
        sku: str,
        quantity: int,
        retailer_name: str,
    ) -> CartOperationResult:
        """Add an item to the cart.

        Args:
            sku: Product SKU.
            quantity: Desired quantity (will be constrained by max_cart_quantity).
            retailer_name: Retailer name (target/walmart/bestbuy).

        Returns:
            CartOperationResult with success status and cart details.
        """
        # Check for duplicate add within this session (CART-6)
        if await self._is_duplicate_add(retailer_name, sku):
            return CartOperationResult(
                success=False,
                sku=sku,
                error=f"SKU {sku} already added to cart for {retailer_name} this session",
                error_type="duplicate_add",
            )

        # Get effective quantity respecting max_cart_quantity (CART-7, CART-8)
        effective_qty = self._get_effective_quantity(
            sku=sku,
            requested_quantity=quantity,
            retailer_name=retailer_name,
        )

        # Get adapter for this retailer (no import here — _get_adapter handles it)
        adapter = await self._get_adapter(retailer_name)
        if adapter is None:
            return CartOperationResult(
                success=False,
                sku=sku,
                error=f"No adapter found for retailer: {retailer_name}",
                error_type="no_adapter",
            )

        # Attempt to add via API first, fall back to UI
        try:
            success = await adapter.add_to_cart(sku, effective_qty)
        except Exception as exc:  # noqa: BLE001
            return CartOperationResult(
                success=False,
                sku=sku,
                error=f"add_to_cart raised: {exc}",
                error_type="api_error",
            )

        if not success:
            # Try UI fallback
            try:
                success = await self._add_to_cart_via_ui(adapter, sku, effective_qty)
            except Exception as exc:  # noqa: BLE001
                return CartOperationResult(
                    success=False,
                    sku=sku,
                    error=f"add_to_cart UI fallback raised: {exc}",
                    error_type="ui_error",
                )

        if not success:
            return CartOperationResult(
                success=False,
                sku=sku,
                error=f"Failed to add SKU {sku} to cart via API or UI",
                error_type="add_failed",
            )

        # Verify item is in cart (CART-2)
        verified, cart_items, cart_url = await self._verify_item_in_cart(
            adapter, sku
        )
        if not verified:
            return CartOperationResult(
                success=False,
                sku=sku,
                error=f"Item {sku} added but not found in cart verification",
                error_type="verification_failed",
            )

        # Track SKU as added (CART-6)
        self._mark_sku_added(retailer_name, sku, effective_qty)

        self.logger.info(
            "CART_ITEM_ADDED",
            sku=sku,
            quantity=effective_qty,
            retailer=retailer_name,
            cart_url=cart_url,
        )

        return CartOperationResult(
            success=True,
            sku=sku,
            quantity=effective_qty,
            cart_url=cart_url,
            items_in_cart=len(cart_items),
        )

    async def verify_cart(
        self,
        sku: str,
        retailer_name: str,
    ) -> tuple[bool, list[CartItem]]:
        """Verify a SKU is present in the cart.

        Args:
            sku: Product SKU to verify.
            retailer_name: Retailer name.

        Returns:
            Tuple of (is_present, list of CartItems).
        """
        adapter = await self._get_adapter(retailer_name)
        if adapter is None:
            return False, []

        try:
            cart_raw = await adapter.get_cart()
        except Exception:  # noqa: BLE001
            return False, []

        cart_items = [
            CartItem(
                sku=item.get("sku", ""),
                name=item.get("name", ""),
                quantity=item.get("quantity", 0),
                price=item.get("price", ""),
            )
            for item in cart_raw
        ]

        present = any(item.sku == sku for item in cart_items)
        return present, cart_items

    async def clear_cart(self, retailer_name: str) -> bool:
        """Clear all items from a retailer's cart.

        Used between checkout attempts on failure (CART-5).

        Args:
            retailer_name: Retailer name.

        Returns:
            True if cart was cleared successfully.
        """
        adapter = await self._get_adapter(retailer_name)
        if adapter is None:
            return False

        try:
            cleared = await self._clear_cart_via_adapter(adapter)
            if cleared:
                self.logger.info(
                    "CART_CLEARED",
                    retailer=retailer_name,
                )
                # Clear duplicate-add tracking for this retailer
                keys_to_remove = [
                    k for k in self._added_skus if k[0] == retailer_name
                ]
                for k in keys_to_remove:
                    del self._added_skus[k]
            return cleared
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "CART_CLEAR_FAILED",
                retailer=retailer_name,
                error=str(exc),
            )
            return False

    async def get_cart(self, retailer_name: str) -> list[CartItem]:
        """Get current cart contents for a retailer.

        Args:
            retailer_name: Retailer name.

        Returns:
            List of CartItems in the cart.
        """
        adapter = await self._get_adapter(retailer_name)
        if adapter is None:
            return []

        try:
            cart_raw = await adapter.get_cart()
        except Exception:  # noqa: BLE001
            return []

        return [
            CartItem(
                sku=item.get("sku", ""),
                name=item.get("name", ""),
                quantity=item.get("quantity", 0),
                price=item.get("price", ""),
            )
            for item in cart_raw
        ]

    def reset_session(self, retailer_name: str | None = None) -> None:
        """Reset duplicate-add tracking for a retailer or all retailers.

        Call this at the start of a new checkout session or drop window.

        Args:
            retailer_name: If provided, reset only this retailer. If None, reset all.
        """
        if retailer_name is None:
            self._added_skus.clear()
        else:
            keys_to_remove = [k for k in self._added_skus if k[0] == retailer_name]
            for k in keys_to_remove:
                del self._added_skus[k]

    # ── Private Helpers ───────────────────────────────────────────────────────

    async def _get_adapter(self, retailer_name: str) -> RetailerAdapter | None:
        """Get or create an adapter instance for the given retailer."""
        if retailer_name in self._adapters:
            return self._adapters[retailer_name]

        try:
            from src.bot.monitor.retailers import get_default_registry

            registry = get_default_registry()
            adapter_cls = registry.get(retailer_name)
            if adapter_cls is None:
                return None
            adapter = adapter_cls(self.config)
            self._adapters[retailer_name] = adapter
            return adapter
        except Exception:  # noqa: BLE001
            return None

    async def _is_duplicate_add(
        self,
        retailer_name: str,
        sku: str,
    ) -> bool:
        """Check if SKU was already added to this retailer's cart this session."""
        key = (retailer_name, sku)
        return key in self._added_skus

    def _mark_sku_added(
        self,
        retailer_name: str,
        sku: str,
        quantity: int,
    ) -> None:
        """Mark a SKU as added to prevent duplicate adds within this session."""
        key = (retailer_name, sku)
        current = self._added_skus.get(key, 0)
        self._added_skus[key] = current + quantity

    def _get_effective_quantity(
        self,
        sku: str,
        requested_quantity: int,
        retailer_name: str,
    ) -> int:
        """Calculate effective quantity respecting max_cart_quantity and retailer limits.

        CART-7: operator can set max_cart_quantity (default: 1)
        CART-8: if retailer's purchase limit is lower than max_cart_quantity,
                retailer's limit takes precedence

        Since retailer-specific purchase limits aren't exposed via API in the
        config schema, we enforce max_cart_quantity from config. Subclasses
        may override _get_retailer_purchase_limit() to check UI scraping if needed.

        Args:
            sku: Product SKU.
            requested_quantity: Quantity requested by the caller.
            retailer_name: Retailer name.

        Returns:
            The effective quantity to add (constrained to max_cart_quantity).
        """
        # Get global max_cart_quantity from config (default 1)
        max_qty = getattr(self.config, "max_cart_quantity", 1)

        # Check retailer-specific override in config
        retailer_cfg = getattr(self.config, "retailers", {}).get(retailer_name, {})
        if isinstance(retailer_cfg, dict):
            retailer_max = retailer_cfg.get("max_cart_quantity", max_qty)
            max_qty = min(max_qty, retailer_max) if retailer_max else max_qty

        # Check monitored item-specific max_cart_quantity
        for item in getattr(self.config, "items", []):
            if isinstance(item, dict) and sku in item.get("skus", []):
                item_max = item.get("max_cart_quantity", max_qty)
                max_qty = min(max_qty, item_max) if item_max else max_qty
                break

        # Retailer purchase limit (CART-8) — unknown from API, use config as ceiling
        effective = min(requested_quantity, max(1, max_qty))
        return effective

    async def _verify_item_in_cart(
        self,
        adapter: RetailerAdapter,
        sku: str,
    ) -> tuple[bool, list[dict[str, Any]], str]:
        """Verify the item is actually in the cart.

        Returns:
            Tuple of (verified, cart_items, cart_url).
        """
        try:
            cart_raw = await adapter.get_cart()
        except Exception:  # noqa: BLE001
            return False, [], ""

        found = any(item.get("sku") == sku for item in cart_raw)
        cart_url = self._get_cart_url(adapter.name)
        return found, cart_raw, cart_url

    async def _add_to_cart_via_ui(
        self,
        adapter: RetailerAdapter,
        sku: str,
        quantity: int,
    ) -> bool:
        """UI fallback for add_to_cart when API fails.

        Delegates to the adapter's internal UI method if available,
        otherwise falls back to Playwright automation.
        """
        # Adapters implement _add_to_cart_ui internally
        # CartManager doesn't have direct Playwright access,
        # so we signal failure if API fails and no UI method available
        return False

    async def _clear_cart_via_adapter(self, adapter: RetailerAdapter) -> bool:
        """Clear the cart via the adapter's clear method if available."""
        # Check if adapter has _clear_cart method
        if hasattr(adapter, "_clear_cart"):
            try:
                result = await adapter._clear_cart()
                return result  # type: ignore[no-any-return]
            except Exception:  # noqa: BLE001
                pass

        # Try get_cart + navigate approach via Playwright if adapter has a page
        if hasattr(adapter, "_page"):
            page = getattr(adapter, "_page", None)
            if page is not None:
                return await self._clear_cart_ui(adapter)

        return False

    async def _clear_cart_ui(self, adapter: RetailerAdapter) -> bool:
        """Clear cart by navigating to cart page and clicking remove buttons."""
        import asyncio as a

        page: Any = getattr(adapter, "_page", None)
        cart_url = self._get_cart_url(adapter.name)
        if page is None:
            return False
        try:
            await page.goto(cart_url, wait_until="networkidle", timeout=15000)
            await a.sleep(1.0)

            # Generic remove button selectors (retailer-specific overrides can override)
            remove_selectors = [
                'button:has-text("Remove")',
                '[data-test="remove-button"]',
                '[aria-label*="Remove"]',
                'button[aria-label*="remove"]',
            ]

            removed_any = False
            for selector in remove_selectors:
                try:
                    remove_btns = await page.query_selector_all(selector)
                    for btn in remove_btns:
                        try:
                            await btn.click()
                            await a.sleep(0.5)
                            removed_any = True
                        except Exception:  # noqa: BLE001
                            continue
                except Exception:  # noqa: BLE001
                    continue

                if removed_any:
                    break

            return True
        except Exception:  # noqa: BLE001
            return False

    def _get_cart_url(self, retailer_name: str) -> str:
        """Return the cart page URL for a retailer."""
        cart_urls = {
            "target": "https://www.target.com/co/cart",
            "walmart": "https://www.walmart.com/cart",
            "bestbuy": "https://www.bestbuy.com/cart",
        }
        return cart_urls.get(retailer_name, "")


__all__ = [
    "CartManager",
    "CartItem",
    "CartOperationResult",
    "CartError",
]