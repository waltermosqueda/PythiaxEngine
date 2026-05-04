# PythiaxEngine

**Quantitative trading research engine** — live forward-testing competition between rule-based and ML-based prediction models on US equities.

**Live dashboard:** https://waltermosqueda.github.io/PythiaxEngine/

---

## What it does

PythiaxEngine ingests daily market data for 178 US equities, runs competing prediction models, evaluates outcomes at multiple holding periods, and publishes a transparent performance leaderboard updated daily.

The core thesis: put rule-based and ML models in honest head-to-head competition, with uniform evaluation criteria, shared data, and no cherry-picking of windows.

---

## Architecture

```
Market Data (yfinance)
        |
        v
PostgreSQL (TitanDB)          <-- single source of truth
        |
        |-- INVERTIR Family (rule-based scanners V8-V13)
        |       |-- RSI / SMA / Volume / Momentum signals
        |
        |-- Legacy ML Family (ensemble models)
                |-- V37, V39, V39FULL, V97, BRAIN_V11, BRAIN_V10
                        |-- XGBoost, HistGradientBoosting, RF/ET, LR
                                |-- Triple Barrier labels, Walk-Forward CV
        |
        v
Outcome Evaluator (D1 / D4 / D5 / D7 / D10 / D15 holding periods)
        |
        v
Dashboard Builder --> analisis/preview_c1_pro.html
        |
        v
GitHub Pages  (static, 24/7 public)
```

---

## Model Competition - Current Standings

> Window: 44 rounds, as of 2026-05-01

| Rank | Model | Family | Win Rate | Avg Return | Picks |
|------|-------|--------|----------|------------|-------|
| 1 | V11 | Rule-based | 100.00% | +6.61% | 19 |
| 2 | ML_V97 | Legacy ML | 78.57% | +4.07% | 84 |
| 3 | ML_V39 | Legacy ML | 63.95% | +0.52% | 86 |
| 4 | V13 | Rule-based | 62.12% | +5.06% | 66 |
| 5 | ML_V39FULL | Legacy ML | 58.82% | +0.40% | 85 |
| 6 | ML_BRAIN_V11 | Legacy ML | 51.25% | +1.64% | 80 |
| 7 | ML_BRAIN_V11_OPT | Legacy ML | 51.25% | +1.40% | 80 |
| 8 | ML_V37 | Legacy ML | 40.74% | -0.16% | 81 |

*ML_BRAIN_V10 (v23 Ultra-Fast) entering competition after backfill completes.*

---

## Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.14 |
| Database | PostgreSQL 16 (Docker local, GitHub Actions cloud) |
| ML | XGBoost 3.2, scikit-learn (HistGBC, RF, ET, LR) |
| Pipeline | GitHub Actions (daily batch) |
| Dashboard | Static HTML/CSS/JS via GitHub Pages |
| Versioning | Git, GitHub |
| Containers | Docker, docker-compose |

---

## Local Setup

```bash
# 1. Start the database
docker-compose up -d

# 2. Install dependencies
pip install -r requirements-prod.txt

# 3. Run daily pipeline
python herramientas/auto_actualizar.py

# 4. Refresh dashboard
python herramientas/refrescar_datos_dashboard.py
```

Copy `.env.example` to `.env` and set `DATABASE_URL` before running.

---

## Repository Layout

```
PythiaxEngine/
|-- SCANNER/                  # Promoted rule-based scanners (invertir_vN.py)
|-- ml_investigacion/         # ML model research (v22, v23/brain_v10, ...)
|-- herramientas/             # Operational adapters and daily pipeline
|-- titan_system/             # Core infrastructure (DB, data loader, models)
|-- backtests/                # Historical research and walk-forward studies
|-- analisis/                 # Dashboard HTML output (GitHub Pages)
|-- aprendizaje_operativo/    # Model registry (JSON) and competition config
|-- infra/                    # DB migrations (Alembic), compat layers
|-- tests/                    # Automated test suite (CI)
|-- docs/                     # Architecture docs and ADRs
|-- bitacora/                 # Session log
|-- ESTADO_ACTUAL.md          # Live handoff state (read at session start)
|-- AGENTS.md                 # AI agent operational policy
`-- CLAUDE.md                 # Coding rules and decision protocols
```

---

## Key Design Principles

1. **Fair competition** - all models evaluated on the same date window, same universe, same entry/exit rules.
2. **No look-ahead bias** - signals generated with only data available at prediction time.
3. **Walk-forward validation** - ML models retrain weekly; no static train/test split.
4. **Simplicity benchmark** - 4-rule scanner (Sharpe 14) vs 40-feature ML (Sharpe -0.65). Complexity must earn its place.
5. **Full auditability** - every prediction stored with model_name, ticker, prediction_date, target_date, and outcome.

---

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Model Catalog](docs/MODELS.md)
- [Project Structure](docs/ESTRUCTURA.md)
- [Architecture Decision Records](docs/cloud/README.md)
- [Session Log](bitacora/BITACORA.md)
- [Current State / Handoff](ESTADO_ACTUAL.md)
