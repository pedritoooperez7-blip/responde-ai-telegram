"""LiggaCuba Anuncios.

Dos orígenes de anuncio:

* ``admin``: los crea el equipo desde el panel de administración. Se publican
  aprobados y se muestran hasta ``ends_at`` (o sin fecha de fin).
* ``business``: los edita el propio negocio tras pagar un plan de anuncio
  (diario, semanal, mensual o anual). Cada cambio vuelve a ``pending`` y no se
  muestra hasta que administración lo aprueba, para evitar contenido que
  incumpla las reglas. Se muestra solo mientras ``paid_until`` no haya vencido.

Solo se muestran a usuarios que no son Premium. El texto de un anuncio se pinta
en la app con ``textContent`` (nunca como HTML) y los enlaces se limitan a
http(s) y t.me, que son los únicos que validan estas funciones.

La lógica recibe una conexión sqlite3 y no depende de FastAPI; ``build_router``
crea las rutas y recibe sus dependencias desde ``main.py``.
"""
import logging
import random
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS ads(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL DEFAULT 'admin',
  owner_user_id TEXT,
  business_name TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL DEFAULT '',
  image_url TEXT NOT NULL DEFAULT '',
  image_filename TEXT NOT NULL DEFAULT '',
  link_url TEXT NOT NULL DEFAULT '',
  cta TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft',
  active INTEGER NOT NULL DEFAULT 1,
  weight INTEGER NOT NULL DEFAULT 1,
  paid_until TEXT,
  ends_at TEXT,
  reject_reason TEXT,
  impressions INTEGER NOT NULL DEFAULT 0,
  clicks INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ads_business_owner ON ads(owner_user_id) WHERE source='business';
CREATE INDEX IF NOT EXISTS idx_ads_status ON ads(status,active);
"""

STATUSES = {"draft", "pending", "approved", "rejected", "paused"}
LIMITS = {"business_name": 60, "title": 60, "body": 220, "cta": 24, "link_url": 300, "image_url": 400}
DEFAULT_CTA = "Ver más"


class AdError(ValueError):
    """Error de validación con mensaje apto para mostrar al usuario."""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _clean(value: Any, field: str, required: bool = False) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    if required and not text:
        raise AdError(f"El campo «{field}» es obligatorio")
    if len(text) > LIMITS.get(field, 300):
        raise AdError(f"El campo «{field}» admite como máximo {LIMITS.get(field, 300)} caracteres")
    return text


def validate_url(value: Any, field: str, *, required: bool) -> str:
    """Solo http(s) con dominio; ``javascript:``, ``data:`` y similares se rechazan."""
    text = _clean(value, field, required=required)
    if not text:
        return ""
    if re.match(r"^(t\.me|wa\.me)/", text, re.I):
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or " " in text:
        raise AdError(f"El enlace de «{field}» debe empezar por https://")
    if field == "image_url" and parsed.scheme != "https":
        raise AdError("La imagen debe usar https://")
    return text


def validate_fields(data: Dict[str, Any]) -> Dict[str, str]:
    return {
        "business_name": _clean(data.get("business_name"), "business_name", required=True),
        "title": _clean(data.get("title"), "title", required=True),
        "body": _clean(data.get("body"), "body", required=True),
        "cta": _clean(data.get("cta"), "cta") or DEFAULT_CTA,
        "link_url": validate_url(data.get("link_url"), "link_url", required=True),
        "image_url": validate_url(data.get("image_url"), "image_url", required=False),
    }


def is_live(row: sqlite3.Row, at: Optional[datetime] = None) -> bool:
    """¿Se puede mostrar ahora? Aprobado, activo y dentro de su vigencia."""
    at = at or datetime.now(timezone.utc)
    if row["status"] != "approved" or not int(row["active"] or 0):
        return False
    if row["source"] == "business":
        paid = _parse(row["paid_until"])
        return bool(paid and paid > at)
    ends = _parse(row["ends_at"])
    return ends is None or ends > at


def public_view(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"], "business_name": row["business_name"], "title": row["title"],
        "body": row["body"], "image_url": row["image_url"], "cta": row["cta"] or DEFAULT_CTA,
    }


def pick_ad(conn: sqlite3.Connection, rng: Optional[random.Random] = None) -> Optional[sqlite3.Row]:
    """Elige un anuncio vigente al azar, ponderado por ``weight``."""
    rows = [r for r in conn.execute("SELECT * FROM ads WHERE status='approved' AND active=1").fetchall() if is_live(r)]
    if not rows:
        return None
    weights = [max(1, int(r["weight"] or 1)) for r in rows]
    return (rng or random).choices(rows, weights=weights, k=1)[0]


def extend_business_subscription(conn: sqlite3.Connection, user_id: str, days: int,
                                 business_name: str = "") -> str:
    """Suma ``days`` al plan de anuncio del usuario (sin perder días ya pagados).

    Crea el anuncio vacío si es la primera compra. Se llama dentro de la misma
    transacción que marca el pago como verificado.
    """
    now = datetime.now(timezone.utc)
    row = conn.execute("SELECT id,paid_until FROM ads WHERE source='business' AND owner_user_id=?", (str(user_id),)).fetchone()
    base = now
    if row and row["paid_until"]:
        current = _parse(row["paid_until"])
        if current and current > now:
            base = current
    until = (base + timedelta(days=int(days))).isoformat()
    if row:
        conn.execute("UPDATE ads SET paid_until=?,updated_at=? WHERE id=?", (until, now.isoformat(), row["id"]))
    else:
        conn.execute(
            "INSERT INTO ads(source,owner_user_id,business_name,status,paid_until,created_at,updated_at) "
            "VALUES('business',?,?,'draft',?,?,?)",
            (str(user_id), business_name or "", until, now.isoformat(), now.isoformat()),
        )
    return until


def business_view(row: Optional[sqlite3.Row]) -> Dict[str, Any]:
    if not row:
        return {"has_plan": False}
    paid = _parse(row["paid_until"])
    active_plan = bool(paid and paid > datetime.now(timezone.utc))
    return {
        "has_plan": True, "plan_active": active_plan, "paid_until": row["paid_until"],
        "status": row["status"], "reject_reason": row["reject_reason"] or "",
        "business_name": row["business_name"], "title": row["title"], "body": row["body"],
        "image_url": row["image_url"], "link_url": row["link_url"], "cta": row["cta"] or DEFAULT_CTA,
        "impressions": int(row["impressions"] or 0), "clicks": int(row["clicks"] or 0),
        "live": is_live(row),
    }


def save_business_ad(conn: sqlite3.Connection, user_id: str, data: Dict[str, Any]) -> sqlite3.Row:
    """Guarda lo que edita el negocio y lo manda a revisión."""
    row = conn.execute("SELECT * FROM ads WHERE source='business' AND owner_user_id=?", (str(user_id),)).fetchone()
    if not row:
        raise AdError("Primero contrata un plan de anuncio")
    fields = validate_fields(data)
    conn.execute(
        "UPDATE ads SET business_name=?,title=?,body=?,cta=?,link_url=?,image_url=?,"
        "status='pending',reject_reason=NULL,updated_at=? WHERE id=?",
        (fields["business_name"], fields["title"], fields["body"], fields["cta"],
         fields["link_url"], fields["image_url"], _now(), row["id"]),
    )
    return conn.execute("SELECT * FROM ads WHERE id=?", (row["id"],)).fetchone()


def apply_admin_action(conn: sqlite3.Connection, ad_id: int, action: str, reason: str = "",
                       actor: str = "") -> Dict[str, Any]:
    """Aplica una decisión de moderación. Única implementación (panel y Telegram)."""
    action = (action or "").strip().lower()
    mapping = {"approve": "approved", "reject": "rejected", "pause": "paused", "resume": "approved"}
    if action not in mapping:
        raise AdError("Acción no válida")
    reason = re.sub(r"\s+", " ", reason or "").strip()[:300]
    if action == "reject" and not reason:
        raise AdError("Indica el motivo del rechazo para que el negocio pueda corregirlo")
    row = conn.execute("SELECT * FROM ads WHERE id=?", (int(ad_id),)).fetchone()
    if not row:
        raise AdError("Anuncio no encontrado")
    if action in {"approve", "resume"} and not (row["title"] and row["link_url"]):
        raise AdError("El anuncio aún no tiene contenido")
    conn.execute("UPDATE ads SET status=?,reject_reason=?,updated_at=? WHERE id=?",
                 (mapping[action], reason if action == "reject" else None, _now(), row["id"]))
    conn.commit()
    return {"id": row["id"], "status": mapping[action], "reason": reason,
            "owner_user_id": row["owner_user_id"], "business_name": row["business_name"],
            "title": row["title"], "body": row["body"]}


def build_router(*, current_user: Callable, connect: Callable, is_premium: Callable,
                 admin: Callable, audit: Callable, payments: Any, request_limiter: Any = None,
                 notify: Optional[Callable] = None, review: Optional[Callable] = None):
    """Crea el APIRouter. ``main.py`` inyecta autenticación, base de datos y pagos."""
    from fastapi import APIRouter, HTTPException, Request
    from pydantic import BaseModel

    router = APIRouter()

    class AdFields(BaseModel):
        business_name: str = ""
        title: str = ""
        body: str = ""
        cta: str = ""
        link_url: str = ""
        image_url: str = ""

    class AdminAd(AdFields):
        id: Optional[int] = None
        weight: int = 1
        ends_at: Optional[str] = None
        active: bool = True

    class AdAction(BaseModel):
        id: int
        action: str
        reason: str = ""

    class AdId(BaseModel):
        id: int

    def _notify_user(fn, user_id: str, text: str):
        if not fn or not user_id:
            return
        try:
            fn(str(user_id), text)
        except Exception:
            pass

    def _notify_review(fn, payload: Dict[str, Any]):
        """Avisa al grupo de revisión sin bloquear la respuesta."""
        if not fn:
            return
        import threading as _threading
        def _run():
            try:
                fn("ad", payload)
            except Exception:
                pass
        _threading.Thread(target=_run, daemon=True).start()

    def _notify_ad_result(fn, result: Dict[str, Any]):
        status = result.get("status")
        uid = result.get("owner_user_id")
        if not fn or not uid:
            return
        reason = result.get("reason") or ""
        if status == "approved":
            _notify_user(fn, uid, "✅ <b>Tu anuncio fue aprobado.</b>\nYa se está mostrando a quienes usan LiggaCuba sin Premium.")
        elif status == "rejected":
            motivo = f"\n\nMotivo: {reason}" if reason else ""
            _notify_user(fn, uid, f"❌ <b>Tu anuncio fue rechazado.</b>{motivo}\n\nCorrígelo y vuelve a enviarlo a revisión.")
        elif status == "paused":
            _notify_user(fn, uid, "⏸ <b>Tu anuncio fue pausado.</b>\nPuedes corregirlo y volver a enviarlo a revisión.")

    def _conn():
        conn = connect()
        ensure_schema(conn)
        return conn

    def _admin_row(r: sqlite3.Row) -> Dict[str, Any]:
        d = {k: r[k] for k in r.keys()}
        d["live"] = is_live(r)
        return d

    # ---- público (usuarios no Premium) ----
    @router.get("/api/ads/next")
    def ads_next(request: Request):
        uid = current_user(request)
        if is_premium(uid):
            return {"ad": None}
        conn = _conn()
        try:
            row = pick_ad(conn)
            if not row:
                return {"ad": None}
            conn.execute("UPDATE ads SET impressions=impressions+1 WHERE id=?", (row["id"],))
            conn.commit()
            return {"ad": public_view(row), "min_seconds": 2}
        finally:
            conn.close()

    @router.post("/api/ads/click")
    def ads_click(p: AdId, request: Request):
        current_user(request)
        conn = _conn()
        try:
            row = conn.execute("SELECT * FROM ads WHERE id=?", (int(p.id),)).fetchone()
            if not row or not is_live(row):
                raise HTTPException(404, "Anuncio no disponible")
            conn.execute("UPDATE ads SET clicks=clicks+1 WHERE id=?", (row["id"],))
            conn.commit()
            return {"url": row["link_url"]}
        finally:
            conn.close()

    @router.get("/api/ads/pricing")
    def ads_pricing():
        return {"currency": payments.payment_currency(), "plans": payments.ad_pricing()}

    # ---- negocio ----
    @router.get("/api/business-ad")
    def business_get(request: Request):
        uid = current_user(request)
        conn = _conn()
        try:
            row = conn.execute("SELECT * FROM ads WHERE source='business' AND owner_user_id=?", (uid,)).fetchone()
            return business_view(row)
        finally:
            conn.close()

    @router.post("/api/business-ad")
    def business_save(p: AdFields, request: Request):
        uid = current_user(request)
        conn = _conn()
        try:
            row = save_business_ad(conn, uid, p.model_dump() if hasattr(p, "model_dump") else p.dict())
            conn.commit()
            _notify_user(notify, uid, "📣 <b>Tu anuncio está en revisión.</b>\nTe avisaremos cuando administración lo apruebe.")
            _notify_review(review, {"id": row["id"], "owner_user_id": uid,
                                    "business_name": row["business_name"], "title": row["title"], "body": row["body"]})
            return business_view(row)
        except AdError as exc:
            conn.rollback()
            raise HTTPException(400, str(exc))
        finally:
            conn.close()

    # ---- administración ----
    @router.get("/api/admin/ads")
    def admin_list(request: Request):
        admin(request, "ads")
        conn = _conn()
        try:
            rows = conn.execute("SELECT * FROM ads ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, updated_at DESC LIMIT 300").fetchall()
            return {"items": [_admin_row(r) for r in rows]}
        finally:
            conn.close()

    @router.post("/api/admin/ads")
    def admin_save(p: AdminAd, request: Request):
        ident = admin(request, "ads")
        raw = p.model_dump() if hasattr(p, "model_dump") else p.dict()
        conn = _conn()
        try:
            fields = validate_fields(raw)
            ends = None
            if raw.get("ends_at"):
                parsed = _parse(raw["ends_at"]) or _parse(str(raw["ends_at"]) + "T23:59:59")
                if not parsed:
                    raise AdError("La fecha de fin no es válida")
                ends = parsed.isoformat()
            weight = max(1, min(10, int(raw.get("weight") or 1)))
            now = _now()
            if raw.get("id"):
                row = conn.execute("SELECT * FROM ads WHERE id=?", (int(raw["id"]),)).fetchone()
                if not row:
                    raise HTTPException(404, "Anuncio no encontrado")
                conn.execute(
                    "UPDATE ads SET business_name=?,title=?,body=?,cta=?,link_url=?,image_url=?,weight=?,ends_at=?,active=?,updated_at=? WHERE id=?",
                    (fields["business_name"], fields["title"], fields["body"], fields["cta"], fields["link_url"],
                     fields["image_url"], weight, ends, 1 if raw.get("active", True) else 0, now, row["id"]),
                )
                ad_id = row["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO ads(source,business_name,title,body,cta,link_url,image_url,status,active,weight,ends_at,created_at,updated_at) "
                    "VALUES('admin',?,?,?,?,?,?, 'approved',?,?,?,?,?)",
                    (fields["business_name"], fields["title"], fields["body"], fields["cta"], fields["link_url"],
                     fields["image_url"], 1 if raw.get("active", True) else 0, weight, ends, now, now),
                )
                ad_id = cur.lastrowid
            conn.commit()
        except AdError as exc:
            conn.rollback()
            raise HTTPException(400, str(exc))
        finally:
            conn.close()
        audit(ident["username"], "ad_saved", ad_id, {})
        return {"success": True, "id": ad_id}

    @router.post("/api/admin/ads/action")
    def admin_action(p: AdAction, request: Request):
        ident = admin(request, "ads")
        conn = _conn()
        try:
            result = apply_admin_action(conn, int(p.id), p.action, p.reason, ident["username"])
        except AdError as exc:
            raise HTTPException(400, str(exc))
        finally:
            conn.close()
        audit(ident["username"], "ad_" + (p.action or "").strip().lower(), p.id, {"reason": p.reason or ""})
        _notify_ad_result(notify, result)
        _notify_review(review, {"id": result["id"], "decision": result["status"], "reason": result["reason"]})
        return {"success": True}

    @router.post("/api/admin/ads/delete")
    def admin_delete(p: AdId, request: Request):
        ident = admin(request, "ads")
        conn = _conn()
        try:
            conn.execute("DELETE FROM ads WHERE id=?", (int(p.id),))
            conn.commit()
        finally:
            conn.close()
        audit(ident["username"], "ad_deleted", p.id, {})
        return {"success": True}

    class AdImageUpload(BaseModel):
        image: str  # base64 data-URL or raw base64

    @router.post("/api/ads/upload-image")
    def upload_ad_image(p: AdImageUpload, request: Request):
        """Recibe imagen base64, la sube a Tigris (público) o disco. Devuelve la URL."""
        import base64 as _b64, uuid as _uuid, os as _os
        try:
            from . import storage as _storage
        except ImportError:
            import storage as _storage
        uid = current_user(request)
        b64 = p.image or ""
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        try:
            img_bytes = _b64.b64decode(b64)
        except Exception:
            raise HTTPException(400, "Imagen inválida")
        if len(img_bytes) > 5 * 1024 * 1024:
            raise HTTPException(400, "La imagen no puede superar 5 MB")
        ct = "image/jpeg"
        if img_bytes[:4] == b'\x89PNG':
            ct = "image/png"
        elif img_bytes[:6] in (b'GIF87a', b'GIF89a'):
            ct = "image/gif"
        elif img_bytes[:4] == b'RIFF' and img_bytes[8:12] == b'WEBP':
            ct = "image/webp"
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}.get(ct, "jpg")
        filename = f"ad_{_uuid.uuid4().hex}.{ext}"
        if _storage.enabled():
            try:
                s = _storage._settings()
                _storage._get_client().put_object(
                    Bucket=s["bucket"], Key=f"ads/{filename}",
                    Body=img_bytes, ContentType=ct,
                )
                # Build public URL — Tigris public buckets serve at endpoint/bucket/key
                endpoint = s["endpoint"].rstrip("/")
                bucket = s["bucket"]
                url = f"{endpoint}/{bucket}/ads/{filename}"
                return {"url": url, "filename": filename}
            except Exception as exc:
                logger.warning("Tigris ad upload failed: %s", exc)
                raise HTTPException(500, "Error subiendo imagen. Inténtalo de nuevo.")
        else:
            photos_dir = getattr(request.app.state, "photos_dir", None)
            if not photos_dir:
                raise HTTPException(503, "Almacenamiento no configurado. Activa Tigris.")
            ads_dir = _os.path.join(photos_dir, "ads")
            _os.makedirs(ads_dir, exist_ok=True)
            with open(_os.path.join(ads_dir, filename), "wb") as fh:
                fh.write(img_bytes)
            return {"url": f"/api/ads/image/{filename}", "filename": filename}

    @router.get("/api/ads/image/{filename}")
    def serve_ad_image(filename: str, request: Request):
        """Sirve imágenes de anuncios guardadas en disco (fallback sin Tigris)."""
        import os as _os
        from fastapi.responses import FileResponse
        safe = _os.path.basename(filename or "")
        if not safe or not safe.startswith("ad_"):
            raise HTTPException(404, "No encontrada")
        photos_dir = getattr(request.app.state, "photos_dir", None)
        if not photos_dir:
            raise HTTPException(404, "No encontrada")
        path = _os.path.join(photos_dir, "ads", safe)
        if not _os.path.isfile(path):
            raise HTTPException(404, "No encontrada")
        return FileResponse(path)

    return router
