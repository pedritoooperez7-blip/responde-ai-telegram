"""LiggaCuba Citas: descubrir perfiles, dar like, hacer match y chatear.

Decisiones de diseño
--------------------
* Hay un chat interno ligero (texto, sin imágenes ni stickers).
* Los usuarios free tienen un límite de FREE_MSG_LIMIT mensajes por match.
* Los contactos externos (Telegram/WhatsApp) siguen disponibles en el perfil.
* Los contactos solo se muestran en matches activos. Bloquear o deshacer un
  match los oculta de inmediato.
* Se exige ser mayor de 18 años (fecha de nacimiento) y aceptar los términos.
* Toda foto pasa por revisión manual (estado ``pending`` -> ``approved``) antes de
  que el perfil aparezca en el feed de otras personas.
* Los perfiles se identifican hacia fuera con un ``public_id`` opaco; el ID de
  Telegram nunca viaja a otros usuarios.
* [Fase 1-4] Los bots de citas (is_bot=1) tienen auto-like y no requieren
  cuenta Telegram real. El admin los gestiona desde el panel y puede responder
  desde el grupo de control de Telegram.

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

# ── Chat interno ──────────────────────────────────────────────────────────────
FREE_MSG_LIMIT = int(os.getenv("DATING_FREE_MSG_LIMIT", "8"))
MSG_RATE_PER_MINUTE = int(os.getenv("DATING_MSG_RATE_PER_MINUTE", "10"))

# ── Bots — siempre en el feed, sin reglas de proporción ───────────────────────
# DATING_BOTS_PER_FEED ya no oculta ni limita bots. Se conserva la variable
# solo para no romper entornos que todavía la definen.
BOT_FEED_MAX = int(os.getenv("DATING_BOTS_PER_FEED", "3"))

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

# Mensajes de error bilingües (es / en). DatingError usa la clave o el texto es.
ERROR_I18N = {
    "msg_limit": {
        "es": "Con el plan gratuito puedes enviar {n} mensajes por match. Mejora a Premium para escribir sin límite.",
        "en": "On the free plan you can send {n} messages per match. Upgrade to Premium for unlimited chat.",
    },
    "premium_only": {
        "es": "Función Premium.",
        "en": "Premium feature.",
    },
    "daily_limit": {
        "es": "Llegaste al límite diario de likes. Mejora a Premium para likes ilimitados.",
        "en": "You reached today's like limit. Upgrade to Premium for unlimited likes.",
    },
    "nothing_to_undo": {
        "es": "No hay nada que deshacer.",
        "en": "Nothing to undo.",
    },
    "already_matched": {
        "es": "Ese like ya generó un match y no se puede deshacer.",
        "en": "That like already matched and cannot be undone.",
    },
}

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
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  is_bot INTEGER NOT NULL DEFAULT 0,
  bot_notes TEXT NOT NULL DEFAULT ''
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
CREATE INDEX IF NOT EXISTS idx_dating_matches_status ON dating_matches(status,user_a,user_b);
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


CHAT_SCHEMA = """
CREATE TABLE IF NOT EXISTS dating_messages (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id   INTEGER NOT NULL,
  sender_id  TEXT    NOT NULL,
  body       TEXT    NOT NULL,
  created_at TEXT    NOT NULL,
  read_at    TEXT,
  is_system  INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (match_id) REFERENCES dating_matches(id)
);
CREATE INDEX IF NOT EXISTS idx_dmsg_match_created ON dating_messages(match_id, created_at);
CREATE INDEX IF NOT EXISTS idx_dmsg_match_id      ON dating_messages(match_id, id);
CREATE INDEX IF NOT EXISTS idx_dmsg_unread        ON dating_messages(match_id, sender_id, read_at);
CREATE TABLE IF NOT EXISTS dating_chat_presence (
  user_id    TEXT NOT NULL,
  match_id   INTEGER NOT NULL,
  seen_at    TEXT NOT NULL,
  PRIMARY KEY (user_id, match_id)
);
CREATE TABLE IF NOT EXISTS dating_mutes (
  user_id    TEXT NOT NULL,
  match_id   INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, match_id)
);
CREATE INDEX IF NOT EXISTS idx_dating_mutes_user ON dating_mutes(user_id);
CREATE TABLE IF NOT EXISTS dating_typing (
  user_id    TEXT NOT NULL,
  match_id   INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, match_id)
);
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
    if "is_bot" not in columns:
        connection.execute("ALTER TABLE dating_profiles ADD COLUMN is_bot INTEGER NOT NULL DEFAULT 0")
        connection.commit()
    if "bot_notes" not in columns:
        connection.execute("ALTER TABLE dating_profiles ADD COLUMN bot_notes TEXT NOT NULL DEFAULT ''")
        connection.commit()
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_dating_profiles_bot ON dating_profiles(is_bot,status,visible)"
    )
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
    # Schema del chat interno
    connection.executescript(CHAT_SCHEMA)


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
    today = today or _cuba_today()
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
    today = today or _cuba_today()
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


def get_match_profile_view(c: sqlite3.Connection, viewer_uid: str, target_public_id: str, secret: str) -> Dict[str, Any]:
    """Vista de solo lectura de un perfil con el que el viewer tiene match activo."""
    viewer_uid = str(viewer_uid)
    target = c.execute(
        "SELECT * FROM dating_profiles WHERE public_id=? AND status='active'",
        (str(target_public_id),)
    ).fetchone()
    if not target:
        raise DatingError("Perfil no encontrado.", 404, "not_found")
    tid = target["user_id"]
    # Debe existir un match activo entre ambos
    match = c.execute(
        "SELECT id FROM dating_matches WHERE status='active' AND "
        "((user_a=? AND user_b=?) OR (user_a=? AND user_b=?))",
        (viewer_uid, tid, tid, viewer_uid)
    ).fetchone()
    if not match:
        raise DatingError("Solo puedes ver el perfil de tus matches.", 403, "not_match")
    age = age_from(target["birth_date"]) if target["birth_date"] else None
    photos = _approved_photo_urls(c, tid, secret)
    interests = []
    try:
        parsed = json.loads(target["interests"] or "[]")
        if isinstance(parsed, list):
            interests = [str(x).strip() for x in parsed if str(x).strip()][:8]
    except Exception:
        pass
    return {
        "profile": {
            "public_id": target["public_id"],
            "display_name": target["display_name"],
            "age": age,
            "province": target["province"],
            "municipality": target["municipality"],
            "bio": target["bio"],
            "gender": target["gender"],
            "interests": interests,
        },
        "photos": photos,
        "match_id": match["id"],
    }


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


def reorder_photos(c: sqlite3.Connection, uid: str, photo_ids: List[int]) -> Dict[str, Any]:
    """Reordena las fotos del usuario. photo_ids = lista ordenada de ids propios."""
    uid = str(uid)
    if not photo_ids or not isinstance(photo_ids, list):
        raise DatingError("Lista de fotos requerida.")
    ids = [int(x) for x in photo_ids]
    if len(ids) != len(set(ids)):
        raise DatingError("IDs duplicados.")
    rows = c.execute(
        "SELECT id FROM dating_photos WHERE user_id=? AND status!='rejected' ORDER BY position",
        (uid,)
    ).fetchall()
    owned = {r["id"] for r in rows}
    if set(ids) != owned:
        raise DatingError("La lista debe incluir exactamente tus fotos actuales.")
    for pos, pid in enumerate(ids):
        c.execute("UPDATE dating_photos SET position=? WHERE id=? AND user_id=?", (pos, pid, uid))
    c.commit()
    return {"ok": True, "order": ids}


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


def _bot_portrait_url(row: sqlite3.Row) -> Optional[str]:
    """Retrato de respaldo si el bot no tiene foto. La tarjeta se ve como la de cualquier persona."""
    if not row["is_bot"]:
        return None
    kind = str(row["gender"] or "")
    if kind not in ("hombre", "mujer"):
        kind = "mujer"
    path = os.path.join(os.path.dirname(__file__), "bot_portraits", f"{kind}.jpg")
    if not os.path.isfile(path):
        return None
    return f"/api/dating/photo/portrait/{kind}"


