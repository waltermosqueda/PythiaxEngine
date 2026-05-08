<!-- AUTO-GENERADO por scripts/generar_estado_actual.py — NO editar esta sección -->
<!-- generated_at: 2026-05-08T00:46:25Z -->
<!-- git_head: 94d35fe -->
<!-- git_branch: main -->
<!--
  ⚠️  AVISO PARA AGENTES IA:
  Este header se auto-genera en cada CI run y al final de cada sesión.
  El git_head aquí puede ser VIEJO si el archivo no se regeneró.

  SIEMPRE ejecutar primero:
    1. py -c "from datetime import datetime,timezone,timedelta; u=datetime.now(timezone.utc); a=u-timedelta(hours=3); print('UTC:',u.strftime('%Y-%m-%d %H:%M'),'| AR:',a.strftime('%Y-%m-%d %H:%M'))"
    2. cd C:\repos\PythiaxEngine ; git log --oneline -3 ; git status --short

  Si el HEAD que ves en git ≠ 94d35fe → secciones de commits abajo DESACTUALIZADAS.
  Si la hora real AR difiere de 2026-05-07 21:46 AR (Jue) → estado de crons abajo DESACTUALIZADO.
-->

# ESTADO ACTUAL — PythiaxEngine

*Auto-generado: 2026-05-08T00:46:25Z | `2026-05-07 21:46 AR (Jue)` | HEAD: `94d35fe`*

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
> - **Si HEAD ≠ `94d35fe`** → sección de commits desactualizada, ignorar.
> - **Si hora AR ≠ `2026-05-07 21:46 AR (Jue)`** → estado de crons abajo desactualizado, recalcular.

---

## ⏰ Ancla temporal (al momento de generación)

| | Valor |
|---|---|
| Generado | `2026-05-08T00:46:25Z` |
| Hora AR | `2026-05-07 21:46 AR (Jue)` |
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

**HEAD:** `94d35fe` — fix(ci): eliminar dashboard gen de intraday — reducir egress Supabase 800→16 MB/día
**Timestamp commit:** 2026-05-07 21:43:03 -0300
**Branch:** main

### Últimos 10 commits
```
94d35fe fix(ci): eliminar dashboard gen de intraday — reducir egress Supabase 800→16 MB/día
b57ac8c chore(auto): update ESTADO_ACTUAL → f78e7808452c85374dee2be67e24cca5f80f2229 [skip ci]
dea2d79 chore(auto): sync dashboard HTML
a47784e docs(rules): agregar REGLA CRÍTICA día de semana — nunca asumir sin calcular [skip ci]
02c9f69 chore(ci): mover cron principal 22:30→21:30 UTC (19:30→18:30 AR) para evitar pico scheduler GitHub
f78e780 fix(ci): ESTADO_ACTUAL rebase falla con uncommitted changes — git checkout antes del pull
8640a2a chore(auto): sync dashboard HTML intraday
f5178af chore(auto): sync dashboard HTML intraday
705bcab chore(auto): update ESTADO_ACTUAL → b7b09a1 [skip ci]
b7b09a1 fix(kpi-sistema): tooltip position:fixed escapa overflow:hidden de main-wrap
```

### Working tree
```
?? herramientas/generar_v2_previews.py
?? herramientas/generar_v2_staging.py
?? herramientas/staging_server.py
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
