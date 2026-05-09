<!-- AUTO-GENERADO por scripts/generar_estado_actual.py — NO editar esta sección -->
<!-- generated_at: 2026-05-09T00:37:15Z -->
<!-- git_head: c2f0766 -->
<!-- git_branch: main -->
<!--
  ⚠️  AVISO PARA AGENTES IA:
  Este header se auto-genera en cada CI run y al final de cada sesión.
  El git_head aquí puede ser VIEJO si el archivo no se regeneró.

  SIEMPRE ejecutar primero:
    1. py -c "from datetime import datetime,timezone,timedelta; u=datetime.now(timezone.utc); a=u-timedelta(hours=3); print('UTC:',u.strftime('%Y-%m-%d %H:%M'),'| AR:',a.strftime('%Y-%m-%d %H:%M'))"
    2. cd C:\repos\PythiaxEngine ; git log --oneline -3 ; git status --short

  Si el HEAD que ves en git ≠ c2f0766 → secciones de commits abajo DESACTUALIZADAS.
  Si la hora real AR difiere de 2026-05-08 21:37 AR (Vie) → estado de crons abajo DESACTUALIZADO.
-->

# ESTADO ACTUAL — PythiaxEngine

*Auto-generado: 2026-05-09T00:37:15Z | `2026-05-08 21:37 AR (Vie)` | HEAD: `c2f0766`*

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
> - **Si HEAD ≠ `c2f0766`** → sección de commits desactualizada, ignorar.
> - **Si hora AR ≠ `2026-05-08 21:37 AR (Vie)`** → estado de crons abajo desactualizado, recalcular.

---

## ⏰ Ancla temporal (al momento de generación)

| | Valor |
|---|---|
| Generado | `2026-05-09T00:37:15Z` |
| Hora AR | `2026-05-08 21:37 AR (Vie)` |
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

**HEAD:** `c2f0766` — chore: regenerar dashboard post-fix outcomes May 4-8
**Timestamp commit:** 2026-05-08 21:36:54 -0300
**Branch:** main

### Últimos 10 commits
```
c2f0766 chore: regenerar dashboard post-fix outcomes May 4-8
43a84bc chore(auto): update ESTADO_ACTUAL â†’ 354a213 [skip ci]
354a213 fix: proteger open price en capa de sync y guard en v12 evaluator
2233f93 chore(auto): update ESTADO_ACTUAL â†’ 0d70dd4 [skip ci]
1b30935 fix: prevenir outcomes=0.0 por precios intraday open=close
fe52e7c chore(auto): update ESTADO_ACTUAL â†’ a1a0a3d72f94802701aedc7fb80cb7f213d5299b [skip ci]
846c332 chore(auto): sync dashboard HTML
a1a0a3d chore(auto): update ESTADO_ACTUAL â†’ c6531ce [skip ci]
c6531ce feat: prices.fetched_at â€” sync escribe timestamp real de descarga YF en Supabase
c452943 feat: live prices JS via Supabase anon REST â€” updates on page load, hourly intraday data
```

### Working tree
```
?? analisis/_ranking_bloomberg_shot.png
?? analisis/_ranking_preview_shot.png
?? herramientas/generar_ranking_preview.py
?? herramientas/generar_v2_previews.py
?? herramientas/generar_v2_staging.py
?? herramientas/generar_v2d_previews.py
?? herramientas/staging_server.py
?? logs/_fix_run.txt
?? scripts/_analyze_html.py
?? scripts/_apply_rls.py
?? scripts/_check_lmt.py
?? scripts/_check_precios.py
?? scripts/_check_timestamps.py
?? scripts/_deploy_live_prices.py
?? scripts/_diag2.py
?? scripts/_diag3.py
?? scripts/_diag4.py
?? scripts/_diag5.py
?? scripts/_diag6.py
?? scripts/_diag_slb_lac.py
?? scripts/_diag_ticker_hist.py
?? scripts/_diag_yf.py
?? scripts/_diagnostico_integridad.py
?? scripts/_fix_cols.py
?? scripts/_tmp_extract_sparks.py
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
