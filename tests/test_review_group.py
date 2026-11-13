"""Tests offline del grupo de revisión (sin FastAPI, sin red).

Cubren: guardia de ADMIN_TELEGRAM_IDS, foto + botones en mensajes separados,
idempotencia (una segunda pulsación no vuelve a otorgar Premium), deduplicación
de avisos, motivo obligatorio para rechazar y datos completos de la transferencia.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Stub del Bot API: ningún test toca la red.
calls = []


class FakeTelegram(types.ModuleType):
    def send_message(self, chat_id, text, reply_markup=None):
        calls.append({"method": "sendMessage", "chat_id": chat_id, "text": text, "markup": reply_markup})
        return {"message_id": len(calls), "chat": {"id": chat_id}}

    def send_photo(self, chat_id, photo, filename="c.jpg", caption=""):
        # La API real no acepta reply_markup aquí: si se pasara, este stub fallaría.
        calls.append({"method": "sendPhoto", "chat_id": chat_id, "caption": caption})
        return {"message_id": len(calls), "chat": {"id": chat_id}}

    def bot_api_call(self, method, payload, timeout=8.0):
        calls.append({"method": method, "payload": payload})
        return {}


fake = FakeTelegram("telegram_bot")
sys.modules["telegram_bot"] = fake
import review_group  # noqa: E402


class HTTPError409(Exception):
    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


def make_db(path):
    """Base en archivo: review_group abre y cierra sus propias conexiones."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY, first_name TEXT, username TEXT, payment_phone TEXT);
        CREATE TABLE IF NOT EXISTS payment_operations(
          operation_id TEXT PRIMARY KEY, user_id TEXT, plan TEXT, language TEXT, status TEXT,
          amount TEXT, payment_method TEXT, payer_phone TEXT, destination_account TEXT,
          transaction_id TEXT, transfer_date TEXT, proof_text TEXT, proof_image TEXT,
          created_at TEXT, updated_at TEXT);
        """
    )
    review_group.ensure_schema(conn)
    conn.execute("DELETE FROM payment_operations")
    conn.execute("DELETE FROM users")
    conn.execute("INSERT INTO users VALUES('501','Ana','ana','5352677163')")
    conn.execute(
        "INSERT INTO payment_operations VALUES('OP1','501','monthly','es','proof_submitted','7500 CUP',"
        "'BANDEC','5352677163','1234567890','TX-99','2026-11-12','Transferencia hecha',NULL,"
        "'2026-11-12T10:00:00','2026-11-12T10:00:00')"
    )
    conn.commit()
    conn.close()


class ReviewGroupTests(unittest.TestCase):
    def setUp(self):
        calls.clear()
        self.env = patch.dict(os.environ, {"PAYMENT_ARCHIVE_CHAT_ID": "-100123",
                                           "ADMIN_TELEGRAM_IDS": "777",
                                           "TELEGRAM_MINI_APP_URL": "https://mini.example/app"})
        self.env.start()
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "review.db")
        make_db(self.db_path)
        self.granted = []

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def conn(self):
        """Conexión nueva, como en producción (db() devuelve una por uso)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def status_of(self, operation_id="OP1"):
        conn = self.conn()
        try:
            return conn.execute("SELECT status FROM payment_operations WHERE operation_id=?",
                                (operation_id,)).fetchone()["status"]
        finally:
            conn.close()

    # --- helpers de negocio falsos que imitan los reales (idempotentes) ------
    def verify_payment(self, operation_id, actor):
        conn = self.conn()
        try:
            row = conn.execute("SELECT status,plan FROM payment_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if not row or row["status"] not in {"pending", "proof_submitted"}:
                raise HTTPError409("Operación no verificable o ya procesada")
            conn.execute("UPDATE payment_operations SET status='verified' WHERE operation_id=?", (operation_id,))
            conn.commit()
        finally:
            conn.close()
        self.granted.append(operation_id)
        return {"success": True, "status": "verified"}

    def reject_payment(self, operation_id, actor, reason=""):
        conn = self.conn()
        try:
            row = conn.execute("SELECT status FROM payment_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if not row or row["status"] not in {"pending", "proof_submitted"}:
                raise HTTPError409("Operación ya procesada")
            conn.execute("UPDATE payment_operations SET status='rejected' WHERE operation_id=?", (operation_id,))
            conn.commit()
        finally:
            conn.close()
        return {"success": True, "status": "rejected"}

    def _handle(self, data, admin_id="777"):
        update = {
            "update_id": 1,
            "callback_query": {
                "id": "cb-1",
                "from": {"id": int(admin_id)},
                "data": data,
                "message": {"message_id": 42, "chat": {"id": "-100123"}},
            },
        }
        return review_group.handle_callback(
            update, connect=self.conn,
            verify_payment=self.verify_payment, reject_payment=self.reject_payment,
            review_photo=lambda *a, **k: {"user_id": "501"},
            resolve_report=lambda *a, **k: {"user_id": "501"},
            ad_action=lambda *a, **k: {"owner_user_id": "501", "status": "approved", "reason": ""},
            resolve_referral=lambda *a, **k: {"success": True},
            admins={"777"},
        )

    # --- tests ---------------------------------------------------------------
    def test_admin_guard_blocks_unknown_ids(self):
        with patch.dict(os.environ, {"ADMIN_TELEGRAM_IDS": "777,888"}):
            update = {"callback_query": {"id": "cb", "from": {"id": 999}, "data": "rv1:pay:ok:OP1",
                                         "message": {"message_id": 1, "chat": {"id": -100}}}}
            out = review_group.handle_callback(
                update, connect=self.conn, admins={"777", "888"},
                verify_payment=self.verify_payment, reject_payment=self.reject_payment,
                review_photo=lambda *a, **k: {}, resolve_report=lambda *a, **k: {},
                ad_action=lambda *a, **k: {}, resolve_referral=lambda *a, **k: {},
            )
        self.assertEqual(out["action"], "denied")
        self.assertEqual(self.granted, [])
        alerts = [c for c in calls if c["method"] == "answerCallbackQuery"]
        self.assertTrue(alerts and alerts[0]["payload"]["show_alert"] is True)

    def test_approve_grants_premium_once(self):
        first = self._handle("rv1:pay:ok:OP1")
        second = self._handle("rv1:pay:ok:OP1")
        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertEqual(self.granted, ["OP1"])
        self.assertEqual(self.status_of(), "verified")

    def test_reject_requires_reason_then_applies_it(self):
        out = self._handle("rv1:pay:no:OP1")
        self.assertEqual(out["action"], "reason_requested")
        self.assertEqual(self.status_of(), "proof_submitted")
        pending = review_group.pending_action_for(self.conn, "777", "-100123", "El importe no coincide")
        self.assertEqual(pending["action"], "reject_payment")
        self.assertEqual(pending["reason"], "El importe no coincide")
        review_group.execute_action(
            connect=self.conn, admin_id="777", chat_id="-100123", message_id=42,
            action=pending["action"], target=pending["target"], reason=pending["reason"],
            verify_payment=self.verify_payment, reject_payment=self.reject_payment,
            review_photo=lambda *a, **k: {}, resolve_report=lambda *a, **k: {},
            ad_action=lambda *a, **k: {}, resolve_referral=lambda *a, **k: {},
        )
        self.assertEqual(self.status_of(), "rejected")

    def test_photo_buttons_are_sent_in_a_separate_message(self):
        ok = review_group.notify("photo", {"photo_id": 5, "user_id": "501",
                                           "display_name": "Ana", "image": b"jpeg"}, connect=self.conn)
        self.assertTrue(ok)
        methods = [c["method"] for c in calls]
        self.assertEqual(methods[:2], ["sendPhoto", "sendMessage"])
        # El mensaje con botones es el segundo y sí lleva teclado.
        self.assertIsNotNone(calls[1]["markup"])
        self.assertIn("rv1:photo:ok:5", str(calls[1]["markup"]))

    def test_notices_are_deduplicated(self):
        payload = {"operation_id": "OP1", "phone": "5352677163", "amount": "7500.00",
                   "method": "BANDEC_BPA", "destination": "1234567890", "transaction": "TX-99",
                   "date": "2026-11-12"}
        self.assertTrue(review_group.notify("atajo_granted", payload, connect=self.conn))
        self.assertFalse(review_group.notify("atajo_granted", payload, connect=self.conn))

    def test_unmatched_notice_has_no_grant_buttons(self):
        review_group.notify("atajo_unmatched", {"status": "unmatched", "phone": "5352677163",
                                               "amount": "7500.00", "method": "BANDEC_BPA",
                                               "destination": "1234567890", "transaction": "S/N",
                                               "date": "", "fingerprint": "abc123"},
                            connect=self.conn)
        sent = [c for c in calls if c["method"] == "sendMessage"]
        self.assertTrue(sent)
        self.assertIsNone(sent[-1]["markup"])

    def test_payment_details_include_transfer_data(self):
        text = review_group.payment_details("OP1", connect=self.conn)
        for needle in ("OP1", "Ana", "Mensual", "7500 CUP", "BANDEC", "5352677163",
                       "1234567890", "TX-99", "2026-11-12"):
            self.assertIn(needle, text)

    def test_malformed_callback_is_rejected(self):
        out = self._handle("rv1:pay")
        self.assertEqual(out["action"], "malformed")


if __name__ == "__main__":
    unittest.main()
