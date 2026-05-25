<!-- AUTO-GENERADO por scripts/generar_estado_actual.py — NO editar esta sección -->
<!-- generated_at: 2026-05-25T02:23:00Z -->
<!-- git_head: 78a2d46 -->
<!-- git_branch: main -->
<!--
  ⚠️  AVISO PARA AGENTES IA:
  Este header se auto-genera en cada CI run y al final de cada sesión.
  El git_head aquí puede ser VIEJO si el archivo no se regeneró.

  SIEMPRE ejecutar primero:
    1. py -c "from datetime import datetime,timezone,timedelta; u=datetime.now(timezone.utc); a=u-timedelta(hours=3); print('UTC:',u.strftime('%Y-%m-%d %H:%M'),'| AR:',a.strftime('%Y-%m-%d %H:%M'))"
    2. cd C:\repos\PythiaxEngine ; git log --oneline -3 ; git status --short

  Si el HEAD que ves en git ≠ 78a2d46 → secciones de commits abajo DESACTUALIZADAS.
  Si la hora real AR difiere de 2026-05-24 23:23 AR (Dom) → estado de crons abajo DESACTUALIZADO.
-->

# ESTADO ACTUAL — PythiaxEngine

*Auto-generado: 2026-05-25T02:23:00Z | `2026-05-24 23:23 AR (Dom)` | HEAD: `78a2d46`*

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
> - **Si HEAD ≠ `78a2d46`** → sección de commits desactualizada, ignorar.
> - **Si hora AR ≠ `2026-05-24 23:23 AR (Dom)`** → estado de crons abajo desactualizado, recalcular.

---

## ⏰ Ancla temporal (al momento de generación)

| | Valor |
|---|---|
| Generado | `2026-05-25T02:23:00Z` |
| Hora AR | `2026-05-24 23:23 AR (Dom)` |
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

**HEAD:** `78a2d46` — fix(tests): restore CI green â€” fix 7 failing unit tests
**Timestamp commit:** 2026-05-24 23:22:35 -0300
**Branch:** main

### Últimos 10 commits
```
78a2d46 fix(tests): restore CI green â€” fix 7 failing unit tests
b1e7ce8 fix(pipeline): load_runtime_market_dates y freshness_report leen precios de TitanDB
05db001 fix(titandb): always use local SQLite â€” eliminate 11k Supabase price reads/day
0ceb7b3 chore: trigger Pages deploy for senales NUEVAS
211fffb chore(auto): update ESTADO_ACTUAL â†’ 3ba9e47 [skip ci]
3ba9e47 fix: senales NUEVAS â€” add explicit 'nuevas' to chip and ticker labels
c729a22 chore(auto): update ESTADO_ACTUAL â†’ ea8d919 [skip ci]
ea8d919 fix: clarify senales activas strip -- SENALES/ABIERTAS label + MTM context + sig. date prefix
2390222 dashboard: improve Portfolio Performance chart readability
79d4515 chore(auto): update ESTADO_ACTUAL â†’ 21f03be [skip ci]
```

### Working tree
```
?? _AUDITORIA_PORCENTAJES.md
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
