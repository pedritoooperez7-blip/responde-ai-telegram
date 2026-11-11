"""Regression tests for LiggaCuba referral attribution and rewards."""
import importlib.util
import sqlite3
import datetime
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "backend" / "referrals.py"
spec = importlib.util.spec_from_file_location("referrals_under_test", MODULE_PATH)
referrals = importlib.util.module_from_spec(spec)
spec.loader.exec_module(referrals)


def database():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE users(
            user_id TEXT PRIMARY KEY, refer_code TEXT, referred_by TEXT,
            updated_at TEXT, premium_until TEXT, first_name TEXT,
            username TEXT, created_at TEXT, payment_phone TEXT
        );
        CREATE TABLE referrals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id TEXT NOT NULL, referred_id TEXT NOT NULL UNIQUE,
            rewarded INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE payment_operations(
            operation_id TEXT PRIMARY KEY, user_id TEXT, plan TEXT,
            status TEXT, verified_at TEXT, created_at TEXT
        );
        INSERT INTO users(user_id,refer_code,updated_at,created_at)
        VALUES('100','REF100','now','2026-11-01');
        INSERT INTO users(user_id,refer_code,updated_at,created_at)
        VALUES('200','REF200','now','2026-11-10');
    """)
    referrals.run_migrations(conn)
    return conn


def test_attribution_is_single_and_idempotent():
    conn = database()
    assert referrals.apply_referral(conn, "200", "REF100", "startapp")["success"]
    assert referrals.apply_referral(conn, "200", "REF100", "manual")["already_registered"]
    assert referrals.apply_referral(conn, "200", "REF200")["error"] == "self_referral"
    assert conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0] == 1


def test_reward_only_once_for_verified_payment():
    conn = database()
    referrals.apply_referral(conn, "200", "REF100")
    now = referrals._now()
    conn.execute(
        "INSERT INTO payment_operations VALUES(?,?,?,?,?,?)",
        ("op-1", "200", "weekly", "verified", now, now),
    )
    conn.execute("UPDATE users SET premium_until=? WHERE user_id='200'", (now,))
    conn.commit()
    referrals.mark_referral_premium_active(conn, "200", "op-1")
    assert referrals.reward_referrer(conn, "200", "op-1") is True
    assert referrals.reward_referrer(conn, "200", "op-1") is False
    assert conn.execute("SELECT rewarded FROM referrals").fetchone()[0] == 1


def test_unverified_payment_cannot_reward():
    conn = database()
    referrals.apply_referral(conn, "200", "REF100")
    now = referrals._now()
    conn.execute(
        "INSERT INTO payment_operations VALUES(?,?,?,?,?,?)",
        ("op-pending", "200", "weekly", "pending", None, now),
    )
    conn.commit()
    assert referrals.reward_referrer(conn, "200", "op-pending") is False
    assert conn.execute("SELECT premium_until FROM users WHERE user_id='100'").fetchone()[0] is None


def test_user_with_prior_verified_payment_cannot_apply_code():
    conn = database()
    now = referrals._now()
    conn.execute(
        "INSERT INTO payment_operations VALUES(?,?,?,?,?,?)",
        ("old-op", "200", "weekly", "verified", now, now),
    )
    conn.commit()
    result = referrals.apply_referral(conn, "200", "REF100")
    assert result["success"] is False
    assert result["error"] == "not_new_user"
    assert conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0] == 0


def test_payment_verified_before_attribution_cannot_reward():
    conn = database()
    now = referrals._now()
    conn.execute(
        "INSERT INTO payment_operations VALUES(?,?,?,?,?,?)",
        ("old-op", "200", "weekly", "verified", now, now),
    )
    conn.commit()
    # Legacy/edge attribution is inserted directly to verify the reward guard.
    earlier = (datetime.datetime.strptime(now, "%Y-%m-%dT%H:%M:%S") + datetime.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "INSERT INTO referrals(referrer_id,referred_id,rewarded,created_at) VALUES(?,?,0,?)",
        ("100", "200", earlier),
    )
    conn.commit()
    referrals.run_migrations(conn)
    referrals.mark_referral_premium_active(conn, "200", "old-op")
    assert referrals.reward_referrer(conn, "200", "old-op") is False
    assert conn.execute("SELECT rewarded FROM referrals").fetchone()[0] == 0


def test_self_referral_blocked():
    conn = database()
    result = referrals.apply_referral(conn, "100", "REF100")
    assert result["success"] is False
    assert result["error"] == "self_referral"


def test_duplicate_code_application_idempotent():
    conn = database()
    r1 = referrals.apply_referral(conn, "200", "REF100", "startapp")
    assert r1["success"] is True
    r2 = referrals.apply_referral(conn, "200", "REF100", "manual")
    assert r2.get("already_registered") or r2["success"] is True
    assert conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0] == 1


def test_code_not_found():
    conn = database()
    result = referrals.apply_referral(conn, "200", "INVALID99")
    assert result["success"] is False
    assert result["error"] == "code_not_found"


def test_ensure_refer_code_generates_unique():
    conn = database()
    code1 = referrals.ensure_refer_code(conn, "300")
    code2 = referrals.ensure_refer_code(conn, "300")
    assert code1 == code2
    assert len(code1) >= 6
    code3 = referrals.ensure_refer_code(conn, "400")
    assert code3 != code1
