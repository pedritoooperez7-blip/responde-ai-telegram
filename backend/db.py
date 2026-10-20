"""SQLite connection helpers with conservative concurrency settings.

The application opens one short-lived connection per request. This module
centralises the settings so every connection waits instead of failing
immediately when another writer holds the lock, and so file-based databases can
use WAL where the filesystem supports it.

WAL requires shared memory and does not work on every network filesystem. If the
PRAGMA fails, the connection keeps SQLite's default journal mode instead of
aborting startup.
"""
from __future__ import annotations

import logging
import os
import sqlite3

logger = logging.getLogger(__name__)

DEFAULT_BUSY_TIMEOUT_MS = 15000
MIN_BUSY_TIMEOUT_MS = 1000


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def busy_timeout_ms() -> int:
    """Lock wait budget in milliseconds (SQLITE_BUSY_TIMEOUT_MS)."""
    return _env_int("SQLITE_BUSY_TIMEOUT_MS", DEFAULT_BUSY_TIMEOUT_MS, MIN_BUSY_TIMEOUT_MS)


def is_file_database(path: str) -> bool:
    """True for an on-disk database; in-memory databases have no shared state."""
    value = (path or "").strip()
    if not value or value == ":memory:":
        return False
    if value.startswith("file:"):
        return "mode=memory" not in value
    return True


def connect(path: str, enable_wal: bool = True) -> sqlite3.Connection:
    """Open a configured connection. Never raises because WAL is unavailable."""
    timeout_ms = busy_timeout_ms()
    connection = sqlite3.connect(path, timeout=timeout_ms / 1000)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(f"PRAGMA busy_timeout={int(timeout_ms)}")
        if enable_wal and is_file_database(path):
            mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()
            if mode and str(mode[0]).lower() != "wal":
                logger.warning("SQLite WAL not enabled for this filesystem (mode=%s); continuing with the default journal", mode[0])
            connection.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error as exc:
        # A read-only or exotic filesystem must not take the service down.
        logger.warning("SQLite tuning skipped: error_type=%s", type(exc).__name__)
    return connection


def is_locked_error(exc: BaseException) -> bool:
    """True when SQLite reports contention rather than a real failure."""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def check_connection(path: str) -> None:
    """Raise if the database cannot be opened, queried or initialised."""
    connection = connect(path, enable_wal=False)
    try:
        connection.execute("SELECT 1").fetchone()
        # An empty or wrong file would open fine but has no application schema;
        # treat that as unavailable so /health catches a bad DB_PATH.
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        if not row:
            raise sqlite3.OperationalError("database schema is not initialised")
    finally:
        connection.close()
