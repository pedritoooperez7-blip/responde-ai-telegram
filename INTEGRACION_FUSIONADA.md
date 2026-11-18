# Integración fusionada — LiggaCuba

**Fecha:** 2026-11-18  
**Base:** `https://github.com/pedritoooperez7-blip/responde-ai-telegram` (main)  
**Contiene:** Prompt 1 (Gestión de Bots de Citas) + Prompt 2 (Zona horaria Cuba) + Prompt 3 (Chats de Bots) + corrección del offset SQLite.

---

## Archivos incluidos (reemplazar en el proyecto)

| Archivo | Origen de la fusión |
|---------|---------------------|
| `admin.html` | bot_chats (UI más completa: Gestión de Bots + Chats mejorados + Havana) |
| `backend/dating.py` | bot_chats (gestión bots + fix conversaciones + edad Cuba) |
| `backend/main.py` | zona + **fix** `cuba_sqlite_day_modifier()` |
| `backend/limits.py` | zona (`DailyCounter` por día Cuba) |
| `backend/referrals.py` | zona |
| `app.js` | zona |
| `chat.js` | zona |
| `dating.js` | zona |

---

## Qué se integró

### 1. Gestión de Bots de Citas (panel admin)
- Sub-pestaña **Gestión de Bots** dentro de Citas.
- Crear / editar / activar-desactivar / eliminar bots.
- Subida de fotos de bots (auto-aprobadas).
- Endpoints: `GET/POST/DELETE /api/admin/dating/bots/{user_id}/photos`.

### 2. Zona horaria Cuba (`America/Havana`)
- Helpers unificados: `CUBA_TZ`, `cuba_today()`, `cuba_day_start_utc()`, `cuba_n_days_ago_date()`.
- Cuotas diarias, likes, edad de perfiles y estadísticas usan día de Cuba.
- Frontend formatea fechas con `timeZone: 'America/Havana'`.
- **Fix extra:** se eliminó el hardcode `date(..., '-5 hours')` en SQLite.
  Ahora se usa `cuba_sqlite_day_modifier()`, que calcula el offset real
  con `ZoneInfo("America/Havana")` (hoy devuelve `-5 hours`).

### 3. Chats de Bots (panel admin)
- **Bug crítico corregido:** la lista ya no filtra solo `status='active'`
  (antes mostraba "0 de 0" si los matches estaban unmatched).
- Filtro por estado (Todos / Activos / Cerrados) + búsqueda por nombre.
- Orden por última actividad (no por fecha del match).
- UX móvil: lista ↔ chat, tiempos relativos, indicadores de leído, etc.

---

## Cómo aplicar

Desde la raíz del repo:

```bash
# Copia los archivos del ZIP sobre el proyecto
cp admin.html ./
cp app.js chat.js dating.js ./
cp backend/dating.py backend/main.py backend/limits.py backend/referrals.py ./backend/
```

Luego reinicia el servicio (Railway / Docker / local).

---

## Checklist de prueba post-integración

1. **Admin → Citas → Gestión de Bots**
   - Crear un bot de prueba, subir foto, activar/desactivar, editar.
2. **Admin → Chats de Bots**
   - Debe listar conversaciones aunque el match esté cerrado/unmatched.
   - Filtros y búsqueda funcionan.
   - Enviar mensaje “como bot” y verlo en el hilo.
3. **Fechas**
   - Dashboard, pagos, mensajes: hora de Cuba.
   - Contadores diarios (likes / cuotas) respetan medianoche de Cuba.
4. **Regresión**
   - Matching de usuarios reales, likes, premium y pagos sin cambios de comportamiento.

---

## Notas técnicas

- `cuba_sqlite_day_modifier()` inyecta el offset actual en las queries de
  agrupación por día (`admin_stats`, `admin_ai_monitor`). Cuba no usa DST
  desde hace décadas; si el offset cambiara, el helper se adapta solo.
- No se tocaron contratos de API públicos de la Mini App.
- Todos los archivos Python de esta fusión pasan `py_compile`.
