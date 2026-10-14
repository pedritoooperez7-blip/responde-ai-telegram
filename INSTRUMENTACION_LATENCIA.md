# Instrumentación limitada de latencia

Esta modificación añade diagnóstico por solicitud sin cambiar el orden de proveedores, timeouts, reintentos, OCR ni la generación de respuestas.

## Métricas

La respuesta exitosa de `/api/generate-reply` incluye `timings_ms`:

- `visual_generation_ms`: duración de la ruta inicial de generación con imagen, incluidos los intentos internos del adaptador.
- `retry_count`: cantidad de reintentos transitorios internos.
- `retry_wait_ms`: tiempo acumulado esperando antes de reintentar.
- `retry_call_ms`: tiempo acumulado consumido por las llamadas de reintento.
- `provider_attempts`: duración y resultado de cada intento por proveedor, sin registrar prompts, imágenes ni respuestas.
- `ocr_ms`: duración de la extracción OCR cuando se usa la alternativa.
- `alternative_generation_ms`: duración de la generación basada en texto después del OCR.
- `total_backend_ms`: tiempo transcurrido desde el inicio de la generación hasta que el backend prepara el resultado para la persistencia. Se calcula antes de guardar el resultado idempotente para evitar una escritura adicional de telemetría. No incluye el registro posterior del evento de éxito, el transporte de red hasta el teléfono ni el renderizado de la interfaz.

Se emite también un registro de backend `AI generation timing` con el mismo objeto de métricas. No se agregan imágenes, OCR, prompts, respuestas ni credenciales a esos registros.

## Límites conocidos

- Si la ruta visual tiene éxito, `ocr_ms` y `alternative_generation_ms` serán cero porque no se ejecutó el fallback.
- `visual_generation_ms` incluye el tiempo total del adaptador en la ruta visual; `provider_attempts` permite separar cada proveedor.
- Las métricas aparecen en la respuesta JSON y en los logs del backend; esta modificación no cambia el diseño del panel HTML.
- `total_backend_ms` es tiempo del backend, no latencia de extremo a extremo medida desde el cliente.
