"""QueueHandler — detect and handle retailer queue/waiting rooms.

Detects queue/waiting room redirects before or during checkout.
Auto-waits until queue clears, fires QUEUE_DETECTED and QUEUE_CLEARED
webhook events, and times out after 60 seconds.

Per PRD Sections 9.1 (MON-9), 12 (Queue/waiting room edge case).
"""

from __future__ import annotations

import asyncio

from typing import TYPE_CHECKING, Callable, Awaitable

if TYPE_CHECKING:
    from src.bot.logger import Logger
    from src.bot.monitor.retailers.base import RetailerAdapter


# Default timeout for queue wait (seconds)
_DEFAULT_QUEUE_TIMEOUT_SECONDS = 60.0

# Polling interval while waiting in queue (seconds)
_QUEUE_POLL_INTERVAL_SECONDS = 2.0


class QueueHandler:
    """Handles retailer queue/waiting room detection and auto-wait.

    Detects queue/waiting room redirects using the adapter's `check_queue()`
    method. Fires QUEUE_DETECTED webhook when entering a queue. Polls until
    queue clears, then fires QUEUE_CLEARED. Times out after `timeout_seconds`.

    Usage:
        handler = QueueHandler(config, logger, webhook_callback)
        in_queue = await handler.check_queue(adapter)
        if in_queue:
            cleared = await handler.wait_for_queue_cleared(adapter)
    """

    def __init__(
        self,
        logger: Logger,
        webhook_callback: Callable[[str, dict[str, object]], Awaitable[None]] | None = None,
        timeout_seconds: float = _DEFAULT_QUEUE_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize the QueueHandler.

        Args:
            logger: Logger instance for structured event logging.
            webhook_callback: Optional async callback(f"QUEUE_DETECTED", dict) or
                (f"QUEUE_CLEARED", dict) for notifications.
            timeout_seconds: Maximum seconds to wait in queue before giving up.
        """
        self.logger = logger
        self._webhook_callback = webhook_callback
        self._timeout_seconds = timeout_seconds

        # Track whether we've already fired QUEUE_DETECTED for current queue entry
        self._queue_detected_fired: bool = False

    async def check_queue(self, adapter: "RetailerAdapter") -> bool:
        """Check if the adapter's current page shows a queue/waiting room.

        Args:
            adapter: RetailerAdapter with an active browser page.

        Returns:
            True if queue/waiting room detected, False otherwise.
        """
        try:
            return await adapter.check_queue()
        except Exception:  # noqa: BLE001
            return False

    async def wait_for_queue_cleared(
        self,
        adapter: "RetailerAdapter",
        item_name: str = "",
        retailer_name: str = "",
    ) -> bool:
        """Wait for the queue to clear, polling check_queue().

        Fires QUEUE_DETECTED on entry, QUEUE_CLEARED on exit.
        Times out after `timeout_seconds` and returns False.

        Args:
            adapter: RetailerAdapter with an active browser page.
            item_name: Item name for webhook context.
            retailer_name: Retailer name for webhook context.

        Returns:
            True if queue cleared within timeout, False if still in queue
            or timed out.
        """
        # Fire QUEUE_DETECTED webhook on entry
        if not self._queue_detected_fired:
            self._queue_detected_fired = True
            self.logger.warning(
                "QUEUE_DETECTED",
                item=item_name,
                retailer=retailer_name,
            )
            if self._webhook_callback is not None:
                await self._webhook_callback(
                    "QUEUE_DETECTED",
                    {
                        "item": item_name,
                        "retailer": retailer_name,
                        "url": self._get_current_url(adapter),
                    },
                )

        # Poll until cleared or timeout
        start_time = asyncio.get_event_loop().time()
        timeout_seconds = self._timeout_seconds

        while True:
            # Check if still in queue
            in_queue = await self.check_queue(adapter)
            if not in_queue:
                # Queue cleared
                self.logger.info(
                    "QUEUE_CLEARED",
                    item=item_name,
                    retailer=retailer_name,
                )
                if self._webhook_callback is not None:
                    await self._webhook_callback(
                        "QUEUE_CLEARED",
                        {
                            "item": item_name,
                            "retailer": retailer_name,
                        },
                    )
                # Reset detection flag for next queue entry
                self._queue_detected_fired = False
                return True

            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout_seconds:
                self.logger.error(
                    "QUEUE_TIMEOUT",
                    item=item_name,
                    retailer=retailer_name,
                    elapsed_seconds=round(elapsed, 1),
                    timeout_seconds=timeout_seconds,
                )
                # Reset detection flag for next queue entry
                self._queue_detected_fired = False
                return False

            # Wait before next poll
            await asyncio.sleep(_QUEUE_POLL_INTERVAL_SECONDS)

    async def check_and_wait(
        self,
        adapter: "RetailerAdapter",
        item_name: str = "",
        retailer_name: str = "",
    ) -> bool:
        """Convenience: check queue, fire webhook, wait for clear if needed.

        Returns True if no queue or queue cleared within timeout.
        Returns False only on timeout.

        Args:
            adapter: RetailerAdapter with an active browser page.
            item_name: Item name for webhook context.
            retailer_name: Retailer name for webhook context.

        Returns:
            True if not in queue or queue cleared, False on timeout.
        """
        in_queue = await self.check_queue(adapter)
        if not in_queue:
            return True
        return await self.wait_for_queue_cleared(adapter, item_name, retailer_name)

    def _get_current_url(self, adapter: "RetailerAdapter") -> str:
        """Get the current page URL from an adapter if possible."""
        page = getattr(adapter, "_page", None)
        if page is not None:
            try:
                url: str = page.url
                return url
            except Exception:  # noqa: BLE001
                pass
        return ""


__all__ = ["QueueHandler"]