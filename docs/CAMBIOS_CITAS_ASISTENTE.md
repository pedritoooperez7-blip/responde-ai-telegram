# Citas: asistente de perfil y corrección de bugs

## Rediseño
* El formulario largo se reemplazó por un **asistente por pantallas** (21 pantallas en total) con los colores de la app.
* Preferencias nuevas guardadas en `dating_profiles.prefs` (JSON validado con lista blanca). La columna se crea sola en bases existentes (`init_schema` hace `ALTER TABLE` si falta).
* El feed se ordena por provincia y afinidad; las tarjetas muestran «N cosas en común».
* No se copiaron de las referencias los datos inventados (cifras de usuarios, premios, testimonios, «mujeres activas en tu ciudad», raspadita con cuenta regresiva, gráficas de matches proyectados).

## Bugs corregidos
| Dónde | Problema | Corrección |
|---|---|---|
| `dating.py` | Los likes diarios se reiniciaban a medianoche **UTC** (8 pm en Cuba) | Ahora usan medianoche de Cuba (`America/Havana`) |
| `dating.py` | La fecha de nacimiento se podía cambiar al editar el perfil | Bloqueada tras crear el perfil (`409 birth_locked`) |
| `dating.py` | Un reporte de «parece menor» ocultaba a cualquiera al instante, sin límite por persona | Máximo 3 por día y por usuario (`429 report_limit`) |
| `dating.py` | Las fotos rechazadas ocupaban cupo de las 6 y las posiciones se repetían al borrar | No cuentan las rechazadas; la posición es máximo+1 |
| `dating.py` | Uso obsoleto de `datetime.utcnow()` | Reemplazado |
| `dating.js` | Pestañas Descubrir, Matches y Mi perfil mostraban «null» o `[object HTMLDivElement]` (se pasaban `null` y arreglos a `replaceChildren`) | Helper `setBody` que aplana y filtra |
| `dating.js` | Borrar una foto fallaba en silencio si el servidor daba error | Ahora comprueba la respuesta y muestra el error |

## Pruebas
* `tests/test_dating.py`: 47 pruebas (8 nuevas: preferencias, orden del feed, fecha bloqueada, hora de Cuba, fotos, límite de reportes, migración).
* `tests/e2e_dating_wizard.py`: recorre el asistente completo en Chromium sin cabeza con la API simulada (español, inglés, borrador, edición, pestañas).

## No verificado
* No se probó en Telegram real, ni con el backend FastAPI levantado (no había `fastapi` disponible): las rutas HTTP se revisaron leyendo el código.
* La migración a Turso **no se tocó**.
