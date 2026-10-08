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


def consume(uid,module,mode):
    reset(uid); prem=premium(uid); c=db();
    if not prem:
        u=user(uid); used=int(u.get("usage_today") or 0)
        if used >= FREE_DAILY_LIMIT: c.close(); return {"allowed":False,"remaining":0,"premium":False}
        c.execute("UPDATE users SET usage_today=usage_today+1,updated_at=? WHERE user_id=?",(now(),uid)); remaining=FREE_DAILY_LIMIT-used-1
    else: remaining=999
    c.execute("INSERT INTO usage_logs(user_id,used_at,module,mode,premium_used) VALUES(?,?,?,?,?)",(uid,now(),module,mode,1 if prem else 0)); c.commit(); c.close()
    return {"allowed":True,"remaining":remaining,"premium":prem}


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


def admin(request:Request):
    if not ADMIN_KEY: raise HTTPException(503,"ADMIN_KEY no configurado en Railway")
    if not hmac.compare_digest(request.headers.get("x-admin-key", ""), ADMIN_KEY): raise HTTPException(401,"No autorizado")


def amount(plan,lang):
    if lang=="en": return "8.99 USD" if plan=="weekly" else "29.99 USD"
    return "2500 CUP" if plan=="weekly" else "15500 CUP"


@app.get("/")
def root(): return FileResponse(os.path.join(ROOT,"index.html"))
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

@app.post("/ocr")
async def ocr_upload(request: Request):
    data=await request.body()
    if not data: raise HTTPException(400,"Imagen vacía")
    try:
        img=Image.open(io.BytesIO(data)); img.load()
        return {"ok":True,"text":_ocr_text(img)}
    except Exception as e:
        raise HTTPException(400,f"OCR error: {e}")

@app.post("/ocr-base64")
def ocr_base64(p:OCR):
    try:
        raw=base64.b64decode(p.image.split(",",1)[-1],validate=True)
        img=Image.open(io.BytesIO(raw)); img.load()
        return {"success":True,"text":_ocr_text(img)}
    except Exception as e:
        raise HTTPException(400,f"OCR inválido: {e}")

@app.post("/ocr-base64-simple")
def ocr_simple(p:OCR): return ocr_base64(p)


@app.post("/api/profile")
def profile(p:Usage, request:Request):
    uid=current_user(request)
    u=user(uid); c=db(); rows=c.execute("SELECT module,COUNT(*) n FROM usage_logs WHERE user_id=? GROUP BY module",(uid,)).fetchall(); c.close(); counts={r["module"]:r["n"] for r in rows}
    return {"user_id":uid,"username":u.get("username"),"first_name":u.get("first_name"),"premium":premium(uid),"premium_until":u.get("premium_until"),"chats":counts.get("chat",0),"stories":counts.get("story",0),"analyses":sum(counts.values())}

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
def payment_phone(p:PaymentPhone, request:Request):
    uid=current_user(request)
    phone=re.sub(r"\D","",p.phone or "")
    if len(phone) < 8 or len(phone) > 15:
        raise HTTPException(400,"Número de teléfono inválido")
    user(uid, {"payment_phone": phone})
    return {"success":True,"payment_phone":phone}


@app.post("/api/atajo-pago")
def atajo_pago(p:AtajoPayment, request:Request):
    key=request.headers.get("x-atajo-key","")
    if not ATAJO_KEY or not hmac.compare_digest(key, ATAJO_KEY):
        raise HTTPException(401,"Atajo no autorizado")

    method=(p.metodo_pago or "").strip().upper()
    if method not in {"BANDEC","BPA","SALDO_MOVIL"}:
        raise HTTPException(400,"Método de pago inválido")

    phone=re.sub(r"\D","",p.telefono_origen or "")
    amount_value=round(float(p.monto_recibido or 0),2)
    transaction=(p.transaccion or "").strip().upper()
    sms=(p.sms or "").strip()
    destination=re.sub(r"\D","",p.cuenta_destino or "")

    if amount_value <= 0 or not phone or not sms:

        raise HTTPException(400,"Datos de transferencia incompletos")

    if method=="BANDEC":

        expected=re.sub(r"\D","",BANDEC_ACCOUNT)

    elif method=="BPA":

        expected=re.sub(r"\D","",BPA_ACCOUNT)

        if not expected:

            raise HTTPException(503,"Cuenta BPA no configurada")

    else:

        expected=""

    if method in {"BANDEC","BPA"}:

        if not destination or destination != expected:

            raise HTTPException(409,"Cuenta destino no coincide")

        if not transaction:

            raise HTTPException(400,"Número de transacción requerido")

    fingerprint=hashlib.sha256(sms.encode("utf-8")).hexdigest()

    c=db()

    duplicate=c.execute(

        "SELECT operation_id,status FROM payment_operations WHERE transaction_id=? OR source_sms=? LIMIT 1",

        (transaction,fingerprint)

    ).fetchone() if transaction else c.execute(

        "SELECT operation_id,status FROM payment_operations WHERE source_sms=? LIMIT 1",

        (fingerprint,)

    ).fetchone()

    if duplicate:

        c.close()

        return {"success":False,"status":"duplicate","operation_id":duplicate["operation_id"]}

    rows=c.execute(

        "SELECT * FROM payment_operations WHERE status='pending' AND payment_method=? ORDER BY created_at ASC",

        (method,)

    ).fetchall()

    matched=None

    for row in rows:

        expected_amount=float(re.sub(r"[^0-9.]","",row["amount"] or "0") or 0)

        if round(expected_amount,2) != amount_value:

            continue

        registered=re.sub(r"\D","",user(row["user_id"]).get("payment_phone") or "")

        if registered and registered != phone:

            continue

        matched=row

        break

    if not matched:

        c.close()

        return {"success":False,"status":"unmatched"}

    t=now()

    c.execute(

        """UPDATE payment_operations

           SET status='verified', payer_phone=?, destination_account=?,

               transaction_id=?, transfer_date=?, source_sms=?,

               verified_at=?, updated_at=?

           WHERE operation_id=? AND status='pending'""",

        (phone,destination,transaction,p.fecha or p.fecha_ejecucion or "",

         fingerprint,t,t,matched["operation_id"])

    )

    if c.execute("SELECT changes()").fetchone()[0] != 1:

        c.rollback()

        c.close()

        return {"success":False,"status":"already_processed"}

    days=7 if matched["plan"]=="weekly" else 365

    current=user(matched["user_id"]).get("premium_until")

    base=datetime.utcnow()

    if current:

        try:

            base=max(base,datetime.fromisoformat(current))

        except ValueError:

            pass

    until=(base+timedelta(days=days)).isoformat()

    c.execute(

        "UPDATE users SET premium_until=?,updated_at=? WHERE user_id=?",

        (until,t,matched["user_id"])

    )

    c.commit()

    c.close()

    return {

        "success":True,

        "status":"verified",

        "operation_id":matched["operation_id"],

        "user_id":matched["user_id"],

        "premium_until":until

    }

