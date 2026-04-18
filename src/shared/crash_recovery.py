"""Crash recovery for the PokeDrop bot.

Per PRD Section 9.14 (OP-1, OP-2).
- On abnormal exit (signal, unhandled exception), persists current checkout state
  to `state.json` — item, retailer, stage reached, timestamps.
- On restart, load_crash_state() returns the saved state so the bot can either
  skip already-ordered items or resume from the last known good stage.

Usage (in daemon.py):
    from src.shared.crash_recovery import CrashRecovery

    crash = CrashRecovery(state_dir=Path("."))
    with crash:
        # bot runs here
        crash.update(item="Pikachu Plush", retailer="target", stage=CrashStage.CART_READY)

    # On normal exit, state.json is cleared automatically.
    # On crash (signal / unhandled exception), state.json is preserved.
    # On restart:
    state = crash.load()
    if state is not None:
        if state.stage == CrashStage.CHECKOUT_COMPLETE:
            skip_item(state.item)  # already ordered
        else:
            resume_from(state.stage, state.item, state.retailer)
"""

from __future__ import annotations

__all__ = ["CrashRecovery", "CrashRecoveryState", "CrashStage"]

import atexit
import json
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

# ── Stage enum ────────────────────────────────────────────────────────────────


class CrashStage(Enum):
    """Checkout stages for crash recovery state.

    Matches the core state machine from PRD Section 7.2.
    """

    STANDBY = "standby"
    STOCK_FOUND = "stock_found"
    CART_READY = "cart_ready"
    CHECKOUT_COMPLETE = "checkout_complete"
    CHECKOUT_FAILED = "checkout_failed"


# ── State dataclass ────────────────────────────────────────────────────────────


