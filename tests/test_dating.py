"""Pruebas offline de LiggaCuba Citas (no requieren FastAPI ni red).

Cubren la lógica de negocio: mayoría de edad, compatibilidad, límites diarios,
match mutuo, contactos externos (sin chat interno), bloqueos, reportes,
moderación de fotos y privacidad.
"""
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import dating  # noqa: E402

SECRET = "s" * 40
TODAY = date(2026, 11, 2)


def make_db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE users(user_id TEXT PRIMARY KEY, username TEXT)")
    dating.init_schema(c)
    return c


def base_profile(**over):
    data = {
        "display_name": "Ana", "birth_date": "2000-05-10", "gender": "mujer", "looking_for": "hombres",
        "province": "La Habana", "municipality": "Plaza", "bio": "Me gusta la música",
        "interests": ["Música", "Playa"], "min_age": 18, "max_age": 60, "whatsapp": "",
        "share_telegram": True, "confirm_adult": True, "accept_terms": True,
    }
    data.update(over)
    return data


def create_user(c, uid, username="user_name", approved=True, photos_dir=None, **over):
    c.execute("INSERT OR REPLACE INTO users(user_id,username) VALUES(?,?)", (uid, username))
    cleaned = dating.clean_profile(base_profile(**over), username, today=TODAY)
    dating.upsert_profile(c, uid, cleaned)
    c.execute("INSERT INTO dating_photos(user_id,filename,position,status,created_at) VALUES(?,?,?,?,?)",
              (uid, f"{uid}.jpg", 0, "approved" if approved else "pending", dating._now()))
    c.commit()
    return dating.get_profile(c, uid)["public_id"]


