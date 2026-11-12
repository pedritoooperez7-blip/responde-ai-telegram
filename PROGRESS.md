# PROGRESS — Production Hardening de Responde AI Telegram / LiggaCuba

**Objetivo:** Auditar, asegurar, estabilizar y preparar el proyecto existente para producción real, sin cambiar concepto, lógica de negocio, comandos, flujos ni experiencia de usuario.

**Rama actual:** `production-hardening`  
**Base:** `main` @ `4fabcdfdbdd659704e58cafa15f61d9e9ec5ffb7`  
**Fecha inicio:** 2026-11-12  

## Estado general

| Fase | Estado | Notas |
|------|--------|-------|
| 1. Auditoría y diagnóstico completo | AVANZADA | Stack, puntos fuertes, tests baseline, hallazgos documentados |
| 2. Seguridad y protección de credenciales | PARCIAL | Dockerfile no-root |
| 3. Estabilidad y gestión de errores | Pendiente | |
| 4. Optimización del rendimiento | Pendiente | |
| 5. Calidad y mantenimiento del código | EN CURSO | Tests alineados con comportamiento actual |
| 6. Integración y fiabilidad de Telegram | Pendiente | |
| 7. Pruebas automatizadas y prevención de regresiones | EN CURSO | Tests de pagos recuperados |
| 8. Docker, configuración y despliegue | PARCIAL | no-root |
| 9. Documentación técnica y operativa | Pendiente | |
| 10. Auditoría final y validación | Pendiente | |

## Mejoras implementadas

1. **Dockerfile (security)**: proceso corre como usuario no-root `app` (uid/gid 1001).
2. **Tests (quality)**:
   - `test_payments_config.py`: actualizado rechazo de plan desconocido ("monthly" es válido; se usa "foobar").
   - `test_isolated.py` (cambio local listo): helpers de pago ahora configuran `payment_phone` antes de crear operaciones, alineados con la regla de negocio actual.

## Pruebas ejecutadas
- Offline suite inicial: varios fallos por tests desactualizados respecto a reglas de negocio recientes.
- Tras correcciones de tests de pagos: grupos de PaymentProof / ManualReview / Cancellation / CurrencySeparation pasan (25 tests).
- Fallos restantes conocidos (preexistentes):
  - 2 en TestCompleteAIFlow (mocks / event logging)
  - 1 en dating swipe/match
  - 1 en backup_sqlite prune

## Próxima tarea exacta
- Completar push de `tests/test_isolated.py` actualizado.
- Investigar fallos restantes de AI flow y dating sin alterar producto.
- Continuar auditoría de sesiones, error handling y Telegram.

## Decisiones técnicas
- No se ha modificado lógica de negocio ni contratos de API.
- Solo se actualizaron tests para reflejar el comportamiento real actual del producto.
- Se mantiene respeto estricto a "mismo producto".

## Riesgos conocidos
- Volumen DB debe ser writable por uid 1001.
- main.py monolítico.
- Algunos tests todavía desactualizados; se documentan y se corrigen de forma incremental.
