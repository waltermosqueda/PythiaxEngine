# PROYECTO TITAN — Instrucciones para Claude
*Leer siempre al inicio de una nueva conversación.*
---

## Qué es este proyecto
Sistema de trading cuantitativo: estrategias rule-based (INVERTIR) validadas contra modelos ML (TITAN).
285 tickers en DB | universo scanner V11: 197 activos | universo extendido de validacion: 209 tickers (V11 + context tickers).

---

## Foco operativo 2026-04-26

- La unica linea activa de trabajo es `PythiaxEngine` en `https://github.com/waltermosqueda/PythiaxEngine`.
- La carpeta local `Claude/` es solo el nombre historico del working copy. No volver a tratarla como un proyecto separado.
- Toda mejora, analisis, correccion, auditoria, prediccion o automatizacion debe validarse contra la arquitectura cloud-first: `GitHub + GitHub Actions + Neon Postgres + GitHub Pages`.
- Solo revisar proyectos locales o dependencias hermanas si una migracion cloud critica quedo rota y bloquea la operacion.

## Reglas OBLIGATORIAS

1. **NUNCA modificar un scanner productivo ya promovido** — crear versión nueva congelada (`v13 -> v13_1` si el cambio es menor, `v13 -> v14` si el salto es mayor)
2. **Simplicidad > Complejidad** — demostrado: 4 reglas Sharpe 14 vs 40 features ML Sharpe -0.65
3. **Todo cambio necesita evidencia** — backtest o análisis de trades antes de implementar
4. **RSI: usar Wilder's smoothing** — `ewm(com=13, adjust=False)` NO `rolling(14).mean()`
   - rolling da ~892 trades falsos; Wilder da ~333 correctos
   - **Verification gate:** antes de devolver cualquier resultado con RSI, verificar en el código que método se usó
5. **Al terminar cada conversación** — actualizar `bitacora/BITACORA.md`
6. **SQLite threading** — NUNCA llamar métodos de DB desde hilos worker. Pre-cargar datos en hilo principal antes de lanzar ThreadPoolExecutor.
7. **Scanners productivos autocontenidos** — cualquier scanner dentro de `SCANNER/` NUNCA importa código de otros scanners. Todo el código debe estar inline. Solo importar infraestructura base (titan_system, librerías estándar).
8. **Naming de `SCANNER/` y variantes** — en `SCANNER/` solo viven scanners productivos promovidos y congelados con nombre `invertir_vN.py` o `invertir_vN_M.py`. Variantes no promovidas, copias de trabajo, legados, herramientas auxiliares o experimentos descriptivos van en `scanner_variantes/`.
9. **Auditoría centinela obligatoria** — cualquier cambio ejecutable importante en `SCANNER/`, `herramientas/`, `backtests/`, `titan_system/` o `experimentos/scanner_ledger.json` deja al proyecto en estado stale hasta pasar `python herramientas/auditoria_integral_claude.py --mode full`.
10. **Protección del dashboard C1 Pro** — NUNCA sobreescribir `analisis/preview_c1_pro.html` directamente con cambios estructurales sin antes: (a) construir una versión de prueba en `analisis/staging/preview_c1_pro_test.html`, (b) mostrarla al usuario y esperar aprobación explícita. El script `herramientas/_build_c1pro.py` ahora escribe **staging/test por defecto** y solo permite producción con `--promote`; al promover, hace backup automático en `analisis/staging/` (retiene últimos 5). Cambios de datos puros vía `refrescar_datos_dashboard.py` (inyección entre markers DATA:...) no requieren staging — solo los cambios estructurales de HTML/CSS/JS.

---

## Estructura del proyecto

