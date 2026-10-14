from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from PIL import Image
import asyncio, base64, hashlib, hmac, io, json, os, re, sqlite3, time, uuid
import pytesseract
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl
from backend.ai_providers import (ProviderError, generate_reply as ai_generate_reply, collect_timings,
                                  provider_deadline, remaining_provider_budget, get_provider_health,
                                  validate_provider_configuration)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@asynccontextmanager
async def app_lifespan(application):
    cleanup_task = asyncio.create_task(_retention_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="LiggaCuba API", version="2.2", lifespan=app_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

FREE_DAILY_LIMIT = 3
MAX_OCR_BYTES = 8 * 1024 * 1024
MAX_OCR_PIXELS = 25_000_000
FREE_CHAT_MODES = {"gracioso", "coquetear", "enamorar"}
PREMIUM_CHAT_MODES = {"provocativo", "salvar"}
FREE_STORY_MODES = {"gracioso", "coquetear"}
PREMIUM_STORY_MODES = {"provocativo", "enamorar"}
DB_PATH = os.getenv("DB_PATH", os.path.join(ROOT, "liggacuba.db"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
ATAJO_KEY = os.getenv("ATAJO_KEY", "")
BANDEC_ACCOUNT = os.getenv("BANDEC_ACCOUNT", "9244069990684435")
BPA_ACCOUNT = os.getenv("BPA_ACCOUNT", "")
PAYMENT_PHONE = os.getenv("PAYMENT_PHONE", "52677163")
SESSION_TTL = 86400
CUBA_TZ = ZoneInfo("America/Havana")
ADMIN_SESSION_TTL = 7 * 24 * 60 * 60
OWNER_SESSION_TTL = 90 * 24 * 60 * 60


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _session_signing_key() -> bytes:
    """Return the independent session signing secret or fail closed."""
    secret = SESSION_SECRET
    if not isinstance(secret, str) or len(secret) < 32:
        raise HTTPException(
            503,
            "SESSION_SECRET no configurado o demasiado corto (mínimo 32 caracteres)",
        )
    return secret.encode("utf-8")


def session_token(uid: str) -> str:
    uid = str(uid or "").strip()
    if not uid:
        raise HTTPException(400, "Usuario inválido")
    key = _session_signing_key()
    payload = _b64e(json.dumps(
        {"uid": uid, "exp": int(time.time()) + SESSION_TTL},
        separators=(",", ":"),
    ).encode())
    sig = _b64e(hmac.new(key, payload.encode(), hashlib.sha256).digest())
    return payload + "." + sig


def verify_session(token: str) -> str:
    if not token or not isinstance(token, str) or len(token) > 8192 or "." not in token:
        raise HTTPException(401, "Sesión requerida")
    key = _session_signing_key()
    payload, sig = token.rsplit(".", 1)
    expected = _b64e(hmac.new(key, payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(401, "Sesión inválida")
    try:
        data = json.loads(_b64d(payload).decode())
        if not isinstance(data, dict):
            raise ValueError("payload inválido")
        expiry = data.get("exp")
        if isinstance(expiry, bool) or not isinstance(expiry, int):
            raise ValueError("expiración inválida")
        if expiry <= int(time.time()):
            raise HTTPException(401, "Sesión expirada")
        raw_uid = data.get("uid")
        if not isinstance(raw_uid, (str, int)) or isinstance(raw_uid, bool):
            raise ValueError("usuario inválido")
        uid = str(raw_uid).strip()
        if not uid:
            raise ValueError("usuario inválido")
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


def _utc_datetime(value: Optional[str] = None) -> datetime:
    """Parse legacy naive timestamps and normalize all comparisons to UTC."""
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def now():
    """Store timestamps in UTC; clients display them in Cuba's local timezone."""
    return datetime.now(timezone.utc).isoformat()

def cuba_now():
    """Current wall-clock time in Cuba, including DST rules."""
    return datetime.now(CUBA_TZ)

def today():
    """Business date in Cuba, used for daily quotas and daily analysis validity."""
    return cuba_now().date().isoformat()

def cuba_day_start_utc():
    """UTC instant corresponding to midnight at the start of Cuba's current day."""
    local_midnight = datetime.combine(cuba_now().date(), datetime.min.time(), tzinfo=CUBA_TZ)
    return local_midnight.astimezone(timezone.utc).isoformat()


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
    CREATE TABLE IF NOT EXISTS analysis_attempts(
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL, analysis_date TEXT NOT NULL,
      module TEXT NOT NULL, mode TEXT NOT NULL, retry_used INTEGER NOT NULL DEFAULT 0,
      generation_count INTEGER NOT NULL DEFAULT 0, generation_in_progress INTEGER NOT NULL DEFAULT 0, generation_started_at TEXT, quota_charged INTEGER NOT NULL DEFAULT 0, retry_call_started INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
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
      session_id TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at INTEGER NOT NULL,
      created_at TEXT NOT NULL, revoked_at TEXT
    );
    CREATE TABLE IF NOT EXISTS ai_idempotency(
      user_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
      status TEXT NOT NULL, result_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      PRIMARY KEY(user_id, idempotency_key)
    );
    CREATE INDEX IF NOT EXISTS idx_ai_idempotency_created ON ai_idempotency(created_at);
    CREATE TABLE IF NOT EXISTS ai_generation_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      analysis_id TEXT, user_id TEXT NOT NULL, module TEXT, mode TEXT,
      provider TEXT, model TEXT, status TEXT NOT NULL, error_code TEXT,
      latency_ms INTEGER NOT NULL DEFAULT 0, quality_score INTEGER,
      retry_number INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
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
        "ALTER TABLE analysis_attempts ADD COLUMN generation_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE analysis_attempts ADD COLUMN generation_in_progress INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE analysis_attempts ADD COLUMN generation_started_at TEXT",
        "ALTER TABLE analysis_attempts ADD COLUMN quota_charged INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE analysis_attempts ADD COLUMN retry_call_started INTEGER NOT NULL DEFAULT 0",
    ):
        try:
            c.execute(sql)
        except sqlite3.OperationalError:
            pass
    c.execute("CREATE INDEX IF NOT EXISTS idx_ai_events_created ON ai_generation_events(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ai_events_user ON ai_generation_events(user_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ai_events_provider ON ai_generation_events(provider, status)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_transaction ON payment_operations(transaction_id) WHERE transaction_id IS NOT NULL AND transaction_id != ''")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_source_sms ON payment_operations(source_sms) WHERE source_sms IS NOT NULL AND source_sms != ''")
    c.commit(); c.close()
init_db()


def purge_expired_records() -> None:
    """Apply retention limits to idempotency results and operational/security metadata."""
    current = datetime.now(timezone.utc)
    idempotency_cutoff = (current - timedelta(hours=24)).isoformat()
    ai_events_cutoff = (current - timedelta(days=30)).isoformat()
    audit_cutoff = (current - timedelta(days=90)).isoformat()
    c = db()
    try:
        c.execute("DELETE FROM ai_idempotency WHERE created_at < ?", (idempotency_cutoff,))
        c.execute("DELETE FROM ai_generation_events WHERE created_at < ?", (ai_events_cutoff,))
        c.execute("DELETE FROM admin_audit WHERE created_at < ?", (audit_cutoff,))
        c.commit()
    finally:
        c.close()


async def _retention_cleanup_loop() -> None:
    """Run once at startup and then hourly; failures are logged without stopping the API."""
    import logging
    logger = logging.getLogger(__name__)
    while True:
        try:
            await asyncio.to_thread(purge_expired_records)
        except Exception as exc:
            logger.error("Retention cleanup failed (type=%s)", type(exc).__name__)
        await asyncio.sleep(3600)


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
    try: return _utc_datetime() < _utc_datetime(p)
    except ValueError: return False


def usage(uid):
    reset(uid); u=user(uid); used=int(u.get("usage_today") or 0); prem=premium(uid)
    return {"allowed": prem or used < FREE_DAILY_LIMIT, "remaining": 999 if prem else max(0,FREE_DAILY_LIMIT-used), "used_today":used, "premium":prem}


def consume(uid, module, mode):
    """Atomically consume one free use; concurrent requests cannot exceed the limit."""
    reset(uid)
    c = db()
    try:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT usage_today, last_reset_date, premium_until FROM users WHERE user_id=?",
            (uid,),
        ).fetchone()
        if row is None:
            t = now()
            c.execute(
                "INSERT INTO users(user_id,created_at,updated_at,last_reset_date) VALUES(?,?,?,?)",
                (uid, t, t, today()),
            )
            row = c.execute(
                "SELECT usage_today,last_reset_date,premium_until FROM users WHERE user_id=?",
                (uid,),
            ).fetchone()
        if row["last_reset_date"] != today():
            c.execute(
                "UPDATE users SET usage_today=0,last_reset_date=?,updated_at=? WHERE user_id=?",
                (today(), now(), uid),
            )
            used = 0
        else:
            used = int(row["usage_today"] or 0)
        try:
            is_premium = bool(row["premium_until"] and _utc_datetime() < _utc_datetime(row["premium_until"]))
        except (TypeError, ValueError):
            is_premium = False
        if not is_premium and used >= FREE_DAILY_LIMIT:
            c.commit()
            return {"allowed": False, "remaining": 0, "premium": False}
        if not is_premium:
            c.execute(
                "UPDATE users SET usage_today=usage_today+1,updated_at=? WHERE user_id=?",
                (now(), uid),
            )
            remaining = max(0, FREE_DAILY_LIMIT - used - 1)
        else:
            remaining = 999
        c.execute(
            "INSERT INTO usage_logs(user_id,used_at,module,mode,premium_used) VALUES(?,?,?,?,?)",
            (uid, now(), module, mode, 1 if is_premium else 0),
        )
        c.commit()
        return {"allowed": True, "remaining": remaining, "premium": is_premium}
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


class TelegramAuth(BaseModel): initData:str=""; user_id:Optional[str]=None
class Usage(BaseModel): user_id:str
class Analyze(BaseModel): user_id:str; mode:str="coquetear"; module:str="chat"; image:str=""
class Generate(BaseModel): user_id:str; mode:str="coquetear"; module:str="chat"; text:str=""; analysis_id:str=""; image:str=""; idempotency_key:str=""
class Retry(BaseModel): analysis_id:str; text:str=""
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
class AdminCreate(BaseModel): username:str; password:str; permissions:list[str]=[]
class AdminStatus(BaseModel): username:str; is_active:bool=True
class PremiumChange(BaseModel): user_id:str; action:str; days:int=7
class PaymentReview(BaseModel): operation_id:str; action:str; reason:str=""
class Proof(BaseModel): operation_id:str; user_id:str; proof_text:str=""; proof_image:str=""
class SaveSituation(BaseModel): user_id:str; ocr_text:str=""; reply:str=""
class OCR(BaseModel): image:str


def parse_init(s: str) -> dict:
    """Parse Telegram initData while rejecting malformed and duplicate parameters."""
    if not isinstance(s, str) or not s or len(s) > 16_384:
        raise ValueError("initData vacío o demasiado grande")
    try:
        pairs = parse_qsl(s, keep_blank_values=True, strict_parsing=True, max_num_fields=100)
    except (ValueError, UnicodeError):
        raise ValueError("initData malformado")
    parsed = {}
    for key, value in pairs:
        if not key:
            raise ValueError("Parámetro de Telegram vacío")
        if key in parsed:
            raise ValueError("Parámetros de Telegram duplicados")
        parsed[key] = value
    return parsed


def verify_init(s: str) -> dict:
    if not s:
        raise ValueError("initData vacío")
    p = parse_init(s)
    received = p.pop("hash", "")
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN no configurado")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", received):
        raise ValueError("Hash de Telegram ausente o inválido")
    raw_auth_date = p.get("auth_date", "")
    if not raw_auth_date or not raw_auth_date.isascii() or not raw_auth_date.isdigit():
        raise ValueError("auth_date inválido")
    auth_date = int(raw_auth_date)
    current_time = int(time.time())
    if auth_date > current_time + 60:
        raise ValueError("auth_date está en el futuro")
    if current_time - auth_date > 86400:
        raise ValueError("Sesión de Telegram expirada")
    check = "\n".join(f"{k}={p[k]}" for k in sorted(p))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received.lower()):
        raise ValueError("Hash de Telegram inválido")
    raw_user = p.get("user")
    if not raw_user:
        raise ValueError("Usuario Telegram ausente")
    try:
        user_data = json.loads(raw_user)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("Datos del usuario Telegram inválidos")
    if not isinstance(user_data, dict):
        raise ValueError("Los datos del usuario Telegram deben ser un objeto")
    user_id = user_data.get("id")
    if (isinstance(user_id, bool) or not isinstance(user_id, (int, str))
            or not str(user_id).strip().isascii() or not str(user_id).strip().isdigit()
            or int(user_id) <= 0):
        raise ValueError("Identificador del usuario Telegram inválido")
    return user_data

def admin_identity(request: Request):
    if not ADMIN_KEY:
        raise HTTPException(503, "ADMIN_KEY no configurado en Railway")
    # The master key is accepted only by /api/admin/login. All subsequent
    # administrative requests must use a short-lived signed session token.
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
        session_id = str(data.get("jti", ""))
        if not session_id:
            raise HTTPException(401, "Sesión administrativa antigua; inicia sesión nuevamente")
        session_db = db()
        active_session = session_db.execute(
            "SELECT username, expires_at, revoked_at FROM admin_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        session_db.close()
        if (not active_session or active_session["revoked_at"] is not None
                or int(active_session["expires_at"]) < int(time.time())):
            raise HTTPException(401, "Sesión administrativa cerrada o expirada")
        username = str(data.get("username", ""))
        if active_session["username"] != username:
            raise HTTPException(401, "Sesión administrativa inválida")
        if username == "owner" and data.get("role") == "owner":
            return {"username": "owner", "is_owner": True, "permissions": ["users", "premium", "payments", "stats", "admins", "settings", "audit", "ai_analytics"]}
        c = db()
        row = c.execute("SELECT * FROM admin_users WHERE username=? AND is_active=1", (username,)).fetchone()
        c.close()
        if not row:
            raise HTTPException(401, "Administrador desactivado")
        return {"username": row["username"], "is_owner": False, "permissions": json.loads(row["permissions"])}
    except HTTPException: raise
    except Exception: raise HTTPException(401, "Sesión administrativa inválida")

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


@app.get("/")
def root(): return FileResponse(os.path.join(ROOT,"index.html"))
@app.get("/liggacuba-logo.jpg")
def liggacuba_logo():
    return FileResponse(
        os.path.join(ROOT, "liggacuba-logo.jpg"),
        media_type="image/jpeg"
    )

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
@app.get("/privacy.html")
def privacy(): return FileResponse(os.path.join(ROOT,"privacy.html"),media_type="text/html")
@app.get("/terms.html")
def terms(): return FileResponse(os.path.join(ROOT,"terms.html"),media_type="text/html")
@app.get("/health")
def health(): return {"status":"ok","service":"LiggaCuba","version":"2.2"}


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

def _validate_image_data_url(data_url: str) -> bytes:
    """Strictly validate data URL, MIME, decoded size, format, dimensions and file integrity."""
    import warnings
    from PIL import ImageFile

    header, separator, encoded = (data_url or "").partition(",")
    if (not separator or not header.lower().startswith("data:image/")
            or ";base64" not in header.lower() or not encoded
            or len(encoded) > 11_200_000):
        raise HTTPException(400, "Imagen inválida o demasiado grande")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if not raw or len(raw) > MAX_OCR_BYTES:
            raise ValueError("size")
        declared = header[5:].split(";", 1)[0].strip().lower()
        aliases = {"image/jpg": "image/jpeg", "image/x-png": "image/png"}
        declared = aliases.get(declared, declared)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                actual = (Image.MIME.get(image.format) or "").lower()
                width, height = image.size
                if (aliases.get(actual, actual) != declared or image.format not in {"PNG", "JPEG", "WEBP", "BMP", "TIFF"}
                        or width < 1 or height < 1 or width * height > MAX_OCR_PIXELS):
                    raise ValueError("format/dimensions")
                image.verify()
            # Reopen and fully decode; verify() alone may not detect every truncated stream.
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
    except HTTPException:
        raise
    except (ValueError, TypeError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(400, "Imagen inválida o dañada") from None
    return raw


def _ai_model_for(provider: str) -> str:
    env_names = {"gemini": "GEMINI_MODEL", "groq": "GROQ_MODEL", "openrouter": "OPENROUTER_MODEL", "cohere": "COHERE_MODEL"}
    defaults = {"gemini": "gemini-3.8-flash", "groq": "openai/gpt-oss-120b", "openrouter": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "cohere": "command-r7b-12-2024"}
    return os.getenv(env_names.get(provider, ""), defaults.get(provider, "desconocido"))


def _generate_with_ocr_fallback(text: str, mode: str, module: str, image_data_url: Optional[str], timings: Optional[dict] = None):
    """Generate visually first and time OCR/text fallback separately when needed."""
    timings = timings if timings is not None else {}
    visual_started = time.monotonic()
    try:
        result = ai_generate_reply(text, mode, module, image_data_url)
        timings["visual_generation_ms"] = int((time.monotonic() - visual_started) * 1000) if image_data_url else 0
        timings["ocr_ms"] = 0
        timings["alternative_generation_ms"] = 0
        return result, ""
    except ProviderError as vision_error:
        timings["visual_generation_ms"] = int((time.monotonic() - visual_started) * 1000) if image_data_url else 0
        if not image_data_url:
            raise
        ocr_started = time.monotonic()
        try:
            _, separator, encoded = image_data_url.partition(",")
            if not separator:
                raise ValueError("Imagen inválida")
            image_bytes = base64.b64decode(encoded, validate=True)
            recognized_text = _ocr_text(_decode_ocr_image(image_bytes))
        except Exception:
            timings["ocr_ms"] = int((time.monotonic() - ocr_started) * 1000)
            # Preserve the original vision-provider failure if local OCR cannot run.
            raise vision_error

        timings["ocr_ms"] = int((time.monotonic() - ocr_started) * 1000)
        recognized_text = re.sub(r"\s+", " ", recognized_text or "").strip()[:12000]
        if not recognized_text:
            timings["alternative_generation_ms"] = 0
            raise HTTPException(
                422,
                "La IA visual no está disponible y el OCR no pudo leer texto. Usa una captura más clara.",
            ) from vision_error

        fallback_text = " ".join(part for part in (text.strip(), recognized_text) if part)
        fallback_started = time.monotonic()
        try:
            return ai_generate_reply(fallback_text, mode, module, None), recognized_text
        finally:
            timings["alternative_generation_ms"] = int((time.monotonic() - fallback_started) * 1000)


def _quality_estimate(reply: str, alternative: str, context: str, mode: str) -> int:
    """Heuristic diagnostic only; it is not a semantic quality guarantee."""
    a, b = reply.strip(), alternative.strip()
    score = 45
    if len(a) >= 12: score += 10
    if len(b) >= 12: score += 10
    if len(a) >= 25 and len(b) >= 25: score += 5
    if a.casefold() != b.casefold(): score += 10
    if len(set(a.casefold().split()) & set(b.casefold().split())) / max(1, len(set(a.casefold().split()) | set(b.casefold().split()))) < 0.8: score += 8
    if context.strip(): score += 5
    if mode in {"gracioso", "coquetear", "enamorar", "provocativo", "salvar"}: score += 5
    return max(1, min(100, score))


def _record_ai_event(analysis_id, user_id, module, mode, provider, model, status, error_code, latency_ms, quality_score, retry_number):
    # Store operational metadata only: never prompts, OCR, images, replies, API keys or raw provider errors.
    c = None
    try:
        c = db()
        c.execute("""INSERT INTO ai_generation_events
        (analysis_id,user_id,module,mode,provider,model,status,error_code,latency_ms,quality_score,retry_number,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (analysis_id, str(user_id), module, mode, (provider or "unknown")[:40], (model or "unknown")[:120],
         status, (error_code or "")[:80], max(0, int(latency_ms)), quality_score, int(retry_number), now()))
        c.commit()
    except Exception as exc:
        # Observability is best-effort: database logging outages must not hide a valid AI response.
        import logging
        logging.getLogger(__name__).error("AI event logging failed (type=%s)", type(exc).__name__)
    finally:
        if c is not None:
            try: c.close()
            except Exception: pass


@app.post("/api/analyze")
def analyze(p:Analyze, request:Request):
    uid=current_user(request)
    module=p.module if p.module in {"chat","story"} else "chat"; mode=p.mode.lower().strip(); free=FREE_CHAT_MODES if module=="chat" else FREE_STORY_MODES; premset=PREMIUM_CHAT_MODES if module=="chat" else PREMIUM_STORY_MODES
    if mode not in free|premset: raise HTTPException(400,"Modo no válido")
    if mode in premset and not premium(uid): raise HTTPException(402,"Este modo requiere Premium")
    if p.image:
        _validate_image_data_url(p.image)
    r=consume(uid,module,mode)
    if not r["allowed"]: raise HTTPException(403,"Has alcanzado tus 3 análisis gratuitos de hoy")
    analysis_id=uuid.uuid4().hex
    c=db()
    try:
        c.execute("INSERT INTO analysis_attempts(id,user_id,analysis_date,module,mode,retry_used,quota_charged,created_at) VALUES(?,?,?,?,?,0,?,?)",
                  (analysis_id,uid,today(),module,mode,0 if r.get("premium") else 1,now()))
        c.commit()
    except Exception:
        c.rollback()
        if not r.get("premium"):
            refund = db()
            try:
                refund.execute("UPDATE users SET usage_today=MAX(0,usage_today-1),updated_at=? WHERE user_id=? AND last_reset_date=?", (now(), uid, today()))
                refund.commit()
            finally:
                refund.close()
        raise HTTPException(503, "No se pudo guardar el análisis. No se consumió el cupo si el reembolso terminó correctamente.") from None
    finally:
        c.close()
    return {**r,"analysis_id":analysis_id}

@app.post("/api/analyze/release")
def release_analysis_quota(p: Retry, request: Request):
    """Release quota when the client never got a generation started/completed."""
    uid = current_user(request)
    c = db()
    try:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM analysis_attempts WHERE id=? AND user_id=?", (p.analysis_id, uid)).fetchone()
        if row is None:
            raise HTTPException(404, "No se encontró este análisis")
        if row["analysis_date"] != today():
            raise HTTPException(403, "Este análisis ya no está disponible")
        if int(row["generation_in_progress"] or 0):
            started = row["generation_started_at"]
            try: stale = started and (_utc_datetime() - _utc_datetime(started)).total_seconds() > 180
            except (TypeError, ValueError): stale = False
            if not stale:
                c.rollback()
                return {"success": True, "released": False, "reason": "generation_in_progress"}
            c.execute("UPDATE analysis_attempts SET generation_in_progress=0,generation_started_at=NULL WHERE id=? AND user_id=?", (p.analysis_id, uid))
        if int(row["generation_count"] or 0) > 0 or not int(row["quota_charged"] or 0):
            c.rollback()
            return {"success": True, "released": False}
        c.execute("UPDATE users SET usage_today=MAX(0,usage_today-1),updated_at=? WHERE user_id=? AND last_reset_date=?", (now(), uid, today()))
        c.execute("UPDATE analysis_attempts SET quota_charged=0 WHERE id=? AND user_id=? AND generation_count=0", (p.analysis_id, uid))
        c.commit()
        return {"success": True, "released": True}
    except HTTPException:
        c.rollback()
        raise
    except Exception:
        c.rollback()
        raise HTTPException(503, "No se pudo liberar el cupo temporalmente") from None
    finally:
        c.close()


@app.post("/api/retry")
def retry_analysis(p: Retry, request: Request):
    uid=current_user(request)
    c=db()
    try:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT * FROM analysis_attempts WHERE id=? AND user_id=?",(p.analysis_id,uid)).fetchone()
        if row is None: raise HTTPException(404,"No se encontró este análisis")
        if row["analysis_date"] != today(): raise HTTPException(403,"El reintento de este análisis ya no está disponible")
        if row["retry_used"]: raise HTTPException(409,"Este análisis ya utilizó su único reintento")
        updated=c.execute("UPDATE analysis_attempts SET retry_used=1 WHERE id=? AND user_id=? AND retry_used=0 AND generation_in_progress=0",(p.analysis_id,uid))
        if updated.rowcount != 1: raise HTTPException(409,"Este análisis ya utilizó su único reintento o tiene una generación en curso")
        c.commit()
        return {"success":True,"retry_used":True,"analysis_id":p.analysis_id,"module":row["module"],"mode":row["mode"]}
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

@app.post("/api/retry/release")
def release_retry(p: Retry, request: Request):
    """Compatibility endpoint: a reserved retry is never refunded/reopened."""
    uid = current_user(request)
    c = db()
    try:
        row = c.execute(
            "SELECT id FROM analysis_attempts WHERE id=? AND user_id=?",
            (p.analysis_id, uid),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "No se encontró este análisis")
        return {"success": True, "released": False, "retry_available": False, "analysis_id": p.analysis_id}
    finally:
        c.close()

@app.post("/api/generate-reply")
def generate(p:Generate, request:Request):
    uid=current_user(request)
    module=p.module if p.module in {"chat","story"} else "chat"
    mode=p.mode.lower().strip()
    if not p.analysis_id:
        raise HTTPException(400,"Falta el identificador del análisis")
    free=FREE_CHAT_MODES if module=="chat" else FREE_STORY_MODES
    premset=PREMIUM_CHAT_MODES if module=="chat" else PREMIUM_STORY_MODES
    if mode not in free|premset:
        raise HTTPException(400,"Modo no válido")
    if mode in premset and not premium(uid):
        raise HTTPException(402,"Este modo requiere Premium")

    t=re.sub(r"\s+"," ",(p.text or "")).strip()
    image_data_url=(p.image or "").strip()
    if image_data_url:
        _validate_image_data_url(image_data_url)
    if not t and not image_data_url:
        raise HTTPException(400,"Adjunta una imagen o proporciona el texto que quieres analizar")

    # Persist idempotency by user + client key. A lost HTTP response can then be replayed
    # without spending a second provider call. The key never stores message/image content.
    idem_key = (p.idempotency_key or "").strip()[:128]
    if not idem_key:
        idem_key = uuid.uuid4().hex
    payload_hash = hashlib.sha256(json.dumps({
        "analysis_id": p.analysis_id, "module": module, "mode": mode,
        "text": t, "image_sha256": hashlib.sha256(image_data_url.encode()).hexdigest() if image_data_url else ""
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    # Reserve one generation atomically. The count is incremented only after a valid AI response.
    c=db()
    try:
        c.execute("BEGIN IMMEDIATE")
        # Idempotency results may contain generated reply text; retain them for at most 24 hours.
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        c.execute("DELETE FROM ai_idempotency WHERE created_at < ?", (cutoff,))
        prior = c.execute("SELECT payload_hash,status,result_json,updated_at FROM ai_idempotency WHERE user_id=? AND idempotency_key=?", (uid, idem_key)).fetchone()
        if prior and prior["payload_hash"] != payload_hash:
            raise HTTPException(409, "La clave de idempotencia ya se utilizó con otra solicitud")
        if prior and prior["status"] == "completed" and prior["result_json"]:
            c.commit()
            return json.loads(prior["result_json"])
        if prior and prior["status"] == "processing":
            try: stale_idempotency = (_utc_datetime() - _utc_datetime(prior["updated_at"])).total_seconds() > 180
            except (TypeError, ValueError): stale_idempotency = False
            if not stale_idempotency:
                raise HTTPException(409, "Esta solicitud ya se está procesando")
        if prior:
            c.execute("UPDATE ai_idempotency SET status='processing',result_json=NULL,updated_at=? WHERE user_id=? AND idempotency_key=?", (now(), uid, idem_key))
        else:
            c.execute("INSERT INTO ai_idempotency(user_id,idempotency_key,payload_hash,status,created_at,updated_at) VALUES(?,?,?,'processing',?,?)", (uid, idem_key, payload_hash, now(), now()))
        attempt=c.execute("SELECT * FROM analysis_attempts WHERE id=? AND user_id=?",(p.analysis_id,uid)).fetchone()
        if attempt is None: raise HTTPException(404,"No se encontró este análisis")
        if int(attempt["generation_in_progress"] or 0):
            started = attempt["generation_started_at"]
            try: stale = started and (_utc_datetime() - _utc_datetime(started)).total_seconds() > 180
            except (TypeError, ValueError): stale = False
            if stale:
                c.execute("UPDATE analysis_attempts SET generation_in_progress=0,generation_started_at=NULL WHERE id=? AND user_id=?", (p.analysis_id, uid))
                attempt = c.execute("SELECT * FROM analysis_attempts WHERE id=? AND user_id=?", (p.analysis_id, uid)).fetchone()
        if attempt["analysis_date"] != today(): raise HTTPException(403,"Este análisis ya no está disponible")
        if attempt["module"] != module or attempt["mode"] != mode: raise HTTPException(400,"El modo no coincide con el análisis original")
        count=int(attempt["generation_count"] or 0)
        # A retry is a single provider-generation attempt, even if that attempt fails.
        # The DB reservation is atomic, so concurrent requests cannot spend it twice.
        if int(attempt["retry_used"] or 0) and count >= 1:
            if int(attempt["retry_call_started"] or 0):
                raise HTTPException(409, "Este análisis ya utilizó su único intento de regeneración")
            retry_lock = c.execute("UPDATE analysis_attempts SET retry_call_started=1 WHERE id=? AND user_id=? AND retry_call_started=0", (p.analysis_id, uid))
            if retry_lock.rowcount != 1:
                raise HTTPException(409, "Este análisis ya utilizó su único intento de regeneración")
        if count == 0 and not int(attempt["quota_charged"] or 0):
            quota_user = c.execute("SELECT usage_today,last_reset_date,premium_until FROM users WHERE user_id=?", (uid,)).fetchone()
            is_premium_now = bool(quota_user and quota_user["premium_until"] and _utc_datetime() < _utc_datetime(quota_user["premium_until"]))
            if not is_premium_now:
                used_now = int(quota_user["usage_today"] or 0) if quota_user and quota_user["last_reset_date"] == today() else 0
                if used_now >= FREE_DAILY_LIMIT:
                    raise HTTPException(403, "Has alcanzado tus 3 análisis gratuitos de hoy")
                c.execute("UPDATE users SET usage_today=?,last_reset_date=?,updated_at=? WHERE user_id=?", (used_now + 1, today(), now(), uid))
                c.execute("UPDATE analysis_attempts SET quota_charged=1 WHERE id=? AND user_id=?", (p.analysis_id, uid))
                attempt = c.execute("SELECT * FROM analysis_attempts WHERE id=? AND user_id=?", (p.analysis_id, uid)).fetchone()
        if count >= 1 and not attempt["retry_used"]: raise HTTPException(409,"Debes usar el reintento disponible para generar otra respuesta")
        if count >= 2: raise HTTPException(409,"Este análisis ya utilizó su único reintento")
        if int(attempt["generation_in_progress"] or 0): raise HTTPException(409,"Ya hay una generación en curso para este análisis")
        updated=c.execute("UPDATE analysis_attempts SET generation_in_progress=1,generation_started_at=? WHERE id=? AND user_id=? AND generation_in_progress=0",(now(),p.analysis_id,uid))
        if updated.rowcount != 1: raise HTTPException(409,"Ya hay una generación en curso para este análisis")
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

    generation_started = time.monotonic()
    timing_details = {"visual_generation_ms": 0, "retry_count": 0, "retry_wait_ms": 0, "retry_call_ms": 0,
                      "provider_attempts": [], "ocr_ms": 0, "alternative_generation_ms": 0}
    provider = "unknown"
    model = "unknown"
    retry_number = 1 if int(attempt["retry_used"] or 0) else 0
    ocr_fallback_text = ""
    try:
        # One monotonic budget covers visual inference, OCR and textual fallback.
        with collect_timings(timing_details), provider_deadline(12.0):
            ai_reply, ocr_fallback_text = _generate_with_ocr_fallback(t, mode, module, image_data_url or None, timing_details)
        if isinstance(ai_reply,dict):
            reply=ai_reply.get("reply")
            alternative=ai_reply.get("alternative")
            provider=str(ai_reply.get("provider") or "desconocido")
            model=_ai_model_for(provider)
            if not isinstance(reply,str) or not reply.strip():
                raise HTTPException(502,"El proveedor de IA no devolvió una respuesta válida. Puedes reintentar.")
            alt=alternative.strip()[:1200] if isinstance(alternative,str) and alternative.strip() else ""
            if not alt or alt.casefold()==reply.strip().casefold():
                raise HTTPException(502,"La IA no generó dos respuestas diferentes. Puedes reintentar.")
            quality_score = _quality_estimate(reply.strip(), alt, t or ocr_fallback_text, mode)
            result={"success":True,"reply":reply.strip()[:1200],"alternative":alt,"provider":provider,"model":model,"quality_score":quality_score,"ocr_fallback":bool(ocr_fallback_text),"ocr_text":ocr_fallback_text,"timings_ms":timing_details}
        elif isinstance(ai_reply,str) and ai_reply.strip():
            raise HTTPException(502,"El proveedor no devolvió dos respuestas estructuradas y diferentes. Puedes reintentar.")
        else:
            raise HTTPException(503,"La IA no está disponible en este momento. Puedes reintentar.")
    except HTTPException as exc:
        _record_ai_event(p.analysis_id, uid, module, mode, provider, model, "error",
                         f"http_{exc.status_code}", int((time.monotonic()-generation_started)*1000), None, retry_number)
        raise
    except Exception as exc:
        import logging
        # Avoid logging exception messages or tracebacks that may contain provider payloads.
        logging.getLogger(__name__).error("Error generando respuesta con IA (tipo=%s)", type(exc).__name__)
        failures = getattr(exc, "provider_failures", None)
        elapsed = int((time.monotonic()-generation_started)*1000)
        if failures:
            for failure in failures:
                failed_provider = str(failure.get("provider") or "unknown")
                _record_ai_event(p.analysis_id, uid, module, mode, failed_provider,
                                 _ai_model_for(failed_provider), "error",
                                 str(failure.get("error_code") or type(exc).__name__),
                                 int(failure.get("latency_ms") or elapsed), None, retry_number)
        else:
            _record_ai_event(p.analysis_id, uid, module, mode, provider, model, "error",
                             type(exc).__name__, elapsed, None, retry_number)
        raise HTTPException(503,"No se pudo generar la respuesta con la IA. Comprueba la configuración del proveedor e inténtalo de nuevo.") from exc
    finally:
        # Always release the in-flight lock. Failed generations do not consume a generation.
        c=db()
        try:
            c.execute("BEGIN IMMEDIATE")
            if 'result' in locals():
                # Finalize timings before the existing idempotency transaction so
                # telemetry cannot introduce a second critical database write.
                timing_details["total_backend_ms"] = int((time.monotonic() - generation_started) * 1000)
                result["timings_ms"] = timing_details
                c.execute("UPDATE analysis_attempts SET generation_count=generation_count+1,generation_in_progress=0,generation_started_at=NULL WHERE id=? AND user_id=?",(p.analysis_id,uid))
                c.execute("UPDATE ai_idempotency SET status='completed',result_json=?,updated_at=? WHERE user_id=? AND idempotency_key=?", (json.dumps(result, ensure_ascii=False, separators=(",", ":")), now(), uid, idem_key))
            else:
                c.execute("UPDATE analysis_attempts SET generation_in_progress=0,generation_started_at=NULL WHERE id=? AND user_id=?",(p.analysis_id,uid))
                c.execute("UPDATE ai_idempotency SET status='failed',updated_at=? WHERE user_id=? AND idempotency_key=?", (now(), uid, idem_key))
                # A provider failure on the first attempt refunds the free analysis quota.
                # Failed retries do not refund the original successful analysis.
                if retry_number == 0 and int(attempt["generation_count"] or 0) == 0 and int(attempt["quota_charged"] or 0):
                    c.execute("UPDATE users SET usage_today=MAX(0,usage_today-1),updated_at=? WHERE user_id=? AND last_reset_date=?", (now(), uid, today()))
                    c.execute("UPDATE analysis_attempts SET quota_charged=0 WHERE id=? AND user_id=?", (p.analysis_id, uid))
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()
    _record_ai_event(p.analysis_id, uid, module, mode, result.get("provider"), result.get("model"), "success", "",
                     int((time.monotonic()-generation_started)*1000), result.get("quality_score"), retry_number)
    # Telemetry is best-effort: it must never turn a successful generation into an error.
    try:
        import logging
        logging.getLogger(__name__).info(
            "AI generation timing: %s",
            json.dumps(timing_details, separators=(",", ":"), sort_keys=True),
        )
    except Exception:
        pass
    return result


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

@app.post("/api/payment-phone")
def payment_phone(p: PaymentPhone, request: Request):
    uid = current_user(request)
    phone = normalize_payment_phone(p.phone or "")
    if len(phone) < 8 or len(phone) > 15:
        raise HTTPException(400, "Número de teléfono inválido")
    user(uid, {"payment_phone": phone})
    return {"success": True, "payment_phone": phone}


def normalize_payment_phone(value: str) -> str:
    """Normalize Cuban mobile numbers with or without the +53 country prefix."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 10 and digits.startswith("53"):
        return digits[2:]
    return digits


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
    admin(request,"payments"); c=db(); rows=c.execute("SELECT * FROM payment_operations ORDER BY created_at DESC LIMIT 100").fetchall(); c.close(); return {"items":[dict(r) for r in rows]}

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
