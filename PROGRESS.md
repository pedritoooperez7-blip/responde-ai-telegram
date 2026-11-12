# PROGRESS — Production Hardening de Responde AI Telegram / LiggaCuba

**Objetivo:** Auditar, asegurar, estabilizar y preparar el proyecto existente para producción real, sin cambiar concepto, lógica de negocio, comandos, flujos ni experiencia de usuario.

**Rama actual:** `production-hardening`  
**Base:** `main` @ `4fabcdfdbdd659704e58cafa15f61d9e9ec5ffb7`  
**Fecha inicio:** 2026-11-12  
**Último push confirmado:** commit anterior + este

## Estado general

| Fase | Estado | Notas |
|------|--------|-------|
| 1. Auditoría y diagnóstico completo | EN CURSO | Estructura, stack, puntos fuertes y áreas de revisión documentadas |
| 2. Seguridad y protección de credenciales | EN CURSO | Dockerfile no-root añadido |
| 3. Estabilidad y gestión de errores | Pendiente | |
| 4. Optimización del rendimiento | Pendiente | |
| 5. Calidad y mantenimiento del código | Pendiente | |
| 6. Integración y fiabilidad de Telegram | Pendiente | |
| 7. Pruebas automatizadas y prevención de regresiones | Pendiente | |
| 8. Docker, configuración y despliegue | EN CURSO | Dockerfile endurecido |
| 9. Documentación técnica y operativa | Pendiente | |
| 10. Auditoría final y validación | Pendiente | |

## Hallazgos de auditoría (FASE 1) — resumen

### Stack y arquitectura (confirmado)
- FastAPI + Uvicorn, SQLite (WAL + busy_timeout), Mini App Telegram, multi-provider IA, pagos manuales, dating, ads, referrals, cleanup y backup a Telegram.
- Despliegue Docker + Railway ya configurado con healthcheck.
- Tests y CI presentes.

### Puntos fuertes (ya implementados)
- Env vars sin defaults inseguros; .env.example completo.
- hmac.compare_digest, rate limiters, security headers, webhook secret, validación de body size.
- Health real, SQLite lock → 503, daemon workers, cifrado de claves IA.
- Logging cuidadoso que evita secretos y PII en errores de proveedores.

### Mejoras implementadas hasta ahora
1. **Dockerfile**: se ejecuta como usuario no-root (`app` uid/gid 1001). Reduce superficie de ataque en caso de compromiso del contenedor. El volumen de DB debe ser writable por uid 1001 (práctica estándar).

### Áreas todavía en revisión
- Lectura detallada de flujos críticos de main.py / dating / payments.
- Posibles mejoras de logging estructurado.
- Cobertura de tests de edge cases.
- Verificación de historial Git por secretos (rápida).
- Timeouts y reintentos ya están razonablemente bien; confirmar cobertura completa.

## Archivos modificados en esta rama
- `PROGRESS.md` (nuevo)
- `Dockerfile` (no-root user)

## Próxima tarea exacta
Continuar auditoría de seguridad de sesiones, admin auth y manejo de errores globales. Preparar cualquier corrección pequeña y segura de logging o validación si se encuentra algo concreto. Luego commit + push.

## Decisiones técnicas
- Se mantiene el mismo CMD y las mismas variables de entorno.
- No se cambió la arquitectura ni el runtime de uvicorn.
- USER app solo afecta el proceso; permisos de volumen siguen siendo responsabilidad del operador.

## Riesgos conocidos
- Si el volumen de `DB_PATH` se monta con ownership de root, el proceso no-root no podrá escribir. Documentar en deployment notes.
- main.py monolítico → cambios mínimos y testeados.
