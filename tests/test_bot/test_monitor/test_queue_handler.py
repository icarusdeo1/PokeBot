"""Tests for QueueHandler — queue detection and auto-wait.

Per PRD Sections 9.1 (MON-9), 12 (Queue/waiting room edge case).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.monitor.queue_handler import QueueHandler


class FakeLoop:
    """Fake event loop for time-tracking tests without real async."""

    def __init__(self) -> None:
        self._time = 0.0

    def time(self) -> float:
        return self._time

    def advance(self, seconds: float) -> None:
        self._time += seconds


class TestQueueHandler:
    """Tests for QueueHandler class."""

    @pytest.fixture
    def mock_logger(self) -> MagicMock:
        logger = MagicMock()
        logger.info = MagicMock()
        logger.warning = MagicMock()
        logger.error = MagicMock()
        return logger

    @pytest.fixture
    def mock_webhook(self) -> AsyncMock:
        return AsyncMock()

    # ── check_queue ──────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_check_queue_returns_true_when_queue_detected(self, mock_logger: MagicMock) -> None:
        """check_queue() returns True when adapter.check_queue() is True."""
        adapter = MagicMock()
        adapter.check_queue = AsyncMock(return_value=True)

        handler = QueueHandler(logger=mock_logger)
        result = await handler.check_queue(adapter)

        assert result is True
        adapter.check_queue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_queue_returns_false_when_no_queue(self, mock_logger: MagicMock) -> None:
        """check_queue() returns False when adapter.check_queue() is False."""
        adapter = MagicMock()
        adapter.check_queue = AsyncMock(return_value=False)

        handler = QueueHandler(logger=mock_logger)
        result = await handler.check_queue(adapter)

        assert result is False

    @pytest.mark.asyncio
    async def test_check_queue_returns_false_on_adapter_exception(self, mock_logger: MagicMock) -> None:
        """check_queue() returns False when adapter.check_queue() raises."""
        adapter = MagicMock()
        adapter.check_queue = AsyncMock(side_effect=RuntimeError("browser closed"))

        handler = QueueHandler(logger=mock_logger)
        result = await handler.check_queue(adapter)

        assert result is False

    # ── wait_for_queue_cleared — happy path ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_wait_for_queue_cleared_returns_true_when_cleared(self, mock_logger: MagicMock) -> None:
        """wait_for_queue_cleared() returns True when queue clears."""
        adapter = MagicMock()
        adapter.check_queue = AsyncMock(return_value=False)  # Not in queue

        handler = QueueHandler(logger=mock_logger)

        # Patch _get_current_url to avoid attribute errors
        handler._get_current_url = MagicMock(return_value="https://target.com/checkout")

        result = await handler.wait_for_queue_cleared(
            adapter=adapter,
            item_name="Pokemon Switch",
            retailer_name="target",
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_queue_cleared_fires_webhook_on_entry(self, mock_logger: MagicMock, mock_webhook: AsyncMock) -> None:
        """QUEUE_DETECTED webhook fired when entering queue."""
        adapter = MagicMock()
        # First call: in queue, Second call: cleared
        adapter.check_queue = AsyncMock(side_effect=[True, False])

        handler = QueueHandler(logger=mock_logger, webhook_callback=mock_webhook)

        result = await handler.wait_for_queue_cleared(
            adapter=adapter,
            item_name="Pokemon Switch",
            retailer_name="target",
        )

        assert result is True
        # Should have called webhook with QUEUE_DETECTED then QUEUE_CLEARED
        assert mock_webhook.call_count == 2
        first_call_args = mock_webhook.call_args_list[0]
        assert first_call_args[0][0] == "QUEUE_DETECTED"
        assert first_call_args[0][1]["item"] == "Pokemon Switch"
        assert first_call_args[0][1]["retailer"] == "target"
        second_call_args = mock_webhook.call_args_list[1]
        assert second_call_args[0][0] == "QUEUE_CLEARED"

    @pytest.mark.asyncio
    async def test_wait_for_queue_cleared_fires_queue_cleared_webhook(self, mock_logger: MagicMock, mock_webhook: AsyncMock) -> None:
        """QUEUE_CLEARED webhook fired when queue clears."""
        adapter = MagicMock()
        adapter.check_queue = AsyncMock(return_value=False)

        handler = QueueHandler(logger=mock_logger, webhook_callback=mock_webhook)
        handler._get_current_url = MagicMock(return_value="https://target.com/checkout")

        result = await handler.wait_for_queue_cleared(
            adapter=adapter,
            item_name="Pokemon Switch",
            retailer_name="target",
        )

        assert result is True
        # Last webhook call should be QUEUE_CLEARED
        last_call_args = mock_webhook.call_args_list[-1]
        assert last_call_args[0][0] == "QUEUE_CLEARED"

    # ── wait_for_queue_cleared — timeout ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_wait_for_queue_cleared_times_out(self, mock_logger: MagicMock, mock_webhook: AsyncMock) -> None:
        """wait_for_queue_cleared() returns False after timeout_seconds."""
        adapter = MagicMock()
        adapter.check_queue = AsyncMock(return_value=True)  # Always in queue

        # Short timeout for test
        handler = QueueHandler(
            logger=mock_logger,
            webhook_callback=mock_webhook,
            timeout_seconds=5.0,
        )
        handler._get_current_url = MagicMock(return_value="https://queue.target.com")

        result = await handler.wait_for_queue_cleared(
            adapter=adapter,
            item_name="Pokemon Switch",
            retailer_name="target",
        )

        assert result is False
        mock_logger.error.assert_called()
        # Verify timeout log contains elapsed info
        error_calls = [c for c in mock_logger.error.call_args_list]
        assert any("QUEUE_TIMEOUT" in str(c) for c in error_calls)

    # ── wait_for_queue_cleared — resets flag on clear ───────────────────────

    @pytest.mark.asyncio
    async def test_queue_detected_flag_resets_after_cleared(self, mock_logger: MagicMock) -> None:
        """_queue_detected_fired resets after queue clears, allowing re-detection."""
        adapter = MagicMock()
        adapter.check_queue = AsyncMock(return_value=False)

        handler = QueueHandler(logger=mock_logger)
        assert handler._queue_detected_fired is False

        # Simulate: call wait_for_queue_cleared with no queue → should return True
        result = await handler.wait_for_queue_cleared(adapter)
        assert result is True
        assert handler._queue_detected_fired is False

    # ── check_and_wait ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_check_and_wait_returns_true_when_no_queue(self, mock_logger: MagicMock) -> None:
        """check_and_wait() returns True immediately when not in queue."""
        adapter = MagicMock()
        adapter.check_queue = AsyncMock(return_value=False)

        handler = QueueHandler(logger=mock_logger)
        result = await handler.check_and_wait(adapter, item_name="Test Item", retailer_name="target")

        assert result is True
        assert adapter.check_queue.call_count == 1

    @pytest.mark.asyncio
    async def test_check_and_wait_waits_when_queue_detected(self, mock_logger: MagicMock, mock_webhook: AsyncMock) -> None:
        """check_and_wait() enters wait loop when queue detected."""
        adapter = MagicMock()
        # First check: in queue, then clears
        adapter.check_queue = AsyncMock(side_effect=[True, False])

        handler = QueueHandler(logger=mock_logger, webhook_callback=mock_webhook)
        handler._get_current_url = MagicMock(return_value="https://target.com/checkout")

        result = await handler.check_and_wait(adapter, item_name="Test Item", retailer_name="target")

        assert result is True
        assert adapter.check_queue.call_count == 2

    # ── _get_current_url ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_current_url_returns_page_url(self, mock_logger: MagicMock) -> None:
        """_get_current_url() extracts URL from adapter._page."""
        adapter = MagicMock()
        page = MagicMock()
        page.url = "https://www.target.com/checkout"
        adapter._page = page

        handler = QueueHandler(logger=mock_logger)
        url = handler._get_current_url(adapter)

        assert url == "https://www.target.com/checkout"

    @pytest.mark.asyncio
    async def test_get_current_url_returns_empty_when_no_page(self, mock_logger: MagicMock) -> None:
        """_get_current_url() returns empty string if no _page."""
        adapter = MagicMock()
        adapter._page = None

        handler = QueueHandler(logger=mock_logger)
        url = handler._get_current_url(adapter)

        assert url == ""

    # ── timeout configuration ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_custom_timeout_respected(self, mock_logger: MagicMock, mock_webhook: AsyncMock) -> None:
        """Custom timeout_seconds is used for queue wait."""
        adapter = MagicMock()
        adapter.check_queue = AsyncMock(return_value=True)  # Always in queue

        handler = QueueHandler(logger=mock_logger, timeout_seconds=3.0)
        handler._get_current_url = MagicMock(return_value="https://queue.target.com")

        # This should time out after 3 seconds, not the default 60
        result = await handler.wait_for_queue_cleared(adapter, item_name="Test", retailer_name="target")

        assert result is False
        # Should not have waited the full 60s — should timeout around 3s
        # We can verify by checking call count is small
        assert adapter.check_queue.call_count < 20  # Much less than 60s / 2s poll

    # ── log events ──────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_queues_detected_logged(self, mock_logger: MagicMock) -> None:
        """QUEUE_DETECTED is logged as warning."""
        adapter = MagicMock()
        adapter.check_queue = AsyncMock(side_effect=[True, False])

        handler = QueueHandler(logger=mock_logger)
        handler._get_current_url = MagicMock(return_value="https://queue.target.com")

        await handler.wait_for_queue_cleared(adapter, item_name="Pokemon", retailer_name="target")

        warning_calls = [c for c in mock_logger.warning.call_args_list]
        assert any("QUEUE_DETECTED" in str(c) for c in warning_calls)

    @pytest.mark.asyncio
    async def test_queues_cleared_logged(self, mock_logger: MagicMock) -> None:
        """QUEUE_CLEARED is logged as info."""
        adapter = MagicMock()
        adapter.check_queue = AsyncMock(return_value=False)

        handler = QueueHandler(logger=mock_logger)
        handler._get_current_url = MagicMock(return_value="https://target.com/checkout")

        await handler.wait_for_queue_cleared(adapter, item_name="Pokemon", retailer_name="target")

        info_calls = [c for c in mock_logger.info.call_args_list]
        assert any("QUEUE_CLEARED" in str(c) for c in info_calls)