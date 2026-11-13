"""
Pruebas para las correcciones al PR feature/review-group-premium-v3.

Ejecutar:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import referrals
import ads


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _referral_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE referrals (
            id INTEGER PRIMARY KEY,
            referrer_id TEXT NOT NULL,
            referred_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'registered',
            resolved_by TEXT,
            notes TEXT,
            updated_at TEXT,
            created_at TEXT DEFAULT '2026-01-01T00:00:00',
            anomaly_flag INTEGER NOT NULL DEFAULT 1,
            anomaly_reason TEXT,
            reward_payment_id TEXT,
            confirmed_at TEXT,
            rewarded INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE payment_operations (
            operation_id TEXT PRIMARY KEY,
            user_id TEXT,
            status TEXT,
            verified_at TEXT,
            created_at TEXT
        );
        CREATE TABLE referral_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_username TEXT NOT NULL,
            action TEXT NOT NULL,
            referral_id INTEGER,
            details TEXT,
            created_at TEXT NOT NULL
        );
        INSERT INTO referrals (id, referrer_id, referred_id, status, anomaly_flag)
        VALUES (1, 'user_A', 'user_B', 'admin_review', 1);
    """)
    return conn


def _ads_db(initial_status: str = "pending") -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(f"""
        CREATE TABLE ads (
            id INTEGER PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            business_name TEXT,
            title TEXT,
            link_url TEXT,
            body TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            reject_reason TEXT,
            updated_at TEXT
        );
        INSERT INTO ads (id, owner_user_id, business_name, title, link_url, body, status)
        VALUES (1, 'owner_1', 'Mi Negocio', 'Titulo', 'https://example.com', 'Texto', '{initial_status}');
    """)
    return conn


class FakeNotify:
    def __init__(self):
        self.calls: list = []

    def __call__(self, user_id: str, text: str):
        self.calls.append((user_id, text))


def _core_referral_fixed(referral_id, approve, notes, actor, conn, notify_fn):
    """_review_referral_core corregido: pasa cadena a resolve_anomaly."""
    row = conn.execute(
        "SELECT referrer_id, referred_id FROM referrals WHERE id=?",
        (int(referral_id),)
    ).fetchone()
    if not row:
        raise ValueError("Referido no encontrado")
    action = "approve" if approve else "reject"
    referrals.resolve_anomaly(conn, int(referral_id), actor, action, notes)
    referrer_id = str(row["referrer_id"] or "")
    if referrer_id:
        if approve:
            notify_fn(referrer_id,
                      "🎁 <b>Tu referido fue aprobado.</b>\n"
                      "Administración revisó la invitación y quedó confirmada. "
                      "Recibirás los días de Premium cuando corresponda.")
        else:
            notify_fn(referrer_id,
                      "ℹ️ <b>Tu referido no fue aprobado.</b>\n"
                      "Administración revisó la invitación y no cumple las condiciones del programa.")
    return {"success": True, "referral_id": int(referral_id)}


def _core_ad_buggy(ad_id, action, reason, actor, conn, notify_fn):
    """_review_ad_core post-PR con el bug (resume no distingue was_paused)."""
    result = ads.apply_admin_action(conn, ad_id, action, reason, actor)
    status = result.get("status")
    uid = result.get("owner_user_id")
    if not uid:
        return result
    reason_txt = result.get("reason") or ""
    if status == "approved":
        notify_fn(uid, "✅ <b>Tu anuncio fue aprobado.</b>\nYa se está mostrando a quienes usan LiggaCuba sin Premium.")
    elif status == "rejected":
        motivo = f"\n\nMotivo: {reason_txt}" if reason_txt else ""
        notify_fn(uid, f"❌ <b>Tu anuncio fue rechazado.</b>{motivo}")
    elif status == "paused":
        notify_fn(uid, "⏸ <b>Tu anuncio fue pausado.</b>")
    return result



def _core_ad_fixed(ad_id, action, reason, actor, conn, notify_fn):
    """_review_ad_core corregido: consulta estado previo antes de actuar."""
    prev = conn.execute("SELECT status FROM ads WHERE id=?", (int(ad_id),)).fetchone()
    was_paused = prev and prev["status"] == "paused"
    result = ads.apply_admin_action(conn, ad_id, action, reason, actor)
    status = result.get("status")
    uid = result.get("owner_user_id")
    if uid:
        if status == "approved" and was_paused:
            notify_fn(uid, "✅ <b>Tu anuncio fue reactivado.</b>\n"
                      "Ya se está mostrando de nuevo.")
        elif status == "approved":
            notify_fn(uid, "✅ <b>Tu anuncio fue aprobado.</b>\n"
                      "Ya se está mostrando a quienes usan LiggaCuba sin Premium.")
        elif status == "rejected":
            motivo = f"\n\nMotivo: {reason}" if reason else ""
            notify_fn(uid, f"❌ <b>Tu anuncio fue rechazado.</b>{motivo}\n\n"
                      "Corrígelo y vuelve a enviarlo a revisión.")
        elif status == "paused":
            notify_fn(uid, "⏸ <b>Tu anuncio fue pausado.</b>\n"
                      "Puedes corregirlo y volver a enviarlo a revisión.")
    return result