class ProfileValidationTests(unittest.TestCase):
    def test_minor_is_rejected(self):
        with self.assertRaises(dating.DatingError) as ctx:
            dating.clean_profile(base_profile(birth_date="2010-01-01"), "user_name", today=TODAY)
        self.assertEqual(ctx.exception.code, "underage")
        self.assertEqual(ctx.exception.status, 403)

    def test_exactly_18_today_is_allowed_and_day_before_is_not(self):
        dating.clean_profile(base_profile(birth_date="2008-11-02"), "user_name", today=TODAY)
        with self.assertRaises(dating.DatingError):
            dating.clean_profile(base_profile(birth_date="2008-11-03"), "user_name", today=TODAY)

    def test_adult_and_terms_confirmation_required_on_creation_only(self):
        with self.assertRaises(dating.DatingError):
            dating.clean_profile(base_profile(confirm_adult=False), "user_name", today=TODAY)
        with self.assertRaises(dating.DatingError):
            dating.clean_profile(base_profile(accept_terms=False), "user_name", today=TODAY)
        dating.clean_profile(base_profile(confirm_adult=False, accept_terms=False), "user_name", existing=True, today=TODAY)

    def test_requires_an_external_contact_channel(self):
        with self.assertRaises(dating.DatingError) as ctx:
            dating.clean_profile(base_profile(share_telegram=False, whatsapp=""), "user_name", today=TODAY)
        self.assertIn("Telegram o WhatsApp", ctx.exception.message)

    def test_telegram_sharing_needs_a_username(self):
        with self.assertRaises(dating.DatingError):
            dating.clean_profile(base_profile(share_telegram=True), "", today=TODAY)
        ok = dating.clean_profile(base_profile(share_telegram=False, whatsapp="52677163"), "", today=TODAY)
        self.assertEqual(ok["whatsapp"], "5352677163")

    def test_links_and_handles_are_not_allowed_in_free_text(self):
        for text in ("escríbeme a t.me/alguien", "mira https://x.com", "wa.me/535", "mi insta @maria_01"):
            with self.assertRaises(dating.DatingError, msg=text):
                dating.clean_profile(base_profile(bio=text), "user_name", today=TODAY)

    def test_invalid_choices_and_age_range(self):
        for field, value in (("gender", "x"), ("looking_for", "x"), ("province", "Marte")):
            with self.assertRaises(dating.DatingError):
                dating.clean_profile(base_profile(**{field: value}), "user_name", today=TODAY)
        with self.assertRaises(dating.DatingError):
            dating.clean_profile(base_profile(min_age=40, max_age=30), "user_name", today=TODAY)

    def test_whatsapp_normalization(self):
        self.assertEqual(dating.normalize_whatsapp("+53 5267-7163"), "5352677163")
        self.assertEqual(dating.normalize_whatsapp(""), "")
        with self.assertRaises(dating.DatingError):
            dating.normalize_whatsapp("123")


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.c = make_db()

    def feed(self, uid):
        return dating.candidate_feed(self.c, uid, SECRET, today=TODAY)

    def test_requires_profile_and_photo(self):
        with self.assertRaises(dating.DatingError) as ctx:
            self.feed("1")
        self.assertEqual(ctx.exception.code, "no_profile")
        self.c.execute("INSERT INTO users(user_id,username) VALUES('1','ana_test')")
        dating.upsert_profile(self.c, "1", dating.clean_profile(base_profile(), "ana_test", today=TODAY))
        with self.assertRaises(dating.DatingError) as ctx:
            self.feed("1")
        self.assertEqual(ctx.exception.code, "no_photo")

    def test_mutual_gender_compatibility(self):
        create_user(self.c, "1", "ana_test", gender="mujer", looking_for="hombres")
        good = create_user(self.c, "2", "juan_test", gender="hombre", looking_for="mujeres")
        create_user(self.c, "3", "pedro_te", gender="hombre", looking_for="hombres")  # no busca mujeres
        create_user(self.c, "4", "rosa_tes", gender="mujer", looking_for="mujeres")   # yo no busco mujeres
        ids = [p["public_id"] for p in self.feed("1")]
        self.assertEqual(ids, [good])

    def test_non_binary_matches_only_with_everyone_preference(self):
        create_user(self.c, "1", "ana_test", gender="otro", looking_for="todos")
        a = create_user(self.c, "2", "juan_test", gender="hombre", looking_for="todos")
        create_user(self.c, "3", "luis_tes", gender="hombre", looking_for="mujeres")
        self.assertEqual([p["public_id"] for p in self.feed("1")], [a])

    def test_unapproved_hidden_paused_and_suspended_profiles_are_excluded(self):
        create_user(self.c, "1", "ana_test", gender="mujer", looking_for="hombres")
        create_user(self.c, "2", "pend_tes", gender="hombre", looking_for="mujeres", approved=False)
        paused = create_user(self.c, "3", "paus_tes", gender="hombre", looking_for="mujeres")
        susp = create_user(self.c, "4", "susp_tes", gender="hombre", looking_for="mujeres")
        self.c.execute("UPDATE dating_profiles SET visible=0 WHERE public_id=?", (paused,))
        self.c.execute("UPDATE dating_profiles SET status='suspended' WHERE public_id=?", (susp,))
        self.c.commit()
        self.assertEqual(self.feed("1"), [])

    def test_age_preferences_apply_in_both_directions(self):
        create_user(self.c, "1", "ana_test", birth_date="2000-05-10", min_age=18, max_age=30)
        create_user(self.c, "2", "old_test", gender="hombre", looking_for="mujeres", birth_date="1970-01-01")
        create_user(self.c, "3", "yng_test", gender="hombre", looking_for="mujeres", birth_date="1999-01-01", min_age=40, max_age=60)
        ok = create_user(self.c, "4", "ok_test1", gender="hombre", looking_for="mujeres", birth_date="1998-01-01")
        self.assertEqual([p["public_id"] for p in self.feed("1")], [ok])

    def test_same_province_first_and_seen_profiles_not_repeated(self):
        create_user(self.c, "1", "ana_test", province="La Habana")
        far = create_user(self.c, "2", "far_test", gender="hombre", looking_for="mujeres", province="Holguín")
        near = create_user(self.c, "3", "nea_test", gender="hombre", looking_for="mujeres", province="La Habana")
        first = self.feed("1")
        self.assertEqual(first[0]["public_id"], near)
        self.assertTrue(first[0]["same_province"])
        dating.record_swipe(self.c, "1", near, "pass", 20, False)
        self.assertEqual([p["public_id"] for p in self.feed("1")], [far])

    def test_card_never_exposes_private_data(self):
        create_user(self.c, "1", "ana_test")
        create_user(self.c, "2", "juan_test", gender="hombre", looking_for="mujeres", whatsapp="5352677163")
        data = self.feed("1")[0]
        text = repr(data)
        for secret in ("5352677163", "juan_test", "2000-05-10", "birth_date", "user_id", "whatsapp"):
            self.assertNotIn(secret, text)
        self.assertNotIn("contacts", data)


