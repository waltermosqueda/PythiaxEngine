# ESTADO ACTUAL — PythiaxEngine
> **LEER ESTO PRIMERO al inicio de cada sesión.**
> **ACTUALIZAR ESTO ÚLTIMO al cerrar cada sesión.**

---

## Estado operativo al 2026-05-03

### Backfill brain_v10 — EN CURSO 🔄
```
Proceso: python herramientas/aprendizaje_operativo_legacy_ml_brain_v10.py backfill --from-date 2025-12-18
Estado: CORRIENDO (terminal async, iniciado ~21:00 hs del 2026-05-03)
Último checkpoint: 2025-12-26 (picks=2, saved=2 por día)
Destino: 2026-04-29
Progreso estimado: ~10% completado al momento de esta nota
```
> Si la sesión se reinicia, verificar con `python _check_backfill.py` antes de asumir nada.

### Git — 2 commits por pushear
```
Commits locales no pusheados:
  f1a819a  feat: ML_BRAIN_V10 (ml_trading_v23) — Ultra-Fast Edition
  256a0df  feat: registrar ML_BRAIN_V10 en liga + script comparacion v22 vs v23

Archivos modificados sin commitear:
  - AGENTS.md  (nueva regla BACKFILL FAIR-START)
  - CLAUDE.md  (nueva regla #11 ventana competitiva)
  - analisis/preview_*.html  (11 archivos — pendientes de dashboard refresh)

Archivos untracked (scripts de diagnóstico):
  - _check_backfill.py, _clean_v10.py, _fix_sequence.py
  - _compare_v22.py, _diag_v9.py, _probe_db.py, _rangos_db.py
```

### Pendiente DESPUÉS de que termine el backfill
1. `python herramientas/refrescar_datos_dashboard.py` — regenerar dashboard con brain_v10
2. Commitear todo: AGENTS.md, CLAUDE.md, analisis/preview_*.html, _fix_sequence.py
3. `git push origin main`

---

## Estado de la DB (a 2026-05-03)

| Familia | Prefijo DB | Desde | Hasta | Filas |
|---|---|---|---|---|
| Legacy ML (V37/V39/V97/BRAIN_V11) | `LEGACY_ML_*` | 2025-12-18 | 2026-04-29 | ~180 c/u |
| brain_v10 (**en backfill**) | `LEGACY_ML_BRAIN_V10_BUY_D5` | 2025-12-18 | **en progreso** | creciendo |
| INVERTIR serie A/D | `INVERTIR_V*` | 2025-12-18 | 2026-04-29 | varios |
| INVERTIR Cx | `INVERTIR_V*_C*` | 2026-01-13 | 2026-04-28 | varios |

**PostgreSQL:** Docker container `pythiax_staging_postgres`, puerto 5433.
**Sequence fix:** `_fix_sequence.py` ya fue ejecutado (reset a 4182). No necesario correrlo de nuevo a menos que haya una interrupción brusca con inserciones parciales.

---

## Decisiones tomadas esta sesión

- **brain_v10 backfill arranca desde 2025-12-18** (no desde 2025-05-15 técnico) — para competencia justa con los demás Legacy ML. Ver regla #11 en CLAUDE.md.
- **v23 = v22 en lógica**: equivalencia probada 8/8 tickers 100% acuerdo, 8.7x más rápido. Aceptado.
- **_fix_sequence.py**: script para resetear `predictions_id_seq` después de desincronías. Mantenerlo en el repo.

---

## Infraestructura

```
Python: C:\Users\wmx_7\AppData\Local\Programs\Python\Python314\python.exe
Repo local: C:\Users\wmx_7\OneDrive\Escritorio\Inversiones\PythiaxEngine
Docker: pythiax_staging_postgres (puerto 5433) — iniciar con docker-compose up -d
DB: pythiax / postgres / postgres_local
Dashboard: https://waltermosqueda.github.io/PythiaxEngine/
```

---

## Protocolo de handoff (OBLIGATORIO)

**Al INICIAR sesión:**
1. Leer este archivo
2. Correr `python _check_backfill.py` para ver estado real de la DB
3. Correr `git status` para ver qué hay pendiente
4. Si Docker no está corriendo: `Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"`

**Al CERRAR sesión:**
1. Actualizar la sección "Estado operativo" con lo que quedó en curso o pendiente
2. Commitear este archivo junto con lo demás: `git add ESTADO_ACTUAL.md`

---

*Última actualización: 2026-05-03 — sesión brain_v10 backfill*
