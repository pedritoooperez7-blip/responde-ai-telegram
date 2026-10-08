from fastapi import FastAPI, File, UploadFile, HTTPException
from PIL import Image
import pytesseract
import io

app = FastAPI(title="Responde AI OCR API")


@app.get("/")
def root():
    return {
        "service": "Responde AI OCR",
        "status": "ok"
    }


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen.")

    try:
        data = await file.read()
        image = Image.open(io.BytesIO(data))
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
