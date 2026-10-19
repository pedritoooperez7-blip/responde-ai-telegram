"""Real Telegram Bot integration: webhook endpoint, /start handling, sending via Bot API.

Security model:
- Webhook updates are authenticated with Telegram's secret token header
  (X-Telegram-Bot-Api-Secret-Token), compared with a constant-time check.
- Every processed update id is persisted before handling, so a redelivered
  update (Telegram retries on non-200) is acknowledged without double actions.
- The bot never touches the Mini App user database: /start only sends the
  welcome message and does not create users or sessions.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
WEBHOOK_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
MAX_UPDATE_BYTES = 256 * 1024
PROCESSING_TTL_DAYS = 14


class TelegramBotError(Exception):
    """Raised when the Telegram Bot API rejects a call or is unreachable."""


def bot_token() -> str:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token or ":" not in token:
        raise TelegramBotError("TELEGRAM_BOT_TOKEN no está configurado")
    return token


def webhook_secret() -> str:
    secret = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()
    if len(secret) < 32:
        raise TelegramBotError("TELEGRAM_WEBHOOK_SECRET debe configurarse con al menos 32 caracteres")
    return secret


def mini_app_url() -> str:
    url = (os.getenv("TELEGRAM_MINI_APP_URL") or "").strip().rstrip("/")
    if not url.startswith("https://"):
        raise TelegramBotError("TELEGRAM_MINI_APP_URL debe ser una URL HTTPS pública")
    return url + "/"


def official_channel() -> str:
    return (os.getenv("TELEGRAM_CHANNEL_URL") or "https://t.me/LiggaCubaOficial").strip()


def community_chat() -> str:
    return (os.getenv("TELEGRAM_COMMUNITY_URL") or "").strip()


def bot_api_call(method: str, payload: Dict[str, Any], timeout: float = 8.0) -> Dict[str, Any]:
    """POST a Bot API method and return the parsed result envelope."""
    url = f"{TELEGRAM_API_BASE}/bot{bot_token()}/{method}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Telegram includes a JSON description in HTTP error responses too.
        # Read only the response body; never log the URL, token, or request payload.
        description = None
        try:
            error_body = json.loads(exc.read().decode("utf-8", errors="replace"))
            if isinstance(error_body, dict):
                description = error_body.get("description")
        except (ValueError, OSError):
            pass
        safe_description = str(description or "Telegram Bot API rechazó la solicitud")[:240]
        logger.warning(
            "Telegram API %s failed: status=%s description=%r",
            method, exc.code, safe_description,
        )
        raise TelegramBotError(f"Telegram Bot API devolvió HTTP {exc.code}: {safe_description}") from None
    except (TimeoutError, OSError) as exc:
        logger.warning("Telegram API %s unreachable or timed out: error_type=%s", method, type(exc).__name__)
        raise TelegramBotError("Telegram Bot API no está accesible") from None
    if not isinstance(body, dict) or body.get("ok") is not True:
        description = body.get("description") if isinstance(body, dict) else None
        # Telegram's description is useful for diagnosing 502s (e.g. invalid
        # inline button URL). Do not log request payloads or credentials.
        safe_description = str(description or "Telegram Bot API rechazó la solicitud")[:240]
        logger.warning("Telegram API %s rejected: description=%r", method, safe_description)
        raise TelegramBotError(safe_description)
    logger.info("Telegram API %s ok latency_ms=%s", method, int((time.monotonic() - started) * 1000))
    result = body.get("result")
    return result if isinstance(result, dict) else {}


def send_message(chat_id: int | str, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Actually send a chat message through the Telegram Bot API."""
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return bot_api_call("sendMessage", payload)


def set_webhook(url: str, secret_token: str, allowed_updates: Optional[list[str]] = None) -> Dict[str, Any]:
    """Register the production webhook (idempotent; safe to re-run)."""
    payload: Dict[str, Any] = {
        "url": url,
        "secret_token": secret_token,
        "allowed_updates": allowed_updates or ["message", "callback_query"],
        "drop_pending_updates": False,
    }
    return bot_api_call("setWebhook", payload, timeout=15.0)


def delete_webhook() -> Dict[str, Any]:
    return bot_api_call("deleteWebhook", {"drop_pending_updates": False})


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlparse((value or "").strip())
        return parsed.scheme in {"https", "http"} and bool(parsed.netloc)
    except (TypeError, ValueError):
        return False


def _is_https_url(value: str) -> bool:
    try:
        parsed = urlparse((value or "").strip())
        return parsed.scheme == "https" and bool(parsed.netloc)
    except (TypeError, ValueError):
        return False


