# Auditoría del flujo de análisis y generación de respuestas

## 1. Flujo original

1. **Autenticación**: las rutas privadas obtienen el usuario de la sesión/token; el `user_id` del cuerpo no debe prevalecer sobre la identidad autenticada.
2. **Reserva del análisis** (`POST /api/analyze`): valida módulo/modo, Premium cuando corresponde, consume cuota y crea `analysis_id`. No analiza todavía la imagen ni genera una respuesta.
3. **Solicitud de generación** (`POST /api/generate-reply`): exige `analysis_id`, valida módulo/modo, texto/imagen y comprueba que el análisis pertenece al usuario, es del día actual y coincide con el modo original.
4. **Control de concurrencia/reintento**: una transacción SQLite reserva `generation_in_progress`; limita a una generación válida inicial y un reintento. Los fallos no incrementan `generation_count`.
5. **Generación IA** (`backend/ai_providers.py`): construye prompt contextual para `chat` o `story` y los modos; intenta proveedores configurados en orden Gemini, Groq (solo texto), OpenRouter y Cohere (solo texto). Cada proveedor usa reintentos limitados para errores transitorios.
6. **Imagen y OCR**: se intenta visión primero. Si la generación visual falla con `ProviderError`, el backend intenta OCR local y vuelve a generar con texto; si OCR no obtiene texto, devuelve un error.
7. **Validación de salida**: exige dos alternativas no vacías y distintas en JSON; calcula una puntuación heurística, identifica proveedor/modelo y devuelve las respuestas.
8. **Monitorización**: registra metadatos operativos de éxito/error, latencia, proveedor, modo y puntuación; evita guardar prompts, imágenes, conversaciones y claves. El bloqueo de generación se libera en `finally`.

## 2. Aspectos incompletos o riesgos encontrados

- Antes del cambio, la API comprobaba principalmente el encabezado y el tamaño codificado de una imagen. Un `data:image/...;base64,...` podía contener Base64 inválido, bytes vacíos, contenido que no fuera una imagen real, MIME distinto del formato detectado o dimensiones excesivas; esos datos podían llegar a la lógica de proveedores.
- La prueba visual usaba un payload JPEG ficticio, por lo que no comprobaba una imagen real ni detectaba el problema de validación.
- El flujo depende de servicios externos y variables de entorno (`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `COHERE_API_KEY`), modelos disponibles, conectividad, límites/cuotas de proveedores y compatibilidad de sus APIs. Las pruebas automatizadas no verifican esos servicios en vivo.
- OCR depende de Pillow, Tesseract y sus datos de idioma instalados correctamente. El OCR es una ruta de contingencia, no una garantía de interpretación correcta.
- La puntuación de calidad es heurística y no demuestra calidad semántica. Dos alternativas distintas en texto pueden seguir siendo poco útiles o parecidas en significado.
- El repositorio presenta advertencias deprecadas de `datetime.utcnow()` en código existente. No bloquean la suite, pero conviene migrarlas a fechas con zona horaria en una tarea separada.
- El comportamiento real de extremo a extremo en Telegram/navegador, los secretos de despliegue, las cuotas y la configuración de producción no pueden verificarse desde el ZIP.

## 3. Cambios implementados

- Se añadió validación temprana de la imagen en `backend/main.py`, antes de reservar una generación o enviar contenido a proveedores:
  - sintaxis de data URL y límite de tamaño;
  - decodificación Base64 estricta;
  - rechazo de payload vacío o superior al límite binario;
  - apertura real de la imagen con Pillow;
  - correspondencia entre MIME declarado y formato detectado;
  - dimensiones positivas y límite de píxeles;
  - verificación de integridad de la imagen.
- Los errores de imagen se responden como HTTP 400 con un mensaje genérico, sin exponer detalles internos.
- Se actualizaron las pruebas visuales para usar una imagen JPEG real generada en memoria y se añadió una regresión que comprueba que una imagen Base64 inválida se rechaza antes de invocar al proveedor.
- Se conservó el flujo de proveedores, la reserva de cuota, el control de reintentos, la salida estructurada y el monitor existente.

## 4. Verificaciones y limitaciones

- `pytest -q`: **36 pruebas pasadas**, 6 subtests pasados; 208 advertencias (principalmente deprecaciones existentes).
- La suite usa base de datos temporal y dobles/mocks para proveedores; no realiza llamadas reales a APIs de IA.
- La validación nueva cubre payloads inválidos y los flujos visuales existentes con una imagen válida.
- No se declara el flujo completo al 100 %: quedan por verificar integración real con cada proveedor, despliegue de Tesseract/modelos, configuración de secretos, y una prueba E2E real desde la interfaz hasta la respuesta final.
