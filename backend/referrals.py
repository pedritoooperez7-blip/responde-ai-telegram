"""Motor de referidos de LiggaCuba.

Responsabilidades:
  - Atribución automática vía startapp / manual vía código
  - Motor de recompensas Premium (3 días, atómica, idempotente)
  - Historial de invitaciones y recompensas
  - Estadísticas personales y administrativas
  - Detección de anomalías

Reglas de negocio invariables:
  - Un usuario solo puede tener UN invitador (ever).
  - No se permiten auto-referidos.
  - La recompensa se acredita una sola vez por referido.
  - Solo pagos Premium elegibles (no anuncios, no rechazados).
  - La acreditación es atómica: transacción + UNIQUE constraint.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Estados de invitación
# ---------------------------------------------------------------------------
STATUS_REGISTERED = "registered"        # Invitación registrada, pendiente de Premium
STATUS_PREMIUM_ACTIVE = "premium_active"  # Invitado activó Premium
STATUS_REWARDED = "rewarded"            # Recompensa acreditada al invitador
STATUS_NOT_ELIGIBLE = "not_eligible"    # Pago no elegible (anuncio, etc.)
STATUS_REVIEW = "admin_review"          # Anomalía detectada, en revisión

REWARD_DAYS = 3  # Días de Premium que recibe el invitador


# ---------------------------------------------------------------------------
# Migraciones de esquema
# ---------------------------------------------------------------------------

def run_migrations(c: sqlite3.Connection) -> None:
    """Aplica las migraciones necesarias sin destruir datos existentes."""

    # Nuevas columnas en referrals
    migrations = [
        "ALTER TABLE referrals ADD COLUMN status TEXT NOT NULL DEFAULT 'registered'",
        "ALTER TABLE referrals ADD COLUMN rewarded_at TEXT",
        "ALTER TABLE referrals ADD COLUMN reward_payment_id TEXT",
        "ALTER TABLE referrals ADD COLUMN confirmed_at TEXT",
        "ALTER TABLE referrals ADD COLUMN anomaly_flag INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE referrals ADD COLUMN anomaly_reason TEXT",
        "ALTER TABLE referrals ADD COLUMN inviter_notified INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE referrals ADD COLUMN invitee_notified INTEGER NOT NULL DEFAULT 0",
        # reward_idempotency_key garantiza atomicidad ante procesos concurrentes
        "ALTER TABLE referrals ADD COLUMN reward_idempotency_key TEXT",
        "ALTER TABLE referrals ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'",
        "ALTER TABLE referrals ADD COLUMN updated_at TEXT",
    ]

    for sql in migrations:
        try:
            c.execute(sql)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise

    # Índices de rendimiento y unicidad
    index_statements = [
        # Unicidad: un solo referral por invitado (ya existe UNIQUE en referred_id,
        # pero la columna reward_idempotency_key necesita su propio índice único)
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_referrals_idempotency ON referrals(reward_idempotency_key) WHERE reward_idempotency_key IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)",
        "CREATE INDEX IF NOT EXISTS idx_referrals_status ON referrals(status)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_refer_code ON users(refer_code) WHERE refer_code IS NOT NULL",
    ]

    for sql in index_statements:
        try:
            c.execute(sql)
        except (sqlite3.OperationalError, sqlite3.IntegrityError) as exc:
            # El índice UNIQUE puede fallar si hay duplicados legacy en refer_code.
            # No se bloquea el arranque; los checks de runtime siguen activos.
            logger.warning("referrals migration index skipped: %s", exc)

    # Tabla de log de auditoría de acciones administrativas sobre referidos
    c.execute("""
        CREATE TABLE IF NOT EXISTS referral_audit_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_username TEXT NOT NULL,
            action TEXT NOT NULL,
            referral_id INTEGER,
            details TEXT,
            created_at TEXT NOT NULL
        )
    """)

    c.commit()


# ---------------------------------------------------------------------------
# Generación de código
# ---------------------------------------------------------------------------

def ensure_refer_code(c: sqlite3.Connection, uid: str) -> str:
    """Devuelve (creando si es necesario) el código de referido permanente del usuario."""
    row = c.execute("SELECT refer_code FROM users WHERE user_id=?", (uid,)).fetchone()
    if row and row["refer_code"]:
        return row["refer_code"]

    # Código determinista basado en uid para evitar duplicados en reinicios
    code = hashlib.sha256(f"ref-{uid}-liggacuba".encode()).hexdigest()[:8].upper()

    # Colisión extremadamente improbable, pero la gestionamos
    existing = c.execute("SELECT user_id FROM users WHERE refer_code=?", (code,)).fetchone()
    if existing and existing["user_id"] != uid:
        # Fallback con más entropía
        code = hashlib.sha256(f"ref2-{uid}-{_now()}-liggacuba".encode()).hexdigest()[:8].upper()

    c.execute(
        "UPDATE users SET refer_code=?, updated_at=? WHERE user_id=?",
        (code, _now(), uid),
    )
    c.commit()
    return code


# ---------------------------------------------------------------------------
# Atribución
# ---------------------------------------------------------------------------

def apply_referral(
    c: sqlite3.Connection,
    uid: str,
    code: str,
    source: str = "manual",
) -> Dict[str, Any]:
    """Registra una atribución única e inmutable para un usuario autenticado."""
    code = (code or "").strip().upper()
    if not code:
        return {"success": False, "error": "code_required", "message": "Código de referido requerido"}
    if source not in {"manual", "startapp"}:
        source = "manual"

    referrer = c.execute("SELECT user_id FROM users WHERE refer_code=?", (code,)).fetchone()
    if not referrer:
        return {"success": False, "error": "code_not_found", "message": "Código de referido no válido"}
    referrer_id = str(referrer["user_id"])
    if referrer_id == str(uid):
        return {"success": False, "error": "self_referral", "message": "No puedes usar tu propio código"}

    try:
        # Serializa solicitudes concurrentes: solo una atribución puede ganar.
        c.execute("BEGIN IMMEDIATE")
        existing = c.execute(
            "SELECT id, referrer_id FROM referrals WHERE referred_id=?", (uid,)
        ).fetchone()
        if existing:
            c.rollback()
            if str(existing["referrer_id"]) == referrer_id:
                return {"success": True, "already_registered": True, "referrer_id": referrer_id,
                        "message": "Código ya registrado"}
            return {"success": False, "error": "already_referred",
                    "message": "Ya tienes un código de referido registrado"}

        user_row = c.execute(
            "SELECT referred_by, created_at FROM users WHERE user_id=?", (uid,)
        ).fetchone()
        if not user_row:
            c.rollback()
            return {"success": False, "error": "user_not_found", "message": "Usuario no encontrado"}
        if user_row["referred_by"]:
            c.rollback()
            return {"success": False, "error": "already_referred",
                    "message": "Ya tienes un código de referido registrado"}

        # Evitar atribución retroactiva: solo usuarios recién creados, sin pagos Premium previos.
        prior_payment = c.execute(
            "SELECT 1 FROM payment_operations WHERE user_id=? AND status='verified' LIMIT 1",
            (uid,),
        ).fetchone()
        if prior_payment:
            c.rollback()
            return {"success": False, "error": "not_new_user",
                    "message": "Los códigos de referido solo pueden aplicarse antes del primer pago Premium"}

        t = _now()
        referrer_phone = c.execute(
            "SELECT payment_phone FROM users WHERE user_id=?", (referrer_id,)
        ).fetchone()
        invitee_phone = c.execute(
            "SELECT payment_phone FROM users WHERE user_id=?", (uid,)
        ).fetchone()
        same_phone = bool(
            referrer_phone and invitee_phone
            and referrer_phone["payment_phone"] and invitee_phone["payment_phone"]
            and str(referrer_phone["payment_phone"]).strip() == str(invitee_phone["payment_phone"]).strip()
        )
        initial_status = STATUS_REVIEW if same_phone else STATUS_REGISTERED
        anomaly_reason = "Mismo teléfono de pago en invitador e invitado; requiere revisión" if same_phone else None
        c.execute(
            """INSERT INTO referrals(referrer_id, referred_id, rewarded, status, source,
                                     anomaly_flag, anomaly_reason, created_at, updated_at)
               VALUES(?, ?, 0, ?, ?, ?, ?, ?, ?)""",
            (referrer_id, uid, initial_status, source, 1 if same_phone else 0,
             anomaly_reason, t, t),
        )
        c.execute(
            "UPDATE users SET referred_by=?, updated_at=? WHERE user_id=? AND (referred_by IS NULL OR referred_by='')",
            (referrer_id, t, uid),
        )
        if c.execute("SELECT changes()").fetchone()[0] != 1:
            c.rollback()
            return {"success": False, "error": "already_referred",
                    "message": "Ya tienes un código de referido registrado"}
        c.commit()
        return {"success": True, "referrer_id": referrer_id, "source": source,
                "anomaly": same_phone,
                "message": ("Código registrado y enviado a revisión de seguridad."
                            if same_phone else
                            "¡Código registrado! Cuando actives Premium, tu amigo ganará 3 días.")}
    except sqlite3.IntegrityError:
        c.rollback()
        existing = c.execute(
            "SELECT referrer_id FROM referrals WHERE referred_id=?", (uid,)
        ).fetchone()
        if existing and str(existing["referrer_id"]) == referrer_id:
            return {"success": True, "already_registered": True, "referrer_id": referrer_id,
                    "message": "Código ya registrado"}
        return {"success": False, "error": "already_referred",
                "message": "Ya tienes un código de referido registrado"}


# ---------------------------------------------------------------------------
# Motor de recompensas
# ---------------------------------------------------------------------------

def reward_referrer(c: sqlite3.Connection, invitee_uid: str, payment_operation_id: str) -> bool:
    """Acredita una sola recompensa por el primer pago Premium verificado posterior a la atribución."""
    if not payment_operation_id:
        return False
    try:
        c.execute("BEGIN IMMEDIATE")
        ref = c.execute(
            """SELECT id, referrer_id, rewarded, status, created_at
               FROM referrals WHERE referred_id=? AND rewarded=0
                 AND status NOT IN (?, ?)""",
            (invitee_uid, STATUS_NOT_ELIGIBLE, STATUS_REVIEW),
        ).fetchone()
        if not ref:
            c.rollback()
            return False

        payment = c.execute(
            """SELECT operation_id, user_id, plan, status, verified_at
               FROM payment_operations WHERE operation_id=?""",
            (payment_operation_id,),
        ).fetchone()
        if not payment or str(payment["user_id"]) != str(invitee_uid) or payment["status"] != "verified":
            c.rollback()
            return False

        # No atribuir recompensas por pagos anteriores a la invitación ni por renovaciones.
        verified_at = payment["verified_at"] or _now()
        if str(verified_at) < str(ref["created_at"]):
            c.rollback()
            return False
        earlier = c.execute(
            """SELECT 1 FROM payment_operations
               WHERE user_id=? AND status='verified'
                 AND operation_id<>?
                 AND COALESCE(verified_at, created_at) <= ?
               LIMIT 1""",
            (invitee_uid, payment_operation_id, verified_at),
        ).fetchone()
        if earlier:
            c.rollback()
            return False

        referrer_id = ref["referrer_id"]
        row = c.execute("SELECT premium_until FROM users WHERE user_id=?", (referrer_id,)).fetchone()
        if not row:
            c.rollback()
            return False
        current = row["premium_until"]
        if current:
            try:
                base = _parse_dt(current)
                if base < datetime.utcnow():
                    base = datetime.now(timezone.utc)
            except Exception:
                base = datetime.now(timezone.utc)
        else:
            base = datetime.now(timezone.utc)
        until = (base + timedelta(days=REWARD_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
        t = _now()
        idempotency_key = f"ref_{ref['id']}_pay_{payment_operation_id}"

        c.execute("UPDATE users SET premium_until=?, updated_at=? WHERE user_id=?",
                  (until, t, referrer_id))
        c.execute(
            """UPDATE referrals SET rewarded=1, status=?, rewarded_at=?,
               reward_payment_id=?, reward_idempotency_key=?, confirmed_at=?, updated_at=?
               WHERE id=? AND rewarded=0""",
            (STATUS_REWARDED, t, payment_operation_id, idempotency_key, verified_at, t, ref["id"]),
        )
        if c.execute("SELECT changes()").fetchone()[0] != 1:
            c.rollback()
            return False
        c.commit()
        return True
    except sqlite3.IntegrityError:
        c.rollback()
        return False
    except Exception as exc:
        logger.warning("reward_referrer failed for invitee=%s payment=%s: %s",
                       invitee_uid, payment_operation_id, exc)
        c.rollback()
        return False


def mark_referral_premium_active(c: sqlite3.Connection, invitee_uid: str, payment_operation_id: str = "") -> None:
    """
    Marca el referral como premium_active cuando el invitado activa su primera suscripción.
    Se llama antes de reward_referrer para mantener trazabilidad del estado intermedio.
    """
    t = _now()
    try:
        c.execute(
            """UPDATE referrals
               SET status=?, confirmed_at=?, reward_payment_id=COALESCE(NULLIF(?, ''), reward_payment_id), updated_at=?
               WHERE referred_id=? AND rewarded=0 AND status=?""",
            (STATUS_PREMIUM_ACTIVE, t, payment_operation_id, t, invitee_uid, STATUS_REGISTERED),
        )
        c.commit()
    except Exception as exc:
        logger.warning("mark_referral_premium_active failed for %s: %s", invitee_uid, exc)


# ---------------------------------------------------------------------------
# Conciliación de recompensas pendientes
# ---------------------------------------------------------------------------

def reconcile_pending_rewards(c: sqlite3.Connection) -> List[Dict]:
    """
    Detecta referidos con status=premium_active pero rewarded=0 cuya recompensa
    no fue acreditada (ej: fallo de servidor durante la acreditación).
    Retorna lista de referidos que necesitan revisión manual.
    """
    rows = c.execute(
        """SELECT r.id, r.referrer_id, r.referred_id, r.status, r.created_at, r.reward_payment_id,
                  u.premium_until as invitee_premium
           FROM referrals r
           JOIN users u ON u.user_id = r.referred_id
           WHERE r.rewarded = 0
             AND r.status = ?
             AND u.premium_until IS NOT NULL""",
        (STATUS_PREMIUM_ACTIVE,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Historial personal
# ---------------------------------------------------------------------------

def get_referral_history(c: sqlite3.Connection, uid: str) -> Dict[str, Any]:
    """
    Historial completo de referidos para el usuario (como invitador).
    Incluye datos del invitado (solo first_name o username, sin datos financieros).
    """
    ensure_refer_code(c, uid)

    ref_code = c.execute(
        "SELECT refer_code FROM users WHERE user_id=?", (uid,)
    ).fetchone()
    code = ref_code["refer_code"] if ref_code else None

    invitations = c.execute(
        """SELECT r.id, r.referred_id, r.status, r.rewarded,
                  r.created_at, r.confirmed_at, r.rewarded_at, r.anomaly_flag, r.source,
                  u.first_name, u.username
           FROM referrals r
           LEFT JOIN users u ON u.user_id = r.referred_id
           WHERE r.referrer_id=?
           ORDER BY r.created_at DESC""",
        (uid,),
    ).fetchall()

    # Estadísticas
    total = len(invitations)
    pending = sum(1 for r in invitations if r["status"] == STATUS_REGISTERED)
    premium_active = sum(1 for r in invitations if r["status"] in (STATUS_PREMIUM_ACTIVE, STATUS_REWARDED))
    rewarded = sum(1 for r in invitations if r["rewarded"] == 1)
    days_earned = rewarded * REWARD_DAYS

    # Próximas recompensas pendientes (premium_active pero no rewarded)
    next_rewards = [
        r for r in invitations
        if r["status"] == STATUS_PREMIUM_ACTIVE and r["rewarded"] == 0
    ]

    return {
        "refer_code": code,
        "stats": {
            "total_invited": total,
            "pending": pending,
            "converted": premium_active,
            "rewarded": rewarded,
            "days_earned": days_earned,
        },
        "invitations": [
            {
                "id": r["id"],
                "invitee_display": _display_name(r["first_name"], r["username"], r["referred_id"]),
                "status": r["status"],
                "source": r["source"] if "source" in r.keys() else "manual",
                "rewarded": bool(r["rewarded"]),
                "invited_at": r["created_at"],
                "premium_activated_at": r["confirmed_at"],
                "rewarded_at": r["rewarded_at"],
                "anomaly": bool(r["anomaly_flag"]),
            }
            for r in invitations
        ],
        "next_rewards_pending": len(next_rewards),
        "rewards_history": [
            {
                "invitee_display": _display_name(
                    r["first_name"], r["username"], r["referred_id"]
                ),
                "days_added": REWARD_DAYS,
                "rewarded_at": r["rewarded_at"],
            }
            for r in invitations if r["rewarded"] == 1
        ],
    }


# ---------------------------------------------------------------------------
# Estadísticas administrativas
# ---------------------------------------------------------------------------

def get_admin_stats(c: sqlite3.Connection) -> Dict[str, Any]:
    """Estadísticas globales del sistema de referidos para el panel admin."""

    total_referrals = c.execute("SELECT COUNT(*) n FROM referrals").fetchone()["n"]
    pending = c.execute(
        "SELECT COUNT(*) n FROM referrals WHERE status=?", (STATUS_REGISTERED,)
    ).fetchone()["n"]
    premium_active = c.execute(
        "SELECT COUNT(*) n FROM referrals WHERE status=?", (STATUS_PREMIUM_ACTIVE,)
    ).fetchone()["n"]
    rewarded = c.execute(
        "SELECT COUNT(*) n FROM referrals WHERE rewarded=1"
    ).fetchone()["n"]
    anomalies = c.execute(
        "SELECT COUNT(*) n FROM referrals WHERE anomaly_flag=1"
    ).fetchone()["n"]

    conversion_rate = round(rewarded / total_referrals * 100, 1) if total_referrals > 0 else 0.0

    # Top invitadores
    top_referrers_rows = c.execute(
        """SELECT r.referrer_id,
                  u.username, u.first_name,
                  COUNT(*) total,
                  SUM(r.rewarded) rewarded
           FROM referrals r
           LEFT JOIN users u ON u.user_id = r.referrer_id
           GROUP BY r.referrer_id
           ORDER BY total DESC
           LIMIT 10"""
    ).fetchall()

    top_referrers = [
        {
            "user_id": r["referrer_id"],
            "display": _display_name(r["first_name"], r["username"], r["referrer_id"]),
            "total_invited": r["total"],
            "rewarded": int(r["rewarded"] or 0),
            "days_given": int((r["rewarded"] or 0)) * REWARD_DAYS,
        }
        for r in top_referrers_rows
    ]

    return {
        "total_referrals": total_referrals,
        "pending": pending,
        "premium_active": premium_active,
        "rewarded": rewarded,
        "anomalies": anomalies,
        "conversion_rate": conversion_rate,
        "days_premium_given": rewarded * REWARD_DAYS,
        "top_referrers": top_referrers,
    }


def get_admin_referral_list(
    c: sqlite3.Connection,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Lista paginada de referidos con filtros para el panel admin."""

    conditions = []
    params: list = []

    if status:
        conditions.append("r.status=?")
        params.append(status)

    if search:
        conditions.append(
            "(u_ref.username LIKE ? OR u_ref.first_name LIKE ? OR "
            "u_inv.username LIKE ? OR u_inv.first_name LIKE ? OR "
            "ref_u.refer_code LIKE ?)"
        )
        q = f"%{search}%"
        params.extend([q, q, q, q, q])

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT r.id, r.referrer_id, r.referred_id, r.status,
               r.rewarded, r.created_at, r.confirmed_at, r.rewarded_at,
               r.reward_payment_id, r.source, r.anomaly_flag, r.anomaly_reason,
               u_ref.first_name as referrer_name, u_ref.username as referrer_username,
               u_inv.first_name as invitee_name, u_inv.username as invitee_username,
               ref_u.refer_code
        FROM referrals r
        LEFT JOIN users u_ref ON u_ref.user_id = r.referrer_id
        LEFT JOIN users u_inv ON u_inv.user_id = r.referred_id
        LEFT JOIN users ref_u ON ref_u.user_id = r.referrer_id
        {where_clause}
        ORDER BY r.created_at DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    rows = c.execute(query, params).fetchall()

    count_query = f"""
        SELECT COUNT(*) n FROM referrals r
        LEFT JOIN users u_ref ON u_ref.user_id = r.referrer_id
        LEFT JOIN users u_inv ON u_inv.user_id = r.referred_id
        LEFT JOIN users ref_u ON ref_u.user_id = r.referrer_id
        {where_clause}
    """
    total = c.execute(count_query, params[:-2]).fetchone()["n"]

    return {
        "total": total,
        "items": [
            {
                "id": r["id"],
                "referrer_id": r["referrer_id"],
                "referrer_display": _display_name(r["referrer_name"], r["referrer_username"], r["referrer_id"]),
                "refer_code": r["refer_code"],
                "invitee_id": r["referred_id"],
                "invitee_display": _display_name(r["invitee_name"], r["invitee_username"], r["referred_id"]),
                "status": r["status"],
                "source": r["source"] if "source" in r.keys() else "manual",
                "rewarded": bool(r["rewarded"]),
                "invited_at": r["created_at"],
                "premium_activated_at": r["confirmed_at"],
                "rewarded_at": r["rewarded_at"],
                "payment_id": r["reward_payment_id"],
                "source": r["source"] if "source" in r.keys() else "manual",
                "anomaly": bool(r["anomaly_flag"]),
                "anomaly_reason": r["anomaly_reason"],
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Anomalías
# ---------------------------------------------------------------------------

def flag_anomaly(c: sqlite3.Connection, referral_id: int, reason: str) -> None:
    """Marca un referido como anomalía para revisión admin."""
    c.execute(
        "UPDATE referrals SET anomaly_flag=1, anomaly_reason=?, status=?, updated_at=? WHERE id=?",
        (reason, STATUS_REVIEW, _now(), referral_id),
    )
    c.commit()


def resolve_anomaly(
    c: sqlite3.Connection,
    referral_id: int,
    admin_username: str,
    action: str,  # "approve" | "reject"
    notes: str = "",
) -> None:
    """Resuelve una anomalía administrativamente y deja registro de auditoría."""
    new_status = STATUS_REGISTERED if action == "approve" else STATUS_NOT_ELIGIBLE
    reward_payment_id = None
    confirmed_at = None
    if action == "approve":
        referral = c.execute(
            "SELECT referred_id, created_at FROM referrals WHERE id=?", (referral_id,)
        ).fetchone()
        if referral:
            payment = c.execute(
                """SELECT operation_id, verified_at FROM payment_operations
                   WHERE user_id=? AND status='verified'
                     AND COALESCE(verified_at, created_at) >= ?
                   ORDER BY COALESCE(verified_at, created_at), created_at
                   LIMIT 1""",
                (referral["referred_id"], referral["created_at"]),
            ).fetchone()
            if payment:
                new_status = STATUS_PREMIUM_ACTIVE
                reward_payment_id = payment["operation_id"]
                confirmed_at = payment["verified_at"]
    c.execute(
        """UPDATE referrals SET anomaly_flag=0, anomaly_reason=NULL, status=?,
           reward_payment_id=COALESCE(?, reward_payment_id),
           confirmed_at=COALESCE(?, confirmed_at), updated_at=? WHERE id=?""",
        (new_status, reward_payment_id, confirmed_at, _now(), referral_id),
    )
    _write_audit(c, admin_username, f"anomaly_{action}", referral_id, notes)
    c.commit()


def admin_adjust_reward(
    c: sqlite3.Connection,
    referral_id: int,
    admin_username: str,
    grant: bool,
    notes: str = "",
) -> Dict[str, Any]:
    """
    Ajuste manual de recompensa por un administrador.
    Deja registro de auditoría. No permite modificaciones silenciosas.
    """
    ref = c.execute(
        "SELECT id, referrer_id, rewarded FROM referrals WHERE id=?", (referral_id,)
    ).fetchone()
    if not ref:
        return {"success": False, "error": "not_found"}

    t = _now()
    if grant and not ref["rewarded"]:
        # Otorgar recompensa manual
        row = c.execute(
            "SELECT premium_until FROM users WHERE user_id=?", (ref["referrer_id"],)
        ).fetchone()
        current = row["premium_until"] if row else None
        if current:
            try:
                base = _parse_dt(current)
                if base < datetime.utcnow():
                    base = datetime.now(timezone.utc)
            except Exception:
                base = datetime.now(timezone.utc)
        else:
            base = datetime.now(timezone.utc)
        until = (base + timedelta(days=REWARD_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")

        c.execute(
            "UPDATE users SET premium_until=?, updated_at=? WHERE user_id=?",
            (until, t, ref["referrer_id"]),
        )
        c.execute(
            """UPDATE referrals SET rewarded=1, status=?, rewarded_at=?,
               reward_idempotency_key=?, updated_at=? WHERE id=?""",
            (STATUS_REWARDED, t, f"admin_{admin_username}_{t}", t, referral_id),
        )
        action_label = "admin_grant_reward"
    elif not grant and ref["rewarded"]:
        # Revocar recompensa manual
        c.execute(
            "UPDATE referrals SET rewarded=0, status=?, rewarded_at=NULL, updated_at=? WHERE id=?",
            (STATUS_REGISTERED, t, referral_id),
        )
        action_label = "admin_revoke_reward"
    else:
        return {"success": False, "error": "no_change_needed"}

    _write_audit(c, admin_username, action_label, referral_id, notes)
    c.commit()
    return {"success": True, "action": action_label}


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _parse_dt(s: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {s!r}")


def _display_name(first_name: Optional[str], username: Optional[str], uid: str) -> str:
    """Nombre de display público y seguro (sin datos financieros)."""
    if first_name:
        return first_name
    if username:
        return f"@{username}"
    # Solo los últimos 4 caracteres del uid para anonimidad mínima
    return f"Usuario ···{uid[-4:]}"


def _write_audit(
    c: sqlite3.Connection,
    admin_username: str,
    action: str,
    referral_id: Optional[int],
    details: str,
) -> None:
    c.execute(
        """INSERT INTO referral_audit_log(admin_username, action, referral_id, details, created_at)
           VALUES(?, ?, ?, ?, ?)""",
        (admin_username, action, referral_id, details, _now()),
    )