def build_start_payload(chat_id: int | str, app_url: str, channel_url: str, community_url: str) -> Dict[str, Any]:
    """Welcome-only /start payload. Sending is handled by send_message()."""
    # Telegram rejects inline URL buttons whose URL is empty or malformed.
    # Treat the community link as optional so a bad/missing value cannot make
    # the whole /start message fail. Keep the Mini App and official channel.
    buttons: list[Dict[str, Any]] = []
    if _is_http_url(channel_url):
        buttons.append({"text": "\U0001F4E2 Canal oficial", "url": channel_url})
    if _is_http_url(community_url):
        buttons.append({"text": "\U0001F4AC Chat de la comunidad", "url": community_url})
    if _is_https_url(app_url):
        buttons.append({"text": "\U0001F680 Abrir Mini App", "web_app": {"url": app_url}})
    return {
        "chat_id": chat_id,
        "text": (
            "🇨🇺 ¡Bienvenido a <b>LiggaCuba</b>! 💜\n\n"
            "¡Hola! 👋 Nos alegra tenerte aquí.\n\n"
            "🤖 <b>¡Tu asistente inteligente está en camino!</b>\n\n"
            "La función de análisis y conversación con nuestro bot estará disponible próximamente. "
            "Estamos trabajando para ofrecerte una experiencia cada vez mejor.\n\n"
            "🚀 Mientras tanto, puedes utilizar nuestra Mini App para disfrutar de las funciones disponibles.\n\n"
            "¡Gracias por acompañarnos! ❤️"
        ),
        # One button per row produces the requested vertical mobile layout.
        "reply_markup": {"inline_keyboard": [[button] for button in buttons]},
    }


def extract_text_message(update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the message dict for plain text updates, ignoring the rest."""
    if not isinstance(update, dict):
        return None
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    if "text" not in message or not isinstance(message.get("chat"), dict):
        return None
    return message


def _processed_db_path() -> str:
    return os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "liggacuba.db"))


def init_processed_updates() -> None:
    conn = sqlite3.connect(_processed_db_path())
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS telegram_processed_updates(
                 update_id INTEGER PRIMARY KEY,
                 processed_at TEXT NOT NULL
               )"""
        )
        conn.commit()
    finally:
        conn.close()


def claim_update(update_id: int) -> bool:
    """Atomically claim an update id. Returns False if it was already handled."""
    conn = sqlite3.connect(_processed_db_path(), timeout=5)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT 1 FROM telegram_processed_updates WHERE update_id=?", (update_id,)
        ).fetchone()
        if row:
            conn.rollback()
            return False
        conn.execute(
            "INSERT INTO telegram_processed_updates(update_id, processed_at) VALUES(?,?)",
            (update_id, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        )
        conn.commit()
        return True
    except sqlite3.Error:
        conn.rollback()
        # If claiming fails, report as already-seen so Telegram redelivers
        # rather than risk executing the update twice.
        return False
    finally:
        conn.close()


def release_update(update_id: int) -> None:
    """Allow Telegram to retry an update when its processing failed."""
    conn = sqlite3.connect(_processed_db_path(), timeout=5)
    try:
        conn.execute("DELETE FROM telegram_processed_updates WHERE update_id=?", (update_id,))
        conn.commit()
    except sqlite3.Error:
        logger.exception("Telegram update claim release failed update_id=%s", update_id)
    finally:
        conn.close()


def purge_processed_updates() -> None:
    cutoff_days = PROCESSING_TTL_DAYS
    conn = sqlite3.connect(_processed_db_path())
    try:
        conn.execute(
            "DELETE FROM telegram_processed_updates WHERE processed_at < ?",
            (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - cutoff_days * 86400)),),
        )
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()


def verify_webhook_secret(received: str) -> bool:
    if not received:
        return False
    return hmac.compare_digest(received, webhook_secret())


def handle_update(update: Dict[str, Any]) -> Dict[str, Any]:
    """Process one verified update; release its claim if processing fails.

    A network timeout can be ambiguous (Telegram may have accepted a message
    before the response was lost), so retries can theoretically duplicate a
    message. This is preferable to permanently discarding every failed send.
    """
    init_processed_updates()
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        return {"handled": False, "reason": "missing_update_id"}

    if not claim_update(update_id):
        return {"handled": False, "reason": "duplicate_update"}

    try:
        # Text messages are supported by the current bot. Other message types
        # still receive a brief availability notice instead of being silently ignored.
        message = update.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("chat"), dict):
            return {"handled": True, "action": "ignored_non_message"}

        chat_id = message["chat"].get("id")
        if not isinstance(chat_id, (int, str)):
            return {"handled": True, "action": "ignored_missing_chat_id"}

        text = (message.get("text") or "").strip()
        command = text.split("@", 1)[0].split()[0].lower() if text else ""
        if command == "/start":
            payload = build_start_payload(
                chat_id,
                mini_app_url(),
                official_channel(),
                community_chat(),
            )
            send_message(payload["chat_id"], payload["text"], payload.get("reply_markup"))
            return {"handled": True, "action": "start_sent", "chat_id": chat_id}

        send_message(
            chat_id,
            "💜 Gracias por escribir a LiggaCuba. La función de análisis y conversación con el bot estará disponible próximamente. "
            "Mientras tanto, puedes utilizar nuestra Mini App desde el botón Abrir.",
        )
        return {"handled": True, "action": "availability_notice_sent", "chat_id": chat_id}
    except Exception:
        # A failed send/config lookup must not leave the update permanently
        # marked as processed. Log the update id only; the endpoint logs the
        # safe exception detail separately.
        release_update(update_id)
        raise

