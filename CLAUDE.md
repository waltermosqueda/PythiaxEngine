# PROYECTO TITAN â€” Instrucciones para Claude
*Leer siempre al inicio de una nueva conversaciÃ³n.*
---

## QuÃ© es este proyecto
Sistema de trading cuantitativo: estrategias rule-based (INVERTIR) validadas contra modelos ML (TITAN).
285 tickers en DB | universo scanner V11: 197 activos | universo extendido de validacion: 209 tickers (V11 + context tickers).

---

## Foco operativo 2026-04-26

- La unica linea activa de trabajo es `PythiaxEngine` en `https://github.com/waltermosqueda/PythiaxEngine`.
- La carpeta local `Claude/` es solo el nombre historico del working copy. No volver a tratarla como un proyecto separado.
- Toda mejora, analisis, correccion, auditoria, prediccion o automatizacion debe validarse contra la arquitectura cloud-first: `GitHub + GitHub Actions + Neon Postgres + GitHub Pages`.
- Solo revisar proyectos locales o dependencias hermanas si una migracion cloud critica quedo rota y bloquea la operacion.

## Reglas OBLIGATORIAS

1. **NUNCA modificar un scanner productivo ya promovido** â€” crear versiÃ³n nueva congelada (`v13 -> v13_1` si el cambio es menor, `v13 -> v14` si el salto es mayor)
2. **Simplicidad > Complejidad** â€” demostrado: 4 reglas Sharpe 14 vs 40 features ML Sharpe -0.65
3. **Todo cambio necesita evidencia** â€” backtest o anÃ¡lisis de trades antes de implementar
4. **RSI: usar Wilder's smoothing** â€” `ewm(com=13, adjust=False)` NO `rolling(14).mean()`
   - rolling da ~892 trades falsos; Wilder da ~333 correctos
   - **Verification gate:** antes de devolver cualquier resultado con RSI, verificar en el cÃ³digo que mÃ©todo se usÃ³
5. **Al terminar cada conversaciÃ³n** â€” actualizar `bitacora/BITACORA.md`
6. **SQLite threading** â€” NUNCA llamar mÃ©todos de DB desde hilos worker. Pre-cargar datos en hilo principal antes de lanzar ThreadPoolExecutor.
7. **Scanners productivos autocontenidos** â€” cualquier scanner dentro de `SCANNER/` NUNCA importa cÃ³digo de otros scanners. Todo el cÃ³digo debe estar inline. Solo importar infraestructura base (titan_system, librerÃ­as estÃ¡ndar).
8. **Naming de `SCANNER/` y variantes** â€” en `SCANNER/` solo viven scanners productivos promovidos y congelados con nombre `invertir_vN.py` o `invertir_vN_M.py`. Variantes no promovidas, copias de trabajo, legados, herramientas auxiliares o experimentos descriptivos van en `scanner_variantes/`.
9. **AuditorÃ­a centinela obligatoria** â€” cualquier cambio ejecutable importante en `SCANNER/`, `herramientas/`, `backtests/`, `titan_system/` o `experimentos/scanner_ledger.json` deja al proyecto en estado stale hasta pasar `python herramientas/auditoria_integral_claude.py --mode full`.
11. **Alineacion de ventana competitiva al hacer backfill** — ANTES de ejecutar cualquier backfill de modelo nuevo, consultar la DB: `SELECT MIN(prediction_date) FROM predictions WHERE model_name LIKE '<familia>%'` y usar ese resultado como `--from-date`. NUNCA usar la fecha tecnica minima (min_rows alcanzado). Todos los modelos de la misma familia deben arrancar desde la misma fecha. Historia extra = ventaja injusta = rankings corruptos. Si ya se guardaron datos erroneos: `DELETE FROM predictions WHERE model_name LIKE '<prefijo>%' AND prediction_date < '<fecha_correcta>'` — verificar count antes/despues y confirmar con el usuario.

