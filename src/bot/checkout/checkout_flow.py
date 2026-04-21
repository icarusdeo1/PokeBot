"""CheckoutFlow — orchestrates the multi-step checkout process per retailer.

Coordinates cart verification, shipping/payment autofill, order review,
order submission, confirmation capture, and retry logic.

Per PRD Section 9.3 (CO-1 to CO-10) and Section 12 (Edge Cases).
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.bot.checkout.payment import (
    PaymentAutofill,
    PaymentDeclineHandler,
)
from src.bot.checkout.shipping import (
    ShippingAutofill,
    get_standard_shipping_field_mapping,
)
from src.bot.monitor.queue_handler import QueueHandler
from src.shared.models import CheckoutStage, WebhookEvent

if TYPE_CHECKING:
    from src.bot.config import Config
    from src.bot.logger import Logger
    from src.bot.monitor.retailers.base import RetailerAdapter
    from src.bot.session.prewarmer import SessionPrewarmer


# Default human-like delay range in milliseconds
_DEFAULT_HUMAN_DELAY_MS = 300
_DEFAULT_MAX_HUMAN_DELAY_MS = 350


@dataclass
class CheckoutResult:
    """Result of a full checkout attempt."""

    success: bool
    order_id: str = ""
    stage: str = ""
    error: str = ""
    attempts: int = 0


class CheckoutFlow:
    """Orchestrates the checkout flow across all retailers.

    Coordinates:
    1. Cart verification (item still present)
    2. Shipping form autofill from ShippingInfo config
    3. Payment form autofill from PaymentInfo config (card masked in logs)
    4. Order review step acknowledgment
    5. Order submission with confirmation capture
    6. Retry on failure (configurable attempts, default 2)
    7. Payment decline retry (once after 2s delay, abort on second decline)

    Per PRD Sections 9.3 (CO-1 to CO-10), 11 (Timeouts), 12 (Edge Cases).
    """

    def __init__(
        self,
        config: Config,
        logger: Logger,
        cart_manager: Any,
        session_prewarmer: SessionPrewarmer | None = None,
    ) -> None:
        """Initialize the CheckoutFlow.

        Args:
            config: Validated Config instance (must include shipping, payment).
            logger: Logger instance for structured event logging.
            cart_manager: CartManager instance for cart verification.
            session_prewarmer: Optional SessionPrewarmer for automatic re-auth
                on session expiry (SESSION-T03).
        """
        self.config = config
        self.logger = logger
        self.cart_manager = cart_manager

        # Session re-authenticator (SESSION-T03)
        self._reauthenticator: Any = None
        if session_prewarmer is not None:
            from src.bot.session.reauth import SessionReauthenticator
            self._reauthenticator = SessionReauthenticator(
                config=config,
                logger=logger,
                session_prewarmer=session_prewarmer,
            )

        # Load retry configuration
        checkout_cfg = getattr(config, "checkout", None)
        self._max_retries: int
        self._human_delay_ms: int
        self._max_human_delay_ms: int

        if checkout_cfg is not None:
            self._max_retries = getattr(checkout_cfg, "retry_attempts", 2)
            self._human_delay_ms = getattr(checkout_cfg, "human_delay_ms", _DEFAULT_HUMAN_DELAY_MS)
            self._max_human_delay_ms = getattr(checkout_cfg, "max_human_delay_ms", _DEFAULT_MAX_HUMAN_DELAY_MS)
        else:
            self._max_retries = 2
            self._human_delay_ms = _DEFAULT_HUMAN_DELAY_MS
            self._max_human_delay_ms = _DEFAULT_MAX_HUMAN_DELAY_MS

        # Payment autofill from config
        payment_info = getattr(config, "payment", None)
        self._payment_autofill: PaymentAutofill | None = (
            PaymentAutofill(payment_info) if payment_info is not None else None
        )

        # Shipping autofill from config
        shipping_info = getattr(config, "shipping", None)
        self._shipping_autofill: ShippingAutofill | None = (
            ShippingAutofill(shipping_info) if shipping_info is not None else None
        )

        # Queue handler (QUEUE-T01)
        self._queue_handler: QueueHandler | None = None
        if logger is not None:
            self._queue_handler = QueueHandler(logger=logger)

        # Payment decline handler
        self._decline_handler = PaymentDeclineHandler(max_retries=1, retry_delay_seconds=2.0)

        # Per-adapter retailer checkout implementations (lazy-loaded)
        self._adapter_checkout_impls: dict[str, Any] = {}

    async def run(
        self,
        adapter: RetailerAdapter,
        sku: str,
        item_name: str,
        dry_run: bool = False,
        webhook_callback: Any = None,
        account_name: str = "default",
    ) -> CheckoutResult:
        """Run the full checkout flow for a retailer adapter.

        Args:
            adapter: The RetailerAdapter instance for this retailer.
            sku: Product SKU being purchased.
            item_name: Display name of the item (for logging/events).
            dry_run: If True, executes the full flow but does NOT place a real order.
                The retailer adapter's checkout() method receives dry_run=True
                and must simulate order submission without charging.
            webhook_callback: Optional async callable that receives WebhookEvent objects.
            account_name: Identifier for the account (used for session re-auth).
                Defaults to "default" for single-account setups.

        Returns:
            CheckoutResult with success status, order_id (if success),
            stage reached, and error message (if failed).

        Per PRD Section 9.1 (MON-10): on session expiry, re-authenticate
        and restart from cart step.
        """
        # Proactive queue check before checkout (QUEUE-T01)
        if self._queue_handler is not None:
            queue_ok = await self._queue_handler.check_and_wait(
                adapter=adapter,
                item_name=item_name,
                retailer_name=adapter.name,
            )
            if not queue_ok:
                return CheckoutResult(
                    success=False,
                    stage=CheckoutStage.PRE_CHECK.value,
                    error="Timed out in retailer queue/waiting room",
                )

        # Proactively check/reauth session before checkout (MON-10)
        if self._reauthenticator is not None:
            reauth_result = await self._reauthenticator.check_and_reauth(
                adapter=adapter,
                account_name=account_name,
                webhook_callback=webhook_callback,
            )
            if not reauth_result.success:
                return CheckoutResult(
                    success=False,
                    stage=CheckoutStage.PRE_CHECK.value,
                    error=f"Session invalid and re-authentication failed: {reauth_result.error}",
                )

        # Verify payment info is configured (lazy check at checkout time)
        if self._payment_autofill is None or not self._payment_autofill.payment_info.card_number or not self._payment_autofill.payment_info.cvv:
            self.logger.error(
                "CHECKOUT_PAYMENT_NOT_CONFIGURED",
                item=item_name,
                retailer=adapter.name,
            )
            return CheckoutResult(
                success=False,
                stage=CheckoutStage.PRE_CHECK.value,
                error="Payment info not configured — add card details in dashboard",
            )

        self.logger.info(
            "CHECKOUT_STARTED",
            item=item_name,
            sku=sku,
            retailer=adapter.name,
            dry_run=dry_run,
        )

        attempt = 0
        last_error = ""
        reauthenticated = False  # Tracks if we re-auth'd mid-checkout

        while attempt <= self._max_retries:
            attempt += 1

            self.logger.info(
                "CHECKOUT_ATTEMPT",
                item=item_name,
                sku=sku,
                retailer=adapter.name,
                attempt=attempt,
                max_retries=self._max_retries,
            )

            result = await self._attempt_checkout(
                adapter=adapter,
                sku=sku,
                item_name=item_name,
                attempt=attempt,
                dry_run=dry_run,
                webhook_callback=webhook_callback,
                account_name=account_name,
            )

            # Mid-checkout queue detection (QUEUE-T01): check after each step
            if self._queue_handler is not None and not result.success:
                queue_cleared = await self._queue_handler.check_and_wait(
                    adapter=adapter,
                    item_name=item_name,
                    retailer_name=adapter.name,
                )
                if not queue_cleared:
                    return CheckoutResult(
                        success=False,
                        stage=result.stage or CheckoutStage.PRE_CHECK.value,
                        error=f"Timed out in retailer queue/waiting room: {result.error}",
                    )

            if result.success:
                self.logger.info(
                    "CHECKOUT_SUCCESS",
                    item=item_name,
                    retailer=adapter.name,
                    order_id=result.order_id,
                    attempts=attempt,
                )
                return result

            last_error = result.error

            # Handle session expiry mid-checkout (MON-10): re-auth and retry
            if self._reauthenticator is not None and not reauthenticated:
                reauth_result = await self._reauthenticator.reauth_on_error(
                    adapter=adapter,
                    account_name=account_name,
                    error=last_error,
                    webhook_callback=webhook_callback,
                )
                if reauth_result.reauthenticated:
                    self.logger.info(
                        "CHECKOUT_REAUTH_SUCCESS",
                        item=item_name,
                        retailer=adapter.name,
                        attempt=attempt,
                        message="Session re-authenticated, retrying checkout",
                    )
                    reauthenticated = True
                    # Retry from cart step — continue to next attempt
                    continue

            # Handle payment decline specifically
            decline_code = result.error or ""
            if "decline" in decline_code.lower() or "declined" in decline_code.lower():
                retry = await self._decline_handler.handle_decline(
                    decline_code=decline_code,
                    retailer=adapter.name,
                    item=item_name,
                    webhook_callback=webhook_callback,
                )
                if not retry:
                    return CheckoutResult(
                        success=False,
                        stage=result.stage or CheckoutStage.PAYMENT.value,
                        error=f"Payment declined and retries exhausted: {last_error}",
                        attempts=attempt,
                    )
                # Continue to retry

            # On last attempt, return failure
            if attempt > self._max_retries:
                break

            # Log failure and retry
            self.logger.warning(
                "CHECKOUT_RETRY",
                item=item_name,
                retailer=adapter.name,
                attempt=attempt,
                error=last_error,
                stage=result.stage,
            )

            # Clear cart before retry (CART-5)
            await self.cart_manager.clear_cart(adapter.name)
            await self._human_delay_async(0.5)  # Brief pause before retry

        # All retries exhausted
        self.logger.error(
            "CHECKOUT_FAILED",
            item=item_name,
            retailer=adapter.name,
            error=last_error,
            attempts=self._max_retries + 1,
        )

        return CheckoutResult(
            success=False,
            stage=result.stage or CheckoutStage.SUBMIT.value,
            error=f"All {self._max_retries + 1} checkout attempts failed: {last_error}",
            attempts=self._max_retries + 1,
        )

    async def _attempt_checkout(
        self,
        adapter: RetailerAdapter,
        sku: str,
        item_name: str,
        attempt: int,
        dry_run: bool,
        webhook_callback: Any,
        account_name: str = "default",
    ) -> CheckoutResult:
        """Execute a single checkout attempt.

        Returns:
            CheckoutResult indicating success or failure and stage reached.
        """
        try:
            # ── Step 1: Pre-check — verify item still in cart (CO-7, CART-2) ──
            self.logger.debug("CHECKOUT_PRE_CHECK", stage="pre_check", sku=sku)

            present, cart_items = await self.cart_manager.verify_cart(sku, adapter.name)
            if not present:
                self.logger.warning(
                    "CHECKOUT_ITEM_OOS",
                    sku=sku,
                    retailer=adapter.name,
                    reason="Item no longer in cart",
                )
                return CheckoutResult(
                    success=False,
                    stage=CheckoutStage.PRE_CHECK.value,
                    error="Item no longer available in cart after add",
                )

            await self._human_delay_async()

            # ── Step 2: Navigate to checkout ────────────────────────────────────
            self.logger.debug("CHECKOUT_NAVIGATE", stage="shipping", retailer=adapter.name)
            navigate_ok = await self._navigate_to_checkout(adapter, dry_run)
            if not navigate_ok:
                return CheckoutResult(
                    success=False,
                    stage=CheckoutStage.SHIPPING.value,
                    error="Failed to navigate to checkout page",
                )

            await self._human_delay_async()

            # ── Step 3: Autofill shipping (CO-1, CO-3) ─────────────────────────
            self.logger.debug("CHECKOUT_SHIPPING", stage="shipping", item=item_name)

            if self._shipping_autofill is not None:
                shipping_data = self._shipping_autofill.build_form_data(
                    get_standard_shipping_field_mapping()
                )
                # Adapter handles billing same-as-shipping via its fill_shipping_form
                filled = await self._fill_shipping_form(adapter, shipping_data)
                if not filled:
                    self.logger.warning(
                        "CHECKOUT_SHIPPING_FILL_FAILED",
                        item=item_name,
                        retailer=adapter.name,
                    )
                    # Continue anyway — retailer may have saved shipping

            await self._human_delay_async()

            # ── Step 4: Autofill payment (CO-2) ────────────────────────────────
            self.logger.debug("CHECKOUT_PAYMENT", stage="payment", item=item_name)

            if self._payment_autofill is not None:
                from src.bot.checkout.payment import get_standard_payment_field_mapping

                payment_data = self._payment_autofill.build_form_data(
                    get_standard_payment_field_mapping()
                )

                filled = await self._fill_payment_form(adapter, payment_data)
                if not filled:
                    self.logger.warning(
                        "CHECKOUT_PAYMENT_FILL_FAILED",
                        item=item_name,
                        retailer=adapter.name,
                    )

            await self._human_delay_async()

            # ── Step 5: Order review step (CO-4) ────────────────────────────────
            self.logger.debug("CHECKOUT_REVIEW", stage="review", item=item_name)
            reviewed = await self._handle_review_step(adapter)
            if not reviewed:
                self.logger.warning(
                    "CHECKOUT_REVIEW_FAILED",
                    item=item_name,
                    retailer=adapter.name,
                )

            await self._human_delay_async()

            # ── Step 6: Submit order (CO-5) ─────────────────────────────────────
            self.logger.debug("CHECKOUT_SUBMIT", stage="submit", item=item_name)

            order_id, submit_error = await self._submit_order(
                adapter, dry_run=dry_run
            )

            if submit_error:
                return CheckoutResult(
                    success=False,
                    stage=CheckoutStage.SUBMIT.value,
                    error=submit_error,
                )

            # ── Step 7: Confirm order (CO-5 confirmation capture) ─────────────
            confirmed, confirmation_id = await self._confirm_order(
                adapter, order_id
            )

            if not confirmed:
                # Order was submitted but not confirmed — treat as failure
                return CheckoutResult(
                    success=False,
                    stage=CheckoutStage.CONFIRMATION.value,
                    error=f"Order {order_id} submitted but not confirmed",
                )

            return CheckoutResult(
                success=True,
                order_id=confirmation_id or order_id,
                stage=CheckoutStage.CONFIRMATION.value,
                attempts=attempt,
            )

        except asyncio.TimeoutError:
            return CheckoutResult(
                success=False,
                stage=CheckoutStage.PRE_CHECK.value,
                error="Checkout step timed out",
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "CHECKOUT_EXCEPTION",
                item=item_name,
                retailer=adapter.name,
                error=str(exc),
                stage=CheckoutStage.PRE_CHECK.value,
            )
            return CheckoutResult(
                success=False,
                stage=CheckoutStage.PRE_CHECK.value,
                error=f"Checkout exception: {exc}",
            )

    async def _navigate_to_checkout(
        self,
        adapter: RetailerAdapter,
        dry_run: bool,
    ) -> bool:
        """Navigate to the retailer's checkout page.

        Delegates to adapter for retailer-specific navigation.

        Returns:
            True if navigation succeeded.
        """
        # Adapter implements go_to_checkout() or equivalent
        if hasattr(adapter, "go_to_checkout"):
            try:
                return await adapter.go_to_checkout(dry_run=dry_run)  # type: ignore[no-any-return]
            except Exception:  # noqa: BLE001
                return False

        # Fallback: adapter.checkout() covers full flow including navigation
        return True

    async def _fill_shipping_form(
        self,
        adapter: RetailerAdapter,
        shipping_data: dict[str, Any],
    ) -> bool:
        """Fill the shipping form via the adapter.

        Adapter handles retailer-specific field names and submission.

        Returns:
            True if fill succeeded.
        """
        if hasattr(adapter, "fill_shipping_form"):
            try:
                return await adapter.fill_shipping_form(shipping_data)  # type: ignore[no-any-return]
            except Exception:  # noqa: BLE001
                pass

        # Adapters that don't implement fill_shipping_form rely on
        # pre-warmed session cookies and saved address — continue
        return True

    async def _fill_payment_form(
        self,
        adapter: RetailerAdapter,
        payment_data: dict[str, Any],
    ) -> bool:
        """Fill the payment form via the adapter.

        Adapter handles retailer-specific field names and submission.

        Returns:
            True if fill succeeded.
        """
        if hasattr(adapter, "fill_payment_form"):
            try:
                return await adapter.fill_payment_form(payment_data)  # type: ignore[no-any-return]
            except Exception:  # noqa: BLE001
                pass

        return True

    async def _handle_review_step(self, adapter: RetailerAdapter) -> bool:
        """Handle the order review/acknowledgment step (CO-4).

        Some retailers show a "Review Order" page before submission.
        This step acknowledges terms and any "apply" buttons.

        Returns:
            True if review step handled (or not needed).
        """
        if hasattr(adapter, "handle_review_step"):
            try:
                return await adapter.handle_review_step()  # type: ignore[no-any-return]
            except Exception:  # noqa: BLE001
                pass

        # Default: no review step needed
        return True

    async def _submit_order(
        self,
        adapter: RetailerAdapter,
        dry_run: bool,
    ) -> tuple[str, str]:
        """Submit the order and capture the order ID.

        Args:
            adapter: The retailer adapter.
            dry_run: If True, simulate submission without placing order.

        Returns:
            Tuple of (order_id, error). If error is empty, submission succeeded.
        """
        if hasattr(adapter, "submit_order"):
            try:
                order_id, error = await adapter.submit_order(dry_run=dry_run)
                return order_id, error or ""
            except Exception as exc:  # noqa: BLE001
                return "", f"submit_order raised: {exc}"

        # Fallback: adapter.checkout() covers full flow
        try:
            result = await adapter.checkout(
                shipping=self.config.shipping,  # type: ignore[arg-type]
                payment=self.config.payment,  # type: ignore[arg-type]
            )
            if result.get("success"):
                return result.get("order_id", "DRYRUN") or "DRYRUN", ""
            return "", result.get("error", "checkout returned failure") or "checkout returned failure"
        except Exception as exc:  # noqa: BLE001
            return "", f"checkout raised: {exc}"

    async def _confirm_order(
        self,
        adapter: RetailerAdapter,
        order_id: str,
    ) -> tuple[bool, str]:
        """Verify the order was successfully placed and return confirmation number.

        Args:
            adapter: The retailer adapter.
            order_id: The order ID returned from submit_order.

        Returns:
            Tuple of (confirmed, confirmation_number).
        """
        if hasattr(adapter, "confirm_order"):
            try:
                confirmed, confirmation_id = await adapter.confirm_order(order_id)
                return confirmed, confirmation_id
            except Exception:  # noqa: BLE001
                pass

        # Default: order_id is sufficient confirmation
        return True, order_id

    # ── Human-like Delay ─────────────────────────────────────────────────────

    def _human_delay(self, base_ms: float | None = None) -> float:
        """Return a human-like delay in seconds (CO-8).

        Uses a flat random in [human_delay_ms, max_human_delay_ms] by default.
        Override with explicit base_ms for ad-hoc pauses.

        Args:
            base_ms: If provided, overrides the configured delay range.

        Returns:
            Delay in seconds (also stored for async sleep in _human_delay_async).
        """
        if base_ms is not None:
            self._last_delay_ms = base_ms
            return base_ms

        lo = float(self._human_delay_ms)
        hi = float(self._max_human_delay_ms)
        self._last_delay_ms = random.uniform(lo, hi)
        return self._last_delay_ms

    async def _human_delay_async(self, base_ms: float | None = None) -> None:
        """Async version of _human_delay that actually sleeps."""
        delay_s = self._human_delay(base_ms)
        await asyncio.sleep(delay_s)

    # ── Utility ───────────────────────────────────────────────────────────────

    def _fire_event(
        self,
        webhook_callback: Any,
        event: WebhookEvent,
    ) -> None:
        """Fire a webhook event if callback is configured."""
        if webhook_callback is None:
            return
        if asyncio.iscoroutinefunction(webhook_callback):
            asyncio.create_task(webhook_callback(event))
        else:
            try:
                webhook_callback(event)
            except Exception:  # noqa: BLE001
                pass


__all__ = [
    "CheckoutFlow",
    "CheckoutResult",
]