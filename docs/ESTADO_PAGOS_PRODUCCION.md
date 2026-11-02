# Estado del sistema de pagos — LiggaCuba V1

**Actualizado:** 2026-11-02  
**Fuente:** ZIP `responde-ai-telegram-main 42.zip` adjunto en la conversación  
**Alcance:** pagos manuales y automáticos, Mini App, panel administrativo, archivo Telegram y pruebas offline.

## Cambios realizados

### Pagos automáticos
- Corregida la lectura de importes almacenados en `sqlite3.Row` en `backend/payments.py`; el matcher ya puede comparar correctamente el importe y la moneda guardados.
- BANDEC, BPA y Saldo Móvil vuelven a coincidir con operaciones pendientes en las pruebas.
- Se mantiene la detección de duplicados y la activación de Premium dentro de la transacción SQLite.
- Se rechazan operaciones con planes inválidos en el camino automático.

### Pagos manuales
- Restaurado en la Mini App el formulario para enviar comprobante como imagen y/o texto.
- La imagen se limita en frontend a 2.1 MB para mantenerse bajo el límite del payload base64 del backend; backend valida formato, contenido y tamaño.
- El envío del comprobante solo cambia el estado a `proof_submitted`; no activa Premium.
- Añadido endpoint administrativo protegido para consultar comprobantes locales.
- El panel de administración incorpora visor de texto e imagen del comprobante.
- Añadidas pruebas para aprobación manual, rechazo, duplicación de aprobación y acceso autorizado al comprobante.

### Estados y robustez
- La consulta de estado del usuario devuelve también `premium_until`.
- La Mini App actualiza los estados `verified`, `proof_submitted`, `rejected` y `cancelled`.
- Corregida la concurrencia de envío de comprobante para evitar que una operación cerrada sea reabierta por una carrera.
- Mejorado el cierre de conexiones de cancelación y conservada la actualización condicional para impedir cancelar una operación que ya está procesándose.
- El usuario puede iniciar una nueva operación tras rechazo o cancelación.
- La lista de precios pública se obtiene del backend mediante `/api/payments/pricing`, usando la misma configuración que crea las operaciones. Se eliminó el precio USD fijo que podía no coincidir con el importe cobrado.
- La migración de índices únicos no detiene el arranque si una base antigua contiene duplicados; el endpoint sigue serializando y verificando las transacciones.
- Se eliminó el porcentaje fijo de descuento anual de la etiqueta para evitar mostrar una promoción incorrecta cuando cambien los precios.

### Archivo de comprobantes
- Se conserva la cola persistente existente `payment_proof_archive_queue`.
- El comprobante original permanece en SQLite hasta que Telegram confirma el envío y se registra el `message_id`; después se limpian los datos grandes locales.
- Los errores de Telegram mantienen el comprobante en cola con reintentos.

## Pruebas realizadas

- `python -m pytest -q`: **201 passed, 4 skipped, 0 failed**.
- `node --check app.js`: correcto.
- JavaScript inline de `admin.html`: correcto.
- `python -m py_compile backend/main.py backend/payments.py`: correcto.
- Las pruebas usan SQLite temporal y secretos ficticios; no realizan transferencias reales ni envían comprobantes a Telegram.

## Variables de entorno a confirmar en Railway

- `DB_PATH`: ruta dentro del volumen persistente.
- `ATAJO_KEY`: debe coincidir con el secreto del Atajo de Apple enviado en `x-atajo-key`.
- `BANDEC_ACCOUNT` y `BPA_ACCOUNT`: destinos reales configurados y mostrados al usuario.
- `PAYMENT_CURRENCY`: moneda comercial, por defecto `CUP`.
- `PAYMENT_PRICE_WEEKLY` y `PAYMENT_PRICE_ANNUAL`: opcionales; si no existen se usan los precios por defecto del módulo.
- `PAYMENT_ARCHIVE_CHAT_ID`: grupo/canal privado donde se archivan los comprobantes; el bot necesita permiso para publicar.
- `TELEGRAM_BOT_TOKEN`: token válido para el archivo y el webhook.

## Validación obligatoria antes de producción

1. Desplegar primero en una rama/servicio de staging, no directamente sobre `main`.
2. Confirmar volumen persistente y hacer backup previo de SQLite.
3. Probar una operación de cada plan y método con importe controlado.
4. Probar el Atajo real de iPhone para BANDEC/BPA y Saldo Móvil, incluyendo reintento de la misma notificación.
5. Probar pago manual: envío de imagen, visualización en admin, aprobación, rechazo y Premium.
6. Probar archivo Telegram, fallo temporal, reinicio con cola pendiente y confirmación de limpieza local tras archivado.
7. Verificar que el usuario ve el estado correcto y la fecha de vencimiento de Premium.

## Limitaciones conocidas

- El backend no puede autenticar criptográficamente el SMS bancario que recibe el Atajo. La seguridad depende de proteger `ATAJO_KEY` y de validar los campos recibidos.
- Telegram no ofrece una clave de idempotencia para `sendPhoto`/`sendMessage`; un timeout ambiguo puede producir un mensaje duplicado en el grupo, aunque el comprobante no se pierde.
- Las pruebas offline no sustituyen una prueba real con Railway, el Atajo instalado y el grupo de archivo configurado.