@dataclass
class CrashRecoveryState:
    """Checkout state persisted on abnormal exit for crash recovery."""

    item: str = ""
    retailer: str = ""
    stage: CrashStage = CrashStage.STANDBY
    started_at: str = ""  # ISO-8601 UTC
    stage_reached_at: str = ""  # ISO-8601 UTC
    order_id: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON serialization."""
        return {
            "item": self.item,
            "retailer": self.retailer,
            "stage": self.stage.value,
            "started_at": self.started_at,
            "stage_reached_at": self.stage_reached_at,
            "order_id": self.order_id,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CrashRecoveryState:
        """Deserialize from a dict (as loaded from JSON)."""
        return cls(
            item=data.get("item", ""),
            retailer=data.get("retailer", ""),
            stage=CrashStage(data.get("stage", "standby")),
            started_at=data.get("started_at", ""),
            stage_reached_at=data.get("stage_reached_at", ""),
            order_id=data.get("order_id", ""),
            error=data.get("error", ""),
        )


# ── CrashRecovery context manager ──────────────────────────────────────────────


class CrashRecovery:
    """Crash recovery context manager.

    Wraps the main bot loop. On normal exit (ctx manager exit), clears
    state.json. On abnormal exit (signal, unhandled exception), persists the
    current checkout state to state.json.

    Usage:
        crash = CrashRecovery(state_dir=Path("."))
        with crash:
            monitor.run()
    """

    STATE_FILENAME = "state.json"

    def __init__(
        self,
        state_dir: Path | str | None = None,
    ) -> None:
        """Initialize the crash recovery handler.

        Args:
            state_dir: Directory for state.json. Defaults to cwd.
        """
        if state_dir is None:
            state_dir = Path.cwd()
        self._state_path = Path(state_dir) / self.STATE_FILENAME

        self._current_state: CrashRecoveryState | None = None
        self._exit_expected = False

        # Signal handlers to install
        self._prev_sigterm: Any = None
        self._prev_sigint: Any = None
        self._prev_sighup: Any = None

    # ── Public API ──────────────────────────────────────────────────────────

    def update(
        self,
        item: str = "",
        retailer: str = "",
        stage: CrashStage = CrashStage.STANDBY,
        order_id: str = "",
        error: str = "",
    ) -> None:
        """Update the current checkout state for crash recovery.

        Call this whenever the checkout stage changes.

        Args:
            item: Item name being checked out.
            retailer: Retailer adapter name.
            stage: Current checkout stage.
            order_id: Order confirmation ID (only set on CHECKOUT_COMPLETE).
            error: Error message (only set on CHECKOUT_FAILED).
        """
        now = datetime.now(timezone.utc).isoformat()
        if self._current_state is None:
            self._current_state = CrashRecoveryState(
                item=item,
                retailer=retailer,
                stage=stage,
                started_at=now,
                stage_reached_at=now,
                order_id=order_id,
                error=error,
            )
        else:
            self._current_state.item = item
            self._current_state.retailer = retailer
            self._current_state.stage = stage
            self._current_state.stage_reached_at = now
            if order_id:
                self._current_state.order_id = order_id
            if error:
                self._current_state.error = error

    def load(self) -> CrashRecoveryState | None:
        """Load and return the persisted crash recovery state.

        Returns None if no state.json exists or it is invalid.

        After loading, the caller should call clear() once the state
        has been acted upon (item skipped or checkout resumed).
        """
        if not self._state_path.exists():
            return None
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            state = CrashRecoveryState.from_dict(data)
            # Validate required fields
            if not state.item or not state.stage:
                return None
            return state
        except (json.JSONDecodeError, ValueError, OSError):
            return None

    def clear(self) -> None:
        """Delete the state.json file.

        Call this after successfully resuming or skipping a crashed checkout.
        Also called automatically on normal context manager exit.
        """
        if self._state_path.exists():
            try:
                self._state_path.unlink()
            except OSError:
                pass

    def stage(self) -> CrashStage | None:
        """Return the current in-memory stage, or None if not set."""
        return self._current_state.stage if self._current_state else None

    # ── Context manager ────────────────────────────────────────────────────

    def _save_state(self) -> None:
        """Persist current state to state.json (called on abnormal exit)."""
        if self._current_state is not None:
            try:
                self._state_path.write_text(
                    json.dumps(self._current_state.to_dict(), indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass  # Best-effort persistence

    def _signal_handler(self, signum: int, _frame: Any) -> None:
        """Handle termination signals by persisting state and exiting."""
        sig_name = signal.Signals(signum).name
        # Re-raise the signal to allow default handler to terminate the process
        # but first save state
        self._save_state()
        sys.exit(128 + signum)

    def _exception_handler(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Handle unhandled exceptions by persisting state then re-raising."""
        self._save_state()

    def __enter__(self) -> CrashRecovery:
        """Install signal handlers and exception hook on entry."""
        self._exit_expected = False

        # Register signal handlers for graceful crash detection
        self._prev_sigterm = signal.signal(signal.SIGTERM, self._signal_handler)
        self._prev_sigint = signal.signal(signal.SIGINT, self._signal_handler)
        self._prev_sighup = signal.signal(signal.SIGHUP, self._signal_handler)

        # Register unhandled exception hook
        self._original_excepthook = sys.excepthook
        sys.excepthook = self._exception_handler

        # atexit handler for normal exit — clears state.json
        atexit.register(self._normal_exit)

        return self

    def _normal_exit(self) -> None:
        """Called on normal interpreter shutdown. Clears state.json."""
        self._exit_expected = True
        self.clear()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Uninstall handlers on exit. State is cleared on normal exit."""
        # Restore original signal handlers
        if self._prev_sigterm is not None:
            signal.signal(signal.SIGTERM, self._prev_sigterm)
        if self._prev_sigint is not None:
            signal.signal(signal.SIGINT, self._prev_sigint)
        if self._prev_sighup is not None:
            signal.signal(signal.SIGHUP, self._prev_sighup)

        # Restore original exception hook
        sys.excepthook = self._original_excepthook

        # Remove atexit handler (prevents double-clear if exit happens normally)
        try:
            atexit.unregister(self._normal_exit)
        except (ValueError, TypeError):
            pass

        # On normal exit: clear persisted state
        if not self._exit_expected and exc_type is None:
            self.clear()
