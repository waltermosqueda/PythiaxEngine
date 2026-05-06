## Instrucciones permanentes para GitHub Copilot — PythiaxEngine

---

### ⚡ PROTOCOLO OBLIGATORIO DE SESIÓN

**FIRST ACTION — Al iniciar CUALQUIER sesión:**
1. Leer `ESTADO_ACTUAL.md` — estado, pendientes, git status de la última sesión
2. Leer `logs/errores_criticos.json` — listar entradas con `"status": "pendiente"`
3. Presentar resumen al usuario y **ESPERAR su dirección** antes de tomar cualquier acción adicional

**LAST ACTION — Al finalizar CUALQUIER sesión:**
1. Actualizar `ESTADO_ACTUAL.md` (qué se hizo, pendientes, git/DB state)
2. Marcar errores resueltos en `errores_criticos.json` con `resolved_at` + `resolution`
3. Agregar entrada en `bitacora/BITACORA.md` si hubo cambios importantes
4. `git add ESTADO_ACTUAL.md logs/errores_criticos.json bitacora/BITACORA.md ; git commit -m "chore(estado): ..." ; git push origin main`

---

### 🗺️ IDENTIDAD Y URLS DEL PROYECTO

| Elemento | Valor |
|----------|-------|
| Repo local | `C:\repos\PythiaxEngine` |
| Git remote | `https://github.com/waltermosqueda/PythiaxEngine` |
| Dashboard live (Cloudflare) | `https://pythiaxengine.pages.dev/preview_c1_pro` |
| Dashboard live (GitHub Pages) | `https://waltermosqueda.github.io/PythiaxEngine/` |
| DB producción | Supabase — URL en `.env` línea comentada `# DATABASE_URL=postgresql+psycopg://...` |
| DB staging local | Docker puerto 5433 (`pythiax_staging_postgres`) |
| Python comando | `py` (NUNCA `python`) |
| Python CI | Python 3.12 en GitHub Actions |

---

### 📐 REGLAS INVARIANTES (nunca cambian)

- **"dashboard"** = SIEMPRE `analisis/preview_c1_pro.html`. `tablero_maquina_pensante.html` = DEPRECADO, no mencionar.
- `actual_return` en DB = ratio (0.05 = 5%). El dashboard multiplica ×100 para mostrar.
- Timestamps UTC expuestos a JS DEBEN tener sufijo `Z` o `+00:00`. Sin timezone → browser parsea como local → tiempo negativo.
- Commits que tocan solo `.md`/`docs/`/`tests/`/`bitacora/` NO disparan `cloud-daily-operations.yml` (paths-ignore).
- Log `logs/pipeline_run.log`: encoding **UTF-16 LE**

### 🧠 PROTOCOLO DE VALIDACIÓN ANTES DE ACTUAR

Antes de diagnosticar cualquier fallo como bug nuevo o tomar cualquier acción significativa (editar código, hacer commit, proponer fix), ejecutar mentalmente este checklist en orden:

**1. ¿El fallo es anterior o posterior al último fix relacionado?**
- Obtener `created_at` del run fallido (API: `https://api.github.com/repos/waltermosqueda/PythiaxEngine/actions/runs?per_page=10`)
- Obtener el timestamp del commit del fix más reciente relacionado con ese tipo de error
- Si `run.created_at < fix_commit_timestamp` → **fallo esperado, pre-fix. No diagnosticar como bug nuevo.**
- Si `run.created_at > fix_commit_timestamp` → bug nuevo o regresión. Continuar análisis.

**2. ¿El error ya está en la tabla de bugs conocidos de este archivo?**
- Revisar la sección `BUGS CONOCIDOS Y FIXES APLICADOS` más abajo
- Si es idéntico a uno resuelto → reportar como regresión con el commit original del fix, no como bug nuevo

**3. ¿El error está en `logs/errores_criticos.json` como ya resuelto?**
- Si `"status": "resuelto"` y el mensaje coincide → es el mismo error. Confirmar al usuario, no investigar.

**4. ¿El fallo es en `ci.yml`?**
- `ci.yml` tiene fallos pre-existentes estructurales (test de URL de Supabase, IPv6 en GitHub Actions). Antes de reportarlo como bug nuevo, verificar si el error es diferente al histórico `test_validate_database_url_accepts_redactable_postgres_url`. Si es el mismo → no es bug nuevo.

**Regla general**: No proponer un fix hasta completar los 4 pasos. Si alguno confirma que el fallo es esperado → comunicar la conclusión razonada al usuario y esperar dirección. (PowerShell Tee-Object) — leer con `read_bytes()` + BOM `\xff\xfe`.
- `ml_trading_v22.py` es archivo FUENTE ORIGINAL — NUNCA modificar.

---

### 🏗️ ARQUITECTURA DEL SISTEMA

