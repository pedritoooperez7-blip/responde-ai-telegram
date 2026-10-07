from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image
import base64
import hashlib
import hmac
import io
import json
import os
import re
import sqlite3
import time
import uuid
import pytesseract
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from urllib.parse import parse_qs

app = FastAPI(title="LiggaCuba OCR API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

FREE_DAILY_LIMIT = 3

FREE_CHAT_MODES = {"gracioso", "coquetear", "enamorar"}
PREMIUM_CHAT_MODES = {"provocativo"}
FREE_STORY_MODES = {"gracioso", "coquetear"}
PREMIUM_STORY_MODES = {"provocativo", "enamorar"}
DB_PATH = os.getenv("DB_PATH", "liggacuba.db")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            premium_until TEXT,
            created_at TEXT,
            updated_at TEXT,
            usage_today INTEGER DEFAULT 0,
            last_reset_date TEXT
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            used_at TEXT,
            mode TEXT,
            premium_used INTEGER DEFAULT 0
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_operations (
            operation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            plan TEXT NOT NULL,
            language TEXT NOT NULL,
            method TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            amount TEXT NOT NULL,
            payment_code TEXT,
            transaction_id TEXT,
            proof_note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            verified_at TEXT,
            cancelled_at TEXT
        )
        """
    )

    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_transaction
        ON payment_operations(transaction_id)
        WHERE transaction_id IS NOT NULL
        """
    )

    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_code
        ON payment_operations(payment_code)
        WHERE payment_code IS NOT NULL
        """
    )

    conn.commit()
    conn.close()


init_db()


def utcnow_iso() -> str:
    return datetime.utcnow().isoformat()


def today_iso() -> str:
    return datetime.utcnow().date().isoformat()


def get_or_create_user(user_id: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user_id = str(user_id or "guest-user")
    now = utcnow_iso()
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

    if row is None:
        conn.execute(
            """
            INSERT INTO users (
                user_id, username, first_name, last_name, premium_until,
                created_at, updated_at, usage_today, last_reset_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (user_id, None, None, None, None, now, now, today_iso()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

    if extra:
        update_fields = []
        update_values = []
        for key, value in extra.items():
            if value is not None:
                update_fields.append(f"{key} = ?")
                update_values.append(value)
        if update_fields:
            update_fields.append("updated_at = ?")
            update_values.extend([now, user_id])
            conn.execute(
                f"UPDATE users SET {', '.join(update_fields)} WHERE user_id = ?",
                tuple(update_values),
            )
            conn.commit()
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

    conn.close()
    return dict(row) if row else {"user_id": user_id}


def reset_if_needed(user_id: str) -> None:
    user = get_or_create_user(user_id)
    today = today_iso()
    if user.get("last_reset_date") != today:
        conn = get_db_connection()
        conn.execute(
            "UPDATE users SET usage_today = 0, last_reset_date = ?, updated_at = ? WHERE user_id = ?",
            (today, utcnow_iso(), user_id),
        )
        conn.commit()
        conn.close()


def is_premium_active(user_id: str) -> bool:
    user = get_or_create_user(user_id)
    if not user.get("premium_until"):
        return False
    try:
        return datetime.utcnow() < datetime.fromisoformat(user["premium_until"])
    except ValueError:
        return False


def can_use_analysis(user_id: str) -> Dict[str, Any]:
    reset_if_needed(user_id)
    user = get_or_create_user(user_id)

    if is_premium_active(user_id):
        return {
            "allowed": True,
            "remaining": 999,
            "used_today": int(user.get("usage_today") or 0),
            "premium": True,
            "message": "Premium activo",
        }

    remaining = max(0, FREE_DAILY_LIMIT - int(user.get("usage_today") or 0))
    return {
        "allowed": int(user.get("usage_today") or 0) < FREE_DAILY_LIMIT,
        "remaining": remaining,
        "used_today": int(user.get("usage_today") or 0),
        "premium": False,
        "message": "Límite gratuito alcanzado" if remaining == 0 else "Disponible",
    }


def consume_analysis(user_id: str, mode: str = "chat") -> Dict[str, Any]:
    reset_if_needed(user_id)
    user = get_or_create_user(user_id)

    if is_premium_active(user_id):
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO usage_logs (user_id, used_at, mode, premium_used) VALUES (?, ?, ?, 1)",
            (user_id, utcnow_iso(), mode),
        )
        conn.commit()
        conn.close()
        return {"allowed": True, "remaining": 999, "premium": True}

    used_today = int(user.get("usage_today") or 0)
    if used_today >= FREE_DAILY_LIMIT:
        return {"allowed": False, "remaining": 0, "premium": False}

    conn = get_db_connection()
    conn.execute(
        "UPDATE users SET usage_today = usage_today + 1, updated_at = ? WHERE user_id = ?",
        (utcnow_iso(), user_id),
    )
    conn.execute(
        "INSERT INTO usage_logs (user_id, used_at, mode, premium_used) VALUES (?, ?, ?, 0)",
        (user_id, utcnow_iso(), mode),
    )
    conn.commit()
    conn.close()

    remaining = max(0, FREE_DAILY_LIMIT - (used_today + 1))
    return {"allowed": True, "remaining": remaining, "premium": False}


class OCRBase64Request(BaseModel):
    image: str


class UsageQuery(BaseModel):
    user_id: str


class AnalyzeRequest(BaseModel):
    user_id: str
    mode: str = "coquetear"
    module: str = "chat"


class PremiumActivate(BaseModel):
    user_id: str
    plan: str = "weekly"


class TelegramAuthRequest(BaseModel):
    initData: str = ""
    user_id: Optional[str] = None


class GenerateReplyRequest(BaseModel):
    user_id: str
    mode: str = "coquetear"
    module: str = "chat"
    text: str = ""


class PendingPaymentRequest(BaseModel):
    user_id: str
    plan: str = "weekly"
    language: str = "es"
    method: Optional[str] = None


class PaymentSubmitRequest(BaseModel):
    operation_id: str
    user_id: str
    method: str
    payment_code: Optional[str] = None
    transaction_id: Optional[str] = None
    proof_note: Optional[str] = None


class PaymentStatusRequest(BaseModel):
    operation_id: str
    user_id: Optional[str] = None


class PaymentCancelRequest(BaseModel):
    operation_id: str
    user_id: str


class PaymentVerifyRequest(BaseModel):
    operation_id: str
    transaction_id: str
    payment_code: Optional[str] = None
    amount: Optional[str] = None


@app.get("/")
def root():
    return {"service": "LiggaCuba OCR API", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "LiggaCuba OCR API"}


def parse_telegram_init_data(init_data: str) -> Dict[str, str]:
    parsed = parse_qs(init_data, keep_blank_values=True)
    return {key: value[0] for key, value in parsed.items() if value}


def verify_telegram_init_data(init_data: str, bot_token: str) -> Dict[str, Any]:
    if not init_data:
        raise ValueError("initData vacío")

    if not bot_token:
        try:
            params = parse_telegram_init_data(init_data)
            user = json.loads(params.get("user", "{}"))
            if user:
                return user
        except Exception:
            pass
        raise ValueError("No hay TELEGRAM_BOT_TOKEN configurado")

    params = parse_telegram_init_data(init_data)
    received_hash = params.pop("hash", "")
    if not received_hash:
        raise ValueError("Falta hash de Telegram")

    auth_date = int(params.get("auth_date", "0"))
    if abs(time.time() - auth_date) > 86400:
        raise ValueError("La sesión de Telegram ha expirado")

    data_check_string = "\n".join(f"{key}={params[key]}" for key in sorted(params))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError("Hash de Telegram inválido")

    user_payload = params.get("user", "{}")
    user = json.loads(user_payload)
    if not user:
        raise ValueError("No se pudo leer el usuario de Telegram")
    return user


def require_admin(request: Request) -> None:
    if not ADMIN_KEY:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_KEY no está configurada en el servidor."
        )

    provided = request.headers.get("x-admin-key", "")

    if not provided or not hmac.compare_digest(provided, ADMIN_KEY):
        raise HTTPException(
            status_code=401,
            detail="No autorizado"
        )


