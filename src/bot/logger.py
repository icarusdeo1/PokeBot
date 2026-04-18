"""Structured logging for the PokeDrop bot.

Per PRD Sections 10.1, 18.
- Structured JSON logging to `logs/poke_drop.log`
- RotatingFileHandler (10MB, 5 backups)
- Log levels: DEBUG (form fields masked), INFO (lifecycle events), WARNING, ERROR
- In-memory event queue consumed by SSE endpoint for dashboard real-time display

Usage:
    from src.bot.logger import init_logger, logger

    init_logger()
    logger.info("STOCK_DETECTED", item="Pikachu Plush", retailer="target")
    logger.error("CHECKOUT_FAILED", item="Pikachu Plush", retailer="target",
                 error="payment_declined", attempt=2)
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# ── Sensitive field masking ───────────────────────────────────────────────────

_SENSITIVE_KEYS = frozenset({
    "card_number",
    "cardnumber",
    "cvv",
    "CVV",
    "cvc",
    "CVC",
    "password",
    "pwd",
    "secret",
    "token",
    "auth_token",
    "cart_token",
    "api_key",
    "apikey",
    "2captcha_key",
    "2captcha",
})


def _mask_value(key: str, value: Any, log_level: int) -> Any:
    """Mask sensitive field values at DEBUG level only.

    At DEBUG: mask card numbers to ****XXXX (last 4), cvv to ***
    At higher levels: value is removed entirely for sensitive fields
    """
    key_lower = key.lower()
    if key_lower not in _SENSITIVE_KEYS:
        return value

    if not isinstance(value, str):
        return "***"

    if log_level <= logging.DEBUG:
        if key_lower in ("card_number", "cardnumber") and len(value) >= 4:
            return f"****{value[-4:]}"
        return "***"
    else:
        return "***"


def _mask_record(data: dict[str, Any], log_level: int) -> dict[str, Any]:
    """Return a copy of data with sensitive fields masked per log level."""
    result: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, dict):
            result[k] = _mask_record(v, log_level)
        elif isinstance(v, list):
            result[k] = [
                _mask_record(item, log_level) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            result[k] = _mask_value(k, v, log_level)
    return result


# ── JSON log formatter ────────────────────────────────────────────────────────


class JsonFormatter(logging.Formatter):
    """Format log records as structured JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        if not isinstance(record.msg, dict):
            raise TypeError("JsonFormatter requires dict msg")
        data: dict[str, Any] = dict(record.msg)

        data["timestamp"] = datetime.now(timezone.utc).isoformat()
        data["level"] = record.levelname

        data = _mask_record(data, record.levelno)

        return json.dumps(data, default=str)


# ── Logger ────────────────────────────────────────────────────────────────────


class _HumanFormatter(logging.Formatter):
    """Human-readable formatter for console output.

    Formats: EVENT_NAME key=value key=value ...
    """

    def format(self, record: logging.LogRecord) -> str:
        if not isinstance(record.msg, dict):
            return record.getMessage()
        d = record.msg
        event = d.get("event", "?")
        parts = [event]
        skip_keys = {"event", "timestamp", "level"}
        for k, v in d.items():
            if k in skip_keys or v is None:
                continue
            if isinstance(v, dict):
                continue
            parts.append(f"{k}={v}")
        return " ".join(parts)


class Logger:
    """Structured logger for the PokeDrop bot.

    Writes structured JSON to a rotating log file and maintains an in-memory
    queue of recent events for SSE consumption by the dashboard.
    """

    _instance: Logger | None = None
    _queue: list[dict[str, Any]] = []
    _max_queue_size = 1000

    def __init__(
        self,
        log_dir: str | Path | None = None,
        max_bytes: int = 10 * 1024 * 1024,  # 10 MB
        backup_count: int = 5,
    ) -> None:
        """Initialize the structured logger.

        Args:
            log_dir: Directory for log files. Defaults to `<repo_root>/logs`.
            max_bytes: Max size of each log file before rotation.
            backup_count: Number of backup files to keep.
        """
        # Resolve log directory relative to project root
        if log_dir is None:
            log_dir = Path(__file__).parent.parent.parent / "logs"
        else:
            log_dir = Path(log_dir)

        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._log_dir / "poke_drop.log"

        self._logger = logging.getLogger("pokedrop")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()

        # Rotating file handler — JSON lines
        fh = RotatingFileHandler(
            filename=str(self._log_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(JsonFormatter())
        self._logger.addHandler(fh)

        # Console handler — human-readable
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(logging.INFO)
        sh.setFormatter(_HumanFormatter())
        self._logger.addHandler(sh)

        # In-memory SSE queue
        Logger._queue = []

        Logger._instance = self

    def debug(self, event: str, **kwargs: Any) -> None:
        """Log a DEBUG level event. Sensitive fields partially masked."""
        self._log(logging.DEBUG, event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        """Log an INFO level event (lifecycle events)."""
        self._log(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        """Log a WARNING level event."""
        self._log(logging.WARNING, event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        """Log an ERROR level event."""
        self._log(logging.ERROR, event, **kwargs)

    def _log(self, level: int, event: str, **kwargs: Any) -> None:
        """Emit a structured log record and enqueue for SSE.

        Sensitive fields are masked before any handler sees the record.
        """
        record_dict: dict[str, Any] = {"event": event}
        record_dict.update(kwargs)
        # Omit None values
        record_dict = {k: v for k, v in record_dict.items() if v is not None}

        # Apply masking before passing to any handler (file or console)
        masked = _mask_record(record_dict, level)

        self._logger.log(level, masked)

        if level >= logging.INFO:
            self._enqueue(masked)

    def _enqueue(self, data: dict[str, Any]) -> None:
        """Add event to the in-memory SSE queue."""
        Logger._queue.append(data)
        if len(Logger._queue) > Logger._max_queue_size:
            Logger._queue = Logger._queue[-Logger._max_queue_size:]

    @classmethod
    def get_sse_queue(cls) -> list[dict[str, Any]]:
        """Return a copy of the SSE event queue.

        Returns [] if the Logger has not been initialized.
        """
        return list(cls._queue) if cls._queue else []

    @classmethod
    def get_instance(cls) -> Logger:
        """Return the singleton Logger instance.

        Raises RuntimeError if not yet initialized.
        """
        if cls._instance is None:
            raise RuntimeError(
                "Logger not initialized. Call init_logger() first."
            )
        return cls._instance


# ── Module-level singleton ────────────────────────────────────────────────────

_logger_instance: Logger | None = None


def init_logger(
    log_dir: str | Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> Logger:
    """Initialize (or return) the Logger singleton.

    Subsequent calls with different arguments are no-ops — the singleton
    is created once and reused.
    """
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger(
            log_dir=log_dir,
            max_bytes=max_bytes,
            backup_count=backup_count,
        )
    return _logger_instance


def logger() -> Logger:
    """Return the Logger singleton, initializing it if needed."""
    return init_logger()
