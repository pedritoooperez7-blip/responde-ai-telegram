# LiggaCuba — actualización de interfaz y administración

## Cambios incluidos
- Perfil Premium muestra beneficios, vencimiento y días restantes.
- El perfil permite guardar el teléfono; el backend devuelve el número guardado en `/api/profile`.
- La sesión de usuario conserva el token en `sessionStorage` y se vuelve a autenticar con Telegram al iniciar la Mini App.
- Métodos de pago en columna vertical; iPhone informa que estará disponible en futuras actualizaciones.
- La pantalla de transferencias tiene sección propia y controles de navegación internos para no chocar con el botón nativo de cerrar Telegram.
- Nuevo panel web `/admin.html` con dashboard, usuarios, cambios de Premium, revisión de pagos, administradores con permisos y auditoría.
- Las acciones administrativas quedan registradas en `admin_audit`.

## Variables de Railway
- `ADMIN_KEY`: obligatoria; clave secreta del administrador principal. Usa una clave larga y aleatoria. No la compartas ni la pongas en el frontend.
- `ADMIN_TELEGRAM_IDS`: IDs de Telegram autorizados a ver el acceso rápido de administración dentro del perfil de la Mini App, separados por coma. Ejemplo de formato: `123456789,987654321`.
- `DB_PATH`: opcional; ruta de la base de datos. Debe apuntar a almacenamiento persistente de Railway para no perder usuarios, administradores y auditoría tras un redeploy.
- Mantén configuradas las variables existentes `TELEGRAM_BOT_TOKEN`, `ATAJO_KEY`, `BANDEC_ACCOUNT` y `BPA_ACCOUNT` según tu despliegue.

## Acceso
- Web: abre `https://TU-DOMINIO/admin.html`.
- Telegram: configura `ADMIN_TELEGRAM_IDS`; los IDs autorizados verán el acceso de administración dentro del perfil. El acceso al panel sigue exigiendo autenticación.
- El administrador principal entra con `ADMIN_KEY` de Railway.
- Los administradores secundarios entran con usuario y contraseña creados desde el panel. La contraseña se guarda mediante PBKDF2-HMAC-SHA256 con salt aleatorio; el panel no vuelve a mostrarla.
- Permisos disponibles para administradores secundarios: `users`, `premium`, `payments` y `stats`. No se concede gestión de administradores ni privilegios de propietario.

## Seguridad y operación
- Antes de aprobar un pago manualmente, confirma que el dinero fue recibido realmente.
- La aprobación rechaza operaciones ya procesadas y no permite procesar una misma operación dos veces por este endpoint.
- Haz una copia de seguridad de la base de datos antes del despliegue.
- Después de desplegar, prueba autenticación de Telegram, guardado del teléfono, cada método de pago y el panel en el entorno de Railway.

## Verificaciones realizadas localmente
- `python -m py_compile backend/main.py`
- `node --check app.js`
- `node --check` del JavaScript del panel.
- Prueba con FastAPI TestClient: login principal, estadísticas, listado de usuarios/pagos/administradores/auditoría, creación de administrador secundario y login de dicho administrador.

No se ha desplegado este ZIP en Railway ni se ha modificado la base de datos de producción.
