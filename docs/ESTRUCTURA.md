# Proyecto TITAN — Mapa de Archivos
*Actualizado: 2026-04-13 (V13 promovido a scanner activo — sesion 58)*

---

## Decision operativa actual

- La unica linea activa de trabajo es `PythiaxEngine` en GitHub.
- `Claude/` aparece abajo solo como nombre historico del working copy local.
- Toda mejora, auditoria o correccion debe contrastarse contra `GitHub + Neon + GitHub Pages`.
- Solo se inspeccionan proyectos locales hermanos si algo critico se rompio en la migracion cloud.

## Estructura completa

```
Claude/
│
├── CLAUDE.md                    ← instrucciones para Claude Code (DEBE estar en raíz)
│
├── docs/                        ════════ DOCUMENTACIÓN ════════
│   └── ESTRUCTURA.md            ← este archivo — mapa completo del proyecto
│
├── herramientas/                ════════ AUTOMATIZACIÓN Y UTILIDADES ════════
│   ├── actualizar_datos.py      ← actualiza titan.db con datos del mercado (manual)
│   │                              Uso: python herramientas/actualizar_datos.py
│   ├── backfill_historico_db.py ← backfill historico one-off de la DB (6 años o mas)
│   ├── validate_market_data.py  ← valida frescura, cobertura e integridad de titan.db
│   │                              Uso: python herramientas/validate_market_data.py
│   ├── auto_actualizar.py       ← corre a diario, detecta días faltantes cerrados
│   │                              Pipeline: update -> validate -> aprendizaje_v11 -> aprendizaje_v12 -> scanner -> gestor -> resumen_v11 -> resumen_v12 -> auditoria fast
│   ├── aprendizaje_operativo_v11.py ← loop operativo referencia V11: guarda predicciones, outcomes y resumen diario
│   ├── aprendizaje_operativo_v12.py ← loop operativo activo V12: guarda predicciones, outcomes y resumen diario
│   ├── auditoria_integral_claude.py ← auditoría reproducible + centinela stale/full del proyecto
│   ├── gestor_posiciones_v11.py ← gestor de posiciones abiertas + sizing V15 real + reporte diario
│   ├── gestor_posiciones_v10.py ← wrapper legacy hacia V11
│   ├── ledger_experimentos.py   ← consulta/promoción del champion y fronteras candidatas del scanner
│   └── setup_tarea_windows.bat  ← registrar tarea diaria en Task Scheduler (1 vez, Admin)
│
├── SCANNER/                     ════════ SOLO PRODUCTIVOS PROMOVIDOS ════════
│   ├── invertir_v13.py          ← SCANNER ACTIVO (V13 — A + C5 + Signal D + Signal E_HW)
│   │                              4 slots: MeanRev + CrashCap + Liderazgo + RS New High HW
│   │                              Signal A: RSI<25 + SMA<-10% + Score>30 + vol_ratio<=1.5 (regime SEGURO)
│   │                              Signal D: Close>SMA50>SMA200 + ROC20>12% + REL20>7% + RSI 55-75 (cualquier regimen)
│   │                              Signal E_HW: RS_LINE>=RS_52W_MAX + RSI 50-75 + ROC20>8% (HW tickers, hold 15d)
│   │                              Portfolio broad: Sharpe 1.62 | MDD -37.0% | Calmar 35.0 | WF 6/7
│   │                              E_HW individual WR hist: 75% | MC P(WR>50%)=100%
│   │                              Uso: python SCANNER/invertir_v13.py
│   ├── invertir_v12.py          ← referencia inmediata anterior (V12 — A + C5 + Signal D, 3 slots)
│   │                              Portfolio broad: Sharpe 1.36 | MDD -39.9%
│   │                              Uso: python SCANNER/invertir_v12.py
│   ├── invertir_v11.py          ← referencia (V11 — A + C5 cap operativa)
│   │                              Signal A requiere regimen SEGURO — en PELIGRO no genera senales
│   │                              Core base: Sharpe 3.39 | cartera 0.88 | MDD -30.7%
│   ├── invertir_v10.py          ← referencia fuerte (V10 Rebound Capture)
│   ├── invertir_v9.py           ← referencia (V9 path quality)
│   ├── invertir_v8.py           ← referencia (V8 candidato)
│   ├── invertir_v7.py           ← referencia histórica (V7 base A+C)
│   ├── invertir_v6.py           ← referencia (V5 + Williams — Signal B débil)
│   ├── invertir_v5.py           ← referencia (V4 + sin LatAm + hold 7d)
│   ├── invertir_v4.py           ← referencia histórica (Sharpe 14.15)
│
├── scanner_variantes/           ════════ VARIANTES NO PROMOVIDAS Y LEGADOS ════════
│   ├── invertir_v13_1_hold_display.py  ← misma lógica de V13, mejora solo visual
│   ├── invertir_v13_2_auto_hygiene.py  ← variante no promovida: D sin Auto + E_AUTO safe
│   ├── invertir_v13_3_dynamic_special.py ← variante no promovida: sleeves dinámicos sobre V13
│   ├── invertir_v10_rebound_capture.py ← V10 original (legado, importa V9)
│   └── scanner_niveles.py       ← herramienta visual de ranking, no versión canónica
│
├── estrategias_historial/       ════════ HISTORIAL DE VERSIONES ════════
│   ├── invertir_final.py        ← referencia base (Sharpe 4.85, 90 trades)
│   ├── invertir_v3.py           ← deprecado (0 trades, filtros muy estrictos)
│   ├── invertir_v2.py           ← primera optimización (+SMA50 +Vol +Score)
│   ├── invertir.py              ← original (RSI<30 + MACD up)
│   └── invertir_titan.py        ← experimental (V2 + insights ML)
│
├── backtests/                   ════════ VALIDACIÓN ════════
│   ├── investigacion_v23_promotion_gate.py    ← V23: gate formal Signal E_HW (6/7 PASS, PROMUEVE V13)
│   ├── investigacion_v22_4slot_portfolio.py   ← V22: 7 arquitecturas 4-slot (ganador: 2V11+D+E_HW Sharpe 1.62)
│   ├── investigacion_v21_sector_rs_wrhigh.py  ← V21: sector RS + WR alta (E_HW WR 75%, n=64)
│   ├── investigacion_v20_nuevos_ejes.py       ← V20: RS New High, ADX, BB Squeeze, multi-ROC (Signal E descubre sector edge)
│   ├── investigacion_v19_sector_panic.py      ← V19: sector filter C5 + panic mode (aplicado en V12/V13)
│   ├── investigacion_v15_edge_enhancement.py  ← V15: 4 vectores de mejora (VIX, ATR exit, CB, ATR sizing)
│   ├── investigacion_v18_v12_signal_d.py      ← V18: cristaliza V12 y reproduce el edge de V17
│   ├── investigacion_v17_signal_d_audit.py    ← V17: auditoria dura y promotion gates de Signal D (PROMUEVE V12)
│   ├── investigacion_v16_oportunidades_perdidas.py ← V16: refuta aflojar SPY gate y detecta hueco estructural
│   ├── investigacion_v14_prioridad_memoria.py ← V14: prioridad fina por memoria (mejora orden, no filtros)
│   ├── investigacion_v13_memoria_operativa.py ← V13: memoria operativa / gates (no promociona filtro duro)
│   ├── investigacion_v11_exit_frontiers.py    ← V11: exits adaptativos (NO supera V10)
│   ├── investigacion_v11_cap_operativo.py    ← V11: cap score<85 + vol<4 (GANADOR)
│   ├── investigacion_v10_rebound_capture.py  ← V10: exit overlay +6%<=4d (GANADOR)
│   ├── investigacion_v9_path_quality.py      ← V9: corp guard + neg_days (GANADOR)
│   ├── auditoria_latam_v11.py                ← audita si LatAm suma o degrada al core V11
│   ├── auditoria_ml_trading_v22_temporal.py  ← auditoría temporal dura de v22 (rechazada)
│   ├── investigacion_v8_ejes_ortogonales.py  ← V8: 5 ejes ortogonales (RECHAZADA)
│   ├── v7_architecture_decision.py       ← V7: A+C vs A+B+C (A+C gana 5/5)
│   ├── deep_analysis_crash_volume.py    ← V7: C7 trade-by-trade, WF, MC, sensitivity
│   ├── investigacion_v7_fronteras.py    ← 10 nuevas señales, VIX regime, dia semana
│   ├── deep_analysis_williams_squeeze.py ← V6: overlap, union WF, Monte Carlo
│   ├── investigacion_modelo_superador.py ← 12 indicadores, 15 estrategias, WF top 10
│   ├── analisis_v5_candidates.py ← V5: 6 candidatos, walk-forward, combos, veredicto
│   ├── mega_round3.py           ← DEFINITIVO: 9 secciones, walk-forward, monte carlo
│   ├── mega_round2.py           ← Round 2: agregó TITAN ML v2/v4/v5
│   ├── mega_round1.py           ← Round 1: comparación inicial 7 estrategias
│   ├── real_trades.py           ← extractor trades reales (RSI Wilder correcto)
│   ├── backtest_v3_vs_final.py  ← comparación V3 vs Final
│   ├── analisis_rsi_slope_v5.py ← análisis slope RSI (V4 vs V5)
│   ├── walkforward_v5_rsi_slope.py       ← walk-forward V4 vs V5
│   ├── analisis_v5b_slope_alternativo.py ← variante slope < 0 OR >= +3
│   ├── walkforward_v5b_slope_alternativo.py ← WF V5b (veredicto: no pasa 60%)
│   ├── analisis_modelo_agresivo.py       ← 8 variantes agresivas (BESTIA, etc.)
│   ├── analisis_bestia_domada.py         ← nuevos indicadores: Stoch, RelPerf, RSI70
│   ├── analisis_relperf_stoch_fino.py    ← granularidad fina + mini walk-forward
│   ├── analisis_v4_hibrido.py            ← test híbrido V4 + V37/V39 (negativo)
│   ├── analisis_v39_v4_hibrido.py        ← variante análisis híbrido
│   └── resultados/
│       └── round3_output.txt    ← output completo del Round 3
│
├── analisis/                    ════════ ANÁLISIS PROFUNDO ════════
│   ├── analyze_invertir.py      ← por qué funciona (RSI depth, vol, días)
│   ├── analyze_correlation.py   ← overlap entre INVERTIR y V37
│   ├── analyze_why_period.py    ← por qué funciona IS y no OOS
│   ├── dashboard_invertir.py    ← dashboard visual
│   └── preview_v11_visual.py    ← prototipo visual separado del scanner productivo
│
├── aprendizaje_operativo/       ════════ MEMORIA OPERATIVA V11/V12 ════════
│   ├── README.md                ← explica los loops diarios y sus artefactos
│   ├── v11_runs/                ← snapshots JSON diarios del scanner activo
│   ├── v12_runs/                ← snapshots JSON diarios de la referencia inmediata
│   ├── v11_reports/             ← validación, aprendizaje, scanner, gestor, resumen y auditoría del pipeline
│   └── v12_reports/             ← resúmenes y artefactos propios del loop V12
│
├── ml_investigacion/            ════════ MODELOS ML (RESEARCH ONLY) ════════
│   │                              ATENCIÓN: todos perdieron vs INVERTIR simple
│   ├── ml_trading_titan_v2.py        ← Base: 27 features (Sharpe -0.47)
│   ├── ml_trading_TITAN_HYBRID.py    ← + cross-sectional ranks
│   ├── ml_trading_TITAN_HYBRID_v3.py ← igual a HYBRID
│   ├── ml_trading_TITAN_HYBRID_v4.py ← 25 alpha factors (Sharpe -0.51)
│   └── ml_trading_TITAN_v5_QUANTUM.py ← 40 factors (Sharpe -0.65, el PEOR)
│
├── bitacora/                    ════════ HISTORIAL DEL PROYECTO ════════
│   ├── BITACORA.md              ← registro cronológico de sesiones
│   │                              Leer para ponerse al día desde otra PC
│   └── auto_actualizar.log      ← log automático de actualizaciones de DB
│
├── titan_system/                ════════ INFRAESTRUCTURA DE DATOS ════════
│   │  (NO renombrar: es un paquete Python — cambiar nombre rompe imports)
│   ├── data/
│   │   └── titan.db             ← base de datos SQLite (~54.7MB)
│   │                              285 tickers | OHLCV diario | ~6 años
│   │                              Actualizar: python herramientas/actualizar_datos.py
│   ├── core/
│   │   ├── data_loader.py       ← descarga incremental desde Yahoo Finance
│   │   ├── database.py          ← capa de acceso a SQLite
│   │   ├── backtester.py        ← motor de backtesting
│   │   └── tracker.py           ← tracking de predicciones
│   ├── models/
│   │   └── strategies.py        ← 25+ estrategias definidas
│   └── run.py                   ← CLI interactivo del sistema
│
├── .claude/                     ════════ CONFIGURACIÓN CLAUDE CODE ════════
│   ├── settings.local.json      ← permisos de bash para este proyecto
│   └── context-essentials.md   ← reglas críticas post-compactación
│
└── (carpeta hermana)            ════════ RECURSOS EDUCATIVOS ════════
    └── ../LIBROS_Y_RECURSOS/
        └── DICCIONARIOS/        ← diccionarios de trading en HTML/PDF
```

