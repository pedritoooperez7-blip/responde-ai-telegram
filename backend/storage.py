"""Almacenamiento de fotos de Citas: Tigris Object Storage (compatible con S3) o disco.

Si las variables B2_* están definidas, las fotos NUEVAS se suben a Tigris. Si no,
todo sigue funcionando en disco como antes. Las fotos antiguas que ya estén en
disco se siguen sirviendo desde disco, así que activar Tigris nunca rompe nada.

En la base de datos solo se guarda el nombre del archivo ("abc123.jpg"); el
bucket es PRIVADO y las fotos se sirven a través de la API (URL firmada), de modo
que una foto pendiente de moderación nunca es pública.

Tigris Object Storage — compatible con S3/boto3. Sin tarjeta de crédito.
Tier gratuito: 5 GB permanentes, egreso gratis, región automática global.
Endpoint: https://t3.storage.dev
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_client = None
_client_key = None
_lock = threading.Lock()


def _settings() -> dict:
    return {
        "endpoint": (os.getenv("B2_ENDPOINT") or "").strip(),
        "key":      (os.getenv("B2_ACCESS_KEY") or "").strip(),
        "secret":   (os.getenv("B2_SECRET_KEY") or "").strip(),
        "bucket":   (os.getenv("B2_BUCKET") or "").strip(),
    }


def enabled() -> bool:
    s = _settings()
    return all(s.values())


def _get_client():
    """Cliente boto3 perezoso: si boto3 no está instalado, Tigris queda desactivado."""
    global _client, _client_key
    s = _settings()
    key = tuple(s.values())
    with _lock:
        if _client is not None and _client_key == key:
            return _client
        import boto3  # noqa: WPS433
        from botocore.config import Config

        _client = boto3.client(
            "s3",
            endpoint_url=s["endpoint"],
            aws_access_key_id=s["key"],
            aws_secret_access_key=s["secret"],
            region_name="auto",
            config=Config(
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=15,
            ),
        )
        _client_key = key
        return _client


def _object_key(filename: str) -> str:
    return "dating/" + os.path.basename(filename or "")


def put(filename: str, data: bytes, content_type: str = "image/jpeg") -> bool:
    """Sube un archivo a Tigris. True si quedó guardado; False si no está disponible."""
    if not enabled() or not os.path.basename(filename or ""):
        return False
    try:
        _get_client().put_object(
            Bucket=_settings()["bucket"],
            Key=_object_key(filename),
            Body=data,
            ContentType=content_type,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tigris put failed: error_type=%s", type(exc).__name__)
        return False


def get(filename: str) -> Optional[bytes]:
    """Descarga un archivo de Tigris; None si no existe o no está disponible."""
    if not enabled() or not os.path.basename(filename or ""):
        return None
    try:
        obj = _get_client().get_object(
            Bucket=_settings()["bucket"],
            Key=_object_key(filename),
        )
        return obj["Body"].read()
    except Exception as exc:  # noqa: BLE001
        code = (
            getattr(exc, "response", {}).get("Error", {}).get("Code")
            if hasattr(exc, "response")
            else None
        )
        if code not in {"NoSuchKey", "404"}:
            logger.warning("Tigris get failed: error_type=%s", type(exc).__name__)
        return None


def delete(filename: str) -> bool:
    """Borra un archivo de Tigris (idempotente). False si no está disponible."""
    if not enabled() or not os.path.basename(filename or ""):
        return False
    try:
        _get_client().delete_object(
            Bucket=_settings()["bucket"],
            Key=_object_key(filename),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tigris delete failed: error_type=%s", type(exc).__name__)
        return False
