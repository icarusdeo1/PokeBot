"""Tests for src.shared.crash_recovery."""

from __future__ import annotations

import json
import signal
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from src.shared.crash_recovery import (
    CrashRecovery,
    CrashRecoveryState,
    CrashStage,
)


# ── CrashRecoveryState tests ───────────────────────────────────────────────────


class TestCrashRecoveryState:
    """Unit tests for CrashRecoveryState serialization."""

    def test_to_dict_roundtrip(self) -> None:
        """State serializes and deserializes correctly."""
        state = CrashRecoveryState(
            item="Pikachu Plush",
            retailer="target",
            stage=CrashStage.CART_READY,
            started_at="2026-04-18T09:00:00+00:00",
            stage_reached_at="2026-04-18T09:00:05+00:00",
            order_id="",
            error="",
        )
        data = state.to_dict()
        restored = CrashRecoveryState.from_dict(data)

        assert restored.item == state.item
        assert restored.retailer == state.retailer
        assert restored.stage == state.stage
        assert restored.started_at == state.started_at
        assert restored.stage_reached_at == state.stage_reached_at

    def test_to_dict_with_order_id(self) -> None:
        """Order ID is preserved through serialization."""
        state = CrashRecoveryState(
            item="Charizard Box",
            retailer="walmart",
            stage=CrashStage.CHECKOUT_COMPLETE,
            started_at="2026-04-18T09:00:00+00:00",
            stage_reached_at="2026-04-18T09:00:30+00:00",
            order_id="ORD-12345",
            error="",
        )
        data = state.to_dict()
        restored = CrashRecoveryState.from_dict(data)

        assert restored.order_id == "ORD-12345"
        assert restored.error == ""

    def test_to_dict_with_error(self) -> None:
        """Error message is preserved through serialization."""
        state = CrashRecoveryState(
            item="Bulbasaur Plush",
            retailer="bestbuy",
            stage=CrashStage.CHECKOUT_FAILED,
            started_at="2026-04-18T09:00:00+00:00",
            stage_reached_at="2026-04-18T09:00:10+00:00",
            order_id="",
            error="Payment declined",
        )
        data = state.to_dict()
        restored = CrashRecoveryState.from_dict(data)

        assert restored.error == "Payment declined"
        assert restored.stage == CrashStage.CHECKOUT_FAILED

    def test_from_dict_missing_fields_use_defaults(self) -> None:
        """Missing fields fall back to defaults."""
        data: dict[str, object] = {}
        state = CrashRecoveryState.from_dict(data)

        assert state.item == ""
        assert state.retailer == ""
        assert state.stage == CrashStage.STANDBY
        assert state.started_at == ""
        assert state.stage_reached_at == ""

    def test_from_dict_invalid_stage_value(self) -> None:
        """Invalid stage value raises ValueError."""
        data = {"stage": "not_a_stage"}
        with pytest.raises(ValueError):
            CrashRecoveryState.from_dict(data)


# ── CrashRecovery context manager tests ───────────────────────────────────────


