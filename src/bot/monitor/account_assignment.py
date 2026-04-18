"""Item-to-account assignment logic (MAC-T02).

Implements MAC-2: items can be assigned to specific account(s) or spread
round-robin across available accounts.

Per PRD Section 9.10 (MAC-2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.bot.config import Config, _AccountConfig


@dataclass
class AssignedAccount:
    """An account selected for a specific item."""
    account: _AccountConfig
    account_index: int  # 0-based index for round-robin tracking


class AccountAssigner:
    """Assigns items to retailer accounts based on item_filter or round-robin.

    Per MAC-T02 / MAC-2:
    - If an account has item_filter matching the item name -> use that account
    - If an account has round_robin=True -> include it in round-robin pool
    - If multiple accounts match (item_filter overlaps), assign round-robin across them
    - If no item_filter matches, assign round-robin across all enabled accounts
      for that retailer that have round_robin=True
    - If still no match, fall back to all enabled accounts with round_robin=False
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        # Round-robin state: dict of retailer -> current position
        self._round_robin_index: dict[str, int] = {}

    def get_accounts_for_item(
        self,
        item_name: str,
        retailer: str,
    ) -> list[AssignedAccount]:
        """Get all accounts eligible for a given item+retailer.

        Assignment rules (MAC-2):
        1. If any account has item_filter matching item_name -> include those accounts
        2. Else if any account has round_robin=True -> round-robin across them
        3. Else use all enabled accounts for retailer (fallback)

        Returns:
            List of AssignedAccount, each with account + account_index for tracking.

        Raises:
            ValueError: If retailer is not a valid retailer name.
        """
        accounts = self._config.accounts.get(retailer, [])
        if not accounts:
            return []

        # Collect enabled accounts
        enabled = [a for a in accounts if a.enabled]
        if not enabled:
            return []

        # Rule 1: accounts with item_filter matching this item
        item_matched = [
            (i, a) for i, a in enumerate(enabled) if item_name in a.item_filter
        ]
        if item_matched:
            return [AssignedAccount(account=a, account_index=i) for i, a in item_matched]

        # Rule 2: accounts with round_robin=True
        rr_accounts = [(i, a) for i, a in enumerate(enabled) if a.round_robin]
        if rr_accounts:
            # Assign round-robin
            return self._assign_round_robin(retailer, rr_accounts)

        # Rule 3: fallback to all enabled accounts (no round-robin tracking)
        return [AssignedAccount(account=a, account_index=i) for i, a in enumerate(enabled)]

    def _assign_round_robin(
        self,
        retailer: str,
        rr_accounts: list[tuple[int, _AccountConfig]],
    ) -> list[AssignedAccount]:
        """Assign round-robin across the given account list.

        Each call advances the index by 1 (mod len).
        """
        if len(rr_accounts) == 1:
            i, a = rr_accounts[0]
            return [AssignedAccount(account=a, account_index=i)]

        key = retailer
        current = self._round_robin_index.get(key, 0)
        # Rotate: advance by 1 so each call gives the next account
        selected_idx = current % len(rr_accounts)
        self._round_robin_index[key] = (current + 1) % len(rr_accounts)

        i, a = rr_accounts[selected_idx]
        return [AssignedAccount(account=a, account_index=i)]

    def get_single_account_for_item(
        self,
        item_name: str,
        retailer: str,
    ) -> _AccountConfig | None:
        """Get the single best account for an item (for pre-warming).

        Uses round-robin across matching accounts. Returns None if no accounts
        are available.
        """
        assigned = self.get_accounts_for_item(item_name, retailer)
        if not assigned:
            return None
        return assigned[0].account

    def reset_round_robin(self, retailer: str | None = None) -> None:
        """Reset round-robin state for a retailer or all retailers."""
        if retailer:
            self._round_robin_index.pop(retailer, None)
        else:
            self._round_robin_index.clear()
