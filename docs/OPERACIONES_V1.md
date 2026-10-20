# Operaciones para la V1 de pruebas

Este documento describe la configuración operativa añadida en la rama
`feature/v1-hardening`. No asume nada sobre el proveedor de hosting: todo lo que
depende del entorno debe verificarse antes de desplegar.

## 1. Variables de entorno nuevas

Todas son opcionales y tienen un valor por defecto conservador. Se leen al
arrancar el proceso (las de límites) o en cada petición (las de pagos).

| Variable | Defecto | Efecto |
|---|---|---|
| `SQLITE_BUSY_TIMEOUT_MS` | `15000` | Tiempo máximo de espera ante un bloqueo de escritura. |
| `OCR_RATE_LIMIT_PER_MINUTE` | `10` | Solicitudes de OCR por usuario y minuto. |
| `OCR_DAILY_LIMIT` | `50` | Solicitudes de OCR por usuario y día UTC. |
| `OCR_MAX_CONCURRENT` | `2` | OCR simultáneos por proceso (protege la CPU). |
| `ANALYZE_RATE_LIMIT_PER_MINUTE` | `20` | Creaciones de análisis por usuario y minuto. |
| `GENERATION_RATE_LIMIT_PER_HOUR` | `40` | Generaciones por usuario y hora (también para Premium). |
| `ADMIN_LOGIN_MAX_ATTEMPTS` | `10` | Intentos fallidos por IP y ventana. |
| `ADMIN_LOGIN_MAX_ATTEMPTS_PER_USER` | `30` | Intentos fallidos por usuario y ventana. |
| `ADMIN_LOGIN_WINDOW_SECONDS` | `900` | Ventana de throttling del login. |
| `PAYMENT_CURRENCY` | `CUP` | Moneda real de las operaciones. |
| `PAYMENT_PRICE_WEEKLY` | `2500` | Importe numérico del plan semanal en esa moneda. |
| `PAYMENT_PRICE_ANNUAL` | `15500` | Importe numérico del plan anual en esa moneda. |
| `DISABLE_BACKGROUND_PURGE` | vacío | `1/true/yes` desactiva la purga periódica. |

**Limitación importante:** los límites de frecuencia viven en memoria del
proceso. Con varios workers de uvicorn cada worker aplica su propio contador, de
modo que el límite efectivo se multiplica por el número de workers. El despliegue
actual arranca un solo proceso (`uvicorn` sin `--workers`).

## 2. Persistencia de SQLite: verificarla, no suponerla

El valor por defecto de `DB_PATH` es `liggacuba.db` dentro del contenedor. Ese
archivo **se pierde en cada despliegue** si no hay un volumen persistente.

Pasos para verificarlo en el entorno real:

1. Configurar `DB_PATH` apuntando a una ruta del volumen, por ejemplo
   `/data/liggacuba.db`.
2. Desplegar y crear un usuario de prueba.
3. Reiniciar o redesplegar el servicio.
4. Comprobar que el usuario y su uso siguen existiendo (consulta admin o
   `GET /api/admin/users?q=<id>`).
5. Comprobar que `GET /health` responde `200` con `"database":"ok"`.

Si el hosting no ofrece volumen, hay que decidir antes de la V1 entre añadir uno
o aceptar que los datos son efímeros (no recomendado con pagos).

WAL se activa automáticamente en bases de datos de archivo. Si el sistema de
archivos no lo soporta, la aplicación sigue funcionando con el journal por
defecto y registra un aviso.

## 3. Salud y observabilidad

`GET /health` ejecuta `SELECT 1` sobre la base de datos:

* `200` + `{"status":"ok","database":"ok"}`: servicio y base disponibles.
* `503` + `{"status":"degraded","database":"unavailable"}`: la base no se puede
  abrir o consultar. No se exponen rutas, SQL ni mensajes internos.

Los bloqueos de SQLite (`database is locked` / `busy`) se traducen en `503` con
`Retry-After: 2`, en lugar de un `500` opaco.

## 4. Copias de seguridad

Ver `docs/BACKUP_RESTORE.md`. Resumen:

```bash
python scripts/backup_sqlite.py --db "$DB_PATH" --out-dir /data/backups
```

El script usa la API de backup de SQLite, abre el origen en modo lectura y nunca
sobrescribe archivos existentes.

## 5. Checklist previo a cada despliegue

1. `python -m pytest tests/ -q --ignore=tests/test_provider_integration.py`
2. `python -m py_compile backend/*.py scripts/*.py`
3. `node --check app.js`
4. `git diff --check`
5. `python scripts/backup_sqlite.py --db "$DB_PATH" --out-dir <volumen>/backups`
6. Desplegar y comprobar `/health`.
7. Enviar `/start` al bot de pruebas y abrir la Mini App.

## 6. Decisiones pendientes del propietario

1. **Moneda comercial y precios.** El código usa `CUP` y 2500/15500 por defecto.
   Si los usuarios en inglés deben ver USD, hay que definir una tasa de cambio y
   un mecanismo de actualización; no se ha inventado ninguna.
2. **Volumen persistente y ruta de `DB_PATH`.** No verificable desde el
   repositorio.
3. **Política de reembolsos y conservación fiscal** de las operaciones de pago.
4. **Procedimiento de supresión de datos de usuario** (hoy manual; no existe
   endpoint ni automatización).
5. **Proveedores de IA activos y modelos confirmados.** `gemini-3.8-flash` sigue
   siendo el valor por defecto heredado y no se ha verificado contra el
   proveedor.
