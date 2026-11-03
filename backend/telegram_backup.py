"""Periodic SQLite backup delivered to a private Telegram chat.

* Uses SQLite's online backup API (consistent copy, no downtime, no locks held).
* Output is gzip-compressed; if BACKUP_ENCRYPTION_KEY is set it is also encrypted
  with Fernet (recommended: the database contains personal data).
* Disabled automatically when there is no bot token, no target chat, or the
  database is not a real file. Failures are logged and retried next cycle; they
  never affect the API.
"""
import base64
import gzip
import hashlib
import logging
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

TELEGRAM_FILE_LIMIT = 49 * 1024 * 1024  # Bot API upload limit is 50 MB
DEFAULT_INTERVAL_HOURS = 6.0
FIRST_RUN_DELAY_SECONDS = 600


def backup_chat_id() -> str:
    return (os.getenv("BACKUP_CHAT_ID") or os.getenv("PAYMENT_ARCHIVE_CHAT_ID") or "").strip()


def interval_seconds() -> float:
    try:
        hours = float((os.getenv("BACKUP_INTERVAL_HOURS") or "").strip())
    except ValueError:
        hours = DEFAULT_INTERVAL_HOURS
    return max(0.25, hours) * 3600


def _fernet():
    secret = (os.getenv("BACKUP_ENCRYPTION_KEY") or "").strip()
    if not secret:
        return None
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest()))


def build_backup(db_path: str) -> tuple[bytes, str]:
    """Return (payload, filename) for a consistent snapshot of the database."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
        try:
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        with open(tmp, "rb") as handle:
            raw = handle.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    payload = gzip.compress(raw, compresslevel=6)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"liggacuba-{stamp}.db.gz"
    fernet = _fernet()
    if fernet:
        payload = fernet.encrypt(payload)
        name += ".enc"
    return payload, name


def run_backup_once(db_path: str, send_document: Callable[..., dict], chat_id: Optional[str] = None) -> bool:
    chat = (chat_id or backup_chat_id())
    if not chat:
        return False
    payload, name = build_backup(db_path)
    if len(payload) > TELEGRAM_FILE_LIMIT:
        logger.error("Telegram backup skipped: %s bytes exceeds the Bot API limit; use an external backup", len(payload))
        return False
    encrypted = name.endswith(".enc")
    caption = (f"<b>Backup LiggaCuba</b>\n{name}\n{len(payload) // 1024} KB"
               f"{' · cifrado' if encrypted else ' · SIN CIFRAR (define BACKUP_ENCRYPTION_KEY)'}")
    result = send_document(chat, payload, name, caption)
    if not str(result.get("message_id") or "").strip():
        raise RuntimeError("Telegram no devolvió message_id para el backup")
    logger.info("Telegram backup sent name=%s bytes=%s", name, len(payload))
    return True


_started = False
_lock = threading.Lock()


def start_backup_worker(db_path: str, send_document: Callable[..., dict]) -> bool:
    global _started
    with _lock:
        if _started or (os.getenv("DISABLE_TELEGRAM_BACKUP") or "").strip().lower() in {"1", "true", "yes"}:
            return False
        if not backup_chat_id() or not (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip():
            return False
        if not db_path or db_path == ":memory:" or not os.path.isfile(db_path):
            return False

        def loop():
            time.sleep(FIRST_RUN_DELAY_SECONDS)
            while True:
                try:
                    run_backup_once(db_path, send_document)
                except Exception as exc:  # never let a backup failure touch the API
                    logger.warning("Telegram backup failed: error_type=%s reason=%s", type(exc).__name__, str(exc)[:200])
                time.sleep(interval_seconds())

        threading.Thread(target=loop, name="telegram-db-backup", daemon=True).start()
        _started = True
        return True
