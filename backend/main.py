from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from PIL import Image
import base64, hashlib, hmac, io, json, os, re, sqlite3, time, uuid
import pytesseract
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from urllib.parse import parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = FastAPI(title="LiggaCuba API", version="2.1")
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
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
ATAJO_KEY = os.getenv("ATAJO_KEY", "")
BANDEC_ACCOUNT = os.getenv("BANDEC_ACCOUNT", "9244069990684435")
BPA_ACCOUNT = os.getenv("BPA_ACCOUNT", "")
PAYMENT_PHONE = os.getenv("PAYMENT_PHONE", "52677163")
SESSION_TTL = 86400


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def session_token(uid: str) -> str:
    payload = _b64e(json.dumps({"uid": str(uid), "exp": int(time.time()) + SESSION_TTL}, separators=(",", ":")).encode())
    secret = hmac.new(b"LiggaCubaSession", BOT_TOKEN.encode(), hashlib.sha256).digest()
    sig = _b64e(hmac.new(secret, payload.encode(), hashlib.sha256).digest())
    return payload + "." + sig


def verify_session(token: str) -> str:
    if not token or "." not in token:
        raise HTTPException(401, "Sesión requerida")
    payload, sig = token.rsplit(".", 1)
    secret = hmac.new(b"LiggaCubaSession", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = _b64e(hmac.new(secret, payload.encode(), hashlib.sha256).digest())
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
    try: return datetime.utcnow() < datetime.fromisoformat(p)
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
            is_premium = bool(row["premium_until"] and datetime.utcnow() < datetime.fromisoformat(row["premium_until"]))
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
class Analyze(BaseModel): user_id:str; mode:str="coquetear"; module:str="chat"
class Generate(BaseModel): user_id:str; mode:str="coquetear"; module:str="chat"; text:str=""
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


def parse_init(s): return {k:v[0] for k,v in parse_qs(s,keep_blank_values=True).items() if v}

def verify_init(s):
    if not s: raise ValueError("initData vacío")
    p=parse_init(s); received=p.pop("hash","")
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN no configurado")
    if not received: raise ValueError("Falta hash de Telegram")
    try: auth_date=int(p.get("auth_date","0"))
    except ValueError: raise ValueError("auth_date inválido")
    if abs(time.time()-auth_date)>86400: raise ValueError("Sesión de Telegram expirada")
    check="\n".join(f"{k}={p[k]}" for k in sorted(p)); secret=hmac.new(b"WebAppData",BOT_TOKEN.encode(),hashlib.sha256).digest(); calc=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc,received): raise ValueError("Hash de Telegram inválido")
    u=json.loads(p.get("user","{}"));
    if not u: raise ValueError("Usuario Telegram ausente")
    return u


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
        username = str(data.get("username", ""))
        if username == "owner" and data.get("role") == "owner":
            return {"username": "owner", "permissions": ["users", "premium", "payments", "stats", "admins", "settings", "audit"]}
        c = db()
        row = c.execute("SELECT * FROM admin_users WHERE username=? AND is_active=1", (username,)).fetchone()
        c.close()
        if not row:
            raise HTTPException(401, "Administrador desactivado")
        return {"username": row["username"], "permissions": json.loads(row["permissions"])}
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
def health(): return {"status":"ok","service":"LiggaCuba","version":"2.1"}


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
def analyze(p:Analyze, request:Request):
    uid=current_user(request)
    module=p.module if p.module in {"chat","story"} else "chat"; mode=p.mode.lower().strip(); free=FREE_CHAT_MODES if module=="chat" else FREE_STORY_MODES; premset=PREMIUM_CHAT_MODES if module=="chat" else PREMIUM_STORY_MODES
    if mode not in free|premset: raise HTTPException(400,"Modo no válido")
    if mode in premset and not premium(uid): raise HTTPException(402,"Este modo requiere Premium")
    r=consume(uid,module,mode)
    if not r["allowed"]: raise HTTPException(403,"Has alcanzado tus 3 análisis gratuitos de hoy")
    return r

