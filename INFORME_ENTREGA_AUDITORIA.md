# LiggaCuba — informe de revisión y entrega

Fecha: 2026-10-11

## Cambios realizados en esta revisión

1. **Reintentos protegidos en backend:** `/api/retry/release` ya no permite restablecer un reintento después de que la segunda generación haya sido registrada. Se conserva la liberación cuando el reintento se reservó pero la generación no llegó a consumirse. Se agregó una prueba de regresión para intentar reutilizar el reintento después de una generación exitosa.
2. **Precios en inglés corregidos en la interfaz:** el cambio de idioma muestra `$8.99 USD` semanal y `$29.99 USD` anual; en español mantiene `2500 CUP` y `15500 CUP`.
3. **Ahorro anual en inglés:** se muestra 94%, aproximación del ahorro calculado comparando $29.99 anual con 52 pagos semanales de $8.99. En español se mantiene el 88% acordado para los precios en CUP.
4. **Disponibilidad de iPhone traducida:** la interfaz muestra “Disponible próximamente” en español y “Coming soon” en inglés.
5. **Pruebas de pagos automáticos ampliadas:** se añadieron pruebas aisladas para BPA y Saldo Móvil, incluyendo destino BPA configurado, validación de importe del SMS, detección de duplicados y activación de Premium en la base temporal.
6. **Pruebas de reintentos ampliadas:** se verifica que el endpoint de liberación no permita convertir un reintento ya usado en uno reutilizable.

## Comprobaciones ejecutadas

- `python3 -m py_compile backend/main.py backend/ai_providers.py tests/test_isolated.py`: aprobado.
- `node --check app.js`: aprobado.
- JavaScript embebido de `index.html`: aprobado.
- JavaScript embebido de `admin.html`: aprobado.
- `python3 -m unittest discover -s tests -v`: **29 pruebas aprobadas**.
- La suite incluye comprobaciones de autenticación, aislamiento de identidad, límite gratuito bajo concurrencia, OCR, límites de tamaño, pagos BANDEC/BPA/Saldo Móvil, duplicados, Premium, reintentos, paso de imágenes a la capa IA, parsers y comportamiento de proveedores.

## Advertencias y límites

- Las pruebas de pagos usan SQLite temporal y datos sintéticos. No se realizó ninguna transferencia real ni se conectó a Railway.
- No se probaron credenciales reales ni se hicieron llamadas en vivo a Gemini, Groq, OpenRouter o Cohere. La generación con esos proveedores depende de que sus variables de entorno estén configuradas y de que el modelo elegido acepte el tipo de contenido enviado.
- No se ejecutó una prueba end-to-end dentro de Telegram/iOS ni se verificó el despliegue real.
- La comprobación de OCR con capturas reales etiquetadas y la comparación de calidad de IA con un corpus controlado siguen pendientes.
- Python 3.13 emite advertencias de obsolescencia por el uso de `datetime.utcnow()` en el backend y algunos tests; no provocaron fallos. Se dejan para una modificación específica de fechas que preserve compatibilidad con timestamps existentes.
- El formato del SMS de Saldo Móvil puede variar. La prueba confirma la lógica para el formato sintético incluido, no la autenticidad criptográfica del SMS recibido en un dispositivo.

## Antes de desplegar

1. Conservar una copia de la base de datos de producción y comprobar `DB_PATH` persistente.
2. Confirmar `TELEGRAM_BOT_TOKEN`, `ATAJO_KEY`, `BANDEC_ACCOUNT`, `BPA_ACCOUNT` y `ADMIN_KEY` en el entorno de despliegue, sin compartir sus valores.
3. Probar en staging los atajos reales con notificaciones no sensibles y sin pagos innecesarios.
4. Confirmar los resultados visuales en Telegram/iOS y ejecutar la suite de nuevo en el entorno de despliegue.

Esta revisión no certifica ausencia total de errores. Los resultados anteriores reflejan exclusivamente las comprobaciones que se ejecutaron.