---

## Comandos de uso frecuente

```bash
# Uso diario: buscar oportunidades de hoy
python SCANNER/invertir_v13.py

# Referencia inmediata anterior (V12)
python SCANNER/invertir_v12.py

# Referencia anterior (V11): sin Signal D, no senala en mercados PELIGRO
python SCANNER/invertir_v11.py

# Actualizar base de datos con datos frescos (~2 min)
python herramientas/actualizar_datos.py

# Hacer backfill historico one-off (ej: 6 años)
python herramientas/backfill_historico_db.py --years 6

# Validar frescura e integridad de la DB antes de operar
python herramientas/validate_market_data.py

# Ver champion y rechazos canonicos del scanner
python herramientas/ledger_experimentos.py status

# Correr auditoria integral del proyecto Claude
python herramientas/auditoria_integral_claude.py --mode full

# Correr auditoria centinela rapida (usa el baseline del ultimo full)
python herramientas/auditoria_integral_claude.py --mode fast

# Registrar y evaluar memoria operativa activa (V13)
python herramientas/aprendizaje_operativo_v13.py run

# Registrar y evaluar memoria operativa de referencia inmediata (V12)
python herramientas/aprendizaje_operativo_v12.py run

# Registrar y evaluar memoria operativa de referencia V11
python herramientas/aprendizaje_operativo_v11.py run

# Ver reporte diario del gestor sized V15
python herramientas/gestor_posiciones_v11.py daily-report

# Correr backtest de referencia V11 (base de la evolucion)
python backtests/investigacion_v11_cap_operativo.py

# Auditar promotion gate fuente de Signal D
python backtests/investigacion_v17_signal_d_audit.py

# Reproducir la referencia inmediata V12 ya construida
python backtests/investigacion_v18_v12_signal_d.py

# Ver referencia histórica de arquitectura V7
python backtests/v7_architecture_decision.py
```

