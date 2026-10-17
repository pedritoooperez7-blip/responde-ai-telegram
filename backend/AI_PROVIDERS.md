# Proveedores de IA de LiggaCuba

La capa común está en `backend/ai_providers.py`. Las claves se configuran únicamente como variables de entorno del servidor (por ejemplo, en Railway); nunca en `app.js`, HTML ni el repositorio.

Variables opcionales:

- `GEMINI_API_KEY` y opcionalmente `GEMINI_MODEL` (por defecto `gemini-3.8-flash`): texto e imágenes.
- `GROQ_API_KEY` y opcionalmente `GROQ_MODEL` (por defecto `openai/gpt-oss-120b`): texto.
- `OPENROUTER_API_KEY` y opcionalmente `OPENROUTER_MODEL` (por defecto `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`): texto e imágenes si el modelo elegido las admite.
- `COHERE_API_KEY` y opcionalmente `COHERE_MODEL` (por defecto `command-r7b-12-2024`): texto.

Se intentan solo los proveedores configurados y elegibles para el tipo de petición. Los fallos transitorios usan hasta tres intentos por proveedor, backoff exponencial con jitter y presupuesto global de 12 segundos para la generación; los `Retry-After` válidos se respetan si la espera cabe en el presupuesto, y las esperas largas provocan failover para no bloquear al usuario. Errores permanentes (autenticación, solicitud inválida o cuota/crédito agotado) no se reintentan. El timeout HTTP se limita al presupuesto restante.

El proveedor Groq usa por defecto `openai/gpt-oss-120b`: el modelo anterior `llama-3.3-70b-versatile` aparece en la documentación oficial de Groq como deprecado para planes no Enterprise desde agosto de 2026. El cambio se aplica solo cuando `GROQ_MODEL` no está configurado; la compatibilidad de cuenta y el smoke test real siguen pendientes. El nuevo modelo tiene precio por token, por lo que conviene validar coste y calidad en staging antes de producción.

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

Las llamadas HTTP tienen un timeout de hasta 8 segundos por intento, reducido al tiempo restante del presupuesto global. Si un proveedor devuelve un `Retry-After` superior a 2 segundos, el adaptador no bloquea esperando: abandona ese proveedor y prueba el siguiente configurado. Los reintentos cortos usan backoff exponencial con jitter. El monitor de IA añade estado de salud por proveedor/modelo y configuración sin claves; ese estado es en memoria por proceso, no persistente ni un circuit breaker distribuido. Los contadores de tokens se guardan solo si el proveedor los devuelve; no se inventan precios ni costes.


## Proveedores adicionales desde el panel (actualización 2026-10-16)

El panel de administración incorpora **Proveedores IA** para añadir proveedores adicionales que implementen el protocolo OpenAI-compatible (`/chat/completions`). Desde ahí se puede establecer ID, nombre, base URL HTTPS, modelo, capacidades declaradas (texto/imagen), prioridad, activación/desactivación, guardar cambios, probar conexión y eliminar una configuración. Los proveedores se intentan en orden de prioridad ascendente y se continúa con el siguiente si falla el anterior. Las capacidades de visión son una declaración administrativa; deben verificarse con una prueba real porque no todos los modelos aceptan imágenes.

- Las URL deben ser HTTPS y no pueden apuntar a IPs privadas/reservadas, localhost ni hosts internos evidentes.
- Las claves de proveedores personalizados se cifran con Fernet antes de guardarse en SQLite. La clave maestra deriva de `AI_PROVIDER_ENCRYPTION_KEY`, que debe ser un secreto estable de Railway de al menos 32 caracteres. **Configúrala antes de guardar claves de proveedores** y conserva una copia segura: si se pierde o cambia, las claves ya guardadas no se podrán descifrar y habrá que volver a introducirlas.
- La API no devuelve el secreto después de guardarlo y el panel muestra únicamente si existe una clave. No se incluyen claves en logs ni en el historial administrativo.
- La prueba de conexión realiza una llamada real pequeña al modelo; puede consumir cuota o producir un cargo.
- Los cuatro proveedores integrados siguen usando sus variables de entorno. Su orden se puede ajustar mediante `AI_PRIORITY_GEMINI`, `AI_PRIORITY_GROQ`, `AI_PRIORITY_OPENROUTER` y `AI_PRIORITY_COHERE` (menor número = antes). Los proveedores personalizados usan el valor de prioridad configurado en el panel.
- Solo se pueden añadir sin código adicional proveedores compatibles con el protocolo OpenAI. Protocolos propios requieren un adaptador implementado una vez.

## Caché global cifrada

Cuando `AI_PROVIDER_ENCRYPTION_KEY` está configurada, el backend puede reutilizar durante seis horas una respuesta solo si coinciden exactamente texto, hash de imagen, módulo, modo, versión de prompt y huella de configuración de proveedores. Se guarda el resultado cifrado; no se guardan en claro el texto original ni la imagen. La caché no cambia la cuota de análisis y es una optimización best-effort: si falla el cifrado/descifrado o la base de datos, se continúa con generación normal. Las entradas caducadas se limpian en el proceso de retención.

La reutilización es global: una persona que envíe exactamente la misma entrada puede recibir la misma respuesta guardada. El backend no añade contexto privado oculto por usuario al prompt actual, pero si se introduce en el futuro contexto de perfil individual, debe incluirse en la clave de caché o deshabilitarse la reutilización para ese flujo. La caché es cifrada en reposo, no debe interpretarse como aislamiento por usuario.
