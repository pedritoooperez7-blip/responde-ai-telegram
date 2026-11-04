# Correcciones tras los cambios en pagos (versión de Railway nº 49)

Se comparó el proyecto con la versión anterior: cambiaron `app.js`, `index.html` y `backend/main.py` (pantalla nueva «Método de pago» y teléfono obligatorio antes de pagar). Todo lo demás estaba intacto.

| # | Dónde | Problema | Corrección |
|---|---|---|---|
| 1 | `app.js` | Al volver atrás desde «Método de pago» o desde Premium la pantalla quedaba **en blanco**. La pila de navegación guardaba `chatScreen` (está dentro de `homeScreen`) en vez de la pantalla real. | `currentScreenId()` busca solo entre las pantallas principales; `goBack()` restaura cada una correctamente. |
| 2 | `app.js` | `#startPayment` llamaba a `showPaymentMethods` pasándole el evento del clic como parámetro. | Se llama sin argumentos y el parámetro solo vale con `true`. |
| 3 | `index.html` | El estado del pago, **Cancelar operación** y **Crear nueva operación** quedaron fuera de `#paymentFlow`. Al mover ese bloque a la pantalla de transferencia, el botón de cancelar se quedaba suelto en Premium y no aparecía donde hacía falta. | Los tres elementos están dentro de `#paymentFlow`. |
| 4 | `dating.js` | Abrir Citas no ocultaba `#paymentMethodScreen`. | Añadida a la lista de pantallas que se ocultan. |
| 5 | `backend/main.py` | `/api/admin/stats` llamaba a `cuba_day_start_utc()`, que **no existía** (error 500 en el panel). El documento de octubre dice que los reinicios diarios usan hora de Cuba, pero el código usaba UTC. | Se añadieron `cuba_today()` y `cuba_day_start_utc()`; `today()` ahora es la fecha de Cuba; el cálculo de «cargo de hoy» y el monitor de IA comparan contra la medianoche cubana en UTC. |
| 6 | `backend/requirements.txt` | `zoneinfo` puede no tener la base de zonas horarias en la imagen. | Añadido `tzdata`. (Si falta, queda un respaldo UTC-5.) |

**Efecto visible del punto 5:** el límite diario gratuito de la IA ahora se reinicia a medianoche de Cuba (antes, a las 8 pm).

## Pruebas nuevas
* `tests/e2e_navegacion_pagos.py`: recorre Premium → método → falta teléfono → Perfil → guardar → transferencia → atrás/cancelar y Citas → Premium → Atrás.

## No verificado
* El backend no se pudo levantar aquí (no hay `fastapi`); se revisó con análisis estático (sin nombres sin definir) y las pruebas unitarias que no lo necesitan (146 de 148 pasan; las 2 restantes importan `main.py` y requieren `fastapi`).
* Los pagos reales (BANDEC, BPA, saldo móvil) no se probaron: el recorrido usa una API simulada.
