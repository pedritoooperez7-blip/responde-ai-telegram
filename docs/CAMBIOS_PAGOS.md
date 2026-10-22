# LiggaCuba — cambios revisados para pagos automáticos

Esta copia conserva la estructura del proyecto y actualiza el backend y la interfaz de pagos para trabajar con los atajos Apple existentes, sin exigir que cambien el formato del payload.

## Cambios incluidos
- Acepta los campos actuales de BANDEC/BPA y Saldo Móvil en `/api/atajo-pago`.
- El atajo bancario puede seguir enviando `metodo_pago: BANDEC_BPA`; el backend valida la cuenta de destino configurada sin intentar adivinar qué banco emitió el SMS.
- Conserva BANDEC y BPA como opciones distintas al crear la operación, para mostrar la cuenta correcta en la interfaz.
- Corrige la normalización de números y compara móviles cubanos tanto con el prefijo `53` como sin él.
- Valida en Saldo Móvil el formato del SMS, el teléfono y el importe recibido que aparece en el texto original.
- Rechaza coincidencias ambiguas, transacciones duplicadas y cuentas de destino no configuradas.
- Usa una transacción SQLite para marcar el pago como verificado y activar Premium conjuntamente.
- Conecta los botones de selección de método, guardar teléfono y copiar destino de la interfaz.

## Configuración necesaria en Railway
1. `ATAJO_KEY`: debe coincidir exactamente con la clave enviada por el encabezado `x-atajo-key` del atajo.
2. `BANDEC_ACCOUNT`: cuenta BANDEC de destino.
3. `BPA_ACCOUNT`: cuenta BPA de destino; necesaria si se ofrece BPA.
4. `DB_PATH`: mantener la ruta de base de datos persistente que ya use el proyecto. No cambiarla durante la integración.

## Pruebas recomendadas antes de desplegar
- Trabajar en una rama separada y abrir un PR; no reemplazar `main` directamente.
- Probar con una copia de la base de datos y SMS de ejemplo, sin dinero real.
- Verificar por separado BANDEC, BPA y Saldo Móvil, incluyendo teléfono con y sin prefijo `53`.
- Confirmar que repetir la misma notificación no vuelve a activar Premium.
- Confirmar que el método y el importe coinciden con la operación pendiente.

## Límites importantes
- El atajo bancario no manda el SMS completo, así que la huella de duplicados se forma con los campos extraídos y depende de la clave compartida del atajo.
- El SMS de Saldo Móvil no incluye una referencia bancaria única; se usa la huella del SMS original.
- El backend no puede demostrar criptográficamente que un SMS recibido por el teléfono sea auténtico. La clave del atajo debe mantenerse privada y no compartirse.

## Validación técnica realizada
- Sintaxis Python: correcta.
- Sintaxis JavaScript: correcta.
- Prueba aislada de BANDEC: verifica pago y rechaza repetición.
- Prueba aislada de BPA: entrega la cuenta BPA configurada.
- Prueba aislada de Saldo Móvil: verifica pago, rechaza repetición y rechaza un importe distinto al SMS.
- Estas pruebas usan una base SQLite temporal; no se conectan a Railway ni procesan dinero real.


## Archivo de comprobantes en Telegram (cola persistente y reintentos)

- Configurar `PAYMENT_ARCHIVE_CHAT_ID` con el ID del grupo/canal privado de archivo y añadir el bot con permiso para enviar mensajes y fotos.
- Los comprobantes se guardan en una cola persistente SQLite (`payment_proof_archive_queue`) y se procesan en segundo plano. Los reinicios conservan la cola si `DB_PATH` apunta a un volumen persistente.
- Los fallos se reintentan indefinidamente con backoff exponencial desde 30 segundos hasta un máximo de 6 horas. Los trabajos `processing` abandonados se recuperan después de 5 minutos.
- El texto y la imagen originales permanecen en `payment_operations` hasta que Telegram devuelve un `message_id` y la base guarda la referencia. Después se limpian las copias grandes de SQLite.
- El panel administrativo muestra estado del archivo, intentos, último error y referencias del chat/mensaje de Telegram. Para un chat privado, el administrador debe pertenecer al grupo/canal.
- Si no se configura `PAYMENT_ARCHIVE_CHAT_ID`, el comprobante permanece en SQLite y el arranque registra una advertencia.
- Un timeout ambiguo después de que Telegram acepte el mensaje puede producir duplicados en un reintento: Telegram Bot API no ofrece una clave de idempotencia para `sendPhoto`/`sendMessage`. Se prioriza no perder el comprobante.
- No se modifican las reglas de pagos automáticos/manuales ni la concesión de Premium.

## Validación de esta entrega ZIP
- Sintaxis Python de los módulos modificados: correcta (`py_compile`).
- Suite offline: 199 pruebas descubiertas, 4 fallos y 4 omitidas. Los cuatro fallos están en las pruebas del atajo de pagos y devuelven `unmatched` en lugar de los resultados esperados; no afectan directamente al archivo de comprobantes, pero impiden declarar la suite completa como aprobada.
- No se realizaron llamadas reales a Telegram, Railway, proveedores de IA ni pagos. Antes de producción hay que ejecutar CI y una prueba controlada en una rama/PR.