@app.post("/api/auth/telegram")
async def auth_telegram(payload: TelegramAuthRequest):
    try:
        user_payload = verify_telegram_init_data(payload.initData, BOT_TOKEN) if payload.initData else {}
    except ValueError:
        if payload.user_id:
            user_payload = {"id": int(payload.user_id), "username": None, "first_name": None, "last_name": None}
        else:
            raise HTTPException(status_code=400, detail="initData inválido o no disponible")

    user_id = str(user_payload.get("id") or payload.user_id or "guest-user")
    extra = {
        "username": user_payload.get("username"),
        "first_name": user_payload.get("first_name"),
        "last_name": user_payload.get("last_name"),
    }
    user = get_or_create_user(user_id, extra)
    usage = can_use_analysis(user_id)

    return {
        "success": True,
        "user_id": user_id,
        "username": user.get("username"),
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "premium": usage["premium"],
        "remaining": usage["remaining"],
    }


@app.post("/api/usage")
async def usage(payload: UsageQuery):
    return can_use_analysis(payload.user_id)


@app.post("/api/analyze")
async def analyze(payload: AnalyzeRequest):
    module = payload.module if payload.module in {"chat", "story"} else "chat"
    mode = payload.mode.lower().strip()
    allowed_free = FREE_CHAT_MODES if module == "chat" else FREE_STORY_MODES
    allowed_premium = PREMIUM_CHAT_MODES if module == "chat" else PREMIUM_STORY_MODES
    if mode not in allowed_free | allowed_premium:
        raise HTTPException(status_code=400, detail="Modo de respuesta no válido.")
    premium = is_premium_active(payload.user_id)
    if mode in allowed_premium and not premium:
        raise HTTPException(status_code=402, detail="Este modo requiere Premium.")
    status = consume_analysis(payload.user_id, mode=f"{module}:{mode}")
    if not status["allowed"]:
        raise HTTPException(status_code=403, detail="Has alcanzado tus 3 análisis gratuitos de hoy. Obtén Premium para continuar.")
    return {"allowed": True, "remaining": status["remaining"], "premium": status["premium"]}


