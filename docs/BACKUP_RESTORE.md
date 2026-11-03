# Copia de seguridad y restauración de SQLite

## Copia (segura en caliente)

`scripts/backup_sqlite.py` usa la API de backup de SQLite, que obtiene una
instantánea consistente aunque la aplicación esté escribiendo.

```bash
# Con DB_PATH definido en el entorno
python scripts/backup_sqlite.py --out-dir /data/backups

# Ruta explícita y conservación de las 14 copias más recientes del script
python scripts/backup_sqlite.py --db /data/liggacuba.db \
  --out-dir /data/backups --keep 14
```

Características:

* Abre la base de datos de origen en modo **solo lectura**; no la modifica.
* Nunca sobrescribe: si el nombre existe, añade `-1`, `-2`, etc.
* Ejecuta `PRAGMA integrity_check` sobre la copia y falla si no devuelve `ok`.
* `--keep N` es opcional y solo borra copias creadas por el propio script; sin
  `--keep` no se borra nada. La política de conservación es una decisión del
  propietario, no del código.

Programación recomendada (ejemplo, adaptar al host): una tarea diaria que ejecute
el comando y alerte si el código de salida no es 0.

## Restauración (manual y en entorno aislado)

El script **no restaura**. La restauración debe hacerla una persona y nunca sobre
la base de datos en uso.

1. Detener el servicio (o crear un despliegue de pruebas separado).
2. Copiar la copia de seguridad a un directorio de trabajo, por ejemplo
   `/tmp/restore/liggacuba.db`.
3. Verificar la copia:
   ```bash
   sqlite3 /tmp/restore/liggacuba.db 'PRAGMA integrity_check;'
   ```
   Debe devolver `ok`.
4. Arrancar una instancia **aislada** con `DB_PATH=/tmp/restore/liggacuba.db` y
   comprobar usuarios, pagos y `/health`.
5. Solo si la verificación es correcta, y con una copia de la base actual ya
   guardada, sustituir el archivo de producción con el servicio detenido.
6. Arrancar y comprobar `/health` y un inicio de sesión real.

Notas:

* No ejecutar `VACUUM INTO` sobre una base en uso como sustituto del script.
* No copiar únicamente `liggacuba.db` si existen `-wal` y `-shm` y el servicio
  está activo: el script evita ese problema.
* La restauración requiere intervención manual; no hay automatización ni borrado
  de la base actual por parte del código.

## Backup automático a Telegram

El servicio envía una copia consistente de SQLite (API de backup de SQLite, comprimida con gzip) a un chat privado
cada `BACKUP_INTERVAL_HOURS` horas (6 por defecto; el primer envío ocurre ~10 min después de arrancar).

| Variable | Efecto |
|---|---|
| `BACKUP_CHAT_ID` | Chat destino. Si falta, usa `PAYMENT_ARCHIVE_CHAT_ID`. El bot debe poder publicar allí. |
| `BACKUP_ENCRYPTION_KEY` | Cifra el archivo con Fernet (recomendado: contiene datos personales). **Guárdala aparte: sin ella no se puede restaurar.** |
| `BACKUP_INTERVAL_HOURS` | Frecuencia en horas (mínimo 0.25). |
| `DISABLE_TELEGRAM_BACKUP` | `1` lo desactiva. |

Restaurar (con la app detenida):

```bash
BACKUP_ENCRYPTION_KEY=... python scripts/restore_telegram_backup.py liggacuba-XXXX.db.gz.enc /base/liggacuba.db
```

El script nunca sobrescribe un archivo existente y verifica `PRAGMA integrity_check`.
Límites: Telegram permite subir hasta 50 MB por archivo (si la base lo supera, se registra un error y no se envía);
las fotos de Citas viven en disco (`DATING_PHOTOS_DIR`, por defecto junto a la base) y **no** van en este backup.
