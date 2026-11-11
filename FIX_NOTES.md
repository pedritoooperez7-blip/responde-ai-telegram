# Fix referido + teclado chat (11 Nov 2026)

## 1. Referidos no recompensaban

Error en logs Railway:
```
AttributeError: 'sqlite3.Row' object has no attribute 'get'
File "/app/backend/main.py", line 2149, in atajo_pago
_reward_referrer(matched["user_id"], str(matched.get("operation_id", "")))
```

Causa: `matched` es un `sqlite3.Row` y no tiene `.get()`.

Corrección: usar `matched["operation_id"]`.

## 2. Teclado del chat no se abría

En Telegram Mini App (especialmente Android/iOS) el textarea no recibía el foco.

Corrección en `chat.js`:
- Atributos `inputmode`, `enterkeyhint`
- Forzar `focus()` en touchstart/pointerdown
- CSS `pointer-events: auto` + `user-select: text`

## Archivos a actualizar

- `backend/main.py`
- `chat.js`

Los archivos completos están en este branch.