```
yfinance (178 tickers, daily OHLCV)
    → TitanDB (PostgreSQL/Supabase)
        ├── prices (OHLCV diario)
        ├── predictions (señales de modelos)
        ├── outcomes (retornos realizados)
        └── pipeline_runs (log de ejecuciones)
    → auto_actualizar.py (orquestador principal)
        ├── DataLoader.update_daily() — descarga EOD
        ├── validate_market_data.py — valida calidad antes del pipeline
        ├── INVERTIR scanners (V11, V13, V8-V12)
        ├── Legacy ML models (V37, V39, V39FULL, V94, V97, BRAIN_V10, BRAIN_V11, BRAIN_V11_OPT)
        └── generar_tablero_maquina_pensante.py — genera HTML
    → GitHub Actions (cloud-daily-operations.yml)
        → GitHub Pages + Cloudflare Pages (deploy automático)
```

**Archivos clave:**

| Archivo | Rol |
|---------|-----|
| `herramientas/auto_actualizar.py` | Orquestador principal del pipeline diario |
| `herramientas/validate_market_data.py` | Validación de calidad de datos pre-pipeline |
| `herramientas/mtm_intraday.py` | Upsert precios intraday (solo tickers con picks) |
| `herramientas/refrescar_datos_dashboard.py` | Refresh local del HTML |
| `analisis/generar_tablero_maquina_pensante.py` | Genera el bundle completo del dashboard |
| `analisis/preview_c1_pro.html` | **EL** dashboard. Fuente para Cloudflare y GitHub Pages. |
| `infra/cloud/decide_cloud_refresh.py` | Decide si reconstruir dashboard en CI |
| `infra/cloud/audit_dashboard_integrity.py` | Auditoría post-build |
| `aprendizaje_operativo/legacy_ml_models.json` | Registro de modelos ML (enabled/disabled) |
| `.github/workflows/cloud-daily-operations.yml` | Pipeline CI principal (crons 19:30/22:00/08:00 AR) |
| `.github/workflows/intraday-mtm-refresh.yml` | MTM parcial 3x/día (11:15/14:00/16:30 AR) |
| `.github/workflows/github-pages-publish.yml` | Deploy a GitHub Pages (push to main) |
| `ESTADO_ACTUAL.md` | Handoff entre sesiones — leer al inicio |
| `logs/errores_criticos.json` | Errores detectados por pipeline — chequear al inicio |
| `bitacora/BITACORA.md` | Registro cronológico de sesiones y decisiones |

---

### 🕐 WORKFLOWS CI Y CRONS

| Workflow | Trigger | Horario AR | UTC |
|----------|---------|-----------|-----|
| `cloud-daily-operations.yml` | cron + push | 19:30, 22:00, 08:00 L-V | 22:30, 01:00, 11:00 |
| `intraday-mtm-refresh.yml` | cron | 11:15, 14:00, 16:30 L-V | 14:15, 17:00, 19:30 |
| `github-pages-publish.yml` | push a main | — (inmediato) | — |
| `dashboard-build.yml` | manual (`workflow_dispatch`) | — | — |

**Regla crítica Cloudflare vs GitHub Pages:**
- Cloudflare Pages sirve `analisis/preview_c1_pro.html` directamente desde rama `main`
- GitHub Pages sirve desde `dist/github-pages/` (generado por CI)
- Sync commits con `[skip ci]` → Cloudflare NO deploya. Fix: usar mensaje sin `[skip ci]`

---

### 🤖 CATÁLOGO DE MODELOS

**Convención de nombres en DB:** `LEGACY_ML_{MODELO}_{SIGNAL}_D{horizonte}` / `INVERTIR_V{N}_{serie}_D{horizonte}`

**INVERTIR (rule-based, horizonte D7):**

| Modelo | Status | DB prefix | WR | Avg Ret | Picks |
|--------|--------|-----------|-----|---------|-------|
| V11 | ✅ Campeón | `INVERTIR_V11_*` | 100% | +6.61% | 19/44 rondas |
| V13 | ✅ Experimental | `INVERTIR_V13_*` | 62.12% | +5.06% | 66/34 rondas |
| V8-V12 | 📦 Histórico | — | — | — | en DB |

**Legacy ML (horizonte D5, salvo indicado):**