class SwipeAndMatchTests(unittest.TestCase):
    def setUp(self):
        self.c = make_db()
        self.a = create_user(self.c, "1", "ana_test", gender="mujer", looking_for="hombres")
        self.b = create_user(self.c, "2", "juan_test", gender="hombre", looking_for="mujeres", whatsapp="5352677163")

    def swipe(self, uid, target, action="like", limit=20, premium=False):
        return dating.record_swipe(self.c, uid, target, action, limit, premium)

    def test_one_sided_like_does_not_match_and_reveals_no_contact(self):
        r = self.swipe("1", self.b)
        self.assertFalse(r["matched"])
        self.assertEqual(dating.list_matches(self.c, "1", SECRET), [])

    def test_mutual_like_creates_match_with_external_contacts_only(self):
        self.swipe("1", self.b)
        r = self.swipe("2", self.a)
        self.assertTrue(r["matched"])
        self.assertCountEqual(r["notify"], ["1", "2"])
        matches = dating.list_matches(self.c, "1", SECRET)
        self.assertEqual(len(matches), 1)
        urls = {x["type"]: x["url"] for x in matches[0]["contacts"]}
        self.assertEqual(urls["telegram"], "https://t.me/juan_test")
        self.assertEqual(urls["whatsapp"], "https://wa.me/5352677163")
        # El producto expone contactos externos en el match y también mantiene
        # chat interno (dating_messages). Ambas cosas son válidas y coexisten.
        tables = {r[0] for r in self.c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("dating_matches", tables)
        self.assertTrue("dating_messages" in tables or "dating_chat_presence" in tables)

    def test_only_shared_channels_are_revealed(self):
        self.c.execute("UPDATE dating_profiles SET share_telegram=0 WHERE user_id='2'")
        self.c.commit()
        self.swipe("1", self.b)
        self.swipe("2", self.a)
        contacts = dating.list_matches(self.c, "1", SECRET)[0]["contacts"]
        self.assertEqual([x["type"] for x in contacts], ["whatsapp"])

    def test_pass_never_matches(self):
        self.swipe("1", self.b, "pass")
        self.assertFalse(self.swipe("2", self.a)["matched"])

    def test_duplicate_swipe_is_ignored(self):
        self.swipe("1", self.b)
        self.assertTrue(self.swipe("1", self.b)["duplicate"])
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM dating_swipes").fetchone()[0], 1)

    def test_cannot_swipe_self_unknown_or_invalid_action(self):
        for target, action in ((self.a, "like"), ("nope", "like"), (self.b, "super")):
            with self.assertRaises(dating.DatingError):
                self.swipe("1", target, action)

    def test_daily_like_limit_for_free_but_not_premium_or_pass(self):
        profiles = [create_user(self.c, str(10 + i), f"user_{i:04d}", gender="hombre", looking_for="mujeres") for i in range(4)]
        self.swipe("1", profiles[0], limit=2)
        self.swipe("1", profiles[1], limit=2)
        with self.assertRaises(dating.DatingError) as ctx:
            self.swipe("1", profiles[2], limit=2)
        self.assertEqual(ctx.exception.code, "daily_limit")
        self.swipe("1", profiles[2], "pass", limit=2)
        self.assertIsNone(self.swipe("1", profiles[3], limit=2, premium=True)["likes_left"])

    def test_undo_removes_swipe_but_not_a_match(self):
        self.swipe("1", self.b)
        undone = dating.undo_last_swipe(self.c, "1", SECRET)
        self.assertEqual(undone["profile"]["public_id"], self.b)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM dating_swipes").fetchone()[0], 0)
        self.swipe("1", self.b)
        self.swipe("2", self.a)
        with self.assertRaises(dating.DatingError):
            dating.undo_last_swipe(self.c, "1", SECRET)

    def test_likes_received_is_locked_for_free_users(self):
        self.swipe("2", self.a)
        free = dating.likes_received(self.c, "1", SECRET, False)
        self.assertEqual((free["count"], free["locked"]), (1, True))
        self.assertNotIn("profiles", free)
        paid = dating.likes_received(self.c, "1", SECRET, True)
        self.assertEqual(paid["profiles"][0]["public_id"], self.b)


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.c = make_db()
        self.a = create_user(self.c, "1", "ana_test", gender="mujer", looking_for="hombres")
        self.b = create_user(self.c, "2", "juan_test", gender="hombre", looking_for="mujeres")
        dating.record_swipe(self.c, "1", self.b, "like", 20, False)
        dating.record_swipe(self.c, "2", self.a, "like", 20, False)

    def test_unmatch_hides_contacts_for_both_sides(self):
        match_id = dating.list_matches(self.c, "1", SECRET)[0]["match_id"]
        dating.unmatch(self.c, "1", match_id)
        self.assertEqual(dating.list_matches(self.c, "1", SECRET), [])
        self.assertEqual(dating.list_matches(self.c, "2", SECRET), [])

    def test_stranger_cannot_unmatch_someone_elses_match(self):
        match_id = dating.list_matches(self.c, "1", SECRET)[0]["match_id"]
        create_user(self.c, "3", "otro_tes")
        with self.assertRaises(dating.DatingError):
            dating.unmatch(self.c, "3", match_id)

    def test_block_ends_match_and_hides_both_ways(self):
        dating.block_user(self.c, "1", self.b)
        self.assertEqual(dating.list_matches(self.c, "2", SECRET), [])
        with self.assertRaises(dating.DatingError):
            dating.record_swipe(self.c, "2", self.a, "like", 20, False)

    def test_blocked_profile_never_shows_in_feed_of_blocker_or_blocked(self):
        c = make_db()
        a = create_user(c, "1", "ana_test", gender="mujer", looking_for="hombres")
        b = create_user(c, "2", "juan_test", gender="hombre", looking_for="mujeres")
        dating.block_user(c, "2", a)
        self.assertEqual(dating.candidate_feed(c, "1", SECRET, today=TODAY), [])
        self.assertEqual(dating.candidate_feed(c, "2", SECRET, today=TODAY), [])

    def test_three_distinct_reports_hide_profile_pending_review(self):
        c = make_db()
        target = create_user(c, "9", "bad_test1", gender="hombre", looking_for="mujeres")
        for i in range(3):
            uid = str(20 + i)
            create_user(c, uid, f"rep_{i:04d}")
            self.assertEqual(dating.get_profile(c, "9")["status"], "active" if i < 2 else "active")
            dating.report_user(c, uid, target, "harassment")
        self.assertEqual(dating.get_profile(c, "9")["status"], "under_review")

    def test_minor_report_hides_immediately_and_duplicates_are_ignored(self):
        c = make_db()
        target = create_user(c, "9", "bad_test1", gender="hombre", looking_for="mujeres")
        create_user(c, "20", "rep_0001")
        first = dating.report_user(c, "20", target, "minor")
        self.assertTrue(first["auto_hidden"])
        self.assertTrue(dating.report_user(c, "20", target, "minor")["duplicate"])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM dating_reports").fetchone()[0], 1)
        with self.assertRaises(dating.DatingError):
            dating.report_user(c, "20", target, "invalid_reason")

    def test_admin_dismiss_restores_and_suspend_ends_matches(self):
        c = make_db()
        a = create_user(c, "1", "ana_test", gender="mujer", looking_for="hombres")
        b = create_user(c, "2", "juan_test", gender="hombre", looking_for="mujeres")
        dating.record_swipe(c, "1", b, "like", 20, False)
        dating.record_swipe(c, "2", a, "like", 20, False)
        dating.report_user(c, "1", b, "minor")
        report = dating.admin_list_reports(c)[0]
        dating.admin_resolve_report(c, report["id"], "dismiss", "owner")
        self.assertEqual(dating.get_profile(c, "2")["status"], "active")
        dating.report_user(c, "1", b, "scam")
        report = dating.admin_list_reports(c)[0]
        dating.admin_resolve_report(c, report["id"], "suspend", "owner")
        self.assertEqual(dating.get_profile(c, "2")["status"], "suspended")
        self.assertEqual(dating.list_matches(c, "1", SECRET), [])
        with self.assertRaises(dating.DatingError):
            dating.candidate_feed(c, "2", SECRET, today=TODAY)
        dating.admin_restore_profile(c, "2")
        self.assertEqual(dating.get_profile(c, "2")["status"], "active")

    def test_delete_all_data_removes_everything_but_keeps_reports(self):
        c = make_db()
        a = create_user(c, "1", "ana_test", gender="mujer", looking_for="hombres")
        b = create_user(c, "2", "juan_test", gender="hombre", looking_for="mujeres")
        dating.record_swipe(c, "1", b, "like", 20, False)
        dating.record_swipe(c, "2", a, "like", 20, False)
        dating.report_user(c, "1", b, "scam")
        dating.delete_dating_data(c, "2", tempfile.gettempdir())
        for table, col in (("dating_profiles", "user_id"), ("dating_photos", "user_id")):
            self.assertEqual(c.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}='2'").fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM dating_swipes WHERE user_id='2' OR target_id='2'").fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM dating_matches").fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM dating_reports").fetchone()[0], 1)


