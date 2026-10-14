# RESPONDE AI / LiggaCuba — Informe de auditoría y correcciones del flujo de IA

**Alcance:** revisión del ZIP `responde-ai-telegram-main 25.zip` comparado con `RESPONDE_AI_mapa_auditoria_flujo_IA.docx`. El código incluido en el ZIP es la fuente de verdad; el mapa se usó como lista de verificación.

## 1. Estado inicial del repositorio

- El ZIP contenía 63 entradas, incluyendo el backend FastAPI, frontend, documentación y pruebas.
- No se encontró `AGENTS.md`, `README.md` en la raíz ni metadatos `.git`. El archivo `backend/README.txt`, `backend/AI_PROVIDERS.md`, los Dockerfiles, requirements, informes y pruebas existentes sí fueron revisados.
- Como el ZIP no contiene `.git`, no fue posible inspeccionar historial, rama, cambios no confirmados ni crear una rama real. No se ha hecho push, PR ni despliegue.
- Línea base antes de editar: `python -m pytest -q` → **84 passed, 4 skipped, 17 subtests passed**.
- No había claves de Gemini, Groq, OpenRouter ni Cohere en el entorno de esta ejecución. Las pruebas de API real quedaron bloqueadas y no se hicieron llamadas pagadas.
- El escaneo estático inicial no encontró patrones evidentes de claves privadas, tokens de proveedores o claves Git en los archivos activos examinados. Esto no sustituye un análisis del historial Git, ausente en el ZIP.

## 2. Matriz de comparación con el mapa técnico

