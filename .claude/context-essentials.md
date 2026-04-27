# TITAN - Reglas criticas (post-compactacion)
*Este archivo se inyecta automaticamente despues de cada compactacion.*

## Las 10 reglas que NUNCA pueden olvidarse

0. **Foco cloud-first obligatorio** - La unica linea activa de trabajo es `PythiaxEngine` sobre `GitHub + Neon + GitHub Pages`. La carpeta `Claude/` es solo el nombre historico del working copy y no debe retomarse como proyecto separado. Solo revisar dependencias locales o proyectos hermanos si hay una rotura critica de migracion.

1. **RSI = Wilder's smoothing SIEMPRE** - `ewm(com=13, adjust=False)` - `rolling(14).mean()` produce muchas senales falsas. Antes de devolver cualquier resultado con RSI: verificar que metodo se uso.

2. **NUNCA modificar un scanner productivo ya promovido** - crear version nueva congelada (`v13 -> v13_1` si el cambio es menor, `v13 -> v14` si el salto es mayor).

3. **Todo cambio = backtest primero** - no implementar nada sin evidencia cuantitativa.

4. **Scanner activo: `SCANNER/invertir_v13.py`** - autocontenido. 4 slots: Signal A (mean-rev: RSI<25 + SMA<-10% + Score>30 + vol_ratio<=1.5, con regime, hold 7d) + Signal C5 cap operativo (crash: ROC10d<-15% + Vol>2x y <4x + RSI<35 + neg_days>=5 + score<85, health bloqueado, exit adaptativo +6% <= 4d sino day 7) + Signal D liderazgo/tendencia (Close>SMA50>SMA200 + ROC20>12% + REL20>7% + RSI 55-75 + vol 0.8-2x, hold 10d) + Signal E_HW RS New High Hardware (RS_LINE>=RS_52W_MAX + Close>SMA50>SMA200 + RSI 50-75 + ROC20>8% + vol 0.8-2.5x, hold 15d, WR hist 75%). V13 promovido 2026-04-13: 6/7 promotion gates PASS. Broad portfolio V13: Sharpe 1.62, MDD -37.0%, Calmar 35.0, WF 6/7. Referencia anterior: `SCANNER/invertir_v12.py` (V12 — A+C5+D 3 slots, Sharpe 1.36).

5. **`titan_system/` NO renombrar** - paquete Python. Cambiar nombre rompe todos los imports (`from titan_system.core.database import TitanDB`).

6. **DB se actualiza manualmente** - `python herramientas/actualizar_datos.py`. Validacion formal: `python herramientas/validate_market_data.py`. Auto-update diario a las 19:15 via Task Scheduler via `herramientas/auto_actualizar.py`, que ahora corre el pipeline `actualizar_datos -> validate_market_data -> aprendizaje_operativo_v11 -> aprendizaje_operativo_v12 -> aprendizaje_operativo_v13 -> scanner activo -> gestor -> resumen_v11 -> resumen_v12 -> resumen_v13 -> auditoria_integral_claude --mode fast`. Backfill historico one-off: `python herramientas/backfill_historico_db.py --years 6`. Invariante: `titan_system/core/data_loader.py::ACTIVOS` debe ser un superconjunto del universo de los scanners canonicos. `VIX` se descarga via alias `^VIX` y se guarda como `VIX`. La DB sanea barras OHLC inconsistentes de forma conservadora (`high=max(high,open,close)` / `low=min(low,open,close)`) al guardar y al reparar. Datos actuales: 2020-04-09 -> 2026-04-14 | 423,312 filas | 285 tickers. Memoria operativa: base `python herramientas/aprendizaje_operativo_v11.py run` | referencia inmediata `python herramientas/aprendizaje_operativo_v12.py run` | activa `python herramientas/aprendizaje_operativo_v13.py run`. Gestor canonico: `python herramientas/gestor_posiciones_v11.py` y reporte diario: `python herramientas/gestor_posiciones_v11.py daily-report`.

7. **Simplicidad > ML** - demostrado definitivamente: 4 reglas > ML complejo. No agregar complejidad sin evidencia.