class TestCrashRecoveryContextManager:
    """Unit tests for CrashRecovery as a context manager."""

    def test_update_stores_state(self, tmp_path: Path) -> None:
        """update() stores the given checkout state."""
        crash = CrashRecovery(state_dir=tmp_path)

        crash.update(
            item="Mewtwo Box",
            retailer="target",
            stage=CrashStage.STOCK_FOUND,
        )

        assert crash.stage() == CrashStage.STOCK_FOUND

    def test_update_overwrites_existing_stage(self, tmp_path: Path) -> None:
        """update() called twice keeps only the latest stage."""
        crash = CrashRecovery(state_dir=tmp_path)

        crash.update(item="Any", retailer="walmart", stage=CrashStage.STANDBY)
        crash.update(item="Any", retailer="walmart", stage=CrashStage.CART_READY)

        assert crash.stage() == CrashStage.CART_READY

    def test_update_preserves_order_id_in_memory(self, tmp_path: Path) -> None:
        """Once set, order_id is not cleared on subsequent updates (in-memory)."""
        crash = CrashRecovery(state_dir=tmp_path)

        crash.update(
            item="X", retailer="y", stage=CrashStage.CHECKOUT_COMPLETE, order_id="OID-99"
        )
        crash.update(item="X", retailer="y", stage=CrashStage.CHECKOUT_COMPLETE)

        assert crash._current_state is not None
        assert crash._current_state.order_id == "OID-99"

    def test_normal_exit_clears_state_json(self, tmp_path: Path) -> None:
        """On normal exit the state.json file is deleted."""
        state_file = tmp_path / "state.json"
        state_file.write_text(
            '{"item":"test","retailer":"t","stage":"standby",'
            '"started_at":"","stage_reached_at":"","order_id":"","error":""}'
        )

        crash = CrashRecovery(state_dir=tmp_path)
        crash._current_state = CrashRecoveryState(
            item="test",
            retailer="t",
            stage=CrashStage.STANDBY,
            started_at="2026-04-18T09:00:00+00:00",
            stage_reached_at="2026-04-18T09:00:00+00:00",
        )

        crash.clear()
        assert not state_file.exists()

    def test_load_returns_none_when_no_file(self, tmp_path: Path) -> None:
        """load() returns None when state.json does not exist."""
        crash = CrashRecovery(state_dir=tmp_path)
        assert crash.load() is None

    def test_load_returns_none_for_invalid_json(self, tmp_path: Path) -> None:
        """load() returns None for corrupted state.json."""
        state_file = tmp_path / "state.json"
        state_file.write_text("not json at all")

        crash = CrashRecovery(state_dir=tmp_path)
        assert crash.load() is None

    def test_load_returns_none_for_empty_file(self, tmp_path: Path) -> None:
        """load() returns None for empty state.json."""
        state_file = tmp_path / "state.json"
        state_file.write_text("")

        crash = CrashRecovery(state_dir=tmp_path)
        assert crash.load() is None

    def test_load_returns_none_for_partially_empty_state(self, tmp_path: Path) -> None:
        """load() returns None when required fields (item/stage) are missing."""
        state_file = tmp_path / "state.json"
        state_file.write_text(
            '{"item":"","retailer":"target","stage":"standby",'
            '"started_at":"","stage_reached_at":"","order_id":"","error":""}'
        )

        crash = CrashRecovery(state_dir=tmp_path)
        assert crash.load() is None

    def test_load_restores_full_state(self, tmp_path: Path) -> None:
        """load() correctly restores a complete saved state."""
        state_file = tmp_path / "state.json"
        state_file.write_text(
            json.dumps({
                "item": "Eevee Plush",
                "retailer": "bestbuy",
                "stage": "cart_ready",
                "started_at": "2026-04-18T09:00:00+00:00",
                "stage_reached_at": "2026-04-18T09:00:05+00:00",
                "order_id": "",
                "error": "",
            })
        )

        crash = CrashRecovery(state_dir=tmp_path)
        state = crash.load()

        assert state is not None
        assert state.item == "Eevee Plush"
        assert state.retailer == "bestbuy"
        assert state.stage == CrashStage.CART_READY
        assert state.started_at == "2026-04-18T09:00:00+00:00"

    def test_clear_deletes_existing_file(self, tmp_path: Path) -> None:
        """clear() removes state.json if it exists."""
        state_file = tmp_path / "state.json"
        state_file.write_text('{"item":"x"}')

        crash = CrashRecovery(state_dir=tmp_path)
        crash.clear()

        assert not state_file.exists()

    def test_clear_handles_missing_file(self, tmp_path: Path) -> None:
        """clear() does not raise when state.json does not exist."""
        crash = CrashRecovery(state_dir=tmp_path)
        crash.clear()  # should not raise

    def test_enter_installs_signal_handlers(self, tmp_path: Path) -> None:
        """__enter__ installs SIGTERM, SIGINT, and SIGHUP handlers."""
        crash = CrashRecovery(state_dir=tmp_path)

        with crash:
            cur_term = signal.getsignal(signal.SIGTERM)
            cur_int = signal.getsignal(signal.SIGINT)
            cur_hup = signal.getsignal(signal.SIGHUP)

            assert cur_term is not signal.SIG_DFL
            assert cur_term is not signal.SIG_IGN
            assert cur_int is not signal.SIG_DFL
            assert cur_hup is not signal.SIG_DFL

    def test_exit_restores_signal_handlers(self, tmp_path: Path) -> None:
        """__exit__ restores the original signal handlers."""
        orig_term = signal.getsignal(signal.SIGTERM)

        crash = CrashRecovery(state_dir=tmp_path)
        with crash:
            pass

        restored = signal.getsignal(signal.SIGTERM)
        assert restored is orig_term

    def test_save_state_before_exit_is_accessible(self, tmp_path: Path) -> None:
        """_save_state() inside the with-block persists correct data."""
        state_file = tmp_path / "state.json"

        crash = CrashRecovery(state_dir=tmp_path)

        with crash:
            crash.update(
                item="Snorlax Box",
                retailer="target",
                stage=CrashStage.CHECKOUT_FAILED,
                error="Session expired",
            )
            # Save inside the context so file is written before exit clears it
            crash._save_state()

            # Verify file exists and has correct content inside the block
            assert state_file.exists()
            data = json.loads(state_file.read_text())
            assert data["item"] == "Snorlax Box"
            assert data["stage"] == "checkout_failed"
            assert data["error"] == "Session expired"

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """_save_state() + load() produces a correct roundtrip."""
        crash = CrashRecovery(state_dir=tmp_path)

        crash.update(
            item="Lapras Plush",
            retailer="walmart",
            stage=CrashStage.STOCK_FOUND,
        )
        crash._save_state()

        loaded = crash.load()
        assert loaded is not None
        assert loaded.item == "Lapras Plush"
        assert loaded.retailer == "walmart"
        assert loaded.stage == CrashStage.STOCK_FOUND

    def test_signal_handler_installed_and_callable(self, tmp_path: Path) -> None:
        """Signal handler installed by __enter__ is a callable (not SIG_DFL)."""
        crash = CrashRecovery(state_dir=tmp_path)

        with crash:
            term_handler = signal.getsignal(signal.SIGTERM)
            int_handler = signal.getsignal(signal.SIGINT)

            assert callable(term_handler)
            assert callable(int_handler)
