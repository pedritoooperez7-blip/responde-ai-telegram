"""Limpieza automática de datos y baneo de usuarios.

Todo opera sobre una conexión sqlite3 recibida (sin FastAPI), así que se puede
probar sin levantar el servidor. ``main.py`` solo conecta estas funciones al
ciclo de purga que ya corre en segundo plano y a las rutas del panel admin.

Reglas (todas configurables por variables de entorno, ver .env.example):
  * Usuario sin Premium inactivo INACTIVE_USER_DAYS (30)  -> se borra con sus datos.
  * Usuario "fantasma" (se registró y nunca usó nada) GHOST_USER_DAYS (7) -> se borra.
  * Usuario baneado: sus datos se conservan BAN_GRACE_HOURS (48 h); si nadie lo
    desbanea en ese tiempo, sus datos se borran. El baneo en sí (solo el ID) se
    conserva para que no pueda volver a entrar como usuario nuevo.
  * Pagos sin comprobante (status 'pending') PENDING_PAYMENT_DAYS (3) -> se cancelan.
  * Registros de uso de más de USAGE_LOG_RETENTION_DAYS -> se borran. DESACTIVADO por
    defecto (0): esos registros alimentan los contadores del perfil de cada usuario.
    Los registros de los usuarios que se borran por inactividad sí desaparecen con ellos.

Nunca se borran: usuarios con Premium vigente, con plan de anuncio vigente, con
un pago pendiente o con comprobante en revisión, ni los administradores.
Los registros de pagos (payment_operations) se conservan como historial contable.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

try:
    from . import dating as _dating
except ImportError:  # uvicorn ejecutado con backend/ como directorio de trabajo
    import dating as _dating

logger = logging.getLogger(__name__)


def _env_num(name: str, default: float, minimum: float = 0) -> float:
    try:
        return max(minimum, float((os.getenv(name) or "").strip()))
    except ValueError:
        return default


def settings() -> Dict[str, Any]:
    return {
        "enabled": (os.getenv("AUTO_CLEANUP_USERS", "1").strip().lower() not in {"0", "false", "no", "off"}),
        "dry_run": (os.getenv("CLEANUP_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}),
        "inactive_days": _env_num("INACTIVE_USER_DAYS", 30, 1),
        "ghost_days": _env_num("GHOST_USER_DAYS", 7, 1),
        "ban_grace_hours": _env_num("BAN_GRACE_HOURS", 48, 0),
        "pending_payment_days": _env_num("PENDING_PAYMENT_DAYS", 3, 1),
        # 0 = desactivado (por defecto): usage_logs alimenta los contadores del perfil (Chats/Historias/Análisis).
        "usage_log_days": _env_num("USAGE_LOG_RETENTION_DAYS", 0, 0),
        "max_users_per_run": int(_env_num("CLEANUP_MAX_USERS_PER_RUN", 200, 1)),
    }


def _stamp(moment: datetime) -> str:
    """Formato de now() en main.py: UTC ISO sin zona horaria."""
    return moment.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def ensure_schema(c: sqlite3.Connection) -> None:
    c.execute(
        "CREATE TABLE IF NOT EXISTS user_bans("
        "user_id TEXT PRIMARY KEY, banned_at TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', "
        "banned_by TEXT NOT NULL DEFAULT '', data_deleted_at TEXT)"
    )
    c.commit()


# ---------------------------------------------------------------------------
# Baneo
# ---------------------------------------------------------------------------

def is_banned(c: sqlite3.Connection, uid: str) -> bool:
    return c.execute("SELECT 1 FROM user_bans WHERE user_id=?", (str(uid),)).fetchone() is not None


def ban_user(c: sqlite3.Connection, uid: str, actor: str, reason: str = "", now: Optional[datetime] = None) -> Dict[str, Any]:
    """Banea (o renueva el baneo de) un usuario y lo oculta de Citas de inmediato."""
    uid = str(uid)
    stamp = _stamp(now or datetime.now(timezone.utc))
    c.execute(
        "INSERT INTO user_bans(user_id,banned_at,reason,banned_by,data_deleted_at) VALUES(?,?,?,?,NULL) "
        "ON CONFLICT(user_id) DO UPDATE SET banned_at=excluded.banned_at,reason=excluded.reason,"
        "banned_by=excluded.banned_by,data_deleted_at=NULL",
        (uid, stamp, str(reason or "")[:300], str(actor or "")[:80]),
    )
    try:
        c.execute("UPDATE dating_profiles SET visible=0 WHERE user_id=?", (uid,))
    except sqlite3.OperationalError:
        pass  # la tabla de Citas puede no existir en instalaciones antiguas
    c.commit()
    grace = settings()["ban_grace_hours"]
    return {"user_id": uid, "banned_at": stamp, "delete_data_after_hours": grace}


def unban_user(c: sqlite3.Connection, uid: str) -> bool:
    """Quita el baneo. Devuelve False si no estaba baneado."""
    cur = c.execute("DELETE FROM user_bans WHERE user_id=?", (str(uid),))
    c.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Borrado de datos de un usuario
# ---------------------------------------------------------------------------

_USER_TABLES = (
    ("usage_logs", "user_id"),
    ("saved_situations", "user_id"),
    ("analysis_attempts", "user_id"),
    ("ai_idempotency", "user_id"),
    ("ai_generation_events", "user_id"),
)


def delete_user_data(c: sqlite3.Connection, uid: str, photos_dir: str, delete_account: bool = True) -> Dict[str, int]:
    """Borra todo lo que la app guarda de una persona.

    Conserva (a propósito): los pagos (historial contable), los reportes de
    seguridad de Citas y el registro de baneo (solo el ID).
    """
    uid = str(uid)
    counts: Dict[str, int] = {}
    try:
        photos = c.execute("SELECT COUNT(*) FROM dating_photos WHERE user_id=?", (uid,)).fetchone()[0]
        _dating.delete_dating_data(c, uid, photos_dir)  # perfil, fotos (disco + R2), swipes, matches, bloqueos
        counts["dating_photos"] = int(photos)
    except sqlite3.OperationalError:
        pass
    for table, column in _USER_TABLES:
        try:
            counts[table] = c.execute(f"DELETE FROM {table} WHERE {column}=?", (uid,)).rowcount
        except sqlite3.OperationalError:
            pass
    try:
        counts["ads"] = c.execute("DELETE FROM ads WHERE source='business' AND owner_user_id=?", (uid,)).rowcount
    except sqlite3.OperationalError:
        pass
    if delete_account:
        counts["users"] = c.execute("DELETE FROM users WHERE user_id=?", (uid,)).rowcount
    c.commit()
    return counts


# ---------------------------------------------------------------------------
# Limpieza automática
# ---------------------------------------------------------------------------

def find_inactive_users(c: sqlite3.Connection, cutoff: str, now_stamp: str, protected: Iterable[str], limit: int) -> List[str]:
    """Usuarios sin Premium vigente cuya última actividad es anterior a ``cutoff``.

    Última actividad = lo más reciente entre users.updated_at (se actualiza cada vez
    que abren la app) y el último registro de uso.
    """
    rows = c.execute(
        """
        SELECT u.user_id FROM users u
        WHERE (u.premium_until IS NULL OR u.premium_until='' OR u.premium_until < :now)
          AND MAX(COALESCE(u.updated_at,''), COALESCE((SELECT MAX(l.used_at) FROM usage_logs l WHERE l.user_id=u.user_id),'')) < :cutoff
          AND NOT EXISTS (SELECT 1 FROM ads a WHERE a.owner_user_id=u.user_id AND a.source='business' AND a.paid_until > :now)
          AND NOT EXISTS (SELECT 1 FROM payment_operations p WHERE p.user_id=u.user_id AND p.status IN ('pending','proof_submitted'))
          AND NOT EXISTS (SELECT 1 FROM user_bans b WHERE b.user_id=u.user_id)
        ORDER BY u.updated_at LIMIT :limit
        """,
        {"now": now_stamp, "cutoff": cutoff, "limit": int(limit) + len(list(protected))},
    ).fetchall()
    protected = {str(p) for p in protected}
    return [r[0] for r in rows if str(r[0]) not in protected][: int(limit)]


def find_ghost_users(c: sqlite3.Connection, cutoff: str, protected: Iterable[str], limit: int) -> List[str]:
    """Cuentas que se registraron y nunca hicieron nada (típico de bots)."""
    rows = c.execute(
        """
        SELECT u.user_id FROM users u
        WHERE u.created_at < :cutoff AND COALESCE(u.updated_at,u.created_at) < :cutoff
          AND (u.premium_until IS NULL OR u.premium_until='')
          AND NOT EXISTS (SELECT 1 FROM usage_logs l WHERE l.user_id=u.user_id)
          AND NOT EXISTS (SELECT 1 FROM saved_situations s WHERE s.user_id=u.user_id)
          AND NOT EXISTS (SELECT 1 FROM payment_operations p WHERE p.user_id=u.user_id)
          AND NOT EXISTS (SELECT 1 FROM dating_profiles d WHERE d.user_id=u.user_id)
          AND NOT EXISTS (SELECT 1 FROM ads a WHERE a.owner_user_id=u.user_id)
          AND NOT EXISTS (SELECT 1 FROM user_bans b WHERE b.user_id=u.user_id)
        ORDER BY u.created_at LIMIT :limit
        """,
        {"cutoff": cutoff, "limit": int(limit) + len(list(protected))},
    ).fetchall()
    protected = {str(p) for p in protected}
    return [r[0] for r in rows if str(r[0]) not in protected][: int(limit)]


def run_cleanup(
    c: sqlite3.Connection,
    photos_dir: str,
    protected: Iterable[str] = (),
    now: Optional[datetime] = None,
    config: Optional[Dict[str, Any]] = None,
    on_delete: Optional[Callable[[str, str, Dict[str, int]], None]] = None,
) -> Dict[str, Any]:
    """Ejecuta una pasada de limpieza. Un fallo con un usuario no detiene a los demás.

    ``on_delete(uid, motivo, conteos)`` se llama tras cada usuario borrado (para auditoría).
    Con CLEANUP_DRY_RUN=1 solo cuenta lo que se borraría, sin tocar nada.
    """
    cfg = dict(settings())
    cfg.update(config or {})
    result: Dict[str, Any] = {"inactive": 0, "ghost": 0, "banned": 0, "payments_cancelled": 0, "usage_logs": 0,
                              "dry_run": bool(cfg["dry_run"]), "errors": 0}
    if not cfg["enabled"]:
        result["disabled"] = True
        return result
    ensure_schema(c)
    moment = now or datetime.now(timezone.utc)
    now_stamp = _stamp(moment)
    protected = {str(p) for p in protected} | {"guest-user"}
    budget = int(cfg["max_users_per_run"])

    def purge(uids: List[str], reason: str, key: str) -> None:
        nonlocal budget
        for uid in uids:
            if budget <= 0:
                return
            budget -= 1
            if cfg["dry_run"]:
                result[key] += 1
                logger.warning("Cleanup (dry-run): would delete user=%s reason=%s", uid, reason)
                continue
            try:
                counts = delete_user_data(c, uid, photos_dir)
                result[key] += 1
                if on_delete:
                    on_delete(uid, reason, counts)
            except Exception:  # noqa: BLE001
                c.rollback()
                result["errors"] += 1
                logger.warning("Cleanup failed for one user (reason=%s); continuing", reason, exc_info=True)

    # 1) Baneados cuya gracia ya venció (los datos se borran; el registro de baneo queda).
    ban_cutoff = _stamp(moment - timedelta(hours=float(cfg["ban_grace_hours"])))
    due = [r[0] for r in c.execute(
        "SELECT user_id FROM user_bans WHERE data_deleted_at IS NULL AND banned_at <= ? LIMIT ?", (ban_cutoff, budget)).fetchall()]
    due = [u for u in due if u not in protected]
    purge(due, "ban_expired", "banned")
    if not cfg["dry_run"]:
        for uid in due:
            if c.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone() is None:
                c.execute("UPDATE user_bans SET data_deleted_at=? WHERE user_id=?", (now_stamp, uid))
        c.commit()

    # 2) Inactivos sin Premium.
    inactive_cutoff = _stamp(moment - timedelta(days=float(cfg["inactive_days"])))
    if budget > 0:
        purge(find_inactive_users(c, inactive_cutoff, now_stamp, protected, budget), "inactive", "inactive")

    # 3) Cuentas fantasma (bots que nunca usaron la app).
    ghost_cutoff = _stamp(moment - timedelta(days=float(cfg["ghost_days"])))
    if budget > 0:
        purge(find_ghost_users(c, ghost_cutoff, protected, budget), "ghost", "ghost")

    # 4) Pagos sin comprobante y registros de uso viejos.
    if not cfg["dry_run"]:
        pay_cutoff = _stamp(moment - timedelta(days=float(cfg["pending_payment_days"])))
        try:
            result["payments_cancelled"] = c.execute(
                "UPDATE payment_operations SET status='cancelled',cancelled_at=?,updated_at=? WHERE status='pending' AND created_at < ?",
                (now_stamp, now_stamp, pay_cutoff)).rowcount
            if float(cfg["usage_log_days"]) > 0:
                result["usage_logs"] = c.execute(
                    "DELETE FROM usage_logs WHERE used_at < ?", (_stamp(moment - timedelta(days=float(cfg["usage_log_days"]))),)).rowcount
            c.commit()
        except sqlite3.OperationalError:
            c.rollback()
    return result
