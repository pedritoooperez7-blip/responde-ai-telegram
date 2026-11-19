# Fase 3 — 14 mejoras (sin transparencia de bots)

## Implementado

### Chat
1. **Paginación hacia atrás** — `before_id` en GET messages; scroll arriba carga historial
2. **En línea** — `other_online` desde presence; indicador verde en el header
3. **Tarjeta de match** — mensaje de sistema con diseño destacado (corazón + “¡Es un match!”)
4. **Visto / enviado** — check simple al enviar, doble check morado al leer
10. **Long-poll / SSE** — `GET /api/dating/matches/{id}/stream` (espera hasta 25s por mensajes nuevos; alternativa a WebSocket sin sticky sessions)

### Producto
5. **Super Like** — acción `superlike` (solo Premium); botón estrella en descubrir
6. **Reordenar fotos** — flechas ◀ ▶ en Mi perfil + `POST /api/dating/photos/reorder`
7. **Ranking del feed** — bonus por actividad reciente + preferencia personas reales vs bots
8. **Undo múltiple** — Premium puede deshacer hasta 3 swipes (`{ count: 3 }`)

### UX
11. **Empty states** — textos con invitar amigos / completar perfil
12. **Reintentos de red** — `withRetry` en carga inicial del chat
13. **Feedback al reportar** — mensaje más claro de confirmación
14. **WhatsApp** — se edita en el perfil existente (mismo formulario de edición)
15. **Textos backend bilingües** — mapa `ERROR_I18N` (es/en) para códigos comunes

## Archivos
- `frontend/chat.js`
- `frontend/dating.js`
- `backend/dating.py`

## Cómo aplicar
1. Sustituye los 3 archivos
2. Reinicia el backend (tablas ya existen de fases anteriores)
3. Prueba: historial scroll ↑, “en línea”, Super Like (Premium), reordenar fotos, undo ×3

## Notas
- WebSocket completo no se implementó (infra + proxies). El endpoint `/stream` es long-poll/SSE compatible con Railway.
- **Frontend ya conectado al SSE** (`chat.js`): usa `EventSource` sobre `/api/dating/matches/{id}/stream`, reconecta al recibir `done`/error. Latencia de mensajes nuevos ~instantánea (antes 3–8 s de polling).
- Super Like cuenta para el límite diario de likes en free (pero solo Premium puede usarlo).
- El ranking del feed sigue intercalando bots con `_interleave_bots`.
