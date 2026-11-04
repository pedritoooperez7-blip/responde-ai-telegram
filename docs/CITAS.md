# LiggaCuba Citas

Módulo de citas tipo Tinder dentro del mismo proyecto. **No tiene chat interno**: cuando hay match, la app muestra botones para escribir por **Telegram** (`t.me/usuario`) o **WhatsApp** (`wa.me/numero`), según los canales que cada persona decidió compartir.

## Qué incluye

| Pieza | Dónde |
|---|---|
| Lógica de negocio y rutas | `backend/dating.py` (`APIRouter`, conectado al final de `backend/main.py`) |
| Tablas | Se crean solas en `init_db()`: `dating_profiles`, `dating_photos`, `dating_swipes`, `dating_matches`, `dating_blocks`, `dating_reports` |
| Interfaz Mini App | `dating.js` + sección `#datingScreen` de `index.html` + estilos al final de `style.css` + pestaña "Citas" en la barra inferior |
| Moderación | Pestaña "Citas" en `admin.html` (permiso nuevo `dating`; el owner ya lo tiene) |
| Textos legales | Secciones nuevas en `terms.html` y `privacy.html` |
| Pruebas | `tests/test_dating.py` (47 pruebas, sin red ni FastAPI) y `tests/e2e_dating_wizard.py` (opcional, navegador sin cabeza con la API simulada) |

## Flujo de la persona usuaria

1. Entra a **Citas** y crea su perfil con el **asistente por pantallas** (ver abajo): nombre, fecha de nacimiento (**solo mayores de 18**, no se puede cambiar después), género, a quién busca, rango de edad, provincia, descripción, intereses y preferencias de estilo de vida.
2. Elige **al menos un canal de contacto** (Telegram y/o WhatsApp). Sin canal no se guarda el perfil.
3. Sube fotos. Quedan **pendientes** hasta que un administrador las aprueba; el perfil no aparece para otros hasta tener una foto aprobada.
4. **Descubrir**: like o pasar. Los free tienen `DATING_FREE_DAILY_LIKES` likes al día (20 por defecto).
5. Like mutuo = **match**: se muestran los botones de Telegram/WhatsApp de la otra persona y el bot envía un aviso (sin datos de contacto).
6. Puede deshacer el match, bloquear, reportar, pausar su perfil o borrar todos sus datos de Citas.

Premium: likes ilimitados, ver quién te dio like y deshacer el último swipe.

## Asistente de perfil (onboarding por pantallas)

Una pregunta por pantalla, con barra de progreso en 5 etapas (**Sobre ti, Tu tipo, Estilo de vida, Objetivos de pareja, Casi listo**), botón Atrás y el botón Continuar fijo abajo. Usa los mismos colores y componentes que el resto de la app. Está en `dating.js` (sección «asistente de perfil»).

* Las preguntas de opción única avanzan solas al tocar; las de varias opciones y las opcionales se pueden omitir.
* El avance se guarda en el teléfono (`localStorage`, clave `liggacuba_dating_draft_v1`) y se borra al crear el perfil. No incluye las casillas de +18 y términos, que se piden siempre.
* El perfil se envía **una sola vez** al final (`POST /api/dating/profile`). Después se pide subir fotos.
* **Editar perfil** muestra un resumen por etapas; cada etapa se edita por separado y se guarda todo junto. La fecha de nacimiento aparece bloqueada.
* Las respuestas de estilo de vida y objetivos viajan en `prefs` y el servidor solo acepta las claves y valores de `PREF_SCHEMA` (`dating.py`). **No se muestran a otras personas**; solo se usan para ordenar el feed y calcular «N cosas en común».
* Orden del feed: misma provincia primero; luego más afinidad (intención ×3, hijos ×2, coincidencias en estilo de vida e intereses). El azar desempata. Las respuestas no excluyen perfiles: solo ordenan.
* Para añadir o cambiar una pregunta hay que tocar `STEPS` en `dating.js` **y** `PREF_SCHEMA` en `dating.py` (si no, el servidor la descarta).

## API (todas con sesión de usuario, salvo `config` y `photo`)