@app.post("/api/generate-reply")
def generate(p:Generate, request:Request):
    uid=current_user(request)
    module=p.module if p.module in {"chat","story"} else "chat"
    mode=p.mode.lower().strip()
    free=FREE_CHAT_MODES if module=="chat" else FREE_STORY_MODES
    premset=PREMIUM_CHAT_MODES if module=="chat" else PREMIUM_STORY_MODES

    if mode not in free|premset:
        raise HTTPException(400,"Modo no válido")
    if mode in premset and not premium(uid):
        raise HTTPException(402,"Este modo requiere Premium")

    t=re.sub(r"\s+"," ",(p.text or "")).strip()
    if not t:
        return {"success":False,"reply":"No pude detectar texto suficiente para generar una respuesta útil."}

    low=t.lower()
    premium_mode=mode in premset

    def contains(words):
        return any(w in low for w in words)

    if mode=="gracioso":
        if contains(["jaj","jaja","😂","🤣","lol"]):
            reply="Puedes seguirle el juego: “JAJA 😂 así empiezas y después no hay quien te aguante.”"
        elif "?" in t:
            reply="Puedes responder con humor: “Esa pregunta viene con trampa 😂 pero me gusta la curiosidad.”"
        else:
            reply="Puedes responder: “Jajaja, contigo uno nunca sabe qué esperar 😂.”"

    elif mode=="coquetear":
        if contains(["hola","hey","buenas"]):
            reply="Puedes responder: “Hola 😏 justo estaba pensando que hacía rato no sabía de ti. ¿Cómo estás?”"
        elif "?" in t:
            reply="Puedes responder: “Depende… ¿me lo preguntas porque tienes curiosidad o porque quieres conocer la respuesta? 😉”"
        else:
            reply="Puedes responder: “No sé si lo haces a propósito, pero tienes una forma de hablar que engancha 😉.”"

    elif mode=="enamorar":
        if contains(["hola","hey","buenas"]):
            reply="Puedes responder: “Qué bonito leerte. Espero que tu día esté yendo bien, porque ya me mejoraste un poquito el mío ❤️.”"
        elif "?" in t:
            reply="Puedes responder con cercanía: “Te respondería rápido, pero contigo prefiero pensarlo bien para decirte exactamente lo que siento ❤️.”"
        else:
            reply="Puedes responder: “Me gusta hablar contigo porque la conversación se siente diferente, de esas que uno quiere seguir un rato más ❤️.”"

    elif mode=="provocativo":
        if contains(["hola","hey","buenas"]):
            reply="Puedes responder: “Hola… aunque tengo la sensación de que contigo un simple hola puede terminar complicándose bastante 😏.”"
        elif "?" in t:
            reply="Puedes responder: “Podría darte una respuesta inocente… pero creo que los dos sabemos que sería demasiado aburrido 😏.”"
        else:
            reply="Puedes responder: “No sé si estás provocando o simplemente eres así, pero definitivamente conseguiste mi atención 😏.”"

    elif mode=="salvar":
        if "?" in t:
            reply="Para salir bien de la situación, puedes responder: “Creo que me expliqué mal 😅. Lo que realmente quería decir era que prefiero hablarlo tranquilamente contigo.”"
        elif contains(["perdón","perdon","enoj","molest","molesto","molesta","mal","problema"]):
            reply="Puedes bajar la tensión sin quedar mal: “No era mi intención que sonara así. Prefiero aclararlo contigo antes de que se malinterprete.”"
        else:
            reply="Puedes responder de forma segura: “Creo que esto se puede explicar mejor 😅. No quiero que se entienda algo que no quise decir.”"

    else:
        reply="Puedes responder de forma natural y mantener la conversación abierta."

    if premium_mode and mode!="salvar":
        reply += " Además, intenta cerrar con una pregunta relacionada con lo que la otra persona acaba de decir para mantener la conversación natural."

    return {"success":True,"reply":reply}



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
            try:
                txt = pytesseract.image_to_string(
                    variant,
                    lang="spa+eng",
                    config=f"--oem 3 --psm {psm}"
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
def ocr_base64(p: OCR):
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
def ocr_simple(p:OCR): return ocr_base64(p)


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
        base_time = datetime.utcnow()
        current = user_row["premium_until"] if user_row else None
        if current:
            try:
                base_time = max(base_time, datetime.fromisoformat(current))
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
    if not ADMIN_KEY: raise HTTPException(503,"ADMIN_KEY no configurado en Railway")
    username="owner"; permissions=["users","premium","payments","stats","admins","settings","audit"]
    if p.master_key and hmac.compare_digest(p.master_key, ADMIN_KEY):
        pass
    else:
        c=db(); row=c.execute("SELECT * FROM admin_users WHERE username=? AND is_active=1",(p.username.strip(),)).fetchone(); c.close()
        if not row:
            raise HTTPException(401,"Credenciales incorrectas")
        salt_hex, stored_hash = row["password_hash"].split(":", 1)
        calculated = hashlib.pbkdf2_hmac("sha256", p.password.encode(), bytes.fromhex(salt_hex), 180000).hex()
        if not hmac.compare_digest(stored_hash, calculated):
            raise HTTPException(401,"Credenciales incorrectas")
        username=row["username"]; permissions=json.loads(row["permissions"])
    claims={"username":username,"exp":int(time.time())+8*3600}
    if username=="owner": claims["role"]="owner"
    payload=_b64e(json.dumps(claims,separators=(",",":")).encode())
    token=payload+"."+_b64e(hmac.new(ADMIN_KEY.encode(),payload.encode(),hashlib.sha256).digest())
    return {"success":True,"token":token,"username":username,"permissions":permissions}

@app.get("/api/admin/me")
def admin_me(request:Request): return admin_identity(request)

@app.get("/api/admin/users")
def admin_users(request:Request, q:str=""):
    ident=admin(request,"users"); c=db(); term=f"%{q.strip()}%"
    rows=c.execute("SELECT user_id,username,first_name,last_name,premium_until,payment_phone,created_at FROM users WHERE user_id LIKE ? OR username LIKE ? OR first_name LIKE ? ORDER BY created_at DESC LIMIT 200",(term,term,term)).fetchall(); c.close()
    return {"items":[{**dict(r),"premium":bool(r["premium_until"] and r["premium_until"]>now())} for r in rows]}

@app.post("/api/admin/premium")
def admin_premium(p:PremiumChange, request:Request):
    ident=admin(request,"premium"); uid=str(p.user_id); u=user(uid); t=now()
    if p.action=="revoke": until=None
    elif p.action=="grant": until=(datetime.utcnow()+timedelta(days=max(1,min(int(p.days),3650)))).isoformat()
    elif p.action=="extend":
        base=datetime.utcnow()
        try:
            if u.get("premium_until"): base=max(base,datetime.fromisoformat(u["premium_until"]))
        except ValueError: pass
        until=(base+timedelta(days=max(1,min(int(p.days),3650)))).isoformat()
    else: raise HTTPException(400,"Acción inválida")
    c=db(); c.execute("UPDATE users SET premium_until=?,updated_at=? WHERE user_id=?",(until,t,uid)); c.commit(); c.close(); audit(ident["username"],"premium_"+p.action,uid,{"days":p.days,"premium_until":until}); return {"success":True,"user_id":uid,"premium_until":until,"premium":bool(until and until>now())}

@app.get("/api/admin/admins")
def admin_list(request:Request):
    admin(request,"admins"); c=db(); rows=c.execute("SELECT username,permissions,is_active,created_at FROM admin_users ORDER BY created_at DESC").fetchall(); c.close(); return {"items":[{**dict(r),"permissions":json.loads(r["permissions"])} for r in rows]}

@app.post("/api/admin/admins")
def admin_create(p:AdminCreate, request:Request):
    ident=admin(request,"admins"); username=re.sub(r"[^a-zA-Z0-9_.-]","",p.username.strip())
    if len(username)<3 or len(p.password)<10: raise HTTPException(400,"Usuario mínimo 3 caracteres y contraseña mínimo 10")
    allowed={"users","premium","payments","stats","audit"}; perms=sorted(set(p.permissions)&allowed)
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
        base=datetime.utcnow()
        if current:
            try: base=max(base,datetime.fromisoformat(current))
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
    admin(request,"stats"); c=db(); out={"total_users":c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],"premium_users":c.execute("SELECT COUNT(*) n FROM users WHERE premium_until>?",(now(),)).fetchone()["n"],"today_usage":c.execute("SELECT COUNT(*) n FROM usage_logs WHERE used_at>=?",(today()+"T00:00:00",)).fetchone()["n"],"pending_payments":c.execute("SELECT COUNT(*) n FROM payment_operations WHERE status IN ('pending','proof_submitted')").fetchone()["n"]}; c.close(); return out

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