def card(c: sqlite3.Connection, row: sqlite3.Row, secret: str, viewer_province: str = "",
         viewer_prefs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    photos = _approved_photo_urls(c, row["user_id"], secret)
    if not photos:
        fallback = _bot_portrait_url(row)
        if fallback:
            photos = [fallback]
    out = {
        "public_id": row["public_id"], "display_name": row["display_name"], "age": age_from(row["birth_date"]),
        "province": row["province"], "municipality": row["municipality"], "bio": row["bio"],
        "interests": json.loads(row["interests"] or "[]"),
        "photos": photos,
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

def _interleave_bots(candidates: List[Any], bot_max: int) -> List[Any]:
    """El bot ocupa su lugar como cualquier perfil, no va fijo de primero.

    Si por el límite de la página se quedaría fuera, entra en el último
    puesto. Así la prueba lo ve, pero no destaca como tarjeta especial.
    bot_max se ignora.
    """
    del bot_max
    return candidates


def candidate_feed(c: sqlite3.Connection, uid: str, secret: str, limit: int = 10, today: Optional[date] = None) -> List[Dict[str, Any]]:
    uid = str(uid)
    me = require_active_profile(c, uid)
    if not c.execute("SELECT 1 FROM dating_photos WHERE user_id=?", (uid,)).fetchone():
        raise DatingError("Sube al menos una foto para ver perfiles.", 409, "no_photo")
    my_age = age_from(me["birth_date"], today)
    # Los bots no pasan por género, edad, foto ni cupo. Las personas reales sí.
    base_where = (
        "FROM dating_profiles p WHERE p.user_id != ? AND p.status='active' AND p.visible=1 "
        "AND NOT EXISTS(SELECT 1 FROM dating_swipes s WHERE s.user_id=? AND s.target_id=p.user_id) "
        "AND NOT EXISTS(SELECT 1 FROM dating_blocks b WHERE (b.blocker_id=? AND b.blocked_id=p.user_id) "
        "OR (b.blocker_id=p.user_id AND b.blocked_id=?)) "
    )
    base_params: List[Any] = [uid, uid, uid, uid]
    gender_parts: List[str] = []
    gender_params: List[Any] = []
    wanted = LOOKING_TO_GENDER.get(me["looking_for"])
    if wanted:
        gender_parts.append("p.gender=?")
        gender_params.append(wanted)
    their_need = GENDER_TO_LOOKING.get(me["gender"])
    if their_need:
        gender_parts.append("p.looking_for IN ('todos',?)")
        gender_params.append(their_need)
    else:
        gender_parts.append("p.looking_for='todos'")
    real_sql = (
        "SELECT p.* " + base_where
        + "AND p.is_bot=0 AND EXISTS(SELECT 1 FROM dating_photos ph WHERE ph.user_id=p.user_id AND ph.status='approved') "
        + "AND " + " AND ".join(gender_parts) + " "
        + "ORDER BY (p.province=?) DESC, RANDOM() LIMIT 200"
    )
    bot_sql = "SELECT p.* " + base_where + "AND p.is_bot=1"
    my_prefs = load_prefs(me["prefs"])
    wants_near = my_prefs.get("distance") in ("neighborhood", "city")
    candidates = []
    rows = list(c.execute(bot_sql, base_params)) + list(
        c.execute(real_sql, base_params + gender_params + [me["province"]])
    )
    for row in rows:
        if not row["is_bot"]:
            their_age = age_from(row["birth_date"], today)
            if not (me["min_age"] <= their_age <= me["max_age"]):
                continue
            if not (row["min_age"] <= my_age <= row["max_age"]):
                continue
        score = compat_score(my_prefs, load_prefs(row["prefs"]))
        if wants_near and row["province"] == me["province"] and me["municipality"] and row["municipality"].lower() == me["municipality"].lower():
            score += 2
        # Bonus por actividad reciente (perfil actualizado en últimos 7 días)
        try:
            updated = datetime.fromisoformat(row["updated_at"] or row["created_at"] or "")
            if updated.tzinfo: updated = updated.replace(tzinfo=None)
            days_old = (_utcnow() - updated).total_seconds() / 86400
            if days_old <= 2: score += 3
            elif days_old <= 7: score += 1
        except Exception:
            pass
        # Personas reales antes que bots en el mismo score
        candidates.append((row["province"] == me["province"], score, 0 if row["is_bot"] else 1, row))
    # Orden: misma provincia → mayor score → persona real → (bots al final del grupo)
    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    ordered = _interleave_bots([(c[0], c[1], c[3]) for c in candidates], BOT_FEED_MAX)
    page = ordered[:limit]
    if not any(item[2]["is_bot"] for item in page):
        bots = [item for item in ordered if item[2]["is_bot"]]
        if bots:
            if len(page) < limit:
                page.append(bots[0])
            elif page:
                page[-1] = bots[0]
    return [card(c, row, secret, me["province"], my_prefs) for _same, _score, row in page]


def likes_today(c: sqlite3.Connection, uid: str, today: Optional[date] = None) -> int:
    """Likes dados hoy. El día cambia a medianoche de Cuba (igual que el resto de la app)."""
    start = _cuba_day_start_utc(today or _cuba_today())
    return c.execute(
        "SELECT COUNT(*) FROM dating_swipes WHERE user_id=? AND action IN ('like','superlike') AND created_at>=?", (str(uid), start)
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


def record_swipe(c: sqlite3.Connection, uid: str, target_public_id: str, action: str, daily_limit: int,
                 is_premium: bool, now: Optional[str] = None) -> Dict[str, Any]:
    uid = str(uid)
    if action not in ("like", "pass", "superlike"):
        raise DatingError("Acción no válida.", 400, "invalid_action")
    if action == "superlike" and not is_premium:
        raise DatingError("El Super Like es una función Premium.", 403, "premium_only")
    is_super = action == "superlike"
    # Para límites y match, superlike cuenta como like
    action_for_match = "like" if is_super else action
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
        if action in ("like", "superlike") and not is_premium and likes_today(c, uid) >= eff_limit:
            raise DatingError("Llegaste al límite diario de likes. Mejora a Premium para likes ilimitados.", 403, "daily_limit")
        c.execute("INSERT INTO dating_swipes(user_id,target_id,action,created_at) VALUES(?,?,?,?)", (uid, tid, action, now))
        # Bots hacen like automático de vuelta: like o superlike a un bot genera match inmediato
        if action_for_match == "like" and target["is_bot"]:
            if not c.execute("SELECT 1 FROM dating_swipes WHERE user_id=? AND target_id=?", (tid, uid)).fetchone():
                c.execute("INSERT INTO dating_swipes(user_id,target_id,action,created_at) VALUES(?,?,?,?)", (tid, uid, "like", now))
        matched = False
        match_row_id = None
        if action_for_match == "like" and c.execute(
                "SELECT 1 FROM dating_swipes WHERE user_id=? AND target_id=? AND action IN ('like','superlike')", (tid, uid)).fetchone():
            a, b = _pair(uid, tid)
            c.execute("INSERT OR IGNORE INTO dating_matches(user_a,user_b,status,created_at) VALUES(?,?,?,?)", (a, b, "active", now))
            c.execute("UPDATE dating_matches SET status='active',ended_at=NULL WHERE user_a=? AND user_b=? AND status!='active'", (a, b))
            row = c.execute("SELECT id FROM dating_matches WHERE user_a=? AND user_b=?", (a, b)).fetchone()
            match_row_id = int(row["id"]) if row else None
            # Mensaje de sistema inicial (solo si aún no hay mensajes en este match)
            if match_row_id is not None:
                existing = c.execute(
                    "SELECT 1 FROM dating_messages WHERE match_id=? LIMIT 1", (match_row_id,)
                ).fetchone()
                if not existing:
                    c.execute(
                        "INSERT INTO dating_messages(match_id, sender_id, body, created_at, is_system) VALUES(?,?,?,?,1)",
                        (match_row_id, "system", "¡Es un match!", now),
                    )
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
        if match_row_id is not None:
            result["match_id"] = match_row_id
        result["_target_is_bot"] = bool(target["is_bot"])
    return result


def _likes_left(c: sqlite3.Connection, uid: str, daily_limit: int, is_premium: bool) -> Optional[int]:
    return None if is_premium else max(0, daily_limit - likes_today(c, uid))


def undo_last_swipe(c: sqlite3.Connection, uid: str, secret: str, now: Optional[float] = None,
                    max_count: int = 1, is_premium: bool = False) -> Dict[str, Any]:
    """Deshace el/los últimos swipes si no generaron match.

    Free: 1 undo. Premium: hasta max_count (por defecto 5) dentro de la ventana.
    """
    uid = str(uid)
    require_active_profile(c, uid)
    limit = min(5, max(1, int(max_count))) if is_premium else 1
    rows = c.execute(
        "SELECT * FROM dating_swipes WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (uid, limit)
    ).fetchall()
    if not rows:
        raise DatingError("No hay nada que deshacer.", 404, "nothing_to_undo")

    undone = []
    for row in rows:
        try:
            age = (_utcnow() - datetime.fromisoformat(row["created_at"])).total_seconds()
        except Exception:
            age = UNDO_WINDOW_SECONDS + 1
        if age > UNDO_WINDOW_SECONDS:
            break
        a, b = _pair(uid, row["target_id"])
        if c.execute("SELECT 1 FROM dating_matches WHERE user_a=? AND user_b=?", (a, b)).fetchone():
            # No deshacer si generó match
            if not undone:
                raise DatingError("Ese like ya generó un match y no se puede deshacer.", 409, "already_matched")
            break
        c.execute("DELETE FROM dating_swipes WHERE user_id=? AND target_id=?", (uid, row["target_id"]))
        target = c.execute("SELECT * FROM dating_profiles WHERE user_id=?", (row["target_id"],)).fetchone()
        if target:
            undone.append(card(c, target, secret))
        if not is_premium:
            break

    if not undone:
        raise DatingError("No hay nada que deshacer dentro del tiempo permitido.", 404, "nothing_to_undo")
    c.commit()
    return {"undone": len(undone), "profiles": undone}



def likes_received(c: sqlite3.Connection, uid: str, secret: str, is_premium: bool) -> Dict[str, Any]:
    uid = str(uid)
    me = require_active_profile(c, uid)
    rows = c.execute(
        "SELECT p.* FROM dating_swipes s JOIN dating_profiles p ON p.user_id=s.user_id "
        "WHERE s.target_id=? AND s.action IN ('like','superlike') AND p.status='active' AND p.visible=1 "
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
    """Borra el perfil, fotos, swipes, matches y bloqueos de la persona. Conserva reportes (seguridad).

    FIX C2: borra dating_messages antes que dating_matches para evitar
    huérfanos con FK activas.
    """
    uid = str(uid)
    files = [r["filename"] for r in c.execute("SELECT filename FROM dating_photos WHERE user_id=?", (uid,)).fetchall()]
    # 1. Obtener match_ids del usuario
    match_ids = [int(r["id"]) for r in c.execute(
        "SELECT id FROM dating_matches WHERE user_a=? OR user_b=?", (uid, uid)).fetchall()]
    c.execute("DELETE FROM dating_photos WHERE user_id=?", (uid,))
    # 2. Borrar mensajes antes de borrar los matches (FK)
    if match_ids:
        marks = ",".join("?" * len(match_ids))
        c.execute(f"DELETE FROM dating_messages WHERE match_id IN ({marks})", match_ids)
        c.execute(f"DELETE FROM dating_chat_presence WHERE match_id IN ({marks})", match_ids)
        c.execute(f"DELETE FROM dating_mutes WHERE match_id IN ({marks})", match_ids)
        c.execute(f"DELETE FROM dating_typing WHERE match_id IN ({marks})", match_ids)
    c.execute("DELETE FROM dating_mutes WHERE user_id=?", (uid,))
    c.execute("DELETE FROM dating_typing WHERE user_id=?", (uid,))
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
        "profiles": one("SELECT COUNT(*) FROM dating_profiles WHERE is_bot=0"),
        "active_profiles": one("SELECT COUNT(*) FROM dating_profiles WHERE status='active' AND is_bot=0"),
        "pending_photos": one("SELECT COUNT(*) FROM dating_photos WHERE status='pending'"),
        "open_reports": one("SELECT COUNT(*) FROM dating_reports WHERE status='open'"),
        "matches": one("SELECT COUNT(*) FROM dating_matches WHERE status='active'"),
        # Campos de bots (nuevos — no rompen admin.html existente)
        "bots": one("SELECT COUNT(*) FROM dating_profiles WHERE is_bot=1"),
        "active_bots": one("SELECT COUNT(*) FROM dating_profiles WHERE is_bot=1 AND status='active'"),
    }


# ---------------------------------------------------------------------------
# Bots de citas — funciones de administración (Fase 1-4)
# ---------------------------------------------------------------------------

_BOT_REQUIRED_FIELDS = ("display_name", "birth_date", "gender", "looking_for", "province")

# Valores válidos para el bot (el admin usa los mismos que el perfil de usuario)
_BOT_VALID_GENDERS = set(GENDERS)
_BOT_VALID_LOOKING = set(LOOKING_FOR)
_BOT_VALID_PROVINCES = set(PROVINCES)


def _validate_bot_data(data: Dict[str, Any]) -> None:
    """Valida los campos obligatorios y el formato del perfil de bot.

    FIX L1-L4: valida género, provincia, fecha de nacimiento y edad mínima 18.
    """
    for field in _BOT_REQUIRED_FIELDS:
        if not str(data.get(field, "") or "").strip():
            raise DatingError(f"El campo '{field}' es obligatorio.", 400, "missing_field")

    # Fecha de nacimiento válida y edad >= 18
    birth_str = str(data.get("birth_date", "") or "").strip()
    try:
        birth = date.fromisoformat(birth_str)
    except ValueError:
        raise DatingError("La fecha de nacimiento del bot no es válida (usa YYYY-MM-DD).", 400, "invalid_birth_date")
    age = age_from(birth.isoformat())
    if age < MIN_AGE:
        raise DatingError(f"El bot debe tener al menos {MIN_AGE} años (fecha de nacimiento demasiado reciente).", 400, "underage_bot")
    if age > MAX_AGE:
        raise DatingError("La fecha de nacimiento del bot no es válida.", 400, "invalid_birth_date")

    # Género válido (hombre / mujer / otro — igual que los usuarios reales)
    gender = str(data.get("gender", "") or "").strip().lower()
    if gender not in _BOT_VALID_GENDERS:
        raise DatingError(f"Género no válido. Usa: {', '.join(sorted(_BOT_VALID_GENDERS))}.", 400, "invalid_gender")

    # looking_for válido (hombres / mujeres / todos)
    looking = str(data.get("looking_for", "") or "").strip().lower()
    if looking not in _BOT_VALID_LOOKING:
        raise DatingError(f"looking_for no válido. Usa: {', '.join(sorted(_BOT_VALID_LOOKING))}.", 400, "invalid_looking_for")

    # Provincia válida (exactamente como aparece en PROVINCES)
    province = str(data.get("province", "") or "").strip()
    if province not in _BOT_VALID_PROVINCES:
        raise DatingError(f"Provincia no válida. Revisa los nombres exactos de PROVINCES.", 400, "invalid_province")

    # Rango de edad coherente
    try:
        min_age = int(data.get("min_age") or MIN_AGE)
        max_age = int(data.get("max_age") or MAX_AGE)
    except (TypeError, ValueError):
        raise DatingError("El rango de edad no es válido.", 400)
    if min_age > max_age:
        raise DatingError("La edad mínima no puede ser mayor que la máxima.", 400)


def _build_bot_portrait_prompt(data: Dict[str, Any]) -> str:
    """Construye un prompt de retrato fotorealista coherente con el perfil del bot."""
    display_name = str(data.get("display_name") or "").strip()
    birth_date = str(data.get("birth_date") or "").strip()
    gender = str(data.get("gender") or "").strip().lower()
    province = str(data.get("province") or "").strip()
    municipality = str(data.get("municipality") or "").strip()
    bio = str(data.get("bio") or "").strip()[:200]
    raw_interests = data.get("interests") or []
    interests = [str(i) for i in (raw_interests if isinstance(raw_interests, list) else []) if str(i).strip()][:6]
    try:
        age = age_from(birth_date) if birth_date else 25
    except Exception:
        age = 25
    sex = "woman" if gender == "mujer" else ("man" if gender == "hombre" else "person")
    loc = ", ".join(x for x in [municipality, province, "Cuba"] if x)
    interests_txt = ", ".join(interests) if interests else "everyday life"
    return (
        f"Photorealistic natural profile portrait photo of a Cuban {sex}, about {age} years old, "
        f"from {loc}. Soft neutral background, natural daylight, candid smartphone selfie style, "
        f"friendly expression, realistic skin texture, no text, no watermark, no logo. "
        f"Interests: {interests_txt}. "
        + (f"Personality vibe from bio: {bio}. " if bio else "")
        + f"Name context only (do not render text): {display_name}."
    )


def generate_bot_portrait(prompt: str) -> Optional[bytes]:
    """Genera un retrato con el proveedor de imágenes disponible. Devuelve JPEG bytes o None.

    Usa Gemini Imagen si hay GEMINI_API_KEY. Falla de forma controlada sin lanzar
    excepciones al llamador (devuelve None).
    """
    import urllib.error
    import urllib.request

    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        return None
    model = (os.getenv("GEMINI_IMAGE_MODEL") or "imagen-3.0-generate-002").strip()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict"
        f"?key={key}"
    )
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "1:1",
            "personGeneration": "allow_adult",
        },
    }
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        preds = data.get("predictions") or []
        if not preds:
            return None
        b64 = preds[0].get("bytesBase64Encoded") or preds[0].get("image", {}).get("bytesBase64Encoded")
        if not b64:
            return None
        raw = base64.b64decode(b64)
        # Normalizar a JPEG vía Pillow si está disponible
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(raw))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=88)
            return out.getvalue()
        except Exception:
            return raw if raw[:3] == b"\xff\xd8\xff" else None
    except Exception as exc:
        logger.warning("generate_bot_portrait failed: %s", exc)
        return None


