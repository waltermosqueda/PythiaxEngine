<!-- AUTO-GENERADO por scripts/generar_estado_actual.py — NO editar esta sección -->
<!-- generated_at: 2026-05-07T21:24:19Z -->
<!-- git_head: 114e7fa -->
<!-- git_branch: main -->
<!--
  ⚠️  AVISO PARA AGENTES IA:
  Este header se auto-genera en cada CI run y al final de cada sesión.
  El git_head aquí puede ser VIEJO si el archivo no se regeneró.

  SIEMPRE ejecutar primero:
    1. py -c "from datetime import datetime,timezone,timedelta; u=datetime.now(timezone.utc); a=u-timedelta(hours=3); print('UTC:',u.strftime('%Y-%m-%d %H:%M'),'| AR:',a.strftime('%Y-%m-%d %H:%M'))"
    2. cd C:\repos\PythiaxEngine ; git log --oneline -3 ; git status --short

  Si el HEAD que ves en git ≠ 114e7fa → secciones de commits abajo DESACTUALIZADAS.
  Si la hora real AR difiere de 2026-05-07 18:24 AR (Jue) → estado de crons abajo DESACTUALIZADO.
-->

# ESTADO ACTUAL — PythiaxEngine

*Auto-generado: 2026-05-07T21:24:19Z | `2026-05-07 18:24 AR (Jue)` | HEAD: `114e7fa`*

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
> - **Si HEAD ≠ `114e7fa`** → sección de commits desactualizada, ignorar.
> - **Si hora AR ≠ `2026-05-07 18:24 AR (Jue)`** → estado de crons abajo desactualizado, recalcular.

---

## ⏰ Ancla temporal (al momento de generación)

| | Valor |
|---|---|
| Generado | `2026-05-07T21:24:19Z` |
| Hora AR | `2026-05-07 18:24 AR (Jue)` |
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

**Pipeline diario** (19:30 AR = 22:30 UTC): `⏳ PENDIENTE`

---

## Estado git (al momento de generación)

**HEAD:** `114e7fa` — chore(ci): cron one-time 21:24 UTC 2026-05-07 para test post-fix [skip ci]
**Timestamp commit:** 2026-05-07 18:21:33 -0300
**Branch:** main

### Últimos 10 commits
```
114e7fa chore(ci): cron one-time 21:24 UTC 2026-05-07 para test post-fix [skip ci]
7e57808 chore(auto): update ESTADO_ACTUAL â†’ 6ff852c [skip ci]
6ff852c fix(dashboard): revertir NameError _render_kpi_sistema + regex footer Z
4e2cfc5 chore(auto): update ESTADO_ACTUAL â†’ 781f0ec [skip ci]
781f0ec fix(tooltip): restaurar kpi-sistema con tooltip en _render_kpi_strip
873875e chore(auto): update ESTADO_ACTUAL â†’ 0bfd774 [skip ci]
e14732c docs(protocol): regla ventana segura para pushes criticos + clasificacion de riesgo de colision
7536516 chore(auto): sync dashboard HTML intraday
32b0918 chore(auto): update ESTADO_ACTUAL â†’ aa1b050 [skip ci]
aa1b050 fix(dashboard): generated_at usa UTC real en vez de TZ=AR local
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