class PhotoTests(unittest.TestCase):
    def setUp(self):
        self.c = make_db()
        self.dir = tempfile.mkdtemp()
        create_user(self.c, "1", "ana_test")
        self.c.execute("DELETE FROM dating_photos")
        self.c.commit()

    def png_bytes(self, size=(2000, 1500), mode="RGB"):
        from PIL import Image
        buf = io.BytesIO()
        Image.new(mode, size, (200, 30, 90)).save(buf, "PNG")
        return buf.getvalue()

    def test_process_photo_resizes_and_strips_metadata(self):
        from PIL import Image
        src = Image.new("RGB", (3000, 2000), (10, 20, 30))
        buf = io.BytesIO()
        exif = Image.Exif()
        exif[0x010F] = "CameraMaker"
        src.save(buf, "JPEG", exif=exif)
        out = dating.process_photo(buf.getvalue())
        img = Image.open(io.BytesIO(out))
        self.assertEqual(img.format, "JPEG")
        self.assertLessEqual(max(img.size), dating.PHOTO_MAX_SIDE)
        self.assertFalse(dict(img.getexif()))

    def test_rejects_non_images_and_bad_data_urls(self):
        with self.assertRaises(dating.DatingError):
            dating.process_photo(b"not an image")
        for bad in ("", "data:text/html;base64,AAAA", "data:image/gif;base64,AAAA", "javascript:alert(1)"):
            with self.assertRaises(dating.DatingError):
                dating.parse_image_data_url(bad)

    def test_upload_limit_delete_and_pending_status(self):
        jpeg = dating.process_photo(self.png_bytes((400, 400)))
        for _ in range(dating.MAX_PHOTOS):
            self.assertEqual(dating.add_photo(self.c, "1", self.dir, jpeg)["status"], "pending")
        with self.assertRaises(dating.DatingError) as ctx:
            dating.add_photo(self.c, "1", self.dir, jpeg)
        self.assertEqual(ctx.exception.code, "photo_limit")
        row = self.c.execute("SELECT id,filename FROM dating_photos").fetchone()
        self.assertTrue(os.path.exists(os.path.join(self.dir, row["filename"])))
        dating.delete_photo(self.c, "1", self.dir, row["id"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, row["filename"])))
        with self.assertRaises(dating.DatingError):
            dating.delete_photo(self.c, "2", self.dir, row["id"])

    def test_moderation_approves_and_rejects(self):
        jpeg = dating.process_photo(self.png_bytes((300, 300)))
        ok = dating.add_photo(self.c, "1", self.dir, jpeg)["id"]
        bad = dating.add_photo(self.c, "1", self.dir, jpeg)["id"]
        self.assertEqual(len(dating.admin_pending_photos(self.c, SECRET)), 2)
        dating.admin_review_photo(self.c, ok, True, "", "owner", self.dir)
        name = self.c.execute("SELECT filename FROM dating_photos WHERE id=?", (bad,)).fetchone()[0]
        dating.admin_review_photo(self.c, bad, False, "Desnudez", "owner", self.dir)
        self.assertFalse(os.path.exists(os.path.join(self.dir, name)))
        statuses = {r["id"]: r["status"] for r in self.c.execute("SELECT id,status FROM dating_photos")}
        self.assertEqual(statuses, {ok: "approved", bad: "rejected"})
        self.assertEqual(dating.admin_pending_photos(self.c, SECRET), [])

    def test_signed_photo_urls_expire_and_cannot_be_forged(self):
        url = dating.photo_url(SECRET, 7, now=1_000_000)
        query = dict(p.split("=") for p in url.split("?")[1].split("&"))
        expires, sig = int(query["e"]), query["s"]
        self.assertTrue(dating.verify_photo_signature(SECRET, 7, expires, sig, now=1_000_100))
        self.assertFalse(dating.verify_photo_signature(SECRET, 8, expires, sig, now=1_000_100))
        self.assertFalse(dating.verify_photo_signature("x" * 40, 7, expires, sig, now=1_000_100))
        self.assertFalse(dating.verify_photo_signature(SECRET, 7, expires, sig, now=expires + 1))
        self.assertFalse(dating.verify_photo_signature(SECRET, 7, expires, "", now=1_000_100))
        # estable dentro de la misma hora (permite caché del navegador)
        self.assertEqual(url, dating.photo_url(SECRET, 7, now=1_000_500))


