# UI Premium updates

## Changes
1. **Logo LiggaCuba** replaces the purple "LC" circle on Premium, Profile, and More screens.
2. **Clearer benefits** (same list for all plans):
   - Análisis ilimitados sin cuota diaria
   - Todos los modos de respuesta
   - Salvar Situación incluido
   - Acceso a funciones Premium nuevas
3. **Savings badges between plans**:
   - Monthly: Popular + "Mejor precio al mes"
   - Annual: **Ahorra 88%** + "vs pagar semanal"

## Files to update (local patch ready)
- `index.html` — logo img tags, benefit text, plan badges
- `app.js` — i18n strings ES/EN
- `style.css` — `.brand-mark-logo`, `.save-strong`

## Status
Branch created from main. Full file push of 30–80KB files hit a tooling size limit from this environment.
Please apply local files from the agent workspace or re-apply the three edits and push.

## Verify before merge
```bash
node --check app.js
node --check ads.js
```
Confirm Premium screen shows logo, updated benefits, and Ahorra 88% badge.
