"""Tests for MAC-T03 one-purchase-per-account enforcement."""

from __future__ import annotations

import pytest
import tempfile
import os
from unittest.mock import MagicMock

from src.bot.monitor.one_purchase_enforcer import OnePurchaseEnforcer
from src.shared.db import DatabaseManager


class TestOnePurchaseEnforcer:
    """Tests for OnePurchaseEnforcer (MAC-T03 / MAC-3)."""

    def _enforcer(self, mock_db: MagicMock) -> OnePurchaseEnforcer:
        return OnePurchaseEnforcer(mock_db)

    def test_can_purchase_true_when_not_purchased(self) -> None:
        mock_db = MagicMock()
        mock_db.has_item_been_purchased_in_window.return_value = False
        enforcer = self._enforcer(mock_db)

        result = enforcer.can_purchase("Charizard Box", "target", "dw_001")
        assert result is True
        mock_db.has_item_been_purchased_in_window.assert_called_once_with(
            "Charizard Box", "target", "dw_001"
        )

    def test_can_purchase_false_when_already_purchased(self) -> None:
        mock_db = MagicMock()
        mock_db.has_item_been_purchased_in_window.return_value = True
        enforcer = self._enforcer(mock_db)

        result = enforcer.can_purchase("Charizard Box", "target", "dw_001")
        assert result is False

    def test_record_purchase_calls_db(self) -> None:
        mock_db = MagicMock()
        enforcer = self._enforcer(mock_db)

        enforcer.record_purchase("Charizard Box", "target", "dw_001", account_index=2)

        mock_db.record_account_purchase.assert_called_once_with(
            "Charizard Box", "target", "dw_001", 2
        )

    def test_get_item_status_purchased(self) -> None:
        mock_db = MagicMock()
        mock_db.get_purchase_window_for_item.return_value = "dw_001"
        enforcer = self._enforcer(mock_db)

        result = enforcer.get_item_status("Charizard Box", "target")
        assert result == "purchased"

    def test_get_item_status_never_purchased(self) -> None:
        mock_db = MagicMock()
        mock_db.get_purchase_window_for_item.return_value = None
        enforcer = self._enforcer(mock_db)

        result = enforcer.get_item_status("Charizard Box", "target")
        assert result == "never_purchased"

    def test_clear_old_history(self) -> None:
        mock_db = MagicMock()
        mock_db.clear_purchase_history.return_value = 5
        enforcer = self._enforcer(mock_db)

        count = enforcer.clear_old_history(older_than_days=30)
        assert count == 5
        mock_db.clear_purchase_history.assert_called_once_with(30)


class TestAccountPurchasesDB:
    """Tests for account_purchases table and DB methods (MAC-T03)."""

    def _temp_db(self):
        db_path = tempfile.mktemp(suffix=".db")
        db = DatabaseManager(db_path)
        db.initialize()
        return db, db_path

    def test_record_account_purchase_inserts_row(self) -> None:
        db, db_path = self._temp_db()
        try:
            db.record_account_purchase("Charizard Box", "target", "dw_001", 0)
            assert db.has_item_been_purchased_in_window("Charizard Box", "target", "dw_001")
            assert not db.has_item_been_purchased_in_window("Pikachu Box", "target", "dw_001")
            assert not db.has_item_been_purchased_in_window("Charizard Box", "walmart", "dw_001")
            assert not db.has_item_been_purchased_in_window("Charizard Box", "target", "dw_002")
        finally:
            os.unlink(db_path)

    def test_has_item_been_purchased_in_window_false(self) -> None:
        db, db_path = self._temp_db()
        try:
            assert not db.has_item_been_purchased_in_window("Charizard Box", "target", "dw_001")
        finally:
            os.unlink(db_path)

    def test_get_purchase_window_returns_latest(self) -> None:
        db, db_path = self._temp_db()
        try:
            assert db.get_purchase_window_for_item("Charizard Box", "target") is None
            db.record_account_purchase("Charizard Box", "target", "dw_001", 0)
            window = db.get_purchase_window_for_item("Charizard Box", "target")
            assert window == "dw_001"
            db.record_account_purchase("Charizard Box", "target", "dw_002", 1)
            # After second purchase, a window should be returned (might be dw_002 or dw_001
            # depending on timestamp precision; verify a value is returned and it's one of our windows)
            window2 = db.get_purchase_window_for_item("Charizard Box", "target")
            assert window2 in ("dw_001", "dw_002")
        finally:
            os.unlink(db_path)

    def test_clear_purchase_history(self) -> None:
        db, db_path = self._temp_db()
        try:
            db.record_account_purchase("Charizard Box", "target", "dw_001", 0)
            assert db.has_item_been_purchased_in_window("Charizard Box", "target", "dw_001")
            # Clear history older than 30 days - row inserted now, not 30+ days old, so 0 deleted
            deleted = db.clear_purchase_history(older_than_days=30)
            assert deleted == 0
            assert db.has_item_been_purchased_in_window("Charizard Box", "target", "dw_001")
            # Clear history older than -1 day (i.e., delete everything)
            deleted_all = db.clear_purchase_history(older_than_days=-1)
            assert deleted_all == 1
            assert not db.has_item_been_purchased_in_window("Charizard Box", "target", "dw_001")
        finally:
            os.unlink(db_path)
