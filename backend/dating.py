"""LiggaCuba Citas: descubrir perfiles, dar like y hacer match.

Decisiones de diseño
--------------------
* NO hay chat interno. Cuando dos personas se dan like (match), cada una ve el
  canal de contacto que la otra decidió compartir: su usuario de Telegram
  (t.me/usuario) y/o su WhatsApp (wa.me/numero). La conversación ocurre fuera.
* Los contactos solo se muestran en matches activos. Bloquear o deshacer un
  match los oculta de inmediato.
* Se exige ser mayor de 18 años (fecha de nacimiento) y aceptar los términos.
* Toda foto pasa por revisión manual (estado ``pending`` -> ``approved``) antes de
  que el perfil aparezca en el feed de otras personas.
* Los perfiles se identifican hacia fuera con un ``public_id`` opaco; el ID de
  Telegram nunca viaja a otros usuarios.

La lógica de negocio (funciones que reciben una conexión sqlite3) no depende de
FastAPI, así que se puede probar sin levantar el servidor. ``build_router`` crea
las rutas HTTP y recibe sus dependencias desde ``main.py``.
"""
import base64
import binascii
import hashlib
import hmac
import io
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

try:
    from . import limits as _limits
    from . import storage as _storage
except ImportError:  # uvicorn ejecutado con backend/ como directorio de trabajo
    import limits as _limits
    import storage as _storage

logger = logging.getLogger(__name__)

MIN_AGE = 18
MAX_AGE = 99
MAX_PHOTOS = 6
MAX_BIO = 300
MAX_NAME = 40
MAX_INTERESTS = 6
PHOTO_MAX_BYTES = 8 * 1024 * 1024
PHOTO_MAX_SIDE = 1080
PHOTO_MAX_PIXELS = 24_000_000
PHOTO_URL_TTL = 3600
REPORT_AUTOHIDE_THRESHOLD = 3
UNDO_WINDOW_SECONDS = 24 * 3600
MAX_MINOR_REPORTS_PER_DAY = 3

GENDERS = ("hombre", "mujer", "otro")
LOOKING_FOR = ("hombres", "mujeres", "todos")
LOOKING_TO_GENDER = {"hombres": "hombre", "mujeres": "mujer"}
GENDER_TO_LOOKING = {"hombre": "hombres", "mujer": "mujeres"}
PROVINCES = (
    "Pinar del Río", "Artemisa", "La Habana", "Mayabeque", "Matanzas", "Cienfuegos",
    "Villa Clara", "Sancti Spíritus", "Ciego de Ávila", "Camagüey", "Las Tunas",
    "Holguín", "Granma", "Santiago de Cuba", "Guantánamo", "Isla de la Juventud",
    "Fuera de Cuba",
)
REPORT_REASONS = ("fake", "inappropriate_photo", "harassment", "minor", "scam", "other")