| Modelo | Status | DB prefix | WR | Avg Ret |
|--------|--------|-----------|-----|---------|
| ML_BRAIN_V10 | ✅ enabled | `LEGACY_ML_BRAIN_V10_BUY_D5` | 42.44% | — (182 picks) |
| ML_BRAIN_V11 | ✅ enabled | `LEGACY_ML_BRAIN_V11_BUY_D5` | 51.25% | +1.64% |
| ML_BRAIN_V11_OPT | ✅ enabled | `LEGACY_ML_BRAIN_V11_OPT_BUY_D5` | 51.25% | +1.40% |
| ML_V97 | ✅ enabled | `LEGACY_ML_V97_SURGE_D3` | 78.57% | +4.07% |
| ML_V39 | ✅ enabled | `LEGACY_ML_V39_TOP_D1` | 63.95% | +0.52% |
| ML_V39FULL | ✅ enabled | `LEGACY_ML_V39FULL_TOP_D1` | 58.82% | +0.40% |
| ML_V94 | ✅ enabled | `LEGACY_ML_V94_BUY_D5` | 60.26% | +2.64% |
| ML_V37 | ✅ enabled | `LEGACY_ML_V37_SURGE_D1` | 40.74% | -0.16% |
| ML_BRAIN_V9 | ❌ disabled | — | — | Timeout >30min diario |
| ML_V22 | ❌ disabled | — | — | Reemplazado por V10 |

**Regla BACKFILL FAIR-START:**
Antes de backfill de modelo nuevo: `SELECT MIN(prediction_date) FROM predictions WHERE model_name LIKE '<familia>%'`
Usar esa fecha como `--from-date`. NUNCA usar la fecha técnica mínima. Todos los modelos de la misma familia deben compartir la misma fecha de inicio.

---

### 🔧 BUGS CONOCIDOS Y FIXES APLICADOS

| Bug | Commit | Descripción |
|-----|--------|-------------|
| BUG 1 | `cf73535` | `github-pages-publish.yml` regeneraba dashboard con datos viejos en cada push |
| BUG 2 | `531ea07` | `audit_dashboard_integrity.py` falso positivo V11 SEGURO (carry-over) |
| BUG 3 | `42a09af` | Cloudflare no sincronizaba — sync commit usaba `[skip ci]` |
| BUG 4 | `ae7595b`/`5695c75` | Freshness badge negativo — datetime UTC sin sufijo Z |
| BUG 5 | `1e36de0` | Stage GitHub Pages site sin guarda `if:` |
| BUG 6 | `82a7de9` | `github-pages-publish.yml` con pipeline redundante (simplificado a 51 líneas) |
| BUG 7 | `a77a2e1` | **Pipeline 19:30 AR fallaba siempre** — MTM intraday adelantaba `MAX(date)`, `faltantes=0`, SPY stale → FAIL |

**BUG 7 (el más importante — nunca revertir):**
`intraday-mtm-refresh.yml` hace upsert en `prices` para tickers con picks abiertos (no SPY/QQQ).
`MAX(date)` queda = fecha actual aunque SPY siga en la anterior.
Fix: `_get_ultima_fecha_sentinel()` en `auto_actualizar.py` — usa `MIN(MAX(date))` para SPY y QQQ como `ultima`.
Si sentinel < MAX global → fuerza descarga EOD completa.

---

### 🔀 GIT — REGLAS CRÍTICAS

**Conflicto en rebase con `preview_c1_pro.html`** (GitHub Actions lo auto-commitea):
```bash
git checkout --theirs analisis/preview_c1_pro.html   # "theirs" en rebase = nuestro commit local
git add analisis/preview_c1_pro.html
git rebase --continue
```
⚠️ En `git rebase`: "theirs" = el commit siendo replayed (nuestro). "ours" = upstream (viejo). Opuesto a `git merge`.

**Sync de dashboard sin loop:**
- Sync commit NO debe tener `[skip ci]` (Cloudflare lo ignora)
- `analisis/preview_c1_pro.html` en `paths-ignore` del `on.push` de `github-pages-publish.yml` evita loop

---

### 📊 ESTADO SUPABASE (actualizar cuando cambie)

| Modelo | Rows predictions | Rows outcomes | Notas |
|--------|-----------------|---------------|-------|
| ML_BRAIN_V10 | 182 | 172 | OK |
| ML_BRAIN_V9 | 0 | 0 | Disabled, NO migrar |
| ML_V94 | 0 | 0 | ⏰ Migrar 2026-05-11 (ARM+INTC, target vence ese día) |

---

### 🏥 FLUJO DE CORRECCIÓN DE ERRORES

Cuando se detecta un error en `logs/errores_criticos.json`:
1. Leer el `line` para identificar el paso que falló
2. Buscar la causa raíz en el código (no solo sugerir)
3. Aplicar el fix directamente
4. Actualizar entrada en JSON: `"status": "resuelto"`, `"resolved_at"`, `"resolution"`
5. Hacer commit del fix + del JSON actualizado

---

### 🗓️ TAREAS PROGRAMADAS LOCALES (Windows Task Scheduler)

| Tarea | Horario | Descripción |
|-------|---------|-------------|
| `TITAN_AutoActualizar_Diario` | L-V 19:15 | Pipeline local → Docker staging |
| `TITAN_UpdateLocalStaging` | L-V 20:00 | Update staging desde market data |
| `TITAN_DashboardHealthCheck` | L-V 20:45 | Health check → `logs/dashboard_health.log` |