`GET /api/dating/config` · `POST /api/dating/me` · `POST /api/dating/profile` (admite `prefs`) · `POST /api/dating/photos` · `DELETE /api/dating/photos/{id}` · `GET /api/dating/photo/{id}?e=&s=` (URL firmada) · `POST /api/dating/feed` · `POST /api/dating/swipe` · `POST /api/dating/undo` (Premium) · `POST /api/dating/likes` · `POST /api/dating/matches` · `POST /api/dating/unmatch` · `POST /api/dating/block` · `POST /api/dating/report` · `POST /api/dating/visibility` · `POST /api/dating/delete`

Administración (permiso `dating`): `GET /api/admin/dating/overview` · `POST /api/admin/dating/photos/{id}/review` · `POST /api/admin/dating/reports/{id}/resolve` · `POST /api/admin/dating/profiles/{user_id}/restore`

## Decisiones de seguridad y privacidad

* **Identificadores opacos**: hacia otras personas solo viaja un `public_id`; nunca el ID de Telegram, la fecha de nacimiento ni el WhatsApp (salvo en un match activo).
* **Contactos solo en matches activos**: deshacer el match o bloquear los oculta de inmediato para ambos.
* **Compatibilidad en ambos sentidos**: género buscado y rango de edad deben encajar para las dos personas.
* **Fotos**: se recodifican a JPEG en el servidor (se borran EXIF/GPS), máximo 1080 px y 6 por persona. Se sirven con **URL firmada** (HMAC con `SESSION_SECRET`) que caduca; no hay acceso público a la carpeta.
* **Moderación**: 3 reportes distintos ocultan el perfil (`under_review`); un reporte de "parece menor" lo oculta al instante. El admin descarta o suspende.
* **Límites de frecuencia** por usuario (swipes, feed, subida de fotos, reportes) con los limitadores en memoria de `limits.py`.
* **Texto libre** sin enlaces ni @usuarios (evita spam y sacar la conversación antes del match).
* **Borrado**: `POST /api/dating/delete` elimina perfil, fotos (archivos incluidos), swipes, matches y bloqueos. Los reportes se conservan y los cerrados se purgan a los 180 días.

## Variables de entorno nuevas (todas opcionales)

| Variable | Defecto | Para qué |
|---|---|---|
| `DATING_PHOTOS_DIR` | carpeta `dating_photos/` junto a `DB_PATH` | Dónde se guardan las fotos. **Debe estar en un volumen persistente** (igual que `DB_PATH`). |
| `DATING_FREE_DAILY_LIKES` | `20` | Likes diarios del plan gratuito. |
| `DATING_SWIPE_RATE_PER_MINUTE` | `60` | Límite de swipes por minuto y usuario. |
| `DATING_PHOTO_RATE_PER_HOUR` | `12` | Fotos subidas por hora y usuario. |
| `DATING_REPORT_RATE_PER_DAY` | `10` | Reportes por día y usuario. |

## Antes de abrirlo al público

1. Montar un volumen y apuntar `DB_PATH` **y** `DATING_PHOTOS_DIR` a él (si no, se pierden perfiles y fotos en cada despliegue).
2. Completar los `[COMPLETAR: ...]` de `terms.html` y `privacy.html` y revisarlos con asesoría legal: es un servicio con datos personales sensibles y contacto entre desconocidos.
3. Crear al menos un administrador con el permiso **Citas** y revisar fotos a diario.
4. Beta cerrada con pocas personas antes de abrir.
5. Escala: SQLite y los limitadores en memoria sirven para una beta con un solo proceso. Si crece, mover a Postgres y a un almacenamiento de objetos para fotos (el código de fotos está aislado en `dating.py`).

## Limitaciones conocidas

* El feed elige hasta 200 candidatos al azar (misma provincia primero) y filtra edad en Python: suficiente para miles de perfiles, no para cientos de miles.
* No hay verificación de identidad ni de que la foto sea de la persona (se podría añadir "foto de verificación" revisada por admin).
* Las pruebas cubren la lógica de negocio; las rutas HTTP y la interfaz hay que probarlas en un entorno con FastAPI instalado y un teléfono/Telegram real.
