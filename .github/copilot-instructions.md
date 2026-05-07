## Instrucciones permanentes para GitHub Copilot — PythiaxEngine

---

### ⚡ PROTOCOLO OBLIGATORIO DE SESIÓN

> **REGLA FUNDAMENTAL**: `ESTADO_ACTUAL.md` es un documento de apoyo. El repo git y
> los archivos JSON son la **única fuente de verdad**. Cualquier dato de texto
> puede estar desactualizado. Los comandos de terminal nunca mienten.

**FIRST ACTION — Al iniciar CUALQUIER sesión (en este orden exacto):**

1. **Ejecutar en terminal — ANTES de leer cualquier archivo:**
   ```powershell
   cd C:\repos\PythiaxEngine ; git log --oneline -5 ; Write-Host "---" ; git status --short
   ```
   Esto da el HEAD real. Si difiere del `<!-- git_head: XXX -->` en `ESTADO_ACTUAL.md` →
   ese archivo tiene commits **desactualizados** para estado de código. Ignorar esas secciones.

2. **Leer `ESTADO_ACTUAL.md`** — usar SOLO la sección `MANUAL_NOTES` (pendientes, decisiones).
   Ignorar la sección de commits si el git_head no coincide con el HEAD real del paso 1.

3. **Leer `logs/errores_criticos.json`** — listar entradas con `"status": "pendiente"`.

4. Presentar resumen al usuario y **ESPERAR su dirección** antes de tomar cualquier acción adicional.

**LAST ACTION — Al finalizar CUALQUIER sesión (obligatorio antes de cerrar):**

1. Marcar errores resueltos en `logs/errores_criticos.json` con `resolved_at` + `resolution`
2. Actualizar sección MANUAL de `ESTADO_ACTUAL.md` con pendientes actuales (entre los marcadores `<!-- MANUAL_NOTES_START -->` y `<!-- MANUAL_NOTES_END -->`)
3. **Regenerar y pushear el estado** con el script auto-generador:
   ```powershell
   cd C:\repos\PythiaxEngine
   py scripts/generar_estado_actual.py --write --commit --push
   ```
   Este script captura git truth, errores y preserva las notas manuales automáticamente.
4. Si hubo cambios importantes de arquitectura, agregar entrada en `bitacora/BITACORA.md`

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

- **FUENTE DE VERDAD**: `git log` y `git status` > `ESTADO_ACTUAL.md` > cualquier otro archivo de texto.
  `ESTADO_ACTUAL.md` puede estar desactualizado. El repo nunca miente.
- **"dashboard"** = SIEMPRE `analisis/preview_c1_pro.html`. `tablero_maquina_pensante.html` = DEPRECADO, no mencionar.
- `actual_return` en DB = ratio (0.05 = 5%). El dashboard multiplica ×100 para mostrar.
- Timestamps UTC expuestos a JS DEBEN tener sufijo `Z` o `+00:00`. Sin timezone → browser parsea como local → tiempo negativo.
- Commits que tocan solo `.md`/`docs/`/`tests/`/`bitacora/` NO disparan `cloud-daily-operations.yml` (paths-ignore).
- Log `logs/pipeline_run.log`: encoding **UTF-16 LE** (PowerShell Tee-Object) — leer con `read_bytes()` + BOM `\xff\xfe`.
- `ml_trading_v22.py` es archivo FUENTE ORIGINAL — NUNCA modificar.

---

### 🧠 FRAMEWORK DE RAZONAMIENTO PROFUNDO

Este no es un checklist. Es el modelo mental que debe activarse antes de cualquier diagnóstico, fix, o acción con efecto en el repo. Se aplica a situaciones conocidas y a situaciones que nadie anticipó.

---

#### Principio 1 — Reconstruir el estado del sistema *en el momento del evento*, no el estado actual

El código actual puede tener fixes que no existían cuando ocurrió el fallo. Antes de diagnosticar:

1. Obtener el timestamp del evento (run de Actions, error de pipeline, etc.)
2. Correr mentalmente `git log --oneline --before="<evento.timestamp>"` — ¿qué commits existían?
3. Si el fix relacionado tiene un `commit.timestamp` **posterior** al evento → el fix no existía entonces → el fallo era el comportamiento esperado en esa versión del código → no diagnosticar como bug activo.

> Ejemplo: Run #35 falló el 2026-05-05 20:26. Fix `a77a2e1` fue pusheado a las 00:37 del 2026-05-06. El fix no existía cuando el run corrió → fallo pre-fix → caso cerrado.

---

#### Principio 2 — Construir la cadena causal completa antes de proponer cualquier fix

La estructura obligatoria para cualquier diagnóstico:

```
Causa raíz → Mecanismo de propagación → Síntoma observable → Error reportado
```

No diagnosticar desde el error reportado hacia arriba con el primer encaje plausible. Cada eslabón de la cadena debe estar verificado con evidencia directa.

**Anti-patrón**: Ver "SPY stale" → proponer "agregar SPY a la descarga forzada". Eso parchea el síntoma.  
**Patrón correcto**: Ver "SPY stale" → encontrar por qué `faltantes=0` → encontrar que MTM adelantó `MAX(date)` → fix en la fuente (`_get_ultima_fecha_sentinel()`).

