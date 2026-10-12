# Proveedores de IA de LiggaCuba

La capa común está en `backend/ai_providers.py`. Las claves se configuran únicamente como variables de entorno del servidor (por ejemplo, en Railway); nunca en `app.js`, HTML ni el repositorio.

Variables opcionales:

- `GEMINI_API_KEY` y opcionalmente `GEMINI_MODEL` (por defecto `gemini-2.5-flash`): texto e imágenes.
- `GROQ_API_KEY` y opcionalmente `GROQ_MODEL` (por defecto `llama-3.3-70b-versatile`): texto.
- `OPENROUTER_API_KEY` y opcionalmente `OPENROUTER_MODEL` (por defecto `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`): texto e imágenes si el modelo elegido las admite.
- `COHERE_API_KEY` y opcionalmente `COHERE_MODEL` (por defecto `command-r7b-12-2024`): texto.

Se intentan solo los proveedores configurados y capaces de atender el tipo de petición. Errores temporales (HTTP 408, 425, 429 y 5xx o problemas de conexión) admiten hasta tres intentos, con espera progresiva y respeto de `Retry-After` limitado a 30 segundos. Errores permanentes no se reintentan. Si ningún proveedor produce dos respuestas estructuradas y diferentes, la solicitud falla con un error recuperable para que el usuario pueda usar el reintento disponible; no se inventa una segunda respuesta.

El análisis visual usa la misma ruta de generación para Chat y Estado/Story. La imagen sigue limitada a 8 MB y a formatos de imagen admitidos por el OCR. No se registra el contenido de la imagen ni las claves. Las capacidades, cuotas y disponibilidad reales dependen de la cuenta, modelo y proveedor configurados.
