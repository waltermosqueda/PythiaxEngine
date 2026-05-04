# Model Catalog — PythiaxEngine

*Last updated: 2026-05-03 | Competition window: 44 rounds (2025-12-18 to 2026-04-29)*

---

## Overview

PythiaxEngine runs two families of prediction models in live competition. All models operate on the same universe (178 US equities), same signal date, same entry/exit prices, and same evaluation windows.

**Competition rule:** a model must be evaluated on the same date range as the rest of its family before joining the leaderboard. No partial-window comparisons.

---

## Current Standings (44-round sample)

| Rank | Model | Family | Status | Win Rate | Avg Return | Total Picks | Competition Rounds |
|------|-------|--------|--------|----------|------------|-------------|-------------------|
| 1 | **V11** | INVERTIR | Active | **100.00%** | **+6.61%** | 19 | 44/44 |
| 2 | **V13** | INVERTIR | Active | 62.12% | +5.06% | 66 | 34/44 |
| 3 | ML_V97 | Legacy ML | Active | 78.57% | +4.07% | 84 | 42/44 |
| 4 | ML_V39 | Legacy ML | Active | 63.95% | +0.52% | 86 | 43/44 |
| 5 | ML_V39FULL | Legacy ML | Active | 58.82% | +0.40% | 85 | 43/44 |
| 6 | ML_BRAIN_V11 | Legacy ML | Active | 51.25% | +1.64% | 80 | 40/44 |
| 7 | ML_BRAIN_V11_OPT | Legacy ML | Active | 51.25% | +1.40% | 80 | 40/44 |
| 8 | ML_V37 | Legacy ML | Active | 40.74% | -0.16% | 81 | 43/44 |
| — | ML_BRAIN_V10 | Legacy ML | Backfill | — | — | — | entering soon |

---

## INVERTIR Family — Rule-Based Scanners

### Design Philosophy

Simple, interpretable filters that exploit short-term mean-reversion in oversold equities. Every filter has a direct market rationale — no black boxes, no parameter fitting on recent data.

**Evaluation mode:** D7 (7-day holding period, close-to-close)

### V11 — Champion

- **Status:** Active, Champion
- **Signal logic:**
  - RSI(14) < 25 (Wilder smoothing: `ewm(com=13, adjust=False)`)
  - 20-day SMA return < -10%
  - Composite score > 30
  - Volume ratio ≤ 1.5x
- **Universe:** 44 curated high-liquidity US equities
- **Max picks per day:** 1
- **Key result:** 100% WR over 44 rounds, +6.61% avg return, 19 picks
- **Best round:** +13.54% | **Worst round:** +0.09%
- **File:** `SCANNER/invertir_v11.py`

### V13 — Experimental Motor

- **Status:** Active, Experimental
- **Signal logic:** Extended V11 with additional composite scoring
- **Universe:** Expanded (178 tickers)
- **Max picks per day:** up to 4
- **Key result:** 62.12% WR, +5.06% avg return, 66 picks over 34 active rounds
- **Best round:** +26.24% | **Worst round:** -20.18%
- **File:** `SCANNER/invertir_v13.py`

### Historical Versions (V8–V12)

Remain in the registry as historical competitors. Their predictions are stored in DB and included in diversification analysis.

| Version | WR | Avg Ret | Notes |
|---------|-----|---------|-------|
| V8 | — | — | Early baseline |
| V9 | — | — | RSI tightened |
| V10 | — | — | Volume filter added |
| V12 | — | — | Composite scoring v1 |

---

## Legacy ML Family — Ensemble Models

### Design Philosophy

Supervised learning on 62 engineered features with Triple Barrier labeling. Walk-forward validation to prevent look-ahead bias. Models compete on identical terms with the rule-based scanners.

**Historical finding:** complexity does not guarantee performance. The 4-filter V11 (Sharpe 14) has outperformed all ML models on risk-adjusted returns. This drives the research agenda — find the ML model that genuinely adds alpha.

**Evaluation mode:** D5 (5-day holding period, native horizon)

### ML_V97 — Best Performing ML

