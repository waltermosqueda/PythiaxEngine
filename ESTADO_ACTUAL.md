<!-- AUTO-GENERADO por scripts/generar_estado_actual.py — NO editar esta sección -->
<!-- generated_at: 2026-05-07T04:32:48Z -->
<!-- git_head: 8afa058 -->
<!-- git_branch: main -->
<!--
  ⚠️  AVISO PARA AGENTES IA:
  Este header se auto-genera en cada CI run y al final de cada sesión.
  El git_head aquí puede ser VIEJO si el archivo no se regeneró.

  SIEMPRE ejecutar primero:
    1. py -c "from datetime import datetime,timezone,timedelta; u=datetime.now(timezone.utc); a=u-timedelta(hours=3); print('UTC:',u.strftime('%Y-%m-%d %H:%M'),'| AR:',a.strftime('%Y-%m-%d %H:%M'))"
    2. cd C:\repos\PythiaxEngine ; git log --oneline -3 ; git status --short

  Si el HEAD que ves en git ≠ 8afa058 → secciones de commits abajo DESACTUALIZADAS.
  Si la hora real AR difiere de 2026-05-07 01:32 AR (Jue) → estado de crons abajo DESACTUALIZADO.
-->

# ESTADO ACTUAL — PythiaxEngine

*Auto-generado: 2026-05-07T04:32:48Z | `2026-05-07 01:32 AR (Jue)` | HEAD: `8afa058`*

---

## ⚡ VERIFICACIÓN OBLIGATORIA AL INICIAR SESIÓN

> Ejecutar en terminal ANTES de leer cualquier cosa:
>
> ```powershell
> # 1. Hora real
> py -c "from datetime import datetime,timezone,timedelta; u=datetime.now(timezone.utc); a=u-timedelta(hours=3); dias=['Lun','Mar','Mie','Jue','Vie','Sab','Dom']; print('UTC: '+u.strftime('%Y-%m-%d %H:%M')+' | AR: '+a.strftime('%Y-%m-%d %H:%M')+' ('+dias[a.weekday()]+')')"
> # 2. Git
> cd C:\repos\PythiaxEngine ; git log --oneline -5 ; git status --short
> ```
>
> - **Si HEAD ≠ `8afa058`** → sección de commits desactualizada, ignorar.
> - **Si hora AR ≠ `2026-05-07 01:32 AR (Jue)`** → estado de crons abajo desactualizado, recalcular.

---

## ⏰ Ancla temporal (al momento de generación)

| | Valor |
|---|---|
| Generado | `2026-05-07T04:32:48Z` |
| Hora AR | `2026-05-07 01:32 AR (Jue)` |
| Argentina | UTC-3, **sin DST** (nunca cambia) |
| NYSE abre | 09:30 ET (EDT=UTC-4 verano) = **13:30 UTC = 10:30 AR** |

### Estado crons intraday al momento de generación
```
  13:30 UTC = 10:30 AR  [⏳ PENDIENTE]
  14:30 UTC = 11:30 AR  [⏳ PENDIENTE]
  15:30 UTC = 12:30 AR  [⏳ PENDIENTE]
  16:30 UTC = 13:30 AR  [⏳ PENDIENTE]
  17:30 UTC = 14:30 AR  [⏳ PENDIENTE]
  18:30 UTC = 15:30 AR  [⏳ PENDIENTE]
  19:30 UTC = 16:30 AR  [⏳ PENDIENTE]
  20:30 UTC = 17:30 AR  [⏳ PENDIENTE]
```

**Pipeline diario** (19:30 AR = 22:30 UTC): `⏳ PENDIENTE`

---

## Estado git (al momento de generación)

**HEAD:** `8afa058` — feat(ops): P7 analisis de impacto bidireccional pre-implementacion
**Timestamp commit:** 2026-05-07 01:32:38 -0300
**Branch:** main

### Últimos 10 commits
```
8afa058 feat(ops): P7 analisis de impacto bidireccional pre-implementacion
17237b0 chore(auto): update ESTADO_ACTUAL â†’ a41d43d [skip ci]
a41d43d fix(perf): validate_market_data CTE full scan â†’ timeout 600s resuelto
f4e1414 fix(ops): ancla temporal AR/UTC en ESTADO_ACTUAL + FIRST ACTION protocolo
f0a2b6b feat(ops): auto-generar ESTADO_ACTUAL.md desde CI + fix protocolo copilot
a90c105 fix(ci): test_validate_db_url - pasar github_actions=False explicitamente para no depender de env GITHUB_ACTIONS
f2af09c feat(ci): intraday MTM cada hora durante la rueda NYSE (3->8 runs/dia)
9e540ef fix(ci): rebase before push in sync step to handle concurrent commits
16cd442 feat(picks): precio actual en picks abiertos + sync Supabaseâ†’local
e708636 fix(kpi): card Sistema â€” tooltip z-index + mouseleave debounce
```

### Working tree
```
M herramientas/audit_precios_live.py
?? =
?? _patch_tooltip.py
?? _patch_tooltip_v2.py
?? analisis/_gen_log.txt
?? analisis/_hybrid_A.html
?? analisis/_hybrid_B.html
?? analisis/_hybrid_C.html
?? analisis/_light_previews.html
?? analisis/_preview_warm_pearl.html
?? analisis/_staging_kpi_sistema.html
?? analisis/_staging_prod_preview.html
?? analisis/svb_preview_options.html
?? scripts/kill_idle_terminals.ps1
?? test-results-local.xml
```

---

## Errores críticos

### ✅ Sin errores pendientes en `logs/errores_criticos.json`

---

<!-- MANUAL_NOTES_START -->
## Próximos pasos al reiniciar sesión

> Editar esta sección al final de cada sesión. Se preserva entre regeneraciones.

1. Leer errores pendientes (arriba en este archivo — auto-generado)
2. Verificar que el cron de 19:30 AR haya pasado con éxito
   → https://github.com/waltermosqueda/PythiaxEngine/actions → "Cloud Daily Operations"
3. Ver pendientes estructurales abajo.

---

## Pendientes estructurales

- **V94 migration** (2026-05-11): correr outcomes, luego bulk insert ARM + INTC en Supabase
- **Cloudflare Access**: pythiaxengine.pages.dev sigue público
  → Fail open → Fail closed en Workers & Pages → Settings → Runtime

---

## Decisiones importantes / reglas que NO hay que romper

- `_get_ultima_fecha_sentinel()` en `auto_actualizar.py` resuelve el problema de
  MTM intraday parcial que adelanta `MAX(date)`. **NO revertir.**
- En rebase, `--theirs` = nuestro commit local (semántica invertida vs merge).
  Para `preview_c1_pro.html` en rebase: `git checkout --theirs`.
- `ml_trading_v22.py` = archivo fuente **intocable**. Toda variante en archivo nuevo.
- Sync commit NO debe tener `[skip ci]` → Cloudflare lo ignoraría.
  `analisis/preview_c1_pro.html` está en `paths-ignore` del trigger para evitar loop.
<!-- MANUAL_NOTES_END -->
