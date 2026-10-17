#!/usr/bin/env python3
"""One-shot script to register the production Telegram webhook.

Usage (run once after each deploy, or wire into CI):
    python scripts/setup_telegram_webhook.py

Requires the environment to contain:
    TELEGRAM_BOT_TOKEN        Bot token from @BotFather
    PUBLIC_BASE_URL           Public HTTPS URL of this deployment
    TELEGRAM_WEBHOOK_SECRET   >= 32 chars, must match the server variable
    ADMIN_KEY                 Owner key, only used to verify server reachability
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import telegram_bot as tb  # noqa: E402


def main() -> int:
    missing = [v for v in ("TELEGRAM_BOT_TOKEN", "PUBLIC_BASE_URL", "TELEGRAM_WEBHOOK_SECRET") if not os.getenv(v, "").strip()]
    if missing:
        print("Faltan variables de entorno: " + ", ".join(missing))
        return 2
    base = os.environ["PUBLIC_BASE_URL"].strip().rstrip("/")
    if not base.startswith("https://"):
        print("PUBLIC_BASE_URL debe ser una URL HTTPS pública")
        return 2
    try:
        result = tb.set_webhook(base + "/webhook/telegram", os.environ["TELEGRAM_WEBHOOK_SECRET"], ["message"])
    except tb.TelegramBotError as exc:
        print("Telegram rechazó el registro del webhook:", exc)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("Webhook registrado en:", base + "/webhook/telegram")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