---

## Resultados clave (resumen ejecutivo)

| Estrategia | Trades | WR | Sharpe | MDD | Estado |
|-----------|--------|----|--------|-----|--------|
| **V13 / SCANNER ACTIVO (2+1+1 sleeve broad)** | 433 | 61.2% | **1.62** | -37.0% | **ACTIVA** |
| **V12 / referencia inmediata (2+1 sleeve broad)** | 311 | 60.8% | 1.36 | -39.9% | Referencia |
| **V11 / referencia (broad base)** | 468 | 62.4% | 1.60 | -78.6% | Referencia |
| **V11 / referencia (core base)** | 86 | 68.6% | **3.39** | -30.7% | Referencia |
| **V17 / Signal D (promotion gate fuente)** | 311 | 60.8% | **1.36** | -39.9% | Validado |
| V10 / referencia | 550 | 62.2% | 1.57 | -79.1% | Referencia |
| V9 path quality | 550 | 58.0% | 1.14 | -92.8% | Referencia |
| V7 referencia | 632 | 55.9% | 0.72 | -97.8% | Referencia |
| V6 (referencia) | 55 | 54.5% | 1.17 | -21.9% | Referencia |
| V5 (referencia) | ~13 | ~77% | ~13-17 | ~-5% | Referencia |
| V4 (referencia) | 15 | 80% | 14.15 | -7.6% | Referencia |
| Final | 90 | 64% | 4.85 | -33.6% | Referencia |
| V2 | 271 | 61% | 1.95 | -99.3% | Historial |
| ML TITAN v5 | 3114 | 46% | -0.65 | -99% | Descartado |

**Conclusión: 4 filtros simples > 40 features ML** (reforzado por research histórico y auditorías temporales duras)

---

## Dónde está qué

| Quiero... | Ir a... |
|-----------|---------|
| Buscar señales hoy | `SCANNER/invertir_v13.py` |
| Ver la referencia inmediata | `SCANNER/invertir_v12.py` |
| Actualizar datos del mercado (manual) | `python herramientas/actualizar_datos.py` |
| Configurar actualización automática | `herramientas/setup_tarea_windows.bat` (Admin, 1 vez) |
| Ver historial de sesiones | `bitacora/BITACORA.md` |
| Entender por qué funciona | `analisis/analyze_invertir.py` |
| Ver resultados de backtests | `backtests/resultados/round3_output.txt` |
| Correr backtest del scanner activo | `backtests/investigacion_v11_cap_operativo.py` |
| Auditar el promotion gate de Signal D | `backtests/investigacion_v17_signal_d_audit.py` |
| Reproducir la referencia inmediata ya cristalizada | `backtests/investigacion_v18_v12_signal_d.py` |
| Ver datos de la DB | `titan_system/data/titan.db` |
| Log de actualizaciones automáticas | `bitacora/auto_actualizar.log` |
