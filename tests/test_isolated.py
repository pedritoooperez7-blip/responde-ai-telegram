"""Isolated regression/security tests. Uses only a temporary SQLite database and dummy secrets."""
import base64
import io
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TMP = tempfile.TemporaryDirectory(prefix="responde-ai-tests-")
os.environ["DB_PATH"] = str(Path(TMP.name) / "test.sqlite3")
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-telegram-token-for-tests"
os.environ["ADMIN_KEY"] = "dummy-admin-key-for-tests"
os.environ["ATAJO_KEY"] = "dummy-atajo-key-for-tests"
os.environ["BANDEC_ACCOUNT"] = "9244069990684435"
os.environ["BPA_ACCOUNT"] = "1234567890123456"

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)


def auth(uid="test-user"):
    main.user(uid)
    return {"Authorization": "Bearer " + main.session_token(uid)}


class TestHardening(unittest.TestCase):
    def test_health(self):
        self.assertEqual(client.get("/health").status_code, 200)

    def test_usage_requires_auth(self):
        self.assertEqual(client.post("/api/usage", json={"user_id":"victim"}).status_code, 401)

    def test_user_id_body_cannot_override_token(self):
        headers = auth("owner-test")
        r = client.post("/api/profile", headers=headers, json={"user_id":"victim"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["user_id"], "owner-test")

    def test_free_limit_under_concurrency(self):
        uid = "concurrent-user"
        headers = auth(uid)
        payload = {"user_id":uid,"module":"chat","mode":"coquetear"}
        def run(_):
            return client.post("/api/analyze", headers=headers, json=payload).status_code
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(run, range(8)))
        self.assertEqual(statuses.count(200), 3, statuses)
        self.assertEqual(statuses.count(403), 5, statuses)

    def test_phone_prefix_is_normalized(self):
        headers = auth("phone-user")
        r = client.post("/api/payment-phone", headers=headers, json={"phone":"+53 52677163"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["payment_phone"], "52677163")

    def test_phone_invalid_rejected(self):
        self.assertEqual(client.post("/api/payment-phone", headers=auth("phone-bad"), json={"phone":"123"}).status_code, 400)

    def test_ocr_requires_auth(self):
        self.assertEqual(client.post("/ocr", content=b"bad-image").status_code, 401)

    def test_ocr_rejects_invalid_image_safely(self):
        r = client.post("/ocr", headers=auth("ocr-user"), content=b"not an image")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "Imagen inválida o dañada")

    def test_ocr_stream_size_limit(self):
        r = client.post("/ocr", headers=auth("ocr-large"), content=b"x" * (8 * 1024 * 1024 + 1))
        self.assertEqual(r.status_code, 413)

    def test_base64_ocr_size_limit(self):
        oversized = base64.b64encode(b"x" * (8 * 1024 * 1024 + 1)).decode()
        r = client.post("/ocr-base64", json={"image":oversized})
        self.assertEqual(r.status_code, 413)

    def test_diagnostic_requires_secret(self):
        self.assertEqual(client.post("/api/atajo-diagnostico", content=b"x").status_code, 401)
        r = client.post("/api/atajo-diagnostico", headers={"x-atajo-key":os.environ["ATAJO_KEY"]}, content=b"hello")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["bytes_recibidos"], 5)

    def test_bank_shortcut_verifies_one_matching_operation(self):
        uid = "bank-clean"
        headers = auth(uid)
        self.assertEqual(client.post("/api/payment-phone", headers=headers, json={"phone":"52677163"}).status_code, 200)
        p = client.post("/api/payments/pending", headers=headers, json={"user_id":uid,"plan":"weekly","language":"es","payment_method":"BANDEC"})
        self.assertEqual(p.status_code, 200, p.text)
        operation_id = p.json()["operation_id"]
        r = client.post("/api/atajo-pago", headers={"x-atajo-key":os.environ["ATAJO_KEY"]}, json={
            "metodo_pago":"BANDEC", "telefono_origen":"52677163", "cuenta_destino":"9244069990684435",
            "monto_recibido":2500, "transaccion":"TX-UNIQUE-001", "fecha":"2026-10-09"
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json().get("status"), "verified", r.json())
        c = main.db()
        payment = c.execute("SELECT status,transaction_id FROM payment_operations WHERE operation_id=?", (operation_id,)).fetchone()
        premium_until = c.execute("SELECT premium_until FROM users WHERE user_id=?", (uid,)).fetchone()[0]
        c.close()
        self.assertEqual(payment["status"], "verified")
        self.assertEqual(payment["transaction_id"], "TX-UNIQUE-001")
        self.assertTrue(premium_until)

    def test_duplicate_bank_transaction_does_not_grant_again(self):
        # Replaying the exact same transaction is idempotently rejected as duplicate.
        payload = {"metodo_pago":"BANDEC", "telefono_origen":"52677163", "cuenta_destino":"9244069990684435", "monto_recibido":2500, "transaccion":"TX-UNIQUE-001", "fecha":"2026-10-09"}
        r = client.post("/api/atajo-pago", headers={"x-atajo-key":os.environ["ATAJO_KEY"]}, json=payload)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("status"), "duplicate")

    def test_static_assets(self):
        for path in ("/", "/app.js", "/style.css", "/admin.html", "/privacy.html", "/terms.html"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
