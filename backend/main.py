from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from PIL import Image
import base64, hashlib, hmac, io, json, logging, os, re, sqlite3, time, uuid
import pytesseract
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import parse_qs
try:
    from .ai_providers import generate_reply as _provider_generate_reply, ProviderError, validate_provider_configuration, get_provider_health, remaining_provider_budget, encrypt_provider_key, decrypt_provider_key, normalize_compatible_endpoint, test_custom_provider, encrypt_cache_payload, decrypt_cache_payload
    from .telegram_bot import TelegramBotError, handle_update, verify_webhook_secret, set_webhook, delete_webhook
except ImportError:  # Support running uvicorn with backend/ as the working directory.
    from ai_providers import generate_reply as _provider_generate_reply, ProviderError, validate_provider_configuration, get_provider_health, remaining_provider_budget, encrypt_provider_key, decrypt_provider_key, normalize_compatible_endpoint, test_custom_provider, encrypt_cache_payload, decrypt_cache_payload
    from telegram_bot import TelegramBotError, handle_update, verify_webhook_secret, set_webhook, delete_webhook
logger = logging.getLogger(__name__)

ai_generate_reply = _provider_generate_reply

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = FastAPI(title="LiggaCuba API", version="2.1")
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Key", "X-Atajo-Key"],
)