```
Claude/
├── CLAUDE.md                ← este archivo (DEBE estar en raíz: Claude Code lo lee automáticamente)
│
├── docs/                    ← documentación del proyecto
│   └── ESTRUCTURA.md        ← mapa detallado de todos los archivos
│
├── SCANNER/                 ← SOLO PRODUCTIVOS PROMOVIDOS
│   ├── invertir_v13.py      ← SCANNER ACTIVO (V13 — A + C5 + Signal D + Signal E_HW)
│   ├── invertir_v12.py      ← referencia inmediata anterior (V12 — A + C5 + Signal D)
│   ├── invertir_v11.py      ← referencia anterior fuerte (V11 — A + C5 cap operativa)
│   ├── invertir_v10.py      ← referencia (V10 Rebound Capture)
│   ├── invertir_v9.py       ← referencia (V9 path quality)
│   ├── invertir_v8.py       ← referencia (V8 candidato)
│   ├── invertir_v7.py       ← referencia histórica (V7 base A+C)
│   ├── invertir_v6.py       ← referencia (V5 OR Williams+Squeeze — Signal B débil)
│   ├── invertir_v5.py       ← referencia (V4 + sin LatAm + hold 7d)
│   └── invertir_v4.py       ← referencia histórica
│
├── scanner_variantes/       ← VARIANTES NO PROMOVIDAS / RESEARCH EJECUTABLE
│   ├── invertir_v13_1_hold_display.py
│   ├── invertir_v13_2_auto_hygiene.py
│   ├── invertir_v13_3_dynamic_special.py
│   └── ...
│
├── herramientas/            ← automatización y utilidades
│   ├── actualizar_datos.py  ← ejecutar para traer datos frescos del mercado
│   ├── backfill_historico_db.py ← backfill histórico one-off (6 años o más)
│   ├── auto_actualizar.py   ← actualización automática diaria + pipeline + auditoría fast final
│   ├── auditoria_integral_claude.py ← auditor centinela reproducible (fast/full)
│   ├── gestor_posiciones_v11.py ← gestor operativo de posiciones abiertas + sizing V15 real
│   ├── gestor_posiciones_v10.py ← wrapper legacy hacia V11
│   └── setup_tarea_windows.bat ← registrar tarea diaria en Task Scheduler (1 vez, Admin)
│
├── estrategias_historial/   ← versiones anteriores (referencia)
├── backtests/               ← scripts de validación
├── analisis/                ← análisis profundo
├── ml_investigacion/        ← modelos ML (research, NO producción)
├── bitacora/                ← historial de trabajo
│   └── BITACORA.md
└── titan_system/            ← infraestructura de base de datos del mercado (NO renombrar)
    └── data/titan.db        ← 285 tickers, OHLCV diario
```

---

## Scanner activo: SCANNER/invertir_v13.py

**Estado vigente 2026-04-13 — PROMOVIDO:**
- **Scanner activo real: `SCANNER/invertir_v13.py`** ← este es el que corres cada dia
- Referencia inmediata anterior: `SCANNER/invertir_v12.py`
- Referencia: `SCANNER/invertir_v11.py`

**Por qué V13 es el activo (no V12):**
- V12 tiene 3 slots (A + C5 + D). D llena el slot secundario en cualquier régimen.
- V13 agrega un 4to sleeve: Signal E_HW (RS New High en Hardware/IndustrialTech).
  D y E_HW tienen solo 13.1% de overlap → son complementarias, no competitivas.
  E_HW individual: WR 75%, avg +13.75% (validado en V23 con MC P(WR>50%)=100%).
- Promotion gate formal de V13: 6/7 PASS (investigacion_v23_promotion_gate.py).
  4-slot Sharpe 1.62 vs V12 1.36 (+18%). MDD mejora de -39.9% a -37.0%. WF 6/7.

**Arquitectura V13 (scanner activo):**