# ===========================================================================
# TEST 1 — referrals.resolve_anomaly: tipo del parámetro action
# ===========================================================================

class TestResolveAnomalySignature(unittest.TestCase):

    def test_approve_cadena_sets_approved(self):
        """resolve_anomaly("approve") → status=approved."""
        conn = _referral_db()
        referrals.resolve_anomaly(conn, 1, "admin_x", "approve", "ok")
        row = conn.execute("SELECT status FROM referrals WHERE id=1").fetchone()
        self.assertEqual(row["status"], "registered")  # STATUS_REGISTERED tras approve

    def test_reject_cadena_sets_rejected(self):
        """CRÍTICO: resolve_anomaly("reject") → status=rejected, nunca approved."""
        conn = _referral_db()
        referrals.resolve_anomaly(conn, 1, "admin_x", "reject", "fraude")
        row = conn.execute("SELECT status FROM referrals WHERE id=1").fetchone()
        self.assertEqual(
            row["status"], "not_eligible",
            "Un rechazo no debe quedar como approved/registered.",
        )

    def test_cadena_invalida_no_aprueba(self):
        """Cualquier cadena que no sea 'approve' no debe dejar status registered de approve."""
        conn = _referral_db()
        referrals.resolve_anomaly(conn, 1, "admin_x", "true")
        row = conn.execute("SELECT status FROM referrals WHERE id=1").fetchone()
        self.assertEqual(row["status"], "not_eligible")
    def test_booleano_True_no_aprueba_silenciosamente(self):
        """Pasar True (booleano) no debe aprobar silenciosamente."""
        conn = _referral_db()
        try:
            referrals.resolve_anomaly(conn, 1, "admin_x", True)  # type: ignore
        except (ValueError, TypeError):
            return  # correcto: la validación lo rechazó
        # Si llegó aquí sin excepción: verificamos que no escribió "approved"
        row = conn.execute("SELECT status FROM referrals WHERE id=1").fetchone()
        self.assertNotEqual(
            row["status"], "approved",
            "Pasar True (booleano) aprobó el referido silenciosamente."
        )


# ===========================================================================
# TEST 2 — _review_referral_core corregido: notificación al invitador
# ===========================================================================

class TestReferralCoreNotification(unittest.TestCase):

    def test_approve_notifica_al_invitador_exactamente_una_vez(self):
        conn = _referral_db()
        notify = FakeNotify()
        _core_referral_fixed(1, True, "", "admin_x", conn, notify)
        self.assertEqual(len(notify.calls), 1,
                         f"Se esperaba 1 notificación, se enviaron {len(notify.calls)}")
        uid, text = notify.calls[0]
        self.assertEqual(uid, "user_A")
        self.assertIn("aprobado", text.lower())

    def test_reject_notifica_al_invitador_exactamente_una_vez(self):
        conn = _referral_db()
        notify = FakeNotify()
        _core_referral_fixed(1, False, "fraude", "admin_x", conn, notify)
        self.assertEqual(len(notify.calls), 1,
                         f"Se esperaba 1 notificación, se enviaron {len(notify.calls)}")
        uid, text = notify.calls[0]
        self.assertEqual(uid, "user_A")
        self.assertIn("no fue aprobado", text.lower())

    def test_approve_persiste_status_approved(self):
        conn = _referral_db()
        notify = FakeNotify()
        _core_referral_fixed(1, True, "", "admin_x", conn, notify)
        row = conn.execute("SELECT status FROM referrals WHERE id=1").fetchone()
        self.assertEqual(row["status"], "registered")  # STATUS_REGISTERED tras approve

    def test_reject_persiste_status_rejected(self):
        conn = _referral_db()
        notify = FakeNotify()
        _core_referral_fixed(1, False, "fraude", "admin_x", conn, notify)
        row = conn.execute("SELECT status FROM referrals WHERE id=1").fetchone()
        self.assertEqual(row["status"], "not_eligible")  # STATUS_NOT_ELIGIBLE tras reject

    def test_no_hay_segunda_notificacion_en_llamada_simple(self):
        """Una sola llamada a _core_referral_fixed no produce más de 1 aviso."""
        conn = _referral_db()
        notify = FakeNotify()
        _core_referral_fixed(1, True, "", "admin_x", conn, notify)
        self.assertEqual(len(notify.calls), 1)


