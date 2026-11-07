# Guía: fotos en Cloudflare R2, limpieza automática y baneo

## 0. Qué cambió en el código

| Qué | Dónde |
|---|---|
| Fotos de Citas a Cloudflare R2 (con respaldo a disco) | `backend/storage.py`, `backend/dating.py` |
| Limpieza automática + baneo con 48 h de gracia | `backend/cleanup.py`, `backend/main.py` |
| Botones Banear / Desbanear / Borrar en el panel | `admin.html` + rutas `/api/admin/users/...` |
| Pantalla de planes separada de la pantalla del anuncio | `index.html`, `ads.js`, `app.js` |
| Tutorial «foto → enlace» (dentro del editor y como página) | `index.html`, `image-guide.html` |
| Script para pasar tus fotos actuales a R2 | `scripts/migrate_photos_to_r2.py` |

**Turso no se incluyó** (explicación al final).

---

## 1. Cloudflare R2 paso a paso

> ⚠️ **Antes de empezar:** R2 incluye 10 GB gratis al mes, pero Cloudflare normalmente pide
> **registrar una tarjeta o PayPal** para activarlo (no cobra mientras no pases del límite gratis).
> Si no puedes añadir un método de pago, **no actives R2**: el código sigue funcionando igual
> guardando las fotos en el disco, y la limpieza automática ya te ahorra mucho espacio.

1. Crea una cuenta gratis en **cloudflare.com** y confirma tu correo.
2. En el panel, entra en **R2 Object Storage** y actívalo (aquí te pedirá el método de pago).
3. **Create bucket** → nombre, por ejemplo `liggacuba-fotos`. **No actives el acceso público**: el bucket debe quedar privado (la app sirve las fotos con enlaces firmados y así una foto pendiente de revisión nunca es pública).
4. Copia tu **Account ID** (aparece en la página principal de R2) → será `R2_ACCOUNT_ID`.
5. En R2 → **Manage API tokens** → **Create API token**:
   - Permiso: **Object Read & Write**
   - Limítalo a tu bucket.
   - Al crearlo verás **Access Key ID** (`R2_ACCESS_KEY`) y **Secret Access Key** (`R2_SECRET_KEY`). **El secreto se muestra una sola vez**: cópialo ya.
6. En **Railway → tu servicio → Variables** añade:

   | Variable | Valor |
   |---|---|
   | `R2_ACCOUNT_ID` | tu Account ID |
   | `R2_ACCESS_KEY` | el Access Key ID |
   | `R2_SECRET_KEY` | el Secret Access Key |
   | `R2_BUCKET` | `liggacuba-fotos` (el nombre de tu bucket) |

   Railway redeploya solo. (`boto3` ya está en `requirements.txt`.)
7. **Prueba:** sube una foto nueva en Citas. En R2 → tu bucket debe aparecer la carpeta `dating/` con el archivo.

### Pasar las fotos que ya tienes (sin perder ninguna)

El script **solo copia**; no borra nada del disco y se puede repetir.

```bash
railway run python scripts/migrate_photos_to_r2.py --dry-run   # solo lista
railway run python scripts/migrate_photos_to_r2.py             # sube
```

(O ábrelo desde la terminal/shell de tu servicio en Railway.) Las fotos viejas **siguen viéndose desde el disco** mientras tanto: el servidor busca primero en disco y luego en R2.
Cuando compruebes que todo se ve bien, puedes borrar la carpeta `dating_photos` del volumen para recuperar espacio.

---

## 2. Limpieza automática

Se ejecuta dentro de la purga que ya corría en segundo plano (cada 6 h, 5 min después de arrancar).

| Regla | Valor por defecto |
|---|---|
| Usuario sin Premium inactivo → se borra con todos sus datos | 30 días (`INACTIVE_USER_DAYS`) |
| Cuenta que nunca usó la app (bots) → se borra | 7 días (`GHOST_USER_DAYS`) |
| Pago sin comprobante → se cancela | 3 días (`PENDING_PAYMENT_DAYS`) |
| Datos de un usuario baneado → se borran si nadie lo desbanea | 48 h (`BAN_GRACE_HOURS`) |

«Inactivo» = la última vez que abrió la app o usó un análisis (lo más reciente de las dos).
**Nunca se borra:** Premium vigente, plan de anuncio vigente, quien tiene un pago pendiente o con comprobante en revisión, ni los IDs de `ADMIN_TELEGRAM_IDS`.
Se conservan los registros de pagos (historial) y los reportes de seguridad de Citas.
Tope de seguridad: máximo 200 usuarios borrados por ciclo (`CLEANUP_MAX_USERS_PER_RUN`). Cada borrado automático queda en el Historial del panel (actor «sistema»).

### ⚠️ Primer día: haz un ensayo
La primera vez que corra, **borrará de golpe a todos los que ya cumplan las reglas**. Para ver antes a quién:

1. En Railway añade `CLEANUP_DRY_RUN=1` y redeploya.
2. Espera ~5 minutos y mira los **Logs**: verás líneas `Cleanup (dry-run): would delete user=...`.
3. Si te parece bien, **quita** `CLEANUP_DRY_RUN` y redeploya.

Para apagar toda la limpieza de usuarios: `AUTO_CLEANUP_USERS=0`.

*Nota:* el borrado de registros de uso por antigüedad (`USAGE_LOG_RETENTION_DAYS`) viene **desactivado**, porque esos registros alimentan los contadores del perfil (Chats / Historias / Análisis).

---

## 3. Banear y borrar usuarios (panel de administración)

En **Usuarios / Premium** cada usuario tiene ahora:
- **Banear** → pide un motivo (opcional). El usuario pierde el acceso al instante (no puede abrir la app ni iniciar sesión) y desaparece de Citas. Sus datos se conservan **48 h**; si en ese tiempo haces **Desbanear**, no pierde nada. Si pasan las 48 h, sus datos se borran solos. El baneo (solo su ID) se queda guardado para que no pueda volver como usuario nuevo.
- **Desbanear** → le devuelve el acceso (su perfil de Citas queda oculto hasta que él lo vuelva a activar).
- **Borrar usuario y datos** → borra todo de inmediato (pide confirmación). Esto **no** lo banea: podría volver como usuario nuevo.

Requiere el permiso «Usuarios» del administrador. No se puede banear ni borrar a los IDs de `ADMIN_TELEGRAM_IDS`.

---

## 4. Pantallas de anuncios

- **Sin plan (o plan vencido):** ve solo «Planes para anunciar» (con un aviso si el plan venció).
- **Con plan vigente:** va directo a «Mi anuncio» (formulario + tutorial) y **no ve los planes**.
- El tutorial «¿Cómo convierto mi foto en un enlace?» tiene 4 opciones gratuitas (Postimages, ImgBB, Imgur, Cloudinary) y un truco para comprobar el enlace. También existe como página en `/image-guide.html`.

---

## 5. Por qué no se migró a Turso

El código usa funciones propias de SQLite que el cliente de Turso no replica igual (filas por nombre `sqlite3.Row`, los errores `sqlite3.IntegrityError`/`OperationalError` que se capturan en varios sitios, `BEGIN IMMEDIATE` y la API de copias de seguridad que usa el backup a Telegram). Cambiarlo sin poder probar contra tu base real arriesga romper pagos y sesiones.
Además ya no hace falta para el espacio: las fotos eran lo que más pesaba y ahora van a R2; el resto de la base es solo texto y la limpieza la mantiene pequeña. Si más adelante la base crece, se puede migrar con calma como un proyecto aparte.
