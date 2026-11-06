# Anuncios, planes de anuncio y 4 respuestas por llamada (5 nov 2026)

## 4 respuestas con una sola llamada a la IA
- El prompt pide `{"replies":[a,b,c,d]}`. Se aceptan 2 a 4 distintas (las casi duplicadas se descartan); el formato antiguo `reply/alternative` sigue funcionando.
- `/api/generate-reply` devuelve solo las 2 primeras. Las otras se guardan en `analysis_attempts.replies_json` (no viajan al cliente hasta el reintento).
- `/api/retry` entrega las respuestas 3 y 4 guardadas **sin llamar a la IA**. Si por algún motivo no hay 2 guardadas (caché antigua, el modelo devolvió pocas), cae al comportamiento anterior (`needs_generation: true`).
- Resultado: plan gratuito = 3 llamadas a la IA por día en vez de 6. `max_tokens` de los proveedores compatibles subió de 500 a 900 para que quepan 4 respuestas.

## Anuncios
- Tabla `ads`. Orígenes: `admin` (los crea el equipo, salen aprobados) y `business` (los edita el negocio tras pagar; cada edición vuelve a `pending`).
- Solo se muestran a usuarios sin Premium, mientras la IA genera (mínimo ~4 s y botón «Ver respuestas»). Si no hay anuncio vigente o falla la carga, el flujo es el de siempre.
- Panel de administración: pestaña **Anuncios** (permiso nuevo `ads`): crear/editar, aprobar, rechazar con motivo, pausar, borrar, ver vistas y clics.
- Seguridad: texto siempre con `textContent`; enlaces solo http(s) (`t.me/…` se normaliza); imagen solo https; límites de longitud.

## Planes de anuncio (CUP, configurables por variable de entorno `AD_PRICE_*`)
| Plan | Precio | Ahorro frente a pagar día a día |
|---|---|---|
| Diario (1 día) | 750 | — |
| Semanal (7 días) | 4500 | 750 (14 %) |
| Mensual (30 días) | 9000 | 13 500 (60 %) |
| Anual (365 días) | 17500 | 256 250 (94 %) |

Se pagan por el mismo flujo de transferencia que Premium (`plan` = `ad_daily|ad_weekly|ad_monthly|ad_annual`). Al verificar el pago (manual o por atajo) se suman días al anuncio del negocio, sin perder días ya pagados. Pantalla: Más → Anunciar mi negocio. Los precios Premium (semanal/anual) no cambian.

## Páginas legales
`rules.html` (reglas de contenido), `terms.html` (sin reembolsos + anuncios) y `privacy.html` (datos de anuncios). Siguen pendientes los `[COMPLETAR]` de titular legal, contacto y jurisdicción.