10. **ProtecciÃ³n del dashboard C1 Pro** â€” NUNCA sobreescribir `analisis/preview_c1_pro.html` directamente con cambios estructurales sin antes: (a) construir una versiÃ³n de prueba en `analisis/staging/preview_c1_pro_test.html`, (b) mostrarla al usuario y esperar aprobaciÃ³n explÃ­cita. El script `herramientas/_build_c1pro.py` ahora escribe **staging/test por defecto** y solo permite producciÃ³n con `--promote`; al promover, hace backup automÃ¡tico en `analisis/staging/` (retiene Ãºltimos 5). Cambios de datos puros vÃ­a `refrescar_datos_dashboard.py` (inyecciÃ³n entre markers DATA:...) no requieren staging â€” solo los cambios estructurales de HTML/CSS/JS.

---

## Estructura del proyecto

```
Claude/
â”œâ”€â”€ CLAUDE.md                â† este archivo (DEBE estar en raÃ­z: Claude Code lo lee automÃ¡ticamente)
â”‚
â”œâ”€â”€ docs/                    â† documentaciÃ³n del proyecto
â”‚   â””â”€â”€ ESTRUCTURA.md        â† mapa detallado de todos los archivos
â”‚
â”œâ”€â”€ SCANNER/                 â† SOLO PRODUCTIVOS PROMOVIDOS
â”‚   â”œâ”€â”€ invertir_v13.py      â† SCANNER ACTIVO (V13 â€” A + C5 + Signal D + Signal E_HW)
â”‚   â”œâ”€â”€ invertir_v12.py      â† referencia inmediata anterior (V12 â€” A + C5 + Signal D)
â”‚   â”œâ”€â”€ invertir_v11.py      â† referencia anterior fuerte (V11 â€” A + C5 cap operativa)
â”‚   â”œâ”€â”€ invertir_v10.py      â† referencia (V10 Rebound Capture)
â”‚   â”œâ”€â”€ invertir_v9.py       â† referencia (V9 path quality)
â”‚   â”œâ”€â”€ invertir_v8.py       â† referencia (V8 candidato)
â”‚   â”œâ”€â”€ invertir_v7.py       â† referencia histÃ³rica (V7 base A+C)
â”‚   â”œâ”€â”€ invertir_v6.py       â† referencia (V5 OR Williams+Squeeze â€” Signal B dÃ©bil)
â”‚   â”œâ”€â”€ invertir_v5.py       â† referencia (V4 + sin LatAm + hold 7d)
â”‚   â””â”€â”€ invertir_v4.py       â† referencia histÃ³rica
â”‚
â”œâ”€â”€ scanner_variantes/       â† VARIANTES NO PROMOVIDAS / RESEARCH EJECUTABLE
â”‚   â”œâ”€â”€ invertir_v13_1_hold_display.py
â”‚   â”œâ”€â”€ invertir_v13_2_auto_hygiene.py
â”‚   â”œâ”€â”€ invertir_v13_3_dynamic_special.py
â”‚   â””â”€â”€ ...
â”‚
â”œâ”€â”€ herramientas/            â† automatizaciÃ³n y utilidades
â”‚   â”œâ”€â”€ actualizar_datos.py  â† ejecutar para traer datos frescos del mercado
â”‚   â”œâ”€â”€ backfill_historico_db.py â† backfill histÃ³rico one-off (6 aÃ±os o mÃ¡s)
â”‚   â”œâ”€â”€ auto_actualizar.py   â† actualizaciÃ³n automÃ¡tica diaria + pipeline + auditorÃ­a fast final
â”‚   â”œâ”€â”€ auditoria_integral_claude.py â† auditor centinela reproducible (fast/full)
â”‚   â”œâ”€â”€ gestor_posiciones_v11.py â† gestor operativo de posiciones abiertas + sizing V15 real
â”‚   â”œâ”€â”€ gestor_posiciones_v10.py â† wrapper legacy hacia V11
â”‚   â””â”€â”€ setup_tarea_windows.bat â† registrar tarea diaria en Task Scheduler (1 vez, Admin)
â”‚
â”œâ”€â”€ estrategias_historial/   â† versiones anteriores (referencia)
â”œâ”€â”€ backtests/               â† scripts de validaciÃ³n
â”œâ”€â”€ analisis/                â† anÃ¡lisis profundo
â”œâ”€â”€ ml_investigacion/        â† modelos ML (research, NO producciÃ³n)
â”œâ”€â”€ bitacora/                â† historial de trabajo
â”‚   â””â”€â”€ BITACORA.md
â””â”€â”€ titan_system/            â† infraestructura de base de datos del mercado (NO renombrar)
    â””â”€â”€ data/titan.db        â† 285 tickers, OHLCV diario
```

