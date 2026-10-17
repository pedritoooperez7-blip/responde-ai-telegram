# Actualización integrada: Telegram /start y flujo de IA

## Comportamiento de `/start`

El backend incorpora `POST /telegram/webhook`. El bot solo responde al comando `/start`: envía un mensaje de bienvenida y tres botones inline (canal oficial, comunidad y Mini App). Los demás mensajes se ignoran; no se activa generación de respuestas dentro del chat del bot.

En Railway, configurar:

- `TELEGRAM_BOT_TOKEN`: token del bot existente.
- `TELEGRAM_WEBHOOK_SECRET`: secreto aleatorio para autenticar los webhooks entrantes (recomendado; si se configura, Telegram debe enviar el mismo secreto al webhook).
- `TELEGRAM_MINI_APP_URL`: opcional; por defecto usa la Mini App publicada en `https://responde-ai-telegram-production-6cdc.up.railway.app/`.

La URL del webhook que se registra en Telegram es `https://<dominio-publico-del-backend>/telegram/webhook`. Debe registrarse usando el método `setWebhook` de Telegram y el `secret_token` debe coincidir con `TELEGRAM_WEBHOOK_SECRET`. Este cambio no registra automáticamente el webhook ni modifica la configuración de Telegram.

## Resiliencia de proveedores

Los adaptadores OpenAI-compatible ahora reconocen respuestas `{ "error": ... }` incluso cuando el proveedor devuelve HTTP 200. Las convierten en categorías operativas seguras (autenticación, cuota, rate limit, servicio no disponible o error del proveedor), sin registrar el cuerpo privado de la respuesta. Esto evita clasificar esos casos como un simple error de estructura.

Las credenciales rechazadas (por ejemplo, HTTP 403 de Groq) no se reintentan como si fueran fallos transitorios. Los fallos temporales siguen sujetos al presupuesto global, reintentos acotados y failover existente. No se crea una respuesta local falsa cuando fallan todos los proveedores.

## Validación ejecutada

- `python -m py_compile backend/main.py backend/ai_providers.py`
- `python -m unittest tests.test_provider_resilience -v`
- `python -m unittest tests.test_telegram_welcome -v`

Estas comprobaciones son locales y offline; no prueban credenciales reales, disponibilidad de los proveedores, despliegue Railway ni recepción real del webhook de Telegram.
