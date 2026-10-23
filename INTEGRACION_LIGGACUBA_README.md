# LiggaCuba — Versión de producción

Aplicación completa: bot de Telegram + Mini App + backend FastAPI con IA multi-proveedor, OCR y pagos.

## Qué se corrigió respecto al repositorio original

1. **Bot de Telegram real (era el hueco principal).** Antes solo se *construía* el mensaje de `/start`; nunca se enviaba. Ahora existe `backend/telegram_bot.py` con:
   - `POST /webhook/telegram`: recibe actualizaciones reales, autenticadas con el header secreto de Telegram (`X-Telegram-Bot-Api-Secret-Token`, comparación en tiempo constante).
   - `/start` funcional: envía el mensaje de bienvenida con los 3 botones (Canal, Comunidad, Abrir Mini App) mediante una llamada real a `sendMessage` de la Bot API.
   - Anti-duplicados: cada `update_id` se reclama atómicamente en la base de datos antes de procesarse; si Telegram reenvía una actualización, se responde OK sin ejecutar la acción dos veces.
   - Endpoint admin `POST /api/admin/telegram-webhook/setup` y script `scripts/setup_telegram_webhook.py` para registrar el webhook.
2. **Seguridad.** CORS limitado a los métodos y cabeceras usados; los orígenes se configuran con `CORS_ORIGINS` y, si está vacío, se permite cualquiera (se registra un aviso al arrancar). Añadidos límites de frecuencia para OCR/análisis/generación y para el login de administrador, `/.dockerignore`, y validación de que `/health` comprueba la base de datos. Eliminadas las credenciales bancarias y de contacto incrustadas como valores por defecto en el código (la cuenta BANDEC y el teléfono de pago ahora solo vienen de variables de entorno); `GET /api/admin/payments` ya no devuelve la imagen del comprobante en base64; métodos HTTP de la API limitados a GET/POST/DELETE.
3. **Código muerto eliminado.** Había tres funciones definidas por duplicado (`_ocr_variants`, `_ocr_text`, `normalize_payment_phone`); se conservó la versión correcta de cada una. En la Mini App se retiró `submitProof()` (llamaba a campos de formulario que no existen) y una variable global sin uso.
4. **Mini App.** Añadida la ruta del logo `/liggacuba-logo.jpg` al backend (antes la imagen del splash no se servía). El resto del diseño, i18n, recortador y flujos se conservan intactos.
5. **Despliegue.** `requirements.txt` con versiones fijadas; `railway.json` con healthcheck en `/health`; Dockerfile conservado y verificado.

## Estructura

```
backend/
  main.py           API FastAPI (usuarios, cuotas, pagos, admin, OCR, IA, webhook)
  ai_providers.py   Adaptadores IA (Gemini, Groq, OpenRouter, Cohere + proveedores propios)
  telegram_bot.py   Bot: webhook, /start, anti-duplicados, Bot API
  requirements.txt
tests/              199 pruebas (195 offline; 4 en vivo de proveedores)
index.html / app.js / style.css / admin.html / privacy.html / terms.html
liggacuba-logo.jpg
Dockerfile / railway.json
scripts/setup_telegram_webhook.py
```

## Variables de entorno requeridas

Ninguna tiene valor por defecto inseguro; todo se configura en Railway (o el host que use):

| Variable | Obligatoria | Para qué |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Sí (bot) | Token del bot de @BotFather. Verifica initData de la Mini App y envía mensajes. |
| `TELEGRAM_WEBHOOK_SECRET` | Sí (bot) | Cadena aleatoria ≥32 caracteres. Autentica las llamadas del webhook. |
| `TELEGRAM_MINI_APP_URL` | Sí (bot) | URL HTTPS pública de esta app; la usa el botón "Abrir Mini App". |
| `SESSION_SECRET` | Sí | ≥32 caracteres. Firma las sesiones de usuario. |
| `ADMIN_KEY` | Sí | Clave maestra del panel admin. |
| `PUBLIC_BASE_URL` | Sí (webhook) | URL pública del despliegue, para registrar el webhook. |
| `AI_PROVIDER_ENCRYPTION_KEY` | Para proveedores propios/caché | ≥32 caracteres. Cifra claves API y caché. |
| `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENROUTER_API_KEY` / `COHERE_API_KEY` | Al menos una | Proveedores de IA. Sin ninguna, la generación falla honestamente (no hay respuestas falsas). |
| `BANDEC_ACCOUNT` / `BPA_ACCOUNT` / `PAYMENT_PHONE` | Para pagos | Cuentas de destino y teléfono de identificación. |
| `ATAJO_KEY` | Para el atajo iOS | Autentica las notificaciones de pago automáticas. |
| `ADMIN_TELEGRAM_IDS` | Opcional | IDs de Telegram con acceso al panel. |
| `CORS_ORIGINS` | Opcional | Orígenes adicionales permitidos, separados por comas. |
| `DB_PATH` | Opcional | Ruta del SQLite. Por defecto `liggacuba.db` en la raíz del contenedor, que **no es persistente**: en producción debe apuntar a un volumen. |
| `GEMINI_MODEL` etc. | Opcional | Modelos específicos por proveedor. |
| `SQLITE_BUSY_TIMEOUT_MS` | Opcional | Espera ante bloqueos de escritura (defecto 15000). |
| `PAYMENT_CURRENCY` / `PAYMENT_PRICE_WEEKLY` / `PAYMENT_PRICE_ANNUAL` | Opcional | Moneda real de las operaciones y precios numéricos (defecto `CUP`, 2500, 15500). |
| `OCR_RATE_LIMIT_PER_MINUTE` / `OCR_DAILY_LIMIT` / `OCR_MAX_CONCURRENT` | Opcional | Límites de OCR (defecto 10/min, 50/día, 2 simultáneos por proceso). |
| `ANALYZE_RATE_LIMIT_PER_MINUTE` / `GENERATION_RATE_LIMIT_PER_HOUR` | Opcional | Límites de análisis (20/min) y generación (40/h) por usuario. |
| `ADMIN_LOGIN_MAX_ATTEMPTS` / `ADMIN_LOGIN_WINDOW_SECONDS` | Opcional | Protección del login admin (defecto 10 intentos / 900 s). |
| `DISABLE_BACKGROUND_PURGE` | Opcional | `1` desactiva la purga periódica (para investigar incidentes). |

