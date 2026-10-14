"""Offline tests for the Telegram /start welcome-only behavior."""
import unittest

from backend import main


class TestTelegramWelcome(unittest.TestCase):
    def test_welcome_has_official_channel_community_and_mini_app_buttons(self):
        payload = main._telegram_start_message(12345)
        self.assertEqual(payload["chat_id"], 12345)
        self.assertIn("disponible próximamente", payload["text"])
        self.assertIn("Mini App", payload["text"])
        buttons = [button for row in payload["reply_markup"]["inline_keyboard"] for button in row]
        by_text = {button["text"]: button for button in buttons}
        self.assertEqual(by_text["📢 Canal oficial"]["url"], "https://t.me/LiggaCubaOficial")
        self.assertEqual(by_text["💬 Chat de la comunidad"]["url"], "https://t.me/+8O32GWhar8VjNjZh")
        self.assertEqual(
            by_text["🚀 Abrir Mini App"]["web_app"]["url"],
            "https://responde-ai-telegram-production-6cdc.up.railway.app/",
        )
        self.assertEqual(len(buttons), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
