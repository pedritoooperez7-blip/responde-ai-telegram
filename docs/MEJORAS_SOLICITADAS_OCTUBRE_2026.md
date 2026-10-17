# Informe de cambios — LiggaCuba (13 de octubre de 2026)

## Cambios implementados

1. **Hora de Cuba**
   - Se incorporó la zona horaria `America/Havana`.
   - Los reinicios diarios y la validez diaria de análisis usan la fecha de Cuba.
   - Los registros continúan almacenándose en UTC para mantener consistencia; la interfaz convierte fechas y horas visibles a la hora cubana.
   - El cálculo de estadísticas diarias usa la medianoche cubana convertida a UTC.

2. **Planes Premium**
   - Se conservaron los planes existentes: semanal (7 días) y anual (365 días).
   - La activación/renovación administrativa suma días al vencimiento futuro existente, sin borrar tiempo que todavía quede.
   - La opción de retirar Premium elimina el vencimiento de inmediato.
   - El backend sigue comprobando el vencimiento real al autorizar funciones Premium.

3. **Sesiones del panel administrativo**
   - Administradores normales: 7 días.
   - Propietario autenticado mediante `ADMIN_KEY`: 90 días.
   - Los tokens se guardan en `localStorage`, por lo que persisten al cerrar el navegador.
   - Se añadió una tabla de sesiones del administrador y un endpoint de cierre de sesión para revocar la sesión también en el servidor.
   - El rol de propietario solo se concede al iniciar sesión con la clave maestra, no por usar simplemente el nombre `owner`.

4. **Pantalla de resultados**
   - Se muestra la captura original seleccionada.
   - Se mantienen visibles las dos respuestas originales.
   - Al reintentar, las dos nuevas respuestas se agregan debajo como respuestas 3 y 4; no sustituyen las originales.
   - Se añadió copia individual para las nuevas respuestas.
   - Se retiró de la pantalla el bloque de OCR y el texto que informaba que la imagen se había enviado a la IA. No se eliminó el procesamiento interno de OCR que pueda seguir siendo necesario.

5. **Un solo reintento por análisis**
   - El botón se bloquea en el cliente después de iniciar el intento.
   - El backend reserva el reintento de forma atómica.
   - Se añadió `retry_call_started` para impedir una segunda llamada de generación con otra clave de idempotencia, incluso si el primer reintento falla.
   - El endpoint heredado de liberación ya no devuelve el reintento consumido.

## Comprobaciones realizadas

- `python -m py_compile backend/main.py backend/ai_providers.py`: correcto.
- `node --check app.js`: correcto.
- Extracción del JavaScript de `admin.html` y `node --check`: correcto.
- `pytest -q`: **65 passed, 4 skipped, 13 subtests passed**.
- Se añadieron/regresaron pruebas para sesiones de 7 y 90 días, revocación al cerrar sesión, renovación Premium que conserva el tiempo restante y protección contra repetir una regeneración fallida con una clave distinta.

## Pendiente de verificación en entorno real

- Las 4 pruebas omitidas corresponden a pruebas que no se ejecutan en esta validación local (incluidas comprobaciones que requieren proveedores/servicios reales).
- No se ejecutó una prueba visual en un navegador/dispositivo real ni se validaron credenciales o servicios de producción.
- El ZIP no contiene la metadata Git del repositorio; la creación de la rama y el Pull Request se hará después de incorporar estos archivos al repositorio, sin modificar `main`.