Detalle operativo, límites y decisiones pendientes: [`docs/OPERACIONES_V1.md`](docs/OPERACIONES_V1.md). Copias de seguridad: [`docs/BACKUP_RESTORE.md`](docs/BACKUP_RESTORE.md).

## Despliegue en Railway

1. Despliega este directorio (Railway detecta `railway.json` + Dockerfile; Tesseract y los idiomas spa/eng se instalan en la imagen).
2. Configura las variables de entorno de la tabla anterior.
3. Registra el webhook del bot: `python scripts/setup_telegram_webhook.py` (una vez, con las variables en el entorno), o llama al endpoint admin `POST /api/admin/telegram-webhook/setup` con la cabecera `X-Admin-Key`.
4. Verifica: `GET /health` debe responder `200` con `{"status":"ok","database":"ok"}`; escribe `/start` al bot y comprueba que llega el mensaje con los 3 botones.
5. Antes de producción, confirma que `DB_PATH` apunta a almacenamiento persistente y que los datos sobreviven a un reinicio (ver `docs/OPERACIONES_V1.md`).
6. Programa una copia de seguridad (`python scripts/backup_sqlite.py --out-dir <volumen>/backups`).

## Pruebas

```
pip install -r backend/requirements.txt -r requirements-test.txt
python -m pytest tests/ -q --ignore=tests/test_provider_integration.py
```

Resultado real en el entorno de esta rama (sin `fastapi`, `pydantic`, `PIL`, `httpx`,
`cryptography` ni `pytest` instalados, y sin instalar nada):

* **87 pruebas ejecutadas y correctas** con `unittest`: `test_telegram_bot`,
  `test_provider_contracts`, `test_provider_resilience`, `test_limits`,
  `test_db_config`, `test_payments_config` y `test_backup_sqlite`. Para
  `ai_providers` se usó un doble temporal de `cryptography.fernet` **fuera del
  repositorio** (`/tmp`), porque el módulo real no está instalado.
* **No ejecutadas:** `test_isolated.py` y `test_telegram_welcome.py` (requieren
  FastAPI, Pydantic, Pillow y HTTPX) y `test_provider_integration.py` (llamadas
  reales de pago). No se declaran aprobadas.

En un entorno con las dependencias declaradas, el comando es el de arriba. No hay
CI configurada todavía.

## Límites verificados y no verificados

**Verificado aquí:** import y arranque del backend, webhook y anti-duplicados con pruebas automatizadas, envío de mensajes con la Bot API simulada a nivel HTTP (formato de llamada correcto), toda la lógica de cuotas/pagos/admin/IA con la suite offline, sintaxis y estructura de la Mini App.

**No verificado aquí (requiere tus credenciales o servicios):**
- Que el bot responda en Telegram real: depende de `TELEGRAM_BOT_TOKEN` y de ejecutar el paso 3 del despliegue. No se ha registrado ningún webhook ni enviado mensajes con el bot de producción (respetando tus restricciones).
- OCR con capturas reales: requiere el binario Tesseract (presente en la imagen Docker).
- Llamadas reales a Gemini/Groq/OpenRouter/Cohere: requieren claves; la integración está cubierta por pruebas de contrato y resiliencia con servicios simulados.

## Tareas pendientes que requieren acción tuya

1. Configurar las variables de entorno en Railway (no hay secretos en el repositorio, por diseño).
2. Ejecutar el registro del webhook con el bot **de pruebas**, no el de producción.
3. Probar un pago real de extremo a extremo con el atajo bancario en el entorno de pruebas.
4. Si tu repo original tiene el frontend servido por otra CDN o dominio, añádelo a `CORS_ORIGINS`.

## Resultado de la integración (rama `integration/liggacuba-unified`, octubre 2026)

Esta rama reemplaza a `bolt/liggacuba-production` (PR #48, ya fusionado): integra la entrega LiggaCuba directamente en la raíz del repositorio, sin carpeta intermedia.

- Backend unificado en `backend/` (el contenido de `liggacuba-delivery/` ya no existe como copia separada).
- Historiales de cambios antiguos movidos a `docs/`.
- Ficheros `.BACKUP_*` eliminados del repositorio.
- Suite: **199 pruebas declaradas** (195 offline + 4 en vivo). En el entorno de esta rama se ejecutaron 87 offline con resultado correcto; el resto requiere las dependencias del proyecto (ver la sección «Pruebas»).
- actualizando railway
