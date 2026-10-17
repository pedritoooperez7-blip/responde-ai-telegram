# Informe de entrega — Monitor de IA y flujo de generación

## Cambios
- Se agregó el registro operacional `ai_generation_events` con eventos de éxito y error por generación/reintento.
- Se registran proveedor, modelo configurado, estado, categoría de error, latencia, número de reintento y puntuación heurística.
- Se evita guardar capturas, OCR, prompts, respuestas o claves en el monitor; además, el registro de errores no imprime mensajes de excepción ni trazas potencialmente sensibles.
- Se agregó `/api/admin/ai-monitor`, protegido por `ai_analytics` en el backend.
- Se añadió la pestaña «Monitor de IA» con indicadores, actividad reciente, proveedores/modelos, datos agregados por usuario y eventos recientes.
- Se habilitó el permiso `ai_analytics` para el administrador principal y como permiso opcional para administradores secundarios.
- Las respuestas incluyen proveedor, modelo y puntuación estimada; se rechazan respuestas no estructuradas en lugar de fabricar una segunda respuesta.
- Se alineó el modelo predeterminado de Gemini con `gemini-2.5-flash` y se actualizó la documentación de proveedores.
- Se añadieron pruebas de autenticación, permisos, registro de eventos y protección de datos.

## Comprobaciones ejecutadas
- `python -m unittest discover -s tests -v`: **33 pruebas aprobadas**.
- `python -m py_compile backend/main.py backend/ai_providers.py`: correcto.
- `node --check` del JavaScript incrustado en `admin.html`: correcto.

## Limitaciones que deben quedar claras
- Las pruebas de proveedores usan mocks donde corresponde; no se hicieron llamadas reales porque este entorno no dispone de las claves de proveedor del despliegue.
- No se pudo verificar Railway en producción ni ejecutar un recorrido real con Telegram y credenciales activas.
- El score 1–100 es una heurística diagnóstica, no una evaluación semántica objetiva.
- Tokens y costes no aparecen como métricas porque los adaptadores actuales no exponen datos de consumo uniformes y verificables para todos los proveedores.
- Los eventos nuevos empiezan a registrarse después de desplegar esta versión; no se pueden reconstruir eventos históricos que nunca se almacenaron.
- Persisten advertencias de obsolescencia de `datetime.utcnow()` en el proyecto; no impidieron que las pruebas pasaran.
