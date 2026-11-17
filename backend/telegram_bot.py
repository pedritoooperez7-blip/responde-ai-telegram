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


def send_photo(chat_id: int | str, photo: bytes, filename: str = "comprobante.jpg", caption: str = "", reply_markup: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Send a photo to Telegram using multipart/form-data without persisting it locally.

    Optional ``reply_markup`` attaches inline buttons under the photo (Telegram supports this).
    """
    boundary = "----LiggaCubaBoundary" + hashlib.sha256(os.urandom(16)).hexdigest()[:24]
    fields = {"chat_id": str(chat_id), "caption": (caption or "")[:900], "parse_mode": "HTML"}
    if reply_markup is not None:
        fields["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    chunks = []
    for name, value in fields.items():
        chunks.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode("utf-8"))
    safe_name = os.path.basename(filename or "comprobante.jpg").replace('"', "")[:100]
    chunks.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{safe_name}\"\r\nContent-Type: image/jpeg\r\n\r\n").encode("utf-8"))
    chunks.append(photo)
    chunks.append(f"\r\n--{boundary}--\r\n".encode("ascii"))
    url = f"{TELEGRAM_API_BASE}/bot{bot_token()}/sendPhoto"
    request = urllib.request.Request(url, data=b"".join(chunks), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15.0) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", errors="replace")).get("description", "")
        except Exception:
            detail = ""
        raise TelegramBotError(f"Telegram sendPhoto falló (HTTP {exc.code}): {str(detail)[:180]}") from None
    except (TimeoutError, OSError, ValueError):
        raise TelegramBotError("No se pudo confirmar el envío de la foto a Telegram") from None
    if not isinstance(body, dict) or body.get("ok") is not True:
        raise TelegramBotError(str(body.get("description", "Telegram rechazó la foto"))[:220] if isinstance(body, dict) else "Respuesta inválida de Telegram")
    result = body.get("result")
    return result if isinstance(result, dict) else {}


def send_document(chat_id: int | str, document: bytes, filename: str = "backup.bin", caption: str = "") -> Dict[str, Any]:
    """Send a file to Telegram (multipart). Used for database backups; nothing is stored locally."""
    boundary = "----LiggaCubaBoundary" + hashlib.sha256(os.urandom(16)).hexdigest()[:24]
    fields = {"chat_id": str(chat_id), "caption": (caption or "")[:900], "parse_mode": "HTML"}
    chunks = []
    for name, value in fields.items():
        chunks.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode("utf-8"))
    safe_name = os.path.basename(filename or "backup.bin").replace('"', "")[:100]
    chunks.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{safe_name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode("utf-8"))
    chunks.append(document)
    chunks.append(f"\r\n--{boundary}--\r\n".encode("ascii"))
    url = f"{TELEGRAM_API_BASE}/bot{bot_token()}/sendDocument"
    request = urllib.request.Request(url, data=b"".join(chunks), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=90.0) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", errors="replace")).get("description", "")
        except Exception:
            detail = ""
        raise TelegramBotError(f"Telegram sendDocument falló (HTTP {exc.code}): {str(detail)[:180]}") from None
    except (TimeoutError, OSError, ValueError):
        raise TelegramBotError("No se pudo confirmar el envío del archivo a Telegram") from None
    if not isinstance(body, dict) or body.get("ok") is not True:
        raise TelegramBotError(str(body.get("description", "Telegram rechazó el archivo"))[:220] if isinstance(body, dict) else "Respuesta inválida de Telegram")
    result = body.get("result")
    return result if isinstance(result, dict) else {}


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


def parse_command(text: str) -> str:
    """Return the lower-case command of a message, or "" when there is none.

    Handles empty/whitespace-only text and texts starting with "@" (which used
    to raise IndexError), and keeps the Telegram "/start@botname" form working.
    """
    parts = (text or "").split()
    if not parts:
        return ""
    return parts[0].split("@", 1)[0].lower()


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
        command = parse_command(text)
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



# =============================================================================
# Fase 5 — Control de bots de citas (grupo de Telegram + replies)
# =============================================================================
# Esta sección coexiste con las funciones de módulo de arriba.
# main.py instancia:  _dating_bot = TelegramBot()
# y pasa:             bot_control=_dating_bot.send_bot_control_event
# y llama en webhook: _dating_bot.process_update_from_main(update)

_CONTROL_TAG_RE = re.compile(r"\[BOT_CHAT:(\d+)\]")


def _esc(s: Any) -> str:
    """Escapa caracteres HTML especiales para parse_mode HTML de Telegram."""
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _validate_control_group_id(raw: str) -> Optional[str]:
    """Valida que el ID del grupo de control sea un entero negativo."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        val = int(raw)
    except ValueError:
        logger.error(
            "BOTS_CONTROL_GROUP_ID no es un entero ('%s'). Los eventos de bots se silenciarán.",
            raw,
        )
        return None
    if val >= 0:
        logger.error(
            "BOTS_CONTROL_GROUP_ID es positivo (%d). Debe ser un ID negativo (grupo/supergrupo).",
            val,
        )
        return None
    return str(val)


def _parse_admin_ids(raw: str) -> Set[str]:
    """Parsea BOTS_CONTROL_ADMIN_IDS: lista de IDs numéricos separados por coma."""
    ids: Set[str] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if part:
            try:
                ids.add(str(int(part)))
            except ValueError:
                logger.warning("BOTS_CONTROL_ADMIN_IDS: '%s' no es un ID válido.", part)
    return ids


class TelegramBot:
    """Control de bots de citas: notificaciones al grupo y replies desde Telegram.

    No sustituye a send_message / handle_update del módulo. Solo gestiona
    el grupo BOTS_CONTROL_GROUP_ID y las respuestas admin → usuario vía API interna.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        bots_control_group_id: Optional[str] = None,
        admin_api_token: Optional[str] = None,
        internal_base_url: Optional[str] = None,
    ) -> None:
        # Preferir TELEGRAM_BOT_TOKEN (estándar del repo); BOT_TOKEN como fallback
        self.token = (
            token
            or (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
            or (os.getenv("BOT_TOKEN") or "").strip()
        )
        raw_ctrl = bots_control_group_id or os.getenv("BOTS_CONTROL_GROUP_ID", "")
        self.bots_control_group_id = _validate_control_group_id(raw_ctrl)
        self.admin_api_token = admin_api_token or (os.getenv("ADMIN_API_TOKEN") or os.getenv("ADMIN_KEY") or "")
        configured_base = (internal_base_url or os.getenv("INTERNAL_BASE_URL") or "").strip()
        if not configured_base:
            # El proceso escucha ${PORT:-10000} (Dockerfile / railway.json), no el 8000.
            configured_base = "http://127.0.0.1:" + (os.getenv("PORT") or "10000").strip()
        self.internal_base_url = configured_base.rstrip("/")
        self.control_admin_ids: Set[str] = _parse_admin_ids(os.getenv("BOTS_CONTROL_ADMIN_IDS", ""))
        self.admin_api_header = os.getenv("ADMIN_API_HEADER", "X-Admin-Key")
        if not self.token:
            logger.warning("TelegramBot (bots): no hay TELEGRAM_BOT_TOKEN/BOT_TOKEN — eventos de bots silenciados.")

    def _api_url(self, method: str) -> str:
        return f"{TELEGRAM_API_BASE}/bot{self.token}/{method}"

    def _post_telegram(self, method: str, payload: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
        if not self.token:
            return {}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._api_url(method),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if not body.get("ok"):
                logger.warning("Telegram %s no OK: %s", method, str(body)[:200])
            return body if isinstance(body, dict) else {}
        except Exception as exc:
            logger.debug("Telegram %s error: %s", method, exc)
            return {}

    def send_bot_control_event(self, event: str, payload: Dict[str, Any]) -> None:
        """Reenvía eventos de bots al grupo de control. Se pasa como bot_control= a dating.build_router."""
        if not self.bots_control_group_id or not self.token:
            return
        try:
            mid = payload.get("match_id", "?")
            if event == "bot_message":
                tag = f"[BOT_CHAT:{mid}]"
                body_preview = _esc(str(payload.get("body", ""))[:300])
                text = (
                    f"💬 <b>Mensaje para el bot</b> {tag}\n"
                    f"Bot: <b>{_esc(payload.get('bot_name', '?'))}</b>\n"
                    f"De: <b>{_esc(payload.get('real_name', '?'))}</b> "
                    f"(<code>{_esc(payload.get('real_id', '?'))}</code>)\n"
                    f"Match ID: <code>{_esc(mid)}</code>\n\n"
                    f"{body_preview}\n\n"
                    f"<i>↩️ Responde a ESTE mensaje para contestar como el bot.</i>"
                )
            elif event == "bot_match":
                text = (
                    f"💜 <b>Nuevo match con bot</b>\n"
                    f"Bot: <b>{_esc(payload.get('bot_name', '?'))}</b>\n"
                    f"Usuario: <b>{_esc(payload.get('real_name', '?'))}</b> "
                    f"(<code>{_esc(payload.get('real_id', '?'))}</code>)\n"
                    f"Match ID: <code>{_esc(mid)}</code>"
                )
            elif event == "bot_admin_reply":
                body_preview = _esc(str(payload.get("body", ""))[:300])
                text = (
                    f"✅ <b>Respuesta enviada como bot</b>\n"
                    f"Bot: <b>{_esc(payload.get('bot_name', '?'))}</b>\n"
                    f"Para: <code>{_esc(payload.get('real_id', '?'))}</code>\n"
                    f"Por: <b>{_esc(payload.get('actor', '?'))}</b>\n\n"
                    f"{body_preview}"
                )
            else:
                text = f"ℹ️ Evento bots: <code>{_esc(event)}</code>\n<pre>{_esc(json.dumps(payload, ensure_ascii=False)[:500])}</pre>"

            self._post_telegram(
                "sendMessage",
                {
                    "chat_id": self.bots_control_group_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        except Exception as exc:
            logger.debug("send_bot_control_event error (event=%s): %s", event, exc)

    def process_update_from_main(self, update: Dict[str, Any]) -> bool:
        """Procesa replies del grupo de control.

        Devuelve False solo si había que entregar una respuesta y el POST interno falló
        (el caller debe soltar el claim para que Telegram reintente).
        Sin tag, sin texto o sin permiso: True, y no se envía nada.
        """
        try:
            message = update.get("message")
            if not isinstance(message, dict):
                return True
            chat_id = str((message.get("chat") or {}).get("id", ""))
            if self.bots_control_group_id and chat_id == str(self.bots_control_group_id):
                return self._handle_control_message(message)
            return True
        except Exception as exc:
            logger.debug("process_update_from_main error: %s", exc)
            return False

    def _handle_control_message(self, message: Dict[str, Any]) -> bool:
        """Solo actúa sobre replies a mensajes que llevan el tag [BOT_CHAT:N]."""
        reply = message.get("reply_to_message") or {}
        reply_text = (reply.get("text") or reply.get("caption") or "") if reply else ""
        m = _CONTROL_TAG_RE.search(reply_text)
        if not m:
            logger.debug("_handle_control_message: sin tag BOT_CHAT, ignorado.")
            return True

        from_user = message.get("from") or {}
        actor_id = str(from_user.get("id", ""))
        if self.control_admin_ids and actor_id not in self.control_admin_ids:
            logger.warning(
                "Reply en grupo de control de ID no autorizado: %s", actor_id
            )
            return True

        match_id = int(m.group(1))
        reply_text_body = (message.get("text") or "").strip()
        if not reply_text_body:
            return True

        actor_name = from_user.get("username") or from_user.get("first_name") or actor_id
        actor_name = str(actor_name).replace("\r", " ").replace("\n", " ").strip()[:64]
        return self._post_bot_reply(match_id, reply_text_body, actor=f"tg:{actor_name}")

    def _post_bot_reply(self, match_id: int, body: str, actor: str = "telegram_admin") -> bool:
        """POST interno a /api/admin/dating/bots/reply."""
        url = f"{self.internal_base_url}/api/admin/dating/bots/reply"
        payload = json.dumps(
            {"match_id": match_id, "body": body, "actor": actor},
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.admin_api_token and self.admin_api_header:
            headers[self.admin_api_header] = self.admin_api_token

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status = getattr(resp, "status", 200)
                if status not in (200, 201):
                    raw = resp.read()[:200]
                    logger.warning(
                        "_post_bot_reply falló: match_id=%d status=%s body=%s",
                        match_id, status, raw,
                    )
                    return False
            logger.info("_post_bot_reply OK: match_id=%d actor=%s", match_id, actor)
            return True
        except urllib.error.HTTPError as exc:
            logger.warning(
                "_post_bot_reply HTTPError: match_id=%d status=%s body=%s",
                match_id, exc.code, (exc.read() or b"")[:200],
            )
            return False
        except Exception as exc:
            logger.error("_post_bot_reply error: match_id=%d %s", match_id, exc)
            return False
