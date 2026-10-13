# Informe de completitud del flujo de análisis y generación de respuesta

## Versión

API backend: `2.2`.

## Alcance de esta entrega

Esta versión endurece el flujo desde la selección de imagen hasta la respuesta, añade pruebas de regresión y prepara una ejecución real aislada de los cuatro proveedores. El ZIP original no se sobrescribe. La implementación se ha probado localmente con SQLite temporal y credenciales ficticias; no se han llamado las API reales ni se ha desplegado en Railway desde este entorno.

## Cambios implementados

- Validación de la imagen antes de reservar el cupo diario: Base64 estricto, MIME coherente con el formato real, lista de formatos permitidos, límite de bytes, límite de píxeles, decodificación completa y tratamiento de avisos de descompresión como errores.
- El cliente envía la imagen al endpoint de análisis para validar antes de cobrar el cupo, y reutiliza los mismos bytes para la generación.
- Si la primera generación falla antes de entregar una respuesta válida, se devuelve el cupo gratuito reservado; un reintento fallido libera la reserva de reintento.
- Clave de idempotencia por usuario, validación de que una misma clave no se reutilice con otro payload, almacenamiento temporal del resultado y recuperación del resultado si se pierde la respuesta HTTP. Los resultados de idempotencia se eliminan tras 24 horas mediante una tarea de limpieza horaria; la telemetría IA se conserva hasta 30 días y la auditoría de seguridad hasta 90 días.
- Bloqueo transaccional de generación, recuperación de bloqueos abandonados tras 180 segundos y prevención de dos generaciones simultáneas para el mismo análisis.
- El fallo al guardar métricas de observabilidad ya no debe convertir una respuesta válida del proveedor en un error visible.
- Fechas nuevas en UTC con zona horaria; las fechas antiguas sin zona se interpretan como UTC para mantener compatibilidad.
- OCR autenticado también en `/ocr-base64` y `/ocr-base64-simple`.
- Pruebas contractuales offline para los adaptadores Gemini, Groq, OpenRouter y Cohere; matriz de formatos de imagen; OCR real con Tesseract sobre una captura sintética tipo Telegram; y fallback visual→OCR→proveedor de texto.
- Runner, Dockerfile y configuración sin reinicios automáticos separados para ejecutar las llamadas reales a proveedores en Railway sin cambiar el contenedor web de producción.

## Resultados de validación local

Última ejecución antes del empaquetado:

- `pytest`: 59 aprobadas, 4 omitidas intencionalmente (smoke tests reales), 13 subtests aprobados, 0 fallos.
- `python -m py_compile` para backend y pruebas: aprobado.
- `node --check app.js`: aprobado.
- OCR real con Tesseract sobre captura sintética: aprobado.

Las pruebas omitidas requieren credenciales reales y `RUN_REAL_PROVIDER_TESTS=1`. El runner de Railway aborta si falta cualquiera de las cuatro claves. No se han probado aún las credenciales, los límites de cuota ni la disponibilidad real de los modelos configurados en Railway.

## Estado de aceptación

| Criterio | Estado | Evidencia / pendiente |
|---|---|---|
| Autenticación de sesiones y OCR | Aprobado local | Pruebas de rutas autenticadas; despliegue real pendiente |
| Cuota diaria concurrente | Aprobado local | Pruebas de concurrencia existentes y de regresión |
| Validación de imagen y cuota | Aprobado local | MIME, formatos, Base64, bytes, píxeles, imagen dañada y cuota sin cargo |
| Adaptadores de proveedores | Aprobado por contrato simulado | Respuestas HTTP simuladas; smoke test real pendiente |
| API real Gemini/Groq/OpenRouter/Cohere | Bloqueado | Requiere ejecutar el runner aislado con secretos en Railway |
| Flujo completo visual→respuesta | Aprobado en pruebas aisladas | Proveedor simulado; credenciales reales pendientes |
| Fallback OCR | Aprobado en prueba sintética local | Falta validar capturas reales de Telegram de producción con permiso del usuario |
| Concurrencia, locks e idempotencia | Aprobado local | Incluye repetición de clave, payload diferente, lock abandonado y generación simultánea |
| Resiliencia de logging | Aprobado local | La caída de almacenamiento de eventos no impide devolver una respuesta válida |
| Calidad semántica | Parcial | El score actual es heurístico y diagnóstico; falta dataset etiquetado y evaluación humana/semántica |
| Retención y borrado en producción | Parcial | Limpieza horaria de idempotencia (24 h), eventos IA (30 días) y auditoría (90 días) implementada; falta confirmar backups/retención del volumen SQLite de Railway |
| Despliegue y secretos | Parcial | Runner aislado documentado; no desplegado ni inspeccionado en Railway desde esta sesión |
| Pull request GitHub | No realizado | No hay conexión de GitHub ni permiso de repositorio disponible en esta sesión |

## Límites y riesgos residuales

- Ningún sistema distribuido puede garantizar exactamente una llamada externa si el proceso cae después de que el proveedor procese la solicitud y antes de persistir el resultado. La clave de idempotencia cubre las repeticiones posteriores a un resultado guardado; una interrupción en esa ventana puede provocar una segunda llamada al proveedor.
- El OCR se ha probado con una captura sintética generada en pruebas, no con capturas reales de usuarios. No se incluye contenido personal de chats como fixture.
- El score de calidad es heurístico, no una evaluación semántica fiable ni una garantía de que la respuesta sea adecuada al contexto.
- Los logs operativos no deben contener claves, imagen, OCR, prompts ni respuestas. Los registros de eventos existentes conservan metadatos; los backups y retención del almacenamiento dependen de la configuración del despliegue.
- Los tests de proveedores reales pueden consumir cuota. Ejecutarlos en un servicio separado evita interferir con el proceso web, pero no separa el coste si se reutilizan las mismas claves/cuentas.

## Veredicto

El flujo local está considerablemente más cubierto y las pruebas automatizadas pasan. No es correcto declararlo completamente validado en producción hasta ejecutar los cuatro smoke tests reales, revisar sus logs, probar el servicio desplegado y evaluar la calidad con casos reales autorizados. No se afirma una garantía absoluta de “100 %”.
