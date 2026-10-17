# Seguridad de autenticación y sesiones

## Variables de entorno obligatorias

- `TELEGRAM_BOT_TOKEN`: token real del bot de Telegram. Se usa para verificar la firma de Telegram Web Apps.
- `SESSION_SECRET`: secreto independiente para firmar las sesiones de LiggaCuba. Debe contener al menos 32 caracteres; usa un valor aleatorio fuerte y mantenlo fuera del repositorio.

Genera un secreto con un generador criptográficamente seguro (por ejemplo, `python -c "import secrets; print(secrets.token_urlsafe(48))"`) y configúralo como variable de entorno en el servicio de despliegue y en cada entorno de prueba. No lo publiques ni lo reutilices como token del bot.

Si `SESSION_SECRET` falta o tiene menos de 32 caracteres, el backend falla de forma cerrada al emitir o validar sesiones y responde con un error de configuración. Configúralo antes de desplegar esta versión. Cambiarlo invalida todas las sesiones de usuario firmadas con el secreto anterior; los usuarios tendrán que autenticarse de nuevo.

## Validación de Telegram Web App

El backend valida la firma HMAC, exige `auth_date` válido, rechaza datos con más de 24 horas y fechas futuras que excedan una tolerancia de 60 segundos, rechaza parámetros duplicados y comprueba que `user` sea un objeto JSON con un identificador positivo.

## Pruebas y límites

Las pruebas automatizadas locales usan credenciales ficticias y SQLite temporal. No prueban las credenciales reales de Telegram ni verifican la configuración de Railway. Antes de desplegar, configura las variables de entorno en staging y prueba el inicio de sesión desde la Mini App real.
