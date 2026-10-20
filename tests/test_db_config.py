"""Offline tests for the SQLite connection settings (no web framework required)."""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import db


class ConnectionSettingsTests(unittest.TestCase):
    def test_file_database_uses_wal_and_busy_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            connection = db.connect(path)
            try:
                self.assertEqual(connection.row_factory, sqlite3.Row)
                self.assertEqual(str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower(), "wal")
                timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
                self.assertEqual(int(timeout), db.busy_timeout_ms())
                connection.execute("CREATE TABLE t(x INTEGER)")
                connection.execute("INSERT INTO t VALUES (1)")
                connection.commit()
            finally:
                connection.close()

    def test_busy_timeout_is_configurable(self):
        with patch.dict(os.environ, {"SQLITE_BUSY_TIMEOUT_MS": "2000"}):
            self.assertEqual(db.busy_timeout_ms(), 2000)
        with patch.dict(os.environ, {"SQLITE_BUSY_TIMEOUT_MS": "not-a-number"}):
            self.assertEqual(db.busy_timeout_ms(), db.DEFAULT_BUSY_TIMEOUT_MS)
        with patch.dict(os.environ, {"SQLITE_BUSY_TIMEOUT_MS": "10"}):
            self.assertEqual(db.busy_timeout_ms(), db.MIN_BUSY_TIMEOUT_MS)

    def test_memory_database_is_supported(self):
        connection = db.connect(":memory:")
        try:
            connection.execute("CREATE TABLE t(x INTEGER)")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM t").fetchone()[0], 0)
        finally:
            connection.close()

    def test_check_connection_detects_missing_directory(self):
        with self.assertRaises(sqlite3.Error):
            db.check_connection("/nonexistent-directory-for-tests/liggacuba.db")

    def test_check_connection_detects_an_uninitialised_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "empty.db")
            sqlite3.connect(path).close()
            with self.assertRaises(sqlite3.OperationalError):
                db.check_connection(path)

    def test_check_connection_accepts_an_initialised_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ready.db")
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE users(user_id TEXT PRIMARY KEY)")
            connection.commit()
            connection.close()
            db.check_connection(path)

    def test_is_file_database(self):
        self.assertFalse(db.is_file_database(":memory:"))
        self.assertFalse(db.is_file_database(""))
        self.assertTrue(db.is_file_database("/data/liggacuba.db"))

    def test_locked_error_detection(self):
        self.assertTrue(db.is_locked_error(sqlite3.OperationalError("database is locked")))
        self.assertTrue(db.is_locked_error(sqlite3.OperationalError("database is busy")))
        self.assertFalse(db.is_locked_error(sqlite3.OperationalError("no such table: x")))
        self.assertFalse(db.is_locked_error(ValueError("database is locked")))

    def test_connect_survives_wal_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.db")
            real_connect = sqlite3.connect

            class ExplodingConnection:
                def __init__(self, connection):
                    self._connection = connection

                def __getattr__(self, name):
                    return getattr(self._connection, name)

                def execute(self, sql, *args, **kwargs):
                    if "journal_mode" in sql:
                        raise sqlite3.OperationalError("WAL not supported")
                    return self._connection.execute(sql, *args, **kwargs)

            with patch.object(db.sqlite3, "connect", side_effect=lambda *a, **k: ExplodingConnection(real_connect(*a, **k))):
                connection = db.connect(path)
            try:
                self.assertEqual(connection.execute("SELECT 1").fetchone()[0], 1)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
