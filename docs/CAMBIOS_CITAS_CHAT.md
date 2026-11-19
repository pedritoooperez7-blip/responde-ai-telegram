# Mejoras implementadas — LiggaCuba Citas + Chat

Fecha: 2026-11-19  
Archivos modificados:
- `frontend/dating.js`
- `frontend/chat.js`
- `backend/dating.py`

---

## 1. Documentación y textos de intro (dating.js)

**Antes:** El comentario del archivo y los textos de intro negaban la existencia del chat interno.

**Ahora:**
- Comentario de cabecera actualizado: menciona chat interno + contactos externos.
- `intro_text` (ES y EN) explica que se puede chatear dentro de la app **o** por Telegram/WhatsApp.
- Los bullets de intro reflejan la realidad actual.

---

## 2. Límite de mensajes free dinámico (chat.js + dating.py)

**Antes:** `MSG_LIMIT_FREE = 8` hardcodeado en el frontend. Si cambiabas la variable de entorno del backend, el front se desincronizaba.

**Ahora:**
- El frontend usa `FREE_MSG_LIMIT` (variable mutable).
- `get_messages` del backend devuelve `free_msg_limit` y `messages_sent`.
- Al cargar el chat (y en el polling) se actualiza el valor real desde el servidor.

---

## 3. Badge de no leídos en tab Matches (chat.js)

**Ahora:**
- Al renderizar la lista de matches se calcula el total de `unread_count`.
- Se actualiza el elemento `#matches-unread-badge` (si existe en el HTML).
- CSS incluido (`.ch-tab-badge`).

**Qué debes añadir en el HTML de las tabs:**

```html
<button type="button" data-tab="matches">
  Matches
  <span id="matches-unread-badge" class="ch-tab-badge" hidden>0</span>
</button>
```

---

## 4. Ver perfil desde el chat (chat.js + dating.py)

**Antes:** `_openProfile` estaba vacío.

**Ahora:**
- Nueva función de negocio `get_match_profile_view` (solo permite ver perfiles con los que tienes match activo).
- Nuevo endpoint: `POST /api/dating/profile-view` con `{ public_id }`.
- `_openProfile` muestra un sheet con nombre, edad, provincia, bio, foto e intereses.
- Si existe `window.openDatingProfile`, la usa (para integración futura más rica).

---

## 5. Notificaciones de mensaje nuevo (dating.py)

**Ya existía lógica parcial.** Se reforzó `post_message` para devolver:
- `other_id`
- `recipient_online` (basado en `is_chat_open`)

El router ya notifica por Telegram cuando el receptor **no** tiene el chat abierto.

---

## 6. Polling adaptativo (chat.js)

**Antes:** Polling fijo cada 4.5 s.

**Ahora:**
- `POLL_MS_ACTIVE = 3000` tras recibir mensajes.
- `POLL_MS_IDLE = 8000` cuando no hay mensajes nuevos.
- Se reinicia el interval automáticamente según la actividad.

Reduce consumo de batería/datos cuando el chat está inactivo.

---

## 7. Mejoras de backend adicionales

- `get_messages` ahora devuelve `free_msg_limit` + `messages_sent`.
- Helper `get_match_profile_view` con validación de match activo (seguridad).
- Ruta `/api/dating/profile-view` registrada.

---

## Lo que NO se implementó (y por qué)

| Mejora | Motivo |
|--------|--------|
| WebSocket / SSE | Requiere cambios de infraestructura + reverse proxy. Mejor como fase 2. |
| Typing indicator completo | Necesita endpoint de presence más frecuente + UI. Se puede añadir después. |
| Mute real (persistente) | Requiere nueva tabla + cambios en notificaciones y badge. Estructura lista para añadirlo. |
| Super-like / Boosts | Feature de producto + pagos. Fuera de este alcance. |
| Reordenar fotos | Requiere UI de drag & drop + endpoint de reorder. |
| Ranking feed con compat_score más agresivo | Ya se usa `compat_score` en Python tras el SQL. Se puede afinar más adelante. |

---

## Cómo aplicar

1. Sustituye los archivos en tu repo:
   - `dating.js` → raíz del frontend
   - `chat.js` → raíz del frontend
   - `backend/dating.py` → carpeta backend
2. Añade el `<span id="matches-unread-badge">` en la tab Matches del HTML.
3. Reinicia el backend (Railway / Docker).
4. Prueba:
   - Crear match → ver intro actualizada
   - Abrir chat → límite free se lee del backend
   - Badge de no leídos
   - Botón "Ver perfil" dentro del chat
   - Polling más lento cuando no hay mensajes

---

## Archivos en este paquete

```
liggacuba-mejoras/
├── CAMBIOS.md          ← este archivo
├── frontend/
│   ├── dating.js
│   └── chat.js
└── backend/
    └── dating.py
```
