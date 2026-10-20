FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY index.html admin.html app.js style.css liggacuba-logo.jpg privacy.html terms.html ./

RUN rm -rf backend/__pycache__

# PUBLIC_BASE_URL is the public HTTPS URL of this deployment; it is used to
# register the Telegram webhook. All other configuration arrives as env vars.
ENV PUBLIC_BASE_URL=""

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
