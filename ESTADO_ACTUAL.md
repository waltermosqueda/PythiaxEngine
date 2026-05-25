<!-- AUTO-GENERADO por scripts/generar_estado_actual.py — NO editar esta sección -->
<!-- generated_at: 2026-05-25T18:44:22Z -->
<!-- git_head: 51c5d36 -->
<!-- git_branch: main -->
<!--
  ⚠️  AVISO PARA AGENTES IA:
  Este header se auto-genera en cada CI run y al final de cada sesión.
  El git_head aquí puede ser VIEJO si el archivo no se regeneró.

  SIEMPRE ejecutar primero:
    1. py -c "from datetime import datetime,timezone,timedelta; u=datetime.now(timezone.utc); a=u-timedelta(hours=3); print('UTC:',u.strftime('%Y-%m-%d %H:%M'),'| AR:',a.strftime('%Y-%m-%d %H:%M'))"
    2. cd C:\repos\PythiaxEngine ; git log --oneline -3 ; git status --short

  Si el HEAD que ves en git ≠ 51c5d36 → secciones de commits abajo DESACTUALIZADAS.
  Si la hora real AR difiere de 2026-05-25 15:44 AR (Lun) → estado de crons abajo DESACTUALIZADO.
-->

# ESTADO ACTUAL — PythiaxEngine

*Auto-generado: 2026-05-25T18:44:22Z | `2026-05-25 15:44 AR (Lun)` | HEAD: `51c5d36`*

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
> - **Si HEAD ≠ `51c5d36`** → sección de commits desactualizada, ignorar.
> - **Si hora AR ≠ `2026-05-25 15:44 AR (Lun)`** → estado de crons abajo desactualizado, recalcular.

---

## ⏰ Ancla temporal (al momento de generación)

| | Valor |
|---|---|
| Generado | `2026-05-25T18:44:22Z` |
| Hora AR | `2026-05-25 15:44 AR (Lun)` |
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

**HEAD:** `51c5d36` — feat(experto): analisis_experto_diario.py + workflow Gemini 2.5 Pro
**Timestamp commit:** 2026-05-25 15:43:29 -0300
**Branch:** main

### Últimos 10 commits
```
51c5d36 feat(experto): analisis_experto_diario.py + workflow Gemini 2.5 Pro
2b1c995 plan_diario: plan de inversion 2026-05-25 [skip ci]
57f5624 chore(auto): update ESTADO_ACTUAL â†’ a4e245424244b46a4a44f0aa6a9302e427e99457 [skip ci]
a4e2454 feat(plan): prob_ajustada con heuristicas honestas + ranking razonado en Telegram
04fd894 feat(plan): workflow para enviar ranking honesto via Telegram
76a123b plan_diario: plan de inversion 2026-05-25 [skip ci]
5f9616f refactor(plan-inversion): remover 'Capital comprometido' / 'Cap USD' del output
3b76a86 plan_diario: plan de inversion 2026-05-25 [skip ci]
0d7342f feat(plan-inversion): MAYOR_RIESGO tier (soft vs hard filters, sizing reducido)
0fd8ac7 plan_diario: plan de inversion 2026-05-25 [skip ci]
```

### Working tree
```
M herramientas/refrescar_datos_dashboard.py
?? _AUDITORIA_PORCENTAJES.md
?? _build_snapshot_from_dashboard.py
?? _real_out/
?? _real_snapshot.json
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
