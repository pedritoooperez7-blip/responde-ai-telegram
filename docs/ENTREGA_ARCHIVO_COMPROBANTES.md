# Entrega técnica — archivo de comprobantes por Telegram

## Incluido

- Cola de archivo persistente SQLite `payment_proof_archive_queue`.
- Worker de segundo plano que recoge trabajos pendientes y recupera trabajos `processing` abandonados.
- Reintentos indefinidos con backoff exponencial (30 segundos iniciales, máximo de 6 horas).
- Conservación del texto/imagen original en `payment_operations` hasta que Telegram confirme y la referencia del mensaje quede persistida.
- Limpieza de las copias grandes de SQLite únicamente después de confirmar el archivo.
- Campos de estado, intentos, próximo intento, último error, fecha archivada y referencias Telegram en el endpoint administrativo.
- Panel administrativo actualizado para mostrar el estado y las referencias del archivo.
- Advertencia de configuración cuando falta `PAYMENT_ARCHIVE_CHAT_ID`.
- Pruebas offline multipart para `send_photo()` y rechazo de Telegram.

## Configuración necesaria

En Railway, antes de probar el flujo, establecer `PAYMENT_ARCHIVE_CHAT_ID` al ID de un grupo/canal privado donde el bot tenga permiso para publicar. `DB_PATH` debe apuntar al volumen persistente ya usado por el servicio. No cambiar la ruta de una base existente sin plan de migración/backup.

Si `PAYMENT_ARCHIVE_CHAT_ID` no existe, el sistema mantiene el comprobante en SQLite y no lo manda a Telegram.

## Garantías y límites

- Los fallos de entrega quedan en cola y se reintentan sin un máximo de intentos.
- Un timeout ambiguo puede duplicar un mensaje si Telegram lo aceptó y la respuesta se perdió. Telegram no ofrece idempotency key para estos métodos. En esa situación se prioriza no perder comprobantes.
- La referencia mostrada al administrador es el chat ID y message ID; el administrador debe tener acceso al chat privado. No se genera un enlace navegable porque un chat privado no proporciona un enlace universal sin conocer su formato/identificador público.
- El worker se ejecuta por proceso y usa transacciones SQLite para reclamar trabajos. Se recomienda mantener un solo worker de aplicación o verificar comportamiento bajo múltiples réplicas antes de aumentar réplicas.
- No se probaron credenciales reales ni se hizo envío a Telegram, Railway o pagos reales.

## Validación ejecutada en el entorno de construcción

- `python -m py_compile backend/main.py backend/telegram_bot.py tests/test_telegram_bot.py`: correcto.
- `node --check app.js`: correcto.
- `node --check` sobre el JavaScript inline de `admin.html`: correcto.
- `python -m unittest tests.test_telegram_bot -v`: 18/18 correctas.
- `python -m unittest discover -s tests`: 201 pruebas descubiertas; 4 fallaron y 4 fueron omitidas. Los cuatro fallos están en pruebas de coincidencia de pagos automáticos de `tests/test_isolated.py`: BANDEC, BPA, duplicado BANDEC y Saldo Móvil devuelven `unmatched`. No se modificó la lógica del endpoint automático en esta entrega, pero no se ejecutó el ZIP original sin cambios para demostrar que estos fallos ya existían. Por tanto, no se declara la suite completa aprobada.

## Siguiente paso recomendado

Subir esta entrega a una rama distinta de `main`, ejecutar CI y corregir/entender primero los cuatro fallos de pagos automáticos. Después hacer una prueba controlada con el canal de archivo configurado, verificando: envío exitoso, Telegram no disponible, reinicio con trabajos pendientes y confirmación de que las pruebas fallidas conservan el comprobante en SQLite.