- **Status:** Active
- **Algorithm:** Stacked ensemble, surge signal
- **Horizon:** D3 (3-day)
- **Key result:** 78.57% WR, +4.07% avg return, 84 picks
- **DB prefix:** `LEGACY_ML_V97_SURGE_D3`
- **File:** `ml_investigacion/ml_trading_TITAN_v5_QUANTUM.py` (adapter: `herramientas/aprendizaje_operativo_legacy_ml_v97.py`)

### ML_V39 — Best Coverage ML

- **Status:** Active
- **Algorithm:** Top-N stacked ensemble selection
- **Horizon:** D1
- **Key result:** 63.95% WR, +0.52% avg return, 86 picks across 43/44 rounds
- **DB prefix:** `LEGACY_ML_V39_TOP_D1`
- **File:** adapter: `herramientas/aprendizaje_operativo_legacy_ml_v39.py`

### ML_V39FULL

- **Status:** Active
- **Algorithm:** Top-N extended universe
- **Horizon:** D1
- **Key result:** 58.82% WR, +0.40% avg return, 85 picks
- **DB prefix:** `LEGACY_ML_V39FULL_TOP_D1`

### ML_BRAIN_V11

- **Status:** Active
- **Algorithm:** GBC(250) + MLP(256, 128, 64) + 4-fold WF
- **Horizon:** D5
- **Training time:** ~222s per run (9 tickers benchmark)
- **Key result:** 51.25% WR, +1.64% avg return, 80 picks
- **DB prefix:** `LEGACY_ML_BRAIN_V11_BUY_D5`

### ML_BRAIN_V11_OPT

- **Status:** Active
- **Algorithm:** Optimized variant of BRAIN_V11
- **Key result:** 51.25% WR, +1.40% avg return, 80 picks
- **DB prefix:** `LEGACY_ML_BRAIN_V11_OPT_BUY_D5`

### ML_V37

- **Status:** Active
- **Algorithm:** Surge signal ensemble
- **Horizon:** D1
- **Key result:** 40.74% WR, -0.16% avg return, 81 picks
- **DB prefix:** `LEGACY_ML_V37_SURGE_D1`

### ML_BRAIN_V10 — Current Generation (entering competition)

- **Status:** Backfill in progress (2025-12-18 onward)
- **Algorithm:** `FastStackedEnsemble` — HistGradientBoosting(150) + RandomForest(80) + ExtraTrees(80) + XGBoost(100 hist) + LogisticRegression
- **Horizon:** D5
- **vs BRAIN_V11:** 8.7x faster (25s vs 222s), identical signal logic, 8/8 ticker agreement validated
- **Key improvements over v22/brain_v9:**
  - Vectorized Triple Barrier (numpy broadcasting, 100x faster)
  - Parallel feature computation (joblib)
  - HistGBC instead of GBC (30–50x faster gradient boosting)
  - 3-fold WF instead of 4-fold
- **DB prefix:** `LEGACY_ML_BRAIN_V10_BUY_D5`
- **Source:** `ml_investigacion/ml_trading_v23.py`
- **Adapter:** `herramientas/aprendizaje_operativo_legacy_ml_brain_v10.py`
- **Equivalence proof:** `_comparar_v22_vs_v23.py`

---

## Disabled Models

| Model | Reason |
|-------|--------|
| ML_V22 (brain_v9) | Superseded by BRAIN_V10 (identical logic, 8.7x slower) |
| ML_V94 | Retired — performance below threshold |

---

## Model Diversification

Jaccard similarity matrix (latest 31 rounds) shows near-zero overlap between most model pairs — the portfolio of signals is well-diversified. Notable exception: BRAIN_V11 and BRAIN_V11_OPT share ~18-33% of picks (expected, as variants of the same base).

---

## Adding a New Model — Checklist

1. Research file in `ml_investigacion/` with equivalence test vs previous version
2. Adapter in `herramientas/aprendizaje_operativo_legacy_ml_<name>.py`
3. Entry in `aprendizaje_operativo/legacy_ml_models.json` with `status: enabled`
4. **Backfill from the family start date** (query `SELECT MIN(prediction_date)...` — see AGENTS.md rule)
5. Audit with `python herramientas/auditoria_integral_claude.py --mode full`
6. Dashboard refresh and commit
