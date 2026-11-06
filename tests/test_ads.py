"""Pruebas offline de anuncios, precios con ahorro y respuestas múltiples (sin FastAPI)."""
import os
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import ads
import payments
import ai_providers


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ads.ensure_schema(conn)
    return conn


class AdPricingTests(unittest.TestCase):
    def test_default_prices(self):
        with patch.dict(os.environ, {}, clear=True):
            p = payments.ad_pricing()
        self.assertEqual([p[k]["amount_value"] for k in ("ad_daily", "ad_weekly", "ad_monthly", "ad_annual")],
                         [750.0, 4500.0, 9000.0, 17500.0])
        self.assertEqual([p[k]["days"] for k in p], [1, 7, 30, 365])

    def test_savings_against_daily(self):
        with patch.dict(os.environ, {}, clear=True):
            p = payments.ad_pricing()
        self.assertEqual(p["ad_daily"]["saved_value"], 0)
        self.assertEqual(p["ad_weekly"]["saved_value"], 750.0)       # 5250 - 4500
        self.assertEqual(p["ad_monthly"]["saved_value"], 13500.0)    # 22500 - 9000
        self.assertEqual(p["ad_annual"]["saved_value"], 256250.0)    # 273750 - 17500
        self.assertEqual(p["ad_monthly"]["saved_percent"], 60)

    def test_env_override_and_plan_helpers(self):
        with patch.dict(os.environ, {"AD_PRICE_WEEKLY": "5000"}, clear=True):
            self.assertEqual(payments.payment_price("ad_weekly"), 5000.0)
        self.assertTrue(payments.is_ad_plan("ad_monthly"))
        self.assertFalse(payments.is_ad_plan("weekly"))
        self.assertEqual(payments.plan_days("ad_monthly"), 30)
        self.assertEqual(payments.plan_days("annual"), 365)
        with self.assertRaises(ValueError):
            payments.validate_plan("ad_forever")

    def test_premium_prices_unchanged(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(payments.payment_price("weekly"), 2500.0)
            self.assertEqual(payments.payment_price("annual"), 15500.0)


class AdValidationTests(unittest.TestCase):
    good = {"business_name": "Café Sol", "title": "2x1 en café", "body": "Todos los martes.",
            "link_url": "https://t.me/cafesol", "image_url": ""}

    def test_valid_fields(self):
        f = ads.validate_fields(self.good)
        self.assertEqual(f["cta"], ads.DEFAULT_CTA)

    def test_dangerous_links_rejected(self):
        for bad in ("javascript:alert(1)", "data:text/html,x", "ftp://x.com/a", "//x.com", "no es url"):
            with self.assertRaises(ads.AdError):
                ads.validate_fields({**self.good, "link_url": bad})

    def test_t_me_shortcut_is_normalized(self):
        f = ads.validate_fields({**self.good, "link_url": "t.me/cafesol"})
        self.assertEqual(f["link_url"], "https://t.me/cafesol")

    def test_image_must_be_https_and_lengths_enforced(self):
        with self.assertRaises(ads.AdError):
            ads.validate_fields({**self.good, "image_url": "http://x.com/a.png"})
        with self.assertRaises(ads.AdError):
            ads.validate_fields({**self.good, "title": "x" * 61})
        with self.assertRaises(ads.AdError):
            ads.validate_fields({**self.good, "body": ""})


class BusinessLifecycleTests(unittest.TestCase):
    def test_cannot_edit_without_plan(self):
        conn = make_db()
        with self.assertRaises(ads.AdError):
            ads.save_business_ad(conn, "42", AdValidationTests.good)

    def test_payment_creates_draft_and_extends_without_losing_days(self):
        conn = make_db()
        first = datetime.fromisoformat(ads.extend_business_subscription(conn, "42", 7, "Café"))
        second = datetime.fromisoformat(ads.extend_business_subscription(conn, "42", 30, "Café"))
        self.assertAlmostEqual((second - first).total_seconds(), 30 * 86400, delta=2)
        self.assertEqual(conn.execute("SELECT COUNT(*) n FROM ads").fetchone()["n"], 1)
        self.assertEqual(conn.execute("SELECT status FROM ads").fetchone()["status"], "draft")

    def test_edit_goes_to_pending_and_is_not_served_until_approved(self):
        conn = make_db()
        ads.extend_business_subscription(conn, "42", 7)
        row = ads.save_business_ad(conn, "42", AdValidationTests.good)
        self.assertEqual(row["status"], "pending")
        self.assertIsNone(ads.pick_ad(conn))
        conn.execute("UPDATE ads SET status='approved'")
        self.assertEqual(ads.pick_ad(conn)["owner_user_id"], "42")
        # Editar de nuevo lo devuelve a revisión y deja de mostrarse.
        ads.save_business_ad(conn, "42", {**AdValidationTests.good, "title": "Otro título"})
        self.assertIsNone(ads.pick_ad(conn))

    def test_expired_business_ad_not_served(self):
        conn = make_db()
        ads.extend_business_subscription(conn, "42", 1)
        ads.save_business_ad(conn, "42", AdValidationTests.good)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        conn.execute("UPDATE ads SET status='approved', paid_until=?", (past,))
        self.assertIsNone(ads.pick_ad(conn))


class AdminAdTests(unittest.TestCase):
    def insert_admin_ad(self, conn, **kw):
        now = ads._now()
        vals = dict(status="approved", active=1, weight=1, ends_at=None)
        vals.update(kw)
        conn.execute("INSERT INTO ads(source,business_name,title,body,link_url,status,active,weight,ends_at,created_at,updated_at) "
                     "VALUES('admin','X','T','B','https://x.com',?,?,?,?,?,?)",
                     (vals["status"], vals["active"], vals["weight"], vals["ends_at"], now, now))

    def test_inactive_paused_and_ended_ads_are_skipped(self):
        conn = make_db()
        self.insert_admin_ad(conn, active=0)
        self.insert_admin_ad(conn, status="paused")
        self.insert_admin_ad(conn, ends_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
        self.assertIsNone(ads.pick_ad(conn))
        self.insert_admin_ad(conn)
        self.assertIsNotNone(ads.pick_ad(conn))

    def test_public_view_hides_internal_fields(self):
        conn = make_db()
        self.insert_admin_ad(conn)
        view = ads.public_view(ads.pick_ad(conn))
        self.assertNotIn("link_url", view)
        self.assertNotIn("owner_user_id", view)


class MultiReplyTests(unittest.TestCase):
    def test_four_replies_parsed(self):
        raw = '{"replies":["Hola, ¿qué tal tu día?","Cuéntame qué hiciste hoy","Te debo un café, ¿cuándo?","Me quedé pensando en lo de ayer"]}'
        out = ai_providers._parse_replies(raw)
        self.assertEqual(len(out["replies"]), 4)
        self.assertEqual(out["reply"], out["replies"][0])
        self.assertEqual(out["alternative"], out["replies"][1])

    def test_duplicates_dropped_and_minimum_two(self):
        out = ai_providers._parse_replies('{"replies":["Hola qué tal todo","Hola qué tal todo","Cuéntame algo nuevo hoy"]}')
        self.assertEqual(len(out["replies"]), 2)
        self.assertIsNone(ai_providers._parse_replies('{"replies":["solo una"]}'))

    def test_legacy_two_reply_format_still_works(self):
        out = ai_providers._parse_replies('{"reply":"Hola, ¿cómo vas?","alternative":"Te estaba esperando por aquí"}')
        self.assertEqual(out["reply"], "Hola, ¿cómo vas?")

    def test_extra_fields_rejected_in_both_formats(self):
        for bad in (
            {"replies": ["Hola qué tal todo", "Cuéntame algo nuevo hoy"], "debug": "x"},
            {"replies": ["Hola qué tal todo", "Cuéntame algo nuevo hoy"], "reply": "a"},
            {"reply": "Hola qué tal todo", "alternative": "Cuéntame algo nuevo hoy", "replies": ["x", "y"]},
            {"reply": "Hola qué tal todo", "alternative": "Cuéntame algo nuevo hoy", "debug": "x"},
        ):
            with self.assertRaises(ValueError):
                ai_providers.validate_reply_schema(bad)

    def test_more_than_four_or_non_string_items_rejected(self):
        five = ["uno distinto aquí", "dos otra cosa", "tres algo más", "cuatro nueva idea", "cinco última frase"]
        with self.assertRaises(ValueError):
            ai_providers.validate_reply_schema({"replies": five})
        with self.assertRaises(ValueError):
            ai_providers.validate_reply_schema({"replies": ["Hola qué tal todo", 5]})

    def test_prompt_asks_for_four(self):
        self.assertIn("CUATRO", ai_providers._build_prompt("coquetear", "chat"))


if __name__ == "__main__":
    unittest.main()
