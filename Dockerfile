FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --home /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY index.html admin.html app.js chat.js dating.js ads.js style.css liggacuba-logo.jpg privacy.html terms.html rules.html image-guide.html ./

RUN rm -rf backend/__pycache__ \
    && chown -R app:app /app

# PUBLIC_BASE_URL is the public HTTPS URL of this deployment; it is used to
# register the Telegram webhook. All other configuration arrives as env vars.
ENV PUBLIC_BASE_URL=""

USER app

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
