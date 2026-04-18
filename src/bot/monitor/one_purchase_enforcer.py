"""One-purchase-per-account enforcement (MAC-T03 / MAC-3).

Per PRD Section 9.10 (MAC-3): same item cannot be purchased by two accounts
in the same drop window. Track purchase state in state.db.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.shared.db import DatabaseManager


class OnePurchaseEnforcer:
    """Enforces the one-purchase-per-account rule per drop window (MAC-3).

    Prevents multiple accounts from purchasing the same item during the same
    drop window. Uses the account_purchases table in state.db.
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def can_purchase(
        self,
        item: str,
        retailer: str,
        drop_window_id: str,
    ) -> bool:
        """Return True if item is available for purchase in this drop window.

        Returns False if the item has already been purchased by another account
        in this drop window.
        """
        return not self._db.has_item_been_purchased_in_window(item, retailer, drop_window_id)

    def record_purchase(
        self,
        item: str,
        retailer: str,
        drop_window_id: str,
        account_index: int,
    ) -> None:
        """Record a successful purchase for this item+retailer+drop_window.

        After this is called, can_purchase() for the same item+retailer+drop_window
        will return False.
        """
        self._db.record_account_purchase(item, retailer, drop_window_id, account_index)

    def get_item_status(
        self,
        item: str,
        retailer: str,
    ) -> str:
        """Return purchase status: 'available', 'purchased', or 'never_purchased'.

        Uses the most recent drop window the item was purchased in.
        """
        window_id = self._db.get_purchase_window_for_item(item, retailer)
        if window_id is None:
            return "never_purchased"
        return "purchased"

    def clear_old_history(self, older_than_days: int = 30) -> int:
        """Clear purchase history older than N days. Returns deleted row count."""
        return self._db.clear_purchase_history(older_than_days)
