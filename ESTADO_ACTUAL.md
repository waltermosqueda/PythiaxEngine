<!-- AUTO-GENERADO por scripts/generar_estado_actual.py — NO editar esta sección -->
<!-- generated_at: 2026-05-20T23:58:09Z -->
<!-- git_head: 9f9a213 -->
<!-- git_branch: main -->
<!--
  ⚠️  AVISO PARA AGENTES IA:
  Este header se auto-genera en cada CI run y al final de cada sesión.
  El git_head aquí puede ser VIEJO si el archivo no se regeneró.

  SIEMPRE ejecutar primero:
    1. py -c "from datetime import datetime,timezone,timedelta; u=datetime.now(timezone.utc); a=u-timedelta(hours=3); print('UTC:',u.strftime('%Y-%m-%d %H:%M'),'| AR:',a.strftime('%Y-%m-%d %H:%M'))"
    2. cd C:\repos\PythiaxEngine ; git log --oneline -3 ; git status --short

  Si el HEAD que ves en git ≠ 9f9a213 → secciones de commits abajo DESACTUALIZADAS.
  Si la hora real AR difiere de 2026-05-20 20:58 AR (Mie) → estado de crons abajo DESACTUALIZADO.
-->

# ESTADO ACTUAL — PythiaxEngine

*Auto-generado: 2026-05-20T23:58:09Z | `2026-05-20 20:58 AR (Mie)` | HEAD: `9f9a213`*

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
> - **Si HEAD ≠ `9f9a213`** → sección de commits desactualizada, ignorar.
> - **Si hora AR ≠ `2026-05-20 20:58 AR (Mie)`** → estado de crons abajo desactualizado, recalcular.

---

## ⏰ Ancla temporal (al momento de generación)

| | Valor |
|---|---|
| Generado | `2026-05-20T23:58:09Z` |
| Hora AR | `2026-05-20 20:58 AR (Mie)` |
| Argentina | UTC-3, **sin DST** (nunca cambia) |
| NYSE abre | 09:30 ET (EDT=UTC-4 verano) = **13:30 UTC = 10:30 AR** |

### Estado crons intraday al momento de generación
```
  13:30 UTC = 10:30 AR  [✅ PASADO]
  14:30 UTC = 11:30 AR  [✅ PASADO]
  15:30 UTC = 12:30 AR  [✅ PASADO]
  16:30 UTC = 13:30 AR  [✅ PASADO]
  17:30 UTC = 14:30 AR  [✅ PASADO]
  18:30 UTC = 15:30 AR  [✅ PASADO]
  19:30 UTC = 16:30 AR  [✅ PASADO]
  20:30 UTC = 17:30 AR  [✅ PASADO]
```

**Pipeline diario** (19:30 AR = 22:30 UTC): `✅ PASADO`

---

## Estado git (al momento de generación)

**HEAD:** `9f9a213` — fix(dashboard): update live-prices Supabase URL+key to new project (okbqqhitseeknruoycby)
**Timestamp commit:** 2026-05-20 20:57:53 -0300
**Branch:** main

### Últimos 10 commits
```
9f9a213 fix(dashboard): update live-prices Supabase URL+key to new project (okbqqhitseeknruoycby)
cfce22c chore(auto): update ESTADO_ACTUAL â†’ 5a87f646a379179f0766cf288997de3ec96e1283 [skip ci]
06e5c42 chore(auto): sync dashboard HTML
5a87f64 chore(auto): update ESTADO_ACTUAL â†’ df5d1e3b28ee1e6e61f6620472853f764c722617 [skip ci]
147e21d chore(auto): sync dashboard HTML
df5d1e3 fix: disable prepared statements in session factory (PgBouncer/Supabase pooler)
aa5c10e chore(auto): update ESTADO_ACTUAL â†’ 0e8e729d5f5b6dd56194b2fb1808e86b0d6fe873 [skip ci]
0e8e729 chore(auto): update ESTADO_ACTUAL â†’ 22fd493 [skip ci]
22fd493 fix(infra): importar_datos_migracion - 3 fixes para Supabase pooler
c05fd2b fix(egress): reducir pipeline diario de 3 a 1 cron/dia
```

### Working tree
```
?? analisis/_find_tkb1_end.py
?? analisis/_inject_h7_complete.py
?? analisis/_inject_ticker_b1.py
?? analisis/_map_h7t3b.py
?? analisis/_ranking_bloomberg_shot.png
?? analisis/_ranking_preview_shot.png
?? analisis/_read_body.py
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