def get_premium_price(plan: str, language: str) -> str:
    if plan not in {"weekly", "annual"}:
        raise HTTPException(status_code=400, detail="Plan inválido.")

    language = (language or "es").lower().strip()

    if language == "en":
        return "8.99 USD" if plan == "weekly" else "29.99 USD"

    return "2500 CUP" if plan == "weekly" else "15500 CUP"


def get_plan_days(plan: str) -> int:
    if plan == "weekly":
        return 7

    if plan == "annual":
        return 365

    raise HTTPException(status_code=400, detail="Plan inválido.")


def activate_verified_premium(user_id: str, plan: str) -> Dict[str, Any]:
    user = get_or_create_user(user_id)

    now = datetime.utcnow()
    current_until = None

    if user.get("premium_until"):
        try:
            current_until = datetime.fromisoformat(user["premium_until"])
        except (ValueError, TypeError):
            current_until = None

    days = get_plan_days(plan)

    if current_until and current_until > now:
        base_date = current_until
    else:
        base_date = now

    premium_until = base_date + timedelta(days=days)

    get_or_create_user(
        user_id,
        {"premium_until": premium_until.isoformat()},
    )

    return {
        "premium": True,
        "premium_until": premium_until.isoformat(),
    }


@app.post("/api/premium/activate")
async def activate_premium(payload: PremiumActivate):
    raise HTTPException(
        status_code=403,
        detail="La activación directa de Premium no está permitida. Debes completar y verificar un pago."
    )


@app.post("/api/premium/check")
async def check_premium(payload: UsageQuery):
    user = get_or_create_user(payload.user_id)
    premium = is_premium_active(payload.user_id)

    return {
        "premium": premium,
        "user_id": payload.user_id,
        "premium_until": user.get("premium_until") if premium else None,
    }


@app.post("/api/payments/pending")
async def create_pending_payment(payload: PendingPaymentRequest):
    plan = (payload.plan or "").lower().strip()
    language = (payload.language or "es").lower().strip()

    if plan not in {"weekly", "annual"}:
        raise HTTPException(status_code=400, detail="Plan inválido.")

    if language not in {"es", "en"}:
        language = "es"

    method = payload.method

    if language == "en":
        method = None
    elif method is not None:
        method = method.lower().strip()

        allowed_methods = {
            "bandec",
            "bpa",
            "saldo_movil",
            "mobile_balance",
            "iphone",
        }

        if method not in allowed_methods:
            raise HTTPException(
                status_code=400,
                detail="Método de pago no válido.",
            )

    amount = get_premium_price(plan, language)

    operation_id = uuid.uuid4().hex[:12].upper()
    now = utcnow_iso()

    conn = get_db_connection()

    conn.execute(
        """
        INSERT INTO payment_operations (
            operation_id,
            user_id,
            plan,
            language,
            method,
            status,
            amount,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """,
        (
            operation_id,
            str(payload.user_id),
            plan,
            language,
            method,
            amount,
            now,
            now,
        ),
    )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "operation_id": operation_id,
        "status": "pending",
        "plan": plan,
        "language": language,
        "amount": amount,
        "method": method,
    }