8. **Al terminar la conversacion** - actualizar `bitacora/BITACORA.md` con resumen de la sesion.

9. **SQLite threading** - NUNCA llamar metodos de DB desde hilos worker del ThreadPoolExecutor. Pre-cargar datos en hilo principal antes de lanzar workers.

10. **Google Drive sync** - el proyecto sincroniza via Google Drive. En otra PC: `G:\Otros ordenadores\Mi New PC\Inversiones\Claude\`

## Protocolos de Razonamiento (post-compactacion)

11. **CoT obligatorio** - NUNCA conclusiones directas en analisis complejos. Enumerar datos -> razonar -> contradicciones -> conclusion.

12. **3-Fases para cambios** - todo cambio al sistema pasa por: ANALISTA (hipotesis + datos) -> CRITICO (overfitting? complejidad?) -> DIRECTOR (proceder SI/NO).

13. **Pre-mortem antes de implementar** - "Si esto falla en 6 meses, por que?" - si revela riesgos no mitigados, volver a Fase 2.

14. **Checklist Anti-Overfitting** - 8 items obligatorios post-backtest. >=6 PASS = aceptar, <4 = rechazar.

15. **Confianza explicita** - ALTA/MEDIA/BAJA en toda recomendacion. Si BAJA -> "REQUIERE MAS DATOS".

16. **Convergencia 3 angulos** - decisiones criticas: Tecnico + Riesgo + Simplicidad. 2/3 coinciden = proceder.

17. **Verification Gates expandidos** - RSI (Wilder), Datos (rango), Logica (filtros V11), Regime (SPY), Threads (pre-carga). Cualquier falla = DETENER.

18. **Scanners productivos autocontenidos** - cualquier scanner dentro de `SCANNER/` NUNCA importa codigo de otros scanners. Todo el codigo inline. Solo importar infraestructura (`titan_system`, librerias estandar).

19. **Naming de `SCANNER/` y variantes** - en `SCANNER/` solo van archivos productivos promovidos y congelados con nombre `invertir_vN.py` o `invertir_vN_M.py`. Variantes no promovidas, experimentos, formatos especiales o legados descriptivos van en `scanner_variantes/`.

20. **Ledger canonico de promociones** - `bitacora/BITACORA.md` narra y `experimentos/scanner_ledger.json` fija el veredicto estructurado. Toda promocion, rechazo o mejora aplicada al scanner activo debe quedar en ambos. Consultar con `python herramientas/ledger_experimentos.py status`.

21. **Promocion completa = aprendizaje propio** - un nuevo scanner activo no queda realmente promovido si no trae su `herramientas/aprendizaje_operativo_vN.py`, su backfill historico razonable y su integracion en `auto_actualizar.py` + `auditoria_integral_claude.py`.

22. **ML research solo vale si pasa validacion temporal dura** - recent check simple no alcanza. Antes de considerar ML para Claude debe pasar, como minimo, purged validation y expanding temporal realista. Si gana solo en k-fold con futuro mezclado pero pierde en expanding past-only, NO promover.

23. **Auditoria integral antes de confiar en cambios grandes** - usar `python herramientas/auditoria_integral_claude.py --mode full` para revalidar scanner, DB, loop operativo, docs, ledger y backtests criticos despues de reparaciones o promociones importantes.
24. **Centinela de stale changes** - cualquier cambio ejecutable en `SCANNER/`, `herramientas/`, `backtests/`, `titan_system/` o `experimentos/scanner_ledger.json` invalida el baseline del ultimo full audit. Hasta rerunear `--mode full`, el proyecto debe considerarse stale aunque el scanner diario siga corriendo.

## Verificacion rapida del estado actual
- DB range: 2020-04-09 -> 2026-04-14
- Scanner activo: `invertir_v13.py`
- Universo scanner: 197 | universo extendido validacion: 209 (`V11 + CONTEXT_TICKERS`)
- Universo loader alineado con V10/V11
- Alias VIX activo en `data_loader.py`
- Auto-update: Task Scheduler configurado 19:15 diario
- Frontera absorbida: `backtests/investigacion_v23_promotion_gate.py` -> `SCANNER/invertir_v13.py` (Signal E_HW RS New High Hardware)
