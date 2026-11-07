"""Pruebas offline de limpieza automática, baneo y almacenamiento R2 (sin FastAPI ni red)."""
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import ads
import cleanup
import dating
import storage

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def stamp(days=0, hours=0):
    return (NOW - timedelta(days=days, hours=hours)).replace(tzinfo=None).isoformat()


def make_db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE users(user_id TEXT PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, premium_until TEXT,
      payment_phone TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, usage_today INTEGER NOT NULL DEFAULT 0,
      last_reset_date TEXT NOT NULL DEFAULT '');
    CREATE TABLE usage_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, used_at TEXT, module TEXT, mode TEXT, premium_used INTEGER DEFAULT 0);
    CREATE TABLE saved_situations(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, ocr_text TEXT, reply TEXT, created_at TEXT NOT NULL);
    CREATE TABLE analysis_attempts(id TEXT PRIMARY KEY, user_id TEXT NOT NULL);
    CREATE TABLE ai_idempotency(user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL);
    CREATE TABLE ai_generation_events(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT);
    CREATE TABLE payment_operations(operation_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, status TEXT NOT NULL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, cancelled_at TEXT);
    """)
    dating.init_schema(c)
    ads.ensure_schema(c)
    cleanup.ensure_schema(c)
    return c


def add_user(c, uid, created_days=100, active_days=100, premium_days=None):
    premium = stamp(days=-premium_days) if premium_days is not None else None
    c.execute("INSERT INTO users(user_id,created_at,updated_at,premium_until) VALUES(?,?,?,?)",
              (uid, stamp(created_days), stamp(active_days), premium))
    c.commit()


def add_profile(c, uid, public_id, gender="mujer"):
    c.execute("INSERT INTO dating_profiles(user_id,public_id,display_name,birth_date,gender,looking_for,province,accepted_terms_at,created_at,updated_at) "
              "VALUES(?,?,?,?,?,?,?,?,?,?)", (uid, public_id, "Ana", "2000-01-01", gender, "todos", "Cuba", stamp(5), stamp(5), stamp(5)))
    c.commit()


def has_user(c, uid):
    return c.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone() is not None


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.c = make_db()
        self.dir = tempfile.mkdtemp()
        # Un usuario "con uso" para que no se confunda con un fantasma.
        self.cfg = {"enabled": True, "dry_run": False}

    def run_cleanup(self, **kw):
        return cleanup.run_cleanup(self.c, self.dir, now=NOW, config=self.cfg, **kw)

    def use(self, uid, days_ago):
        self.c.execute("INSERT INTO usage_logs(user_id,used_at,module,mode) VALUES(?,?,?,?)", (uid, stamp(days_ago), "chat", "x"))
        self.c.commit()

    def test_inactive_30_days_is_deleted_with_their_data(self):
        add_user(self.c, "old", active_days=31)
        self.use("old", 31)
        self.c.execute("INSERT INTO saved_situations(user_id,ocr_text,reply,created_at) VALUES('old','a','b',?)", (stamp(40),))
        self.c.commit()
        r = self.run_cleanup()
        self.assertEqual(r["inactive"], 1)
        self.assertFalse(has_user(self.c, "old"))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM saved_situations WHERE user_id='old'").fetchone()[0], 0)

    def test_29_days_inactive_is_kept(self):
        add_user(self.c, "recent", active_days=29)
        self.use("recent", 29)
        self.run_cleanup()
        self.assertTrue(has_user(self.c, "recent"))

    def test_recent_usage_log_keeps_user_even_if_updated_at_is_old(self):
        add_user(self.c, "u", active_days=90)
        self.use("u", 2)
        self.run_cleanup()
        self.assertTrue(has_user(self.c, "u"))

    def test_active_premium_is_never_deleted(self):
        add_user(self.c, "vip", active_days=90, premium_days=10)
        self.use("vip", 90)
        self.run_cleanup()
        self.assertTrue(has_user(self.c, "vip"))

    def test_active_business_ad_plan_and_open_payment_protect_user(self):
        add_user(self.c, "biz", active_days=90)
        self.use("biz", 90)
        self.c.execute("INSERT INTO ads(source,owner_user_id,status,paid_until,created_at,updated_at) VALUES('business','biz','approved',?,?,?)",
                       (stamp(days=-5), stamp(60), stamp(60)))
        add_user(self.c, "paying", active_days=90)
        self.use("paying", 90)
        self.c.execute("INSERT INTO payment_operations(operation_id,user_id,status,created_at,updated_at) VALUES('op1','paying','proof_submitted',?,?)",
                       (stamp(1), stamp(1)))
        self.c.commit()
        self.run_cleanup()
        self.assertTrue(has_user(self.c, "biz"))
        self.assertTrue(has_user(self.c, "paying"))

    def test_admins_are_protected(self):
        add_user(self.c, "777", active_days=90)
        self.use("777", 90)
        self.run_cleanup(protected={"777"})
        self.assertTrue(has_user(self.c, "777"))

    def test_ghost_bot_deleted_after_7_days_but_not_before(self):
        add_user(self.c, "bot", created_days=8, active_days=8)
        add_user(self.c, "newbie", created_days=3, active_days=3)
        r = self.run_cleanup()
        self.assertEqual(r["ghost"], 1)
        self.assertFalse(has_user(self.c, "bot"))
        self.assertTrue(has_user(self.c, "newbie"))

    def test_ghost_with_dating_profile_is_not_ghost(self):
        add_user(self.c, "dater", created_days=10, active_days=10)
        add_profile(self.c, "dater", "p1")
        self.assertEqual(cleanup.find_ghost_users(self.c, stamp(7), set(), 50), [])

    def test_ban_blocks_then_data_deleted_after_48h_but_ban_record_stays(self):
        add_user(self.c, "bad", active_days=0)
        self.use("bad", 0)
        cleanup.ban_user(self.c, "bad", "admin", "spam", now=NOW - timedelta(hours=49))
        self.assertTrue(cleanup.is_banned(self.c, "bad"))
        r = self.run_cleanup()
        self.assertEqual(r["banned"], 1)
        self.assertFalse(has_user(self.c, "bad"))
        self.assertTrue(cleanup.is_banned(self.c, "bad"))  # no puede volver como usuario nuevo
        row = self.c.execute("SELECT data_deleted_at FROM user_bans WHERE user_id='bad'").fetchone()
        self.assertIsNotNone(row["data_deleted_at"])

    def test_ban_within_48h_keeps_data_and_unban_saves_it(self):
        add_user(self.c, "maybe", active_days=0)
        self.use("maybe", 0)
        cleanup.ban_user(self.c, "maybe", "admin", now=NOW - timedelta(hours=10))
        self.run_cleanup()
        self.assertTrue(has_user(self.c, "maybe"))
        self.assertTrue(cleanup.unban_user(self.c, "maybe"))
        self.assertFalse(cleanup.is_banned(self.c, "maybe"))
        self.assertFalse(cleanup.unban_user(self.c, "maybe"))
        self.run_cleanup()
        self.assertTrue(has_user(self.c, "maybe"))

    def test_ban_hides_dating_profile(self):
        add_user(self.c, "d", active_days=0)
        add_profile(self.c, "d", "p2")
        cleanup.ban_user(self.c, "d", "admin", now=NOW)
        self.assertEqual(self.c.execute("SELECT visible FROM dating_profiles WHERE user_id='d'").fetchone()[0], 0)

    def test_pending_payments_cancelled_after_3_days_and_old_logs_removed(self):
        add_user(self.c, "p", active_days=0)
        self.use("p", 0)
        self.use("p", 70)
        for oid, status, age in (("a", "pending", 4), ("b", "pending", 1), ("c", "proof_submitted", 10)):
            self.c.execute("INSERT INTO payment_operations(operation_id,user_id,status,created_at,updated_at) VALUES(?,?,?,?,?)", (oid, "p", status, stamp(age), stamp(age)))
        self.c.commit()
        r = self.run_cleanup()
        st = {x["operation_id"]: x["status"] for x in self.c.execute("SELECT operation_id,status FROM payment_operations")}
        self.assertEqual(st, {"a": "cancelled", "b": "pending", "c": "proof_submitted"})
        # Por defecto NO se purgan los registros de uso (alimentan los contadores del perfil).
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM usage_logs WHERE user_id='p'").fetchone()[0], 2)
        self.cfg["usage_log_days"] = 60
        self.assertEqual(self.run_cleanup()["usage_logs"], 1)

    def test_payment_history_is_kept_when_user_is_deleted(self):
        add_user(self.c, "gone", active_days=60)
        self.use("gone", 60)
        self.c.execute("INSERT INTO payment_operations(operation_id,user_id,status,created_at,updated_at) VALUES('z','gone','verified',?,?)", (stamp(90), stamp(90)))
        self.c.commit()
        self.run_cleanup()
        self.assertFalse(has_user(self.c, "gone"))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM payment_operations WHERE user_id='gone'").fetchone()[0], 1)

    def test_dry_run_deletes_nothing(self):
        add_user(self.c, "old", active_days=60)
        self.use("old", 60)
        self.cfg["dry_run"] = True
        r = self.run_cleanup()
        self.assertEqual(r["inactive"], 1)
        self.assertTrue(has_user(self.c, "old"))

    def test_disabled_does_nothing_and_cap_is_respected(self):
        for i in range(5):
            add_user(self.c, f"o{i}", active_days=60)
            self.use(f"o{i}", 60)
        self.cfg["max_users_per_run"] = 2
        r = self.run_cleanup()
        self.assertEqual(r["inactive"], 2)
        self.cfg["enabled"] = False
        self.assertTrue(self.run_cleanup().get("disabled"))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM users").fetchone()[0], 3)

    def test_delete_user_data_removes_photo_files_on_disk(self):
        add_user(self.c, "ph", active_days=0)
        add_profile(self.c, "ph", "p3")
        self.c.execute("INSERT INTO dating_photos(user_id,filename,position,status,created_at) VALUES('ph','abc.jpg',0,'approved',?)", (stamp(1),))
        self.c.commit()
        path = os.path.join(self.dir, "abc.jpg")
        Path(path).write_bytes(b"x")
        cleanup.delete_user_data(self.c, "ph", self.dir)
        self.assertFalse(os.path.exists(path))
        self.assertFalse(has_user(self.c, "ph"))


class StorageTests(unittest.TestCase):
    def test_disabled_without_env(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(storage.enabled())
            self.assertFalse(storage.put("a.jpg", b"x"))
            self.assertIsNone(storage.get("a.jpg"))
            self.assertFalse(storage.delete("a.jpg"))

    def test_add_photo_falls_back_to_disk_when_r2_unavailable(self):
        c = make_db()
        d = tempfile.mkdtemp()
        add_profile(c, "1", "p9")
        with patch.dict(os.environ, {}, clear=True):
            out = dating.add_photo(c, "1", d, b"jpegdata")
        name = c.execute("SELECT filename FROM dating_photos WHERE id=?", (out["id"],)).fetchone()[0]
        self.assertTrue(os.path.isfile(os.path.join(d, name)))

    def test_add_photo_goes_to_r2_when_configured(self):
        c = make_db()
        d = tempfile.mkdtemp()
        add_profile(c, "1", "p9")
        uploaded = {}
        with patch.object(storage, "put", side_effect=lambda n, b, *a: uploaded.setdefault(n, b) is not None):
            out = dating.add_photo(c, "1", d, b"jpegdata")
        name = c.execute("SELECT filename FROM dating_photos WHERE id=?", (out["id"],)).fetchone()[0]
        self.assertEqual(uploaded[name], b"jpegdata")
        self.assertFalse(os.path.exists(os.path.join(d, name)))  # no ocupa disco

    def test_remove_file_also_deletes_from_r2_and_read_prefers_disk(self):
        d = tempfile.mkdtemp()
        Path(d, "old.jpg").write_bytes(b"disk")
        with patch.object(storage, "delete") as deleted, patch.object(storage, "get", return_value=b"cloud"):
            self.assertEqual(dating.read_photo_bytes(d, "old.jpg"), b"disk")
            self.assertEqual(dating.read_photo_bytes(d, "new.jpg"), b"cloud")
            dating._remove_file(d, "old.jpg")
            deleted.assert_called_once_with("old.jpg")
        self.assertFalse(os.path.exists(os.path.join(d, "old.jpg")))


if __name__ == "__main__":
    unittest.main()
