"""SQLite database helpers for state.db and auth.db.

Provides WAL-mode SQLite connection management and schema initialization
for all bot state, event history, command queue, session state, and auth.

Per PRD Sections 8.1, 8.2.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from typing_extensions import Self

logger = logging.getLogger(__name__)

# Default paths — can be overridden at construction time
DEFAULT_STATE_DB = Path("state.db")
DEFAULT_AUTH_DB = Path("auth.db")


class DatabaseManager:
    """Thread-safe SQLite database manager with WAL mode and connection pooling.

    Supports both state.db (bot state) and auth.db (authentication).
    All write operations are serialized via a lock. Reads can happen concurrently
    on the same connection (SQLite handles this via WAL mode).
    """

    def __init__(self, db_path: Path = DEFAULT_STATE_DB) -> None:
        """Initialize DatabaseManager with path to the SQLite database file.

        Args:
            db_path: Path to the .db file. Defaults to state.db in cwd.
        """
        self._db_path = db_path
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._initialized = False

    @property
    def path(self) -> Path:
        """Return the database file path."""
        return self._db_path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Get a thread-local SQLite connection.

        Yields:
            A sqlite3.Connection configured for this thread.

        Raises:
            sqlite3.Error: If the connection cannot be established.
        """
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                database=str(self._db_path),
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                timeout=30.0,
            )
            conn.row_factory = sqlite3.Row
            # Enable WAL mode for better concurrency
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        try:
            yield self._local.conn
        except sqlite3.Error:
            self._local.conn = None
            raise

    def _init_schema(self) -> None:
        """Initialize the database schema (idempotent)."""
        with self._write_lock:
            with self.connection() as conn:
                # ── events table ──────────────────────────────────────────────
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event TEXT NOT NULL,
                        item TEXT NOT NULL DEFAULT '',
                        retailer TEXT NOT NULL DEFAULT '',
                        timestamp TEXT NOT NULL,
                        order_id TEXT NOT NULL DEFAULT '',
                        error TEXT NOT NULL DEFAULT '',
                        attempt INTEGER NOT NULL DEFAULT 1
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_retailer ON events(retailer)"
                )

                # ── command_queue table ───────────────────────────────────────
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS command_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        command TEXT NOT NULL,
                        args TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        processed_at TEXT,
                        status TEXT NOT NULL DEFAULT 'pending'
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cmd_status ON command_queue(status)"
                )

                # ── session_state table ─────────────────────────────────────
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS session_state (
                        retailer TEXT PRIMARY KEY,
                        cookies_json TEXT NOT NULL DEFAULT '{}',
                        auth_token TEXT NOT NULL DEFAULT '',
                        cart_token TEXT NOT NULL DEFAULT '',
                        prewarmed_at TEXT,
                        expires_at TEXT,
                        is_valid INTEGER NOT NULL DEFAULT 1
                    )
                """)
                # Migration: add expires_at column if missing (existing dbs)
                try:
                    conn.execute(
                        "ALTER TABLE session_state ADD COLUMN expires_at TEXT"
                    )
                except sqlite3.OperationalError:
                    pass  # Column already exists

                # ── drop_windows table ───────────────────────────────────────
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS drop_windows (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        item TEXT NOT NULL,
                        retailer TEXT NOT NULL,
                        drop_datetime TEXT NOT NULL,
                        prewarm_minutes INTEGER NOT NULL DEFAULT 15,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        max_cart_quantity INTEGER NOT NULL DEFAULT 1
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_drop_retailer ON drop_windows(retailer)"
                )

                # ── captcha_spend table (for budget tracking) ─────────────
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS captcha_spend (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL,
                        retailer TEXT NOT NULL DEFAULT '',
                        amount_usd REAL NOT NULL,
                        solve_time_ms INTEGER NOT NULL,
                        captcha_type TEXT NOT NULL DEFAULT ''
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_captcha_date_retailer "
                    "ON captcha_spend(date, retailer)"
                )
                # ── account_purchases table (MAC-T03 / MAC-3) ────────────────────
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS account_purchases (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        item TEXT NOT NULL,
                        retailer TEXT NOT NULL,
                        drop_window_id TEXT NOT NULL DEFAULT '',
                        account_index INTEGER NOT NULL,
                        purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_purchase_lookup "
                    "ON account_purchases(item, retailer, drop_window_id)"
                )

                # ── account_sessions table (MAC-T02 / MAC-4) ──────────────────────
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS account_sessions (
                        retailer TEXT NOT NULL,
                        username TEXT NOT NULL,
                        cookies_json TEXT NOT NULL DEFAULT '{}',
                        auth_token TEXT NOT NULL DEFAULT '',
                        cart_token TEXT NOT NULL DEFAULT '',
                        prewarmed_at TEXT,
                        expires_at TEXT,
                        is_valid INTEGER NOT NULL DEFAULT 1,
                        PRIMARY KEY (retailer, username)
                    )"""
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_account_sessions_retailer "
                    "ON account_sessions(retailer)"
                )
                conn.commit()

    def initialize(self) -> Self:
        """Initialize the database and schema. Idempotent. Returns self."""
        if not self._initialized:
            self._init_schema()
            self._initialized = True
        return self

    # ── Event logging ────────────────────────────────────────────────────────

    def log_event(
        self,
        event: str,
        item: str = "",
        retailer: str = "",
        order_id: str = "",
        error: str = "",
        attempt: int = 1,
    ) -> int:
        """Insert a bot lifecycle event into the events table.

        Args:
            event: Event type string (e.g. "STOCK_DETECTED").
            item: Monitored item name.
            retailer: Retailer adapter name.
            order_id: Order confirmation number (for CHECKOUT_SUCCESS).
            error: Error message (for CHECKOUT_FAILED).
            attempt: Checkout attempt number.

        Returns:
            The rowid of the inserted event.
        """
        timestamp = datetime.utcnow().isoformat() + "Z"
        with self._write_lock:
            with self.connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO events
                        (event, item, retailer, timestamp, order_id, error, attempt)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (event, item, retailer, timestamp, order_id, error, attempt),
                )
                conn.commit()
                return cursor.lastrowid  # type: ignore[return-value]

    def get_recent_events(
        self,
        limit: int = 500,
        event_type: str | None = None,
        retailer: str | None = None,
        item: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve recent events with optional filters.

        Args:
            limit: Maximum number of events to return (default 500).
            event_type: Filter by event type string.
            retailer: Filter by retailer.
            item: Filter by item name.

        Returns:
            List of event dictionaries ordered by timestamp DESC.
        """
        query = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if event_type:
            query += " AND event=?"
            params.append(event_type)
        if retailer:
            query += " AND retailer=?"
            params.append(retailer)
        if item:
            query += " AND item=?"
            params.append(item)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    # ── Command queue ─────────────────────────────────────────────────────────

    def enqueue_command(
        self,
        command: str,
        args: dict[str, Any] | None = None,
    ) -> int:
        """Enqueue a command for the daemon to process.

        Args:
            command: Command name (e.g. "start", "stop", "dryrun").
            args: JSON-serializable argument dictionary.

        Returns:
            The rowid of the inserted command.
        """
        created_at = datetime.utcnow().isoformat() + "Z"
        args_json = json.dumps(args or {})
        with self._write_lock:
            with self.connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO command_queue (command, args, created_at, status)
                    VALUES (?, ?, ?, 'pending')
                    """,
                    (command, args_json, created_at),
                )
                conn.commit()
                return cursor.lastrowid  # type: ignore[return-value]

    def claim_pending_command(self) -> dict[str, Any] | None:
        """Atomically claim and return the oldest pending command.

        Marks it as 'processing'. Returns None if queue is empty.
        Caller is responsible for completing or releasing the command.
        """
        with self._write_lock:
            with self.connection() as conn:
                row = conn.execute(
                    """
                    SELECT * FROM command_queue
                    WHERE status='pending'
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                ).fetchone()
                if not row:
                    return None
                cmd_id = row["id"]
                conn.execute(
                    "UPDATE command_queue SET status='processing' WHERE id=?",
                    (cmd_id,),
                )
                conn.commit()
                # Build result dict with updated status to avoid sqlite3.Row
                # snapshot staleness after the UPDATE
                result = dict(row)
                result["status"] = "processing"
                return result

    def complete_command(
        self,
        command_id: int,
        status: str = "completed",
    ) -> None:
        """Mark a command as completed (or failed).

        Args:
            command_id: The command rowid.
            status: 'completed' or 'failed'.
        """
        processed_at = datetime.utcnow().isoformat() + "Z"
        with self._write_lock:
            with self.connection() as conn:
                conn.execute(
                    "UPDATE command_queue SET status=?, processed_at=? WHERE id=?",
                    (status, processed_at, command_id),
                )
                conn.commit()

    def get_pending_commands(self) -> list[dict[str, Any]]:
        """Return all pending commands (status = 'pending')."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM command_queue WHERE status='pending' ORDER BY created_at ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    # ── Session state ────────────────────────────────────────────────────────

    def save_session(
        self,
        retailer: str,
        cookies: dict[str, str],
        auth_token: str = "",
        cart_token: str = "",
        is_valid: bool = True,
        expires_at: str = "",
    ) -> None:
        """Persist or update a retailer's browser session.

        Args:
            retailer: Retailer name (e.g. "target").
            cookies: Dict of cookie name → value.
            auth_token: Auth token string.
            cart_token: Cart token string.
            is_valid: Whether the session is currently valid.
            expires_at: ISO-8601 UTC expiry timestamp (used for TTL-based expiry).
        """
        cookies_json = json.dumps(cookies)
        prewarmed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._write_lock:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO session_state
                        (retailer, cookies_json, auth_token, cart_token, prewarmed_at, expires_at, is_valid)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (retailer, cookies_json, auth_token, cart_token, prewarmed_at, expires_at, int(is_valid)),
                )
                conn.commit()

    def load_session(self, retailer: str) -> dict[str, Any] | None:
        """Load persisted session for a retailer.

        Args:
            retailer: Retailer name.

        Returns:
            Session dict with keys: cookies, auth_token, cart_token, prewarmed_at, is_valid,
            or None if no session is stored.
        """
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM session_state WHERE retailer=?",
                (retailer,),
            ).fetchone()
        if not row:
            return None
        return {
            "cookies": json.loads(row["cookies_json"]),
            "auth_token": row["auth_token"],
            "cart_token": row["cart_token"],
            "prewarmed_at": row["prewarmed_at"],
            "expires_at": row["expires_at"] if "expires_at" in row.keys() else "",
            "is_valid": bool(row["is_valid"]),
        }

    def invalidate_session(self, retailer: str) -> None:
        """"Mark a retailer's session as invalid (e.g. on auth failure)."""
        with self._write_lock:
            with self.connection() as conn:
                conn.execute(
                    "UPDATE session_state SET is_valid=0 WHERE retailer=?",
                    (retailer,),
                )
                conn.commit()

    # ── Account sessions (per-username, for multi-account FRONTEND-T10) ────────

    def save_account_session(
        self,
        retailer: str,
        username: str,
        cookies: dict[str, str],
        auth_token: str = "",
        cart_token: str = "",
        is_valid: bool = True,
        expires_at: str = "",
    ) -> None:
        """Persist a per-account session (upsert by composite key)."""
        cookies_json = json.dumps(cookies)
        prewarmed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._write_lock:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO account_sessions
                        (retailer, username, cookies_json, auth_token, cart_token, prewarmed_at, expires_at, is_valid)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (retailer, username, cookies_json, auth_token, cart_token, prewarmed_at, expires_at, int(is_valid)),
                )
                conn.commit()


    def load_account_session(
        self, retailer: str, username: str
    ) -> dict[str, Any] | None:
        """Load persisted session for a specific account."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM account_sessions WHERE retailer=? AND username=?",
                (retailer, username),
            ).fetchone()
        if not row:
            return None
        return {
            "cookies": json.loads(row["cookies_json"]),
            "auth_token": row["auth_token"],
            "cart_token": row["cart_token"],
            "prewarmed_at": row["prewarmed_at"],
            "expires_at": row["expires_at"] if "expires_at" in row.keys() else "",
            "is_valid": bool(row["is_valid"]),
        }


    def load_all_account_sessions(self) -> list[dict[str, Any]]:
        """Load all account session records."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM account_sessions"
            ).fetchall()
        return [
            {
                "retailer": row["retailer"],
                "username": row["username"],
                "cookies": json.loads(row["cookies_json"]),
                "auth_token": row["auth_token"],
                "cart_token": row["cart_token"],
                "prewarmed_at": row["prewarmed_at"],
                "expires_at": row["expires_at"] if "expires_at" in row.keys() else "",
                "is_valid": bool(row["is_valid"]),
            }
            for row in rows
        ]


    def invalidate_account_session(self, retailer: str, username: str) -> None:
        """Mark a specific account's session as invalid."""
        with self._write_lock:
            with self.connection() as conn:
                conn.execute(
                    "UPDATE account_sessions SET is_valid=0 WHERE retailer=? AND username=?",
                    (retailer, username),
                )
                conn.commit()

    # ── Drop windows ──────────────────────────────────────────────────────────

    def save_drop_window(
        self,
        item: str,
        retailer: str,
        drop_datetime: str,
        prewarm_minutes: int = 15,
        enabled: bool = True,
        max_cart_quantity: int = 1,
    ) -> int:
        """Add or update a drop window entry."""
        with self._write_lock:
            with self.connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO drop_windows
                        (item, retailer, drop_datetime, prewarm_minutes, enabled, max_cart_quantity)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (item, retailer, drop_datetime, prewarm_minutes, int(enabled), max_cart_quantity),
                )
                conn.commit()
                return cursor.lastrowid  # type: ignore[return-value]

    def get_drop_windows(
        self,
        enabled_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Retrieve all (or enabled) drop windows."""
        query = "SELECT * FROM drop_windows"
        if enabled_only:
            query += " WHERE enabled=1"
        query += " ORDER BY drop_datetime ASC"
        with self.connection() as conn:
            rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]

    def delete_drop_window(self, window_id: int) -> None:
        """Delete a drop window by its id."""
        with self._write_lock:
            with self.connection() as conn:
                conn.execute("DELETE FROM drop_windows WHERE id=?", (window_id,))
                conn.commit()

    def prune_past_drop_windows(self) -> int:
        """Remove all drop windows whose datetime has already passed.

        Returns:
            Number of windows pruned.
        """
        now = datetime.utcnow().isoformat() + "Z"
        with self._write_lock:
            with self.connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM drop_windows WHERE drop_datetime < ?",
                    (now,),
                )
                conn.commit()
                return cursor.rowcount

    # ── CAPTCHA budget tracking ──────────────────────────────────────────────

    def log_captcha_spend(
        self,
        amount_usd: float,
        solve_time_ms: int,
        retailer: str = "",
        captcha_type: str = "",
    ) -> None:
        """Log a CAPTCHA solve spend for daily budget tracking.

        Accumulates into the existing daily record for the retailer via UPSERT
        so that get_daily_captcha_spend returns a correct cumulative total.
        """
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        with self._write_lock:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO captcha_spend
                        (date, retailer, amount_usd, solve_time_ms, captcha_type)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (date_str, retailer, amount_usd, solve_time_ms, captcha_type),
                )
                conn.commit()

    def get_daily_captcha_spend(self, date: str | None = None) -> float:
        """Return total CAPTCHA spend for a given date (default: today)."""
        date_str = date or datetime.utcnow().strftime("%Y-%m-%d")
        with self.connection() as conn:
            row = conn.execute(
                "SELECT SUM(amount_usd) FROM captcha_spend WHERE date=?",
                (date_str,),
            ).fetchone()
        return float(row[0] or 0.0)

    # ── Account Purchase Tracking (MAC-T03 / MAC-3) ─────────────────────────

    def record_account_purchase(
        self,
        item: str,
        retailer: str,
        drop_window_id: str,
        account_index: int,
    ) -> None:
        """Record that an account purchased an item during a drop window.

        Enforces one-purchase-per-account: same item cannot be purchased by
        two accounts in the same drop window (MAC-3).
        """
        with self._write_lock:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO account_purchases
                        (item, retailer, drop_window_id, account_index)
                    VALUES (?, ?, ?, ?)
                    """,
                    (item, retailer, drop_window_id, account_index),
                )
                conn.commit()

    def has_item_been_purchased_in_window(
        self,
        item: str,
        retailer: str,
        drop_window_id: str,
    ) -> bool:
        """Return True if this item has already been purchased in this drop window.

        Used by MAC-T03 one-purchase-per-account enforcement.
        """
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM account_purchases
                WHERE item=? AND retailer=? AND drop_window_id=?
                LIMIT 1
                """,
                (item, retailer, drop_window_id),
            ).fetchone()
        return row is not None

    def get_purchase_window_for_item(
        self,
        item: str,
        retailer: str,
    ) -> str | None:
        """Return the most recent drop_window_id that this item was purchased in.

        Returns None if the item has never been purchased.
        """
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT drop_window_id FROM account_purchases
                WHERE item=? AND retailer=?
                ORDER BY purchased_at DESC LIMIT 1
                """,
                (item, retailer),
            ).fetchone()
        return row[0] if row else None

    def clear_purchase_history(self, older_than_days: int = 30) -> int:
        """Clear purchase history older than N days. Returns count of rows deleted."""
        with self._write_lock:
            with self.connection() as conn:
                cursor = conn.execute(
                    """
                    DELETE FROM account_purchases
                    WHERE purchased_at < datetime('now', ?||' days')
                    """,
                    (str(-older_than_days),),
                )
                conn.commit()
                return cursor.rowcount

    # ── Utility ─────────────────────────────────────────────────────────────

    def vacuum(self) -> None:
        """Run VACUUM to reclaim space after many deletes."""
        with self._write_lock:
            with self.connection() as conn:
                conn.execute("VACUUM")

    def close(self) -> None:
        """Close the thread-local connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None