---

## Scanner activo: SCANNER/invertir_v13.py

**Estado vigente 2026-04-13 â€” PROMOVIDO:**
- **Scanner activo real: `SCANNER/invertir_v13.py`** â† este es el que corres cada dia
- Referencia inmediata anterior: `SCANNER/invertir_v12.py`
- Referencia: `SCANNER/invertir_v11.py`

**Por quÃ© V13 es el activo (no V12):**
- V12 tiene 3 slots (A + C5 + D). D llena el slot secundario en cualquier rÃ©gimen.
- V13 agrega un 4to sleeve: Signal E_HW (RS New High en Hardware/IndustrialTech).
  D y E_HW tienen solo 13.1% de overlap â†’ son complementarias, no competitivas.
  E_HW individual: WR 75%, avg +13.75% (validado en V23 con MC P(WR>50%)=100%).
- Promotion gate formal de V13: 6/7 PASS (investigacion_v23_promotion_gate.py).
  4-slot Sharpe 1.62 vs V12 1.36 (+18%). MDD mejora de -39.9% a -37.0%. WF 6/7.

**Arquitectura V13 (scanner activo):**

**SeÃ±al A â€” Mean Reversion (requiere rÃ©gimen SEGURO):**
- RSI(14) < 25 (Wilder's smoothing)
- SMA50 distancia < -10%
- Score compuesto > 30
- Volumen relativo <= 1.5x
- SPY: precio > SMA50 y volatilidad 20d < 1%
- Corporate action guard | Anti-knife 5 dÃ­as | Hold 7d

**SeÃ±al C5 â€” Crash + Path Quality + Rebound (SIN regime):**
- ROC 10d < -15% | Volume 2x-4x | RSI < 35 | NEG_DAYS10 >= 5
- Cap operativa: score < 85 y vol_ratio < 4.0
- **Sector health bloqueado** (V19: WR=33%, avg=-1.84% en portfolio)
- Exit adaptativo: si +6% en dÃ­as 1-4 â†’ cerrar; sino cerrar dÃ­a 7
- **Modo PANIC display**: cuando SPY ROC20 < -10%, muestra alerta (WR historico 88.9%)

**SeÃ±al D â€” Liderazgo / Tendencia (SIN gate de SPY, ortogonal):**
- Close > SMA50 > SMA200 (tendencia estructural)
- ROC20 > 12% (momentum relativo fuerte)
- REL20 > 7% (liderazgo vs SPY en 20d)
- RSI 55-75 (momentum sin sobrecompra)
- Vol ratio 0.8-2.0x (flujo institucional moderado)
- Corporate action guard | Hold 10d

**SeÃ±al E_HW â€” RS New High Hardware (SIN gate de SPY, ortogonal):**
- Tickers: GLW, GRMN, HPQ, MSI, SWKS, TXN, EA, ASTS, RKLB, ERIC, BB
- RS_LINE (Close/SPY) >= maximo de RS_LINE en 52 semanas anteriores (shift(1), sin look-ahead)
- Close > SMA50 > SMA200 (tendencia estructural)
- RSI 50-75 | ROC20 > 8% | Vol ratio 0.8-2.5x
- Corporate action guard | Hold 15d
- WR individual historico: **75%** | avg: +13.75% | WF 6/7

**Universo:** ~197 activos (sin LatAm) | **Fuente:** titan.db | **Slots:** 4 (2 A/C5 + 1 D + 1 E_HW)

**Resultados validados (Abr 2020 â€“ Abr 2026):**

| Arquitectura | Sharpe portfolio | MDD | WR E_HW |
|-------------|-----------------|-----|---------|
| V11 base (referencia) | 0.71 | -37.9% | â€” |
| **V12 (2 slots V11 + 1 slot D) â€” referencia** | 1.36 | -39.9% | â€” |
| **V13 (2 slots V11 + 1 D + 1 E_HW)** | **1.62** | **-37.0%** | **75%** |
| V13 Calmar ratio | 35.0 vs V12 22.5 | | |

**Mejoras incorporadas en V13 (todas heredadas de investigaciones):**
- `V14`: prioridad por memoria C5_D4 (Sharpe cartera broad 0.71 â†’ 0.82)
- `V15`: ATR sizing en gestor (target 4%, factor = target/ATR%, clamp 0.3-2.0x) â€” SIZING_MAX_SLOTS=4
- `V19`: health block en C5 + panic mode display (Sharpe cartera broad +15.7%)
- `V23`: Signal E_HW (RS New High HW) como 4to sleeve â€” 6/7 gates PASS

**Backtests de referencia:**
- Arquitectura V11 cap: `backtests/investigacion_v11_cap_operativo.py`
- Portfolio operativo (3 slots): `backtests/investigacion_v12_portfolio_operativo.py`
- Signal D promotion gate: `backtests/investigacion_v17_signal_d_audit.py`
- Cristalizacion V12: `backtests/investigacion_v18_v12_signal_d.py`
- Sector filter + panic: `backtests/investigacion_v19_sector_panic.py`
- Nuevos ejes ortogonales (RS, ADX, BB): `backtests/investigacion_v20_nuevos_ejes.py`
- Sector RS + WR alta: `backtests/investigacion_v21_sector_rs_wrhigh.py`
- Portfolio 4 slots: `backtests/investigacion_v22_4slot_portfolio.py`
- **Signal E_HW promotion gate: `backtests/investigacion_v23_promotion_gate.py`**

**Gestor vivo:** `herramientas/gestor_posiciones_v11.py` (nombre historico, valido para V13 tambien)
**Reporte diario gestor:** `python herramientas/gestor_posiciones_v11.py daily-report`
**Aprendizaje activo:** `python herramientas/aprendizaje_operativo_v13.py run`

**Ejecutar activo:** `python SCANNER/invertir_v13.py`
**Referencia anterior:** `python SCANNER/invertir_v12.py`
**Referencia clasica:** `python SCANNER/invertir_v11.py`

---

**Nota historica V12** (referencia inmediata anterior a V13):
V12 agrego Signal D como tercer eje ortogonal (liderazgo/tendencia, cualquier rÃ©gimen).
Promotion gate 7/7 PASS. Sharpe 1.36 vs V11 0.77. Fue el champion durante sesiones 57-58.
Su limitacion: 3 slots dejan el portfolio con capacidad ociosa cuando D no tiene setups.

---

## Base de datos del mercado

**Archivo:** `titan_system/data/titan.db` â€” SQLite, ~54.7MB
**Contenido:** 285 tickers, OHLCV diario, ~6 aÃ±os de historia
**Rango actual:** 2020-04-09 -> 2026-04-14 (actualizada)
**Actualizar manual:** `python herramientas/actualizar_datos.py` (~2 min, solo dÃ­as nuevos)
**Backfill historico one-off:** `python herramientas/backfill_historico_db.py --years 6`
**Actualizar auto:** corre todos los dÃ­as a las 19:15 via Task Scheduler
**Pipeline diario real:** `actualizar_datos -> validate_market_data -> aprendizaje_operativo_v11 -> aprendizaje_operativo_v12 -> aprendizaje_operativo_v13 -> scanner activo -> gestor -> resumen_v11 -> resumen_v12 -> resumen_v13 -> auditoria_integral_claude --mode fast`
**Memoria operativa:** base `python herramientas/aprendizaje_operativo_v11.py run` | referencia inmediata `python herramientas/aprendizaje_operativo_v12.py run` | activo `python herramientas/aprendizaje_operativo_v13.py run`
**Regla de promocion:** un nuevo scanner activo no queda completo si no trae su `aprendizaje_operativo_vN.py` y su integracion en pipeline + auditoria.
**Regla centinela:** si hubo cambios ejecutables despuÃ©s del Ãºltimo `--mode full`, el proyecto queda stale hasta rerunear la auditorÃ­a full.
**NO se actualiza sola** sin haber configurado la tarea. Ver `herramientas/setup_tarea_windows.bat`

---

## ConclusiÃ³n principal (confirmada en todos los backtests)

| Estrategia | Features | Sharpe |
|-----------|----------|--------|
| V13 (activa) | A + C5 + D + E_HW â€” portfolio broad | **1.62** |
| V12 (referencia) | A + C5 + D â€” portfolio broad | 1.36 |
| V11 (referencia) | A + C5 (cap operativo) â€” core | 3.39 |
| V11 (referencia) | A + C5 (cap operativo) â€” broad | 1.60 |
| V10 (referencia) | A + C4 (rebound capture) â€” core | 2.91 |
| V10 (referencia) | A + C4 (rebound capture) â€” broad | 1.57 |
| V9 (referencia) | A + C (path quality) â€” core | 1.89 |
| V9 (referencia) | A + C (path quality) â€” broad | 1.14 |
| V7 (referencia) | A + C (crash+vol) | 0.72-1.67 |
| V6 (referencia) | A + B (Williams+Squeeze â€” B dÃ©bil) | 1.17 |
| V5 (referencia) | 4 reglas + universo limpio + hold 7d | ~13-17 |
| V4 (referencia) | 4 reglas | 14.15 |
| INVERTIR Final | 4 reglas | 4.85 |
| V37 NOVA | 7 ML | -0.39 |
| TITAN v4 | 25 ML | -0.51 |
| TITAN v5 QUANTUM | 40 ML | **-0.65** |

**MÃ¡s features ML = peor performance** (confirmado por el research histÃ³rico y por auditorÃ­as temporales posteriores)

---

## Setup del usuario

- Sincroniza via **Google Drive**
- Path en otra PC: `G:\Otros ordenadores\Mi New PC\Inversiones\Claude\`
- Usa Claude Code desktop app en Windows
- Al abrir desde otra PC: leer `bitacora/BITACORA.md` para ver Ãºltimo estado

---

## CÃ³mo ponerse al dÃ­a desde otra PC

1. Verificar que Google Drive sincronizÃ³
2. Leer este archivo (CLAUDE.md)
3. Leer `bitacora/BITACORA.md` â€” Ãºltimas 2 sesiones si existe una frontera nueva
4. Leer `docs/ESTRUCTURA.md` â€” mapa completo de archivos
5. Confirmar:
   - scanner activo: `SCANNER/invertir_v13.py` â† este es el que se corre cada dia
   - referencia anterior: `SCANNER/invertir_v12.py`
   - promotion gate fuente: `backtests/investigacion_v23_promotion_gate.py`

---

## Instrucciones de CompactaciÃ³n

Cuando el contexto se compacte automÃ¡ticamente, preservar en el resumen:
- Todos los archivos modificados con sus rutas exactas
- El estado de la tarea actual y los pasos pendientes
- Ãšltimos resultados de backtest o scanner (nÃºmeros concretos)
- Cualquier error activo o en investigaciÃ³n con el stack trace
- ParÃ¡metros exactos usados en la Ãºltima ejecuciÃ³n

DespuÃ©s de cada compactaciÃ³n, las reglas crÃ­ticas se reinyectan automÃ¡ticamente desde `.claude/context-essentials.md`.

---

## Errores conocidos del pasado (no repetir)

| Error | Causa | SoluciÃ³n |
|-------|-------|----------|
| 892 trades falsos en backtest | RSI con `rolling(14).mean()` | Usar `ewm(com=13, adjust=False)` |
| V3 con 0 trades | CombinaciÃ³n de 7 filtros muy estrictos | V4 usa solo 3 filtros confirmados |
| SQLite threading error en update DB | `get_latest_date()` llamado desde workers | Pre-cargar fechas con `get_all_latest_dates()` en hilo principal |

<!-- Pendientes: ver bitacora/BITACORA.md â€” secciÃ³n "Pendientes" de la Ãºltima sesiÃ³n -->

---

## Protocolos de Razonamiento Avanzado

*TÃ©cnicas seleccionadas por evidencia empÃ­rica. Integradas al workflow, no opcionales.*

### Protocolo 1: Razonamiento Paso a Paso (CoT obligatorio)

**CuÃ¡ndo:** Cualquier anÃ¡lisis complejo, evaluaciÃ³n de estrategia, o diagnÃ³stico de error.
**Evidencia:** +6% accuracy promedio vs respuestas directas (meta-anÃ¡lisis acadÃ©mico).

**Regla:** NUNCA dar conclusiones directas en anÃ¡lisis complejos. Siempre:
1. Enumerar los datos disponibles
2. Razonar sobre cada dato por separado
3. Identificar contradicciones o gaps
4. ENTONCES dar la conclusiÃ³n

---

### Protocolo 2: Tres Fases (Analista â†’ CrÃ­tico â†’ Director)

**CuÃ¡ndo:** Evaluar cualquier cambio al scanner, nueva estrategia, o modificaciÃ³n de filtros.
**Evidencia:** 80x mejor especificidad y 140x mejor correcciÃ³n vs anÃ¡lisis de una sola pasada (348 trials controlados, multi-agente research 2025).

**Regla:** Toda evaluaciÃ³n de cambio al sistema sigue este flujo:

```
FASE 1 â€” ANALISTA:
  - Â¿CuÃ¡l es la hipÃ³tesis?
  - Â¿QuÃ© mejora espera en WR, Sharpe, o MDD?
  - Â¿QuÃ© datos la soportan?

FASE 2 â€” CRÃTICO (cambiar de mentalidad, buscar fallas):
  - Â¿Puede ser overfitting?
  - Â¿Se sostiene en out-of-sample?
  - Â¿Agrega complejidad innecesaria?
  - Recordar: 4 reglas Sharpe 14 vs 40 features ML Sharpe -0.65

FASE 3 â€” DIRECTOR (veredicto final):
  - Â¿Proceder con backtest? SI/NO
  - Si SI: quÃ© mÃ©tricas monitorear y quÃ© umbrales mÃ­nimos
  - Si NO: por quÃ©, y quÃ© alternativa explorar
```

---

### Protocolo 3: Pre-mortem (antes de implementar)

**CuÃ¡ndo:** Antes de implementar cualquier cambio que pase la Fase 3.
**Evidencia:** TÃ©cnica de Kahneman â€” reduce sesgo de confirmaciÃ³n, el error #1 en sistemas de trading. El proyecto TITAN lo sufriÃ³: 5 modelos ML implementados sin pre-mortem, todos perdieron.

**Regla:** Antes de escribir cÃ³digo para un cambio aprobado:
```
"Imaginar que implementamos este cambio y falla completamente en 6 meses:
1. Â¿QuÃ© saliÃ³ mal?
2. Â¿QuÃ© seÃ±ales ignoramos?
3. Â¿QuÃ© deberÃ­amos haber hecho diferente?
â†’ Si las respuestas revelan riesgos no mitigados, volver a Fase 2."
```

---

### Protocolo 4: Checklist Anti-Overfitting

**CuÃ¡ndo:** DespuÃ©s de cada backtest nuevo.
**Evidencia:** Historia propia del proyecto â€” todos los modelos ML sobreajustaron. Este checklist previene repetir el error.

**Regla:** Todo backtest se audita con este checklist antes de aceptar resultados:
```
[ ] LOOK-AHEAD BIAS:    Â¿Se usaron datos futuros en algÃºn paso?
[ ] SURVIVORSHIP BIAS:  Â¿Se excluyeron tickers deslistados?
[ ] PERÃODO:            Â¿Al menos 18 meses de datos?
[ ] OUT-OF-SAMPLE:      Â¿Hay validaciÃ³n fuera de muestra?
[ ] WALK-FORWARD:       Â¿Se probÃ³ con ventanas mÃ³viles?
[ ] COMPLEJIDAD:        Â¿Menos de 5 filtros? (mÃ¡s = riesgo overfitting)
[ ] TRADES MÃNIMOS:     Â¿Al menos 15 trades para significancia?
[ ] COSTOS:             Â¿Se incluyeron comisiones y slippage?

Resultado: â‰¥6 PASS = aceptar | 4-5 PASS = revisar | <4 = rechazar
```

---

### Protocolo 5: CalibraciÃ³n de Confianza

**CuÃ¡ndo:** Cualquier predicciÃ³n, recomendaciÃ³n, o evaluaciÃ³n de seÃ±al.
**Evidencia:** Fuerza auto-evaluaciÃ³n del modelo, reduce sobreconfianza. En decisiones financieras, la sobreconfianza es el sesgo mÃ¡s costoso.

**Regla:** Toda recomendaciÃ³n incluye nivel de confianza:
```
ALTA (>80%):   Datos sÃ³lidos, mÃºltiples indicadores alineados, evidencia histÃ³rica
MEDIA (50-80%): Algunos datos soportan, pero hay incertidumbre o datos faltantes
BAJA (<50%):   Datos insuficientes o seÃ±ales contradictorias
â†’ Si confianza es BAJA: marcar "REQUIERE MÃS DATOS" y especificar quÃ© falta
```

---

### Protocolo 6: Convergencia Multi-Perspectiva (Self-Consistency)

**CuÃ¡ndo:** Decisiones crÃ­ticas â€” cambiar el scanner activo, agregar/quitar filtros, modificar umbrales.
**Evidencia:** El voto mayoritario entre mÃºltiples razonamientos independientes converge en la respuesta correcta con mayor frecuencia que un solo razonamiento.

**Regla:** Para decisiones crÃ­ticas, analizar desde 3 Ã¡ngulos independientes:
```
Ãngulo 1 â€” TÃ©cnico: Â¿QuÃ© dicen los indicadores y los nÃºmeros del backtest?
Ãngulo 2 â€” Riesgo:  Â¿QuÃ© pasa en el peor escenario? Â¿MDD aceptable?
Ãngulo 3 â€” Simplicidad: Â¿Esto complica el sistema? Â¿Vale la complejidad aÃ±adida?

â†’ Si 2/3 coinciden = proceder
â†’ Si 3/3 divergen = no proceder, investigar mÃ¡s
```

---

### Protocolo 7: Verification Gates (expandido)

**CuÃ¡ndo:** Antes de devolver CUALQUIER resultado que involucre cÃ¡lculos o datos.
**Evidencia:** El RSI verification gate existente previno el error de 892 trades falsos. Expandir el patrÃ³n a todos los outputs crÃ­ticos.

**Gates obligatorios:**
```
GATE RSI:     Â¿Se usÃ³ Wilder's smoothing? ewm(com=13, adjust=False) â€” NO rolling
GATE DATOS:   Â¿Los datos estÃ¡n actualizados? Verificar rango de fechas en DB
GATE LÃ“GICA:  Â¿Los filtros del scanner son los de V11? A = RSI<25, SMA<-10%, Score>30, vol<=1.5 | C5 = ROC10d<-15%, Vol 2x-4x, RSI<35, neg_days>=5, score<85
GATE REGIME:  Â¿Se verificÃ³ el estado de SPY antes de generar seÃ±ales?
GATE THREADS: Â¿Se pre-cargaron datos antes de lanzar ThreadPoolExecutor?

â†’ Si cualquier gate falla: DETENER y corregir antes de continuar
```

---

### CuÃ¡ndo aplicar cada protocolo (resumen)

| SituaciÃ³n | Protocolos a aplicar |
|-----------|---------------------|
| AnÃ¡lisis de seÃ±ales/datos | 1 (CoT) + 5 (Confianza) + 7 (Gates) |
| Evaluar cambio al scanner | 1 + 2 (3-Fases) + 3 (Pre-mortem) + 6 (Convergencia) |
| Correr/revisar backtest | 1 + 4 (Anti-Overfitting) + 5 |
| DecisiÃ³n crÃ­tica (cambiar estrategia activa) | TODOS (1-7) |
| Bug fix o error de cÃ³digo | 1 + 7 (Gates) |
| AnÃ¡lisis exploratorio | 1 + 5 |

