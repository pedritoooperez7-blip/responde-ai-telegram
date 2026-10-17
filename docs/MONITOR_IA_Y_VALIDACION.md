# Monitor de IA y criterios de validación

## Implementado en esta actualización
- Tabla `ai_generation_events` para registrar cada generación y cada reintento, con usuario interno, análisis, módulo, modo, proveedor/modelo, estado, categoría de error, latencia, puntuación heurística y número de reintento.
- El registro operacional no guarda imágenes, texto OCR, prompt, respuesta generada, claves ni cuerpos de error del proveedor.
- Endpoint `GET /api/admin/ai-monitor`, protegido en el backend por permiso `ai_analytics`.
- Pestaña «Monitor de IA» con indicadores, actividad reciente, proveedor/modelo, usuarios, análisis totales, generaciones, intentos gratuitos estimados restantes, tasa de éxito, errores y puntuación estimada.
- El propietario tiene el permiso. Los administradores secundarios solo lo reciben si se selecciona explícitamente al crearlos.
- Las respuestas incluyen proveedor, modelo y puntuación estimada. Las salidas que no contienen dos respuestas estructuradas y distintas ya no se convierten artificialmente en dos opciones.
- Los fallos y éxitos quedan registrados sin guardar contenido privado.

## Interpretación de métricas
- `quality_score` es una heurística técnica basada en longitud, diferencia textual y contexto disponible. No equivale a una evaluación semántica de exactitud ni garantiza que la respuesta sea buena.
- El número de intentos restantes representa el cupo gratuito diario. El reintento técnico pertenece a un análisis y aparece por separado en eventos.
- El panel informa de eventos registrados desde esta versión. No se reconstruye el historial de generaciones anterior al despliegue si ese dato nunca se guardó.
- Tokens y costes no se muestran: los adaptadores actuales no entregan métricas de consumo normalizadas para todos los proveedores. No se inventan valores.

## Comprobaciones
La suite aislada se ejecuta con:
`python -m unittest discover -s tests -v`

También puede comprobarse sintaxis con:
`python -m py_compile backend/main.py backend/ai_providers.py`

Las llamadas reales a proveedores y el despliegue Railway requieren claves válidas y acceso al entorno de producción; no quedan demostrados por pruebas con proveedores simulados.