class OverviewTests(unittest.TestCase):
    def test_overview_shows_owner_data_and_photo_status(self):
        c = make_db()
        create_user(c, "1", "ana_test", approved=False)
        data = dating.overview(c, "1", SECRET)
        self.assertEqual(data["profile"]["telegram_username"], "ana_test")
        self.assertEqual(data["photos"][0]["status"], "pending")
        self.assertEqual(dating.overview(c, "99", SECRET), {"profile": None, "photos": []})

    def test_age_calculation(self):
        self.assertEqual(dating.age_from("2000-11-02", TODAY), 26)
        self.assertEqual(dating.age_from("2000-11-03", TODAY), 25)


class WizardPrefsTests(unittest.TestCase):
    """Asistente de perfil: preferencias, orden del feed, fecha de nacimiento y migración."""

    def setUp(self):
        self.c = make_db()

    def test_prefs_whitelist_drops_unknown_keys_and_values(self):
        cleaned = dating.clean_prefs({
            "intent": ["serious", "serious", "hack"], "work": "office", "kids": "invalid",
            "unknown": "x", "dealbreakers": ["smoke", "none"], "common": "travel",
        })
        self.assertEqual(cleaned, {"intent": ["serious"], "work": "office", "dealbreakers": ["none"]})
        self.assertEqual(dating.clean_prefs("no es dict"), {})

    def test_prefs_saved_and_kept_when_request_omits_them(self):
        create_user(self.c, "1", "ana_test", prefs={"work": "office", "intent": ["serious"]})
        prefs = dating.overview(self.c, "1", SECRET)["profile"]["prefs"]
        self.assertEqual(prefs, {"intent": ["serious"], "work": "office"})
        again = dating.clean_profile(base_profile(bio="Nueva bio"), "ana_test", existing=True, today=TODAY)
        self.assertIsNone(again["prefs"])
        dating.upsert_profile(self.c, "1", again)
        self.assertEqual(dating.overview(self.c, "1", SECRET)["profile"]["prefs"], prefs)

    def test_feed_prefers_same_province_then_affinity(self):
        create_user(self.c, "1", "ana_test", gender="mujer", looking_for="hombres", province="La Habana",
                    prefs={"intent": ["serious"], "kids": "want", "common": ["travel", "sport"]})
        far_fit = create_user(self.c, "2", "far_fit_u", gender="hombre", looking_for="mujeres", province="Holguín",
                              prefs={"intent": ["serious"], "kids": "want", "common": ["travel"]})
        near_low = create_user(self.c, "3", "near_low", gender="hombre", looking_for="mujeres", province="La Habana",
                               prefs={"intent": ["casual"]})
        near_fit = create_user(self.c, "4", "near_fit", gender="hombre", looking_for="mujeres", province="La Habana",
                               prefs={"intent": ["serious"], "kids": "want", "common": ["travel", "sport"]})
        feed = dating.candidate_feed(self.c, "1", SECRET, today=TODAY)
        self.assertEqual([p["public_id"] for p in feed], [near_fit, near_low, far_fit])
        self.assertEqual(feed[0]["in_common"], 4)  # intención + hijos + 2 intereses comunes
        self.assertNotIn("prefs", feed[0])  # las respuestas privadas no viajan a otras personas

    def test_birth_date_is_locked_after_creation(self):
        create_user(self.c, "1", "ana_test")
        with self.assertRaises(dating.DatingError) as ctx:
            dating.clean_profile(base_profile(birth_date="1990-01-01"), "ana_test", existing=True,
                                 today=TODAY, locked_birth_date="2000-05-10")
        self.assertEqual(ctx.exception.code, "birth_locked")
        ok = dating.clean_profile(base_profile(birth_date=""), "ana_test", existing=True, today=TODAY,
                                  locked_birth_date="2000-05-10")
        self.assertEqual(ok["birth_date"], "2000-05-10")

    def test_daily_likes_reset_at_cuban_midnight_not_utc(self):
        from datetime import timezone as tz
        create_user(self.c, "1", "ana_test", gender="mujer", looking_for="hombres")
        # 23:30 hora de Cuba del 1/nov (04:30 UTC del 2/nov): cuenta como el día 1 de Cuba
        late = dating._cuba_day_start_utc(date(2026, 11, 2))
        self.assertTrue(late.startswith("2026-11-02T05:00") or late.startswith("2026-11-02T04:00"))
        self.c.execute("INSERT INTO dating_swipes VALUES('1','x','like',?)", ("2026-11-02T04:30:00",))
        self.assertEqual(dating.likes_today(self.c, "1", date(2026, 11, 2)), 0)   # aún era el 1 en Cuba
        self.assertEqual(dating.likes_today(self.c, "1", date(2026, 11, 1)), 1)
        self.c.execute("INSERT INTO dating_swipes VALUES('1','y','like',?)", ("2026-11-02T06:00:00",))
        self.assertEqual(dating.likes_today(self.c, "1", date(2026, 11, 2)), 1)

    def test_rejected_photos_do_not_use_slots_and_positions_do_not_repeat(self):
        create_user(self.c, "1", "ana_test")
        self.c.execute("DELETE FROM dating_photos")
        with tempfile.TemporaryDirectory() as folder:
            ids = [dating.add_photo(self.c, "1", folder, b"jpg")["id"] for _ in range(dating.MAX_PHOTOS)]
            with self.assertRaises(dating.DatingError):
                dating.add_photo(self.c, "1", folder, b"jpg")
            dating.admin_review_photo(self.c, ids[0], False, "mala", "admin", folder)
            dating.delete_photo(self.c, "1", folder, ids[2])
            dating.add_photo(self.c, "1", folder, b"jpg")
            positions = [r[0] for r in self.c.execute("SELECT position FROM dating_photos WHERE status!='rejected'")]
            self.assertEqual(len(positions), len(set(positions)))

    def test_minor_report_is_rate_limited_per_reporter(self):
        for i in range(5):
            create_user(self.c, str(10 + i), f"target_{i:02d}")
        create_user(self.c, "1", "report_er")
        publics = [dating.get_profile(self.c, str(10 + i))["public_id"] for i in range(5)]
        for target in publics[:dating.MAX_MINOR_REPORTS_PER_DAY]:
            dating.report_user(self.c, "1", target, "minor")
        with self.assertRaises(dating.DatingError) as ctx:
            dating.report_user(self.c, "1", publics[3], "minor")
        self.assertEqual(ctx.exception.code, "report_limit")
        dating.report_user(self.c, "1", publics[3], "scam")  # otros motivos no se limitan igual

    def test_schema_migration_adds_prefs_column_to_old_database(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute("CREATE TABLE dating_profiles(user_id TEXT PRIMARY KEY, public_id TEXT, display_name TEXT, birth_date TEXT, "
                  "gender TEXT, looking_for TEXT, province TEXT, municipality TEXT, bio TEXT, interests TEXT, min_age INTEGER, "
                  "max_age INTEGER, whatsapp TEXT, share_telegram INTEGER, visible INTEGER, status TEXT, accepted_terms_at TEXT, "
                  "created_at TEXT, updated_at TEXT)")
        dating.init_schema(c)
        self.assertIn("prefs", [r[1] for r in c.execute("PRAGMA table_info(dating_profiles)")])
        dating.init_schema(c)  # idempotente


if __name__ == "__main__":
    unittest.main()
