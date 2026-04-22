# Backtest Signal — Pipeline Automatizado

Cuando el usuario pida testear una nueva señal o estrategia, ejecutar este pipeline completo sin saltar pasos.

## Input esperado
El usuario provee una descripción de la señal a testear. Ejemplo:
- "testea RSI<20 + volumen 3x como nueva señal"
- "quiero probar CLV > 0.7 después de 3 días con CLV < 0.3"

## Pipeline obligatorio (NO saltar pasos)

### PASO 1: Definir hipótesis
Antes de escribir código, documentar:
- Nombre de la señal
- Filtros exactos y thresholds
- Hipótesis: ¿por qué debería funcionar?
- ¿Qué eje de información nuevo aporta?
- ¿Requiere regime filter o es contrarian?

### PASO 2: Implementar y correr backtest
Crear función de señal compatible con el engine de backtest del proyecto.
REGLAS CRÍTICAS:
- RSI SIEMPRE con Wilder's smoothing: `ewm(com=13, adjust=False)` — NUNCA `rolling(14).mean()`
- Entrada en close del día de señal, ejecución en open D+1
- Universo: ~70 tickers core (sin LatAm)
- Datos: mínimo 18 meses
- Anti-knife: 5 días entre trades del mismo ticker
- Hold: 7 días default (testear también 5, 10)

Métricas a reportar:
- Trades, WR, Sharpe, Avg Return, Total Return, MDD, Profit Factor

### PASO 3: Walk-Forward (OBLIGATORIO)
- 5 ventanas Y 7 ventanas
- Requerido: >= 80% ventanas positivas para PASS
- Reportar trades y Sharpe por ventana

### PASO 4: Comparar con V7 actual
Tabla comparativa obligatoria:
| Métrica | V7 (A+C) | Nueva señal | V7 + Nueva |
Incluir overlap analysis (% trades compartidos con V7).

### PASO 5: Monte Carlo (si pasa WF)
- 2000 simulaciones bootstrap
- Reportar: P(Sharpe>0), Median Sharpe, Worst 1% Sharpe, Worst 1% MDD

### PASO 6: Protocolo Anti-Overfitting (8 items)
```
[ ] LOOK-AHEAD BIAS
[ ] SURVIVORSHIP BIAS
[ ] PERÍODO >= 18 meses
[ ] OUT-OF-SAMPLE (WF)
[ ] WALK-FORWARD >= 80%
[ ] COMPLEJIDAD < 5 filtros
[ ] TRADES >= 15
[ ] COSTOS considerados
Resultado: >= 6 PASS = aceptar | 4-5 = revisar | <4 = rechazar
```

### PASO 7: Veredicto con Convergencia 3 ángulos
```
Ángulo 1 (Técnico): ¿Sharpe, WR, WF superan V7?
Ángulo 2 (Riesgo): ¿MDD aceptable? ¿Peor escenario MC?
Ángulo 3 (Simplicidad): ¿Cuántos filtros añade? ¿Vale la complejidad?
2/3 coinciden = proceder | 3/3 divergen = rechazar
```

### PASO 8: Output final
```
SEÑAL: [nombre]
VEREDICTO: APROBADA / RECHAZADA / NECESITA MÁS DATOS
CONFIANZA: ALTA / MEDIA / BAJA
ACCIÓN: [Agregar a V7 como Signal D / Reemplazar Signal X / No implementar]
EVIDENCIA: [resumen de números clave]
```

## Referencia V7 actual (baseline)
- Signal A: RSI<25 + MACD up + SMA<-10% + Score>30 (CON regime)
- Signal C: ROC 10d < -15% + Volume > 2x (SIN regime)
- 59 trades, WR 71.2%, Sharpe 4.12, MDD -7.9%
- WF 5w 100%, WF 7w 100%
- MC P(Sharpe>0) = 100%, Worst 1% Sharpe = +2.39
- Profit Factor: 5.69