def admin_create_bot(c: sqlite3.Connection, data: Dict[str, Any], now: Optional[str] = None) -> Dict[str, Any]:
    """Crea un perfil de bot de citas. No requiere cuenta de Telegram real.

    FIX L1-L4: llama a _validate_bot_data que ahora valida todos los campos.
    FIX L6: interests serializado como List[str].
    """
    _validate_bot_data(data)
    now = now or _now()
    bot_user_id = "bot_" + uuid.uuid4().hex[:20]
    public_id = uuid.uuid4().hex[:16]
    display_name = str(data["display_name"]).strip()
    birth_date = str(data["birth_date"]).strip()
    gender = str(data["gender"]).strip().lower()
    looking_for = str(data["looking_for"]).strip().lower()
    province = str(data["province"]).strip()
    municipality = str(data.get("municipality") or "").strip()
    bio = str(data.get("bio") or "").strip()[:MAX_BIO]
    # FIX L6: solo strings, nada anidado
    raw_interests = data.get("interests") or []
    interests = json.dumps(
        [str(i)[:20] for i in (raw_interests if isinstance(raw_interests, list) else []) if isinstance(i, str)][:MAX_INTERESTS],
        ensure_ascii=False,
    )
    whatsapp = str(data.get("whatsapp") or "").strip()
    share_telegram = 1 if data.get("share_telegram") else 0
    bot_notes = str(data.get("bot_notes") or "").strip()
    status = str(data.get("status") or "active")
    if status not in ("active", "inactive", "suspended"):
        status = "active"
    try:
        min_age = max(MIN_AGE, min(MAX_AGE, int(data.get("min_age") or MIN_AGE)))
        max_age = max(MIN_AGE, min(MAX_AGE, int(data.get("max_age") or MAX_AGE)))
    except (TypeError, ValueError):
        min_age, max_age = MIN_AGE, MAX_AGE
    c.execute(
        "INSERT INTO dating_profiles("
        "user_id, public_id, display_name, birth_date, gender, looking_for, province, municipality,"
        "bio, interests, min_age, max_age, whatsapp, share_telegram, prefs,"
        "accepted_terms_at, created_at, updated_at, is_bot, bot_notes, status, visible"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            bot_user_id, public_id, display_name, birth_date, gender, looking_for,
            province, municipality, bio, interests,
            min_age, max_age,
            whatsapp, share_telegram, "{}",
            now, now, now,
            1,
            bot_notes,
            status,
            1 if data.get("visible", True) else 0,
        ),
    )
    c.commit()
    row = c.execute("SELECT * FROM dating_profiles WHERE user_id=?", (bot_user_id,)).fetchone()
    return dict(row)