_LINK_RE = re.compile(r"(https?://|www\.|t\.me/|wa\.me/|@\w{4,})", re.IGNORECASE)
_TG_USER_RE = re.compile(r"^[A-Za-z0-9_]{4,32}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS dating_profiles(
  user_id TEXT PRIMARY KEY, public_id TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL, birth_date TEXT NOT NULL,
  gender TEXT NOT NULL, looking_for TEXT NOT NULL,
  province TEXT NOT NULL, municipality TEXT NOT NULL DEFAULT '',
  bio TEXT NOT NULL DEFAULT '', interests TEXT NOT NULL DEFAULT '[]', prefs TEXT NOT NULL DEFAULT '{}',
  min_age INTEGER NOT NULL DEFAULT 18, max_age INTEGER NOT NULL DEFAULT 99,
  whatsapp TEXT NOT NULL DEFAULT '', share_telegram INTEGER NOT NULL DEFAULT 0,
  visible INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'active',
  accepted_terms_at TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dating_photos(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, filename TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
  reject_reason TEXT, created_at TEXT NOT NULL, reviewed_at TEXT, reviewed_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_dating_photos_user ON dating_photos(user_id,status);
CREATE TABLE IF NOT EXISTS dating_swipes(
  user_id TEXT NOT NULL, target_id TEXT NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(user_id,target_id)
);
CREATE INDEX IF NOT EXISTS idx_dating_swipes_target ON dating_swipes(target_id,action);
CREATE INDEX IF NOT EXISTS idx_dating_swipes_day ON dating_swipes(user_id,action,created_at);
CREATE TABLE IF NOT EXISTS dating_matches(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_a TEXT NOT NULL, user_b TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, ended_at TEXT,
  UNIQUE(user_a,user_b)
);
CREATE TABLE IF NOT EXISTS dating_blocks(
  blocker_id TEXT NOT NULL, blocked_id TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(blocker_id,blocked_id)
);
CREATE TABLE IF NOT EXISTS dating_reports(
  id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id TEXT NOT NULL, reported_id TEXT NOT NULL,
  reason TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
  resolution TEXT, created_at TEXT NOT NULL, resolved_at TEXT, resolved_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_dating_reports_open ON dating_reports(reported_id,status);
"""


class DatingError(Exception):
    """Error de negocio con código HTTP sugerido."""

    def __init__(self, message: str, status: int = 400, code: str = "error"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def init_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    # Bases creadas antes del asistente de perfil no tienen la columna ``prefs``.
    columns = {row[1] for row in connection.execute("PRAGMA table_info(dating_profiles)").fetchall()}
    if "prefs" not in columns:
        connection.execute("ALTER TABLE dating_profiles ADD COLUMN prefs TEXT NOT NULL DEFAULT '{}'")
        connection.commit()
    # Share-to-earn: tabla de bonus de likes por compartir estado
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS dating_share_earn(
        user_id   TEXT NOT NULL,
        earn_date TEXT NOT NULL,          -- fecha YYYY-MM-DD (hora Cuba)
        bonus     INTEGER NOT NULL DEFAULT 10,
        granted_at TEXT NOT NULL,
        PRIMARY KEY(user_id, earn_date)
    );
    """)


def _utcnow() -> datetime:
    """Fecha/hora UTC sin zona (mismo formato que ya hay guardado en la base)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _now() -> str:
    return _utcnow().isoformat()


def _today() -> date:
    return _utcnow().date()


try:  # hora de Cuba: el resto de la app reinicia los límites diarios a medianoche cubana
    from zoneinfo import ZoneInfo
    _CUBA_TZ = ZoneInfo("America/Havana")
except Exception:  # pragma: no cover - sin base de zonas horarias
    _CUBA_TZ = timezone(timedelta(hours=-5))


def _cuba_today() -> date:
    return datetime.now(timezone.utc).astimezone(_CUBA_TZ).date()


def _cuba_day_start_utc(day: date) -> str:
    """Medianoche cubana de ``day`` expresada en UTC (formato ISO sin zona)."""
    start = datetime(day.year, day.month, day.day, tzinfo=_CUBA_TZ).astimezone(timezone.utc)
    return start.replace(tzinfo=None).isoformat()


# ---------------------------------------------------------------------------
# Preferencias del asistente de perfil (lista blanca: lo demás se descarta)
# ---------------------------------------------------------------------------

PREF_SCHEMA = {
    # clave: (tipo, opciones permitidas)
    "intent": ("multi", ("serious", "casual", "online", "unsure")),
    "important": ("multi", ("travel", "emotional", "fun", "family", "goals")),
    "attention": ("multi", ("eyes", "hair", "smile", "style", "voice", "humor")),
    "distance": ("single", ("neighborhood", "city", "province", "any")),
    "first_move": ("single", ("me", "them", "either")),
    "work": ("single", ("office", "flexible", "night", "own")),
    "weekend": ("single", ("out", "sport", "home", "work")),
    "social": ("single", ("party", "small", "reserved", "mood")),
    "first_date": ("single", ("coffee", "dinner", "active", "undecided")),
    "kids": ("single", ("want", "open", "have", "no")),
    "ambition": ("single", ("career", "balanced", "family", "any")),
    "common": ("multi", ("traditional", "home", "travel", "growth", "career", "sport", "cinema", "nightlife")),
    "dealbreakers": ("multi", ("smoke", "no_relationship", "far", "values", "none")),
}
# Campos de opción única cuya coincidencia suma puntos en el feed (clave -> peso).
_MATCH_SINGLE_WEIGHTS = {"work": 1, "weekend": 1, "social": 1, "first_date": 1, "kids": 2, "ambition": 1}
_MATCH_MULTI_WEIGHTS = {"intent": 3, "important": 1, "common": 1, "attention": 0}


def clean_prefs(raw: Any) -> Dict[str, Any]:
    """Valida las respuestas del asistente. Ignora claves y valores desconocidos."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, (kind, options) in PREF_SCHEMA.items():
        value = raw.get(key)
        if kind == "single":
            if isinstance(value, str) and value in options:
                out[key] = value
        elif isinstance(value, (list, tuple)):
            picked: List[str] = []
            for item in value:
                if isinstance(item, str) and item in options and item not in picked:
                    picked.append(item)
            if "none" in picked and len(picked) > 1:
                picked = ["none"]
            if picked:
                out[key] = picked
    return out


def load_prefs(raw: Any) -> Dict[str, Any]:
    try:
        return clean_prefs(json.loads(raw or "{}"))
    except (TypeError, ValueError):
        return {}


def compat_score(mine: Dict[str, Any], theirs: Dict[str, Any]) -> int:
    """Puntos por coincidencias entre dos juegos de preferencias (solo ordena el feed)."""
    score = 0
    for key, weight in _MATCH_SINGLE_WEIGHTS.items():
        if mine.get(key) and mine.get(key) == theirs.get(key):
            score += weight
    for key, weight in _MATCH_MULTI_WEIGHTS.items():
        shared = set(mine.get(key, [])) & set(theirs.get(key, []))
        if shared:
            score += weight * (1 if key == "intent" else len(shared))
    return score


def in_common(mine: Dict[str, Any], theirs: Dict[str, Any]) -> int:
    """Número de respuestas en común que se muestra en la tarjeta."""
    total = 0
    for key, (kind, _options) in PREF_SCHEMA.items():
        if key == "dealbreakers":
            continue
        if kind == "single":
            total += 1 if mine.get(key) and mine.get(key) == theirs.get(key) else 0
        else:
            total += len(set(mine.get(key, [])) & set(theirs.get(key, [])))
    return total


# ---------------------------------------------------------------------------
# Validación del perfil
# ---------------------------------------------------------------------------

def age_from(birth_date: str, today: Optional[date] = None) -> int:
    born = date.fromisoformat(birth_date)
    today = today or _today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def normalize_whatsapp(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits:
        return ""
    if len(digits) == 8 and digits.startswith("5"):
        digits = "53" + digits  # móvil cubano sin prefijo de país
    if not 8 <= len(digits) <= 15:
        raise DatingError("El número de WhatsApp no es válido (incluye el código de país).")
    return digits


def _clean_text(value: Any, maximum: int, field: str, required: bool = False) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    if required and not text:
        raise DatingError(f"{field} es obligatorio.")
    if len(text) > maximum:
        raise DatingError(f"{field} admite máximo {maximum} caracteres.")
    if _LINK_RE.search(text):
        raise DatingError(f"{field} no puede incluir enlaces ni usuarios. Tu contacto se comparte solo con tus matches.")
    return text


def clean_profile(data: Dict[str, Any], telegram_username: str = "", existing: bool = False,
                  today: Optional[date] = None, locked_birth_date: Optional[str] = None) -> Dict[str, Any]:
    """Valida el perfil. Si ``locked_birth_date`` viene, la fecha de nacimiento no se puede cambiar."""
    today = today or _today()
    if locked_birth_date:
        sent = str(data.get("birth_date") or "")
        if sent and sent != locked_birth_date:
            raise DatingError("La fecha de nacimiento no se puede cambiar. Si te equivocaste, contacta a soporte.", 409, "birth_locked")
        data = {**data, "birth_date": locked_birth_date}
    name = _clean_text(data.get("display_name"), MAX_NAME, "El nombre", required=True)
    if len(name) < 2:
        raise DatingError("El nombre debe tener al menos 2 caracteres.")
    try:
        birth = date.fromisoformat(str(data.get("birth_date") or ""))
    except ValueError:
        raise DatingError("La fecha de nacimiento no es válida.")
    age = age_from(birth.isoformat(), today)
    if age < MIN_AGE:
        raise DatingError("Debes ser mayor de 18 años para usar Citas.", 403, "underage")
    if age > MAX_AGE:
        raise DatingError("La fecha de nacimiento no es válida.")
    gender = str(data.get("gender") or "")
    looking = str(data.get("looking_for") or "")
    if gender not in GENDERS:
        raise DatingError("Selecciona tu género.")
    if looking not in LOOKING_FOR:
        raise DatingError("Selecciona a quién quieres conocer.")
    province = str(data.get("province") or "")
    if province not in PROVINCES:
        raise DatingError("Selecciona tu provincia.")
    municipality = _clean_text(data.get("municipality"), 60, "El municipio")
    bio = _clean_text(data.get("bio"), MAX_BIO, "La descripción")
    interests = []
    for item in (data.get("interests") or [])[:MAX_INTERESTS]:
        text = _clean_text(item, 20, "Un interés")
        if text and text.lower() not in [x.lower() for x in interests]:
            interests.append(text)
    try:
        min_age = int(data.get("min_age") or MIN_AGE)
        max_age = int(data.get("max_age") or MAX_AGE)
    except (TypeError, ValueError):
        raise DatingError("El rango de edad no es válido.")
    min_age = max(MIN_AGE, min(MAX_AGE, min_age))
    max_age = max(MIN_AGE, min(MAX_AGE, max_age))
    if min_age > max_age:
        raise DatingError("La edad mínima no puede ser mayor que la máxima.")
    whatsapp = normalize_whatsapp(data.get("whatsapp"))
    share_telegram = bool(data.get("share_telegram"))
    if share_telegram and not _TG_USER_RE.match(telegram_username or ""):
        raise DatingError("Para compartir Telegram necesitas tener un @usuario en tu cuenta de Telegram.")
    if not share_telegram and not whatsapp:
        raise DatingError("Elige al menos un canal para que tus matches te escriban: Telegram o WhatsApp.")
    if not existing:
        if not data.get("confirm_adult"):
            raise DatingError("Debes confirmar que eres mayor de 18 años.")
        if not data.get("accept_terms"):
            raise DatingError("Debes aceptar los términos de Citas.")
    return {
        "display_name": name, "birth_date": birth.isoformat(), "gender": gender, "looking_for": looking,
        "province": province, "municipality": municipality, "bio": bio,
        "interests": json.dumps(interests, ensure_ascii=False), "min_age": min_age, "max_age": max_age,
        "whatsapp": whatsapp, "share_telegram": 1 if share_telegram else 0,
        # None = no venía en la petición: se conservan las preferencias guardadas.
        "prefs": json.dumps(clean_prefs(data.get("prefs")), ensure_ascii=False) if data.get("prefs") is not None else None,
    }


def get_profile(c: sqlite3.Connection, uid: str) -> Optional[sqlite3.Row]:
    return c.execute("SELECT * FROM dating_profiles WHERE user_id=?", (str(uid),)).fetchone()


def upsert_profile(c: sqlite3.Connection, uid: str, cleaned: Dict[str, Any], now: Optional[str] = None) -> sqlite3.Row:
    now = now or _now()
    uid = str(uid)
    if get_profile(c, uid):
        c.execute(
            "UPDATE dating_profiles SET display_name=?,birth_date=?,gender=?,looking_for=?,province=?,municipality=?,"
            "bio=?,interests=?,min_age=?,max_age=?,whatsapp=?,share_telegram=?,prefs=COALESCE(?,prefs),updated_at=? WHERE user_id=?",
            (cleaned["display_name"], cleaned["birth_date"], cleaned["gender"], cleaned["looking_for"],
             cleaned["province"], cleaned["municipality"], cleaned["bio"], cleaned["interests"],
             cleaned["min_age"], cleaned["max_age"], cleaned["whatsapp"], cleaned["share_telegram"],
             cleaned.get("prefs"), now, uid),
        )
    else:
        c.execute(
            "INSERT INTO dating_profiles(user_id,public_id,display_name,birth_date,gender,looking_for,province,"
            "municipality,bio,interests,min_age,max_age,whatsapp,share_telegram,prefs,accepted_terms_at,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid, uuid.uuid4().hex[:16], cleaned["display_name"], cleaned["birth_date"], cleaned["gender"],
             cleaned["looking_for"], cleaned["province"], cleaned["municipality"], cleaned["bio"],
             cleaned["interests"], cleaned["min_age"], cleaned["max_age"], cleaned["whatsapp"],
             cleaned["share_telegram"], cleaned.get("prefs") or "{}", now, now, now),
        )
    c.commit()
    return get_profile(c, uid)


# ---------------------------------------------------------------------------
# Fotos
# ---------------------------------------------------------------------------

def parse_image_data_url(data_url: str) -> bytes:
    match = re.match(r"^data:image/(jpeg|jpg|png|webp);base64,([A-Za-z0-9+/=\s]+)$", str(data_url or ""))
    if not match:
        raise DatingError("Formato de imagen no válido. Usa JPG, PNG o WEBP.")
    if len(match.group(2)) > int(PHOTO_MAX_BYTES * 1.4):
        raise DatingError("La foto supera los 8 MB.")
    try:
        raw = base64.b64decode(match.group(2), validate=False)
    except (binascii.Error, ValueError):
        raise DatingError("La imagen no se pudo leer.")
    if not raw or len(raw) > PHOTO_MAX_BYTES:
        raise DatingError("La foto supera los 8 MB.")
    return raw


def process_photo(raw: bytes) -> bytes:
    """Valida, corrige la orientación, elimina metadatos (EXIF/GPS) y recodifica a JPEG."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    Image.MAX_IMAGE_PIXELS = PHOTO_MAX_PIXELS
    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in ("JPEG", "PNG", "WEBP"):
            raise DatingError("Formato de imagen no válido. Usa JPG, PNG o WEBP.")
        if img.width * img.height > PHOTO_MAX_PIXELS:
            raise DatingError("La imagen es demasiado grande.")
        img = ImageOps.exif_transpose(img)
        img.load()
    except DatingError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise DatingError("La imagen no se pudo leer.")
    if img.mode not in ("RGB",):
        img = img.convert("RGB")
    img.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85, optimize=True)  # sin exif: no se pasa exif=
    return out.getvalue()


def add_photo(c: sqlite3.Connection, uid: str, photos_dir: str, jpeg: bytes, now: Optional[str] = None) -> Dict[str, Any]:
    uid = str(uid)
    if not get_profile(c, uid):
        raise DatingError("Primero crea tu perfil de Citas.", 409, "no_profile")
    # Las fotos rechazadas no ocupan cupo; la posición sigue al máximo para no repetirse tras borrar.
    count = c.execute("SELECT COUNT(*) FROM dating_photos WHERE user_id=? AND status!='rejected'", (uid,)).fetchone()[0]
    position = c.execute("SELECT COALESCE(MAX(position),-1)+1 FROM dating_photos WHERE user_id=?", (uid,)).fetchone()[0]
    if count >= MAX_PHOTOS:
        raise DatingError(f"Máximo {MAX_PHOTOS} fotos.", 409, "photo_limit")
    filename = uuid.uuid4().hex + ".jpg"
    # Con R2 configurado la foto va a la nube; si R2 falla o no está configurado, se guarda en disco
    # (el servidor busca primero en disco y luego en R2, así que ambas ubicaciones conviven).
    if not _storage.put(filename, jpeg):
        os.makedirs(photos_dir, exist_ok=True)
        with open(os.path.join(photos_dir, filename), "wb") as handle:
            handle.write(jpeg)
    cur = c.execute(
        "INSERT INTO dating_photos(user_id,filename,position,status,created_at) VALUES(?,?,?,?,?)",
        (uid, filename, position, "pending", now or _now()),
    )
    c.commit()
    return {"id": cur.lastrowid, "status": "pending"}


def delete_photo(c: sqlite3.Connection, uid: str, photos_dir: str, photo_id: int) -> None:
    row = c.execute("SELECT * FROM dating_photos WHERE id=? AND user_id=?", (int(photo_id), str(uid))).fetchone()
    if not row:
        raise DatingError("Foto no encontrada.", 404)
    c.execute("DELETE FROM dating_photos WHERE id=?", (row["id"],))
    c.commit()
    _remove_file(photos_dir, row["filename"])


def _remove_file(photos_dir: str, filename: str) -> None:
    """Borra la foto de disco y de R2 (donde esté). Nunca lanza errores."""
    safe = os.path.basename(filename or "")
    if not safe:
        return
    try:
        os.remove(os.path.join(photos_dir, safe))
    except OSError:
        pass
    _storage.delete(safe)  # no-op si R2 no está configurado


def read_photo_bytes(photos_dir: str, filename: str) -> Optional[bytes]:
    """Lee una foto: primero disco (fotos antiguas), luego R2."""
    safe = os.path.basename(filename or "")
    if not safe:
        return None
    path = os.path.join(photos_dir, safe)
    if os.path.isfile(path):
        with open(path, "rb") as handle:
            return handle.read()
    return _storage.get(safe)


def photo_signature(secret: str, photo_id: int, expires: int) -> str:
    digest = hmac.new(secret.encode(), f"dating-photo:{int(photo_id)}:{int(expires)}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:32]


def photo_url(secret: str, photo_id: int, now: Optional[float] = None) -> str:
    """URL firmada y estable durante ~1 hora (permite caché del navegador)."""
    now = time.time() if now is None else now
    expires = (int(now) // PHOTO_URL_TTL + 2) * PHOTO_URL_TTL
    return f"/api/dating/photo/{int(photo_id)}?e={expires}&s={photo_signature(secret, photo_id, expires)}"


def verify_photo_signature(secret: str, photo_id: int, expires: int, signature: str, now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    if int(expires) < int(now):
        return False
    return hmac.compare_digest(str(signature or ""), photo_signature(secret, photo_id, expires))


# ---------------------------------------------------------------------------
# Tarjetas públicas y contactos
# ---------------------------------------------------------------------------

def _approved_photo_urls(c: sqlite3.Connection, user_id: str, secret: str) -> List[str]:
    rows = c.execute(
        "SELECT id FROM dating_photos WHERE user_id=? AND status='approved' ORDER BY position,id", (user_id,)
    ).fetchall()
    return [photo_url(secret, r["id"]) for r in rows]


def card(c: sqlite3.Connection, row: sqlite3.Row, secret: str, viewer_province: str = "",
         viewer_prefs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = {
        "public_id": row["public_id"], "display_name": row["display_name"], "age": age_from(row["birth_date"]),
        "province": row["province"], "municipality": row["municipality"], "bio": row["bio"],
        "interests": json.loads(row["interests"] or "[]"),
        "photos": _approved_photo_urls(c, row["user_id"], secret),
        "same_province": bool(viewer_province) and row["province"] == viewer_province,
    }
    if viewer_prefs is not None:
        out["in_common"] = in_common(viewer_prefs, load_prefs(row["prefs"]))
    return out


def contact_links(row: sqlite3.Row, telegram_username: str) -> List[Dict[str, str]]:
    """Canales externos que la persona eligió compartir con sus matches."""
    links = []
    if row["share_telegram"] and _TG_USER_RE.match(telegram_username or ""):
        links.append({"type": "telegram", "label": "Telegram", "url": f"https://t.me/{telegram_username}"})
    if row["whatsapp"]:
        links.append({"type": "whatsapp", "label": "WhatsApp", "url": f"https://wa.me/{row['whatsapp']}"})
    return links


def _username_of(c: sqlite3.Connection, uid: str) -> str:
    row = c.execute("SELECT username FROM users WHERE user_id=?", (str(uid),)).fetchone()
    return (row["username"] if row and row["username"] else "") or ""


def _pair(a: str, b: str):
    return (a, b) if a < b else (b, a)


def _is_blocked(c: sqlite3.Connection, a: str, b: str) -> bool:
    return bool(c.execute(
        "SELECT 1 FROM dating_blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)",
        (a, b, b, a)).fetchone())


def _by_public_id(c: sqlite3.Connection, public_id: str) -> sqlite3.Row:
    row = c.execute("SELECT * FROM dating_profiles WHERE public_id=?", (str(public_id or ""),)).fetchone()
    if not row:
        raise DatingError("Perfil no encontrado.", 404)
    return row


def require_active_profile(c: sqlite3.Connection, uid: str) -> sqlite3.Row:
    me = get_profile(c, uid)
    if not me:
        raise DatingError("Primero crea tu perfil de Citas.", 409, "no_profile")
    if me["status"] == "suspended":
        raise DatingError("Tu perfil de Citas está suspendido. Contacta a soporte.", 403, "suspended")
    return me


def overview(c: sqlite3.Connection, uid: str, secret: str) -> Dict[str, Any]:
    me = get_profile(c, uid)
    if not me:
        return {"profile": None, "photos": []}
    photos = [
        {"id": r["id"], "status": r["status"], "reject_reason": r["reject_reason"], "url": photo_url(secret, r["id"])}
        for r in c.execute("SELECT * FROM dating_photos WHERE user_id=? ORDER BY position,id", (str(uid),)).fetchall()
    ]
    profile = {k: me[k] for k in ("public_id", "display_name", "birth_date", "gender", "looking_for", "province",
                                   "municipality", "bio", "min_age", "max_age", "whatsapp", "status")}
    profile["interests"] = json.loads(me["interests"] or "[]")
    profile["prefs"] = load_prefs(me["prefs"])
    profile["share_telegram"] = bool(me["share_telegram"])
    profile["visible"] = bool(me["visible"])
    profile["age"] = age_from(me["birth_date"])
    profile["telegram_username"] = _username_of(c, uid)
    return {"profile": profile, "photos": photos}


# ---------------------------------------------------------------------------
# Feed, swipes y matches
# ---------------------------------------------------------------------------

def candidate_feed(c: sqlite3.Connection, uid: str, secret: str, limit: int = 10, today: Optional[date] = None) -> List[Dict[str, Any]]:
    uid = str(uid)
    me = require_active_profile(c, uid)
    if not c.execute("SELECT 1 FROM dating_photos WHERE user_id=?", (uid,)).fetchone():
        raise DatingError("Sube al menos una foto para ver perfiles.", 409, "no_photo")
    my_age = age_from(me["birth_date"], today)
    sql = (
        "SELECT p.* FROM dating_profiles p WHERE p.user_id != ? AND p.status='active' AND p.visible=1 "
        "AND EXISTS(SELECT 1 FROM dating_photos ph WHERE ph.user_id=p.user_id AND ph.status='approved') "
        "AND NOT EXISTS(SELECT 1 FROM dating_swipes s WHERE s.user_id=? AND s.target_id=p.user_id) "
        "AND NOT EXISTS(SELECT 1 FROM dating_blocks b WHERE (b.blocker_id=? AND b.blocked_id=p.user_id) "
        "OR (b.blocker_id=p.user_id AND b.blocked_id=?)) "
    )
    params: List[Any] = [uid, uid, uid, uid]
    wanted = LOOKING_TO_GENDER.get(me["looking_for"])
    if wanted:
        sql += "AND p.gender=? "
        params.append(wanted)
    their_need = GENDER_TO_LOOKING.get(me["gender"])
    if their_need:
        sql += "AND p.looking_for IN ('todos',?) "
        params.append(their_need)
    else:
        sql += "AND p.looking_for='todos' "
    sql += "ORDER BY (p.province=?) DESC, RANDOM() LIMIT 200"
    params.append(me["province"])
    my_prefs = load_prefs(me["prefs"])
    wants_near = my_prefs.get("distance") in ("neighborhood", "city")
    candidates = []
    for row in c.execute(sql, params).fetchall():
        their_age = age_from(row["birth_date"], today)
        if not (me["min_age"] <= their_age <= me["max_age"]):
            continue
        if not (row["min_age"] <= my_age <= row["max_age"]):
            continue
        score = compat_score(my_prefs, load_prefs(row["prefs"]))
        if wants_near and row["province"] == me["province"] and me["municipality"] and row["municipality"].lower() == me["municipality"].lower():
            score += 2
        candidates.append((row["province"] == me["province"], score, row))
    # sort estable: la misma provincia primero, luego más afinidad; el azar de SQL desempata
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [card(c, row, secret, me["province"], my_prefs) for _same, _score, row in candidates[:limit]]


def likes_today(c: sqlite3.Connection, uid: str, today: Optional[date] = None) -> int:
    """Likes dados hoy. El día cambia a medianoche de Cuba (igual que el resto de la app)."""
    start = _cuba_day_start_utc(today or _cuba_today())
    return c.execute(
        "SELECT COUNT(*) FROM dating_swipes WHERE user_id=? AND action='like' AND created_at>=?", (str(uid), start)
    ).fetchone()[0]


SHARE_EARN_BONUS = 10  # likes extra al compartir estado


def share_earn_today(c: sqlite3.Connection, uid: str, today: Optional[str] = None) -> int:
    """Devuelve el bonus de likes ganado hoy por compartir estado (0 si no ha compartido)."""
    today = today or _cuba_today().isoformat()
    row = c.execute(
        "SELECT bonus FROM dating_share_earn WHERE user_id=? AND earn_date=?", (str(uid), today)
    ).fetchone()
    return int(row["bonus"]) if row else 0


def effective_daily_limit(c: sqlite3.Connection, uid: str, base_limit: int, today: Optional[str] = None) -> int:
    """Límite diario efectivo = base + bonus de share-to-earn del día."""
    return base_limit + share_earn_today(c, uid, today)


def grant_share_earn(c: sqlite3.Connection, uid: str, today: Optional[str] = None) -> Dict[str, Any]:
    """Registra que el usuario compartió su estado hoy y le da SHARE_EARN_BONUS likes extra.

    Idempotente: si ya compartió hoy devuelve already_granted=True sin doblar el bonus.
    """
    today = today or _cuba_today().isoformat()
    now_ts = _now()
    existing = c.execute(
        "SELECT bonus FROM dating_share_earn WHERE user_id=? AND earn_date=?", (str(uid), today)
    ).fetchone()
    if existing:
        return {"granted": False, "already_granted": True, "bonus": int(existing["bonus"]), "earn_date": today}
    c.execute(
        "INSERT INTO dating_share_earn(user_id,earn_date,bonus,granted_at) VALUES(?,?,?,?)",
        (str(uid), today, SHARE_EARN_BONUS, now_ts),
    )
    c.commit()
    return {"granted": True, "already_granted": False, "bonus": SHARE_EARN_BONUS, "earn_date": today}





# Override with proper Cuba timezone when available
try:
    from zoneinfo import ZoneInfo as _ZI
    _CUBA_TZ = _ZI("America/Havana")
    def _cuba_today() -> date:  # noqa: F811
        from datetime import timezone as _tz
        return datetime.now(_tz.utc).astimezone(_CUBA_TZ).date()
except Exception:
    pass  # already defined above


def record_swipe(c: sqlite3.Connection, uid: str, target_public_id: str, action: str, daily_limit: int,
                 is_premium: bool, now: Optional[str] = None) -> Dict[str, Any]:
    uid = str(uid)
    if action not in ("like", "pass"):
        raise DatingError("Acción no válida.")
    now = now or _now()
    c.execute("BEGIN IMMEDIATE")
    try:
        me = require_active_profile(c, uid)
        target = _by_public_id(c, target_public_id)
        tid = target["user_id"]
        if tid == uid:
            raise DatingError("No puedes interactuar con tu propio perfil.")
        if target["status"] != "active" or _is_blocked(c, uid, tid):
            raise DatingError("Perfil no disponible.", 404)
        if c.execute("SELECT 1 FROM dating_swipes WHERE user_id=? AND target_id=?", (uid, tid)).fetchone():
            c.rollback()
            eff_limit = effective_daily_limit(c, uid, daily_limit)
            return {"matched": False, "duplicate": True, "likes_left": _likes_left(c, uid, eff_limit, is_premium)}
        eff_limit = effective_daily_limit(c, uid, daily_limit)
        if action == "like" and not is_premium and likes_today(c, uid) >= eff_limit:
            raise DatingError("Llegaste al límite diario de likes. Mejora a Premium para likes ilimitados.", 403, "daily_limit")
        c.execute("INSERT INTO dating_swipes(user_id,target_id,action,created_at) VALUES(?,?,?,?)", (uid, tid, action, now))
        matched = False
        if action == "like" and c.execute(
                "SELECT 1 FROM dating_swipes WHERE user_id=? AND target_id=? AND action='like'", (tid, uid)).fetchone():
            a, b = _pair(uid, tid)
            c.execute("INSERT OR IGNORE INTO dating_matches(user_a,user_b,status,created_at) VALUES(?,?,?,?)", (a, b, "active", now))
            c.execute("UPDATE dating_matches SET status='active',ended_at=NULL WHERE user_a=? AND user_b=? AND status!='active'", (a, b))
            matched = True
        c.commit()
    except Exception:
        c.rollback()
        raise
    eff_limit = effective_daily_limit(c, uid, daily_limit)
    result: Dict[str, Any] = {"matched": matched, "duplicate": False, "likes_left": _likes_left(c, uid, eff_limit, is_premium)}
    if matched:
        result["notify"] = [uid, tid]
        result["match_public_id"] = target["public_id"]
    return result


def _likes_left(c: sqlite3.Connection, uid: str, daily_limit: int, is_premium: bool) -> Optional[int]:
    return None if is_premium else max(0, daily_limit - likes_today(c, uid))


def undo_last_swipe(c: sqlite3.Connection, uid: str, secret: str, now: Optional[float] = None) -> Dict[str, Any]:
    """Premium: deshace el último swipe si no generó un match."""
    uid = str(uid)
    require_active_profile(c, uid)
    row = c.execute("SELECT * FROM dating_swipes WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (uid,)).fetchone()
    if not row:
        raise DatingError("No hay nada que deshacer.", 404)
    age = (_utcnow() - datetime.fromisoformat(row["created_at"])).total_seconds()
    if age > UNDO_WINDOW_SECONDS:
        raise DatingError("Ese swipe ya no se puede deshacer.", 409)
    a, b = _pair(uid, row["target_id"])
    if c.execute("SELECT 1 FROM dating_matches WHERE user_a=? AND user_b=?", (a, b)).fetchone():
        raise DatingError("Ese like ya generó un match; no se puede deshacer.", 409)
    c.execute("DELETE FROM dating_swipes WHERE user_id=? AND target_id=?", (uid, row["target_id"]))
    c.commit()
    target = c.execute("SELECT * FROM dating_profiles WHERE user_id=?", (row["target_id"],)).fetchone()
    me = get_profile(c, uid)
    return {"profile": card(c, target, secret, me["province"], load_prefs(me["prefs"])) if target and target["status"] == "active" else None}


def likes_received(c: sqlite3.Connection, uid: str, secret: str, is_premium: bool) -> Dict[str, Any]:
    uid = str(uid)
    me = require_active_profile(c, uid)
    rows = c.execute(
        "SELECT p.* FROM dating_swipes s JOIN dating_profiles p ON p.user_id=s.user_id "
        "WHERE s.target_id=? AND s.action='like' AND p.status='active' AND p.visible=1 "
        "AND NOT EXISTS(SELECT 1 FROM dating_swipes m WHERE m.user_id=? AND m.target_id=s.user_id) "
        "AND NOT EXISTS(SELECT 1 FROM dating_blocks b WHERE (b.blocker_id=? AND b.blocked_id=p.user_id) "
        "OR (b.blocker_id=p.user_id AND b.blocked_id=?)) "
        "AND EXISTS(SELECT 1 FROM dating_photos ph WHERE ph.user_id=p.user_id AND ph.status='approved') "
        "ORDER BY s.created_at DESC LIMIT 50", (uid, uid, uid, uid)).fetchall()
    out: Dict[str, Any] = {"count": len(rows), "locked": not is_premium}
    if is_premium:
        my_prefs = load_prefs(me["prefs"])
        out["profiles"] = [card(c, r, secret, me["province"], my_prefs) for r in rows]
    return out


def list_matches(c: sqlite3.Connection, uid: str, secret: str) -> List[Dict[str, Any]]:
    uid = str(uid)
    require_active_profile(c, uid)
    out = []
    rows = c.execute(
        "SELECT * FROM dating_matches WHERE status='active' AND (user_a=? OR user_b=?) ORDER BY created_at DESC",
        (uid, uid)).fetchall()
    for m in rows:
        other_id = m["user_b"] if m["user_a"] == uid else m["user_a"]
        other = c.execute("SELECT * FROM dating_profiles WHERE user_id=?", (other_id,)).fetchone()
        if not other or other["status"] == "suspended" or _is_blocked(c, uid, other_id):
            continue
        item = card(c, other, secret)
        item["match_id"] = m["id"]
        item["matched_at"] = m["created_at"]
        item["contacts"] = contact_links(other, _username_of(c, other_id))
        out.append(item)
    return out


def unmatch(c: sqlite3.Connection, uid: str, match_id: int, now: Optional[str] = None) -> None:
    uid = str(uid)
    row = c.execute("SELECT * FROM dating_matches WHERE id=? AND (user_a=? OR user_b=?)", (int(match_id), uid, uid)).fetchone()
    if not row:
        raise DatingError("Match no encontrado.", 404)
    c.execute("UPDATE dating_matches SET status='unmatched',ended_at=? WHERE id=?", (now or _now(), row["id"]))
    c.commit()


def block_user(c: sqlite3.Connection, uid: str, target_public_id: str, now: Optional[str] = None) -> None:
    uid = str(uid)
    target = _by_public_id(c, target_public_id)
    tid = target["user_id"]
    if tid == uid:
        raise DatingError("No puedes bloquearte a ti mismo.")
    now = now or _now()
    a, b = _pair(uid, tid)
    c.execute("INSERT OR IGNORE INTO dating_blocks(blocker_id,blocked_id,created_at) VALUES(?,?,?)", (uid, tid, now))
    c.execute("UPDATE dating_matches SET status='unmatched',ended_at=? WHERE user_a=? AND user_b=? AND status='active'", (now, a, b))
    c.commit()


def report_user(c: sqlite3.Connection, uid: str, target_public_id: str, reason: str, details: str = "",
                now: Optional[str] = None) -> Dict[str, Any]:
    uid = str(uid)
    if reason not in REPORT_REASONS:
        raise DatingError("Motivo de reporte no válido.")
    target = _by_public_id(c, target_public_id)
    tid = target["user_id"]
    if tid == uid:
        raise DatingError("No puedes reportarte a ti mismo.")
    details = re.sub(r"[\x00-\x1f\x7f]", " ", str(details or "")).strip()[:500]
    if c.execute("SELECT 1 FROM dating_reports WHERE reporter_id=? AND reported_id=? AND status='open'", (uid, tid)).fetchone():
        return {"success": True, "duplicate": True}
    if reason == "minor":
        # "Parece menor" oculta el perfil al instante: se limita para que no sirva para ocultar perfiles ajenos en masa.
        since = ((_utcnow() if now is None else datetime.fromisoformat(now)) - timedelta(days=1)).isoformat()
        recent = c.execute("SELECT COUNT(*) FROM dating_reports WHERE reporter_id=? AND reason='minor' AND created_at>=?", (uid, since)).fetchone()[0]
        if recent >= MAX_MINOR_REPORTS_PER_DAY:
            raise DatingError("Has enviado demasiados reportes de este tipo hoy. Un administrador revisará los anteriores.", 429, "report_limit")
    c.execute("INSERT INTO dating_reports(reporter_id,reported_id,reason,details,created_at) VALUES(?,?,?,?,?)",
              (uid, tid, reason, details, now or _now()))
    distinct = c.execute("SELECT COUNT(DISTINCT reporter_id) FROM dating_reports WHERE reported_id=? AND status='open'", (tid,)).fetchone()[0]
    threshold = 1 if reason == "minor" else REPORT_AUTOHIDE_THRESHOLD
    hidden = False
    if distinct >= threshold and target["status"] == "active":
        c.execute("UPDATE dating_profiles SET status='under_review',updated_at=? WHERE user_id=?", (now or _now(), tid))
        hidden = True
    c.commit()
    return {"success": True, "duplicate": False, "auto_hidden": hidden}


def set_visibility(c: sqlite3.Connection, uid: str, visible: bool) -> None:
    require_active_profile(c, uid)
    c.execute("UPDATE dating_profiles SET visible=?,updated_at=? WHERE user_id=?", (1 if visible else 0, _now(), str(uid)))
    c.commit()


def delete_dating_data(c: sqlite3.Connection, uid: str, photos_dir: str) -> None:
    """Borra el perfil, fotos, swipes, matches y bloqueos de la persona. Conserva reportes (seguridad)."""
    uid = str(uid)
    files = [r["filename"] for r in c.execute("SELECT filename FROM dating_photos WHERE user_id=?", (uid,)).fetchall()]
    c.execute("DELETE FROM dating_photos WHERE user_id=?", (uid,))
    c.execute("DELETE FROM dating_swipes WHERE user_id=? OR target_id=?", (uid, uid))
    c.execute("DELETE FROM dating_matches WHERE user_a=? OR user_b=?", (uid, uid))
    c.execute("DELETE FROM dating_blocks WHERE blocker_id=? OR blocked_id=?", (uid, uid))
    c.execute("DELETE FROM dating_profiles WHERE user_id=?", (uid,))
    c.commit()
    for name in files:
        _remove_file(photos_dir, name)


# ---------------------------------------------------------------------------
# Moderación (panel de administración)
# ---------------------------------------------------------------------------

def admin_pending_photos(c: sqlite3.Connection, secret: str, limit: int = 30) -> List[Dict[str, Any]]:
    rows = c.execute(
        "SELECT ph.id,ph.user_id,ph.created_at,p.display_name,p.public_id FROM dating_photos ph "
        "JOIN dating_profiles p ON p.user_id=ph.user_id WHERE ph.status='pending' ORDER BY ph.created_at LIMIT ?",
        (int(limit),)).fetchall()
    return [{"id": r["id"], "user_id": r["user_id"], "display_name": r["display_name"],
             "created_at": r["created_at"], "url": photo_url(secret, r["id"])} for r in rows]


def admin_review_photo(c: sqlite3.Connection, photo_id: int, approve: bool, reason: str, actor: str,
                       photos_dir: str, now: Optional[str] = None) -> Dict[str, Any]:
    row = c.execute("SELECT * FROM dating_photos WHERE id=?", (int(photo_id),)).fetchone()
    if not row:
        raise DatingError("Foto no encontrada.", 404)
    now = now or _now()
    if approve:
        c.execute("UPDATE dating_photos SET status='approved',reject_reason=NULL,reviewed_at=?,reviewed_by=? WHERE id=?", (now, actor, row["id"]))
    else:
        reason = str(reason or "No cumple las normas de Citas")[:200]
        c.execute("UPDATE dating_photos SET status='rejected',reject_reason=?,reviewed_at=?,reviewed_by=? WHERE id=?", (reason, now, actor, row["id"]))
    c.commit()
    if not approve:
        _remove_file(photos_dir, row["filename"])
    return {"user_id": row["user_id"], "status": "approved" if approve else "rejected"}


def admin_list_reports(c: sqlite3.Connection, status: str = "open", limit: int = 50) -> List[Dict[str, Any]]:
    rows = c.execute(
        "SELECT r.*,p.display_name,p.status AS profile_status,p.public_id FROM dating_reports r "
        "LEFT JOIN dating_profiles p ON p.user_id=r.reported_id WHERE r.status=? ORDER BY r.created_at DESC LIMIT ?",
        (status, int(limit))).fetchall()
    return [{k: r[k] for k in ("id", "reporter_id", "reported_id", "reason", "details", "status", "created_at",
                                "display_name", "profile_status", "public_id")} for r in rows]


def admin_resolve_report(c: sqlite3.Connection, report_id: int, action: str, actor: str, now: Optional[str] = None) -> Dict[str, Any]:
    if action not in ("dismiss", "suspend"):
        raise DatingError("Acción no válida.")
    row = c.execute("SELECT * FROM dating_reports WHERE id=?", (int(report_id),)).fetchone()
    if not row:
        raise DatingError("Reporte no encontrado.", 404)
    now = now or _now()
    tid = row["reported_id"]
    if action == "suspend":
        c.execute("UPDATE dating_profiles SET status='suspended',updated_at=? WHERE user_id=?", (now, tid))
        c.execute("UPDATE dating_matches SET status='unmatched',ended_at=? WHERE (user_a=? OR user_b=?) AND status='active'", (now, tid, tid))
        c.execute("UPDATE dating_reports SET status='resolved',resolution='suspended',resolved_at=?,resolved_by=? WHERE reported_id=? AND status='open'", (now, actor, tid))
    else:
        c.execute("UPDATE dating_reports SET status='dismissed',resolution='dismissed',resolved_at=?,resolved_by=? WHERE id=?", (now, actor, row["id"]))
        if not c.execute("SELECT 1 FROM dating_reports WHERE reported_id=? AND status='open'", (tid,)).fetchone():
            c.execute("UPDATE dating_profiles SET status='active',updated_at=? WHERE user_id=? AND status='under_review'", (now, tid))
    c.commit()
    return {"user_id": tid, "action": action}


def admin_restore_profile(c: sqlite3.Connection, user_id: str, now: Optional[str] = None) -> None:
    if not get_profile(c, user_id):
        raise DatingError("Perfil no encontrado.", 404)
    c.execute("UPDATE dating_profiles SET status='active',updated_at=? WHERE user_id=?", (now or _now(), str(user_id)))
    c.commit()


def admin_stats(c: sqlite3.Connection) -> Dict[str, int]:
    one = lambda sql: c.execute(sql).fetchone()[0]
    return {
        "profiles": one("SELECT COUNT(*) FROM dating_profiles"),
        "active_profiles": one("SELECT COUNT(*) FROM dating_profiles WHERE status='active'"),
        "pending_photos": one("SELECT COUNT(*) FROM dating_photos WHERE status='pending'"),
        "open_reports": one("SELECT COUNT(*) FROM dating_reports WHERE status='open'"),
        "matches": one("SELECT COUNT(*) FROM dating_matches WHERE status='active'"),
    }


# ---------------------------------------------------------------------------
# Rutas HTTP
# ---------------------------------------------------------------------------

def build_router(*, current_user: Callable, connect: Callable, is_premium: Callable, admin: Callable,
                 audit: Callable, notify: Callable, secret: Callable, photos_dir: Callable,
                 free_daily_likes: int = 20):
    """Crea el APIRouter. ``main.py`` inyecta autenticación, base de datos y Telegram."""
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import FileResponse, Response
    from pydantic import BaseModel

    router = APIRouter()
    swipe_limiter = _limits.SlidingWindowLimiter(int(os.getenv("DATING_SWIPE_RATE_PER_MINUTE", "60")), 60)
    feed_limiter = _limits.SlidingWindowLimiter(60, 60)
    photo_limiter = _limits.SlidingWindowLimiter(int(os.getenv("DATING_PHOTO_RATE_PER_HOUR", "12")), 3600)
    profile_limiter = _limits.SlidingWindowLimiter(30, 3600)
    report_limiter = _limits.SlidingWindowLimiter(int(os.getenv("DATING_REPORT_RATE_PER_DAY", "10")), 86400)

    class ProfileIn(BaseModel):
        display_name: str = ""
        birth_date: str = ""
        gender: str = ""
        looking_for: str = ""
        province: str = ""
        municipality: str = ""
        bio: str = ""
        interests: List[str] = []
        prefs: Optional[Dict[str, Any]] = None
        min_age: int = 18
        max_age: int = 99
        whatsapp: str = ""
        share_telegram: bool = False
        confirm_adult: bool = False
        accept_terms: bool = False

    class PhotoIn(BaseModel):
        image: str

    class SwipeIn(BaseModel):
        target: str
        action: str

    class TargetIn(BaseModel):
        target: str

    class ReportIn(BaseModel):
        target: str
        reason: str
        details: str = ""

    class MatchIn(BaseModel):
        match_id: int

    class VisibleIn(BaseModel):
        visible: bool

    class ReviewIn(BaseModel):
        action: str
        reason: str = ""

    class ResolveIn(BaseModel):
        action: str

    def throttle(limiter, key: str, message: str):
        allowed, retry = limiter.check(key)
        if not allowed:
            raise HTTPException(429, message, headers={"Retry-After": str(max(1, int(retry + 0.999)))})

    def run(fn):
        """Ejecuta ``fn(conexion)`` y traduce DatingError a HTTPException."""
        c = connect()
        try:
            return fn(c)
        except DatingError as exc:
            raise HTTPException(exc.status, exc.message)
        finally:
            c.close()

    def fire_and_forget(user_id: str, text: str):
        threading.Thread(target=notify, args=(user_id, text), daemon=True).start()

    @router.get("/api/dating/config")
    def dating_config():
        return {"provinces": list(PROVINCES), "genders": list(GENDERS), "looking_for": list(LOOKING_FOR),
                "min_age": MIN_AGE, "max_photos": MAX_PHOTOS, "max_bio": MAX_BIO,
                "free_daily_likes": free_daily_likes, "report_reasons": list(REPORT_REASONS)}

    @router.post("/api/dating/me")
    def dating_me(request: Request):
        uid = current_user(request)
        data = run(lambda c: overview(c, uid, secret()))
        data["free_daily_likes"] = free_daily_likes
        return data

    @router.post("/api/dating/profile")
    def dating_save_profile(p: ProfileIn, request: Request):
        uid = current_user(request)
        throttle(profile_limiter, uid, "Demasiados cambios de perfil. Intenta más tarde.")

        def work(c):
            existing = get_profile(c, uid)
            if existing and existing["status"] == "suspended":
                raise DatingError("Tu perfil de Citas está suspendido. Contacta a soporte.", 403, "suspended")
            cleaned = clean_profile(p.model_dump() if hasattr(p, "model_dump") else p.dict(),
                                    _username_of(c, uid), existing=bool(existing),
                                    locked_birth_date=existing["birth_date"] if existing else None)
            upsert_profile(c, uid, cleaned)
            return overview(c, uid, secret())
        return run(work)

    @router.post("/api/dating/photos")
    def dating_add_photo(p: PhotoIn, request: Request):
        uid = current_user(request)
        throttle(photo_limiter, uid, "Demasiadas fotos subidas. Intenta más tarde.")

        def work(c):
            require_active_profile(c, uid)
            jpeg = process_photo(parse_image_data_url(p.image))
            return add_photo(c, uid, photos_dir(), jpeg)
        return run(work)

    @router.delete("/api/dating/photos/{photo_id}")
    def dating_delete_photo(photo_id: int, request: Request):
        uid = current_user(request)
        run(lambda c: delete_photo(c, uid, photos_dir(), photo_id))
        return {"success": True}

    @router.get("/api/dating/photo/{photo_id}")
    def dating_photo(photo_id: int, e: int = 0, s: str = ""):
        if not verify_photo_signature(secret(), photo_id, e, s):
            raise HTTPException(403, "Enlace de foto inválido o vencido")
        c = connect()
        try:
            row = c.execute("SELECT filename FROM dating_photos WHERE id=?", (photo_id,)).fetchone()
        finally:
            c.close()
        if not row:
            raise HTTPException(404, "Foto no encontrada")
        headers = {"Cache-Control": "private, max-age=3000"}
        path = os.path.join(photos_dir(), os.path.basename(row["filename"]))
        if os.path.isfile(path):
            return FileResponse(path, media_type="image/jpeg", headers=headers)
        data = _storage.get(row["filename"])  # foto guardada en Cloudflare R2
        if data is None:
            raise HTTPException(404, "Foto no encontrada")
        return Response(content=data, media_type="image/jpeg", headers=headers)

    @router.post("/api/dating/feed")
    def dating_feed(request: Request):
        uid = current_user(request)
        throttle(feed_limiter, uid, "Demasiadas solicitudes. Espera un momento.")
        premium = is_premium(uid)

        def work(c):
            profiles = candidate_feed(c, uid, secret())
            eff_limit = effective_daily_limit(c, uid, free_daily_likes)
            bonus = share_earn_today(c, uid)
            return {
                "profiles":    profiles,
                "premium":     premium,
                "likes_left":  _likes_left(c, uid, eff_limit, premium),
                "share_earn":  {
                    "bonus_today":    bonus,
                    "base_limit":     free_daily_likes,
                    "effective_limit": eff_limit,
                    "already_earned": bonus > 0,
                },
            }
        return run(work)

    @router.post("/api/dating/share-earn")
    def dating_share_earn(request: Request):
        """El cliente llama a este endpoint después de que el usuario comparte su estado.
        Registra el bonus del día (idempotente) y devuelve los likes restantes actualizados.
        """
        uid = current_user(request)

        def work(c):
            result = grant_share_earn(c, uid)
            eff_limit = effective_daily_limit(c, uid, free_daily_likes)
            result["likes_left"] = _likes_left(c, uid, eff_limit, is_premium(uid))
            result["effective_limit"] = eff_limit
            return result
        return run(work)

    @router.post("/api/dating/swipe")
    def dating_swipe(p: SwipeIn, request: Request):
        uid = current_user(request)
        throttle(swipe_limiter, uid, "Vas muy rápido. Espera un momento.")
        premium = is_premium(uid)

        def work(c):
            result = record_swipe(c, uid, p.target, p.action, free_daily_likes, premium)
            if result.get("matched"):
                other = c.execute("SELECT * FROM dating_profiles WHERE public_id=?", (result["match_public_id"],)).fetchone()
                result["match"] = card(c, other, secret())
                result["match"]["contacts"] = contact_links(other, _username_of(c, other["user_id"]))
            return result
        result = run(work)
        for user_id in result.pop("notify", []):
            fire_and_forget(user_id, "💜 <b>¡Tienes un nuevo match en LiggaCuba Citas!</b>\nAbre la Mini App, entra en Matches y escríbele por Telegram o WhatsApp.")
        result.pop("match_public_id", None)
        return result

    @router.post("/api/dating/undo")
    def dating_undo(request: Request):
        uid = current_user(request)
        if not is_premium(uid):
            raise HTTPException(402, "Deshacer es una función Premium")
        return run(lambda c: undo_last_swipe(c, uid, secret()))

    @router.post("/api/dating/likes")
    def dating_likes(request: Request):
        uid = current_user(request)
        premium = is_premium(uid)
        return run(lambda c: likes_received(c, uid, secret(), premium))

    @router.post("/api/dating/matches")
    def dating_matches(request: Request):
        uid = current_user(request)
        return {"matches": run(lambda c: list_matches(c, uid, secret()))}

    @router.post("/api/dating/unmatch")
    def dating_unmatch(p: MatchIn, request: Request):
        uid = current_user(request)
        run(lambda c: unmatch(c, uid, p.match_id))
        return {"success": True}

    @router.post("/api/dating/block")
    def dating_block(p: TargetIn, request: Request):
        uid = current_user(request)
        run(lambda c: block_user(c, uid, p.target))
        return {"success": True}

    @router.post("/api/dating/report")
    def dating_report(p: ReportIn, request: Request):
        uid = current_user(request)
        throttle(report_limiter, uid, "Has enviado demasiados reportes hoy.")
        return run(lambda c: report_user(c, uid, p.target, p.reason, p.details))

    @router.post("/api/dating/visibility")
    def dating_visibility(p: VisibleIn, request: Request):
        uid = current_user(request)
        run(lambda c: set_visibility(c, uid, p.visible))
        return {"success": True, "visible": p.visible}

    @router.post("/api/dating/delete")
    def dating_delete(request: Request):
        uid = current_user(request)
        run(lambda c: delete_dating_data(c, uid, photos_dir()))
        return {"success": True}

    # --- administración -------------------------------------------------
    @router.get("/api/admin/dating/overview")
    def admin_dating_overview(request: Request):
        admin(request, "dating")
        return run(lambda c: {"stats": admin_stats(c), "photos": admin_pending_photos(c, secret()),
                              "reports": admin_list_reports(c)})

    @router.post("/api/admin/dating/photos/{photo_id}/review")
    def admin_dating_review(photo_id: int, p: ReviewIn, request: Request):
        ident = admin(request, "dating")
        if p.action not in ("approve", "reject"):
            raise HTTPException(400, "Acción no válida")
        result = run(lambda c: admin_review_photo(c, photo_id, p.action == "approve", p.reason, ident["username"], photos_dir()))
        audit(ident["username"], "dating_photo_" + p.action, photo_id, {"user_id": result["user_id"]})
        if p.action == "approve":
            fire_and_forget(result["user_id"], "📸 <b>¡Tu foto fue aprobada!</b>\nYa aparece en tu perfil de LiggaCuba Citas.")
        else:
            fire_and_forget(result["user_id"], f"❌ <b>Tu foto fue rechazada.</b>\nMotivo: {p.reason or 'No cumple las normas de la comunidad'}. Sube una nueva foto.")
        return result

    @router.post("/api/admin/dating/reports/{report_id}/resolve")
    def admin_dating_resolve(report_id: int, p: ResolveIn, request: Request):
        ident = admin(request, "dating")
        result = run(lambda c: admin_resolve_report(c, report_id, p.action, ident["username"]))
        audit(ident["username"], "dating_report_" + p.action, report_id, {"user_id": result["user_id"]})
        if p.action == "suspend":
            fire_and_forget(result["user_id"],
                "⚠️ <b>Tu perfil de Citas ha sido suspendido.</b>\n\nRecibimos un reporte sobre tu actividad. Si crees que es un error, contacta a soporte.")
        return result

    @router.post("/api/admin/dating/profiles/{user_id}/restore")
    def admin_dating_restore(user_id: str, request: Request):
        ident = admin(request, "dating")
        run(lambda c: admin_restore_profile(c, user_id))
        audit(ident["username"], "dating_profile_restored", user_id, {})
        fire_and_forget(user_id,
            "✅ <b>Tu perfil de Citas ha sido reactivado.</b>\n\nYa puedes usar Citas con normalidad. ¡Mucho éxito! 💜")
        return {"success": True}

    return router