@app.post("/api/payments/submit")
async def submit_payment(payload: PaymentSubmitRequest):
    operation_id = (payload.operation_id or "").strip()
    user_id = (payload.operation_id or "").strip()

    user_id = str(payload.user_id or "").strip()

    if not operation_id or not user_id:

        raise HTTPException(

            status_code=400,

            detail="Operación y usuario son obligatorios.",

        )

    conn = get_db_connection()

    row = conn.execute(

        """

        SELECT *

        FROM payment_operations

        WHERE operation_id = ?

        """,

        (operation_id,),

    ).fetchone()

    if not row:

        conn.close()

        raise HTTPException(

            status_code=404,

            detail="Operación no encontrada.",

        )

    payment = dict(row)

    if str(payment["user_id"]) != user_id:

        conn.close()

        raise HTTPException(

            status_code=403,

            detail="La operación no pertenece a este usuario.",

        )

    if payment["status"] != "pending":

        conn.close()

        raise HTTPException(

            status_code=409,

            detail="Solo se pueden cancelar operaciones pendientes.",

        )

    now = utcnow_iso()

    conn.execute(

        """

        UPDATE payment_operations

        SET

            status = 'cancelled',

            cancelled_at = ?,

            updated_at = ?

        WHERE operation_id = ?

        """,

        (

            now,

            now,

            operation_id,

        ),

    )

    conn.commit()

    conn.close()

    return {

        "success": True,

        "operation_id": operation_id,

        "status": "cancelled",

    }

@app.post("/api/payments/verify")

async def verify_payment(

    payload: PaymentVerifyRequest,

    request: Request,

):

    require_admin(request)

    operation_id = (payload.operation_id or "").strip()

    transaction_id = (payload.transaction_id or "").strip()

    if not operation_id:

        raise HTTPException(

            status_code=400,

            detail="operation_id es obligatorio.",

        )

    if not transaction_id:

        raise HTTPException(

            status_code=400,

            detail="transaction_id es obligatorio.",

        )

    conn = get_db_connection()

    row = conn.execute(

        """

        SELECT *

        FROM payment_operations

        WHERE operation_id = ?

        """,

        (operation_id,),

    ).fetchone()

    if not row:

        conn.close()

        raise HTTPException(

            status_code=404,

            detail="Operación no encontrada.",

        )

    payment = dict(row)

    if payment["status"] not in {"pending", "submitted"}:

        conn.close()

        raise HTTPException(

            status_code=409,

            detail=f"La operación no puede verificarse porque está en estado '{payment['status']}'.",

        )

    if payload.amount is not None:

        if str(payload.amount).strip() != str(payment["amount"]).strip():

            conn.close()

            raise HTTPException(

                status_code=400,

                detail="El importe no coincide con el precio de la operación.",

            )

    duplicate_transaction = conn.execute(

        """

        SELECT operation_id

        FROM payment_operations

        WHERE transaction_id = ?

          AND operation_id != ?

        """,

        (

            transaction_id,

            operation_id,

        ),

    ).fetchone()

    if duplicate_transaction:

        conn.close()

        raise HTTPException(

            status_code=409,

            detail="La transacción ya está asociada a otra operación.",

        )

    if payload.payment_code:

        duplicate_code = conn.execute(

            """

            SELECT operation_id

            FROM payment_operations

            WHERE payment_code = ?

              AND operation_id != ?

            """,

            (

                payload.payment_code.strip(),

                operation_id,

            ),

        ).fetchone()

        if duplicate_code:

            conn.close()

            raise HTTPException(

                status_code=409,

                detail="El código de pago ya fue utilizado.",

            )

    now = utcnow_iso()

    conn.execute(

        """

        UPDATE payment_operations

        SET

            status = 'paid',

            transaction_id = ?,

            payment_code = COALESCE(?, payment_code),

            verified_at = ?,

            updated_at = ?

        WHERE operation_id = ?

        """,

        (

            transaction_id,

            payload.payment_code.strip()

            if payload.payment_code

            else None,

            now,

            now,

            operation_id,

        ),

    )

    conn.commit()

    conn.close()

    premium_result = activate_verified_premium(

        payment["user_id"],

        payment["plan"],

    )

    return {

        "success": True,

        "operation_id": operation_id,

        "status": "paid",

        "premium": True,

        "premium_until": premium_result["premium_until"],

        "message": "Pago verificado y Premium activado correctamente.",

    }

