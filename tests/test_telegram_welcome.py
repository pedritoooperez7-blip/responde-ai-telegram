"""Offline tests for the /start welcome payload built through the bot module."""
import os
import unittest
from unittest import mock

os.environ.setdefault("DB_PATH", ":memory:")

from backend import main
from backend import telegram_bot as tb

VALID_ENV = {
    "TELEGRAM_BOT_TOKEN": "123456:TESTTOKEN-for-offline-tests",
    "TELEGRAM_WEBHOOK_SECRET": "s" * 40,
    "TELEGRAM_MINI_APP_URL": "https://liggacuba.example.app",
    "TELEGRAM_CHANNEL_URL": "https://t.me/LiggaCubaOficial",
    "TELEGRAM_COMMUNITY_URL": "https://t.me/+8O32GWhar8VjNjZh",
}


class TestTelegramWelcome(unittest.TestCase):
    def test_welcome_has_official_channel_community_and_mini_app_buttons(self):
        with mock.patch.dict(os.environ, VALID_ENV):
            payload = main._telegram_start_message(12345)
        self.assertEqual(payload["chat_id"], 12345)
        self.assertIn("LiggaCuba", payload["text"])
        self.assertIn("Mini App", payload["text"])
        buttons = [button for row in payload["reply_markup"]["inline_keyboard"] for button in row]
        by_text = {button["text"]: button for button in buttons}
        self.assertEqual(by_text["\U0001F4E2 Canal oficial"]["url"], "https://t.me/LiggaCubaOficial")
        self.assertEqual(by_text["\U0001F4AC Chat de la comunidad"]["url"], "https://t.me/+8O32GWhar8VjNjZh")
        self.assertEqual(
            by_text["\U0001F680 Abrir Mini App"]["web_app"]["url"],
            "https://liggacuba.example.app/",
        )
        self.assertEqual(len(buttons), 3)
        self.assertEqual([len(row) for row in payload["reply_markup"]["inline_keyboard"]], [1, 1, 1])
        self.assertIn("disponible próximamente", payload["text"])
        self.assertNotIn("up.railway.app", payload["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