FREE_DAILY_LIMIT = 3
FREE_CHAT_MODES = {"gracioso", "coquetear", "enamorar"}
PREMIUM_CHAT_MODES = {"provocativo", "salvar"}
FREE_STORY_MODES = {"gracioso", "coquetear"}
PREMIUM_STORY_MODES = {"provocativo", "enamorar"}
DB_PATH = os.getenv("DB_PATH", os.path.join(ROOT, "liggacuba.db"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
ATAJO_KEY = os.getenv("ATAJO_KEY", "")
BANDEC_ACCOUNT = os.getenv("BANDEC_ACCOUNT", "")
BPA_ACCOUNT = os.getenv("BPA_ACCOUNT", "")
PAYMENT_PHONE = os.getenv("PAYMENT_PHONE", "")
SESSION_TTL = 86400
MAX_OCR_BYTES = 8 * 1024 * 1024
MAX_OCR_PIXELS = 24_000_000
OWNER_SESSION_TTL = 90 * 86400
ADMIN_SESSION_TTL = 7 * 86400
SESSION_SECRET = os.getenv("SESSION_SECRET", "")


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def session_token(uid: str) -> str:
    if not SESSION_SECRET or len(SESSION_SECRET) < 32:
        raise HTTPException(503, "SESSION_SECRET debe configurarse con al menos 32 caracteres")
    payload = _b64e(json.dumps({"uid": str(uid), "exp": int(time.time()) + SESSION_TTL}, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return payload + "." + sig


def verify_session(token: str) -> str:
    if not token or "." not in token:
        raise HTTPException(401, "Sesión requerida")
    payload, sig = token.rsplit(".", 1)
    if not SESSION_SECRET or len(SESSION_SECRET) < 32:
        raise HTTPException(503, "SESSION_SECRET debe configurarse con al menos 32 caracteres")
    expected = _b64e(hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(401, "Sesión inválida")
    try:
        data = json.loads(_b64d(payload).decode())
        if int(data.get("exp", 0)) < int(time.time()):
            raise HTTPException(401, "Sesión expirada")
        uid = str(data.get("uid", ""))
        if not uid:
            raise HTTPException(401, "Usuario inválido")
        return uid
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Sesión inválida")


def current_user(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Sesión requerida")
    return verify_session(auth[7:].strip())


def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def now(): return datetime.utcnow().isoformat()
def today(): return datetime.utcnow().date().isoformat()

def _utc_datetime(value=None):
    """Parse a timestamp as an aware UTC datetime; naive legacy values are treated as UTC."""
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def _validate_image_data_url(data_url: str) -> bytes:
    """Validate a supported base64 image URL and return its raw bytes without retaining it."""
    if not isinstance(data_url, str) or len(data_url) > 15_000_000:
        raise HTTPException(400, "La imagen supera el tamaño permitido o no es válida")
    match = re.fullmatch(r"data:image/(png|jpeg|jpg|webp|bmp|tiff);base64,([A-Za-z0-9+/]+={0,2})", data_url.strip(), re.I)
    if not match:
        raise HTTPException(400, "Formato de imagen inválido")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
        if not raw:
            raise HTTPException(400, "Imagen vacía")
        if len(raw) > MAX_OCR_BYTES:
            raise HTTPException(400, "La imagen supera el límite de 8 MB")
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.format not in {"PNG", "JPEG", "WEBP", "BMP", "TIFF"}:
                raise HTTPException(415, "Formato de imagen no admitido")
            width, height = probe.size
            if width < 1 or height < 1 or width * height > MAX_OCR_PIXELS:
                raise HTTPException(413, "La imagen tiene demasiados píxeles")
            probe.verify()
        return raw
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "Imagen inválida o dañada") from None


AI_PROMPT_CACHE_VERSION = "reply-context-v1"
AI_CACHE_TTL_HOURS = 6

def _ai_cache_key(text: str, image_data_url: str, mode: str, module: str) -> str | None:
    # Global reuse only for an exact input/configuration match. The original input is never stored.
    if len((os.getenv("AI_PROVIDER_ENCRYPTION_KEY") or "").strip()) < 32:
        return None
    image_digest = hashlib.sha256(image_data_url.encode("utf-8")).hexdigest() if image_data_url else ""
    config = {k: os.getenv(k, "") for k in ("GEMINI_MODEL", "GROQ_MODEL", "OPENROUTER_MODEL", "COHERE_MODEL", "AI_PRIORITY_GEMINI", "AI_PRIORITY_GROQ", "AI_PRIORITY_OPENROUTER", "AI_PRIORITY_COHERE")}
    config["credential_fingerprints"] = {k: hashlib.sha256(os.getenv(k, "").encode("utf-8")).hexdigest() for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "COHERE_API_KEY") if os.getenv(k)}
    c = db()
    try:
        rows = c.execute("SELECT provider_id,base_url,model,supports_text,supports_image,enabled,priority,updated_at FROM custom_ai_providers ORDER BY provider_id").fetchall()
        config["custom"] = [dict(r) for r in rows]
    except sqlite3.Error:
        config["custom"] = []
    finally:
        c.close()
    material = {"version": AI_PROMPT_CACHE_VERSION, "text": text, "image_sha256": image_digest, "mode": mode, "module": module, "provider_config": config}
    return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()

def _ai_cache_get(cache_key: str | None):
    if not cache_key:
        return None
    c = db()
    try:
        row = c.execute("SELECT encrypted_payload,expires_at FROM ai_response_cache WHERE cache_key=?", (cache_key,)).fetchone()
        if not row:
            return None
        if _utc_datetime(row["expires_at"]) <= _utc_datetime():
            c.execute("DELETE FROM ai_response_cache WHERE cache_key=?", (cache_key,)); c.commit()
            return None
        payload = json.loads(decrypt_cache_payload(row["encrypted_payload"]))
        if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
            c.execute("DELETE FROM ai_response_cache WHERE cache_key=?", (cache_key,)); c.commit()
            return None
        return payload
    except Exception:
        # A cache read or key rotation must never block live generation.
        try: c.execute("DELETE FROM ai_response_cache WHERE cache_key=?", (cache_key,)); c.commit()
        except Exception: pass
        return None
    finally:
        c.close()

def _ai_cache_put(cache_key: str | None, result: dict, recognized: str):
    if not cache_key or not isinstance(result, dict):
        return
    try:
        encrypted = encrypt_cache_payload(json.dumps({"result": result, "recognized": recognized}, ensure_ascii=False, separators=(",", ":")))
        created = datetime.now(timezone.utc)
        c = db()
        try:
            c.execute("INSERT INTO ai_response_cache(cache_key,encrypted_payload,prompt_version,created_at,expires_at) VALUES(?,?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET encrypted_payload=excluded.encrypted_payload,prompt_version=excluded.prompt_version,created_at=excluded.created_at,expires_at=excluded.expires_at",
                      (cache_key, encrypted, AI_PROMPT_CACHE_VERSION, created.isoformat(), (created + timedelta(hours=AI_CACHE_TTL_HOURS)).isoformat()))
            c.execute("DELETE FROM ai_response_cache WHERE expires_at < ?", (created.isoformat(),))
            c.commit()
        finally:
            c.close()
    except Exception:
        # Cache is an optimization, never a dependency for serving the answer.
        return


def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      user_id TEXT PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
      premium_until TEXT, payment_phone TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      usage_today INTEGER NOT NULL DEFAULT 0, last_reset_date TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS usage_logs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, used_at TEXT, module TEXT, mode TEXT, premium_used INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS payment_operations(
      operation_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, plan TEXT NOT NULL, language TEXT NOT NULL,
      status TEXT NOT NULL, amount TEXT NOT NULL, proof_text TEXT, proof_image TEXT,
      payment_method TEXT, payer_phone TEXT, destination_account TEXT,
      transaction_id TEXT, transfer_date TEXT, source_sms TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, verified_at TEXT, cancelled_at TEXT
    );
    CREATE TABLE IF NOT EXISTS saved_situations(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, ocr_text TEXT, reply TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS admin_users(
      username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, permissions TEXT NOT NULL,
      is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS admin_audit(
      id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL,
      target TEXT, details TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS admin_sessions(
      session_id TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at TEXT NOT NULL,
      created_at TEXT NOT NULL, revoked_at TEXT
    );
    CREATE TABLE IF NOT EXISTS analysis_attempts(
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL, module TEXT NOT NULL, mode TEXT NOT NULL,
      retry_used INTEGER NOT NULL DEFAULT 0, generation_count INTEGER NOT NULL DEFAULT 0,
      generation_in_progress INTEGER NOT NULL DEFAULT 0, generation_started_at TEXT,
      quota_charged INTEGER NOT NULL DEFAULT 1, quota_log_id INTEGER, retry_call_started INTEGER NOT NULL DEFAULT 0,
      generation_calls INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS ai_idempotency(
      user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
      status TEXT NOT NULL, result_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      PRIMARY KEY(user_id,idempotency_key)
    );
    CREATE TABLE IF NOT EXISTS ai_generation_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, analysis_id TEXT, provider TEXT, model TEXT,
      status TEXT NOT NULL, latency_ms INTEGER, error_category TEXT, error_code TEXT,
      quality_score REAL, retry_number INTEGER NOT NULL DEFAULT 0, module TEXT, mode TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS custom_ai_providers(
      provider_id TEXT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL, model TEXT NOT NULL,
      api_key_encrypted TEXT NOT NULL, supports_text INTEGER NOT NULL DEFAULT 1,
      supports_image INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
      priority INTEGER NOT NULL DEFAULT 50, last_test_status TEXT, last_test_at TEXT,
      last_error_category TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS ai_response_cache(
      cache_key TEXT PRIMARY KEY, encrypted_payload TEXT NOT NULL, prompt_version TEXT NOT NULL,
      created_at TEXT NOT NULL, expires_at TEXT NOT NULL
    );
    """)
    for sql in (
        "ALTER TABLE users ADD COLUMN payment_phone TEXT",
        "ALTER TABLE payment_operations ADD COLUMN payment_method TEXT",
        "ALTER TABLE payment_operations ADD COLUMN payer_phone TEXT",
        "ALTER TABLE payment_operations ADD COLUMN destination_account TEXT",
        "ALTER TABLE payment_operations ADD COLUMN transaction_id TEXT",
        "ALTER TABLE payment_operations ADD COLUMN transfer_date TEXT",
        "ALTER TABLE payment_operations ADD COLUMN source_sms TEXT",
    ):
        try:
            c.execute(sql)
        except sqlite3.OperationalError:
            pass
    # Safe additive migrations: SQLite ignores duplicate-column errors.
    for sql in (
        "ALTER TABLE analysis_attempts ADD COLUMN quota_log_id INTEGER",
        "ALTER TABLE analysis_attempts ADD COLUMN retry_call_started INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE analysis_attempts ADD COLUMN generation_calls INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE ai_generation_events ADD COLUMN error_code TEXT",
        "ALTER TABLE ai_generation_events ADD COLUMN quality_score REAL",
        "ALTER TABLE ai_generation_events ADD COLUMN retry_number INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE ai_generation_events ADD COLUMN module TEXT",
        "ALTER TABLE ai_generation_events ADD COLUMN mode TEXT",
    ):
        try:
            c.execute(sql)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_transaction ON payment_operations(transaction_id) WHERE transaction_id IS NOT NULL AND transaction_id != ''")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_source_sms ON payment_operations(source_sms) WHERE source_sms IS NOT NULL AND source_sms != ''")
    c.commit(); c.close()
init_db()


def user(user_id: str, extra: Optional[Dict[str, Any]] = None):
    uid = str(user_id or "guest-user")
    c = db(); row = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        t=now(); c.execute("INSERT INTO users(user_id,created_at,updated_at,last_reset_date) VALUES(?,?,?,?)", (uid,t,t,today()))
        c.commit(); row=c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    if extra:
        allowed={"username","first_name","last_name","premium_until","payment_phone"}; fields=[]; vals=[]
        for k,v in extra.items():
            if k in allowed and v is not None: fields.append(f"{k}=?"); vals.append(v)
        if fields:
            fields.append("updated_at=?"); vals.extend([now(),uid]); c.execute(f"UPDATE users SET {','.join(fields)} WHERE user_id=?", vals); c.commit()
            row=c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    c.close(); return dict(row)


def reset(uid):
    u=user(uid)
    if u["last_reset_date"] != today():
        c=db(); c.execute("UPDATE users SET usage_today=0,last_reset_date=?,updated_at=? WHERE user_id=?",(today(),now(),uid)); c.commit(); c.close()


def premium(uid):
    p=user(uid).get("premium_until")
    if not p: return False
    try:
        expiry = datetime.fromisoformat(p)
        if expiry.tzinfo is not None:
            return datetime.now(expiry.tzinfo) < expiry
        return datetime.utcnow() < expiry
    except (ValueError, TypeError): return False


def usage(uid):
    reset(uid); u=user(uid); used=int(u.get("usage_today") or 0); prem=premium(uid)
    return {"allowed": prem or used < FREE_DAILY_LIMIT, "remaining": 999 if prem else max(0,FREE_DAILY_LIMIT-used), "used_today":used, "premium":prem}


def consume(uid, module, mode):
    reset(uid)
    c = db()
    try:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT usage_today, premium_until FROM users WHERE user_id=?", (str(uid),)).fetchone()
        if not row:
            c.execute("INSERT INTO users(user_id,created_at,updated_at,last_reset_date) VALUES(?,?,?,?)", (str(uid), now(), now(), today()))
            used, until = 0, None
        else:
            used, until = int(row["usage_today"] or 0), row["premium_until"]
        is_premium = False
        if until:
            try:
                expiry = datetime.fromisoformat(until)
                is_premium = (datetime.now(expiry.tzinfo) < expiry) if expiry.tzinfo else (datetime.utcnow() < expiry)
            except (ValueError, TypeError):
                is_premium = False
        if not is_premium and used >= FREE_DAILY_LIMIT:
            c.rollback()
            return {"allowed": False, "remaining": 0, "premium": False}
        if not is_premium:
            c.execute("UPDATE users SET usage_today=usage_today+1,updated_at=? WHERE user_id=? AND usage_today<?", (now(), str(uid), FREE_DAILY_LIMIT))
            if c.total_changes < 1:
                c.rollback()
                return {"allowed": False, "remaining": 0, "premium": False}
            remaining = max(0, FREE_DAILY_LIMIT - used - 1)
        else:
            remaining = 999
        log_cursor = c.execute("INSERT INTO usage_logs(user_id,used_at,module,mode,premium_used) VALUES(?,?,?,?,?)", (str(uid), now(), module, mode, 1 if is_premium else 0))
        log_id = log_cursor.lastrowid
        c.commit()
        return {"allowed": True, "remaining": remaining, "premium": is_premium, "usage_log_id": log_id}
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


class TelegramAuth(BaseModel): initData:str=""; user_id:Optional[str]=None
class Usage(BaseModel): user_id:str
class Analyze(BaseModel): user_id:str; mode:str="coquetear"; module:str="chat"; image:str=""
class Generate(BaseModel): user_id:str; mode:str="coquetear"; module:str="chat"; text:str=""; analysis_id:Optional[str]=None; image:str=""; idempotency_key:Optional[str]=None
class Pending(BaseModel): user_id:str; plan:str="weekly"; language:str="es"; payment_method:str="BANDEC"
class PaymentPhone(BaseModel): phone:str
class AtajoPayment(BaseModel):
    metodo_pago:str
    telefono_origen:str=""
    cuenta_destino:str=""
    monto_recibido:float
    transaccion:str=""
    fecha:str=""
    fecha_ejecucion:str=""
    sms:str=""
class PaymentId(BaseModel): operation_id:str; user_id:str
class AdminLogin(BaseModel): username:str=""; password:str=""; master_key:str=""
class AIProviderUpsert(BaseModel):
    provider_id: str
    name: str
    base_url: str
    model: str
    api_key: str = ""
    supports_text: bool = True
    supports_image: bool = False
    enabled: bool = True
    priority: int = 50
class AdminCreate(BaseModel): username:str; password:str; permissions:list[str]=[]
class AdminStatus(BaseModel): username:str; is_active:bool=True
class PremiumChange(BaseModel): user_id:str; action:str; days:int=7
class PaymentReview(BaseModel): operation_id:str; action:str; reason:str=""
class Proof(BaseModel): operation_id:str; user_id:str; proof_text:str=""; proof_image:str=""
class SaveSituation(BaseModel): user_id:str; ocr_text:str=""; reply:str=""
class OCR(BaseModel): image:str


def parse_init(s):
    pairs = parse_qs(s, keep_blank_values=True, strict_parsing=True)
    if any(len(values) != 1 for values in pairs.values()):
        raise ValueError("Parámetros de Telegram duplicados")
    return {key: values[0] for key, values in pairs.items()}

def verify_init(s):
    if not s: raise ValueError("initData vacío")
    try:
        p = parse_init(s)
    except ValueError:
        raise ValueError("Parámetros de Telegram duplicados o inválidos") from None
    received = p.pop("hash", "")
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN no configurado")
    if not received: raise ValueError("Hash de Telegram ausente")
    try: auth_date = int(p.get("auth_date", "0"))
    except (ValueError, TypeError): raise ValueError("auth_date inválido")
    if auth_date > time.time() + 60: raise ValueError("auth_date en el futuro")
    if time.time() - auth_date > 86400: raise ValueError("Sesión de Telegram expirada")
    check = "\n".join(f"{k}={p[k]}" for k in sorted(p))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received): raise ValueError("Hash de Telegram inválido")
    try: u = json.loads(p.get("user", "{}"))
    except (json.JSONDecodeError, TypeError): raise ValueError("Datos de usuario Telegram inválidos") from None
    if not isinstance(u, dict): raise ValueError("Los datos de usuario deben ser un objeto")
    uid = u.get("id")
    if isinstance(uid, bool) or not isinstance(uid, (int, str)) or not str(uid).isdigit() or int(uid) <= 0:
        raise ValueError("Identificador de usuario Telegram inválido")
    return u


def admin_identity(request: Request):
    if not ADMIN_KEY:
        raise HTTPException(503, "ADMIN_KEY no configurado en Railway")
    key = request.headers.get("x-admin-key", "")
    if key and hmac.compare_digest(key, ADMIN_KEY):
        return {"username": "owner", "permissions": ["users", "premium", "payments", "stats", "admins", "settings", "audit", "ai_analytics"]}
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token or "." not in token:
        raise HTTPException(401, "No autorizado")
    payload, sig = token.rsplit(".", 1)
    expected = _b64e(hmac.new(ADMIN_KEY.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(401, "Sesión administrativa inválida")
    try:
        data = json.loads(_b64d(payload).decode())
        if int(data.get("exp", 0)) < int(time.time()):
            raise HTTPException(401, "Sesión administrativa expirada")
        username = str(data.get("username", ""))
        jti = str(data.get("jti", ""))
        if not username or not jti:
            raise HTTPException(401, "Sesión administrativa inválida")
        c = db()
        try:
            session = c.execute("SELECT * FROM admin_sessions WHERE session_id=? AND username=?", (jti, username)).fetchone()
            if not session or session["revoked_at"]:
                raise HTTPException(401, "Sesión administrativa revocada o inexistente")
            if int(session["expires_at"] or 0) < int(time.time()):
                raise HTTPException(401, "Sesión administrativa expirada")
            if data.get("role") == "owner" and username == "owner":
                return {"username": "owner", "permissions": ["users", "premium", "payments", "stats", "admins", "settings", "audit", "ai_analytics"]}
            row = c.execute("SELECT * FROM admin_users WHERE username=? AND is_active=1", (username,)).fetchone()
            if not row:
                raise HTTPException(401, "Administrador desactivado")
            return {"username": row["username"], "permissions": json.loads(row["permissions"])}
        finally:
            c.close()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Sesión administrativa inválida")

def admin(request:Request, permission: str = None):
    identity = admin_identity(request)
    if permission and permission not in identity["permissions"]:
        raise HTTPException(403, "No tienes permiso para esta acción")
    return identity

def audit(actor, action, target=None, details=None):
    c=db(); c.execute("INSERT INTO admin_audit(actor,action,target,details,created_at) VALUES(?,?,?,?,?)", (actor,action,str(target or ""),json.dumps(details or {},ensure_ascii=False),now())); c.commit(); c.close()


def amount(plan,lang):
    if lang=="en": return "8.99 USD" if plan=="weekly" else "29.99 USD"
    return "2500 CUP" if plan=="weekly" else "15500 CUP"


def _telegram_start_message(chat_id):
    """Compatibility wrapper: delegates to the real Telegram bot module."""
    from . import telegram_bot as _tb
    try:
        app_url = _tb.mini_app_url()
    except _tb.TelegramBotError:
        app_url = ""
    if not app_url:
        return {"chat_id": chat_id, "text": "¡Bienvenido a LiggaCuba! La Mini App estará disponible próximamente.", "reply_markup": {"inline_keyboard": [[{"text": "📢 Canal oficial", "url": _tb.official_channel()}]]}}
    payload = _tb.build_start_payload(chat_id, app_url, _tb.official_channel(), _tb.community_chat())
    return payload

def purge_expired_records():
    """Apply conservative retention: idempotency results 24h, AI events 30d, admin audit 90d."""
    current = datetime.now(timezone.utc)
    idem_cutoff = (current - timedelta(hours=24)).isoformat()
    event_cutoff = (current - timedelta(days=30)).isoformat()
    audit_cutoff = (current - timedelta(days=90)).isoformat()
    c = db()
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute("DELETE FROM ai_idempotency WHERE updated_at < ?", (idem_cutoff,))
        c.execute("DELETE FROM ai_generation_events WHERE created_at < ?", (event_cutoff,))
        c.execute("DELETE FROM admin_audit WHERE created_at < ?", (audit_cutoff,))
        c.execute("DELETE FROM ai_response_cache WHERE expires_at < ?", (current.isoformat(),))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

@app.get("/")
def root(): return FileResponse(os.path.join(ROOT,"index.html"))
@app.get("/admin.html")
def admin_page(): return FileResponse(os.path.join(ROOT,"admin.html"), media_type="text/html")

@app.post("/api/admin/telegram-access")
def admin_telegram_access(p: Usage, request: Request):
    uid = current_user(request)
    allowed = {x.strip() for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip()}
    return {"allowed": bool(uid in allowed), "url": "/admin.html" if uid in allowed else None}
@app.get("/app.js")
def js(): return FileResponse(os.path.join(ROOT,"app.js"),media_type="application/javascript")
@app.get("/style.css")
def css(): return FileResponse(os.path.join(ROOT,"style.css"),media_type="text/css")
@app.get("/liggacuba-logo.jpg")
def logo(): return FileResponse(os.path.join(ROOT,"liggacuba-logo.jpg"),media_type="image/jpeg")
@app.get("/privacy.html")
def privacy(): return FileResponse(os.path.join(ROOT,"privacy.html"),media_type="text/html")
@app.get("/terms.html")
def terms(): return FileResponse(os.path.join(ROOT,"terms.html"),media_type="text/html")
@app.get("/health")
def health(): return {"status":"ok","service":"LiggaCuba","version":"2.1"}


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Receive Telegram updates. Authenticated via X-Telegram-Bot-Api-Secret-Token."""
    try:
        secret_valid = verify_webhook_secret(request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""))
    except TelegramBotError:
        logger.error("Telegram webhook unavailable: secret configuration invalid")
        raise HTTPException(503, "Webhook de Telegram no configurado en el servidor")
    if not secret_valid:
        raise HTTPException(401, "Webhook no autorizado")
    body = await request.body()
    if len(body) > 256 * 1024:
        raise HTTPException(413, "Update demasiado grande")
    try:
        update = json.loads(body.decode("utf-8"))
        if not isinstance(update, dict):
            raise ValueError("update no es un objeto")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "Update inválido")
    try:
        outcome = handle_update(update)
        return {"ok": True, **outcome}
    except TelegramBotError as exc:
        # handle_update releases its claim on failure, so Telegram's retry can
        # attempt processing again. Never log tokens or request payloads.
        logger.warning(
            "Telegram webhook processing failed update_id=%s error_type=%s reason=%s",
            update.get("update_id"), type(exc).__name__, str(exc)[:240],
        )
        raise HTTPException(502, str(exc))


@app.post("/api/admin/telegram-webhook/setup")
def admin_setup_webhook(request: Request):
    """Register the production webhook URL. Requires the owner admin key."""
    admin(request, "settings")
    public_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not public_url.startswith("https://"):
        raise HTTPException(503, "PUBLIC_BASE_URL debe ser la URL HTTPS pública de este despliegue")
    try:
        result = set_webhook(
            public_url + "/webhook/telegram",
            os.getenv("TELEGRAM_WEBHOOK_SECRET", ""),
            ["message"],
        )
    except TelegramBotError as exc:
        raise HTTPException(502, str(exc))
    audit("owner", "telegram_webhook_setup", public_url, {})
    return {"success": True, "webhook_url": public_url + "/webhook/telegram", "telegram_result": result}


@app.post("/api/auth/telegram")
def auth_telegram(p:TelegramAuth):
    try:
        if p.initData:
            u=verify_init(p.initData)
        elif not BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN no configurado")
        else:
            u=None
    except ValueError as e:
        raise HTTPException(401,str(e))
    if not u or not u.get("id"): raise HTTPException(401,"Autenticación requerida")
    if p.user_id and str(p.user_id) != str(u.get("id")):
        raise HTTPException(401,"El usuario no coincide con Telegram")
    uid=str(u["id"]); user(uid,{"username":u.get("username"),"first_name":u.get("first_name"),"last_name":u.get("last_name")}); x=usage(uid)
    return {"success":True,"user_id":uid,"token":session_token(uid),**x}

@app.post("/api/usage")
def api_usage(p:Usage, request:Request):
    uid=current_user(request)
    return usage(uid)

@app.post("/api/analyze")
def analyze(p: Analyze, request: Request):
    uid = current_user(request)
    module = p.module if p.module in {"chat", "story"} else "chat"
    mode = (p.mode or "coquetear").lower().strip()
    free = FREE_CHAT_MODES if module == "chat" else FREE_STORY_MODES
    premset = PREMIUM_CHAT_MODES if module == "chat" else PREMIUM_STORY_MODES
    if mode not in free | premset:
        raise HTTPException(400, "Modo no válido")
    if mode in premset and not premium(uid):
        raise HTTPException(402, "Este modo requiere Premium")
    if str(p.user_id) != uid:
        raise HTTPException(403, "El usuario no coincide con la sesión")
    if p.image:
        _validate_image_data_url(p.image)
    reservation = consume(uid, module, mode)
    if not reservation["allowed"]:
        raise HTTPException(403, "Has alcanzado tus 3 análisis gratuitos de hoy")
    analysis_id = uuid.uuid4().hex
    c = db()
    try:
        c.execute("INSERT INTO analysis_attempts(id,user_id,module,mode,quota_charged,quota_log_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                  (analysis_id, uid, module, mode, 0 if reservation.get("premium") else 1, reservation.get("usage_log_id"), now(), now()))
        c.commit()
    except Exception:
        c.rollback()
        # Undo the quota reservation if attempt persistence failed.
        if not reservation.get("premium"):
            c.execute("UPDATE users SET usage_today=MAX(0,usage_today-1) WHERE user_id=?", (uid,))
            if reservation.get("usage_log_id"):
                c.execute("DELETE FROM usage_logs WHERE id=? AND user_id=?", (reservation["usage_log_id"], uid))
            c.commit()
        raise
    finally:
        c.close()
    public_reservation = {k: v for k, v in reservation.items() if k != "usage_log_id"}
    return {**public_reservation, "analysis_id": analysis_id, "module": module, "mode": mode}


def _generate_with_ocr_fallback(text: str, mode: str, module: str, image_data_url: str | None, timings: dict | None = None):
    timings = timings if timings is not None else {}
    recognized = ""
    if image_data_url:
        start = time.monotonic()
        try:
            result = ai_generate_reply(text, mode, module, image_data_url)
            timings["visual_generation_ms"] = int((time.monotonic()-start)*1000)
            timings.setdefault("ocr_ms", 0); timings.setdefault("alternative_generation_ms", 0)
            return result, recognized
        except ProviderError:
            timings["visual_generation_ms"] = int((time.monotonic()-start)*1000)
            raw = base64.b64decode(image_data_url.split(",",1)[1], validate=True)
            image = _decode_ocr_image(raw)
            ocr_start = time.monotonic()
            recognized = _ocr_text(image)
            timings["ocr_ms"] = int((time.monotonic()-ocr_start)*1000)
            if not recognized.strip() and not text.strip():
                raise HTTPException(422, "No se pudo reconocer texto en la imagen")
            combined = (text.strip() + "\n" + recognized.strip()).strip()
            alt_start = time.monotonic()
            result = ai_generate_reply(combined, mode, module, None)
            timings["alternative_generation_ms"] = int((time.monotonic()-alt_start)*1000)
            return result, recognized
    start = time.monotonic()
    result = ai_generate_reply(text, mode, module, None)
    timings["visual_generation_ms"] = int((time.monotonic()-start)*1000)
    timings.setdefault("ocr_ms", 0); timings.setdefault("alternative_generation_ms", 0)
    return result, recognized


@app.post("/api/generate-reply")
def generate(p: Generate, request: Request):
    uid = current_user(request)
    if str(p.user_id) != uid:
        raise HTTPException(403, "El usuario no coincide con la sesión")
    module = p.module if p.module in {"chat", "story"} else "chat"
    mode = (p.mode or "coquetear").lower().strip()
    free = FREE_CHAT_MODES if module == "chat" else FREE_STORY_MODES
    premium_modes = PREMIUM_CHAT_MODES if module == "chat" else PREMIUM_STORY_MODES
    if mode not in free | premium_modes:
        raise HTTPException(400, "Modo no válido")
    if mode in premium_modes and not premium(uid):
        raise HTTPException(402, "Este modo requiere Premium")
    text = re.sub(r"\s+", " ", (p.text or "")).strip()
    image = (p.image or "").strip()
    if image:
        _validate_image_data_url(image)
    if not text and not image: raise HTTPException(400, "Debes enviar texto o una imagen")
    aid = (p.analysis_id or "").strip()
    if not aid: raise HTTPException(400, "analysis_id es obligatorio; crea primero un análisis")
    payload_hash = hashlib.sha256(json.dumps({"text":text,"image_hash":hashlib.sha256(image.encode()).hexdigest() if image else "","mode":mode,"module":module,"analysis_id":aid}, sort_keys=True).encode()).hexdigest()
    key = (p.idempotency_key or uuid.uuid4().hex).strip()
    if len(key) > 128 or len(key) < 8: raise HTTPException(400, "idempotency_key debe tener entre 8 y 128 caracteres")
    c=db()
    try:
        c.execute("BEGIN IMMEDIATE")
        attempt=c.execute("SELECT * FROM analysis_attempts WHERE id=? AND user_id=?",(aid,uid)).fetchone()
        if not attempt: raise HTTPException(404,"Análisis no encontrado")
        if attempt["module"] != module or attempt["mode"] != mode: raise HTTPException(409,"El análisis no coincide con el módulo o modo")
        if int(attempt["generation_in_progress"] or 0) and attempt["generation_started_at"]:
            try:
                stale = (_utc_datetime() - _utc_datetime(attempt["generation_started_at"])).total_seconds() > 120
            except (ValueError, TypeError, OverflowError):
                stale = True
            if stale:
                c.execute("UPDATE analysis_attempts SET generation_in_progress=0,generation_started_at=NULL,updated_at=? WHERE id=?", (now(), aid))
                attempt = c.execute("SELECT * FROM analysis_attempts WHERE id=? AND user_id=?", (aid, uid)).fetchone()
        idem=c.execute("SELECT * FROM ai_idempotency WHERE user_id=? AND idempotency_key=?",(uid,key)).fetchone()
        if idem:
            if idem["payload_hash"] != payload_hash: raise HTTPException(409,"La clave de idempotencia ya se usó con otros datos")
            if idem["status"] == "completed" and idem["result_json"]: return json.loads(idem["result_json"])
            raise HTTPException(409,"Esta generación ya está en curso o falló; usa el flujo de reintento autorizado")
        if attempt["generation_in_progress"]: raise HTTPException(409,"Ya hay una generación en curso")
        generation_calls = int(attempt["generation_calls"] or 0)
        generation_count = int(attempt["generation_count"] or 0)
        retry_used = int(attempt["retry_used"] or 0)
        if generation_count > 0 and (retry_used != 1 or int(attempt["retry_call_started"] or 0) == 1): raise HTTPException(409,"Debes reservar un reintento disponible antes de generar otra respuesta")
        if generation_count == 0 and generation_calls >= 2:
            raise HTTPException(409, "El intento inicial y su reintento ya se utilizaron; crea un análisis nuevo")
        if retry_used == 1:
            c.execute("UPDATE analysis_attempts SET retry_call_started=1 WHERE id=?", (aid,))
        c.execute("UPDATE analysis_attempts SET generation_calls=generation_calls+1 WHERE id=?", (aid,))
        c.execute("INSERT INTO ai_idempotency(user_id,idempotency_key,payload_hash,status,created_at,updated_at) VALUES(?,?,?,'running',?,?)",(uid,key,payload_hash,now(),now()))
        c.execute("UPDATE analysis_attempts SET generation_in_progress=1,generation_started_at=?,updated_at=? WHERE id=?",(now(),now(),aid))
        c.commit()
    except HTTPException:
        c.rollback(); raise
    finally: c.close()
    timings={}; started=time.monotonic()
    cache_key = _ai_cache_key(text, image, mode, module)
    cache_hit = _ai_cache_get(cache_key)
    try:
        if cache_hit:
            result = cache_hit["result"]
            recognized = str(cache_hit.get("recognized") or "")
            timings["cache_hit"] = True
        else:
            result, recognized = _generate_with_ocr_fallback(text,mode,module,image or None,timings)
        if not isinstance(result,dict) or not result.get("reply") or not result.get("alternative"):
            raise HTTPException(502,"La IA no devolvió dos respuestas válidas")
        if not cache_hit:
            _ai_cache_put(cache_key, result, recognized)
        reply_text = str(result.get("reply", ""))
        alternative_text = str(result.get("alternative", ""))
        quality_score = max(1, min(5, round((min(len(reply_text), 160) + min(len(alternative_text), 160)) / 64)))
        result={"success":True,**result,"model":result.get("model") or validate_provider_configuration().get(result.get("provider", ""), {}).get("model", "unknown"),"ocr_text":recognized,"ocr_fallback":bool(recognized),"quality_score":quality_score,"cache_hit":bool(cache_hit),"timings_ms":{**timings,"total_backend_ms":int((time.monotonic()-started)*1000)}}
        c=db(); c.execute("BEGIN IMMEDIATE")
        attempt=c.execute("SELECT * FROM analysis_attempts WHERE id=? AND user_id=?",(aid,uid)).fetchone()
        # Charge quota only after successful generation; retry is never allowed to charge twice.
        if attempt and not int(attempt["quota_charged"] or 0) and not premium(uid):
            quota_user = c.execute("SELECT usage_today,last_reset_date FROM users WHERE user_id=?", (uid,)).fetchone()
            if not quota_user:
                raise HTTPException(404, "Usuario no encontrado")
            used = int(quota_user["usage_today"] or 0)
            if quota_user["last_reset_date"] != today():
                used = 0
                c.execute("UPDATE users SET usage_today=0,last_reset_date=?,updated_at=? WHERE user_id=?", (today(), now(), uid))
            if used >= FREE_DAILY_LIMIT:
                raise HTTPException(403, "Has alcanzado tus 3 análisis gratuitos de hoy")
            c.execute("UPDATE users SET usage_today=?,last_reset_date=?,updated_at=? WHERE user_id=?", (used + 1, today(), now(), uid))
            quota_cursor = c.execute("INSERT INTO usage_logs(user_id,used_at,module,mode,premium_used) VALUES(?,?,?,?,0)", (uid, now(), module, mode))
            c.execute("UPDATE analysis_attempts SET quota_charged=1,quota_log_id=? WHERE id=? AND user_id=?", (quota_cursor.lastrowid, aid, uid))
        c.execute("UPDATE analysis_attempts SET generation_count=generation_count+1,generation_in_progress=0,generation_started_at=NULL,updated_at=? WHERE id=?",(now(),aid))
        c.execute("UPDATE ai_idempotency SET status='completed',result_json=?,updated_at=? WHERE user_id=? AND idempotency_key=?",(json.dumps(result,ensure_ascii=False),now(),uid,key))
        c.commit(); c.close()
        # Monitoring is best-effort: metrics storage must not turn a successful AI reply into an error.
        try:
            telemetry = db()
            telemetry.execute("INSERT INTO ai_generation_events(user_id,analysis_id,provider,model,status,latency_ms,quality_score,retry_number,module,mode,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (uid, aid, result.get("provider"), result.get("model"), "success", result["timings_ms"]["total_backend_ms"], quality_score, int(attempt["retry_used"] or 0) if attempt else 0, module, mode, now()))
            telemetry.commit()
        except Exception:
            pass
        finally:
            try: telemetry.close()
            except Exception: pass
        return result
    except Exception as exc:
        c = db()
        try:
            c.execute("BEGIN IMMEDIATE")
            failed_attempt = c.execute("SELECT * FROM analysis_attempts WHERE id=? AND user_id=?", (aid, uid)).fetchone()
            # Refund exactly once only when the very first generation failed before any success.
            if failed_attempt and int(failed_attempt["generation_count"] or 0) == 0 and int(failed_attempt["quota_charged"] or 0) == 1 and not premium(uid):
                c.execute("UPDATE users SET usage_today=MAX(0,usage_today-1),updated_at=? WHERE user_id=?", (now(), uid))
                log_id = failed_attempt["quota_log_id"] if "quota_log_id" in failed_attempt.keys() else None
                if log_id:
                    c.execute("DELETE FROM usage_logs WHERE id=? AND user_id=?", (log_id, uid))
                c.execute("UPDATE analysis_attempts SET quota_charged=0,quota_log_id=NULL WHERE id=? AND user_id=?", (aid, uid))
            c.execute("UPDATE analysis_attempts SET generation_in_progress=0,generation_started_at=NULL,updated_at=? WHERE id=? AND user_id=?", (now(), aid, uid))
            c.execute("UPDATE ai_idempotency SET status='failed',updated_at=? WHERE user_id=? AND idempotency_key=?", (now(), uid, key))
            failed_attempt = c.execute("SELECT retry_used,module,mode FROM analysis_attempts WHERE id=? AND user_id=?", (aid, uid)).fetchone()
            c.execute("INSERT INTO ai_generation_events(user_id,analysis_id,status,error_category,error_code,retry_number,module,mode,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (uid, aid, "error", "provider_or_generation_failure", type(exc).__name__, int(failed_attempt["retry_used"] or 0) if failed_attempt else 0, module, mode, now()))
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()
        if isinstance(exc,HTTPException): raise
        if isinstance(exc,ProviderError): raise HTTPException(503,"No se pudo generar la respuesta con IA. Inténtalo de nuevo.") from None
        raise HTTPException(503,"No se pudo generar la respuesta con IA. Inténtalo de nuevo.") from None


@app.post("/api/retry")
def reserve_retry(p: dict, request: Request):
    uid=current_user(request); aid=str(p.get("analysis_id") or "")
    c=db()
    try:
        c.execute("BEGIN IMMEDIATE"); row=c.execute("SELECT * FROM analysis_attempts WHERE id=? AND user_id=?",(aid,uid)).fetchone()
        if not row: raise HTTPException(404,"Análisis no encontrado")
        if int(row["retry_used"] or 0) or int(row["generation_in_progress"] or 0): raise HTTPException(409,"El reintento ya fue utilizado o hay una generación en curso")
        c.execute("UPDATE analysis_attempts SET retry_used=1,updated_at=? WHERE id=?",(now(),aid)); c.commit(); return {"reserved":True,"analysis_id":aid}
    except HTTPException: c.rollback(); raise
    finally: c.close()


@app.post("/api/retry/release")
def release_retry(p: dict, request: Request):
    current_user(request)
    return {"released":False,"reason":"Los reintentos reservados no se reabren para evitar duplicados"}


@app.post("/api/analyze/release")
def release_analysis(p: dict, request: Request):
    uid=current_user(request); aid=str(p.get("analysis_id") or ""); c=db()
    try:
        c.execute("BEGIN IMMEDIATE"); row=c.execute("SELECT * FROM analysis_attempts WHERE id=? AND user_id=?",(aid,uid)).fetchone()
        if not row: raise HTTPException(404,"Análisis no encontrado")
        released=False
        if not int(row["generation_count"] or 0) and not int(row["generation_in_progress"] or 0) and int(row["quota_charged"] or 0) and not premium(uid):
            c.execute("UPDATE users SET usage_today=MAX(0,usage_today-1) WHERE user_id=?",(uid,))
            quota_log_id = row["quota_log_id"] if "quota_log_id" in row.keys() else None
            if quota_log_id:
                c.execute("DELETE FROM usage_logs WHERE id=? AND user_id=?", (quota_log_id, uid))
            c.execute("UPDATE analysis_attempts SET quota_charged=0,quota_log_id=NULL,updated_at=? WHERE id=?",(now(),aid)); released=True
        c.commit(); return {"released":released}
    except HTTPException: c.rollback(); raise
    finally: c.close()


@app.get("/api/ai/providers")
def ai_provider_status(request: Request):
    current_user(request)
    return {"providers": validate_provider_configuration(), "health": get_provider_health()}


def _local_alternative(reply: str, mode: str, text: str) -> str:
    """Produce a clearly identified local fallback alternative without claiming an AI provider."""
    clean = re.sub(r"^Puedes responder(?: de forma segura| con humor| con cercanía)?[: ]*", "", reply, flags=re.I).strip().strip("“”\"")
    if mode == "gracioso":
        return "Otra opción más ligera: “Jajaja, y eso que la conversación todavía no se ha puesto buena 😂.”"
    if mode == "coquetear":
        return "Otra opción más coqueta: “Jajaja, me gusta hablar contigo; siempre sale algo que comentar 😏.”"
    if mode == "enamorar":
        return "Otra opción más cálida: “Me gusta que podamos hablar así, sin forzar nada 😊.”"
    if mode == "provocativo":
        return "Otra opción con picardía: “Jajaja, ahora me dejaste con curiosidad 😏.”"
    if mode == "salvar":
        return "Otra opción tranquila: “Quizá no me expliqué bien; prefiero que lo hablemos con calma.”"
    return ("Otra forma de decirlo: " + clean[:900]) if clean else "¿Y tú qué piensas?"


def _ocr_variants(img: Image.Image):
    from PIL import ImageOps, ImageEnhance, ImageFilter

    img = img.convert("RGB")
    w, h = img.size
    max_side = max(w, h)

    # Mantener suficiente resolución para texto pequeño, pero evitar imágenes
    # gigantes que hacen lento el OCR.
    if max_side > 2600:
        scale = 2600 / max_side
        img = img.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.LANCZOS
        )

    gray = img.convert("L")

    # El OCR funciona mejor cuando el texto ocupa una cantidad razonable
    # de píxeles. Ampliamos capturas pequeñas.
    if max(gray.size) < 1800:
        factor = min(2.5, 1800 / max(gray.size))
        gray = gray.resize(
            (max(1, int(gray.width * factor)),
             max(1, int(gray.height * factor))),
            Image.Resampling.LANCZOS
        )

    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(1.45)
    gray = gray.filter(ImageFilter.SHARPEN)

    variants = [gray]

    # Umbral claro para capturas con fondo claro.
    variants.append(
        gray.point(lambda px: 255 if px > 165 else 0)
    )

    # Umbral más bajo para texto tenue/gris.
    variants.append(
        gray.point(lambda px: 255 if px > 125 else 0)
    )

    # Variante invertida para modo oscuro.
    inv = ImageOps.invert(gray)
    inv = ImageEnhance.Contrast(inv).enhance(1.25)
    variants.append(inv)

    # Umbral de la variante invertida.
    variants.append(
        inv.point(lambda px: 255 if px > 145 else 0)
    )

    return variants


def _ocr_text(img: Image.Image):
    candidates = []

    for variant_index, variant in enumerate(_ocr_variants(img)):
        for psm in (6, 11, 12):
            remaining = remaining_provider_budget()
            if remaining is not None and remaining <= 0.1:
                break
            try:
                ocr_timeout = min(3.0, remaining) if remaining is not None else 3.0
                txt = pytesseract.image_to_string(
                    variant,
                    lang="spa+eng",
                    config=f"--oem 3 --psm {psm}",
                    timeout=max(0.1, ocr_timeout),
                )
            except Exception:
                continue

            txt = re.sub(r"[ \t]+", " ", txt)
            txt = re.sub(r"\n{3,}", "\n\n", txt).strip()

            if not txt:
                continue

            lines = [x.strip() for x in txt.splitlines() if x.strip()]
            alnum = len(re.findall(
                r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]", txt
            ))
            words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]{2,}", txt)

            # Penalizar resultados que parecen ruido de OCR.
            junk = len(re.findall(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9\s.,!?¿¡:;()'\"@#$%&+\-_/]", txt))

            score = (
                alnum
                + min(len(lines), 25) * 8
                + min(len(words), 80) * 2
                - junk * 3
            )

            # Preferir texto suficientemente largo y con palabras reales.
            if len(words) >= 2:
                score += 12
            if len(txt) >= 20:
                score += 8

            candidates.append((score, txt, variant_index, psm))

    if not candidates:
        return ""

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

def _decode_ocr_image(raw: bytes) -> Image.Image:
    if not raw:
        raise HTTPException(400, "Imagen vacía")
    if len(raw) > MAX_OCR_BYTES:
        raise HTTPException(413, "La imagen supera el límite de 8 MB")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP", "BMP", "TIFF"}:
                raise HTTPException(415, "Formato de imagen no admitido")
            width, height = source.size
            if width < 1 or height < 1 or width * height > MAX_OCR_PIXELS:
                raise HTTPException(413, "La imagen tiene demasiados píxeles")
            source.load()
            return source.convert("RGB")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "Imagen inválida o dañada")


@app.post("/ocr")
async def ocr_upload(request: Request):
    # OCR is expensive; only authenticated Telegram WebApp sessions may invoke it.
    current_user(request)
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_OCR_BYTES:
            raise HTTPException(413, "La imagen supera el límite de 8 MB")
        chunks.append(chunk)
    img = _decode_ocr_image(b"".join(chunks))
    try:
        return {"ok": True, "text": _ocr_text(img)}
    except Exception:
        raise HTTPException(503, "El servicio OCR no está disponible temporalmente")

@app.post("/ocr-base64")
def ocr_base64(p: OCR, request: Request):
    current_user(request)
    encoded = p.image.split(",", 1)[-1]
    if len(encoded) > ((MAX_OCR_BYTES + 2) // 3) * 4 + 8:
        raise HTTPException(413, "La imagen supera el límite de 8 MB")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        raise HTTPException(400, "Imagen Base64 inválida")
    img = _decode_ocr_image(raw)
    try:
        return {"success": True, "text": _ocr_text(img)}
    except Exception:
        raise HTTPException(503, "El servicio OCR no está disponible temporalmente")

@app.post("/ocr-base64-simple")
def ocr_simple(p:OCR, request: Request): return ocr_base64(p, request)


@app.post("/api/profile")
def profile(p:Usage, request:Request):
    uid=current_user(request)
    u=user(uid); c=db(); rows=c.execute("SELECT module,COUNT(*) n FROM usage_logs WHERE user_id=? GROUP BY module",(uid,)).fetchall(); c.close(); counts={r["module"]:r["n"] for r in rows}
    return {"user_id":uid,"username":u.get("username"),"first_name":u.get("first_name"),"payment_phone":u.get("payment_phone") or "","premium":premium(uid),"premium_until":u.get("premium_until"),"chats":counts.get("chat",0),"stories":counts.get("story",0),"analyses":sum(counts.values())}

@app.post("/api/situations/save")
def save_situation(p:SaveSituation, request:Request):
    uid=current_user(request)
    c=db(); c.execute("INSERT INTO saved_situations(user_id,ocr_text,reply,created_at) VALUES(?,?,?,?)",(uid,p.ocr_text[:20000],p.reply[:20000],now())); c.commit(); c.close(); return {"success":True}

@app.post("/api/situations/list")
def list_situations(p:Usage, request:Request):
    uid=current_user(request)
    c=db(); rows=c.execute("SELECT id,ocr_text,reply,created_at FROM saved_situations WHERE user_id=? ORDER BY id DESC LIMIT 30",(uid,)).fetchall(); c.close(); return {"items":[dict(r) for r in rows]}


@app.post("/api/premium/check")
def premium_check(p: Usage, request:Request):
    uid=current_user(request)
    u=user(uid)
    return {
        "ok": True,
        "premium": premium(uid),
        "premium_until": u.get("premium_until")
    }

def normalize_payment_phone(value: str) -> str:
    """Normalize Cuban mobile numbers with or without the +53 country prefix."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 10 and digits.startswith("53"):
        return digits[2:]
    return digits


@app.post("/api/payment-phone")
def payment_phone(p: PaymentPhone, request: Request):
    uid = current_user(request)
    phone = normalize_payment_phone(p.phone or "")
    if len(phone) < 8 or len(phone) > 15:
        raise HTTPException(400, "Número de teléfono inválido")
    user(uid, {"payment_phone": phone})
    return {"success": True, "payment_phone": phone}


@app.post("/api/atajo-pago")
def atajo_pago(p: AtajoPayment, request: Request):
    """Recibe los datos existentes de los atajos Apple y procesa pagos idempotentemente."""
    key = request.headers.get("x-atajo-key", "")
    if not ATAJO_KEY or not hmac.compare_digest(key, ATAJO_KEY):
        raise HTTPException(401, "Atajo no autorizado")

    method = (p.metodo_pago or "").strip().upper()
    # El atajo bancario no distingue BANDEC de BPA: se conserva su identificador.
    if method in {"BANDEC", "BPA"}:
        method = "BANDEC_BPA"
    if method not in {"BANDEC_BPA", "SALDO_MOVIL"}:
        raise HTTPException(400, "Método de pago inválido")

    phone = re.sub(r"\D", "", p.telefono_origen or "")
    try:
        amount_value = round(float(p.monto_recibido or 0), 2)
    except (TypeError, ValueError):
        raise HTTPException(400, "Importe inválido")
    transaction = (p.transaccion or "").strip().upper()
    sms = (p.sms or "").strip()
    destination = re.sub(r"\D", "", p.cuenta_destino or "")
    transfer_date = (p.fecha or p.fecha_ejecucion or "").strip()

    if amount_value <= 0 or not phone:
        raise HTTPException(400, "Faltan teléfono de origen o importe válido")
    if method == "BANDEC_BPA":
        if not destination or not transaction:
            raise HTTPException(400, "Faltan cuenta de destino o número de transacción")
        # Acepta la cuenta bancaria configurada. Si BPA_ACCOUNT está configurada,
        # también la admite; no intenta inferir qué banco originó el SMS.
        configured_accounts = {
            re.sub(r"\D", "", value)
            for value in (BANDEC_ACCOUNT, BPA_ACCOUNT)
            if value and re.sub(r"\D", "", value)
        }
        if not configured_accounts:
            raise HTTPException(503, "No hay cuentas bancarias configuradas")
        if destination not in configured_accounts:
            raise HTTPException(409, "Cuenta destino no configurada")
        # El atajo bancario no manda el SMS completo: construimos una huella estable
        # a partir de los campos extraídos que sí envía.
        fingerprint_source = "|".join(
            ["BANDEC_BPA", phone, destination, f"{amount_value:.2f}", transaction, transfer_date]
        )
    else:
        if not sms:
            raise HTTPException(400, "Falta el SMS original de Saldo Móvil")
        # Validar que el SMS tenga estructura compatible con el aviso de ETECSA.
        sms_norm = " ".join(sms.lower().split())
        if "ha recibido" not in sms_norm or "numero" not in sms_norm:
            raise HTTPException(400, "El SMS no tiene el formato esperado de Saldo Móvil")
        # Verifica que teléfono e importe coincidan con el aviso original.
        sms_phone_match = re.search(r"numero\s+(\+?\d{8,12})", sms_norm, re.IGNORECASE)
        if not sms_phone_match or normalize_payment_phone(sms_phone_match.group(1)) != normalize_payment_phone(phone):
            raise HTTPException(400, "El teléfono no coincide con el SMS")
        amount_match = re.search(r"ha recibido\s+([0-9.,]+)\s*CUP", sms_norm, re.IGNORECASE)
        if not amount_match:
            raise HTTPException(400, "No se pudo leer el importe del SMS")
        try:
            sms_amount = round(float(amount_match.group(1).replace(",", "")), 2)
        except ValueError:
            raise HTTPException(400, "El importe del SMS no es válido")
        if sms_amount != amount_value:
            raise HTTPException(400, "El importe no coincide con el SMS")
        fingerprint_source = "SALDO_MOVIL|" + sms
    fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()

    c = db()
    try:
        # Serializa recepción concurrente: evita procesar dos veces la misma operación.
        c.execute("BEGIN IMMEDIATE")
        if transaction:
            duplicate = c.execute(
                "SELECT operation_id,status FROM payment_operations WHERE transaction_id=? LIMIT 1",
                (transaction,),
            ).fetchone()
        else:
            duplicate = None
        if not duplicate:
            duplicate = c.execute(
                "SELECT operation_id,status FROM payment_operations WHERE source_sms=? LIMIT 1",
                (fingerprint,),
            ).fetchone()
        if duplicate:
            c.rollback()
            return {
                "success": False,
                "status": "duplicate",
                "operation_id": duplicate["operation_id"],
            }

        # Una sola operación activa por usuario: el pago debe coincidir con
        # teléfono registrado, método, importe y destino cuando aplica.
        rows = c.execute(
            """SELECT po.*, u.payment_phone
               FROM payment_operations po
               JOIN users u ON u.user_id=po.user_id
               WHERE po.status='pending'
               ORDER BY po.created_at ASC"""
        ).fetchall()
        candidates = []
        for row in rows:
            row_method = (row["payment_method"] or "").strip().upper()
            if method == "BANDEC_BPA":
                if row_method not in {"BANDEC_BPA", "BANDEC", "BPA"}:
                    continue
                row_destination = re.sub(r"\D", "", row["destination_account"] or "")
                if not row_destination or row_destination != destination:
                    continue
            else:
                if row_method != "SALDO_MOVIL":
                    continue
            expected_amount = float(re.sub(r"[^0-9.]", "", row["amount"] or "0") or 0)
            if round(expected_amount, 2) != amount_value:
                continue
            registered = row["payment_phone"] or row["payer_phone"] or ""
            if not registered or normalize_payment_phone(registered) != normalize_payment_phone(phone):
                continue
            candidates.append(row)

        if len(candidates) != 1:
            c.rollback()
            return {
                "success": False,
                "status": "unmatched" if not candidates else "ambiguous",
                "matches": len(candidates),
            }

        matched = candidates[0]
        t = now()
        updated = c.execute(
            """UPDATE payment_operations
               SET status='verified', payer_phone=?, destination_account=?,
                   transaction_id=?, transfer_date=?, source_sms=?,
                   verified_at=?, updated_at=?
               WHERE operation_id=? AND status='pending'""",
            (
                phone, destination, transaction, transfer_date, fingerprint,
                t, t, matched["operation_id"],
            ),
        )
        if updated.rowcount != 1:
            c.rollback()
            return {"success": False, "status": "already_processed"}

        # Actualización de pago y Premium en la misma transacción.
        user_row = c.execute(
            "SELECT premium_until FROM users WHERE user_id=?",
            (matched["user_id"],),
        ).fetchone()
        days = 7 if matched["plan"] == "weekly" else 365
        base_time = datetime.now(timezone.utc)
        current = user_row["premium_until"] if user_row else None
        if current:
            try:
                base_time = max(base_time, _utc_datetime(current))
            except (ValueError, TypeError):
                pass
        until = (base_time + timedelta(days=days)).isoformat()
        c.execute(
            "UPDATE users SET premium_until=?,updated_at=? WHERE user_id=?",
            (until, t, matched["user_id"]),
        )
        c.commit()
        return {
            "success": True,
            "status": "verified",
            "operation_id": matched["operation_id"],
            "user_id": matched["user_id"],
            "premium_until": until,
        }
    except sqlite3.IntegrityError:
        c.rollback()
        return {"success": False, "status": "duplicate"}
    finally:
        c.close()

@app.post("/api/payments/pending")
def pending(p: Pending, request: Request):
    uid = current_user(request)
    if p.plan not in {"weekly", "annual"}:
        raise HTTPException(400, "Plan inválido")
    method = (p.payment_method or "BANDEC").strip().upper()
    if method not in {"BANDEC", "BPA", "SALDO_MOVIL"}:
        raise HTTPException(400, "Método de pago inválido")

    registered_user = user(uid)
    c = db()
    try:
        c.execute("BEGIN IMMEDIATE")
        existing = c.execute(
            """SELECT * FROM payment_operations
               WHERE user_id=? AND status IN ('pending','proof_submitted')
               ORDER BY created_at DESC LIMIT 1""",
            (uid,),
        ).fetchone()
        if existing:
            # No permitir cambiar método/plan en mitad de una operación.
            c.commit()
            return {
                "success": True,
                "operation_id": existing["operation_id"],
                "status": existing["status"],
                "amount": existing["amount"],
                "payment_method": existing["payment_method"],
                "destination_account": existing["destination_account"] or "",
                "payment_phone": existing["payer_phone"] or registered_user.get("payment_phone") or "",
                "existing_operation": True,
                "requires_cancel_to_change": (
                    existing["payment_method"] != method or existing["plan"] != p.plan
                ),
            }

        oid = uuid.uuid4().hex[:12].upper()
        t = now()
        a = amount(p.plan, p.language)
        if method == "BANDEC":
            destination = BANDEC_ACCOUNT
            if not re.sub(r"\D", "", destination or ""):
                raise HTTPException(503, "Cuenta BANDEC no configurada")
        elif method == "BPA":
            destination = BPA_ACCOUNT
            if not re.sub(r"\D", "", destination or ""):
                raise HTTPException(503, "Cuenta BPA no configurada")
        else:
            destination = ""
        phone = registered_user.get("payment_phone") or ""
        c.execute(
            """INSERT INTO payment_operations(
               operation_id,user_id,plan,language,status,amount,payment_method,
               payer_phone,destination_account,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (oid, uid, p.plan, p.language, "pending", a, method, phone, destination, t, t),
        )
        c.commit()
        return {
            "success": True,
            "operation_id": oid,
            "status": "pending",
            "amount": a,
            "payment_method": method,
            "destination_account": destination,
            "payment_phone": phone,
            "existing_operation": False,
        }
    except sqlite3.IntegrityError:
        c.rollback()
        raise HTTPException(409, "Ya existe una operación de pago activa")
    finally:
        c.close()

@app.post("/api/payments/proof")
def proof(p:Proof, request:Request):
    uid=current_user(request)
    c=db(); row=c.execute("SELECT * FROM payment_operations WHERE operation_id=? AND user_id=?",(p.operation_id,uid)).fetchone()
    if not row: c.close(); raise HTTPException(404,"Operación no encontrada")
    if row["status"] not in {"pending","proof_submitted"}: c.close(); raise HTTPException(409,"La operación ya no admite comprobantes")
    if len(p.proof_text)>4000: raise HTTPException(400,"Comprobante demasiado largo")
    image=p.proof_image or ""
    if len(image)>3_000_000: raise HTTPException(400,"El comprobante de imagen supera 3 MB")
    t=now(); c.execute("UPDATE payment_operations SET status='proof_submitted',proof_text=?,proof_image=?,updated_at=? WHERE operation_id=?",(p.proof_text,image,t,p.operation_id)); c.commit(); c.close(); return {"success":True,"status":"proof_submitted"}

@app.post("/api/payments/cancel")
def cancel(p:PaymentId, request:Request):
    uid=current_user(request)
    if not uid: raise HTTPException(400,"user_id requerido")
    c=db(); row=c.execute("SELECT * FROM payment_operations WHERE operation_id=? AND user_id=?",(p.operation_id,uid)).fetchone()
    if not row: c.close(); raise HTTPException(404,"Operación no encontrada")
    if row["status"] in {"verified","cancelled"}: c.close(); raise HTTPException(409,"La operación ya está cerrada")
    t=now(); c.execute("UPDATE payment_operations SET status='cancelled',cancelled_at=?,updated_at=? WHERE operation_id=?",(t,t,p.operation_id)); c.commit(); c.close(); return {"success":True,"status":"cancelled"}

@app.post("/api/payments/status")
def status(p:PaymentId, request:Request):
    uid=current_user(request)
    c=db(); row=c.execute("SELECT operation_id,user_id,plan,language,status,amount,created_at,updated_at,verified_at,cancelled_at FROM payment_operations WHERE operation_id=? AND user_id=?",(p.operation_id,uid)).fetchone(); c.close()
    if not row: raise HTTPException(404,"Operación no encontrada")
    return dict(row)

@app.post("/api/admin/login")
def admin_login(p: AdminLogin):
    if not ADMIN_KEY:
        raise HTTPException(503, "ADMIN_KEY no configurado en Railway")
    is_owner = bool(p.master_key and hmac.compare_digest(p.master_key, ADMIN_KEY))
    if is_owner:
        username = "owner"
        permissions = ["users", "premium", "payments", "stats", "admins", "settings", "audit", "ai_analytics"]
        ttl = OWNER_SESSION_TTL
    else:
        username_input = p.username.strip()
        c = db()
        row = c.execute("SELECT * FROM admin_users WHERE username=? AND is_active=1", (username_input,)).fetchone()
        c.close()
        if not row:
            raise HTTPException(401, "Credenciales incorrectas")
        salt_hex, stored_hash = row["password_hash"].split(":", 1)
        calculated = hashlib.pbkdf2_hmac("sha256", p.password.encode(), bytes.fromhex(salt_hex), 180000).hex()
        if not hmac.compare_digest(stored_hash, calculated):
            raise HTTPException(401, "Credenciales incorrectas")
        username = row["username"]
        permissions = json.loads(row["permissions"])
        ttl = ADMIN_SESSION_TTL
    claims = {"username": username, "exp": int(time.time()) + ttl, "jti": uuid.uuid4().hex}
    if is_owner:
        claims["role"] = "owner"
    payload = _b64e(json.dumps(claims, separators=(",", ":")).encode())
    token = payload + "." + _b64e(hmac.new(ADMIN_KEY.encode(), payload.encode(), hashlib.sha256).digest())
    session_db = db()
    try:
        session_db.execute(
            "INSERT INTO admin_sessions(session_id, username, expires_at, created_at, revoked_at) VALUES(?,?,?,?,NULL)",
            (claims["jti"], username, claims["exp"], now()),
        )
        session_db.commit()
    finally:
        session_db.close()
    return {"success": True, "token": token, "username": username, "is_owner": is_owner, "permissions": permissions,
            "expires_at": datetime.fromtimestamp(claims["exp"], timezone.utc).isoformat(),
            "session_days": 90 if is_owner else 7}

@app.get("/api/admin/me")
def admin_me(request:Request): return admin_identity(request)

@app.post("/api/admin/logout")
def admin_logout(request: Request):
    identity = admin_identity(request)
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    payload = token.rsplit(".", 1)[0]
    claims = json.loads(_b64d(payload).decode())
    c = db()
    try:
        c.execute("UPDATE admin_sessions SET revoked_at=? WHERE session_id=? AND username=? AND revoked_at IS NULL",
                  (now(), str(claims.get("jti", "")), identity["username"]))
        c.commit()
    finally:
        c.close()
    return {"success": True, "logged_out": True}

@app.get("/api/admin/users")
def admin_users(request:Request, q:str=""):
    ident=admin(request,"users"); c=db(); term=f"%{q.strip()}%"
    rows=c.execute("SELECT user_id,username,first_name,last_name,premium_until,payment_phone,created_at FROM users WHERE user_id LIKE ? OR username LIKE ? OR first_name LIKE ? ORDER BY created_at DESC LIMIT 200",(term,term,term)).fetchall(); c.close()
    return {"items":[{**dict(r),"premium":bool(r["premium_until"] and _utc_datetime(r["premium_until"]) > _utc_datetime())} for r in rows]}

@app.post("/api/admin/premium")
def admin_premium(p:PremiumChange, request:Request):
    ident=admin(request,"premium"); uid=str(p.user_id); u=user(uid); t=now()
    if p.action == "revoke":
        until = None
    elif p.action in {"grant", "extend"}:
        # Grants/renewals never discard already-paid time on an active subscription.
        base = datetime.now(timezone.utc)
        try:
            if u.get("premium_until"):
                base = max(base, _utc_datetime(u["premium_until"]))
        except (ValueError, TypeError):
            pass
        until = (base + timedelta(days=max(1, min(int(p.days), 3650)))).isoformat()
    else: raise HTTPException(400,"Acción inválida")
    c=db(); c.execute("UPDATE users SET premium_until=?,updated_at=? WHERE user_id=?",(until,t,uid)); c.commit(); c.close(); audit(ident["username"],"premium_"+p.action,uid,{"days":p.days,"premium_until":until}); return {"success":True,"user_id":uid,"premium_until":until,"premium":bool(until and _utc_datetime(until) > _utc_datetime())}

@app.get("/api/admin/admins")
def admin_list(request:Request):
    admin(request,"admins"); c=db(); rows=c.execute("SELECT username,permissions,is_active,created_at FROM admin_users ORDER BY created_at DESC").fetchall(); c.close(); return {"items":[{**dict(r),"permissions":json.loads(r["permissions"])} for r in rows]}

@app.post("/api/admin/admins")
def admin_create(p:AdminCreate, request:Request):
    ident=admin(request,"admins"); username=re.sub(r"[^a-zA-Z0-9_.-]","",p.username.strip())
    if len(username)<3 or len(p.password)<10: raise HTTPException(400,"Usuario mínimo 3 caracteres y contraseña mínimo 10")
    allowed={"users","premium","payments","stats","audit","ai_analytics"}; perms=sorted(set(p.permissions)&allowed)
    if not perms: raise HTTPException(400,"Selecciona al menos un permiso")
    salt=os.urandom(16); digest=salt.hex()+":"+hashlib.pbkdf2_hmac("sha256",p.password.encode(),salt,180000).hex(); t=now(); c=db()
    try: c.execute("INSERT INTO admin_users(username,password_hash,permissions,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?)",(username,digest,json.dumps(perms),1,t,t)); c.commit()
    except sqlite3.IntegrityError: c.close(); raise HTTPException(409,"Ese administrador ya existe")
    c.close(); audit(ident["username"],"admin_created",username,{"permissions":perms}); return {"success":True,"username":username,"permissions":perms}

@app.post("/api/admin/admins/status")
def admin_admin_status(p:AdminStatus, request:Request):
    ident=admin(request,"admins")
    if p.username=="owner": raise HTTPException(400,"No se puede desactivar al administrador principal")
    c=db(); cur=c.execute("UPDATE admin_users SET is_active=?,updated_at=? WHERE username=?",(1 if p.is_active else 0,now(),p.username)); c.commit(); c.close()
    if not cur.rowcount: raise HTTPException(404,"Administrador no encontrado")
    audit(ident["username"],"admin_status",p.username,{"active":p.is_active}); return {"success":True}

@app.get("/api/admin/audit")
def admin_audit(request:Request):
    admin(request,"audit"); c=db(); rows=c.execute("SELECT actor,action,target,details,created_at FROM admin_audit ORDER BY id DESC LIMIT 200").fetchall(); c.close(); return {"items":[dict(r) for r in rows]}

@app.post("/api/admin/payments/verify")
def verify_payment(p:PaymentId, request:Request):
    ident=admin(request,"payments")
    c=db()
    try:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT * FROM payment_operations WHERE operation_id=?",(p.operation_id,)).fetchone()
        if not row:
            c.rollback()
            raise HTTPException(404,"Operación no encontrada")
        if row["status"] not in {"pending","proof_submitted"}:
            c.rollback()
            raise HTTPException(409,"Operación no verificable o ya procesada")
        # Reserve the operation atomically so a concurrent request cannot grant Premium twice.
        t=now()
        cur=c.execute("UPDATE payment_operations SET status='processing',updated_at=? WHERE operation_id=? AND status IN ('pending','proof_submitted')",(t,p.operation_id))
        if cur.rowcount != 1:
            c.rollback()
            raise HTTPException(409,"La operación ya está siendo procesada")
        current_row=c.execute("SELECT premium_until FROM users WHERE user_id=?",(row["user_id"],)).fetchone()
        current=current_row["premium_until"] if current_row else None
        base=datetime.now(timezone.utc)
        if current:
            try: base=max(base,_utc_datetime(current))
            except ValueError: pass
        days=7 if row["plan"]=="weekly" else 365
        until=(base+timedelta(days=days)).isoformat()
        c.execute("UPDATE users SET premium_until=?,updated_at=? WHERE user_id=?",(until,t,row["user_id"]))
        c.execute("UPDATE payment_operations SET status='verified',verified_at=?,updated_at=? WHERE operation_id=? AND status='processing'",(t,t,p.operation_id))
        c.commit()
    except HTTPException:
        raise
    except Exception:
        c.rollback()
        raise HTTPException(500,"No se pudo verificar el pago")
    finally:
        c.close()
    audit(ident["username"],"payment_verified",p.operation_id,{"user_id":row["user_id"],"premium_until":until})
    return {"success":True,"status":"verified","premium_until":until}

@app.post("/api/admin/payments/reject")
def reject_payment(p: PaymentReview, request:Request):
    ident=admin(request,"payments")
    c=db()
    try:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT * FROM payment_operations WHERE operation_id=?",(p.operation_id,)).fetchone()
        if not row:
            c.rollback()
            raise HTTPException(404,"Operación no encontrada")
        if row["status"] not in {"pending","proof_submitted"}:
            c.rollback()
            raise HTTPException(409,"Operación ya procesada")
        t=now()
        cur=c.execute("UPDATE payment_operations SET status='rejected',updated_at=? WHERE operation_id=? AND status IN ('pending','proof_submitted')",(t,p.operation_id))
        if cur.rowcount != 1:
            c.rollback()
            raise HTTPException(409,"La operación ya fue procesada")
        c.commit()
    except HTTPException:
        raise
    except Exception:
        c.rollback()
        raise HTTPException(500,"No se pudo rechazar el pago")
    finally:
        c.close()
    audit(ident["username"],"payment_rejected",p.operation_id,{"reason":p.reason,"user_id":row["user_id"]})
    return {"success":True,"status":"rejected"}

@app.get("/api/admin/stats")
def admin_stats(request:Request):
    admin(request,"stats"); c=db(); out={"total_users":c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],"premium_users":c.execute("SELECT COUNT(*) n FROM users WHERE premium_until>?",(now(),)).fetchone()["n"],"today_usage":c.execute("SELECT COUNT(*) n FROM usage_logs WHERE used_at>=?",(cuba_day_start_utc(),)).fetchone()["n"],"pending_payments":c.execute("SELECT COUNT(*) n FROM payment_operations WHERE status IN ('pending','proof_submitted')").fetchone()["n"]}; c.close(); return out

@app.get("/api/admin/ai-monitor")
def admin_ai_monitor(request: Request):
    admin(request, "ai_analytics")
    c = db()
    try:
        today_start = today() + "T00:00:00"
        totals = c.execute("""
          SELECT COUNT(*) total,
                 SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) successes,
                 SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) failures,
                 COUNT(DISTINCT user_id) users,
                 AVG(CASE WHEN status='success' THEN latency_ms END) avg_latency,
                 AVG(CASE WHEN status='success' THEN quality_score END) avg_quality
          FROM ai_generation_events WHERE created_at >= ?
        """, (today_start,)).fetchone()
        provider_rows = c.execute("""
          SELECT provider, model, COUNT(*) total,
                 SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) successes,
                 SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) failures,
                 AVG(latency_ms) avg_latency,
                 AVG(quality_score) avg_quality
          FROM ai_generation_events GROUP BY provider, model ORDER BY total DESC LIMIT 30
        """).fetchall()
        user_rows = c.execute("""
          SELECT u.user_id, COALESCE(NULLIF(u.username,''), NULLIF(TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')),''), 'Usuario') display_name,
                 u.usage_today, u.premium_until,
                 COUNT(e.id) total_attempts,
                 (SELECT COUNT(*) FROM analysis_attempts aa WHERE aa.user_id=u.user_id) total_analyses,
                 SUM(CASE WHEN e.status='success' THEN 1 ELSE 0 END) successes,
                 SUM(CASE WHEN e.status='error' THEN 1 ELSE 0 END) failures,
                 AVG(e.quality_score) avg_quality,
                 (SELECT e2.model FROM ai_generation_events e2 WHERE e2.user_id=u.user_id ORDER BY e2.id DESC LIMIT 1) last_model,
                 (SELECT e3.provider FROM ai_generation_events e3 WHERE e3.user_id=u.user_id ORDER BY e3.id DESC LIMIT 1) last_provider
          FROM users u LEFT JOIN ai_generation_events e ON e.user_id=u.user_id
          GROUP BY u.user_id ORDER BY total_attempts DESC, u.created_at DESC LIMIT 200
        """).fetchall()
        event_rows = c.execute("""
          SELECT e.created_at, COALESCE(NULLIF(u.username,''), NULLIF(TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')),''), 'Usuario') display_name,
                 e.provider, e.model, e.status, e.error_code, e.latency_ms, e.quality_score, e.retry_number, e.module, e.mode
          FROM ai_generation_events e LEFT JOIN users u ON u.user_id=e.user_id
          ORDER BY e.id DESC LIMIT 100
        """).fetchall()
        days = c.execute("""
          SELECT substr(created_at,1,10) day,
                 SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) successes,
                 SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) failures
          FROM ai_generation_events WHERE created_at >= ? GROUP BY substr(created_at,1,10) ORDER BY day
        """, ((datetime.now(timezone.utc)-timedelta(days=6)).isoformat(),)).fetchall()
        total=int(totals["total"] or 0); successes=int(totals["successes"] or 0); failures=int(totals["failures"] or 0)
        return {
          "summary":{"today_events":total,"successes":successes,"failures":failures,
                     "success_rate":round(successes*100/total,1) if total else 0,
                     "unique_users":int(totals["users"] or 0),
                     "avg_latency_ms":round(totals["avg_latency"] or 0),
                     "avg_quality":round(totals["avg_quality"] or 0,1)},
          "providers":[{**dict(r),"total":int(r["total"] or 0),"successes":int(r["successes"] or 0),
                        "failures":int(r["failures"] or 0),"avg_latency":round(r["avg_latency"] or 0),
                        "avg_quality":round(r["avg_quality"] or 0,1)} for r in provider_rows],
          "users":[{**dict(r),"remaining_attempts":max(0, FREE_DAILY_LIMIT-int(r["usage_today"] or 0)),
                    "successes":int(r["successes"] or 0),"failures":int(r["failures"] or 0),
                    "total_attempts":int(r["total_attempts"] or 0),
                    "total_analyses":int(r["total_analyses"] or 0),
                    "success_rate":round(int(r["successes"] or 0)*100/max(1,int(r["total_attempts"] or 0)),1),
                    "avg_quality":round(r["avg_quality"] or 0,1),
                    "premium":bool(r["premium_until"] and _utc_datetime(r["premium_until"]) > _utc_datetime())} for r in user_rows],
          "events":[dict(r) for r in event_rows],
          "days":[dict(r) for r in days],
          "provider_health": get_provider_health(),
          "provider_configuration": validate_provider_configuration(),
          "quality_note":"Puntuación heurística estimada (1–100), no evaluación semántica objetiva. La salud en memoria es local al proceso y no sustituye métricas persistentes. No se guardan imágenes, textos de conversación, respuestas ni claves API."
        }
    finally:
        c.close()


@app.get("/api/admin/payments")
def admin_payments(request:Request):
    admin(request,"payments"); c=db()
    rows=c.execute("""SELECT operation_id,user_id,plan,language,status,amount,proof_text,payment_method,payer_phone,destination_account,transaction_id,transfer_date,created_at,updated_at,verified_at,cancelled_at
                      FROM payment_operations ORDER BY created_at DESC LIMIT 100""").fetchall()
    c.close()
    return {"items":[dict(r) for r in rows]}

@app.post("/api/atajo-diagnostico")
async def atajo_diagnostico(request: Request):
    # This diagnostic endpoint must not be an unauthenticated public reflector.
    key = request.headers.get("x-atajo-key", "")
    if not ATAJO_KEY or not hmac.compare_digest(key, ATAJO_KEY):
        raise HTTPException(401, "Atajo no autorizado")
    body = await request.body()
    if len(body) > 16 * 1024:
        raise HTTPException(413, "Solicitud demasiado grande")
    return {
        "success": True,
        "mensaje": "Atajos se comunica con el servidor",
        "bytes_recibidos": len(body),
    }


@app.get("/api/admin/ai-providers")
def admin_ai_providers(request: Request):
    admin(request, "settings")
    c = db()
    try:
        rows = c.execute("SELECT provider_id,name,base_url,model,supports_text,supports_image,enabled,priority,last_test_status,last_test_at,last_error_category,created_at,updated_at,api_key_encrypted FROM custom_ai_providers ORDER BY priority,name").fetchall()
        return {"encryption_configured": len((os.getenv("AI_PROVIDER_ENCRYPTION_KEY") or "").strip()) >= 32,
                "items": [{k: row[k] for k in row.keys() if k != "api_key_encrypted"} | {"has_api_key": bool(row["api_key_encrypted"])} for row in rows],
                "built_in": validate_provider_configuration()}
    finally:
        c.close()


@app.post("/api/admin/ai-providers")
def admin_ai_provider_upsert(p: AIProviderUpsert, request: Request):
    ident = admin(request, "settings")
    provider_id = re.sub(r"[^a-z0-9_-]", "", p.provider_id.strip().lower())
    name = p.name.strip()[:80]
    model = p.model.strip()[:200]
    if not provider_id or len(provider_id) > 48 or not name or not model:
        raise HTTPException(400, "Identificador, nombre y modelo son obligatorios; el ID debe usar letras, números, guion o guion bajo.")
    if provider_id in {"gemini", "groq", "openrouter", "cohere"}:
        raise HTTPException(409, "Ese ID está reservado para un proveedor integrado.")
    try:
        endpoint = normalize_compatible_endpoint(p.base_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    if not (1 <= int(p.priority) <= 1000):
        raise HTTPException(400, "La prioridad debe estar entre 1 y 1000; el número menor se intenta primero.")
    if not p.supports_text and not p.supports_image:
        raise HTTPException(400, "Selecciona al menos una capacidad: texto o imagen.")
    c = db()
    try:
        existing = c.execute("SELECT api_key_encrypted FROM custom_ai_providers WHERE provider_id=?", (provider_id,)).fetchone()
        if not existing and not p.api_key.strip():
            raise HTTPException(400, "Introduce la clave API para registrar el proveedor.")
        if p.api_key.strip():
            try:
                encrypted = encrypt_provider_key(p.api_key.strip())
            except ProviderError as exc:
                raise HTTPException(503, "Configura AI_PROVIDER_ENCRYPTION_KEY en Railway antes de guardar claves.") from None
        else:
            encrypted = existing["api_key_encrypted"]
        timestamp = now()
        c.execute("""INSERT INTO custom_ai_providers(provider_id,name,base_url,model,api_key_encrypted,supports_text,supports_image,enabled,priority,created_at,updated_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(provider_id) DO UPDATE SET name=excluded.name,base_url=excluded.base_url,model=excluded.model,
                     api_key_encrypted=excluded.api_key_encrypted,supports_text=excluded.supports_text,supports_image=excluded.supports_image,
                     enabled=excluded.enabled,priority=excluded.priority,updated_at=excluded.updated_at,last_test_status=NULL,last_error_category=NULL""",
                  (provider_id,name,endpoint,model,encrypted,int(p.supports_text),int(p.supports_image),int(p.enabled),int(p.priority),timestamp,timestamp))
        c.commit()
    finally:
        c.close()
    audit(ident["username"], "ai_provider_upsert", provider_id, {"name": name, "model": model, "enabled": p.enabled, "priority": p.priority, "supports_text": p.supports_text, "supports_image": p.supports_image})
    return {"success": True, "provider_id": provider_id, "api_key_saved": True, "api_key_returned": False}


@app.post("/api/admin/ai-providers/{provider_id}/test")
def admin_ai_provider_test(provider_id: str, request: Request):
    ident = admin(request, "settings")
    c = db()
    try:
        row = c.execute("SELECT * FROM custom_ai_providers WHERE provider_id=?", (provider_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Proveedor no encontrado")
        try:
            config = dict(row)
            config["api_key"] = decrypt_provider_key(row["api_key_encrypted"])
            result = test_custom_provider(config)
            status, category = "success", None
        except Exception as exc:
            result = {"ok": False, "latency_ms": None, "error_category": getattr(exc, "category", "connection_error")}
            status, category = "error", result["error_category"]
        c.execute("UPDATE custom_ai_providers SET last_test_status=?,last_test_at=?,last_error_category=?,updated_at=? WHERE provider_id=?", (status, now(), category, now(), provider_id))
        c.commit()
    finally:
        c.close()
    audit(ident["username"], "ai_provider_test", provider_id, {"status": status, "error_category": category, "latency_ms": result.get("latency_ms")})
    return result


@app.delete("/api/admin/ai-providers/{provider_id}")
def admin_ai_provider_delete(provider_id: str, request: Request):
    ident = admin(request, "settings")
    c = db()
    try:
        cur = c.execute("DELETE FROM custom_ai_providers WHERE provider_id=?", (provider_id,))
        c.commit()
    finally:
        c.close()
    if not cur.rowcount:
        raise HTTPException(404, "Proveedor no encontrado")
    audit(ident["username"], "ai_provider_deleted", provider_id, {})
    return {"success": True, "provider_id": provider_id}
