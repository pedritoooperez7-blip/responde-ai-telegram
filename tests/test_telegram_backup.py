import gzip, os, sqlite3, sys, tempfile, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
import telegram_backup as tb


def _make_db():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "t.db")
    c = sqlite3.connect(path)
    c.execute("create table users(id text)")
    c.execute("insert into users values('42')")
    c.commit(); c.close()
    return path


class TelegramBackupTests(unittest.TestCase):
    def test_plain_backup_is_valid_gzip_sqlite(self):
        db = _make_db()
        sent = {}
        def fake(chat, payload, name, caption):
            sent.update(chat=chat, payload=payload, name=name, caption=caption); return {"message_id": 1}
        with patch.dict(os.environ, {"BACKUP_ENCRYPTION_KEY": ""}):
            self.assertTrue(tb.run_backup_once(db, fake, "-1001"))
        self.assertTrue(sent["name"].endswith(".db.gz"))
        raw = gzip.decompress(sent["payload"])
        self.assertTrue(raw.startswith(b"SQLite format 3"))

    def test_encrypted_backup_hides_content_and_roundtrips(self):
        db = _make_db()
        sent = {}
        def fake(chat, payload, name, caption):
            sent.update(payload=payload, name=name); return {"message_id": 1}
        with patch.dict(os.environ, {"BACKUP_ENCRYPTION_KEY": "k" * 40}):
            self.assertTrue(tb.run_backup_once(db, fake, "-1001"))
            self.assertTrue(sent["name"].endswith(".enc"))
            self.assertNotIn(b"SQLite format 3", sent["payload"])
            plain = gzip.decompress(tb._fernet().decrypt(sent["payload"]))
        self.assertTrue(plain.startswith(b"SQLite format 3"))

    def test_no_chat_means_no_backup(self):
        db = _make_db()
        with patch.dict(os.environ, {"BACKUP_CHAT_ID": "", "PAYMENT_ARCHIVE_CHAT_ID": ""}):
            self.assertFalse(tb.run_backup_once(db, lambda *a: {"message_id": 1}))

    def test_missing_message_id_is_an_error(self):
        db = _make_db()
        with self.assertRaises(RuntimeError):
            tb.run_backup_once(db, lambda *a: {}, "-1001")

    def test_worker_disabled_without_token(self):
        db = _make_db()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "BACKUP_CHAT_ID": "-1"}), patch.object(tb, "_started", False):
            self.assertFalse(tb.start_backup_worker(db, lambda *a: {}))

    def test_interval_has_floor_and_default(self):
        with patch.dict(os.environ, {"BACKUP_INTERVAL_HOURS": ""}):
            self.assertEqual(tb.interval_seconds(), 6 * 3600)
        with patch.dict(os.environ, {"BACKUP_INTERVAL_HOURS": "0"}):
            self.assertEqual(tb.interval_seconds(), 900)


if __name__ == "__main__":
    unittest.main()
