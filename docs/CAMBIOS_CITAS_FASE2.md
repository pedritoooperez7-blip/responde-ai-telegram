# Fase 2 — Mute real + Typing indicator + limpieza

Fecha: 2026-11-19

Archivos:
- `frontend/chat.js`
- `backend/dating.py`

---

## 1. Mute real de conversaciones

### Backend
- Nueva tabla `dating_mutes (user_id, match_id, created_at)`
- Funciones: `is_muted()`, `set_mute()`
- Endpoint: `POST /api/dating/matches/{match_id}/mute` con body `{ muted: true|false }`
- Lista de matches: cada item incluye `muted: true|false`
- Si está silenciado → `unread_count = 0` (no suma al badge)
- Notificaciones Telegram: **no se envían** si el receptor silenció ese match
- Al borrar datos de citas se limpian mutes

### Frontend
- Botón **Silenciar / Activar notificaciones** en el menú del chat
- Lista de conversaciones: filas silenciadas con clase `muted-row` y preview `🔇 Silenciado`
- Estado `S.muted` sincronizado con el backend

---

## 2. Typing indicator (“escribiendo…”)

### Backend
- Nueva tabla `dating_typing (user_id, match_id, updated_at)`
- `touch_typing()` — el cliente lo llama mientras escribe
- `is_other_typing()` — true si el otro tecleó en los últimos ~6 s
- Endpoint: `POST /api/dating/matches/{match_id}/typing`
- `get_messages` / polling devuelve `other_typing: true|false`

### Frontend
- Al escribir en el input se envía typing (debounce 2.5 s)
- En el header del chat aparece “escribiendo…” cuando el otro está activo
- Se actualiza en cada poll automáticamente

---

## 3. Ver perfil desde el menú

El botón “Ver perfil” del menú del chat ahora llama a `_openProfile(public_id)` (ya no muestra un toast vacío).

---

## 4. Limpieza

`delete_dating_data` también borra filas de `dating_mutes` y `dating_typing`.

---

## Cómo aplicar

1. Sustituye:
   - `chat.js`
   - `backend/dating.py`
2. Reinicia el backend (la nueva schema se crea sola con `CREATE TABLE IF NOT EXISTS`).
3. Prueba:
   - Abrir un chat → menú → **Silenciar**
   - En la lista debe aparecer “🔇 Silenciado”
   - El badge de no leídos no debe contar ese chat
   - Escribir en un chat → el otro debería ver “escribiendo…” (tras el siguiente poll)

---

## Notas

- El typing indicator depende del polling (3–8 s). No es tiempo real tipo WhatsApp, pero funciona sin WebSocket.
- Mute es por usuario y por match (A puede silenciar a B sin que B lo sepa).
