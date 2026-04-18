"""Tests for MAC-T02 item-to-account assignment logic."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from src.bot.monitor.account_assignment import AccountAssigner, AssignedAccount


class TestAccountAssigner:
    """Tests for AccountAssigner (MAC-T02 / MAC-2)."""

    def _mock_config(self, accounts: dict) -> MagicMock:
        cfg = MagicMock()
        cfg.accounts = accounts
        return cfg

    def test_single_account_returns_that_account(self) -> None:
        cfg = self._mock_config({
            "target": [
                MagicMock(username="user1", password="pass1", enabled=True,
                           item_filter=[], round_robin=False),
            ]
        })
        assigner = AccountAssigner(cfg)
        result = assigner.get_single_account_for_item("Charizard Box", "target")
        assert result is not None
        assert result.username == "user1"

    def test_item_filter_exact_match(self) -> None:
        acct1 = MagicMock(username="user1", password="pass1", enabled=True,
                          item_filter=["Charizard Box"], round_robin=False)
        acct2 = MagicMock(username="user2", password="pass2", enabled=True,
                          item_filter=["Pikachu Box"], round_robin=False)
        cfg = self._mock_config({"target": [acct1, acct2]})
        assigner = AccountAssigner(cfg)

        result = assigner.get_single_account_for_item("Charizard Box", "target")
        assert result is not None
        assert result.username == "user1"

        result2 = assigner.get_single_account_for_item("Pikachu Box", "target")
        assert result2 is not None
        assert result2.username == "user2"

    def test_item_filter_no_match_falls_back_to_all(self) -> None:
        acct1 = MagicMock(username="user1", password="pass1", enabled=True,
                          item_filter=["Charizard Box"], round_robin=False)
        acct2 = MagicMock(username="user2", password="pass2", enabled=True,
                          item_filter=["Pikachu Box"], round_robin=False)
        cfg = self._mock_config({"target": [acct1, acct2]})
        assigner = AccountAssigner(cfg)

        # No filter matches "Mewtwo Box"
        result = assigner.get_single_account_for_item("Mewtwo Box", "target")
        # Falls back to first enabled account (round_robin=False, so first)
        assert result is not None
        assert result.username == "user1"

    def test_disabled_account_not_returned(self) -> None:
        acct1 = MagicMock(username="user1", password="pass1", enabled=False,
                          item_filter=[], round_robin=False)
        cfg = self._mock_config({"target": [acct1]})
        assigner = AccountAssigner(cfg)
        result = assigner.get_single_account_for_item("Charizard Box", "target")
        assert result is None

    def test_no_accounts_for_retailer_returns_none(self) -> None:
        cfg = self._mock_config({})
        assigner = AccountAssigner(cfg)
        result = assigner.get_single_account_for_item("Charizard Box", "target")
        assert result is None

    def test_unknown_retailer_returns_none(self) -> None:
        cfg = self._mock_config({"target": []})
        assigner = AccountAssigner(cfg)
        result = assigner.get_single_account_for_item("Charizard Box", "amazon")
        assert result is None

    def test_round_robin_rotates_accounts(self) -> None:
        acct1 = MagicMock(username="user1", password="pass1", enabled=True,
                          item_filter=[], round_robin=True)
        acct2 = MagicMock(username="user2", password="pass2", enabled=True,
                          item_filter=[], round_robin=True)
        cfg = self._mock_config({"target": [acct1, acct2]})
        assigner = AccountAssigner(cfg)

        # First call - user1
        r1 = assigner.get_single_account_for_item("Generic Item", "target")
        assert r1.username == "user1"
        # Second call - user2 (rotated)
        r2 = assigner.get_single_account_for_item("Generic Item", "target")
        assert r2.username == "user2"
        # Third call - back to user1
        r3 = assigner.get_single_account_for_item("Generic Item", "target")
        assert r3.username == "user1"

    def test_item_filter_takes_priority_over_round_robin(self) -> None:
        acct1 = MagicMock(username="user1", password="pass1", enabled=True,
                          item_filter=["Charizard Box"], round_robin=True)
        acct2 = MagicMock(username="user2", password="pass2", enabled=True,
                          item_filter=[], round_robin=True)
        cfg = self._mock_config({"target": [acct1, acct2]})
        assigner = AccountAssigner(cfg)

        # Item matches acct1's filter - should always return user1, not round-robin
        result = assigner.get_single_account_for_item("Charizard Box", "target")
        assert result.username == "user1"
        # Second call - still user1 (filter takes priority)
        result2 = assigner.get_single_account_for_item("Charizard Box", "target")
        assert result2.username == "user1"
        # Third call - still user1
        result3 = assigner.get_single_account_for_item("Charizard Box", "target")
        assert result3.username == "user1"

    def test_round_robin_single_account_always_returns_it(self) -> None:
        acct1 = MagicMock(username="user1", password="pass1", enabled=True,
                          item_filter=[], round_robin=True)
        cfg = self._mock_config({"target": [acct1]})
        assigner = AccountAssigner(cfg)

        result = assigner.get_single_account_for_item("Item", "target")
        assert result.username == "user1"
        for _ in range(5):
            r = assigner.get_single_account_for_item("Item", "target")
            assert r.username == "user1"

    def test_get_accounts_for_item_multiple_matches(self) -> None:
        acct1 = MagicMock(username="user1", password="pass1", enabled=True,
                          item_filter=["Charizard Box"], round_robin=False)
        acct2 = MagicMock(username="user2", password="pass2", enabled=True,
                          item_filter=["Charizard Box"], round_robin=False)
        cfg = self._mock_config({"target": [acct1, acct2]})
        assigner = AccountAssigner(cfg)

        result = assigner.get_accounts_for_item("Charizard Box", "target")
        assert len(result) == 2
        usernames = {r.account.username for r in result}
        assert usernames == {"user1", "user2"}

    def test_reset_round_robin_clears_state(self) -> None:
        acct1 = MagicMock(username="user1", password="pass1", enabled=True,
                          item_filter=[], round_robin=True)
        acct2 = MagicMock(username="user2", password="pass2", enabled=True,
                          item_filter=[], round_robin=True)
        cfg = self._mock_config({"target": [acct1, acct2]})
        assigner = AccountAssigner(cfg)

        r1 = assigner.get_single_account_for_item("Item", "target")
        assert r1.username == "user1"

        assigner.reset_round_robin("target")

        r2 = assigner.get_single_account_for_item("Item", "target")
        assert r2.username == "user1"  # reset, starts from beginning again

    def test_reset_all_clears_all_retailers(self) -> None:
        acct = MagicMock(username="user1", password="pass1", enabled=True,
                         item_filter=[], round_robin=True)
        cfg = self._mock_config({"target": [acct], "walmart": [acct]})
        assigner = AccountAssigner(cfg)

        assigner.get_single_account_for_item("Item", "target")
        assigner.get_single_account_for_item("Item", "walmart")

        assigner.reset_round_robin()

        # Both should be reset
        r1 = assigner.get_single_account_for_item("Item", "target")
        r2 = assigner.get_single_account_for_item("Item", "walmart")
        assert r1.username == "user1"
        assert r2.username == "user1"

    def test_assigned_account_dataclass_fields(self) -> None:
        acct = MagicMock(username="user1", password="pass1", enabled=True,
                         item_filter=[], round_robin=False)
        cfg = self._mock_config({"target": [acct]})
        assigner = AccountAssigner(cfg)

        result = assigner.get_accounts_for_item("Item", "target")
        assert len(result) == 1
        aa = result[0]
        assert isinstance(aa, AssignedAccount)
        assert aa.account.username == "user1"
        assert aa.account_index == 0
