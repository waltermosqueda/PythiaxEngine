<!-- AUTO-GENERADO por scripts/generar_estado_actual.py — NO editar esta sección -->
<!-- generated_at: 2026-05-08T18:33:52Z -->
<!-- git_head: 72f7546 -->
<!-- git_branch: main -->
<!--
  ⚠️  AVISO PARA AGENTES IA:
  Este header se auto-genera en cada CI run y al final de cada sesión.
  El git_head aquí puede ser VIEJO si el archivo no se regeneró.

  SIEMPRE ejecutar primero:
    1. py -c "from datetime import datetime,timezone,timedelta; u=datetime.now(timezone.utc); a=u-timedelta(hours=3); print('UTC:',u.strftime('%Y-%m-%d %H:%M'),'| AR:',a.strftime('%Y-%m-%d %H:%M'))"
    2. cd C:\repos\PythiaxEngine ; git log --oneline -3 ; git status --short

  Si el HEAD que ves en git ≠ 72f7546 → secciones de commits abajo DESACTUALIZADAS.
  Si la hora real AR difiere de 2026-05-08 15:33 AR (Vie) → estado de crons abajo DESACTUALIZADO.
-->

# ESTADO ACTUAL — PythiaxEngine

*Auto-generado: 2026-05-08T18:33:52Z | `2026-05-08 15:33 AR (Vie)` | HEAD: `72f7546`*

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
> - **Si HEAD ≠ `72f7546`** → sección de commits desactualizada, ignorar.
> - **Si hora AR ≠ `2026-05-08 15:33 AR (Vie)`** → estado de crons abajo desactualizado, recalcular.

---

## ⏰ Ancla temporal (al momento de generación)

| | Valor |
|---|---|
| Generado | `2026-05-08T18:33:52Z` |
| Hora AR | `2026-05-08 15:33 AR (Vie)` |
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
  19:30 UTC = 16:30 AR  [⏳ PENDIENTE]
  20:30 UTC = 17:30 AR  [⏳ PENDIENTE]
```

**Pipeline diario** (19:30 AR = 22:30 UTC): `⏳ PENDIENTE`

---

## Estado git (al momento de generación)

**HEAD:** `72f7546` — feat: live prices JS via Supabase anon REST â€” updates on page load, hourly intraday data
**Timestamp commit:** 2026-05-08 15:33:29 -0300
**Branch:** main

### Últimos 10 commits
```
72f7546 feat: live prices JS via Supabase anon REST â€” updates on page load, hourly intraday data
2992700 chore(auto): update ESTADO_ACTUAL â†’ beb9ab2 [skip ci]
beb9ab2 Revert "feat(dashboard): panel Senales Vivas A (Full) en violet_dense - ticker+pct+precio+fecha con scroll y altura = ranking"
6569f4b Revert "chore(auto): update ESTADO_ACTUAL â†’ 4a9b699 [skip ci]"
2e6b27b chore(auto): update ESTADO_ACTUAL â†’ 4a9b699 [skip ci]
4a9b699 feat(dashboard): panel Senales Vivas A (Full) en violet_dense - ticker+pct+precio+fecha con scroll y altura = ranking
b4497ff chore(auto): update ESTADO_ACTUAL â†’ dcaa372a0600de52399d0b630aa4ba57c16dd2b2 [skip ci]
dcaa372 chore(auto): update ESTADO_ACTUAL â†’ 754847fda9c99c6c624c08e164d18cfe64ca3bcb [skip ci]
754847f chore(auto): update ESTADO_ACTUAL â†’ 94d35fe [skip ci]
94d35fe fix(ci): eliminar dashboard gen de intraday â€” reducir egress Supabase 800â†’16 MB/dÃ­a
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
?? scripts/_analyze_html.py
?? scripts/_apply_rls.py
?? scripts/_check_lmt.py
?? scripts/_check_precios.py
?? scripts/_deploy_live_prices.py
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