@app.post("/api/payments/pending")

def pending(p:Pending, request:Request):
    uid=current_user(request)
    if p.plan not in {"weekly","annual"}: raise HTTPException(400,"Plan inválido")
    # Prevent duplicate active operations for the same user/plan.
    c=db(); existing=c.execute("SELECT * FROM payment_operations WHERE user_id=? AND plan=? AND status IN ('pending','proof_submitted') ORDER BY created_at DESC LIMIT 1",(uid,p.plan)).fetchone()
    if existing: c.close(); return {"success":True,"operation_id":existing["operation_id"],"status":existing["status"],"amount":existing["amount"]}
    method=(p.payment_method or "BANDEC").upper()
    if method not in {"BANDEC","BPA","SALDO_MOVIL"}: raise HTTPException(400,"Método de pago inválido")
    oid=uuid.uuid4().hex[:12].upper(); t=now(); a=amount(p.plan,p.language)
    destination={"BANDEC":BANDEC_ACCOUNT,"BPA":BPA_ACCOUNT,"SALDO_MOVIL":""}[method]
    phone=user(uid).get("payment_phone") or ""
    c.execute(
        """INSERT INTO payment_operations(
           operation_id,user_id,plan,language,status,amount,payment_method,
           payer_phone,destination_account,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (oid,uid,p.plan,p.language,"pending",a,method,phone,destination,t,t)
    )
    c.commit(); c.close()
    return {
        "success":True,
        "operation_id":oid,
        "status":"pending",
        "amount":a,
        "payment_method":method,
        "destination_account":destination,
        "payment_phone":phone
    }

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

@app.post("/api/admin/payments/verify")
def verify_payment(p:PaymentId, request:Request):
    admin(request); c=db(); row=c.execute("SELECT * FROM payment_operations WHERE operation_id=?",(p.operation_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404,"Operación no encontrada")
    if row["status"] not in {"pending","proof_submitted"}: c.close(); raise HTTPException(409,"Operación no verificable")
    days=7 if row["plan"]=="weekly" else 365; current=user(row["user_id"]).get("premium_until"); base=datetime.utcnow()
    if current:
        try: base=max(base,datetime.fromisoformat(current))
        except ValueError: pass
    until=(base+timedelta(days=days)).isoformat(); t=now(); c.execute("UPDATE users SET premium_until=?,updated_at=? WHERE user_id=?",(until,t,row["user_id"])); c.execute("UPDATE payment_operations SET status='verified',verified_at=?,updated_at=? WHERE operation_id=?",(t,t,p.operation_id)); c.commit(); c.close(); return {"success":True,"status":"verified","premium_until":until}

@app.get("/api/admin/stats")
def admin_stats(request:Request):
    admin(request); c=db(); out={"total_users":c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],"premium_users":c.execute("SELECT COUNT(*) n FROM users WHERE premium_until>?",(now(),)).fetchone()["n"],"today_usage":c.execute("SELECT COUNT(*) n FROM usage_logs WHERE used_at>=?",(today()+"T00:00:00",)).fetchone()["n"],"pending_payments":c.execute("SELECT COUNT(*) n FROM payment_operations WHERE status IN ('pending','proof_submitted')").fetchone()["n"]}; c.close(); return out

@app.get("/api/admin/payments")
def admin_payments(request:Request):
    admin(request); c=db(); rows=c.execute("SELECT * FROM payment_operations ORDER BY created_at DESC LIMIT 100").fetchall(); c.close(); return {"items":[dict(r) for r in rows]}