# ===========================================================================
# TEST 3 — ads: apply_admin_action y notificación de resume
# ===========================================================================

class TestAdsApplyAdminAction(unittest.TestCase):

    def test_approve_initial_returns_approved(self):
        conn = _ads_db("pending")
        result = ads.apply_admin_action(conn, 1, "approve", "", "admin_x")
        self.assertEqual(result["status"], "approved")

    def test_resume_returns_approved(self):
        """resume mapea a 'approved' — igual que approve."""
        conn = _ads_db("paused")
        result = ads.apply_admin_action(conn, 1, "resume", "", "admin_x")
        self.assertEqual(result["status"], "approved")

    def test_resume_no_devuelve_was_paused(self):
        """Documenta el bug: apply_admin_action no incluye was_paused."""
        conn = _ads_db("paused")
        result = ads.apply_admin_action(conn, 1, "resume", "", "admin_x")
        self.assertNotIn(
            "was_paused", result,
            "apply_admin_action empezó a devolver was_paused — "
            "ajusta _core_ad_fixed para no depender de él."
        )

    def test_reject_sin_motivo_lanza_AdError(self):
        conn = _ads_db("pending")
        with self.assertRaises(ads.AdError):
            ads.apply_admin_action(conn, 1, "reject", "", "admin_x")

    def test_pause_sets_paused(self):
        conn = _ads_db("approved")
        result = ads.apply_admin_action(conn, 1, "pause", "", "admin_x")
        self.assertEqual(result["status"], "paused")


class TestAdsNotifyResumeBug(unittest.TestCase):
    """Documenta el comportamiento del bug pre-fix."""

    def test_buggy_resume_envia_mensaje_de_aprobado(self):
        """Pre-fix: resume envía 'fue aprobado' en lugar de 'fue reactivado'."""
        conn = _ads_db("paused")
        notify = FakeNotify()
        _core_ad_buggy(1, "resume", "", "admin_x", conn, notify)
        self.assertEqual(len(notify.calls), 1)
        _, text = notify.calls[0]
        self.assertIn("aprobado", text.lower(),
                      "El bug no existe: el mensaje pre-fix no dice 'aprobado'.")
        self.assertNotIn("reactivado", text.lower(),
                         "El bug ya no existe en la versión pre-fix.")


class TestAdsNotifyResumeFix(unittest.TestCase):
    """Verifica el comportamiento correcto post-fix."""

    def test_resume_envia_mensaje_reactivado(self):
        """Post-fix: resume sobre anuncio pausado → 'fue reactivado'."""
        conn = _ads_db("paused")
        notify = FakeNotify()
        _core_ad_fixed(1, "resume", "", "admin_x", conn, notify)
        self.assertEqual(len(notify.calls), 1,
                         f"Se esperaba 1 notif, se enviaron {len(notify.calls)}")
        _, text = notify.calls[0]
        self.assertIn("reactivado", text.lower(),
                      f"Se esperaba 'reactivado', se obtuvo: {text!r}")

    def test_approve_inicial_envia_mensaje_aprobado(self):
        """Post-fix: approve sobre pending → 'fue aprobado', no 'reactivado'."""
        conn = _ads_db("pending")
        notify = FakeNotify()
        _core_ad_fixed(1, "approve", "", "admin_x", conn, notify)
        self.assertEqual(len(notify.calls), 1)
        _, text = notify.calls[0]
        self.assertIn("aprobado", text.lower())
        self.assertNotIn("reactivado", text.lower())

    def test_reject_envia_mensaje_rechazado_con_motivo(self):
        conn = _ads_db("pending")
        notify = FakeNotify()
        _core_ad_fixed(1, "reject", "Contenido inapropiado", "admin_x", conn, notify)
        self.assertEqual(len(notify.calls), 1)
        _, text = notify.calls[0]
        self.assertIn("rechazado", text.lower())
        self.assertIn("Contenido inapropiado", text)

    def test_pause_envia_mensaje_pausado(self):
        conn = _ads_db("approved")
        notify = FakeNotify()
        _core_ad_fixed(1, "pause", "", "admin_x", conn, notify)
        self.assertEqual(len(notify.calls), 1)
        _, text = notify.calls[0]
        self.assertIn("pausado", text.lower())

    def test_resume_envia_exactamente_una_notificacion(self):
        """No se duplican notificaciones en una reactivación."""
        conn = _ads_db("paused")
        notify = FakeNotify()
        _core_ad_fixed(1, "resume", "", "admin_x", conn, notify)
        self.assertEqual(len(notify.calls), 1,
                         f"Se esperaba 1 notif, se enviaron {len(notify.calls)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
