# ESTADO ACTUAL — PythiaxEngine

*Archivo de handoff entre sesiones. Leer al inicio, actualizar al final.*

---

## LEER AL INICIO DE CADA SESION

1. Leer `logs/errores_criticos.json` — si hay entradas `"status": "pendiente"`, reportar y proponer fix
2. Verificar salud del dashboard en Cloudflare: `https://pythiaxengine.pages.dev/preview_c1_pro`
3. Si es dia habil despues de las 21:00 AR, verificar que el cron de 19:30 AR haya pasado

---

## Estado al 2026-05-06 (sesion actual)

### Bug 7 — RESUELTO (commit `a77a2e1`)

**Root cause:** `intraday-mtm-refresh.yml` (cron 16:30 AR) hace upsert en `prices`
para tickers con picks abiertos (no SPY/QQQ), adelantando `MAX(date)` a la fecha
actual. El pipeline de 19:30 AR veia `faltantes=0` y saltaba la descarga EOD.
`validate_market_data.py` detectaba SPY stale y fallaba. Steps 9-18 quedaban skipped.

**Fix:**
- `herramientas/auto_actualizar.py`: `_get_ultima_fecha_sentinel()` — si SPY/QQQ
  < MAX global, usa su fecha para forzar descarga EOD completa
- `.github/workflows/cloud-daily-operations.yml`: `if: "!cancelled()"` en step
  "Decide cloud refresh" para evitar cascade skip

### Error pendiente — outcomes_v12 timeout

- `logs/errores_criticos.json` tiene 1 entrada pendiente:
  `2026-05-05 00:00 [CRITICAL ALERT] pipeline_step_timeout_outcomes_v12`
- Causa probable: V12 tarda demasiado calculando outcomes a la medianoche
- Accion recomendada proxima sesion: leer el log de V12 y evaluar si hay un
  loop o query lenta; considerar agregar timeout explicito al paso

### Git status

- Branch: `main`
- Ultimo commit pusheado: `124cde3` (docs: bitacora sesion 2026-05-06)
- Commits de esta sesion: `a77a2e1` (Bug 7), `124cde3` (bitacora)
- Todo pusheado, rama limpia

### DB state (Supabase)

- LEGACY_ML_BRAIN_V10_BUY_D5: 182 predictions, 172 outcomes OK
- LEGACY_ML_BRAIN_V9_BUY_D5: 0 rows — disabled, NO migrar
- LEGACY_ML_V94_BUY_D5: 0 rows en Supabase / 2 rows local (ARM + INTC)
  → migrar el 2026-05-11 cuando venza el target

---

## Proximos pasos al reiniciar sesion

1. Leer `logs/errores_criticos.json` (regla de inicio)
2. Verificar que el cron de 19:30 AR del 2026-05-06 haya pasado con exito
   → `https://github.com/waltermosqueda/PythiaxEngine/actions` → ultimo run "Cloud Daily Operations"
3. Investigar `outcomes_v12` timeout (unica entrada pendiente en errores_criticos.json)
4. El 2026-05-11: migrar LEGACY_ML_V94_BUY_D5 a Supabase (2 rows: ARM + INTC)

---

## Pendientes estructurales

- **Cloudflare Access**: pagina `pythiaxengine.pages.dev` sigue publica
  → cambiar Fail open → Fail closed en Workers & Pages → Settings → Runtime
- **V94 migration**: esperar a 2026-05-11, correr outcomes, luego bulk insert

---

## Infraestructura

| Componente | Detalle |
|------------|---------|
| Python CI  | `py` (Python 3.12 en Actions, 3.14.x local) |
| DB cloud   | Supabase — URL en `.env` linea comentada `# DATABASE_URL=...` |
| DB local   | Docker puerto 5433 (`pythiax_staging_postgres`) |
| Repo       | `C:\repos\PythiaxEngine` |
| Branch     | main |
| Cloudflare | `https://pythiaxengine.pages.dev/` (rama main, dir `analisis/`) |
| GitHub Pages | `https://waltermosqueda.github.io/PythiaxEngine/` |

---

## Reglas criticas (ver AGENTS.md y copilot-instructions.md)

- **SENTINEL CHECK**: `_get_ultima_fecha_sentinel()` en auto_actualizar.py resuelve
  el problema de MTM intraday parcial. NO revertir.
- **BACKFILL FAIR-START**: Antes de backfill nuevo, `SELECT MIN(prediction_date) FROM predictions WHERE model_name LIKE '<familia>%'`
- **Commits que no disparan CI**: los que solo tocan `.md`, `docs/`, `tests/`, `bitacora/`
- **preview_c1_pro.html**: en rebase, usar `--theirs` (= nuestro local) para conservar version fresca
