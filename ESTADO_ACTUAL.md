<!-- AUTO-GENERADO por scripts/generar_estado_actual.py — NO editar esta sección -->
<!-- generated_at: 2026-06-01T01:43:06Z -->
<!-- git_head: 5205300 -->
<!-- git_branch: main -->
<!--
  ⚠️  AVISO PARA AGENTES IA:
  Este header se auto-genera en cada CI run y al final de cada sesión.
  El git_head aquí puede ser VIEJO si el archivo no se regeneró.

  SIEMPRE ejecutar primero:
    1. py -c "from datetime import datetime,timezone,timedelta; u=datetime.now(timezone.utc); a=u-timedelta(hours=3); print('UTC:',u.strftime('%Y-%m-%d %H:%M'),'| AR:',a.strftime('%Y-%m-%d %H:%M'))"
    2. cd C:\repos\PythiaxEngine ; git log --oneline -3 ; git status --short

  Si el HEAD que ves en git ≠ 5205300 → secciones de commits abajo DESACTUALIZADAS.
  Si la hora real AR difiere de 2026-05-31 22:43 AR (Dom) → estado de crons abajo DESACTUALIZADO.
-->

# ESTADO ACTUAL — PythiaxEngine

*Auto-generado: 2026-06-01T01:43:06Z | `2026-05-31 22:43 AR (Dom)` | HEAD: `5205300`*

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
> - **Si HEAD ≠ `5205300`** → sección de commits desactualizada, ignorar.
> - **Si hora AR ≠ `2026-05-31 22:43 AR (Dom)`** → estado de crons abajo desactualizado, recalcular.

---

## ⏰ Ancla temporal (al momento de generación)

| | Valor |
|---|---|
| Generado | `2026-06-01T01:43:06Z` |
| Hora AR | `2026-05-31 22:43 AR (Dom)` |
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

**HEAD:** `5205300` — fix(dashboard): heatmap today column for prior-signal models + label fix
**Timestamp commit:** 2026-05-31 22:42:51 -0300
**Branch:** main

### Últimos 10 commits
```
5205300 fix(dashboard): heatmap today column for prior-signal models + label fix
6456b0c fix(heatmap): show open picks in today column for multi-day window models
22976ee fix(dashboard): restore missing closing div for h7-chip-signals
3bc2ac1 chore(auto): update ESTADO_ACTUAL â†’ cd5b484 [skip ci]
cd5b484 fix(dashboard): add h7-champ/chip/ticker markers; fix Mercado+Actualiz chips; regenerate with Jun01 close data
f217174 Merge pull request #1 from waltermosqueda/fix/freshness-client-utc
7edbb19 Merge fix/freshness-client-utc -> main (agent)
037621e fix(freshness): treat naive data-ts as UTC in client freshness updater (update submodule pointer)
9b0d6f3 infra(cloud): add generated_at and tracebacks to audit payload\n\nAdd generated_at/generated_at_display and sanitized tracebacks in audit payload and error handler.
ca45068 infra(cloud): include checks/failures in audit error payload for robust diagnostics
```

### Working tree
```
?? _audit_db_query.py
?? _audit_full.py
?? _audit_snapshot.py
?? _q1.py
?? _q2.py
?? _q3.py
?? _q4.py
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
