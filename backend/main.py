from fastapi import FastAPI, File, UploadFile, HTTPException
from pydantic import BaseModel
import base64
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
import pytesseract
import io

app = FastAPI(title="Responde AI OCR API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "service": "Responde AI OCR",
        "status": "ok"
    }


class OCRBase64Request(BaseModel):
    image: str


@app.post("/ocr-base64")
async def ocr_base64(payload: OCRBase64Request):
    try:
        image_data = payload.image

        if "," in image_data:
            image_data = image_data.split(",", 1)[1]

        raw = base64.b64decode(image_data)

        if not raw:
            raise HTTPException(status_code=400, detail="La imagen está vacía.")

        image = Image.open(io.BytesIO(raw))
        image.load()

        text = pytesseract.image_to_string(image, lang="spa+eng")

        return {
            "success": True,
            "text": text.strip()
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo procesar la imagen: {exc}"
        )


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen.")

    try:
        data = await file.read()

        if not data:
            raise HTTPException(status_code=400, detail="La imagen está vacía.")

        image = Image.open(io.BytesIO(data))
        image.load()
        text = pytesseract.image_to_string(image, lang="spa+eng")

        return {
            "success": True,
            "text": text.strip()
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo procesar la imagen: {exc}"
        )
