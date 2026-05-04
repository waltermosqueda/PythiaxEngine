# Architecture — PythiaxEngine

*Last updated: 2026-05-03*

---

## Overview

PythiaxEngine is a quantitative trading research platform built around a single question: **can machine learning consistently beat a well-calibrated rule-based strategy on short-term US equity signals?**

The architecture is designed to answer this honestly — with live forward testing, no post-hoc selection, and identical evaluation criteria for all models.

---

## System Components

```
+---------------------------+
|     Data Ingestion        |   yfinance daily pull, 178 US equities
+---------------------------+
              |
              v
+---------------------------+
|    PostgreSQL (TitanDB)   |   tables: prices, predictions, outcomes
+---------------------------+
       /            \
      /              \
     v                v
+----------+    +------------------+
| INVERTIR |    |    Legacy ML     |
| scanners |    |     models       |
+----------+    +------------------+
     |                |
     +-------+--------+
             |
             v
+---------------------------+
|   Outcome Evaluator       |   computes actual returns at D1/D4/D5/D7/D10/D15
+---------------------------+
             |
             v
+---------------------------+
|   Dashboard Builder       |   generates static HTML bundle
+---------------------------+
             |
             v
+---------------------------+
|     GitHub Pages          |   24/7 public dashboard
+---------------------------+
```

---

## Data Layer

### TitanDB

Central database abstraction (`titan_system/core/database.py`). Wraps PostgreSQL via `psycopg` (async-compatible). All model adapters and the dashboard read/write through this layer.

Key tables:

| Table | Purpose |
|-------|---------|
| `prices` | Daily OHLCV for 178 tickers (2024-04-29 onward, ~503 rows/ticker) |
| `predictions` | One row per model/ticker/date signal. Columns: `model_name`, `ticker`, `prediction_date`, `target_date`, `signal_score`, `signal_code`, `metadata` |
| `outcomes` | Realized returns at each holding period, linked to predictions |
| `pipeline_runs` | Execution log for every daily run |

### Prediction naming convention

```
LEGACY_ML_{MODEL}_BUY_D{horizon}
INVERTIR_V{N}_{series}_D{horizon}
```

Examples: `LEGACY_ML_BRAIN_V10_BUY_D5`, `INVERTIR_V13_D_D10`

---

## Model Families

### INVERTIR — Rule-based Scanners

Located in `SCANNER/invertir_vN.py`. Each version is a frozen, self-contained file.

**Current active scanner: V13** (promoted 2026-04-13)

Signal logic (V13):
- RSI(14) < 25 using Wilder smoothing `ewm(com=13, adjust=False)`
- 20d SMA return < -10%
- Composite score > 30
- Volume ratio <= 1.5x

Versions V8–V12 remain in the registry as historical competitors. Scanner variants under research live in `scanner_variantes/`.

### Legacy ML — Ensemble Models

Located in `ml_investigacion/`. Each model is an independent research file. Production adapters in `herramientas/aprendizaje_operativo_legacy_ml_*.py`.

**Feature set (62 features, shared across all ML models):**
- Price momentum: 1d/3d/5d/10d/20d returns
- RSI at multiple windows
- Bollinger Band position and width
- Volume ratios and anomaly flags
- SMA crossover distances
- Sector relative performance
- Market regime features (SPY-based)
- Volatility (ATR, realized vol)

**Label: Triple Barrier**
- Upper barrier: +1.8% in 5 days → BUY label
- Lower barrier: -1.8% in 5 days → neutral/skip
- Time barrier: 5 days

**Training: Walk-Forward Cross-Validation**
- ML models retrain once per ISO week during backfill
- 3-fold expanding window (v23/brain_v10), 4-fold (v22/brain_v9)

---

## ML Model Architectures

| Model ID | Algorithm | Notes |
|----------|-----------|-------|
| ML_V37 | Stacked ensemble | Surge signal, D1 horizon |
| ML_V39 | Stacked ensemble | Top-N selection, D1 |
| ML_V39FULL | Stacked ensemble | Extended universe |
| ML_V97 | Stacked ensemble | Surge signal, D3 |
| ML_BRAIN_V11 | GBC + MLP + 4-fold WF | ~222s per run |
| ML_BRAIN_V11_OPT | GBC + MLP optimized | Variant of V11 |
| ML_BRAIN_V10 | HistGBC + RF/ET/XGB + 3-fold WF | 8.7x faster than V11 |

### ML_BRAIN_V10 (ml_trading_v23.py) — current generation

`FastStackedEnsemble`: HistGradientBoosting(150) + RandomForest(80) + ExtraTrees(80) + XGBoost(100, hist) + LogisticRegression
- Vectorized Triple Barrier with numpy broadcasting (100x faster than loop)
- Parallel feature computation via joblib
- 3-fold walk-forward (vs 4-fold in v22)
- Identical pick logic to v22/brain_v9 — 8/8 ticker agreement proven in `_comparar_v22_vs_v23.py`

---

## Daily Pipeline

Orchestrated by `herramientas/auto_actualizar.py` and triggered by GitHub Actions (`.github/workflows/`):

```
1. Fetch latest prices (yfinance)
2. Store/update prices table
3. Run each active scanner adapter
   - INVERTIR models → record_snapshot()
   - Legacy ML models → record_snapshot()
4. Evaluate outcomes for predictions with reached target_date
5. Rebuild dashboard HTML
6. Commit and push to GitHub Pages branch
```

---

## Dashboard

Generated by `herramientas/refrescar_datos_dashboard.py` and `analisis/generar_tablero_maquina_pensante.py`.

Published variants:
- `analisis/preview_c1_pro.html` — main C1 Pro dashboard (default)
- `analisis/preview_h1_classic_full.html` through `h10` — heatmap variants

Dashboard sections:
- Live picks with signal date, entry price, target date
- Win rate and average return per model
- Competition ranking (36-round sliding window)
- Performance heatmap (30 rounds + 5 upcoming)
- Jaccard similarity matrix (model diversification)

---

## Evaluation Methodology

**Entry price:** OPEN of the day after the signal date
**Exit price:** CLOSE at target date
**Return:** `(exit - entry) / entry`
**Win:** return > 0%

All models share the same evaluation logic. No custom exit rules per model.

**Competition window:** all models evaluated on the same date range. New models must backfill from the earliest date of their family before entering the leaderboard.

---

## Infrastructure

| Component | Local | Cloud (CI) |
|-----------|-------|------------|
| Database | Docker `postgres:16-alpine`, port 5433 | GitHub Actions service container |
| Config | `.env` with `DATABASE_URL` | GitHub Secrets |
| DB migrations | Alembic (`infra/alembic/`) | Applied in CI pre-test step |
| Dashboard publish | Manual push | GitHub Actions on main merge |
