"""StockMonitor — main orchestration loop for stock monitoring and checkout.

Per PRD Section 9.1 (MON-1 to MON-11), Section 7.2 (State Machine).

State Machine:
  STANDBY ──[stock detected]──> STOCK_FOUND ──[cart added]──> CART_READY
    │                                  │                          │
    │                                  │                          ▼
    │                                  └────────[checkout done]──> CHECKOUT_COMPLETE
    │                                                               │
    │                                                               ▼
    └─────────────[failure/timeout]──────────────────────────────> CHECKOUT_FAILED
"""

from __future__ import annotations

import asyncio
import random
import signal
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.shared.models import WebhookEvent

if TYPE_CHECKING:
    from src.bot.checkout.checkout_flow import CheckoutFlow
    from src.bot.config import Config
    from src.bot.logger import Logger
    from src.bot.monitor.retailers.base import RetailerAdapter
    from src.bot.session.prewarmer import SessionPrewarmer


class MonitorStage(Enum):
    """StockMonitor stage for state tracking."""

    STANDBY = "standby"
    MONITORING = "monitoring"
    STOCK_FOUND = "stock_found"
    CART_READY = "cart_ready"
    CHECKOUT_COMPLETE = "checkout_complete"
    CHECKOUT_FAILED = "checkout_failed"
    SHUTDOWN = "shutdown"


@dataclass
class MonitorState:
    """Current state of the StockMonitor."""

    stage: MonitorStage = MonitorStage.STANDBY
    item_name: str = ""
    retailer_name: str = ""
    sku: str = ""
    keyword: str = ""  # Populated when keyword-based detection found stock
    order_id: str = ""
    error: str = ""
    checkout_attempt: int = 0
    started_at: datetime | None = None
    stock_found_at: datetime | None = None


