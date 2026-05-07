<!-- AUTO-GENERADO por scripts/generar_estado_actual.py — NO editar esta sección -->
<!-- generated_at: 2026-05-07T03:38:07Z -->
<!-- git_head: a90c105 -->
<!-- git_branch: main -->
<!--
  ⚠️  AVISO PARA AGENTES IA:
  Este header se auto-genera en cada CI run y al final de cada sesión.
  El git_head aquí puede ser VIEJO si el archivo no se regeneró.

  SIEMPRE ejecutar esto PRIMERO antes de leer cualquier sección:
      cd C:\repos\PythiaxEngine ; git log --oneline -3 ; git status --short

  Si el HEAD que ves allí ≠ a90c105 → las secciones de commits abajo
  están DESACTUALIZADAS. Usar solo git como fuente de verdad para estado de código.
-->

# ESTADO ACTUAL — PythiaxEngine

*Auto-generado: 2026-05-07T03:38:07Z | HEAD: `a90c105` (`fix(ci): test_validate_db_url - pasar github_actions=False explicitamente para no depender de env GITHUB_ACTIONS`)*

---

## ⚡ VERIFICACIÓN OBLIGATORIA AL INICIAR SESIÓN

> Antes de leer CUALQUIER COSA de este archivo, ejecutar en terminal:
>
> ```powershell
> cd C:\repos\PythiaxEngine ; git log --oneline -5 ; git status --short
> ```
>
> **Si HEAD ≠ `a90c105`** → este archivo está desactualizado para git.
> Ignorar las secciones de commits. Confiar solo en la salida de git.

---

## Estado git (al momento de generación)

**HEAD:** `a90c105` — fix(ci): test_validate_db_url - pasar github_actions=False explicitamente para no depender de env GITHUB_ACTIONS
**Timestamp commit:** 2026-05-06 23:39:05 -0300
**Branch:** main

### Últimos 10 commits
```
a90c105 fix(ci): test_validate_db_url - pasar github_actions=False explicitamente para no depender de env GITHUB_ACTIONS
f2af09c feat(ci): intraday MTM cada hora durante la rueda NYSE (3->8 runs/dia)
9e540ef fix(ci): rebase before push in sync step to handle concurrent commits
16cd442 feat(picks): precio actual en picks abiertos + sync Supabaseâ†’local
e708636 fix(kpi): card Sistema â€” tooltip z-index + mouseleave debounce
8bd17c6 chore(auto): sync dashboard HTML
80ea284 fix(dashboard): kpi-strip repeat(4) -- 4 cards generados por _render_kpi_strip
3a35854 revert(dashboard): rollback HTML a 0ef66eb â€” restablecer layout correcto (pre-SEMAFORO)
3610881 chore(ci): trigger gh-pages deploy Sistema card
f8924d2 feat(kpi): card Sistema unificado -- tooltip hover con datos integros y al dia
```

### Working tree
```
M .github/copilot-instructions.md
 M .github/workflows/cloud-daily-operations.yml
 M herramientas/audit_precios_live.py
 M logs/errores_criticos.json
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
?? scripts/generar_estado_actual.py
?? scripts/kill_idle_terminals.ps1
?? test-results-local.xml
```

---

## Errores críticos

### ⚠️ Errores pendientes

- `2026-05-06T19:28:33.377174-03:00` — **pipeline_critical_alert**
  > 2026-05-06 19:28  [CRITICAL ALERT] pipeline_step_timeout_validacion | El paso validacion del pipeline diario expiro por timeout.


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