| Elemento del mapa | Archivo / función | Estado inicial | Problema o evidencia | Acción aplicada / prueba |
|---|---|---|---|---|
| `collect_timings` | `backend/ai_providers.py` | IMPLEMENTADO Y VERIFICADO | ContextVar por solicitud ya existía. | Se conserva y se usa para métricas de proveedor y tokens; tests de instrumentación pasan. |
| `_request_json` | `backend/ai_providers.py` | IMPLEMENTADO, PERO INCOMPLETO | Normalizaba HTTP, pero intentaba registrar fragmentos del mensaje de error del proveedor, con riesgo de exponer contenido privado. Timeout no respetaba un presupuesto global. | No registra cuerpos ni mensajes arbitrarios; categoriza HTTP, limita timeout al presupuesto restante. Tests de seguridad y clasificación pasan. |
| `_with_retry` | `backend/ai_providers.py` | IMPLEMENTADO, PERO INCOMPLETO | Solo un reintento y espera fija, sin jitter ni deadline compartido. | Hasta 3 intentos por proveedor, backoff exponencial con jitter, `Retry-After` y límite global. Tests de retry y deadline pasan. |
| `_build_prompt` | `backend/ai_providers.py` | IMPLEMENTADO Y VERIFICADO | Conserva instrucciones para modos Chat/Story y salida JSON. | No se reemplazó el prompt ni se cambió el contrato público. Suite de regresión pasa. |
| `_parse_replies` | `backend/ai_providers.py` | IMPLEMENTADO, PERO INCOMPLETO | Validaba cadenas y duplicados exactos, pero no rechazaba campos extra, contenido excesivamente largo ni alternativas casi duplicadas. | Se separó `validate_reply_schema` de `validate_reply_quality`; tipos estrictos, claves exactas, límite de 1200 caracteres y detector determinista de similitud. Tests nuevos pasan. |
| `generate_reply` | `backend/ai_providers.py` | IMPLEMENTADO, PERO INCOMPLETO | La selección y failover ya existían; no había presupuesto compartido por solicitud. | Se mantiene la firma de uso existente y se añade deadline opcional de 12 s. El contexto exterior puede limitar el conjunto de la generación y OCR. Tests de regresión pasan. |
| `generate_reply_with_fallback` | `backend/main.py` / `generate_reply` | NO APLICABLE COMO FUNCIÓN NUEVA | Ya existe `_generate_with_ocr_fallback()` en `main.py` y `generate_reply()` en el módulo de proveedores. Añadir un tercer orquestador duplicaría la responsabilidad. | Se mejoró la ruta existente; no se duplicó el pipeline. Tests de OCR y generación pasan. |
| `_gemini` | `backend/ai_providers.py` | IMPLEMENTADO; compatibilidad estática contrastada | Usa Interactions API, cabecera `x-goog-api-key` y carga de imagen Base64. | Endpoint/modelo predeterminados coinciden con documentación oficial consultada. El contrato se prueba con respuestas simuladas; la API real está BLOQUEADA por ausencia de credenciales. |
| `_openai_compatible` / Groq | `backend/ai_providers.py` | IMPLEMENTADO, PERO MODELO PREDETERMINADO OBSOLETO PARA PLANES NO ENTERPRISE | Endpoint compatible Chat Completions correcto en pruebas contractuales. La documentación oficial de Groq consultada marca `llama-3.3-70b-versatile` como deprecado desde el 16-08-2026 para planes no Enterprise. | El valor predeterminado pasó a `openai/gpt-oss-120b`, documentado por Groq con Chat Completions y JSON Object Mode. `GROQ_MODEL` explícito conserva prioridad. Prueba real por cuenta aún pendiente; cambio de modelo puede alterar coste/calidad. |
| `_openai_compatible` / OpenRouter | `backend/ai_providers.py` | IMPLEMENTADO; contrato estático verificado | Endpoint y forma Chat Completions presentes. Visión depende del modelo configurado. | No se cambió el modelo por defecto. Contrato simulado pasa; modelo/cuenta/visión real no verificados. |
| `_cohere` | `backend/ai_providers.py` | IMPLEMENTADO; contrato estático verificado | Cohere Chat V2 y extracción `message.content` ya existían. | Se registra uso de tokens si el proveedor lo devuelve. Endpoint y modelo documentados oficialmente; llamada real bloqueada por falta de clave. |
| `validate_provider_configuration` | `backend/ai_providers.py` | AUSENTE | No existía diagnóstico centralizado sin revelar secretos. | Añadida función que devuelve solo estado configurado, modelo y notas de compatibilidad visual no verificada. Pruebas de ausencia de claves en salida pasan. |
| `classify_provider_error` | `backend/ai_providers.py` | AUSENTE | La excepción solo distinguía `transient`; no tenía categorías seguras para estado HTTP. | Añadida clasificación de autenticación, cuota, rate limit, timeout, solicitud inválida, servicio caído y errores HTTP. Tests de 400/401/403/408/429/5xx pasan. |
| `get_provider_health` | `backend/ai_providers.py` | AUSENTE | No existía estado por proveedor/modelo. | Añadido estado en memoria por proceso y conectado al endpoint administrativo `/api/admin/ai-monitor`. No es persistente ni distribuido. |
| Circuit breaker | Proveedores | NO APLICABLE POR AHORA, CON JUSTIFICACIÓN | No hay métricas de carga/latencia de producción ni almacenamiento compartido entre workers que permitan calibrar umbrales con seguridad. | No se añadió un breaker local que pudiera dar estados inconsistentes entre procesos. `get_provider_health` da visibilidad; reconsiderar breaker tras medir producción y definir almacenamiento compartido. |
| `record_token_usage` | `backend/ai_providers.py` | AUSENTE | No se registraban tokens de entrada/salida reales. | Añadido registro solo cuando el proveedor informa contadores; la fuente se marca `provider_reported`. No se inventan tokens ni coste. Tests pasan. |
| `record_provider_metrics` | `backend/ai_providers.py` | IMPLEMENTADO PARCIALMENTE | Existían timings de intentos en el contexto y eventos persistentes, pero no un registro uniforme de latencia/estado por proveedor en el contexto. | Añadido registro por proveedor, modelo, estado, latencia y categoría; se integra con el contexto de timings existente. No se crean tablas duplicadas. |
| `_generate_with_ocr_fallback` | `backend/main.py` | IMPLEMENTADO, PERO INCOMPLETO | OCR real ya existía, pero no compartía presupuesto de tiempo con visión y fallback textual. | Se aplica deadline global a la ruta completa y se limita cada llamada de Tesseract a un máximo de 3 s o al presupuesto restante. Tests de OCR y generación pasan. |
| `_ocr_text` / `_decode_ocr_image` | `backend/main.py` | IMPLEMENTADO Y VERIFICADO EN PRUEBAS LOCALES | Pillow/Tesseract, límites de bytes/píxeles y tests de imagen ya existían. | Se conserva el motor real; se añade timeout por ejecución OCR. La suite local incluye regresiones de OCR; el rendimiento de producción depende del entorno Tesseract instalado. |
| `analyze`, cuotas y liberación | `backend/main.py` | IMPLEMENTADO Y VERIFICADO POR REGRESIÓN | Las reservas y liberaciones de cuotas ya estaban implementadas. | No se reescribieron transacciones ni reglas de cuota. Tests existentes pasan. |
| Idempotencia y generación concurrente | `backend/main.py` | IMPLEMENTADO Y VERIFICADO POR REGRESIÓN | Existían clave idempotente, hash de payload, estados processing/completed/failed y bloqueo por análisis. | Se conservaron. Tests existentes de reintento, cuota e idempotencia/concurrencia pasan. No se hizo migración de esquema. |
| `_quality_estimate` | `backend/main.py` | IMPLEMENTADO, PERO HEURÍSTICO | La puntuación no es una evaluación semántica fiable. | Se mantiene y se documenta explícitamente como heurística. No se añade juez semántico con coste/latencia extra sin medir su beneficio. |
| Monitor de IA | `backend/main.py` | IMPLEMENTADO, PERO INCOMPLETO | El monitor persistente muestra eventos, latencias y puntuación, pero no estado efímero/configuración actual del proceso. | Añadidos `provider_health` y `provider_configuration` al JSON administrativo; la respuesta conserva sus claves previas. Tests de permisos y estructura pasan. |
| Costes monetarios | Métricas | BLOQUEADO POR FALTA DE TARIFAS VIGENTES POR CUENTA/MODELO | No hay catálogo de precios vigente y fiable dentro del proyecto. | No se inventan costes. Se registran tokens reales cuando están disponibles; calcular coste requiere tabla de tarifas versionada y su mantenimiento. |
| `run_provider_contract_tests` | Suite `tests/test_provider_contracts.py`, `tests/test_provider_resilience.py`, `tests/test_isolated.py` | NO APLICABLE COMO FUNCIÓN DE PRODUCCIÓN | Las pruebas deben ejecutarse mediante pytest, no desde el servidor web. | Se ampliaron las pruebas unitarias/contractuales. `python -m pytest -q` pasa con 98 pruebas más subtests y 4 smoke tests reales omitidos. |
| Pruebas de API reales | `tests/test_provider_integration.py` | BLOQUEADO POR FALTA DE CREDENCIALES | Son pruebas opt-in que hacen llamadas externas y pueden consumir saldo. | No se ejecutaron. Las cuatro pruebas reales continúan omitidas de forma intencional. |
| Asincronía | Capa HTTP | NO APLICABLE SIN MEDICIÓN | La implementación usa urllib síncrono, y la API FastAPI tiene endpoints síncronos. No se entregaron métricas de saturación que justifiquen una migración amplia. | Se mantuvo la arquitectura y se acotaron timeouts/esperas. Medir concurrencia en staging antes de migrar a un cliente async. |
| Historial Git / rama | Repositorio | BLOQUEADO POR FORMATO DEL ENTREGABLE | El ZIP no incluye `.git`. | No se sobrescribió historial ni se creó commit/branch/PR. Entrega en ZIP para que se revise y luego se aplique en el repositorio Git original. |

