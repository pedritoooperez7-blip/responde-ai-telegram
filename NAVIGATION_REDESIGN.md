# Premium Navigation Redesign

**Branch:** `feature/premium-navigation-redesign`  
**Date:** 2026-11-13  
**Scope:** Navegación completa de LiggaCuba / Responde AI Telegram Mini App

## Auditoría inicial (resumen)

- Arquitectura SPA por pantallas con `screenStack` ya existente.
- Bottom nav: Inicio · Citas · Perfil.
- **Gap crítico:** no se usaba `Telegram.WebApp.BackButton`.
- Safe areas y viewport parcialmente resueltos.
- Flujos de pago, premium, dating y análisis conservados sin cambios de negocio.

## Nueva arquitectura de navegación

1. **Bottom nav** sigue siendo el eje principal (Home / Dating / Profile).
2. **Telegram BackButton** nativo sincronizado con:
   - stack de pantallas secundarias
   - modales (crop + resultado)
3. `goBack()` unificado: primero cierra modal, luego desapila pantalla.
4. Indicador `aria-current` en la sección activa.
5. Feedback háptico ligero al cambiar de sección principal.

## Mejoras visuales

- Tokens de diseño ampliados (`--radius-*`, `--space-*`, `--touch-min`, `--focus-ring`, `--transition`).
- Bottom nav con blur, borde sutil y sombra más limpia.
- Ítems de nav en columna (icono + label), touch target ≥ 44px.
- Estados `:focus-visible` y `:active` consistentes.
- Transición de entrada discreta en `.screen` (respeta `prefers-reduced-motion`).

## Mejoras funcionales

- `syncBackButton()` en `showScreen`, `goBack`, `home`, `profile`, `settings`, `more`, apertura de Dating y apertura/cierre de modales.
- `BackButton.onClick` → `goBack()`.
- Nav inferior: handler unificado que también dispara Dating.
- Cierre de modales actualiza el BackButton.

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `app.js` | BackButton, goBack unificado, haptic, aria-current, sync en flujos |
| `dating.js` | syncBackButton + aria-current al abrir Citas |
| `style.css` | Design tokens, bottom-nav premium, focus/active, motion |
| `index.html` | role/aria en bottom-nav |
| `NAVIGATION_REDESIGN.md` | Este documento |

## Lo que NO se cambió

- Lógica de negocio, precios, permisos, APIs.
- Flujos de pago / Premium / dating internos.
- Integraciones Telegram existentes (initData, viewport, etc.).

## Cómo verificar

1. Abrir la Mini App en Telegram.
2. Ir a Perfil → Configuración → el BackButton nativo debe aparecer y volver atrás.
3. Subir imagen → modal crop → BackButton cierra el crop.
4. Analizar → modal resultado → BackButton cierra el resultado.
5. Bottom nav: Inicio / Citas / Perfil con estado activo visible y háptico.
6. `node --check app.js dating.js ads.js`