**Señal A — Mean Reversion (requiere régimen SEGURO):**
- RSI(14) < 25 (Wilder's smoothing)
- SMA50 distancia < -10%
- Score compuesto > 30
- Volumen relativo <= 1.5x
- SPY: precio > SMA50 y volatilidad 20d < 1%
- Corporate action guard | Anti-knife 5 días | Hold 7d

**Señal C5 — Crash + Path Quality + Rebound (SIN regime):**
- ROC 10d < -15% | Volume 2x-4x | RSI < 35 | NEG_DAYS10 >= 5
- Cap operativa: score < 85 y vol_ratio < 4.0
- **Sector health bloqueado** (V19: WR=33%, avg=-1.84% en portfolio)
- Exit adaptativo: si +6% en días 1-4 → cerrar; sino cerrar día 7
- **Modo PANIC display**: cuando SPY ROC20 < -10%, muestra alerta (WR historico 88.9%)

**Señal D — Liderazgo / Tendencia (SIN gate de SPY, ortogonal):**
- Close > SMA50 > SMA200 (tendencia estructural)
- ROC20 > 12% (momentum relativo fuerte)
- REL20 > 7% (liderazgo vs SPY en 20d)
- RSI 55-75 (momentum sin sobrecompra)
- Vol ratio 0.8-2.0x (flujo institucional moderado)
- Corporate action guard | Hold 10d

**Señal E_HW — RS New High Hardware (SIN gate de SPY, ortogonal):**
- Tickers: GLW, GRMN, HPQ, MSI, SWKS, TXN, EA, ASTS, RKLB, ERIC, BB
- RS_LINE (Close/SPY) >= maximo de RS_LINE en 52 semanas anteriores (shift(1), sin look-ahead)
- Close > SMA50 > SMA200 (tendencia estructural)
- RSI 50-75 | ROC20 > 8% | Vol ratio 0.8-2.5x
- Corporate action guard | Hold 15d
- WR individual historico: **75%** | avg: +13.75% | WF 6/7

**Universo:** ~197 activos (sin LatAm) | **Fuente:** titan.db | **Slots:** 4 (2 A/C5 + 1 D + 1 E_HW)

**Resultados validados (Abr 2020 – Abr 2026):**

| Arquitectura | Sharpe portfolio | MDD | WR E_HW |
|-------------|-----------------|-----|---------|
| V11 base (referencia) | 0.71 | -37.9% | — |
| **V12 (2 slots V11 + 1 slot D) — referencia** | 1.36 | -39.9% | — |
| **V13 (2 slots V11 + 1 D + 1 E_HW)** | **1.62** | **-37.0%** | **75%** |
| V13 Calmar ratio | 35.0 vs V12 22.5 | | |

**Mejoras incorporadas en V13 (todas heredadas de investigaciones):**
- `V14`: prioridad por memoria C5_D4 (Sharpe cartera broad 0.71 → 0.82)
- `V15`: ATR sizing en gestor (target 4%, factor = target/ATR%, clamp 0.3-2.0x) — SIZING_MAX_SLOTS=4
- `V19`: health block en C5 + panic mode display (Sharpe cartera broad +15.7%)
- `V23`: Signal E_HW (RS New High HW) como 4to sleeve — 6/7 gates PASS

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
V12 agrego Signal D como tercer eje ortogonal (liderazgo/tendencia, cualquier régimen).
Promotion gate 7/7 PASS. Sharpe 1.36 vs V11 0.77. Fue el champion durante sesiones 57-58.
Su limitacion: 3 slots dejan el portfolio con capacidad ociosa cuando D no tiene setups.

---

## Base de datos del mercado

**Archivo:** `titan_system/data/titan.db` — SQLite, ~54.7MB
**Contenido:** 285 tickers, OHLCV diario, ~6 años de historia
**Rango actual:** 2020-04-09 -> 2026-04-14 (actualizada)
**Actualizar manual:** `python herramientas/actualizar_datos.py` (~2 min, solo días nuevos)
**Backfill historico one-off:** `python herramientas/backfill_historico_db.py --years 6`
**Actualizar auto:** corre todos los días a las 19:15 via Task Scheduler
**Pipeline diario real:** `actualizar_datos -> validate_market_data -> aprendizaje_operativo_v11 -> aprendizaje_operativo_v12 -> aprendizaje_operativo_v13 -> scanner activo -> gestor -> resumen_v11 -> resumen_v12 -> resumen_v13 -> auditoria_integral_claude --mode fast`
**Memoria operativa:** base `python herramientas/aprendizaje_operativo_v11.py run` | referencia inmediata `python herramientas/aprendizaje_operativo_v12.py run` | activo `python herramientas/aprendizaje_operativo_v13.py run`
**Regla de promocion:** un nuevo scanner activo no queda completo si no trae su `aprendizaje_operativo_vN.py` y su integracion en pipeline + auditoria.
**Regla centinela:** si hubo cambios ejecutables después del último `--mode full`, el proyecto queda stale hasta rerunear la auditoría full.
**NO se actualiza sola** sin haber configurado la tarea. Ver `herramientas/setup_tarea_windows.bat`

---

## Conclusión principal (confirmada en todos los backtests)

| Estrategia | Features | Sharpe |
|-----------|----------|--------|
| V13 (activa) | A + C5 + D + E_HW — portfolio broad | **1.62** |
| V12 (referencia) | A + C5 + D — portfolio broad | 1.36 |
| V11 (referencia) | A + C5 (cap operativo) — core | 3.39 |
| V11 (referencia) | A + C5 (cap operativo) — broad | 1.60 |
| V10 (referencia) | A + C4 (rebound capture) — core | 2.91 |
| V10 (referencia) | A + C4 (rebound capture) — broad | 1.57 |
| V9 (referencia) | A + C (path quality) — core | 1.89 |
| V9 (referencia) | A + C (path quality) — broad | 1.14 |
| V7 (referencia) | A + C (crash+vol) | 0.72-1.67 |
| V6 (referencia) | A + B (Williams+Squeeze — B débil) | 1.17 |
| V5 (referencia) | 4 reglas + universo limpio + hold 7d | ~13-17 |
| V4 (referencia) | 4 reglas | 14.15 |
| INVERTIR Final | 4 reglas | 4.85 |
| V37 NOVA | 7 ML | -0.39 |
| TITAN v4 | 25 ML | -0.51 |
| TITAN v5 QUANTUM | 40 ML | **-0.65** |

**Más features ML = peor performance** (confirmado por el research histórico y por auditorías temporales posteriores)

---

## Setup del usuario

- Sincroniza via **Google Drive**
- Path en otra PC: `G:\Otros ordenadores\Mi New PC\Inversiones\Claude\`
- Usa Claude Code desktop app en Windows
- Al abrir desde otra PC: leer `bitacora/BITACORA.md` para ver último estado

---

## Cómo ponerse al día desde otra PC

1. Verificar que Google Drive sincronizó
2. Leer este archivo (CLAUDE.md)
3. Leer `bitacora/BITACORA.md` — últimas 2 sesiones si existe una frontera nueva
4. Leer `docs/ESTRUCTURA.md` — mapa completo de archivos
5. Confirmar:
   - scanner activo: `SCANNER/invertir_v13.py` ← este es el que se corre cada dia
   - referencia anterior: `SCANNER/invertir_v12.py`
   - promotion gate fuente: `backtests/investigacion_v23_promotion_gate.py`

---

## Instrucciones de Compactación

Cuando el contexto se compacte automáticamente, preservar en el resumen:
- Todos los archivos modificados con sus rutas exactas
- El estado de la tarea actual y los pasos pendientes
- Últimos resultados de backtest o scanner (números concretos)
- Cualquier error activo o en investigación con el stack trace
- Parámetros exactos usados en la última ejecución

Después de cada compactación, las reglas críticas se reinyectan automáticamente desde `.claude/context-essentials.md`.

---

## Errores conocidos del pasado (no repetir)

| Error | Causa | Solución |
|-------|-------|----------|
| 892 trades falsos en backtest | RSI con `rolling(14).mean()` | Usar `ewm(com=13, adjust=False)` |
| V3 con 0 trades | Combinación de 7 filtros muy estrictos | V4 usa solo 3 filtros confirmados |
| SQLite threading error en update DB | `get_latest_date()` llamado desde workers | Pre-cargar fechas con `get_all_latest_dates()` en hilo principal |

<!-- Pendientes: ver bitacora/BITACORA.md — sección "Pendientes" de la última sesión -->

---

## Protocolos de Razonamiento Avanzado

*Técnicas seleccionadas por evidencia empírica. Integradas al workflow, no opcionales.*

### Protocolo 1: Razonamiento Paso a Paso (CoT obligatorio)

**Cuándo:** Cualquier análisis complejo, evaluación de estrategia, o diagnóstico de error.
**Evidencia:** +6% accuracy promedio vs respuestas directas (meta-análisis académico).

**Regla:** NUNCA dar conclusiones directas en análisis complejos. Siempre:
1. Enumerar los datos disponibles
2. Razonar sobre cada dato por separado
3. Identificar contradicciones o gaps
4. ENTONCES dar la conclusión

---

### Protocolo 2: Tres Fases (Analista → Crítico → Director)

**Cuándo:** Evaluar cualquier cambio al scanner, nueva estrategia, o modificación de filtros.
**Evidencia:** 80x mejor especificidad y 140x mejor corrección vs análisis de una sola pasada (348 trials controlados, multi-agente research 2025).

**Regla:** Toda evaluación de cambio al sistema sigue este flujo:

```
FASE 1 — ANALISTA:
  - ¿Cuál es la hipótesis?
  - ¿Qué mejora espera en WR, Sharpe, o MDD?
  - ¿Qué datos la soportan?

FASE 2 — CRÍTICO (cambiar de mentalidad, buscar fallas):
  - ¿Puede ser overfitting?
  - ¿Se sostiene en out-of-sample?
  - ¿Agrega complejidad innecesaria?
  - Recordar: 4 reglas Sharpe 14 vs 40 features ML Sharpe -0.65

FASE 3 — DIRECTOR (veredicto final):
  - ¿Proceder con backtest? SI/NO
  - Si SI: qué métricas monitorear y qué umbrales mínimos
  - Si NO: por qué, y qué alternativa explorar
```

---

### Protocolo 3: Pre-mortem (antes de implementar)

**Cuándo:** Antes de implementar cualquier cambio que pase la Fase 3.
**Evidencia:** Técnica de Kahneman — reduce sesgo de confirmación, el error #1 en sistemas de trading. El proyecto TITAN lo sufrió: 5 modelos ML implementados sin pre-mortem, todos perdieron.

**Regla:** Antes de escribir código para un cambio aprobado:
```
"Imaginar que implementamos este cambio y falla completamente en 6 meses:
1. ¿Qué salió mal?
2. ¿Qué señales ignoramos?
3. ¿Qué deberíamos haber hecho diferente?
→ Si las respuestas revelan riesgos no mitigados, volver a Fase 2."
```

---

### Protocolo 4: Checklist Anti-Overfitting

**Cuándo:** Después de cada backtest nuevo.
**Evidencia:** Historia propia del proyecto — todos los modelos ML sobreajustaron. Este checklist previene repetir el error.

**Regla:** Todo backtest se audita con este checklist antes de aceptar resultados:
```
[ ] LOOK-AHEAD BIAS:    ¿Se usaron datos futuros en algún paso?
[ ] SURVIVORSHIP BIAS:  ¿Se excluyeron tickers deslistados?
[ ] PERÍODO:            ¿Al menos 18 meses de datos?
[ ] OUT-OF-SAMPLE:      ¿Hay validación fuera de muestra?
[ ] WALK-FORWARD:       ¿Se probó con ventanas móviles?
[ ] COMPLEJIDAD:        ¿Menos de 5 filtros? (más = riesgo overfitting)
[ ] TRADES MÍNIMOS:     ¿Al menos 15 trades para significancia?
[ ] COSTOS:             ¿Se incluyeron comisiones y slippage?

Resultado: ≥6 PASS = aceptar | 4-5 PASS = revisar | <4 = rechazar
```

---

### Protocolo 5: Calibración de Confianza

**Cuándo:** Cualquier predicción, recomendación, o evaluación de señal.
**Evidencia:** Fuerza auto-evaluación del modelo, reduce sobreconfianza. En decisiones financieras, la sobreconfianza es el sesgo más costoso.

**Regla:** Toda recomendación incluye nivel de confianza:
```
ALTA (>80%):   Datos sólidos, múltiples indicadores alineados, evidencia histórica
MEDIA (50-80%): Algunos datos soportan, pero hay incertidumbre o datos faltantes
BAJA (<50%):   Datos insuficientes o señales contradictorias
→ Si confianza es BAJA: marcar "REQUIERE MÁS DATOS" y especificar qué falta
```

---

### Protocolo 6: Convergencia Multi-Perspectiva (Self-Consistency)

**Cuándo:** Decisiones críticas — cambiar el scanner activo, agregar/quitar filtros, modificar umbrales.
**Evidencia:** El voto mayoritario entre múltiples razonamientos independientes converge en la respuesta correcta con mayor frecuencia que un solo razonamiento.

**Regla:** Para decisiones críticas, analizar desde 3 ángulos independientes:
```
Ángulo 1 — Técnico: ¿Qué dicen los indicadores y los números del backtest?
Ángulo 2 — Riesgo:  ¿Qué pasa en el peor escenario? ¿MDD aceptable?
Ángulo 3 — Simplicidad: ¿Esto complica el sistema? ¿Vale la complejidad añadida?

→ Si 2/3 coinciden = proceder
→ Si 3/3 divergen = no proceder, investigar más
```

---

### Protocolo 7: Verification Gates (expandido)

**Cuándo:** Antes de devolver CUALQUIER resultado que involucre cálculos o datos.
**Evidencia:** El RSI verification gate existente previno el error de 892 trades falsos. Expandir el patrón a todos los outputs críticos.

**Gates obligatorios:**
```
GATE RSI:     ¿Se usó Wilder's smoothing? ewm(com=13, adjust=False) — NO rolling
GATE DATOS:   ¿Los datos están actualizados? Verificar rango de fechas en DB
GATE LÓGICA:  ¿Los filtros del scanner son los de V11? A = RSI<25, SMA<-10%, Score>30, vol<=1.5 | C5 = ROC10d<-15%, Vol 2x-4x, RSI<35, neg_days>=5, score<85
GATE REGIME:  ¿Se verificó el estado de SPY antes de generar señales?
GATE THREADS: ¿Se pre-cargaron datos antes de lanzar ThreadPoolExecutor?

→ Si cualquier gate falla: DETENER y corregir antes de continuar
```

---

### Cuándo aplicar cada protocolo (resumen)

| Situación | Protocolos a aplicar |
|-----------|---------------------|
| Análisis de señales/datos | 1 (CoT) + 5 (Confianza) + 7 (Gates) |
| Evaluar cambio al scanner | 1 + 2 (3-Fases) + 3 (Pre-mortem) + 6 (Convergencia) |
| Correr/revisar backtest | 1 + 4 (Anti-Overfitting) + 5 |
| Decisión crítica (cambiar estrategia activa) | TODOS (1-7) |
| Bug fix o error de código | 1 + 7 (Gates) |
| Análisis exploratorio | 1 + 5 |