La profundidad del fix debe ser la misma que la profundidad de la causa raíz.

---

#### Principio 3 — Falsificación activa: intentar destruir tu propia hipótesis antes de actuar

Antes de proponer cualquier fix, formular explícitamente la pregunta inversa:
> *"¿Qué tendría que ser verdad para que mi diagnóstico esté EQUIVOCADO?"*

- Si podés responder esa pregunta y descartar esa posibilidad con evidencia concreta → diagnóstico sólido, proceder.
- Si no podés descartarla → existe incertidumbre real. Decirlo al usuario, no inventar certeza.

Ejemplo: Diagnosticás "el run falló por X". Pregunta inversa: "¿Pudo haber fallado por Y?". Si Y es posible y no lo verificaste → verificar antes de commitear el fix.

---

#### Principio 4 — Taxonomía de evidencia: no toda información tiene el mismo peso

| Nivel | Confiabilidad | Fuente típica |
|-------|--------------|---------------|
| Verdad directa | ✅ Alta | Archivo leído en esta sesión, output de query SQL, log de CI expandido |
| Inferencia lógica | ⚠️ Media | Deducción de hechos verificados ("si A y B, entonces C") |
| Patrón conocido | ⚠️ Media-baja | "Este tipo de error suele ser X en este proyecto" |
| Memoria de sesión anterior | ❌ Baja | El repo puede haber cambiado — verificar contra archivos actuales |

Regla: ser explícito sobre qué nivel de evidencia respalda cada afirmación.  
`"Confirmo que el bug es X"` (leí el log) ≠ `"Infiero que el bug podría ser X"` (patrón).  
Nunca presentar inferencia como certeza.

---

#### Principio 5 — Mapa de blast radius antes de cualquier acción con efecto en el repo

Antes de cualquier edición de archivo o `git commit`, responder:

- ¿Qué workflows se disparan? (revisar `paths-ignore` en cada `.github/workflows/*.yml`)
- ¿Este cambio toca datos de Supabase (producción)?
- ¿La acción es reversible?
  - Reversible (editar archivo, leer DB) → proceder libremente
  - Parcialmente reversible (commit, push) → proceder con buen mensaje de commit
  - Irreversible (`DROP TABLE`, `git push --force`, borrar branch) → pedir confirmación explícita al usuario

---

#### Principio 6 — Mínima intervención: el fix correcto es el más pequeño que ataca la causa raíz

El objetivo nunca es refactorizar, mejorar la arquitectura, ni agregar features no solicitados.  
Una línea que resuelve el root cause es mejor que 50 que resuelven el síntoma más varios extras.  
Si el fix propuesto toca más de 3 archivos, preguntarse: ¿cada uno de estos cambios es estrictamente necesario para resolver la causa raíz, o estoy agregando cosas?

---

#### Aplicación a patrones frecuentes en este repo

Estos no son reglas — son ejemplos de cómo los principios anteriores aplican a casos conocidos:

| Observación | Principio que aplica | Razonamiento correcto |
|-------------|---------------------|-----------------------|
| Run de Actions con ❌ | P1: estado en momento del evento | ¿`run.created_at` > timestamp del último fix relacionado? Si no → pre-fix, cerrar. |
| Mismo mensaje que un bug resuelto | P1 + P4: evidencia directa | Verificar que el fix commit estaba en el repo cuando corrió el run. No asumir. |
| `ci.yml` falla con `test_validate_database_url` | P2: cadena causal | Causa raíz conocida: IPv6 + Direct Connection de Supabase en CI. Pre-existente estructural. |
| Dashboard no se actualizó tras push | P5: blast radius | ¿El commit tocó algún `.py`? Si solo `.md` → paths-ignore lo filtró → hacer commit que toque `.py`. |
| Modelo no aparece en live | P4: verdad directa | ¿Predictions/outcomes existen en Supabase? Verificar con query — no asumir que Docker local = Supabase. |

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

**Por qué el 08:00 AR siempre pasaba — detalle técnico preciso:**
La explicación superficial es "corrió antes del intraday-refresh". Eso es verdad en la práctica pero incompleto.
La razón técnica real es `fecha_objetivo_mercado(now)` en `auto_actualizar.py`:
- Si `now.hour < MARKET_CLOSE_HOUR` (19) → retorna **ayer** como fecha objetivo
- `faltantes = objetivo - MAX(date)` → siempre ≥ 1 → siempre descarga EOD
- **Esto es independiente del orden de los crons.** Aunque MTM hubiera corrido antes del 08:00, el pipeline igual forzaría descarga porque el target es ayer, no hoy.

Esto hace el fix mucho más robusto: el 08:00 AR no depende de timing de otros workflows — depende de una propiedad matemática de la hora. La vulnerabilidad era exclusiva del 19:30 AR (único horario donde `hour >= 19` → `fecha_objetivo = hoy` → expuesto al MAX(date) contaminado por MTM).

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
