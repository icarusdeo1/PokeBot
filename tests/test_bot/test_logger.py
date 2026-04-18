"""Tests for bot/logger.py (SHARED-T05: Structured logging + SSE stream)."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

import pytest


class TestSensitiveFieldMasking:
    """Test that sensitive fields are masked correctly per log level."""

    def test_mask_value_card_number_debug_shows_last_4(self) -> None:
        """At DEBUG level, card_number should be masked to ****XXXX (last 4)."""
        from src.bot.logger import _mask_value
        result = _mask_value("card_number", "4111111111111111", logging.DEBUG)
        assert result == "****1111"

    def test_mask_value_cvv_debug_shows_obfuscated(self) -> None:
        """At DEBUG level, CVV should be masked to ***."""
        from src.bot.logger import _mask_value
        result = _mask_value("cvv", "123", logging.DEBUG)
        assert result == "***"

    def test_mask_value_card_number_info_redacts_fully(self) -> None:
        """At INFO level, card_number should be fully redacted."""
        from src.bot.logger import _mask_value
        result = _mask_value("card_number", "4111111111111111", logging.INFO)
        assert result == "***"

    def test_mask_value_non_sensitive_passed_through(self) -> None:
        """Non-sensitive fields should pass through unchanged at DEBUG."""
        from src.bot.logger import _mask_value
        result = _mask_value("item", "Pikachu Plush", logging.DEBUG)
        assert result == "Pikachu Plush"

    def test_mask_value_password_always_redacted(self) -> None:
        """Password should be redacted at any level."""
        from src.bot.logger import _mask_value
        assert _mask_value("password", "secret123", logging.DEBUG) == "***"
        assert _mask_value("password", "secret123", logging.ERROR) == "***"

    def test_mask_value_token_always_redacted(self) -> None:
        """Token fields should be redacted at any level."""
        from src.bot.logger import _mask_value
        assert _mask_value("auth_token", "tok_abc123", logging.DEBUG) == "***"
        assert _mask_value("api_key", "key_xyz", logging.ERROR) == "***"

    def test_mask_record_nested_dict(self) -> None:
        """Nested dicts should have their sensitive fields masked."""
        from src.bot.logger import _mask_record
        data = {
            "event": "CHECKOUT_STARTED",
            "card_number": "4111111111111111",
            "nested": {"cvv": "999", "item": "Pikachu Plush"},
        }
        result = _mask_record(data, logging.DEBUG)
        assert result["event"] == "CHECKOUT_STARTED"
        assert result["card_number"] == "****1111"
        assert result["nested"]["cvv"] == "***"
        assert result["nested"]["item"] == "Pikachu Plush"

    def test_mask_record_list_of_dicts(self) -> None:
        """Lists containing dicts should have each dict masked."""
        from src.bot.logger import _mask_record
        data = {
            "event": "CART_ADDED",
            "items": [
                {"sku": "12345", "card_number": "4111111111111111"},
                {"sku": "67890", "card_number": "5555555555554444"},
            ],
        }
        result = _mask_record(data, logging.DEBUG)
        assert result["items"][0]["card_number"] == "****1111"
        assert result["items"][1]["card_number"] == "****4444"


class TestJsonFormatter:
    """Test the JSON log formatter output."""

    def test_formatter_produces_valid_json(self) -> None:
        """Formatted output should be valid JSON."""
        from src.bot.logger import JsonFormatter
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg={"event": "STOCK_DETECTED", "item": "Pikachu Plush"},
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["event"] == "STOCK_DETECTED"
        assert parsed["item"] == "Pikachu Plush"
        assert "timestamp" in parsed
        assert parsed["level"] == "INFO"

    def test_formatter_adds_timestamp_and_level(self) -> None:
        """Each formatted record should include timestamp and level."""
        from src.bot.logger import JsonFormatter
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg={"event": "CHECKOUT_FAILED", "error": "declined"},
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "ERROR"
        assert parsed["event"] == "CHECKOUT_FAILED"

    def test_formatter_masks_at_debug_level(self) -> None:
        """DEBUG records should have partial masking applied."""
        from src.bot.logger import JsonFormatter
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg={"event": "CART_DEBUG", "card_number": "4111111111111111"},
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["card_number"] == "****1111"


class TestLoggerInit:
    """Test Logger singleton initialization."""

    def setup_method(self) -> None:
        """Reset the singleton before each test."""
        from src.bot import logger as logger_module
        from src.bot.logger import Logger
        logger_module._logger_instance = None
        Logger._instance = None
        Logger._queue = []

    def test_init_logger_returns_logger_instance(self) -> None:
        """init_logger should return a Logger instance."""
        from src.bot.logger import init_logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            assert log is not None

    def test_init_logger_twice_same_instance(self) -> None:
        """Calling init_logger twice should return the same singleton."""
        from src.bot.logger import init_logger
        with tempfile.TemporaryDirectory() as tmpdir:
            l1 = init_logger(log_dir=tmpdir)
            l2 = init_logger(log_dir=tmpdir)
            assert l1 is l2

    def test_get_instance_raises_if_not_initialized(self) -> None:
        """get_instance() should raise RuntimeError if not initialized."""
        from src.bot.logger import Logger
        with pytest.raises(RuntimeError, match="not initialized"):
            Logger.get_instance()


class TestLoggerFileOutput:
    """Test that log messages are written correctly to the log file."""

    def setup_method(self) -> None:
        from src.bot import logger as logger_module
        from src.bot.logger import Logger
        logger_module._logger_instance = None
        Logger._instance = None
        Logger._queue = []

    def test_info_writes_json_line_to_file(self) -> None:
        """info() should write a JSON line to the log file."""
        from src.bot.logger import init_logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.info("MONITOR_STARTED", item="Pikachu Plush", retailer="target")

            log_path = Path(tmpdir) / "poke_drop.log"
            assert log_path.exists()
            lines = [l for l in log_path.read_text().strip().split("\n") if l]
            last = json.loads(lines[-1])
            assert last["event"] == "MONITOR_STARTED"
            assert last["item"] == "Pikachu Plush"
            assert last["retailer"] == "target"
            assert last["level"] == "INFO"

    def test_error_writes_json_line_with_error_field(self) -> None:
        """error() should write a JSON line with error info."""
        from src.bot.logger import init_logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.error(
                "CHECKOUT_FAILED",
                item="Pikachu Plush",
                retailer="target",
                error="payment_declined",
                attempt=2,
            )

            log_path = Path(tmpdir) / "poke_drop.log"
            lines = [l for l in log_path.read_text().strip().split("\n") if l]
            last = json.loads(lines[-1])
            assert last["event"] == "CHECKOUT_FAILED"
            assert last["error"] == "payment_declined"
            assert last["attempt"] == 2
            assert last["level"] == "ERROR"

    def test_debug_masks_card_number_to_last_4(self) -> None:
        """DEBUG logs should mask card_number to last 4 digits."""
        from src.bot.logger import init_logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.debug("CART_DEBUG", card_number="4111111111111111", cvv="123")

            log_path = Path(tmpdir) / "poke_drop.log"
            content = log_path.read_text()
            assert "4111111111111111" not in content
            assert "****1111" in content
            assert '"cvv": "***"' in content

    def test_none_values_omitted_from_output(self) -> None:
        """Fields with None values should be omitted from output."""
        from src.bot.logger import init_logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.info("STOCK_DETECTED", item="Pikachu Plush", retailer=None)

            log_path = Path(tmpdir) / "poke_drop.log"
            lines = [l for l in log_path.read_text().strip().split("\n") if l]
            last = json.loads(lines[-1])
            assert "retailer" not in last

    def test_multiple_events_all_persisted(self) -> None:
        """Multiple info() calls should all be written to the log file."""
        from src.bot.logger import init_logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.info("MONITOR_STARTED", item="Item1", retailer="target")
            log.info("STOCK_DETECTED", item="Item1", retailer="target")
            log.info("CART_ADDED", item="Item1", retailer="target")

            log_path = Path(tmpdir) / "poke_drop.log"
            lines = [json.loads(l) for l in log_path.read_text().strip().split("\n") if l]
            events = [l["event"] for l in lines]
            assert "MONITOR_STARTED" in events
            assert "STOCK_DETECTED" in events
            assert "CART_ADDED" in events

    def test_warning_writes_json_with_warning_level(self) -> None:
        """warning() should write a JSON line at WARNING level."""
        from src.bot.logger import init_logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.warning("QUEUE_DETECTED", item="Pikachu Plush", retailer="walmart")

            log_path = Path(tmpdir) / "poke_drop.log"
            lines = [l for l in log_path.read_text().strip().split("\n") if l]
            last = json.loads(lines[-1])
            assert last["event"] == "QUEUE_DETECTED"
            assert last["level"] == "WARNING"


class TestSSEQueue:
    """Test in-memory SSE event queue for dashboard consumption."""

    def setup_method(self) -> None:
        from src.bot import logger as logger_module
        from src.bot.logger import Logger
        logger_module._logger_instance = None
        Logger._instance = None
        Logger._queue = []

    def test_info_puts_event_on_sse_queue(self) -> None:
        """info() should add the event to the SSE queue."""
        from src.bot.logger import init_logger, Logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.info("STOCK_DETECTED", item="Pikachu Plush", retailer="target")

            queue = Logger.get_sse_queue()
            assert len(queue) == 1
            assert queue[0]["event"] == "STOCK_DETECTED"
            assert queue[0]["item"] == "Pikachu Plush"

    def test_debug_does_not_put_on_sse_queue(self) -> None:
        """DEBUG level events should NOT be put on the SSE queue."""
        from src.bot.logger import init_logger, Logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.debug("SOME_DEBUG_EVENT", item="Pikachu Plush")

            queue = Logger.get_sse_queue()
            assert len(queue) == 0

    def test_warning_puts_event_on_sse_queue(self) -> None:
        """WARNING level events should be on the SSE queue."""
        from src.bot.logger import init_logger, Logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.warning("QUEUE_DETECTED", retailer="target")

            queue = Logger.get_sse_queue()
            assert len(queue) == 1
            assert queue[0]["event"] == "QUEUE_DETECTED"

    def test_multiple_events_accumulate_on_queue(self) -> None:
        """Multiple info() calls should accumulate on the SSE queue."""
        from src.bot.logger import init_logger, Logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            for i in range(5):
                log.info("MONITOR_STARTED", item=f"Item{i}", retailer="target")

            queue = Logger.get_sse_queue()
            assert len(queue) == 5

    def test_queue_max_size_enforced(self) -> None:
        """SSE queue should be capped at _max_queue_size (1000)."""
        from src.bot.logger import init_logger, Logger
        with tempfile.TemporaryDirectory() as tmpdir:
            original_max = Logger._max_queue_size
            Logger._max_queue_size = 10
            try:
                log = init_logger(log_dir=tmpdir)
                for i in range(20):
                    log.info("MONITOR_STARTED", item=f"Item{i}", retailer="target")

                queue = Logger.get_sse_queue()
                assert len(queue) == 10
                assert queue[-1]["item"] == "Item19"
            finally:
                Logger._max_queue_size = original_max

    def test_get_sse_queue_returns_empty_if_not_initialized(self) -> None:
        """get_sse_queue() should return [] if Logger was never initialized."""
        from src.bot.logger import Logger
        Logger._instance = None
        Logger._queue = []
        # Should not raise, just return empty list
        assert Logger.get_sse_queue() == []


class TestWebhookEventCoverage:
    """Test that all webhook events from PRD Section 8.2 can be logged."""

    def setup_method(self) -> None:
        from src.bot import logger as logger_module
        from src.bot.logger import Logger
        logger_module._logger_instance = None
        Logger._instance = None
        Logger._queue = []

    @pytest.mark.parametrize(
        "event_name",
        [
            "MONITOR_STARTED",
            "STOCK_DETECTED",
            "CART_ADDED",
            "CHECKOUT_STARTED",
            "CHECKOUT_SUCCESS",
            "CHECKOUT_FAILED",
            "CAPTCHA_PENDING",
            "CAPTCHA_SOLVED",
            "CAPTCHA_FAILED",
            "SESSION_EXPIRED",
            "QUEUE_DETECTED",
            "QUEUE_CLEARED",
            "DROP_WINDOW_APPROACHING",
            "DROP_WINDOW_OPEN",
            "PREWARM_URGENT",
            "PAYMENT_DECLINED",
            "MONITOR_STOPPED",
            "DAEMON_STARTED",
            "DAEMON_STOPPED",
        ],
    )
    def test_all_webhook_events_log_without_error(self, event_name: str) -> None:
        """Every defined webhook event type should be loggable without raising."""
        from src.bot.logger import init_logger, Logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.info(event_name, item="TestItem", retailer="target", attempt=1)

            queue = Logger.get_sse_queue()
            assert len(queue) == 1
            assert queue[0]["event"] == event_name

    def test_checkout_success_with_order_id_and_total(self) -> None:
        """CHECKOUT_SUCCESS should include order_id and total."""
        from src.bot.logger import init_logger, Logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.info(
                "CHECKOUT_SUCCESS",
                item="Pikachu Plush",
                retailer="target",
                order_id="ORDER-12345",
                total="$29.99",
            )
            queue = Logger.get_sse_queue()
            assert queue[0]["order_id"] == "ORDER-12345"
            assert queue[0]["total"] == "$29.99"

    def test_captcha_pending_with_pause_url(self) -> None:
        """CAPTCHA_PENDING should include pause_url for manual solving."""
        from src.bot.logger import init_logger, Logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.info(
                "CAPTCHA_PENDING",
                item="Pikachu Plush",
                retailer="target",
                captcha_type="recaptcha_v2",
                pause_url="https://target.com/checkout/captcha",
                timeout_seconds=120,
            )
            queue = Logger.get_sse_queue()
            assert queue[0]["pause_url"] == "https://target.com/checkout/captcha"
            assert queue[0]["captcha_type"] == "recaptcha_v2"

    def test_queue_detected_at_warning_level(self) -> None:
        """QUEUE_DETECTED should be logged at WARNING level."""
        from src.bot.logger import init_logger, Logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.warning(
                "QUEUE_DETECTED",
                item="Pikachu Plush",
                retailer="walmart",
                queue_url="https://walmart.com/queue.html",
            )
            log_path = Path(tmpdir) / "poke_drop.log"
            lines = [l for l in log_path.read_text().strip().split("\n") if l]
            last = json.loads(lines[-1])
            assert last["queue_url"] == "https://walmart.com/queue.html"
            assert last["level"] == "WARNING"
            queue = Logger.get_sse_queue()
            assert queue[0]["queue_url"] == "https://walmart.com/queue.html"

    def test_log_file_has_no_raw_card_numbers(self) -> None:
        """Raw card numbers must never appear in log file at any level.

        At INFO/WARNING/ERROR level, sensitive fields are fully redacted (***).
        At DEBUG level, card_number is masked to ****XXXX (last 4).
        """
        from src.bot.logger import init_logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.info(
                "CHECKOUT_STARTED",
                item="Pikachu Plush",
                retailer="target",
                card_number="4111111111111111",
                cvv="999",
            )
            log.error(
                "CHECKOUT_FAILED",
                item="Pikachu Plush",
                retailer="target",
                card_number="4111111111111111",
            )

            log_path = Path(tmpdir) / "poke_drop.log"
            content = log_path.read_text()
            # Raw card numbers must never appear
            assert "4111111111111111" not in content
            # At INFO/ERROR level, card_number is fully redacted
            assert '"card_number": "***"' in content
            assert '"cvv": "***"' in content

    def test_debug_level_shows_last_4_of_card(self) -> None:
        """At DEBUG level, card_number should show last 4 digits."""
        from src.bot.logger import init_logger
        with tempfile.TemporaryDirectory() as tmpdir:
            log = init_logger(log_dir=tmpdir)
            log.debug(
                "CART_DEBUG",
                card_number="4111111111111111",
            )

            log_path = Path(tmpdir) / "poke_drop.log"
            content = log_path.read_text()
            assert "4111111111111111" not in content
            assert "****1111" in content
