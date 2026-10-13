# Proveedores de IA de LiggaCuba

La capa común está en `backend/ai_providers.py`. Las claves se configuran únicamente como variables de entorno del servidor (por ejemplo, en Railway); nunca en `app.js`, HTML ni el repositorio.

Variables opcionales:

- `GEMINI_API_KEY` y opcionalmente `GEMINI_MODEL` (por defecto `gemini-3.8-flash`): texto e imágenes.
- `GROQ_API_KEY` y opcionalmente `GROQ_MODEL` (por defecto `llama-3.3-70b-versatile`): texto.
- `OPENROUTER_API_KEY` y opcionalmente `OPENROUTER_MODEL` (por defecto `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`): texto e imágenes si el modelo elegido las admite.
- `COHERE_API_KEY` y opcionalmente `COHERE_MODEL` (por defecto `command-r7b-12-2024`): texto.

Se intentan solo los proveedores configurados y capaces de atender el tipo de petición. Errores temporales (HTTP 408, 425, 429 y 5xx o problemas de conexión) admiten hasta dos intentos en total (una repetición), con espera progresiva y respeto de `Retry-After` limitado a 30 segundos. Errores permanentes no se reintentan. Si ningún proveedor produce dos respuestas estructuradas y diferentes, la solicitud falla con un error recuperable para que el usuario pueda usar el reintento disponible; no se inventa una segunda respuesta.

El análisis visual usa la misma ruta de generación para Chat y Estado/Story. La imagen sigue limitada a 8 MB y a formatos de imagen admitidos por el OCR. No se registra el contenido de la imagen ni las claves. Las capacidades, cuotas y disponibilidad reales dependen de la cuenta, modelo y proveedor configurados.

## Pruebas reales aisladas (opt-in)

`tests/test_provider_integration.py` contiene smoke tests que llaman a cada API real por separado. No se ejecutan en la suite normal. Pueden consumir saldo/cuota y solo deben lanzarse en un entorno de pruebas separado del bot activo:

```bash
RUN_REAL_PROVIDER_TESTS=1 python -m pytest -q tests/test_provider_integration.py
```

Cada prueba exige su propia variable (`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` o `COHERE_API_KEY`) y desactiva los otros proveedores para impedir que un fallback oculte un fallo. Las claves se leen desde el entorno, no se imprimen y no deben añadirse a archivos, capturas, logs ni commits. Si una clave no está presente, esa prueba queda omitida; un resultado omitido no equivale a una integración validada.

**Importante:** no ejecutes estas pruebas dentro del proceso web del bot ni contra producción sin una ventana aprobada. Con acceso solo al panel de Railway, no se puede asumir que exista una consola de comandos disponible. Lo correcto es usar un servicio de staging aislado con variables de entorno propias, o ejecutar el test desde un runner privado que tenga las claves inyectadas como secretos. No copies claves a este chat ni al repositorio.

## Railway: ejecutar smoke tests reales sin tocar el servicio activo

Se añadió `Dockerfile.provider-tests` y `scripts/run_live_provider_tests.py` para ejecutarlos como un **servicio separado de una sola ejecución**. No cambies el Dockerfile del servicio de producción.

1. En Railway, crea un servicio nuevo desde el mismo repositorio y asígnale el nombre `ai-provider-smoke-tests`.
2. En la configuración de ese servicio, selecciona `Dockerfile.provider-tests` como Dockerfile y configura la política de reinicio como `Never` (también se incluye `railway.provider-tests.json` como referencia). Esto evita repetir pruebas y consumir cuota si un test falla.
3. Configura en ese servicio las cuatro variables secretas (`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `COHERE_API_KEY`) y, si hace falta, los cuatro nombres de modelo. No copies los valores al repositorio ni a este chat.
4. Usa credenciales de prueba o límites de gasto/cuota en cada proveedor cuando estén disponibles. Aunque este servicio esté aislado del bot, las llamadas consumen cuota de las cuentas cuyas claves se configuren.
5. Despliega el servicio y revisa sus logs de ejecución. El runner falla si falta alguna clave o si una prueba real falla; no imprime los valores secretos. Tras la ejecución, detén o elimina el servicio temporal.
6. No conectes este runner a la base de datos de producción. Las pruebas de proveedores no necesitan `DB_PATH`, token del bot ni credenciales de administración.

Este procedimiento prueba las credenciales y los modelos configurados en el runner. No prueba por sí solo el webhook de Telegram, el despliegue del servicio web ni los permisos de producción. Con el acceso actual solo al panel, no se ha ejecutado aquí un despliegue ni se afirma que las cuatro API hayan pasado.


### Latencia y failover

Las llamadas HTTP tienen un timeout de 8 segundos por intento. En un flujo interactivo, si un proveedor devuelve un `Retry-After` superior a 2 segundos, el adaptador no espera ese periodo: abandona ese proveedor y prueba el siguiente configurado. Los reintentos cortos esperan como máximo 1 segundo. Así se prioriza la respuesta al usuario frente a esperar mucho por un proveedor temporalmente saturado. La disponibilidad y latencia finales siguen dependiendo de cada proveedor.