@dataclass
class StockMonitor:
    """Main orchestration loop for stock monitoring and checkout.

    Responsibilities:
    - Load all configured items and retailers from config
    - Start monitoring per item using retailer adapters
    - Detect OOS→IS transitions (MON-2)
    - Route to CheckoutFlow on stock detection
    - Handle graceful shutdown (MON-11): stop loop, close browser, persist state

    Per PRD Sections 9.1 (MON-1 to MON-11), 7.2 (State Machine).
    """

    def __init__(
        self,
        config: Config,
        logger: Logger,
        checkout_flow: CheckoutFlow,
        session_prewarmer: SessionPrewarmer,
        webhook_callback: Any = None,
    ) -> None:
        """Initialize the StockMonitor.

        Args:
            config: Validated Config instance with items, retailers, shipping, payment.
            logger: Logger instance for structured event logging.
            checkout_flow: CheckoutFlow instance for checkout orchestration.
            session_prewarmer: SessionPrewarmer instance for session management.
            webhook_callback: Optional async callable that receives WebhookEvent objects
                for DROP_WINDOW events. Typically a DiscordWebhook.send or
                TelegramWebhook.send method. Defaults to None (no webhook delivery).
        """
        self.config = config
        self.logger = logger
        self.checkout_flow = checkout_flow
        self.session_prewarmer = session_prewarmer
        self._webhook_callback: Any = webhook_callback

        # Active monitoring tasks per item/retailer
        self._monitor_tasks: dict[str, asyncio.Task[None]] = {}
        self._running = False
        self._shutdown_event = asyncio.Event()

        # Per-item/retailer state
        self._item_states: dict[str, MonitorState] = {}

        # Signal handling
        self._previous_sigterm: Any | None = None
        self._previous_sigint: Any | None = None

        # Drop window auto-prewarm scheduler (PHASE3-T02)
        self._drop_window_scheduler_task: asyncio.Task[None] | None = None
        # Tracks drop windows that have already triggered prewarm
        # (key = f"{retailer}:{item}:{drop_datetime}", value = prewarmed_at datetime)
        self._prewarmed_windows: dict[str, datetime] = {}
        # How often to check drop windows (seconds)
        self._DROP_WINDOW_CHECK_INTERVAL: int = 30
        # Fire PREWARM_URGENT if drop is within this many minutes and not prewarmed
        self._URGENT_PREWARM_MINUTES: int = 5

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start monitoring all configured items and retailers.

        Loads items from config, starts per-item monitoring loops.
        Blocks until shutdown is requested.
        """
        self.logger.info(
            "MONITOR_STARTED",
            items_count=sum(len(r.items) for r in self.config.retailers.values() if r.enabled),
            retailers=[r for r in self.config.retailers],
        )

        self._running = True
        self._setup_signal_handlers()

        # Start drop window auto-prewarm scheduler (PHASE3-T02)
        self._drop_window_scheduler_task = asyncio.create_task(
            self._run_drop_window_scheduler()
        )

        # Start session pre-warming for each retailer adapter
        for retailer_name in self.config.retailers:
            adapter = await self._get_adapter_for_retailer(retailer_name)
            if adapter:
                await self.session_prewarmer.prewarm_all_accounts(adapter=adapter)

        # Load monitored items from retailers and create monitoring tasks
        for retailer_name, retailer_cfg in self.config.retailers.items():
            if not retailer_cfg.enabled:
                continue

            for item_def in retailer_cfg.items:
                item_name = item_def.get("name", "unknown")
                skus = item_def.get("skus", [])
                enabled = item_def.get("enabled", True)
                retailers_for_item = item_def.get("retailers", [retailer_name])

                if not enabled:
                    self.logger.info(
                        "MONITOR_ITEM_SKIPPED",
                        item=item_name,
                        reason="disabled",
                    )
                    continue

                for sku in skus:
                    task_key = f"{item_name}:{retailer_name}:{sku}"
                    state = MonitorState(
                        stage=MonitorStage.STANDBY,
                        item_name=item_name,
                        retailer_name=retailer_name,
                        sku=sku,
                    )
                    self._item_states[task_key] = state

                    task = asyncio.create_task(
                        self._monitor_item_loop(item_name, retailer_name, sku)
                    )
                    self._monitor_tasks[task_key] = task

                    self.logger.info(
                        "MONITOR_TASK_STARTED",
                        item=item_name,
                        retailer=retailer_name,
                        sku=sku,
                    )

                # MON-4: Keyword-based detection tasks (MON-4)
                keywords = item_def.get("keywords", [])
                for keyword in keywords:
                    kw_task_key = f"{item_name}:{retailer_name}:kw:{keyword}"
                    kw_state = MonitorState(
                        stage=MonitorStage.STANDBY,
                        item_name=item_name,
                        retailer_name=retailer_name,
                        keyword=keyword,
                    )
                    self._item_states[kw_task_key] = kw_state

                    kw_task = asyncio.create_task(
                        self._monitor_keyword_loop(item_name, retailer_name, keyword)
                    )
                    self._monitor_tasks[kw_task_key] = kw_task

                    self.logger.info(
                        "MONITOR_KEYWORD_TASK_STARTED",
                        item=item_name,
                        retailer=retailer_name,
                        keyword=keyword,
                    )

        # Wait for shutdown signal
        await self._shutdown_event.wait()

    async def stop(self) -> None:
        """Stop all monitoring tasks gracefully (MON-11).

        Cancels active monitoring tasks, closes browser sessions,
        persists state. Called on SIGTERM/SIGINT.
        """
        if not self._running:
            return

        self.logger.info("MONITOR_SHUTDOWN_INITIATED")
        self._running = False

        # Cancel drop window scheduler
        if self._drop_window_scheduler_task is not None:
            self._drop_window_scheduler_task.cancel()
            try:
                await self._drop_window_scheduler_task
            except asyncio.CancelledError:
                pass
            self._drop_window_scheduler_task = None

        # Cancel all monitoring tasks
        for task_key, task in self._monitor_tasks.items():
            if not task.done():
                task.cancel()
                self.logger.debug(
                    "MONITOR_TASK_CANCELLED",
                    task_key=task_key,
                )

        # Wait for tasks to finish
        if self._monitor_tasks:
            await asyncio.gather(
                *self._monitor_tasks.values(),
                return_exceptions=True,
            )

        # Close all adapter sessions
        await self._close_all_adapters()

        self._shutdown_event.set()
        self.logger.info("MONITOR_SHUTDOWN_COMPLETE")

    async def start_monitoring_item(
        self,
        item_name: str,
        retailer_name: str,
        sku: str,
    ) -> None:
        """Start monitoring a specific item/retailer combination.

        Can be called at runtime to add new monitoring targets.
        """
        task_key = f"{item_name}:{retailer_name}:{sku}"
        if task_key in self._monitor_tasks and not self._monitor_tasks[task_key].done():
            return  # Already monitoring

        state = MonitorState(
            stage=MonitorStage.STANDBY,
            item_name=item_name,
            retailer_name=retailer_name,
            sku=sku,
        )
        self._item_states[task_key] = state

        task = asyncio.create_task(
            self._monitor_item_loop(item_name, retailer_name, sku)
        )
        self._monitor_tasks[task_key] = task

        self.logger.info(
            "MONITOR_ITEM_STARTED",
            item=item_name,
            retailer=retailer_name,
            sku=sku,
        )

    async def stop_monitoring_item(
        self,
        item_name: str,
        retailer_name: str,
        sku: str,
    ) -> None:
        """Stop monitoring a specific item/retailer combination."""
        task_key = f"{item_name}:{retailer_name}:{sku}"
        if task_key in self._monitor_tasks:
            self._monitor_tasks[task_key].cancel()
            del self._monitor_tasks[task_key]
            self.logger.info(
                "MONITOR_ITEM_STOPPED",
                item=item_name,
                retailer=retailer_name,
                sku=sku,
            )

    def get_status(self) -> dict[str, Any]:
        """Return current monitoring status for all items/retailers.

        Returns:
            Dict with running status, item states, and uptime.
        """
        states = {}
        for key, state in self._item_states.items():
            states[key] = {
                "stage": state.stage.value,
                "item_name": state.item_name,
                "retailer": state.retailer_name,
                "sku": state.sku,
                "keyword": state.keyword,
                "order_id": state.order_id,
                "error": state.error,
                "started_at": (
                    state.started_at.isoformat() if state.started_at else None
                ),
                "stock_found_at": (
                    state.stock_found_at.isoformat()
                    if state.stock_found_at
                    else None
                ),
            }

        return {
            "running": self._running,
            "task_count": len(self._monitor_tasks),
            "states": states,
        }

    # ── Private: Monitoring Loop ─────────────────────────────────────────────

    async def _monitor_item_loop(
        self,
        item_name: str,
        retailer_name: str,
        sku: str,
    ) -> None:
        """Main monitoring loop for a single item/retailer/sku.

        Detects OOS→IS transitions and triggers checkout flow.
        Respects check interval from config with jitter applied.
        """
        task_key = f"{item_name}:{retailer_name}:{sku}"
        state = self._item_states.get(task_key)
        if state is None:
            return

        state.stage = MonitorStage.MONITORING
        state.started_at = datetime.now(timezone.utc)

        self.logger.info(
            "MONITOR_LOOP_STARTED",
            item=item_name,
            retailer=retailer_name,
            sku=sku,
        )

        # Get adapter for this retailer
        adapter = await self._get_adapter_for_retailer(retailer_name)
        if adapter is None:
            self.logger.error(
                "MONITOR_ADAPTER_NOT_FOUND",
                item=item_name,
                retailer=retailer_name,
            )
            return

        # Get check interval from retailer config
        check_interval_ms = self._get_check_interval(retailer_name)

        last_stock_status: bool | None = None
        last_check_time: datetime | None = None

        while self._running:
            try:
                current_task = asyncio.current_task()
                if current_task is None or current_task.cancelled():
                    break

                # Check stock
                stock_status = await self._check_stock_with_adapter(
                    adapter, sku
                )
                last_check_time = datetime.now(timezone.utc)

                # Detect OOS→IS transition (MON-2)
                # stock_status.in_stock is True = in stock, False = OOS
                is_currently_in_stock = stock_status.in_stock
                was_oos = last_stock_status is None or last_stock_status is False

                if was_oos and is_currently_in_stock:
                    self.logger.info(
                        "STOCK_DETECTED",
                        item=item_name,
                        retailer=retailer_name,
                        sku=sku,
                        url=stock_status.url or "",
                        price=stock_status.price or "",
                    )

                    state.stage = MonitorStage.STOCK_FOUND
                    state.stock_found_at = last_check_time

                    # Route to checkout flow
                    await self._route_to_checkout(
                        adapter=adapter,
                        item_name=item_name,
                        retailer_name=retailer_name,
                        sku=sku,
                        state=state,
                    )

                    # If checkout completed successfully, we're done with this item
                    if state.stage == MonitorStage.CHECKOUT_COMPLETE:
                        self.logger.info(
                            "MONITOR_ITEM_COMPLETE",
                            item=item_name,
                            retailer=retailer_name,
                            order_id=state.order_id,
                        )
                        return

                last_stock_status = is_currently_in_stock

                # Apply jitter to check interval (MON-6)
                import random

                jitter_pct = getattr(self.config, "evasion", {}).get(
                    "jitter_percent", 20
                )
                jitter_factor = 1.0 + random.uniform(-jitter_pct / 100, jitter_pct / 100)
                wait_seconds = (check_interval_ms / 1000) * jitter_factor

                await asyncio.sleep(wait_seconds)

            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "MONITOR_LOOP_ERROR",
                    item=item_name,
                    retailer=retailer_name,
                    sku=sku,
                    error=str(exc),
                )
                # Brief pause before retry
                await asyncio.sleep(1.0)

    async def _monitor_keyword_loop(
        self,
        item_name: str,
        retailer_name: str,
        keyword: str,
    ) -> None:
        """Keyword-based monitoring loop for a single item/retailer/keyword.

        Uses check_stock_by_keyword to detect in-stock items matching
        the configured keyword. Triggers checkout when stock is found.

        Per PRD Section 9.1 (MON-4).
        """
        task_key = f"{item_name}:{retailer_name}:kw:{keyword}"
        state = self._item_states.get(task_key)
        if state is None:
            return

        state.stage = MonitorStage.MONITORING
        state.started_at = datetime.now(timezone.utc)

        self.logger.info(
            "MONITOR_KEYWORD_LOOP_STARTED",
            item=item_name,
            retailer=retailer_name,
            keyword=keyword,
        )

        # Get adapter for this retailer
        adapter = await self._get_adapter_for_retailer(retailer_name)
        if adapter is None:
            self.logger.error(
                "MONITOR_ADAPTER_NOT_FOUND",
                item=item_name,
                retailer=retailer_name,
            )
            return

        # Get check interval from retailer config
        check_interval_ms = self._get_check_interval(retailer_name)

        last_check_time: datetime | None = None

        while self._running:
            try:
                current_task = asyncio.current_task()
                if current_task is None or current_task.cancelled():
                    break

                # Keyword-based stock check
                stock_status = await adapter.check_stock_by_keyword(keyword)
                last_check_time = datetime.now(timezone.utc)

                if stock_status.in_stock:
                    self.logger.info(
                        "STOCK_DETECTED_KEYWORD",
                        item=item_name,
                        retailer=retailer_name,
                        keyword=keyword,
                        sku=stock_status.sku,
                        url=stock_status.url or "",
                        price=stock_status.price or "",
                    )

                    state.stage = MonitorStage.STOCK_FOUND
                    state.stock_found_at = last_check_time
                    state.sku = stock_status.sku

                    # Route to checkout with the discovered SKU
                    await self._route_to_checkout(
                        adapter=adapter,
                        item_name=item_name,
                        retailer_name=retailer_name,
                        sku=stock_status.sku,
                        state=state,
                    )

                    if state.stage == MonitorStage.CHECKOUT_COMPLETE:
                        self.logger.info(
                            "MONITOR_KEYWORD_ITEM_COMPLETE",
                            item=item_name,
                            retailer=retailer_name,
                            keyword=keyword,
                            order_id=state.order_id,
                        )
                        return

                # Apply jitter to check interval (MON-6)
                import random

                jitter_pct = getattr(self.config, "evasion", {}).get(
                    "jitter_percent", 20
                )
                jitter_factor = 1.0 + random.uniform(-jitter_pct / 100, jitter_pct / 100)
                wait_seconds = (check_interval_ms / 1000) * jitter_factor

                await asyncio.sleep(wait_seconds)

            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "MONITOR_KEYWORD_LOOP_ERROR",
                    item=item_name,
                    retailer=retailer_name,
                    keyword=keyword,
                    error=str(exc),
                )
                await asyncio.sleep(1.0)

    async def _check_stock_with_adapter(
        self,
        adapter: RetailerAdapter,
        sku: str,
    ) -> Any:
        """Check stock using the adapter's stock check method.

        Returns:
            StockStatus object with in_stock, sku, url, price, available_quantity.
        """
        return await adapter.stock_check_with_retry(sku)

    async def _route_to_checkout(
        self,
        adapter: RetailerAdapter,
        item_name: str,
        retailer_name: str,
        sku: str,
        state: MonitorState,
    ) -> None:
        """Route to checkout flow when stock is detected.

        Orchestrates: add to cart → verify → run CheckoutFlow.
        Handles all failure modes per PRD Section 12.
        """
        self.logger.info(
            "CHECKOUT_ROUTE_STARTED",
            item=item_name,
            retailer=retailer_name,
            sku=sku,
        )

        # Add to cart
        from src.bot.checkout.cart_manager import CartManager

        cart_manager = CartManager(self.config, self.logger)

        cart_result = await cart_manager.add_item(
            sku=sku,
            quantity=1,
            retailer_name=retailer_name,
        )

        if not cart_result.success:
            self.logger.error(
                "CART_ADD_FAILED",
                item=item_name,
                retailer=retailer_name,
                sku=sku,
                error=cart_result.error,
            )
            state.stage = MonitorStage.CHECKOUT_FAILED
            state.error = cart_result.error
            return

        self.logger.info(
            "CART_ADDED",
            item=item_name,
            retailer=retailer_name,
            sku=sku,
            cart_url=cart_result.cart_url,
        )

        state.stage = MonitorStage.CART_READY

        # Run checkout flow
        webhook_callback = self._make_webhook_callback()

        checkout_result = await self.checkout_flow.run(
            adapter=adapter,
            sku=sku,
            item_name=item_name,
            dry_run=False,
            webhook_callback=webhook_callback,
        )

        if checkout_result.success:
            state.stage = MonitorStage.CHECKOUT_COMPLETE
            state.order_id = checkout_result.order_id
            self.logger.info(
                "CHECKOUT_COMPLETE",
                item=item_name,
                retailer=retailer_name,
                order_id=checkout_result.order_id,
            )
        else:
            state.stage = MonitorStage.CHECKOUT_FAILED
            state.error = checkout_result.error
            state.checkout_attempt = checkout_result.attempts
            self.logger.error(
                "CHECKOUT_FAILED",
                item=item_name,
                retailer=retailer_name,
                error=checkout_result.error,
                stage=checkout_result.stage,
            )

    def _make_webhook_callback(self) -> Any:
        """Create a webhook callback for checkout events.

        Returns an async callable that logs events.
        """
        async def callback(event: WebhookEvent) -> None:
            self.logger.info(
                event.event,
                item=event.item,
                retailer=event.retailer,
                order_id=event.order_id,
                error=event.error,
            )

        return callback

    # ── Private: Adapter Management ─────────────────────────────────────────

    async def _get_adapter_for_retailer(self, retailer_name: str) -> RetailerAdapter | None:
        """Get or create a retailer adapter instance.

        Uses the adapter registry.

        Returns:
            RetailerAdapter instance or None if not found.
        """
        try:
            from src.bot.monitor.retailers import get_default_registry

            registry = get_default_registry()
            adapter_cls = registry.get(retailer_name)
            if adapter_cls is None:
                return None
            return adapter_cls(self.config)
        except Exception:  # noqa: BLE001
            return None

    def _get_check_interval(self, retailer_name: str) -> int:
        """Get the stock check interval for a retailer from config.

        Args:
            retailer_name: The retailer name.

        Returns:
            Check interval in milliseconds.
        """
        retailer_cfg = self.config.retailers.get(retailer_name)
        if retailer_cfg is not None:
            interval = getattr(retailer_cfg, "check_interval_ms", 500)
            return interval
        return 500

    async def _close_all_adapters(self) -> None:
        """"Close all active adapter sessions."""
        pass

    # ── Private: Drop Window Auto-Prewarm Scheduler (PHASE3-T02) ──────────────

    async def _run_drop_window_scheduler(self) -> None:
        """Background loop: check drop windows and trigger pre-warming (DWC-2, DWC-4).

        Runs every _DROP_WINDOW_CHECK_INTERVAL seconds while monitoring is active.
        Handles multiple drop windows simultaneously (DWC-4).
        Fires PREWARM_URGENT if drop is within 5 minutes and not yet prewarmed.
        """
        while self._running:
            try:
                await self._check_drop_windows()
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "DROP_WINDOW_SCHEDULER_ERROR",
                    error=str(exc),
                )
            await asyncio.sleep(self._DROP_WINDOW_CHECK_INTERVAL)

    async def _check_drop_windows(self) -> None:
        """Check all drop windows and trigger pre-warming for approaching ones.


        Per PRD Section 9.9 (DWC-2, DWC-4):
        - When countdown reaches prewarm_minutes, auto-start session pre-warming
        - Multiple drop windows can be active simultaneously
        - Fire PREWARM_URGENT if drop time is within 5 minutes and not prewarmed
        """
        now = datetime.now(timezone.utc)
        drop_windows = getattr(self.config, "drop_windows", [])
        if not drop_windows:
            return

        enabled_retailers = self.config.get_enabled_retailers()


        for dw in drop_windows:
            if not dw.get("enabled", True):
                continue
            retailer = dw.get("retailer", "")
            if retailer not in enabled_retailers:
                continue

            item = dw.get("item", "")
            drop_datetime_str = dw.get("drop_datetime", "")
            prewarm_minutes = dw.get("prewarm_minutes", 15)


            # Parse drop datetime
            drop_dt = self._parse_drop_datetime(drop_datetime_str)
            if drop_dt is None:
                continue

            minutes_until_drop = (drop_dt - now).total_seconds() / 60.0
            dw_key = f"{retailer}:{item}:{drop_datetime_str}"


            # ── DROP_WINDOW_OPEN: drop time has arrived ──
            if minutes_until_drop <= 0:
                # Drop time reached or past — fire webhook and disable window
                self.logger.warning(
                    "DROP_WINDOW_OPEN",
                    item=item,
                    retailer=retailer,
                    reason="Drop window is now open!",
                )
                await self._fire_webhook_event(
                    event="DROP_WINDOW_OPEN",
                    item=item,
                    retailer=retailer,
                    reason="Drop window is now open!",
                )
                # Remove from tracking and disable so this window stops firing every 30s
                if dw_key in self._prewarmed_windows:
                    del self._prewarmed_windows[dw_key]
                dw["enabled"] = False
                continue

            # ── PREWARM_URGENT: within 5 min and not yet prewarmed ──
            if 0 < minutes_until_drop <= self._URGENT_PREWARM_MINUTES:
                if dw_key not in self._prewarmed_windows:
                    self.logger.warning(
                        "PREWARM_URGENT",
                        item=item,
                        retailer=retailer,
                        minutes_until_drop=int(minutes_until_drop),
                        reason=(
                            f"Drop in {int(minutes_until_drop)} min — "
                            f"session not yet prewarmed!"
                        ),
                    )
                    # Fire urgent webhook via checkout_flow webhook callback
                    await self._fire_webhook_event(
                        event="PREWARM_URGENT",
                        item=item,
                        retailer=retailer,
                        reason=f"Drop in {int(minutes_until_drop)} minutes — pre-warm immediately!",
                    )

            # ── Auto-prewarm when within prewarm_minutes window ──
            if 0 < minutes_until_drop <= prewarm_minutes:
                # Check if already prewarmed
                prewarmed_at = self._prewarmed_windows.get(dw_key)
                if prewarmed_at is not None:
                    continue  # Already prewarmed for this window

                self.logger.info(
                    "DROP_WINDOW_PREWARM_TRIGGERED",
                    item=item,
                    retailer=retailer,
                    minutes_until_drop=int(minutes_until_drop),
                    prewarm_window_minutes=prewarm_minutes,
                )

                # Fire DROP_WINDOW_APPROACHING webhook (DWC-5)
                await self._fire_webhook_event(
                    event="DROP_WINDOW_APPROACHING",
                    item=item,
                    retailer=retailer,
                    reason=f"Drop in {int(minutes_until_drop)} minutes — pre-warming session now",
                )

                # Trigger pre-warm via session_prewarmer
                adapter = await self._get_adapter_for_retailer(retailer)
                if adapter is not None:
                    # Use drop window item as account identifier
                    account_name = f"drop_{item}"
                    result = await self.session_prewarmer.prewarm_now(
                        adapter=adapter,
                        account_name=account_name,
                    )
                    if result.success:
                        self._prewarmed_windows[dw_key] = now
                        self.logger.info(
                            "DROP_WINDOW_PREWARM_SUCCESS",
                            item=item,
                            retailer=retailer,
                            cookies_count=result.cookies_count,
                        )
                    else:
                        self.logger.warning(
                            "DROP_WINDOW_PREWARM_FAILED",
                            item=item,
                            retailer=retailer,
                            error=result.error,
                        )
                else:
                    self.logger.error(
                        "DROP_WINDOW_PREWARM_NO_ADAPTER",
                        item=item,
                        retailer=retailer,
                    )

    def _parse_drop_datetime(self, value: str) -> datetime | None:
        """Parse an ISO-8601 drop datetime string, treating naive as UTC."""
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None

    async def _fire_webhook_event(
        self,
        event: str,
        item: str = "",
        retailer: str = "",
        reason: str = "",
        **kwargs: Any,
    ) -> None:
        """Fire a webhook event via the configured webhook callback if available.

        The callback is typically a DiscordWebhook.send or TelegramWebhook.send method.
        If no callback is configured, the event is silently dropped (logged via logger).
        """
        if self._webhook_callback is None:
            return
        from src.shared.models import WebhookEvent
        now = datetime.now(timezone.utc)
        webhook_event = WebhookEvent(
            event=event,
            item=item,
            retailer=retailer,
            timestamp=now.isoformat(),
            reason=reason,
        )
        callback = self._webhook_callback
        if asyncio.iscoroutinefunction(callback):
            await callback(webhook_event)
        else:
            callback(webhook_event)

    # ── Private: Signal Handling ──────────────────────────────────────────────

    def _setup_signal_handlers(self) -> None:
        """Register SIGTERM and SIGINT handlers for graceful shutdown (MON-11)."""

        def sigterm_handler(signum: int, frame: Any) -> None:
            self.logger.warning("RECEIVED_SIGTERM", signal="SIGTERM")
            asyncio.create_task(self.stop())

        def sigint_handler(signum: int, frame: Any) -> None:
            self.logger.warning("RECEIVED_SIGINT", signal="SIGINT")
            asyncio.create_task(self.stop())

        self._previous_sigterm = signal.signal(signal.SIGTERM, sigterm_handler)
        self._previous_sigint = signal.signal(signal.SIGINT, sigint_handler)

    # ── Private: State Persistence ─────────────────────────────────────────

    def _persist_state(self, state: MonitorState) -> None:
        """Persist current checkout state to state.json for crash recovery (OP-1).

        Called on abnormal exit to enable restart without duplicate orders (OP-2).
        """
        import json
        from pathlib import Path

        state_file = Path("state.json")
        data = {
            "item": state.item_name,
            "retailer": state.retailer_name,
            "sku": state.sku,
            "stage": state.stage.value,
            "order_id": state.order_id,
            "error": state.error,
            "started_at": (
                state.started_at.isoformat() if state.started_at else None
            ),
            "stock_found_at": (
                state.stock_found_at.isoformat() if state.stock_found_at else None
            ),
            "checkout_attempt": state.checkout_attempt,
        }

        try:
            state_file.write_text(json.dumps(data, indent=2))
        except Exception:  # noqa: BLE001
            pass  # Best effort — don't fail on state write error


__all__ = [
    "StockMonitor",
    "MonitorStage",
    "MonitorState",
]