@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    require_admin(request)
    conn = get_db_connection()
    total_users = conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
    premium_users = conn.execute(
        "SELECT COUNT(*) AS total FROM users WHERE premium_until IS NOT NULL AND premium_until > ?",
        (utcnow_iso(),),
    ).fetchone()["total"]
    today = today_iso()
    today_usage = conn.execute(
        "SELECT COUNT(*) AS total FROM usage_logs WHERE used_at >= ?",
        (f"{today}T00:00:00",),
    ).fetchone()["total"]
    conn.close()
    return {"total_users": total_users, "premium_users": premium_users, "today_usage": today_usage}


@app.get("/api/admin/users")
async def admin_users(request: Request):
    require_admin(request)
    conn = get_db_connection()
    items = conn.execute(
        "SELECT user_id, username, first_name, last_name, premium_until, usage_today, last_reset_date FROM users ORDER BY updated_at DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return {"users": [dict(item) for item in items]}


def build_reply_for_mode(mode: str, text: str) -> str:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    lower = normalized.lower()

    templates = {
        "gracioso": "Responde con un toque ligero y divertido, sin perder naturalidad.",
        "coquetear": "Usa un tono cálido y atractivo, pero sin presionar ni forzar.",
        "provocativo": "Da un tono más directo e intenso, pero con control y clase.",
        "enamorar": "Haz una respuesta elegante, cercana y romántica, con buena energía y respeto.",
    }

    if not normalized:
        return "No pude detectar texto suficiente para generar una respuesta útil. Intenta otra captura."

    base = templates.get(mode, templates["coquetear"])
    if "hola" in lower or "hey" in lower:
        return f"{base} Además, puedes empezar con un saludo amable y seguir la conversación sin hacerla forzada."
    if "porque" in lower or "por qué" in lower:
        return f"{base} Responde con claridad, evita entrar en defensiva y deja la conversación con una línea amable y directa."
    return f"{base} Mantén la respuesta breve, auténtica y con buena energía."


@app.post("/api/generate-reply")
async def generate_reply(payload: GenerateReplyRequest):
    module = payload.module if payload.module in {"chat", "story"} else "chat"
    mode = payload.mode.lower().strip()
    allowed_free = FREE_CHAT_MODES if module == "chat" else FREE_STORY_MODES
    allowed_premium = PREMIUM_CHAT_MODES if module == "chat" else PREMIUM_STORY_MODES
    if mode not in allowed_free | allowed_premium:
        raise HTTPException(status_code=400, detail="Modo de respuesta no válido.")
    if mode in allowed_premium and not is_premium_active(payload.user_id):
        raise HTTPException(status_code=402, detail="Este modo requiere Premium.")
    if not payload.text:
        return {"success": True, "reply": "No pude detectar texto suficiente para generar una respuesta útil."}
    reply = build_reply_for_mode(mode, payload.text)
    return {"success": True, "reply": reply}


def preprocess_image(raw: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(raw))
    image.load()
    if image.mode in ("RGBA", "LA"):
        image = image.convert("RGB")
    return image


@app.post("/ocr-base64")
async def ocr_base64(payload: OCRBase64Request):
    try:
        image_data = payload.image or ""
        if not image_data:
            raise HTTPException(status_code=400, detail="La imagen está vacía.")
        if "," in image_data:
            image_data = image_data.split(",", 1)[1]
        raw = base64.b64decode(image_data)
        if not raw:
            raise HTTPException(status_code=400, detail="La imagen está vacía.")

        image = preprocess_image(raw)
        text = pytesseract.image_to_string(image, lang="spa+eng")
        return {"success": True, "text": text.strip()}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo procesar la imagen: {exc}")


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen.")

    try:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="La imagen está vacía.")

        image = preprocess_image(data)
        text = pytesseract.image_to_string(image, lang="spa+eng")
        return {"success": True, "text": text.strip()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo procesar la imagen: {exc}")


@app.post("/ocr-base64-simple")
async def ocr_base64_simple(request: Request):
    try:
        raw_body = await request.body()
        image_data = raw_body.decode("utf-8").strip()
        if not image_data:
            raise HTTPException(status_code=400, detail="La imagen está vacía.")

        if "," in image_data:
            image_data = image_data.split(",", 1)[1]

        raw = base64.b64decode(image_data)
        if not raw:
            raise HTTPException(status_code=400, detail="La imagen está vacía.")

        image = preprocess_image(raw)
        text = pytesseract.image_to_string(image, lang="spa+eng")
        return {"success": True, "text": text.strip()}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo procesar la imagen: {exc}")