def admin_list_bots(c: sqlite3.Connection, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """Lista todos los perfiles marcados como bots."""
    rows = c.execute(
        "SELECT * FROM dating_profiles WHERE is_bot=1 ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    total = c.execute("SELECT COUNT(*) FROM dating_profiles WHERE is_bot=1").fetchone()[0]
    return {"bots": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


def admin_update_bot(c: sqlite3.Connection, user_id: str, data: Dict[str, Any], now: Optional[str] = None) -> Dict[str, Any]:
    """Actualiza un perfil de bot. Solo permite modificar bots (is_bot=1).

    FIX L4: nunca escribe None en columnas NOT NULL.
    FIX L5: compatible con pydantic v1/v2 (exclude_unset).
    """
    row = c.execute("SELECT * FROM dating_profiles WHERE user_id=? AND is_bot=1", (str(user_id),)).fetchone()
    if not row:
        raise DatingError("Bot no encontrado.", 404, "not_found")
    now = now or _now()
    allowed = {
        "display_name", "birth_date", "gender", "looking_for", "province", "municipality",
        "bio", "interests", "min_age", "max_age", "whatsapp", "share_telegram",
        "visible", "status", "bot_notes",
    }
    updates: Dict[str, Any] = {}
    for k, v in data.items():
        if k not in allowed or v is None:  # FIX L4: nunca escribir None
            continue
        if k == "interests":
            raw = v if isinstance(v, list) else []
            updates[k] = json.dumps([str(i)[:20] for i in raw if isinstance(i, str)][:MAX_INTERESTS], ensure_ascii=False)
        elif k in ("share_telegram", "visible"):
            updates[k] = 1 if v else 0
        elif k == "status":
            updates[k] = v if v in ("active", "inactive", "suspended") else row["status"]
        elif k == "gender":
            updates[k] = v if v in _BOT_VALID_GENDERS else row["gender"]
        elif k == "looking_for":
            updates[k] = v if v in _BOT_VALID_LOOKING else row["looking_for"]
        elif k == "province":
            updates[k] = v if v in _BOT_VALID_PROVINCES else row["province"]
        else:
            updates[k] = v
    if not updates:
        return dict(row)
    updates["updated_at"] = now
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [str(user_id)]
    c.execute(f"UPDATE dating_profiles SET {set_clause} WHERE user_id=?", values)
    c.commit()
    return dict(c.execute("SELECT * FROM dating_profiles WHERE user_id=?", (str(user_id),)).fetchone())


def admin_delete_bot(c: sqlite3.Connection, user_id: str, photos_dir: Optional[str] = None) -> Dict[str, Any]:
    """Elimina un bot y todos sus datos asociados de forma transaccional.

    FIX C1: borra dating_messages ANTES de dating_matches para no violar FK.
    El orden es: mensajes → presencia → matches → swipes → bloqueos → reportes
                 → fotos (archivos) → perfil.
    """
    uid = str(user_id)
    row = c.execute("SELECT * FROM dating_profiles WHERE user_id=? AND is_bot=1", (uid,)).fetchone()
    if not row:
        raise DatingError("Bot no encontrado.", 404, "not_found")

    # Recopilar IDs de matches y archivos de fotos ANTES de la transacción
    match_ids = [int(r["id"]) for r in c.execute(
        "SELECT id FROM dating_matches WHERE user_a=? OR user_b=?", (uid, uid)).fetchall()]
    photo_files = [r["filename"] for r in c.execute(
        "SELECT filename FROM dating_photos WHERE user_id=?", (uid,)).fetchall()]

    c.execute("BEGIN IMMEDIATE")
    try:
        # 1. Mensajes (FK apunta a dating_matches → borrar primero)
        if match_ids:
            marks = ",".join("?" * len(match_ids))
            msgs_deleted = c.execute(
                f"DELETE FROM dating_messages WHERE match_id IN ({marks})", match_ids
            ).rowcount
            c.execute(f"DELETE FROM dating_chat_presence WHERE match_id IN ({marks})", match_ids)
            c.execute(f"DELETE FROM dating_mutes WHERE match_id IN ({marks})", match_ids)
            c.execute(f"DELETE FROM dating_typing WHERE match_id IN ({marks})", match_ids)
        else:
            msgs_deleted = 0

        # 2. Matches
        matches_deleted = c.execute(
            "DELETE FROM dating_matches WHERE user_a=? OR user_b=?", (uid, uid)
        ).rowcount

        # 3. Swipes
        c.execute("DELETE FROM dating_swipes WHERE user_id=? OR target_id=?", (uid, uid))

        # 4. Bloqueos
        c.execute("DELETE FROM dating_blocks WHERE blocker_id=? OR blocked_id=?", (uid, uid))

        # 5. Reportes (el bot puede haber sido reportado)
        c.execute("DELETE FROM dating_reports WHERE reported_id=?", (uid,))

        # 6. Fotos (registro en BD)
        c.execute("DELETE FROM dating_photos WHERE user_id=?", (uid,))

        # 7. Perfil
        c.execute("DELETE FROM dating_profiles WHERE user_id=?", (uid,))

        c.commit()
    except Exception:
        c.rollback()
        raise

    # 8. Borrar archivos físicos (fuera de la transacción: fallo no-crítico)
    if photos_dir:
        for fname in photo_files:
            _remove_file(photos_dir, fname)

    return {
        "deleted": True,
        "user_id": uid,
        "matches_deleted": matches_deleted,
        "messages_deleted": msgs_deleted,
    }


def admin_add_bot_photo(
    c: sqlite3.Connection,
    user_id: str,
    photos_dir: str,
    jpeg: bytes,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Agrega una foto a un bot de citas y la aprueba automáticamente (sin revisión manual).

    Los bots son perfiles artificiales controlados por el admin; sus fotos no
    pasan por el flujo de moderación normal.
    """
    uid = str(user_id)
    row = c.execute(
        "SELECT * FROM dating_profiles WHERE user_id=? AND is_bot=1", (uid,)
    ).fetchone()
    if not row:
        raise DatingError("Bot no encontrado.", 404, "not_found")

    count = c.execute(
        "SELECT COUNT(*) FROM dating_photos WHERE user_id=? AND status!='rejected'",
        (uid,),
    ).fetchone()[0]
    if count >= MAX_PHOTOS:
        raise DatingError(f"El bot ya tiene el máximo de {MAX_PHOTOS} fotos.", 409, "photo_limit")

    position = c.execute(
        "SELECT COALESCE(MAX(position),-1)+1 FROM dating_photos WHERE user_id=?", (uid,)
    ).fetchone()[0]

    filename = uuid.uuid4().hex + ".jpg"
    if not _storage.put(filename, jpeg):
        os.makedirs(photos_dir, exist_ok=True)
        with open(os.path.join(photos_dir, filename), "wb") as handle:
            handle.write(jpeg)

    now = now or _now()
    cur = c.execute(
        "INSERT INTO dating_photos(user_id,filename,position,status,reviewed_at,reviewed_by,created_at) "
        "VALUES(?,?,?,'approved',?,?,?)",
        (uid, filename, position, now, "admin_bot_manager", now),
    )
    c.commit()
    return {"id": cur.lastrowid, "status": "approved", "user_id": uid}


def admin_delete_bot_photo(
    c: sqlite3.Connection,
    user_id: str,
    photo_id: int,
    photos_dir: str,
) -> Dict[str, Any]:
    """Elimina una foto de un bot. Solo funciona sobre bots (is_bot=1)."""
    uid = str(user_id)
    bot_row = c.execute(
        "SELECT 1 FROM dating_profiles WHERE user_id=? AND is_bot=1", (uid,)
    ).fetchone()
    if not bot_row:
        raise DatingError("Bot no encontrado.", 404, "not_found")

    photo_row = c.execute(
        "SELECT * FROM dating_photos WHERE id=? AND user_id=?",
        (int(photo_id), uid),
    ).fetchone()
    if not photo_row:
        raise DatingError("Foto no encontrada en este bot.", 404, "not_found")

    c.execute("DELETE FROM dating_photos WHERE id=?", (int(photo_id),))
    c.commit()
    _remove_file(photos_dir, photo_row["filename"])
    return {"deleted": True, "photo_id": photo_id}


def admin_list_bot_photos(
    c: sqlite3.Connection,
    user_id: str,
    secret: str,
) -> List[Dict[str, Any]]:
    """Lista todas las fotos de un bot con URLs firmadas."""
    uid = str(user_id)
    rows = c.execute(
        "SELECT * FROM dating_photos WHERE user_id=? ORDER BY position, id",
        (uid,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "status": r["status"],
            "position": r["position"],
            "url": photo_url(secret, r["id"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Chat interno — funciones de negocio
# ---------------------------------------------------------------------------

def _require_active_match(c: sqlite3.Connection, uid: str, match_id: int) -> sqlite3.Row:
    """Devuelve la fila del match si está activo y el usuario pertenece a él."""
    row = c.execute(
        "SELECT * FROM dating_matches WHERE id=? AND status='active' AND (user_a=? OR user_b=?)",
        (int(match_id), str(uid), str(uid))
    ).fetchone()
    if not row:
        raise DatingError("Chat no disponible.", 404, "match_not_found")
    return row


def count_sent_messages(c: sqlite3.Connection, match_id: int, sender_id: str) -> int:
    """Número de mensajes (no sistema) que el remitente ya envió en este match."""
    return c.execute(
        "SELECT COUNT(*) FROM dating_messages WHERE match_id=? AND sender_id=? AND is_system=0",
        (int(match_id), str(sender_id))
    ).fetchone()[0]


def get_messages(
    c: sqlite3.Connection,
    uid: str,
    match_id: int,
    after_id: int = 0,
    before_id: int = 0,
    limit: int = 40,
) -> Dict[str, Any]:
    """Devuelve mensajes del match.

    - after_id > 0: polling incremental (mensajes nuevos)
    - before_id > 0: historial hacia atrás (mensajes más antiguos)
    - ambos 0: últimos `limit` mensajes
    """
    _require_active_match(c, uid, match_id)
    touch_chat_presence(c, uid, match_id)
    safe_limit = max(1, min(100, int(limit or 40)))
    mid = int(match_id)

    if before_id and int(before_id) > 0:
        rows = c.execute(
            "SELECT * FROM dating_messages WHERE match_id=? AND id<? ORDER BY id DESC LIMIT ?",
            (mid, int(before_id), safe_limit)
        ).fetchall()
        rows = list(reversed(rows))
    elif after_id and int(after_id) > 0:
        rows = c.execute(
            "SELECT * FROM dating_messages WHERE match_id=? AND id>? ORDER BY id LIMIT ?",
            (mid, int(after_id), safe_limit)
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT * FROM dating_messages WHERE match_id=? ORDER BY id DESC LIMIT ?",
            (mid, safe_limit)
        ).fetchall()
        rows = list(reversed(rows))

    messages = [
        {
            "id":         r["id"],
            "sender_id":  r["sender_id"],
            "body":       r["body"],
            "created_at": r["created_at"],
            "read_at":    r["read_at"],
            "is_system":  bool(r["is_system"]),
        }
        for r in rows
    ]
    last_id = messages[-1]["id"] if messages else int(after_id or 0)
    first_id = messages[0]["id"] if messages else 0
    has_more = False
    if before_id and messages:
        has_more = bool(c.execute(
            "SELECT 1 FROM dating_messages WHERE match_id=? AND id<? LIMIT 1",
            (mid, first_id)
        ).fetchone())
    elif not after_id and messages:
        has_more = bool(c.execute(
            "SELECT 1 FROM dating_messages WHERE match_id=? AND id<? LIMIT 1",
            (mid, first_id)
        ).fetchone())

    # other user online?
    match_row = c.execute("SELECT user_a, user_b FROM dating_matches WHERE id=?", (mid,)).fetchone()
    other_online = False
    if match_row:
        other = match_row["user_b"] if str(match_row["user_a"]) == str(uid) else match_row["user_a"]
        other_online = is_chat_open(c, other, mid, window_seconds=25)

    sent = count_sent_messages(c, match_id, uid)
    return {
        "messages": messages,
        "last_id": last_id,
        "first_id": first_id,
        "has_more": has_more,
        "free_msg_limit": FREE_MSG_LIMIT,
        "messages_sent": sent,
        "muted": is_muted(c, uid, match_id),
        "other_typing": is_other_typing(c, uid, match_id),
        "other_online": other_online,
    }


def post_message(
    c: sqlite3.Connection,
    uid: str,
    match_id: int,
    body: str,
    free_msg_limit: int,
    is_premium_user: bool,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Envía un mensaje al match."""
    uid = str(uid)
    now = now or _now()

    body = str(body or "").strip()
    if not body:
        raise DatingError("El mensaje no puede estar vacío.")
    if len(body) > 1000:
        raise DatingError("El mensaje es demasiado largo (máximo 1000 caracteres).")
    if _LINK_RE.search(body):
        raise DatingError(
            "Los mensajes no pueden contener enlaces ni usuarios. "
            "Comparte tu contacto en tu perfil para que lo vean tus matches."
        )

    _require_active_match(c, uid, match_id)

    if not is_premium_user:
        sent = count_sent_messages(c, match_id, uid)
        if sent >= free_msg_limit:
            raise DatingError(
                f"Con el plan gratuito puedes enviar {free_msg_limit} mensajes por match. "
                "Mejora a Premium para escribir sin límite.",
                403, "msg_limit"
            )

    # Obtener el otro usuario del match (para notificar si no tiene el chat abierto)
    match_row = c.execute(
        "SELECT user_a, user_b FROM dating_matches WHERE id=?", (int(match_id),)
    ).fetchone()
    other_id = None
    if match_row:
        other_id = match_row["user_b"] if str(match_row["user_a"]) == uid else match_row["user_a"]

    cur = c.execute(
        "INSERT INTO dating_messages(match_id, sender_id, body, created_at, is_system) VALUES(?,?,?,?,0)",
        (int(match_id), uid, body, now)
    )
    c.commit()

    # Indicar si el receptor tiene el chat abierto (para que el router decida notificar)
    recipient_online = False
    if other_id:
        recipient_online = is_chat_open(c, other_id, match_id, window_seconds=20)

    return {
        "id":         cur.lastrowid,
        "sender_id":  uid,
        "body":       body,
        "created_at": now,
        "read_at":    None,
        "is_system":  False,
        "other_id":   other_id,
        "recipient_online": recipient_online,
        "match_id":   int(match_id),
    }


def mark_messages_read(c: sqlite3.Connection, uid: str, match_id: int) -> None:
    """Marca como leídos los mensajes del otro usuario en este match."""
    _require_active_match(c, uid, match_id)
    c.execute(
        "UPDATE dating_messages SET read_at=? WHERE match_id=? AND sender_id!=? AND read_at IS NULL AND is_system=0",
        (_now(), int(match_id), str(uid))
    )
    c.execute(
        "INSERT INTO dating_chat_presence(user_id, match_id, seen_at) VALUES(?,?,?) "
        "ON CONFLICT(user_id, match_id) DO UPDATE SET seen_at=excluded.seen_at",
        (str(uid), int(match_id), _now()),
    )
    c.commit()


def touch_chat_presence(c: sqlite3.Connection, uid: str, match_id: int) -> None:
    """Registra que el usuario tiene el chat abierto (polling / lectura)."""
    c.execute(
        "INSERT INTO dating_chat_presence(user_id, match_id, seen_at) VALUES(?,?,?) "
        "ON CONFLICT(user_id, match_id) DO UPDATE SET seen_at=excluded.seen_at",
        (str(uid), int(match_id), _now()),
    )
    c.commit()


def is_chat_open(c: sqlite3.Connection, uid: str, match_id: int, window_seconds: int = 15) -> bool:
    """True si el usuario hizo poll/read de este match en los últimos window_seconds."""
    row = c.execute(
        "SELECT seen_at FROM dating_chat_presence WHERE user_id=? AND match_id=?",
        (str(uid), int(match_id)),
    ).fetchone()
    if not row or not row["seen_at"]:
        return False
    try:
        seen = datetime.fromisoformat(row["seen_at"])
        if seen.tzinfo is not None:
            seen = seen.replace(tzinfo=None)
        return (_utcnow() - seen).total_seconds() <= window_seconds
    except Exception:
        return False


def is_muted(c: sqlite3.Connection, uid: str, match_id: int) -> bool:
    """True si el usuario silenció este match."""
    row = c.execute(
        "SELECT 1 FROM dating_mutes WHERE user_id=? AND match_id=?",
        (str(uid), int(match_id))
    ).fetchone()
    return bool(row)


def set_mute(c: sqlite3.Connection, uid: str, match_id: int, muted: bool, now: Optional[str] = None) -> Dict[str, Any]:
    """Silencia o desilencia un match. Solo el propio usuario."""
    _require_active_match(c, uid, match_id)
    now = now or _now()
    if muted:
        c.execute(
            "INSERT OR IGNORE INTO dating_mutes(user_id, match_id, created_at) VALUES(?,?,?)",
            (str(uid), int(match_id), now)
        )
    else:
        c.execute(
            "DELETE FROM dating_mutes WHERE user_id=? AND match_id=?",
            (str(uid), int(match_id))
        )
    c.commit()
    return {"match_id": int(match_id), "muted": muted}


def touch_typing(c: sqlite3.Connection, uid: str, match_id: int, now: Optional[str] = None) -> None:
    """Registra que el usuario está escribiendo en este match."""
    _require_active_match(c, uid, match_id)
    now = now or _now()
    c.execute(
        "INSERT INTO dating_typing(user_id, match_id, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(user_id, match_id) DO UPDATE SET updated_at=excluded.updated_at",
        (str(uid), int(match_id), now)
    )
    c.commit()


def is_other_typing(c: sqlite3.Connection, uid: str, match_id: int, window_seconds: int = 6) -> bool:
    """True si el otro usuario del match escribió (typing) en los últimos window_seconds."""
    row = c.execute(
        "SELECT user_a, user_b FROM dating_matches WHERE id=? AND status='active'",
        (int(match_id),)
    ).fetchone()
    if not row:
        return False
    other = row["user_b"] if str(row["user_a"]) == str(uid) else row["user_a"]
    trow = c.execute(
        "SELECT updated_at FROM dating_typing WHERE user_id=? AND match_id=?",
        (str(other), int(match_id))
    ).fetchone()
    if not trow or not trow["updated_at"]:
        return False
    try:
        updated = datetime.fromisoformat(trow["updated_at"])
        if updated.tzinfo is not None:
            updated = updated.replace(tzinfo=None)
        return (_utcnow() - updated).total_seconds() <= window_seconds
    except Exception:
        return False


def _enrich_matches_with_chat(c: sqlite3.Connection, uid: str, matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Añade last_message, unread_count y muted a cada match de la lista."""
    for m in matches:
        mid = m.get("match_id")
        if mid is None:
            m["last_message"] = None
            m["unread_count"] = 0
            m["muted"] = False
            continue
        last = c.execute(
            "SELECT * FROM dating_messages WHERE match_id=? ORDER BY id DESC LIMIT 1",
            (mid,)
        ).fetchone()
        if last:
            m["last_message"] = {
                "id":         last["id"],
                "sender_id":  last["sender_id"],
                "body":       last["body"],
                "created_at": last["created_at"],
                "is_system":  bool(last["is_system"]),
            }
        else:
            m["last_message"] = None
        muted = is_muted(c, uid, mid)
        m["muted"] = muted
        # Si está silenciado, no contar unread para el badge total
        if muted:
            m["unread_count"] = 0
        else:
            m["unread_count"] = c.execute(
                "SELECT COUNT(*) FROM dating_messages WHERE match_id=? AND sender_id!=? AND read_at IS NULL AND is_system=0",
                (mid, str(uid))
            ).fetchone()[0]
    return matches


# ---------------------------------------------------------------------------
# Chats de bots — funciones de administración (Fase 3)
# ---------------------------------------------------------------------------

def admin_bot_conversations(
    c: sqlite3.Connection,
    bot_user_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Lista los matches que involucran bots, con el último mensaje.

    FIX L13: u.user_id != b.user_id evita producto cartesiano en match bot↔bot.
    FIX L14: muestra TODOS los matches (no solo 'active') para que el panel no
             aparezca vacío cuando hay matches cerrados/unmatched con bots.
             Se añade status_filter ('active'|'unmatched'|'all') para filtrar.
    FIX L15: ordena por actividad reciente (último mensaje DESC) en lugar de
             fecha de match, para que los chats más activos aparezcan primero.
    FIX L16: soporte de búsqueda por nombre de bot o nombre de usuario real.
    """
    # Construir condición de estado
    if status_filter and status_filter != "all":
        status_cond = "AND m.status=? "
        status_params_val: List[Any] = [status_filter]
    else:
        # Mostrar todos los matches con bots (activos y cerrados)
        status_cond = ""
        status_params_val = []

    base_join = (
        "FROM dating_matches m "
        "JOIN dating_profiles b ON b.user_id IN (m.user_a, m.user_b) AND b.is_bot=1 "
        "JOIN dating_profiles u ON u.user_id IN (m.user_a, m.user_b) AND u.is_bot=0 "
        "   AND u.user_id != b.user_id "
        "LEFT JOIN dating_messages lm ON lm.id = ("
        "  SELECT MAX(id) FROM dating_messages WHERE match_id=m.id AND is_system=0"
        ") "
    )

    search_cond = ""
    search_params: List[Any] = []
    if search:
        search_cond = "AND (b.display_name LIKE ? OR u.display_name LIKE ?) "
        patt = f"%{search}%"
        search_params = [patt, patt]

    bot_cond = ""
    bot_params: List[Any] = []
    if bot_user_id:
        bot_cond = "AND b.user_id=? "
        bot_params = [str(bot_user_id)]

    where_clause = "WHERE 1=1 " + status_cond + bot_cond + search_cond

    all_params: List[Any] = status_params_val + bot_params + search_params

    base_sql = (
        "SELECT m.id AS match_id, m.user_a, m.user_b, m.created_at AS matched_at, "
        "       m.status AS match_status, m.ended_at, "
        "       b.user_id AS bot_id, b.display_name AS bot_name, b.public_id AS bot_public_id, "
        "       u.user_id AS real_id, u.display_name AS real_name, u.public_id AS real_public_id, "
        "       lm.id AS lm_id, lm.sender_id AS lm_sender, lm.body AS lm_body, lm.created_at AS lm_at "
        + base_join
        + where_clause
        + "ORDER BY COALESCE(lm.created_at, m.created_at) DESC LIMIT ? OFFSET ?"
    )

    rows = c.execute(base_sql, all_params + [int(limit), int(offset)]).fetchall()

    total_sql = "SELECT COUNT(*) " + base_join + where_clause
    total = c.execute(total_sql, all_params).fetchone()[0]

    conversations = []
    for r in rows:
        mid = r["match_id"]
        unread = c.execute(
            "SELECT COUNT(*) FROM dating_messages "
            "WHERE match_id=? AND sender_id=? AND read_at IS NULL AND is_system=0",
            (mid, r["real_id"]),
        ).fetchone()[0]
        msg_count = c.execute(
            "SELECT COUNT(*) FROM dating_messages WHERE match_id=? AND is_system=0",
            (mid,),
        ).fetchone()[0]
        conversations.append({
            "match_id":        mid,
            "match_status":    r["match_status"],
            "matched_at":      r["matched_at"],
            "ended_at":        r["ended_at"],
            "bot_id":          r["bot_id"],
            "bot_name":        r["bot_name"],
            "bot_public_id":   r["bot_public_id"],
            "real_id":         r["real_id"],
            "real_name":       r["real_name"],
            "real_public_id":  r["real_public_id"],
            "unread_from_user": unread,
            "message_count":   msg_count,
            "last_message": {
                "id":         r["lm_id"],
                "sender_id":  r["lm_sender"],
                "body":       r["lm_body"],
                "created_at": r["lm_at"],
            } if r["lm_id"] else None,
        })
    return {"conversations": conversations, "total": total, "limit": limit, "offset": offset}


def admin_bot_messages(
    c: sqlite3.Connection,
    match_id: int,
    after_id: int = 0,
    limit: int = 60,
) -> Dict[str, Any]:
    """Devuelve los mensajes de un match con bot para el panel de admin.

    FIX L11: funciona aunque el match esté cerrado (elimina el filtro status='active').
    """
    row = c.execute(
        "SELECT m.*, m.status AS match_status, "
        "       b.user_id AS bot_id, b.display_name AS bot_name, "
        "       u.user_id AS real_id, u.display_name AS real_name "
        "FROM dating_matches m "
        "JOIN dating_profiles b ON b.user_id IN (m.user_a, m.user_b) AND b.is_bot=1 "
        "JOIN dating_profiles u ON u.user_id IN (m.user_a, m.user_b) AND u.is_bot=0 "
        "   AND u.user_id != b.user_id "
        "WHERE m.id=?",
        (int(match_id),),
    ).fetchone()
    if not row:
        raise DatingError("Conversación de bot no encontrada.", 404, "not_found")

    messages_rows = c.execute(
        "SELECT * FROM dating_messages WHERE match_id=? AND id>? ORDER BY id LIMIT ?",
        (int(match_id), int(after_id), min(200, max(1, int(limit)))),
    ).fetchall()
    messages = [
        {
            "id":         m["id"],
            "sender_id":  m["sender_id"],
            "body":       m["body"],
            "created_at": m["created_at"],
            "read_at":    m["read_at"],
            "is_system":  bool(m["is_system"]),
        }
        for m in messages_rows
    ]
    last_id = messages[-1]["id"] if messages else int(after_id)
    return {
        "match_id":     int(match_id),
        "match_status": row["match_status"],
        "bot_id":       row["bot_id"],
        "bot_name":     row["bot_name"],
        "real_id":      row["real_id"],
        "real_name":    row["real_name"],
        "messages":     messages,
        "last_id":      last_id,
    }


def admin_bot_reply(
    c: sqlite3.Connection,
    match_id: int,
    body: str,
    actor: str,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """El admin envía un mensaje como si fuera el bot en el match indicado.

    FIX L12: operación envuelta en BEGIN IMMEDIATE para evitar escrituras
    intercaladas de dos admins simultáneos.
    """
    now = now or _now()
    body = str(body or "").strip()
    if not body:
        raise DatingError("El mensaje no puede estar vacío.")
    if len(body) > 2000:
        raise DatingError("El mensaje es demasiado largo (máximo 2000 caracteres).")

    c.execute("BEGIN IMMEDIATE")
    try:
        row = c.execute(
            "SELECT m.*, "
            "       b.user_id AS bot_id, b.display_name AS bot_name, "
            "       u.user_id AS real_id "
            "FROM dating_matches m "
            "JOIN dating_profiles b ON b.user_id IN (m.user_a, m.user_b) AND b.is_bot=1 "
            "JOIN dating_profiles u ON u.user_id IN (m.user_a, m.user_b) AND u.is_bot=0 "
            "   AND u.user_id != b.user_id "
            "WHERE m.id=? AND m.status='active'",
            (int(match_id),),
        ).fetchone()
        if not row:
            raise DatingError("Conversación de bot activa no encontrada.", 404, "not_found")

        bot_id = row["bot_id"]
        real_id = row["real_id"]

        # Marcar como leídos los mensajes del usuario real
        c.execute(
            "UPDATE dating_messages SET read_at=? "
            "WHERE match_id=? AND sender_id=? AND read_at IS NULL AND is_system=0",
            (now, int(match_id), real_id),
        )

        # Insertar el mensaje como el bot
        cur = c.execute(
            "INSERT INTO dating_messages(match_id, sender_id, body, created_at, is_system) VALUES(?,?,?,?,0)",
            (int(match_id), bot_id, body, now),
        )
        c.commit()
    except Exception:
        c.rollback()
        raise

    return {
        "id":         cur.lastrowid,
        "match_id":   int(match_id),
        "sender_id":  bot_id,
        "bot_name":   row["bot_name"],
        "real_id":    real_id,
        "body":       body,
        "created_at": now,
        "actor":      actor,
    }


# ---------------------------------------------------------------------------
# Rutas HTTP
# ---------------------------------------------------------------------------

def build_router(*, current_user: Callable, connect: Callable, is_premium: Callable, admin: Callable,
                 audit: Callable, notify: Callable, secret: Callable, photos_dir: Callable,
                 free_daily_likes: int = 20, free_msg_limit: int = FREE_MSG_LIMIT,
                 review: Optional[Callable] = None,
                 bot_control: Optional[Callable] = None):
    """Crea el APIRouter. ``main.py`` inyecta autenticación, base de datos y Telegram.

    ``bot_control(event, payload)`` — callable opcional inyectado por ``main.py``
    que reenvía eventos al grupo de control de Telegram de los bots de citas.
    Si es ``None`` los eventos se silencian sin error.

    Eventos emitidos:
      - ``"bot_match"``   → nuevo match entre usuario y bot
      - ``"bot_message"`` → el usuario escribió un mensaje a un bot
      - ``"bot_admin_reply"`` → el admin respondió desde el panel web
    """
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

    class ProfileViewIn(BaseModel):
        public_id: str

    class VisibleIn(BaseModel):
        visible: bool

    class ReviewIn(BaseModel):
        action: str
        reason: str = ""

    class ResolveIn(BaseModel):
        action: str

    # --- Bots ---------------------------------------------------------------
    class BotCreateIn(BaseModel):
        display_name: str
        birth_date: str
        gender: str
        looking_for: str
        province: str
        municipality: str = ""
        bio: str = ""
        interests: List[str] = []
        min_age: int = 18
        max_age: int = 99
        whatsapp: str = ""
        share_telegram: bool = False
        visible: bool = True
        status: str = "active"
        bot_notes: str = ""

    class BotUpdateIn(BaseModel):
        display_name: Optional[str] = None
        birth_date: Optional[str] = None
        gender: Optional[str] = None
        looking_for: Optional[str] = None
        province: Optional[str] = None
        municipality: Optional[str] = None
        bio: Optional[str] = None
        interests: Optional[List[str]] = None
        min_age: Optional[int] = None
        max_age: Optional[int] = None
        whatsapp: Optional[str] = None
        share_telegram: Optional[bool] = None
        visible: Optional[bool] = None
        status: Optional[str] = None
        bot_notes: Optional[str] = None

    class BotReplyIn(BaseModel):
        match_id: int
        body: str
        actor: Optional[str] = None

    def _model_dump(model, exclude_unset: bool = False) -> Dict[str, Any]:
        """Compatibilidad pydantic v1 / v2."""
        if hasattr(model, "model_dump"):
            return model.model_dump(exclude_unset=exclude_unset)
        return model.dict(exclude_unset=exclude_unset)

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
        # No notificar a bots (no tienen Telegram real)
        if str(user_id).startswith("bot_"):
            return
        threading.Thread(target=notify, args=(user_id, text), daemon=True).start()

    def fire_review(kind: str, payload: Dict[str, Any]):
        """Avisa al grupo de revisión sin bloquear la respuesta al usuario."""
        if not review:
            return
        def _run():
            try:
                review(kind, payload)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def fire_bot_control(event: str, payload: Dict[str, Any]):
        """Reenvía un evento al grupo de control de bots (BOTS_CONTROL_GROUP_ID)."""
        if not bot_control:
            return
        def _run():
            try:
                bot_control(event, payload)
            except Exception as exc:
                logger.debug("fire_bot_control error: %s", exc)
        threading.Thread(target=_run, daemon=True).start()

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
            cleaned = clean_profile(_model_dump(p),
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
            result = add_photo(c, uid, photos_dir(), jpeg)
            result["user_id"] = uid
            return result
        out = run(work)
        fire_and_forget(uid, "📸 <b>Tu foto está en revisión.</b>\nLa revisaremos en breve y te avisaremos cuando esté publicada.")
        fire_review("photo", out)
        return out

    
    class ReorderIn(BaseModel):
        photo_ids: List[int] = []

    @router.post("/api/dating/photos/reorder")
    def dating_photos_reorder(p: ReorderIn, request: Request):
        """Reordena fotos. Body: { photo_ids: [id1, id2, ...] }"""
        uid = current_user(request)
        return run(lambda c: reorder_photos(c, uid, list(p.photo_ids)))

    @router.delete("/api/dating/photos/{photo_id}")
    def dating_delete_photo(photo_id: int, request: Request):
        uid = current_user(request)
        run(lambda c: delete_photo(c, uid, photos_dir(), photo_id))
        return {"success": True}

    @router.get("/api/dating/photo/portrait/{kind}")
    def dating_bot_portrait(kind: str):
        if kind not in ("hombre", "mujer"):
            raise HTTPException(404, "Foto no encontrada")
        path = os.path.join(os.path.dirname(__file__), "bot_portraits", f"{kind}.jpg")
        if not os.path.isfile(path):
            raise HTTPException(404, "Foto no encontrada")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})

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
        data = _storage.get(row["filename"])
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
            target_is_bot = result.pop("_target_is_bot", False)
            if result.get("matched"):
                other = c.execute("SELECT * FROM dating_profiles WHERE public_id=?", (result["match_public_id"],)).fetchone()
                result["match"] = card(c, other, secret())
                result["match"]["contacts"] = contact_links(other, _username_of(c, other["user_id"]))
                if result.get("match_id") is not None:
                    result["match"]["match_id"] = result["match_id"]
            return result, target_is_bot
        result, target_is_bot = run(work)
        match_id_for_link = result.get("match_id")

        # Notificaciones de match
        for user_id in result.pop("notify", []):
            if str(user_id).startswith("bot_"):
                continue  # los bots no tienen Telegram
            if target_is_bot and str(user_id) != uid:
                # No notificar al bot (ya es bot_)
                continue
            link_hint = ""
            if match_id_for_link is not None:
                link_hint = f"\nAbre la Mini App (startapp=chat_{match_id_for_link}) para chatear."
            else:
                link_hint = "\nAbre la Mini App, entra en Matches y escríbele."
            fire_and_forget(
                user_id,
                "💜 <b>¡Tienes un nuevo match en LiggaCuba Citas!</b>" + link_hint,
            )

        # Notificar al grupo de control si fue match con bot
        if result.get("matched") and target_is_bot and match_id_for_link:
            def _notify_bot_match(mid=match_id_for_link, u=uid):
                try:
                    c2 = connect()
                    try:
                        row = c2.execute(
                            "SELECT b.user_id AS bot_id, b.display_name AS bot_name, "
                            "       u2.display_name AS real_name "
                            "FROM dating_matches m "
                            "JOIN dating_profiles b ON b.user_id IN (m.user_a, m.user_b) AND b.is_bot=1 "
                            "JOIN dating_profiles u2 ON u2.user_id IN (m.user_a, m.user_b) AND u2.is_bot=0 "
                            "   AND u2.user_id != b.user_id "
                            "WHERE m.id=?",
                            (mid,),
                        ).fetchone()
                        if row:
                            fire_bot_control("bot_match", {
                                "match_id":  mid,
                                "bot_id":    row["bot_id"],
                                "bot_name":  row["bot_name"],
                                "real_id":   u,
                                "real_name": row["real_name"],
                            })
                    finally:
                        c2.close()
                except Exception as exc:
                    logger.debug("_notify_bot_match error: %s", exc)
            threading.Thread(target=_notify_bot_match, daemon=True).start()

        result.pop("match_public_id", None)
        return result

    @router.post("/api/dating/undo")
    def dating_undo(request: Request, p: dict = None):
        uid = current_user(request)
        premium = is_premium(uid)
        if not premium:
            raise HTTPException(402, detail="Undo is a Premium feature / Deshacer es una función Premium")
        count = int((p or {}).get("count") or 1)
        return run(lambda c: undo_last_swipe(c, uid, secret(), max_count=count, is_premium=premium))

    @router.post("/api/dating/likes")
    def dating_likes(request: Request):
        uid = current_user(request)
        premium = is_premium(uid)
        return run(lambda c: likes_received(c, uid, secret(), premium))

    
    @router.post("/api/dating/profile-view")
    def dating_profile_view(p: ProfileViewIn, request: Request):
        """Vista de solo lectura del perfil de un match (para el botón Ver perfil del chat)."""
        uid = current_user(request)
        public_id = str(p.public_id or "").strip()
        if not public_id:
            raise HTTPException(400, "public_id requerido.")
        return run(lambda c: get_match_profile_view(c, uid, public_id, secret()))

    @router.post("/api/dating/matches")
    def dating_matches(request: Request):
        uid = current_user(request)

        def work(c):
            raw = list_matches(c, uid, secret())
            enriched = _enrich_matches_with_chat(c, uid, raw)
            return {"matches": enriched}

        return run(work)

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
        result = run(lambda c: report_user(c, uid, p.target, p.reason, p.details))
        report_id = result.get("report_id") if isinstance(result, dict) else None
        if not report_id:
            c = connect()
            try:
                row_id = c.execute(
                    "SELECT id FROM dating_reports WHERE reporter_id=? AND status='open' ORDER BY id DESC LIMIT 1",
                    (uid,),
                ).fetchone()
            finally:
                c.close()
            report_id = row_id["id"] if row_id else None
        if report_id:
            payload = {"report_id": report_id, "reporter_id": uid, "reason": p.reason, "details": p.details}
            c = connect()
            try:
                row = c.execute(
                    "SELECT p.public_id, p.display_name FROM dating_profiles p WHERE p.public_id=? OR p.user_id=?",
                    (p.target, p.target),
                ).fetchone()
            finally:
                c.close()
            if row:
                payload["reported_name"] = row["display_name"]
                payload["reported_id"] = row["public_id"]
            fire_review("report", payload)
        return result

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

    # --- bots de citas (Fase 1-4) -------------------------------------------

    @router.post("/api/admin/dating/bots")
    def admin_bots_create(p: BotCreateIn, request: Request):
        """Crea un nuevo perfil de bot de citas.
        Tras crear, intenta generar un retrato IA y asociarlo como foto approved.
        Si la IA falla, el bot queda con el fallback de bot_portraits.
        """
        ident = admin(request, "dating")
        data = _model_dump(p)
        result = run(lambda c: admin_create_bot(c, data))
        # Foto IA solo al crear (no en edición). Fallo controlado → fallback actual.
        try:
            prompt = _build_bot_portrait_prompt(data)
            jpeg = generate_bot_portrait(prompt)
            if jpeg:
                def _attach(c):
                    return admin_add_bot_photo(c, result["user_id"], photos_dir(), jpeg)
                photo = run(_attach)
                result["ai_photo_id"] = photo.get("id")
        except Exception as exc:
            logger.warning("AI portrait skipped for bot %s: %s", result.get("user_id"), exc)
        audit(ident["username"], "dating_bot_created", result["user_id"], {"display_name": result["display_name"]})
        return result

    @router.get("/api/admin/dating/bots")
    def admin_bots_list(request: Request, limit: int = 100, offset: int = 0):
        """Lista todos los perfiles de bots."""
        admin(request, "dating")
        return run(lambda c: admin_list_bots(c, limit=limit, offset=offset))

    @router.put("/api/admin/dating/bots/{user_id}")
    def admin_bots_update(user_id: str, p: BotUpdateIn, request: Request):
        """Actualiza los campos de un bot existente."""
        ident = admin(request, "dating")
        # FIX L5: exclude_unset=True para no sobreescribir con None campos no enviados
        data = _model_dump(p, exclude_unset=True)
        result = run(lambda c: admin_update_bot(c, user_id, data))
        audit(ident["username"], "dating_bot_updated", user_id, data)
        return result

    @router.delete("/api/admin/dating/bots/{user_id}")
    def admin_bots_delete(user_id: str, request: Request):
        """Elimina un bot y todos sus datos asociados (matches, mensajes, fotos)."""
        ident = admin(request, "dating")
        result = run(lambda c: admin_delete_bot(c, user_id, photos_dir()))
        audit(ident["username"], "dating_bot_deleted", user_id,
              {"matches_deleted": result.get("matches_deleted", 0),
               "messages_deleted": result.get("messages_deleted", 0)})
        return result

    # --- fotos de bots -------------------------------------------------------

    @router.get("/api/admin/dating/bots/{user_id}/photos")
    def admin_bots_photos_list(user_id: str, request: Request):
        """Lista las fotos de un bot con URLs firmadas."""
        admin(request, "dating")
        return {"photos": run(lambda c: admin_list_bot_photos(c, user_id, secret()))}

    @router.post("/api/admin/dating/bots/{user_id}/photos")
    def admin_bots_photos_add(user_id: str, p: PhotoIn, request: Request):
        """Sube y aprueba automáticamente una foto para un bot de citas.

        El cuerpo debe ser JSON con campo ``image`` en formato data-URL
        (``data:image/jpeg;base64,...``).
        """
        ident = admin(request, "dating")
        jpeg = process_photo(parse_image_data_url(p.image))
        result = run(lambda c: admin_add_bot_photo(c, user_id, photos_dir(), jpeg))
        audit(ident["username"], "dating_bot_photo_added", user_id, {"photo_id": result["id"]})
        return result

    @router.delete("/api/admin/dating/bots/{user_id}/photos/{photo_id}")
    def admin_bots_photos_delete(user_id: str, photo_id: int, request: Request):
        """Elimina una foto de un bot."""
        ident = admin(request, "dating")
        result = run(lambda c: admin_delete_bot_photo(c, user_id, photo_id, photos_dir()))
        audit(ident["username"], "dating_bot_photo_deleted", user_id, {"photo_id": photo_id})
        return result

    # --- chat interno -------------------------------------------------------
    msg_rate_limiter = _limits.SlidingWindowLimiter(
        int(os.getenv("DATING_MSG_RATE_PER_MINUTE", str(MSG_RATE_PER_MINUTE))), 60
    )

    class MessageIn(BaseModel):
        body: str = ""

    class MuteIn(BaseModel):
        muted: bool = True

    
    @router.get("/api/dating/matches/{match_id}/stream")
    async def dating_messages_stream(match_id: int, request: Request, after_id: int = 0):
        """Long-poll / stream ligero: espera hasta 25s por mensajes nuevos.
        Alternativa a WebSocket compatible con Railway/proxy sin sticky sessions.
        """
        import asyncio
        from fastapi.responses import StreamingResponse
        uid = current_user(request)

        async def event_gen():
            last = int(after_id or 0)
            deadline = time.time() + 25
            while time.time() < deadline:
                if await request.is_disconnected():
                    break
                def work(c):
                    return get_messages(c, uid, match_id, after_id=last, limit=30)
                try:
                    data = run(work)
                except Exception as exc:
                    yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"
                    break
                msgs = data.get("messages") or []
                if msgs:
                    last = data.get("last_id") or last
                    payload = json.dumps(data, ensure_ascii=False)
                    yield f"event: messages\ndata: {payload}\n\n"
                    break
                yield "event: ping\ndata: {}\n\n"
                await asyncio.sleep(2.5)
            yield "event: done\ndata: {}\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.get("/api/dating/matches/{match_id}/messages")
    def dating_messages_get(match_id: int, request: Request, after_id: int = 0, before_id: int = 0, limit: int = 40):
        uid = current_user(request)
        return run(lambda c: get_messages(c, uid, match_id, after_id=after_id, before_id=before_id, limit=limit))

    @router.post("/api/dating/matches/{match_id}/messages")
    def dating_messages_post(match_id: int, p: MessageIn, request: Request):
        uid = current_user(request)
        throttle(msg_rate_limiter, uid, "Vas muy rápido. Espera un momento.")
        premium_user = is_premium(uid)

        def work(c):
            msg = post_message(c, uid, match_id, p.body, free_msg_limit, premium_user)
            match_row = c.execute(
                "SELECT * FROM dating_matches WHERE id=?", (match_id,)
            ).fetchone()
            if not match_row:
                return {"message": msg}

            other_id = match_row["user_b"] if match_row["user_a"] == uid else match_row["user_a"]

            # Notificar al usuario real (si no tiene el chat abierto y no silenció este match)
            if not str(other_id).startswith("bot_"):
                if not is_muted(c, other_id, match_id) and not is_chat_open(c, other_id, match_id, window_seconds=15):
                    sender_row = c.execute(
                        "SELECT display_name FROM dating_profiles WHERE user_id=?", (uid,)
                    ).fetchone()
                    sender_name = sender_row["display_name"] if sender_row else "Alguien"
                    fire_and_forget(
                        other_id,
                        f"💬 <b>{sender_name} te envió un mensaje en LiggaCuba Citas.</b>\n"
                        f"Abre la Mini App para leer y responder (startapp=chat_{match_id}).",
                    )

            # Si el destinatario ES un bot → reenviar al grupo de control
            if str(other_id).startswith("bot_"):
                bot_row = c.execute(
                    "SELECT display_name FROM dating_profiles WHERE user_id=?", (other_id,)
                ).fetchone()
                sender_row = c.execute(
                    "SELECT display_name FROM dating_profiles WHERE user_id=?", (uid,)
                ).fetchone()
                control_payload = {
                    "match_id":    match_id,
                    "bot_id":      other_id,
                    "bot_name":    bot_row["display_name"] if bot_row else other_id,
                    "real_id":     uid,
                    "real_name":   sender_row["display_name"] if sender_row else uid,
                    "message_id":  msg["id"],
                    "body":        p.body,
                    "created_at":  msg["created_at"],
                }
                fire_bot_control("bot_message", control_payload)

            return {"message": msg}

        return run(work)

    
    @router.post("/api/dating/matches/{match_id}/mute")
    def dating_mute(match_id: int, p: MuteIn, request: Request):
        """Silenciar o desilenciar un match. Body: { muted: true|false }"""
        uid = current_user(request)
        return run(lambda c: set_mute(c, uid, match_id, p.muted))

    @router.post("/api/dating/matches/{match_id}/typing")
    def dating_typing(match_id: int, request: Request):
        """Registra que el usuario está escribiendo (llamado mientras teclea)."""
        uid = current_user(request)
        def work(c):
            touch_typing(c, uid, match_id)
            return {"ok": True}
        return run(work)

    @router.post("/api/dating/matches/{match_id}/read")
    def dating_messages_read(match_id: int, request: Request):
        uid = current_user(request)
        run(lambda c: mark_messages_read(c, uid, match_id))
        return {"success": True}

    # --- admin: chats de bots (Fase 3) -------------------------------------

    @router.get("/api/admin/dating/bots/conversations")
    def admin_bots_conversations(
        request: Request,
        bot_user_id: Optional[str] = None,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ):
        """Lista los matches que involucran bots (activos y cerrados).

        FIX L14: ahora devuelve todos los matches, no solo status='active'.
        Parámetros opcionales: bot_user_id, status_filter ('active'|'unmatched'|'all'), search.
        """
        admin(request, "dating")
        return run(lambda c: admin_bot_conversations(
            c,
            bot_user_id=bot_user_id,
            status_filter=status_filter,
            search=search,
            limit=limit,
            offset=offset,
        ))

    @router.get("/api/admin/dating/bots/conversations/{match_id}/messages")
    def admin_bots_messages(
        match_id: int,
        request: Request,
        after_id: int = 0,
        limit: int = 60,
    ):
        """Devuelve los mensajes de un match con bot (panel admin).
        FIX L11: funciona aunque el match esté cerrado.
        """
        admin(request, "dating")
        return run(lambda c: admin_bot_messages(c, match_id, after_id=after_id, limit=limit))

    @router.post("/api/admin/dating/bots/reply")
    def admin_bots_reply(p: BotReplyIn, request: Request):
        """El admin responde como si fuera el bot en un match."""
        ident = admin(request, "dating")
        raw_actor = (p.actor or "").replace("\r", " ").replace("\n", " ").strip()
        actor = raw_actor[:80] if raw_actor.startswith("tg:") and len(raw_actor) <= 80 else ident["username"]
        result = run(lambda c: admin_bot_reply(c, p.match_id, p.body, actor))
        audit(ident["username"], "dating_bot_reply", p.match_id, {"body_len": len(p.body)})

        # Notificar al usuario real vía Telegram (si no tiene el chat abierto)
        def _notify_user_and_group(res=result, actor=actor):
            try:
                c2 = connect()
                try:
                    real_id  = res["real_id"]
                    bot_name = res["bot_name"]
                    mid      = res["match_id"]
                    if not is_chat_open(c2, real_id, mid, window_seconds=30):
                        notify(
                            real_id,
                            f"💬 <b>{bot_name} te envió un mensaje en LiggaCuba Citas.</b>\n"
                            f"Abre la Mini App para leer y responder (startapp=chat_{mid}).",
                        )
                    # Registrar en el grupo de control
                    fire_bot_control("bot_admin_reply", {
                        "match_id":  mid,
                        "bot_id":    res["sender_id"],
                        "bot_name":  bot_name,
                        "real_id":   real_id,
                        "body":      res["body"],
                        "actor":     actor,
                    })
                finally:
                    c2.close()
            except Exception as exc:
                logger.debug("_notify_user_and_group error: %s", exc)
        threading.Thread(target=_notify_user_and_group, daemon=True).start()
        return result

    return router
