"""Shared, server-side AI provider adapter with bounded transient retries."""
from __future__ import annotations
import json, os, time, urllib.error, urllib.request
from dataclasses import dataclass
from typing import Any

@dataclass
class ProviderError(Exception):
    message: str
    transient: bool = False
    retry_after: float | None = None
    def __str__(self): return self.message


def _request_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float = 25) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={**headers, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
            if not isinstance(parsed, dict): raise ProviderError("Respuesta inválida del proveedor")
            return parsed
    except urllib.error.HTTPError as exc:
        retry_after = None
        try: retry_after = max(0.0, min(30.0, float(exc.headers.get("Retry-After", ""))))
        except (TypeError, ValueError): pass
        transient = exc.code in (408, 425, 429, 500, 502, 503, 504)
        raise ProviderError(f"Proveedor respondió HTTP {exc.code}", transient, retry_after) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProviderError("Proveedor temporalmente no disponible", True) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ProviderError("Respuesta inválida del proveedor") from None


def _with_retry(call):
    for attempt in range(3):
        try: return call()
        except ProviderError as exc:
            if not exc.transient or attempt == 2: raise
            delay = exc.retry_after if exc.retry_after is not None else min(0.5 * (2 ** attempt), 4)
            time.sleep(delay)


def generate_reply(text: str, mode: str, module: str, image_data_url: str | None = None) -> str | None:
    """Try configured providers in order; return None when none can serve this request."""
    prompt = ("Eres LiggaCuba, asistente para sugerir una respuesta natural en español. "
              f"Módulo: {module}. Estilo: {mode}. Usa el contexto visual si hay imagen. "
              "Si es una captura de chat, identifica brevemente el contexto y propone una sola respuesta lista para enviar. "
              "Si es un estado/story, interpreta la imagen, texto, tono y contexto y propone una respuesta pertinente. "
              "No inventes detalles que no se vean. Devuelve solo la respuesta sugerida.")
    user_content: Any = text.strip() or "Analiza el contexto visual y sugiere una respuesta."
    if image_data_url:
        if image_data_url.startswith("data:"):
            mime, sep, encoded = image_data_url.partition(",")
            if not sep or not mime.startswith("data:image/") or len(encoded) > 11_200_000:
                raise ProviderError("Imagen inválida o demasiado grande")
        user_content = [{"type":"text", "text":user_content}, {"type":"image_url", "image_url":{"url":image_data_url}}]
    providers = []
    if os.getenv("GEMINI_API_KEY"):
        providers.append(("gemini", lambda: _gemini(prompt, user_content)))
    if os.getenv("GROQ_API_KEY") and not image_data_url:
        providers.append(("groq", lambda: _openai_compatible("https://api.groq.com/openai/v1/chat/completions", os.environ["GROQ_API_KEY"], os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), prompt, user_content)))
    if os.getenv("OPENROUTER_API_KEY"):
        providers.append(("openrouter", lambda: _openai_compatible("https://openrouter.ai/api/v1/chat/completions", os.environ["OPENROUTER_API_KEY"], os.getenv("OPENROUTER_MODEL", "openrouter/free"), prompt, user_content)))
    # Cohere is text-only here; it is a fallback, not a vision provider.
    if os.getenv("COHERE_API_KEY") and not image_data_url:
        providers.append(("cohere", lambda: _cohere(prompt, str(user_content))))
    for name, call in providers:
        try:
            answer = _with_retry(call)
            if isinstance(answer, str) and answer.strip(): return answer.strip()[:4000]
        except ProviderError:
            continue
    return None


def _gemini(prompt: str, content: Any) -> str:
    key = os.environ["GEMINI_API_KEY"]
    parts = [{"text":prompt}]
    if isinstance(content, list):
        parts.append({"text":content[0]["text"]})
        url = content[1]["image_url"]["url"]
        header, encoded = url.split(",", 1)
        import base64
        parts.append({"inline_data":{"mime_type":header[5:].split(";",1)[0],"data":encoded}})
    else: parts.append({"text":content})
    data = _with_retry(lambda: _request_json(f"https://generativelanguage.googleapis.com/v1beta/models/{os.getenv('GEMINI_MODEL','gemini-2.5-flash')}:generateContent?key={key}", {}, {"contents":[{"parts":parts}],"generationConfig":{"temperature":0.7,"maxOutputTokens":500}}))
    try: return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError): raise ProviderError("Respuesta inválida de Gemini")


def _openai_compatible(url: str, key: str, model: str, prompt: str, content: Any) -> str:
    data = _with_retry(lambda: _request_json(url, {"Authorization":f"Bearer {key}"}, {"model":model,"messages":[{"role":"system","content":prompt},{"role":"user","content":content}],"temperature":0.7,"max_tokens":500}))
    try: return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError): raise ProviderError("Respuesta inválida del proveedor")


def _cohere(prompt: str, text: str) -> str:
    data = _with_retry(lambda: _request_json("https://api.cohere.com/v2/chat", {"Authorization":f"Bearer {os.environ['COHERE_API_KEY']}"}, {"model":os.getenv("COHERE_MODEL","command-r7b-12-2024"),"messages":[{"role":"system","content":prompt},{"role":"user","content":text}]}))
    try: return "".join(x.get("text", "") for x in data["message"]["content"] if x.get("type")=="text")
    except (KeyError, TypeError): raise ProviderError("Respuesta inválida de Cohere")
