# Plan de inversion diario — PythiaxEngine

Este directorio almacena los planes de inversion diarios generados por
`scripts/plan_inversion_diario.py`.

Cada dia el workflow `.github/workflows/plan-inversion-diario.yml` se
dispara despues del **Cloud Daily Operations** (post-cierre NYSE 18:30 AR)
y deja aqui dos archivos:

- `plan_YYYY-MM-DD.md`   — Markdown legible con metodologia, picks, sizing, news, watchlist, descartes y disclaimer.
- `plan_YYYY-MM-DD.json` — version estructurada del mismo plan para consumo programatico.

Convive en paralelo con `scripts/reporte_diario_trader.py`, que envia un
resumen breve por Telegram. Este plan agrega:

- **Sizing concreto en USD** (shares, capital comprometido, riesgo a stop, R:R).
- **News headlines (14d)** via yfinance.
- **Earnings calendar** (filtro de eventos binarios).
- **Macro context** (SPY, QQQ, VIX, tendencia 5d).
- **Filtros de descarte estrictos** con razon explicita.
- **Markdown versionado** en git para historial y reproducibilidad.
- **Tambien envia por Telegram** un resumen del plan (formato distinto al `reporte_diario_trader.py`).

## Ejecucion manual

```powershell
py scripts/plan_inversion_diario.py
py scripts/plan_inversion_diario.py --capital 5000 --risk-pct 0.01 --max-picks 3
py scripts/plan_inversion_diario.py --no-enrichment --no-telegram   # smoke test
```

## ⚠️ Disclaimer

Los planes son propuestas algoritmicas basadas en consenso multi-modelo,
analisis tecnico (yfinance) y fundamental. **NO son asesoramiento financiero.**
Hacé tu propia diligencia.