## 3. Cambios realizados

- `backend/ai_providers.py`
  - Clasificación segura de errores y parseo de `Retry-After` como segundos o fecha HTTP.
  - Retries con backoff exponencial, jitter, máximo acotado y deadline.
  - Presupuesto de tiempo compartido por ContextVar.
  - Validación estricta de `reply`/`alternative`, límite de longitud y similitud textual.
  - Diagnóstico de configuración sin secretos.
  - Estado de salud por proveedor/modelo, métricas de proveedor y captura de tokens reportados.
  - Eliminación de los cuerpos/mensajes arbitrarios de proveedor de los logs.
- `backend/main.py`
  - Un presupuesto común de 12 segundos abarca generación visual, OCR y generación textual alternativa.
  - Timeout por llamada de Tesseract.
  - Monitor administrativo con salud/configuración de proveedores sin claves.
  - Modelo predeterminado Groq actualizado por deprecación documentada; `GROQ_MODEL` de entorno sigue prevaleciendo.
- `backend/AI_PROVIDERS.md`
  - Documentación de reintentos, presupuesto, salud y límites de verificación real.
- `tests/test_provider_contracts.py`
  - La regresión de logs verifica que no se registren cuerpos de error ni texto de clave, incluso sanitizado.
- `tests/test_provider_resilience.py` (nuevo)
  - Clasificación HTTP, cuota, `Retry-After`, validación estricta, deadline, tokens reales reportados y ausencia de secretos en configuración.
