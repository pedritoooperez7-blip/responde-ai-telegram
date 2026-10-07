from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image
import base64
import io
import os
import sqlite3
import pytesseract
from datetime import datetime, timedelta
from typing import Dict, Any

app = FastAPI(title="LiggaCuba API", version="1.2.0")

allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

FREE_DAILY_LIMIT = 3
DB_PATH = os.getenv("DATABASE_PATH", "/tmp/liggacuba.db")


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = db_connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            used_today INTEGER NOT NULL DEFAULT 0,
            premium INTEGER NOT NULL DEFAULT 0,
            premium_until TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


def utc_now() -> datetime:
    return datetime.utcnow()


def get_or_create_user(user_id: str) -> Dict[str, Any]:
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id requerido")

    conn = db_connect()
    row = conn.execute(
        "SELECT user_id, date, used_today, premium, premium_until FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()

    if row is None:
        now_iso = utc_now().isoformat()
        conn.execute(
            """
            INSERT INTO users (user_id, date, used_today, premium, premium_until, created_at, updated_at)
            VALUES (?, ?, 0, 0, NULL, ?, ?)
            """,
            (user_id, utc_now().date().isoformat(), now_iso, now_iso),
        )
        conn.commit()
        row = conn.execute(
            "SELECT user_id, date, used_today, premium, premium_until FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    conn.close()
    if row is None:
        raise HTTPException(status_code=500, detail="No se pudo crear el usuario")

    return {
        "user_id": row["user_id"],
        "date": row["date"],
        "used_today": int(row["used_today"]),
        "premium": bool(row["premium"]),
        "premium_until": row["premium_until"],
    }


def reset_if_needed(user_id: str):
    user = get_or_create_user(user_id)
    today = utc_now().date().isoformat()
    if user["date"] != today:
        conn = db_connect()
        conn.execute(
            "UPDATE users SET date = ?, used_today = 0, updated_at = ? WHERE user_id = ?",
            (today, utc_now().isoformat(), user_id),
        )
        conn.commit()
        conn.close()


def is_premium_active(user_id: str) -> bool:
    user = get_or_create_user(user_id)
    if not user.get("premium"):
        return False
    premium_until = user.get("premium_until")
    if not premium_until:
        return False
    return utc_now() < datetime.fromisoformat(premium_until)


def can_use_analysis(user_id: str) -> Dict[str, Any]:
    reset_if_needed(user_id)
    user = get_or_create_user(user_id)
    if is_premium_active(user_id):
        return {
            "allowed": True,
            "remaining": 999,
            "used_today": user["used_today"],
            "premium": True,
            "message": "Premium activo",
        }

    remaining = max(0, FREE_DAILY_LIMIT - int(user["used_today"]))
    return {
        "allowed": int(user["used_today"]) < FREE_DAILY_LIMIT,
        "remaining": remaining,
        "used_today": int(user["used_today"]),
        "premium": False,
        "message": "Límite gratuito alcanzado" if remaining == 0 else "Disponible",
    }


def consume_analysis(user_id: str) -> Dict[str, Any]:
    reset_if_needed(user_id)
    user = get_or_create_user(user_id)

    if is_premium_active(user_id):
        return {"allowed": True, "remaining": 999, "premium": True}

    if int(user["used_today"]) >= FREE_DAILY_LIMIT:
        return {"allowed": False, "remaining": 0, "premium": False}

    new_used = int(user["used_today"]) + 1
    conn = db_connect()
    conn.execute(
        "UPDATE users SET used_today = ?, updated_at = ? WHERE user_id = ?",
        (new_used, utc_now().isoformat(), user_id),
    )
    conn.commit()
    conn.close()

    remaining = max(0, FREE_DAILY_LIMIT - new_used)
    return {"allowed": True, "remaining": remaining, "premium": False}


def normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\n", " ").split())


def generate_reply(mode: str, text: str) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return "No pude detectar texto suficiente en la captura. Inténtalo con otra imagen."

    lower = normalized.lower()
    if "hola" in lower or "hey" in lower:
        opener = "Hola, "
    else:
        opener = "Podrías responder con un tono "

    mode_map = {
        "natural": "natural y tranquilo, manteniendo la conversación sin forzarla.",
        "casual": "relajado y cercano para que la charla fluya sin presión.",
        "segura": "claro y seguro, sin entrar en drama ni hacerla incómoda.",
        "curiosa": "curioso y natural, dejando una pequeña pregunta para seguir la conversación.",
        "gracioso": "ligero y divertido, sin perder naturalidad ni exagerar.",
        "coquetear": "cálido y atractivo, con confianza y sin presionar demasiado.",
        "enamorar": "cercano, elegante y romántico, con buen tono y respeto.",
        "provocativo": "más directo y intenso, con mucha presencia y un toque sensual controlado.",
    }

    style = mode_map.get(mode, mode_map["natural"])
    return f"{opener}responde de forma {style} Mantén la respuesta breve, cercana y natural. Puedes decir: ‘Vi lo que escribiste y me gustó cómo lo planteas, me gustaría seguir esta conversación contigo.’"


@app.get("/")
def root():
    return {"service": "LiggaCuba API", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "LiggaCuba API"}


class OCRBase64Request(BaseModel):
    image: str


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


class UsageQuery(BaseModel):
    user_id: str


@app.post("/api/usage")
async def usage(payload: UsageQuery):
    return can_use_analysis(payload.user_id)


@app.post("/api/analyze")
async def analyze(payload: UsageQuery):
    status = consume_analysis(payload.user_id)
    if not status["allowed"]:
        raise HTTPException(
            status_code=403,
            detail="Has alcanzado tus 3 análisis gratuitos de hoy. Obtén Premium para continuar.",
        )
    return {"allowed": True, "remaining": status["remaining"], "premium": status["premium"]}


class GenerateReplyRequest(BaseModel):
    user_id: str
    mode: str
    text: str


@app.post("/api/generate-reply")
async def generate_reply_endpoint(payload: GenerateReplyRequest):
    if not payload.user_id:
        raise HTTPException(status_code=400, detail="user_id requerido")

    get_or_create_user(payload.user_id)
    if not is_premium_active(payload.user_id):
        status = can_use_analysis(payload.user_id)
        if not status["allowed"]:
            raise HTTPException(status_code=403, detail="Límite alcanzado. Compra Premium.")

    reply = generate_reply(payload.mode, payload.text)
    return {"success": True, "reply": reply}


class PremiumActivate(BaseModel):
    user_id: str
    plan: str = "weekly"


@app.post("/api/premium/activate")
async def activate_premium(payload: PremiumActivate):
    user = get_or_create_user(payload.user_id)
    user["premium"] = True
    user["premium_until"] = (
        (utc_now() + timedelta(days=7 if payload.plan == "weekly" else 365)).isoformat()
    )

    conn = db_connect()
    conn.execute(
        "UPDATE users SET premium = 1, premium_until = ?, updated_at = ? WHERE user_id = ?",
        (user["premium_until"], utc_now().isoformat(), payload.user_id),
    )
    conn.commit()
    conn.close()

    return {
        "success": True,
        "premium": True,
        "premium_until": user["premium_until"],
    }


@app.post("/api/premium/check")
async def check_premium(payload: UsageQuery):
    return {"premium": is_premium_active(payload.user_id), "user_id": payload.user_id}


@app.post("/api/premium/status")
async def premium_status(payload: UsageQuery):
    user = get_or_create_user(payload.user_id)
    return {
        "premium": is_premium_active(payload.user_id),
        "premium_until": user.get("premium_until"),
        "user_id": payload.user_id,
    }


@app.post("/api/reset")
async def reset_usage(payload: UsageQuery):
    conn = db_connect()
    conn.execute(
        "UPDATE users SET date = ?, used_today = 0, updated_at = ? WHERE user_id = ?",
        (utc_now().date().isoformat(), utc_now().isoformat(), payload.user_id),
    )
    conn.commit()
    conn.close()
    return {"success": True, "remaining": FREE_DAILY_LIMIT}
