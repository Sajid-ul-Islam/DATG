"""
SQLite-backed session persistence.

Stores the raw uploaded file bytes (plus filename) per Telegram user so the
loaded dataset survives bot restarts. The parsed DataFrame is cached in memory
by the handlers; this store is the durable source of truth.

If the database cannot be created or accessed (e.g. a read-only serverless
filesystem such as Vercel), the store degrades gracefully to no-op behavior and
the bot continues to work with in-memory-only sessions.
"""
import logging
import sqlite3
import threading
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    user_id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    data BLOB NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


class SessionStore:
    """
    Persists (filename, file bytes) per user id in SQLite.

    Uses a single long-lived connection guarded by a lock; safe for use from
    the bot's async handlers.
    """

    def __init__(self, db_path: str = "bot_sessions.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        try:
            self._conn = sqlite3.connect(
                db_path, timeout=30, check_same_thread=False
            )
            with self._lock:
                self._conn.execute(_SCHEMA)
                self._conn.commit()
        except Exception as e:  # e.g. read-only filesystem on serverless
            logger.warning(
                "SQLite session store unavailable at %r (%s); "
                "sessions will be in-memory only",
                db_path,
                e,
            )
            self._conn = None

    @property
    def available(self) -> bool:
        return self._conn is not None

    def close(self) -> None:
        """Close the underlying database connection (releases file locks)."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> "SessionStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def save(self, user_id: int, filename: str, data: bytes) -> None:
        """Upsert the dataset bytes for a user."""
        if not self.available:
            return
        try:
            with self._lock:
                # ON CONFLICT upsert requires SQLite >= 3.24 (Python 3.9+ bundles newer)
                self._conn.execute(
                    "INSERT INTO sessions (user_id, filename, data) VALUES (?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "filename = excluded.filename, "
                    "data = excluded.data, "
                    "updated_at = datetime('now')",
                    (user_id, filename, data),
                )
                self._conn.commit()
        except Exception as e:
            logger.warning("Failed to persist session for user %s: %s", user_id, e)

    def load(self, user_id: int) -> Optional[Tuple[str, bytes]]:
        """Return (filename, bytes) for a user, or None if no session exists."""
        if not self.available:
            return None
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT filename, data FROM sessions WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            if row is None:
                return None
            return row[0], bytes(row[1])
        except Exception as e:
            logger.warning("Failed to load session for user %s: %s", user_id, e)
            return None

    def clear(self, user_id: int) -> None:
        """Remove the persisted session for a user (e.g. a future /clear command)."""
        if not self.available:
            return
        try:
            with self._lock:
                self._conn.execute(
                    "DELETE FROM sessions WHERE user_id = ?", (user_id,)
                )
                self._conn.commit()
        except Exception as e:
            logger.warning("Failed to clear session for user %s: %s", user_id, e)
