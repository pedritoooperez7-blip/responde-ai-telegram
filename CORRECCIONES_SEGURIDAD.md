# Correcciones aplicadas a LiggaCuba

## Backend
- Los tokens administrativos del propietario incluyen una marca de rol firmada y se validan sin depender de una cuenta secundaria `owner`.
- Se agregó el permiso independiente `audit` para consultar el historial administrativo.
- La creación de administradores secundarios permite asignar `audit`, sin permitir `admins` ni `settings`.
- La aprobación y el rechazo de pagos usan una transacción SQLite `BEGIN IMMEDIATE` y actualización condicional del estado para evitar que dos solicitudes procesen simultáneamente la misma operación.
- Se conserva el registro de auditoría de aprobaciones y rechazos.

## Panel web
- La clave principal se envía en el cuerpo de la petición de inicio de sesión y ya no se guarda en `sessionStorage` ni se adjunta a todas las solicitudes posteriores.
- La interfaz oculta las pestañas según los permisos y verifica el permiso `audit` antes de cargar el historial.

## Validaciones ejecutadas
- `backend/main.py`: compilación sintáctica de Python correcta.
- JavaScript embebido de `admin.html`: `node --check` correcto.

## Límites de la revisión
Estas validaciones no sustituyen pruebas integrales contra una base de datos de prueba ni pruebas en Telegram/Railway. Antes del despliegue, configurar `ADMIN_KEY` y `TELEGRAM_BOT_TOKEN` como variables de entorno seguras y probar el flujo de pagos en staging.
