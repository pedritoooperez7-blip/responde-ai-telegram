"""Real Telegram Bot integration: webhook endpoint, /start handling, sending via Bot API.

Security model:
- Webhook updates are authenticated with Telegram's secret token header
  (X-Telegram-Bot-Api-Secret-Token), compared with a constant-time check.
- Every processed update id is persisted before handling, so a redelivered
  update (Telegram retries on non-200) is acknowledged without double actions.
- The bot never touches the Mini App user database: /start only sends the
  welcome message and does not create users or sessions.

[Fase 5 — Bots de citas]
- Clase ``TelegramBot`` (al final del módulo) para el grupo de control de bots
  de citas: reenvía bot_message / bot_match / bot_admin_reply y procesa replies
  del grupo con tag [BOT_CHAT:<match_id>].
- Usa TELEGRAM_BOT_TOKEN (mismo token que el resto del bot).
- No reemplaza handle_update / send_message / verify_webhook_secret.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
WEBHOOK_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
MAX_UPDATE_BYTES = 256 * 1024
PROCESSING_TTL_DAYS = 14


class TelegramBotError(Exception):
    """Raised when the Telegram Bot API rejects a call or is unreachable."""
