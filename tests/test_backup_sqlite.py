"""Offline tests for the SQLite backup script (never touches a real database)."""
import hashlib
import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup_sqlite.py"
spec = importlib.util.spec_from_file_location("backup_sqlite", SCRIPT)
backup_sqlite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup_sqlite)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "source.db")
        connection = sqlite3.connect(self.db_path)
        connection.execute("CREATE TABLE users(id TEXT PRIMARY KEY, name TEXT)")
        connection.execute("INSERT INTO users VALUES ('1', 'Ana')")
        connection.commit()
        connection.close()
        self.out = os.path.join(self.tmp.name, "backups")

    def test_backup_copies_rows_and_verifies_integrity(self):
        destination = backup_sqlite.backup(self.db_path, self.out)
        self.assertTrue(destination.is_file())
        copy = sqlite3.connect(str(destination))
        try:
            self.assertEqual(copy.execute("SELECT name FROM users WHERE id='1'").fetchone()[0], "Ana")
            self.assertEqual(copy.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            copy.close()

    def test_source_file_is_not_modified(self):
        before = sha256(self.db_path)
        backup_sqlite.backup(self.db_path, self.out)
        self.assertEqual(sha256(self.db_path), before)

    def test_existing_backups_are_never_overwritten(self):
        first = backup_sqlite.backup(self.db_path, self.out, timestamp=1700000000)
        second = backup_sqlite.backup(self.db_path, self.out, timestamp=1700000000)
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())

    def test_keep_prunes_only_older_script_backups(self):
        unrelated = Path(self.out) / "manual-note.db"
        Path(self.out).mkdir(parents=True, exist_ok=True)
        unrelated.write_bytes(b"keep me")
        for offset in range(3):
            backup_sqlite.backup(self.db_path, self.out, timestamp=1700000000 + offset, keep=1)
        remaining = list(Path(self.out).glob("liggacuba-*.db"))
        self.assertEqual(len(remaining), 1)
        self.assertTrue(unrelated.is_file())

    def test_missing_source_raises(self):
        with self.assertRaises(FileNotFoundError):
            backup_sqlite.backup(os.path.join(self.tmp.name, "missing.db"), self.out)

    def test_main_returns_error_for_missing_source(self):
        self.assertEqual(backup_sqlite.main(["--db", os.path.join(self.tmp.name, "missing.db"), "--out-dir", self.out]), 1)

    def test_backup_works_with_wal_source(self):
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO users VALUES ('2', 'Luis')")
        connection.commit()
        destination = backup_sqlite.backup(self.db_path, self.out)
        connection.close()
        copy = sqlite3.connect(str(destination))
        try:
            self.assertEqual(copy.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)
        finally:
            copy.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
