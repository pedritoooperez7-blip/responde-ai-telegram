"""Offline tests for the real Telegram bot integration.

These tests never touch the network: the Bot API call layer is replaced with
a recorder, and TELEGRAM_* configuration is provided via environment
variables inside each test.
"""
from __future__ import annotations

import importlib
import json
import os
import unittest
from unittest import mock

os.environ.setdefault("DB_PATH", ":memory:")

from backend import telegram_bot as tb


VALID_ENV = {
    "TELEGRAM_BOT_TOKEN": "123456:TESTTOKEN-for-offline-tests",
    "TELEGRAM_WEBHOOK_SECRET": "s" * 40,
    "TELEGRAM_MINI_APP_URL": "https://liggacuba.example.app",
    "TELEGRAM_CHANNEL_URL": "https://t.me/LiggaCubaOficial",
    "TELEGRAM_COMMUNITY_URL": "https://t.me/+TESTCOMMUNITY",
}


def start_message(update_id: int = 1, chat_id: int = 777) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 10,
            "chat": {"id": chat_id, "type": "private"},
            "text": "/start",
        },
    }


class WebhookSecretTests(unittest.TestCase):
    def test_verify_accepts_matching_secret(self):
        with mock.patch.dict(os.environ, VALID_ENV):
            importlib.reload(tb)
            self.assertTrue(tb.verify_webhook_secret("s" * 40))

    def test_verify_rejects_wrong_or_missing_secret(self):
        with mock.patch.dict(os.environ, VALID_ENV):
            importlib.reload(tb)
            self.assertFalse(tb.verify_webhook_secret("x" * 40))
            self.assertFalse(tb.verify_webhook_secret(""))

    def test_missing_configuration_raises(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("TELEGRAM_")}
        with mock.patch.dict(os.environ, env, clear=True):
            importlib.reload(tb)
            with self.assertRaises(tb.TelegramBotError):
                tb.webhook_secret()
            with self.assertRaises(tb.TelegramBotError):
                tb.bot_token()
            with self.assertRaises(tb.TelegramBotError):
                tb.mini_app_url()


class StartPayloadTests(unittest.TestCase):
    def test_start_payload_has_three_buttons_and_mini_app(self):
        payload = tb.build_start_payload(
            777,
            "https://liggacuba.example.app/",
            "https://t.me/LiggaCubaOficial",
            "https://t.me/+TESTCOMMUNITY",
        )
        self.assertEqual(payload["chat_id"], 777)
        self.assertIn("LiggaCuba", payload["text"])
        buttons = [b for row in payload["reply_markup"]["inline_keyboard"] for b in row]
        by_text = {b["text"]: b for b in buttons}
        self.assertEqual(by_text["\U0001F4E2 Canal oficial"]["url"], "https://t.me/LiggaCubaOficial")
        self.assertEqual(by_text["\U0001F4AC Chat de la comunidad"]["url"], "https://t.me/+TESTCOMMUNITY")
        self.assertEqual(
            by_text["\U0001F680 Abrir Mini App"]["web_app"]["url"],
            "https://liggacuba.example.app/",
        )
        self.assertEqual(len(buttons), 3)


class HandleUpdateTests(unittest.TestCase):
    def setUp(self):
        env_patcher = mock.patch.dict(os.environ, VALID_ENV)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        os.environ["DB_PATH"] = f"/tmp/ligga_updates_{id(self)}.db"
        if os.path.exists(os.environ["DB_PATH"]):
            os.remove(os.environ["DB_PATH"])
        importlib.reload(tb)
        tb.init_processed_updates()

    def test_start_sends_real_message_once(self):
        sent = []

        def fake_send(chat_id, text, reply_markup=None):
            sent.append((chat_id, text, reply_markup))
            return {"message_id": 1}

        with mock.patch.object(tb, "send_message", side_effect=fake_send):
            outcome = tb.handle_update(start_message(101))
            self.assertEqual(outcome["action"], "start_sent")
            self.assertEqual(sent, [(777, mock.ANY, mock.ANY)])
            self.assertIn("LiggaCuba", sent[0][1])

            # A redelivered update must never send again.
            outcome2 = tb.handle_update(start_message(101))
            self.assertEqual(outcome2.get("reason"), "duplicate_update")
            self.assertEqual(len(sent), 1)

    def test_unknown_command_is_ignored_without_sending(self):
        sent = []
        update = start_message(102)
        update["message"]["text"] = "/help"
        with mock.patch.object(tb, "send_message", side_effect=lambda *a, **k: sent.append(a)):
            outcome = tb.handle_update(update)
        self.assertEqual(outcome["action"], "ignored_unknown_command")
        self.assertEqual(sent, [])

    def test_plain_text_and_non_text_are_ignored(self):
        sent = []
        plain = start_message(103)
        plain["message"]["text"] = "hola"
        photo = {"update_id": 104, "message": {"message_id": 11, "chat": {"id": 777}, "photo": []}}
        with mock.patch.object(tb, "send_message", side_effect=lambda *a, **k: sent.append(a)):
            self.assertEqual(tb.handle_update(plain)["action"], "ignored_plain_message")
            self.assertEqual(tb.handle_update(photo)["action"], "ignored_non_text")
        self.assertEqual(sent, [])

    def test_update_without_id_is_rejected(self):
        with mock.patch.object(tb, "send_message"):
            outcome = tb.handle_update({"message": {"text": "/start"}})
        self.assertEqual(outcome["handled"], False)


class ApiCallTests(unittest.TestCase):
    def test_send_message_posts_to_bot_api(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"ok": True, "result": {"message_id": 5}}).encode()

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode())
            return FakeResponse()

        with mock.patch.dict(os.environ, VALID_ENV):
            importlib.reload(tb)
            with mock.patch.object(tb.urllib.request, "urlopen", side_effect=fake_urlopen):
                result = tb.send_message(777, "hola", {"inline_keyboard": []})
        self.assertIn("/bot123456:TESTTOKEN-for-offline-tests/sendMessage", captured["url"])
        self.assertEqual(captured["body"]["chat_id"], 777)
        self.assertEqual(captured["body"]["text"], "hola")
        self.assertEqual(result.get("message_id"), 5)

    def test_api_error_raises_telegram_bot_error(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"ok": False, "description": "Bad Request: chat not found"}).encode()

        with mock.patch.dict(os.environ, VALID_ENV):
            importlib.reload(tb)
            with mock.patch.object(tb.urllib.request, "urlopen", return_value=FakeResponse()):
                with self.assertRaises(tb.TelegramBotError):
                    tb.send_message(777, "hola")


if __name__ == "__main__":
    unittest.main(verbosity=2)
