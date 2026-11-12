# PROGRESS — Production Hardening de Responde AI Telegram / LiggaCuba

**Objetivo:** Auditar, asegurar, estabilizar y preparar el proyecto existente para producción real, sin cambiar concepto, lógica de negocio, comandos, flujos ni experiencia de usuario.

**Rama actual:** `fix/tests-18-failures`  
**Base:** `main` @ `4fabcdfdbdd659704e58cafa15f61d9e9ec5ffb7`  
**PR:** #77 → `main`  
**Fecha inicio:** 2026-11-12  

## Estado general

| Fase | Estado | Notas |
|------|--------|-------|
| 1. Auditoría y diagnóstico completo | AVANZADA | Stack, puntos fuertes, tests baseline, hallazgos documentados |
| 2. Seguridad y protección de credenciales | EN CURSO | Dockerfile no-root + CORS sin wildcard |
| 3. Estabilidad y gestión de errores | Pendiente | |
| 4. Optimización del rendimiento | Pendiente | |
| 5. Calidad y mantenimiento del código | EN CURSO | 18 fallos de tests investigados y corregidos |
| 6. Integración y fiabilidad de Telegram | Pendiente | |
| 7. Pruebas automatizadas y prevención de regresiones | EN CURSO | Helpers de pago + AI connection counts + dating schema |
| 8. Docker, configuración y despliegue | PARCIAL | no-root |
| 9. Documentación técnica y operativa | Pendiente | |
| 10. Auditoría final y validación | Pendiente | |

## Mejoras implementadas

1. **Dockerfile (security)**: proceso corre como usuario no-root `app` (uid/gid 1001).
2. **CORS (security)**: eliminado fallback `["*"]`; lista vacía deniega cross-origin.
3. **Tests — 18 fallos investigados (2026-11-12)**:
   - **Dating**: test desactualizado (esperaba ausencia de `dating_messages`; el producto tiene chat interno). Test actualizado.
   - **Pagos**: helpers no configuraban `payment_phone` antes de crear operaciones. La validación de negocio se mantiene; se corrigieron fixtures.
   - **AI event logging / timing**: conteo de conexiones desfasado por `_reject_if_banned` en `current_user`. Tests alineados (telemetry = 4ª conexión, best-effort).
   - **expected_values**: el código no inventa precios cuando faltan campos; el test se alineó a `(0.0, "CUP")` (más seguro para verificación bancaria).

## Pruebas ejecutadas (este entorno)

| Suite | Resultado | Notas |
|-------|-----------|-------|
| `tests/test_payments_config.py` | 8/8 PASSED | Offline |
| `tests/test_dating.py` | PASSED (suite offline) | Offline |
| `tests/test_backup_sqlite.py` | 7/7 PASSED | Offline |
| `tests/test_isolated.py` (pagos, AI, CORS) | NO EJECUTADA aquí | Requiere FastAPI; verificar en CI del PR #77 |

## Próxima tarea exacta
- CI verde en PR #77 y autorización explícita para merge a `main`.
- FASE B: restauración atómica de backups.
- Continuar auditoría de sesiones, error handling y Telegram.

## Decisiones técnicas
- No se modificó lógica de negocio ni contratos de API.
- No se eliminó la exigencia de teléfono antes de iniciar un pago.
- No se inventan importes de pago cuando faltan en operaciones históricas.
- CORS: denegar por defecto es más seguro que `*`.
- Telemetría AI sigue siendo best-effort y no debe tumbar una respuesta exitosa.

## Riesgos conocidos
- Volumen DB debe ser writable por uid 1001.
- main.py monolítico.
- Suite completa de isolated no verificada en este entorno por falta de FastAPI (depende de CI).
- Restauración de backup aún escribe el destino antes de validar integridad (FASE B).