- `tests/test_isolated.py`
  - Verifica las nuevas claves de estado/configuración del monitor sin quitar las claves previas.

## 4. Verificación final

- `python -m compileall -q backend tests`: **correcto**.
- `python -m pytest -q`: **98 passed, 4 skipped, 27 subtests passed**.
- Las 4 pruebas omitidas son los smoke tests de proveedores reales, protegidos por `RUN_REAL_PROVIDER_TESTS=1` y claves de entorno. No se reportan como exitosos.
- `ruff`, `flake8` y `mypy` no están instalados en el entorno; no se afirma que esos análisis hayan pasado.
- El escaneo estático final de secretos se debe volver a ejecutar sobre el paquete final; no se incorporaron credenciales reales durante esta ejecución.

## 5. Integraciones y documentación oficial consultada

La consulta de documentación confirma la forma de las APIs y el modelo Groq elegido como predeterminado; **no** verifica credenciales, cuota, disponibilidad de cuenta ni una llamada real desde este despliegue.

- Gemini Interactions API y entradas de imagen: https://ai.google.dev/gemini-api/docs/image-understanding y https://ai.google.dev/gemini-api/docs/interactions-overview
- Groq modelos y deprecaciones: https://console.groq.com/docs/models y https://console.groq.com/docs/deprecations
- Modelo Groq `openai/gpt-oss-120b`: https://console.groq.com/docs/model/openai/gpt-oss-120b
- OpenRouter Chat Completions: https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request
- Cohere Chat V2 y modelo Command R7B: https://docs.cohere.com/v2/reference/chat y https://docs.cohere.com/v2/docs/command-r7b

## 6. Riesgos restantes y pasos de despliegue

1. Revisar el diff contra el repositorio Git original antes de aplicar el ZIP; ese historial no estaba en el archivo recibido.
2. En staging, ejecutar `RUN_REAL_PROVIDER_TESTS=1 python -m pytest -q tests/test_provider_integration.py` con claves autorizadas y límite de gasto. Hacerlo proveedor por proveedor si se desea controlar el coste.
3. Validar explícitamente el nuevo default Groq. Si la cuenta tiene acceso Enterprise al modelo anterior, puede fijar `GROQ_MODEL` en el entorno; si no, el nuevo default documentado evita depender del modelo deprecado para planes no Enterprise.
4. Confirmar que `Tesseract` y los idiomas `spa`/`eng` están instalados en el entorno desplegado.
5. Revisar la métrica de coste con tarifas vigentes antes de activar cualquier cálculo monetario. Actualmente solo se guardan tokens cuando los devuelve el proveedor.
6. `get_provider_health` es local al proceso y se reinicia al reiniciar el servicio; no actúa como circuit breaker y no sustituye el historial persistente de eventos.
7. Después de revisar el ZIP y las pruebas, aplicar cambios en una rama del repositorio original, repetir la suite allí y abrir el pull request manualmente. No se ha hecho push ni despliegue.
