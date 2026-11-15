"""Grupo único de revisión en Telegram (comprobantes, fotos, reportes, anuncios, referidos).

Este módulo **no** decide nada por su cuenta: sólo envía los mensajes al chat ya
configurado en ``PAYMENT_ARCHIVE_CHAT_ID`` y traduce los botones pulsados en
llamadas a las mismas funciones de negocio que usa el panel administrativo.

Reglas de seguridad que se respetan aquí:
- Sólo los IDs de ``ADMIN_TELEGRAM_IDS`` pueden ejecutar una acción.
- Cada pulsación se registra; las funciones de negocio vuelven a validar el
  estado (una operación ya verificada no se puede volver a otorgar).
- Telegram no acepta teclados en un mensaje con foto: primero va la foto y
  después un mensaje corto con los botones.
"""
from __future__ import annotations

import html as _html
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

CALLBACK_PREFIX = "rv1"
PLAN_LABELS = {"weekly": "Semanal (7 días)", "monthly": "Mensual (30 días)", "annual": "Anual (365 días)"}
AD_PLAN_LABELS = {
    "ad_daily": "Anuncio diario",
    "ad_weekly": "Anuncio semanal",
    "ad_monthly": "Anuncio mensual",
    "ad_annual": "Anuncio anual",
}
STATUS_LABELS = {
    "pending": "pendiente",
    "proof_submitted": "comprobante recibido",
    "processing": "en proceso",
    "verified": "verificado",
    "rejected": "rechazado",
    "cancelled": "cancelado",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _esc(value: Any) -> str:
    return _html.escape(str(value if value is not None else ""), quote=False)


def _bot():
    try:
        from . import telegram_bot as tb
    except ImportError:  # pragma: no cover - ejecución como script suelto
        import telegram_bot as tb
    return tb


def review_chat_id() -> str:
    return (os.getenv("PAYMENT_ARCHIVE_CHAT_ID") or "").strip()


def admin_ids() -> set:
    return {x.strip() for x in (os.getenv("ADMIN_TELEGRAM_IDS") or "").split(",") if x.strip()}


def mini_app_url() -> str:
    url = (os.getenv("TELEGRAM_MINI_APP_URL") or "").strip().rstrip("/")
    return url if url.startswith("https://") else ""


def app_keyboard(label: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Botón que abre la Mini App (sólo si hay una URL HTTPS configurada)."""
    url = mini_app_url()
    if not url:
        return None
    return {"inline_keyboard": [[{"text": label or "🚀 Abrir Mini App", "web_app": {"url": url + "/"}}]]}


def plan_label(plan: str) -> str:
    plan = str(plan or "")
    return PLAN_LABELS.get(plan) or AD_PLAN_LABELS.get(plan) or plan or "—"


def ensure_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS telegram_review_notices(
          dedupe_key TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          chat_id TEXT,
          message_id TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telegram_review_log(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          admin_id TEXT NOT NULL,
          chat_id TEXT,
          message_id TEXT,
          action TEXT NOT NULL,
          target TEXT NOT NULL,
          result TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telegram_review_pending_reason(
          admin_id TEXT NOT NULL,
          chat_id TEXT NOT NULL,
          action TEXT NOT NULL,
          target TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (admin_id, chat_id)
        );
        CREATE INDEX IF NOT EXISTS idx_review_log_target ON telegram_review_log(target, created_at);
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Envío
# ---------------------------------------------------------------------------

def _kb(rows: Optional[Iterable[Iterable[Dict[str, Any]]]]) -> Optional[Dict[str, Any]]:
    if not rows:
        return None
    prepared = [list(r) for r in rows if r]
    return {"inline_keyboard": prepared} if prepared else None


def _send(text: str, rows=None, chat_id: Optional[str] = None) -> Dict[str, Any]:
    chat = chat_id or review_chat_id()
    if not chat:
        return {}
    return _bot().send_message(chat, text, _kb(rows))


def _send_photo(raw: bytes, caption: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
    chat = chat_id or review_chat_id()
    if not chat:
        return {}
    return _bot().send_photo(chat, raw, "comprobante.jpg", caption)


def _answer_callback(callback_id: str, text: str = "", alert: bool = False) -> None:
    if not callback_id:
        return
    try:
        _bot().bot_api_call(
            "answerCallbackQuery",
            {"callback_query_id": callback_id, "text": (text or "")[:190], "show_alert": bool(alert)},
        )
    except Exception:  # el aviso es cosmético: nunca debe romper la acción
        logger.debug("answerCallbackQuery failed", exc_info=True)


def _clear_buttons(chat_id, message_id) -> None:
    """Quita los botones del mensaje ya resuelto (idempotencia visual)."""
    if not chat_id or not message_id:
        return
    try:
        _bot().bot_api_call(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": int(message_id), "reply_markup": {"inline_keyboard": []}},
        )
    except Exception:
        logger.debug("editMessageReplyMarkup failed", exc_info=True)


def _remember(conn, dedupe_key: str, kind: str, message: Optional[Dict[str, Any]] = None) -> bool:
    """Registra un aviso enviado. Devuelve False si ya se había enviado."""
    if conn is None:
        return True
    ensure_schema(conn)
    exists = conn.execute("SELECT 1 FROM telegram_review_notices WHERE dedupe_key=?", (dedupe_key,)).fetchone()
    if exists:
        return False
    message = message or {}
    conn.execute(
        "INSERT OR REPLACE INTO telegram_review_notices(dedupe_key,kind,chat_id,message_id,created_at) VALUES(?,?,?,?,?)",
        (dedupe_key, kind, str(message.get("chat", {}).get("id") or ""), str(message.get("message_id") or ""), _now()),
    )
    conn.commit()
    return True


# ---------------------------------------------------------------------------
# Teclados
# ---------------------------------------------------------------------------

def _pay_rows(operation_id: str) -> List[List[Dict[str, str]]]:
    return [[
        {"text": "✅ Aprobar", "callback_data": f"{CALLBACK_PREFIX}:pay:ok:{operation_id}"},
        {"text": "❌ Rechazar", "callback_data": f"{CALLBACK_PREFIX}:pay:no:{operation_id}"},
    ]]


def _photo_rows(photo_id: Any) -> List[List[Dict[str, str]]]:
    return [[
        {"text": "✅ Aprobar foto", "callback_data": f"{CALLBACK_PREFIX}:photo:ok:{photo_id}"},
        {"text": "❌ Rechazar foto", "callback_data": f"{CALLBACK_PREFIX}:photo:no:{photo_id}"},
    ]]


def _report_rows(report_id: Any) -> List[List[Dict[str, str]]]:
    return [[
        {"text": "🚫 Suspender", "callback_data": f"{CALLBACK_PREFIX}:report:suspend:{report_id}"},
        {"text": "🗑 Descartar", "callback_data": f"{CALLBACK_PREFIX}:report:dismiss:{report_id}"},
    ]]


def _ad_rows(ad_id: Any) -> List[List[Dict[str, str]]]:
    return [[
        {"text": "✅ Aprobar", "callback_data": f"{CALLBACK_PREFIX}:ad:ok:{ad_id}"},
        {"text": "❌ Rechazar", "callback_data": f"{CALLBACK_PREFIX}:ad:no:{ad_id}"},
    ]]


def _ref_rows(referral_id: Any) -> List[List[Dict[str, str]]]:
    return [[
        {"text": "✅ Aprobar", "callback_data": f"{CALLBACK_PREFIX}:ref:ok:{referral_id}"},
        {"text": "❌ Rechazar", "callback_data": f"{CALLBACK_PREFIX}:ref:no:{referral_id}"},
    ]]


# ---------------------------------------------------------------------------
# Textos
# ---------------------------------------------------------------------------

def payment_details(operation_id: str, connect: Callable) -> str:
    """Mensaje con todos los datos de la transferencia que pide el grupo."""
    row = None
    try:
        c = connect()
        try:
            row = c.execute(
                """SELECT po.operation_id,po.user_id,po.plan,po.status,po.amount,po.payment_method,
                          po.payer_phone,po.destination_account,po.transaction_id,po.transfer_date,
                          po.proof_text,po.created_at,u.first_name,u.username,u.payment_phone
                     FROM payment_operations po LEFT JOIN users u ON u.user_id=po.user_id
                    WHERE po.operation_id=?""",
                (operation_id,),
            ).fetchone()
        finally:
            c.close()
    except Exception:
        logger.warning("Could not read payment details operation_id=%s", operation_id, exc_info=True)
    if not row:
        return f"💳 <b>Comprobante de pago</b>\nOperación: <code>{_esc(operation_id)}</code>"
    name = row["first_name"] or (f"@{row['username']}" if row["username"] else "") or "Sin nombre"
    lines = [
        "💳 <b>Comprobante de pago</b>",
        f"Operación: <code>{_esc(row['operation_id'])}</code>",
        f"Usuario: {_esc(name)} · <code>{_esc(row['user_id'])}</code>",
        f"Plan: <b>{_esc(plan_label(row['plan']))}</b>",
        f"Importe: <b>{_esc(row['amount'])}</b>",
        f"Método: {_esc(row['payment_method'] or '—')}",
        f"Teléfono: {_esc(row['payer_phone'] or row['payment_phone'] or '—')}",
        f"Cuenta destino: {_esc(row['destination_account'] or '—')}",
        f"Nº transacción: {_esc(row['transaction_id'] or '—')}",
        f"Fecha: {_esc(row['transfer_date'] or row['created_at'] or '—')}",
        f"Estado: {_esc(STATUS_LABELS.get(row['status'], row['status']))}",
    ]
    proof_text = (row["proof_text"] or "").strip()
    if proof_text:
        lines.append(f"Texto del usuario: {_esc(proof_text[:600])}")
    return "\n".join(lines)


def send_payment_review(operation_id: str, connect: Callable, chat_id: Optional[str] = None) -> Dict[str, Any]:
    """Comprobante sin foto: un solo mensaje con datos y botones."""
    message = _send(payment_details(operation_id, connect), _pay_rows(operation_id), chat_id)
    return message


def send_payment_buttons(operation_id: str, connect: Callable, chat_id: Optional[str] = None) -> Dict[str, Any]:
    """Botones aparte, para cuando el comprobante ya viajó como foto."""
    return _send(
        f"Revisión de la operación <code>{_esc(operation_id)}</code>",
        _pay_rows(operation_id),
        chat_id,
    )


def notify(kind: str, payload: Dict[str, Any], connect: Optional[Callable] = None) -> bool:
    """Envía al grupo un elemento pendiente de revisión. Best-effort."""
    if not review_chat_id():
        return False
    payload = payload or {}
    try:
        if kind == "photo":
            return _photo_item(payload, connect)
        if kind == "report":
            return _report_item(payload, connect)
        if kind == "ad":
            return _ad_item(payload, connect)
        if kind == "referral":
            return _referral_item(payload, connect)
        if kind == "atajo_granted":
            return _atajo_item(payload, granted=True, connect=connect)
        if kind == "atajo_unmatched":
            return _atajo_item(payload, granted=False, connect=connect)
        logger.debug("Unknown review notice kind=%s", kind)
    except Exception:
        logger.warning("Review group notice failed kind=%s", kind, exc_info=True)
    return False


def _photo_item(payload: Dict[str, Any], connect: Optional[Callable]) -> bool:
    photo_id = payload.get("photo_id")
    if not photo_id:
        return False
    conn = None
    try:
        if connect is not None:
            conn = connect()
            ensure_schema(conn)
        key = f"photo:{photo_id}"
        if conn is not None and conn.execute(
            "SELECT 1 FROM telegram_review_notices WHERE dedupe_key=?", (key,)
        ).fetchone():
            return False
        caption = (
            "🖼 <b>Foto de Citas en revisión</b>\n"
            f"Usuario: {_esc(payload.get('display_name') or 'Sin nombre')} · "
            f"<code>{_esc(payload.get('user_id') or '—')}</code>"
        )
        raw = payload.get("image")
        if raw:
            _send_photo(raw, caption)
        else:
            _send(caption)
        # Telegram no admite teclado en un mensaje con foto: los botones van aparte.
        _send(f"Revisión de la foto <b>#{_esc(photo_id)}</b>", _photo_rows(photo_id))
        if conn is not None:
            conn.execute(
                "INSERT OR REPLACE INTO telegram_review_notices(dedupe_key,kind,created_at) VALUES(?,?,?)",
                (key, "photo", _now()),
            )
            conn.commit()
        return True
    finally:
        if conn is not None:
            conn.close()


def _report_item(payload: Dict[str, Any], connect: Optional[Callable]) -> bool:
    report_id = payload.get("report_id")
    if not report_id:
        return False
    conn = None
    try:
        if connect is not None:
            conn = connect()
            ensure_schema(conn)
        if conn is not None and conn.execute(
            "SELECT 1 FROM telegram_review_notices WHERE dedupe_key=?", (f"report:{report_id}",)
        ).fetchone():
            return False
        text = (
            "🚩 <b>Reporte de Citas</b>\n"
            f"Reporte: <code>#{_esc(report_id)}</code>\n"
            f"Motivo: {_esc(payload.get('reason') or '—')}\n"
            f"Reporta: <code>{_esc(payload.get('reporter_id') or '—')}</code>\n"
            f"Reportado: {_esc(payload.get('reported_name') or 'Sin nombre')} · "
            f"<code>{_esc(payload.get('reported_id') or '—')}</code>"
        )
        if payload.get("details"):
            text += f"\nDetalles: {_esc(str(payload['details'])[:500])}"
        _send(text, _report_rows(report_id))
        if conn is not None:
            conn.execute(
                "INSERT OR REPLACE INTO telegram_review_notices(dedupe_key,kind,created_at) VALUES(?,?,?)",
                (f"report:{report_id}", "report", _now()),
            )
            conn.commit()
        return True
    finally:
        if conn is not None:
            conn.close()


def _ad_item(payload: Dict[str, Any], connect: Optional[Callable]) -> bool:
    ad_id = payload.get("id")
    if not ad_id:
        return False
    conn = None
    try:
        if connect is not None:
            conn = connect()
            ensure_schema(conn)
        row = None
        if conn is not None:
            row = conn.execute("SELECT * FROM ads WHERE id=?", (int(ad_id),)).fetchone()
        decision = str(payload.get("decision") or "").strip()
        if decision:
            # Resultado de una revisión hecha en el panel: informativo, sin botones.
            if conn is not None and conn.execute(
                "SELECT 1 FROM telegram_review_notices WHERE dedupe_key=?",
                (f"ad-decision:{ad_id}:{decision}",),
            ).fetchone():
                return False
            text = (
                "📣 <b>Anuncio revisado</b>\n"
                f"Anuncio: <code>#{_esc(ad_id)}</code>\n"
                f"Resultado: <b>{_esc(decision)}</b>"
            )
            if payload.get("reason"):
                text += f"\nMotivo: {_esc(str(payload['reason'])[:300])}"
            _send(text)
            if conn is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO telegram_review_notices(dedupe_key,kind,created_at) VALUES(?,?,?)",
                    (f"ad-decision:{ad_id}:{decision}", "ad", _now()),
                )
                conn.commit()
            return True
        if conn is not None and conn.execute(
            "SELECT 1 FROM telegram_review_notices WHERE dedupe_key=?", (f"ad:{ad_id}",)
        ).fetchone():
            return False
        name = (row["business_name"] if row is not None else payload.get("business_name")) or "—"
        title = (row["title"] if row is not None else payload.get("title")) or "—"
        body = (row["body"] if row is not None else payload.get("body")) or ""
        text = (
            "📣 <b>Anuncio de negocio en revisión</b>\n"
            f"Anuncio: <code>#{_esc(ad_id)}</code>\n"
            f"Negocio: {_esc(name)}\n"
            f"Título: {_esc(title)}"
        )
        if body:
            text += f"\nTexto: {_esc(str(body)[:500])}"
        _send(text, _ad_rows(ad_id))
        if conn is not None:
            conn.execute(
                "INSERT OR REPLACE INTO telegram_review_notices(dedupe_key,kind,created_at) VALUES(?,?,?)",
                (f"ad:{ad_id}", "ad", _now()),
            )
            conn.commit()
        return True
    finally:
        if conn is not None:
            conn.close()


def _referral_item(payload: Dict[str, Any], connect: Optional[Callable]) -> bool:
    referral_id = payload.get("referral_id")
    if not referral_id:
        return False
    conn = None
    try:
        if connect is not None:
            conn = connect()
            ensure_schema(conn)
        if conn is not None and conn.execute(
            "SELECT 1 FROM telegram_review_notices WHERE dedupe_key=?", (f"ref:{referral_id}",)
        ).fetchone():
            return False
        text = (
            "👥 <b>Referido en anomalía</b>\n"
            f"Referido: <code>#{_esc(referral_id)}</code>\n"
            f"Invitador: <code>{_esc(payload.get('referrer_id') or '—')}</code>\n"
            f"Invitado: <code>{_esc(payload.get('referred_id') or '—')}</code>\n"
            f"Motivo: {_esc(payload.get('reason') or '—')}"
        )
        _send(text, _ref_rows(referral_id))
        if conn is not None:
            conn.execute(
                "INSERT OR REPLACE INTO telegram_review_notices(dedupe_key,kind,created_at) VALUES(?,?,?)",
                (f"ref:{referral_id}", "referral", _now()),
            )
            conn.commit()
        return True
    finally:
        if conn is not None:
            conn.close()


def _atajo_item(payload: Dict[str, Any], granted: bool, connect: Optional[Callable]) -> bool:
    key_target = str(payload.get("operation_id") or payload.get("fingerprint") or "")
    if not key_target:
        return False
    kind = "atajo-granted" if granted else "atajo-unmatched"
    conn = None
    try:
        if connect is not None:
            conn = connect()
            ensure_schema(conn)
        if conn is not None and conn.execute(
            "SELECT 1 FROM telegram_review_notices WHERE dedupe_key=?", (f"{kind}:{key_target}",)
        ).fetchone():
            return False

        # Usuario clicable (abre chat privado)
        user_id = str(payload.get("user_id") or "").strip()
        first_name = (payload.get("first_name") or "").strip()
        username = (payload.get("username") or "").strip()
        if first_name:
            display = first_name
        elif username:
            display = f"@{username}"
        else:
            display = "Sin nombre"
        if user_id and user_id.isdigit():
            user_line = f'👤 <b>Usuario:</b> <a href="tg://user?id={_esc(user_id)}">{_esc(display)}</a> · <code>{_esc(user_id)}</code>'
        else:
            user_line = f"👤 <b>Usuario:</b> {_esc(display)}"

        phone = _esc(payload.get("phone") or "—")
        amount = _esc(payload.get("amount") or "—")
        method = _esc(payload.get("method") or "—")
        destination = _esc(payload.get("destination") or "—")
        origin_account = _esc(payload.get("origin_account") or "—")
        transaction = _esc(payload.get("transaction") or "—")
        date = _esc(payload.get("date") or "—")
        operation_id = _esc(payload.get("operation_id") or "—")
        raw_sms = (payload.get("raw_sms") or "").strip()

        if granted:
            lines = [
                "✅ <b>Premium otorgado por atajo</b>",
                "",
                user_line,
                f"📱 <b>Teléfono:</b> {phone}",
                f"💰 <b>Monto:</b> <b>{amount} CUP</b>",
                f"🏦 <b>Método:</b> {method}",
                f"💳 <b>Cuenta origen:</b> {origin_account}",
                f"🏛 <b>Cuenta destino:</b> {destination}",
                f"🔢 <b>Nº de Transacción:</b> {transaction}",
                f"📅 <b>Fecha:</b> {date}",
                f"🆔 <b>Operación:</b> <code>{operation_id}</code>",
            ]
            if raw_sms:
                lines.append("")
                lines.append("📋 <b>Datos del atajo:</b>")
                # Mostrar el SMS/raw en bloque de código para que se vea limpio
                lines.append(f"<pre>{_esc(raw_sms[:1200])}</pre>")
            lines.append("")
            lines.append("⚡ Premium otorgado automáticamente por atajo")
        else:
            status = (payload.get("status") or "unmatched").strip()
            head = "⚠️ <b>Atajo sin coincidencia</b>"
            if status == "ambiguous":
                head += f" · {_esc(payload.get('matches') or 0)} operaciones posibles"
            lines = [
                head,
                "<i>No se otorgó nada.</i>",
                "",
                f"📱 <b>Teléfono:</b> {phone}",
                f"💰 <b>Monto:</b> <b>{amount} CUP</b>",
                f"🏦 <b>Método:</b> {method}",
                f"💳 <b>Cuenta origen:</b> {origin_account}",
                f"🏛 <b>Cuenta destino:</b> {destination}",
                f"🔢 <b>Nº de Transacción:</b> {transaction}",
                f"📅 <b>Fecha:</b> {date}",
            ]
            if payload.get("operation_id"):
                lines.append(f"🆔 <b>Operación:</b> <code>{operation_id}</code>")
            if raw_sms:
                lines.append("")
                lines.append("📋 <b>Datos del atajo:</b>")
                lines.append(f"<pre>{_esc(raw_sms[:1200])}</pre>")

        _send("\n".join(lines))
        if conn is not None:
            conn.execute(
                "INSERT OR REPLACE INTO telegram_review_notices(dedupe_key,kind,created_at) VALUES(?,?,?)",
                (f"{kind}:{key_target}", kind, _now()),
            )
            conn.commit()
        return True
    finally:
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def _set_pending_reason(connect: Callable, admin_id: str, chat_id: Any, action: str, target: str) -> None:
    conn = connect()
    try:
        ensure_schema(conn)
        conn.execute(
            """INSERT OR REPLACE INTO telegram_review_pending_reason(admin_id,chat_id,action,target,created_at)
               VALUES(?,?,?,?,?)""",
            (str(admin_id), str(chat_id), action, str(target), _now()),
        )
        conn.commit()
    finally:
        conn.close()


def pending_reason(connect: Callable, admin_id: str, chat_id: Any) -> Optional[Dict[str, Any]]:
    conn = connect()
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM telegram_review_pending_reason WHERE admin_id=? AND chat_id=?",
            (str(admin_id), str(chat_id)),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def clear_pending_reason(connect: Callable, admin_id: str, chat_id: Any) -> None:
    conn = connect()
    try:
        ensure_schema(conn)
        conn.execute(
            "DELETE FROM telegram_review_pending_reason WHERE admin_id=? AND chat_id=?",
            (str(admin_id), str(chat_id)),
        )
        conn.commit()
    finally:
        conn.close()


def _log(connect: Callable, admin_id: str, chat_id: Any, message_id: Any, action: str, target: str, result: str) -> None:
    conn = connect()
    try:
        ensure_schema(conn)
        conn.execute(
            """INSERT INTO telegram_review_log(admin_id,chat_id,message_id,action,target,result,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (str(admin_id), str(chat_id or ""), str(message_id or ""), action, str(target), result, _now()),
        )
        conn.commit()
    finally:
        conn.close()
