# PROGRESS — Production Hardening de Responde AI Telegram / LiggaCuba

**Objetivo:** Auditar, asegurar, estabilizar y preparar el proyecto existente para producción real, sin cambiar concepto, lógica de negocio, comandos, flujos ni experiencia de usuario.

**Rama actual:** `production-hardening`  
**Base:** `main` @ `4fabcdfdbdd659704e58cafa15f61d9e9ec5ffb7`  
**Fecha inicio:** 2026-11-12  

## Estado general

| Fase | Estado | Notas |
|------|--------|-------|
| 1. Auditoría y diagnóstico completo | EN CURSO | Exploración de estructura, stack, puntos de entrada, integraciones |
| 2. Seguridad y protección de credenciales | Pendiente | |
| 3. Estabilidad y gestión de errores | Pendiente | |
| 4. Optimización del rendimiento | Pendiente | |
| 5. Calidad y mantenimiento del código | Pendiente | |
| 6. Integración y fiabilidad de Telegram | Pendiente | |
| 7. Pruebas automatizadas y prevención de regresiones | Pendiente | |
| 8. Docker, configuración y despliegue | Pendiente | |
| 9. Documentación técnica y operativa | Pendiente | |
| 10. Auditoría final y validación | Pendiente | |

## Hallazgos preliminares de auditoría (FASE 1)

### Stack y arquitectura
- Backend: FastAPI (Python 3.11) + Uvicorn
- Base de datos: SQLite con WAL, busy_timeout, connection helpers centralizados (`backend/db.py`)
- Frontend: HTML/JS vanilla (Mini App de Telegram) + panel admin
- Integraciones: Telegram Bot API (webhook), múltiples proveedores de IA (Gemini, Groq, OpenRouter, Cohere + custom), almacenamiento de fotos (B2/Tigris o local), pagos manuales (Cuba)
- Despliegue: Docker + Railway (`railway.json` con healthcheck `/health`, restart on failure)
- Tests: suite pytest offline + e2e + CI en GitHub Actions
- Ya existen: `.env.example`, rate limiters (OCR, generation, admin login), headers de seguridad, cifrado de claves de proveedores, verificación de webhook secret, manejo de SQLite locks como 503, cleanup de usuarios, backup a Telegram, etc.

### Puntos fuertes ya presentes
- Variables de entorno sin valores por defecto inseguros
- `hmac.compare_digest` para claves de admin
- Rate limiting en endpoints sensibles (OCR, analyze, generation, admin login)
- Healthcheck real (verifica conexión y schema de DB)
- Exception handler para SQLite contention → 503 + Retry-After
- Validación de tamaño de body del webhook
- Documentación extensa en `docs/`
- CI con syntax checks + pytest offline
- Cifrado de API keys de proveedores propios y de payloads de caché

### Áreas a revisar en profundidad (próximos pasos de FASE 1)
1. Completar lectura de `main.py` (≈3221 líneas), `telegram_bot.py`, `ai_providers.py`, `dating.py`
2. Buscar posibles fugas de información en logs/errores
3. Revisar manejo de timeouts y reintentos en llamadas a Telegram y proveedores de IA
4. Evaluar si hay código muerto o duplicaciones claras sin rediseñar
5. Revisar dependencias por vulnerabilidades conocidas
6. Verificar que no haya secretos en el historial de Git
7. Comprobar cobertura de tests de los flujos críticos (webhook, sesiones, pagos, dating)
8. Revisar apagado controlado y workers de background (cleanup, backup, etc.)

## Último commit en esta rama
(ninguno todavía — inicialización de rama y PROGRESS.md)

## Próxima tarea exacta
Completar la auditoría de código crítico (seguridad de sesiones, webhook, generación de IA, manejo de errores globales, workers) y documentar hallazgos concretos antes de modificar código de producción.

## Decisiones técnicas
- Se respeta estrictamente la arquitectura y el comportamiento actual.
- No se introducirán servicios de pago nuevos ni cambios de stack.
- Commits frecuentes y pequeños.
- Preferencia por cambios seguros, verificables y respaldados.

## Riesgos conocidos
- `main.py` es monolítico; cualquier cambio requiere cuidado extremo con regresiones.
- SQLite en producción con volumen persistente es obligatorio (ya documentado).
- Dependencia de proveedores de IA externos (rate limits y disponibilidad).
- Workers en background (cleanup, backup, etc.) deben manejarse bien en reinicios de contenedor.
