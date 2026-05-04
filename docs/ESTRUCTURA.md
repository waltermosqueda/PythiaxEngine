# Project Structure — PythiaxEngine

*Last updated: 2026-05-03*

---

## Root

```
PythiaxEngine/
|
|-- SCANNER/                        # Rule-based scanner production files
|-- ml_investigacion/               # ML model research files
|-- herramientas/                   # Operational pipeline and adapters
|-- titan_system/                   # Core infrastructure
|-- backtests/                      # Historical research
|-- analisis/                       # Dashboard output (published via GitHub Pages)
|-- aprendizaje_operativo/          # Model registry and competition config
|-- infra/                          # Database migrations and compatibility layers
|-- tests/                          # Automated test suite
|-- docs/                           # Project documentation
|-- bitacora/                       # Session history log
|-- scripts/                        # Utility scripts
|-- .github/
|   |-- workflows/                  # GitHub Actions CI/CD workflows
|   `-- copilot-instructions.md     # (reserved)
|
|-- AGENTS.md                       # AI agent policy (read first)
|-- CLAUDE.md                       # Coding rules and decision protocols
|-- ESTADO_ACTUAL.md                # Live session handoff state
|-- README.md                       # Project overview
|-- docker-compose.yml              # Local PostgreSQL service
|-- .env.example                    # Environment variable template
|-- pyproject.toml                  # Project metadata and tool config
|-- requirements-prod.txt           # Production dependencies
|-- requirements-dev.txt            # Development dependencies
|-- requirements-research.txt       # Research/ML dependencies
`-- alembic.ini                     # Database migration config
```

---

## SCANNER/

Frozen, production-grade rule-based scanner files. Each version is self-contained — no cross-imports between scanners.

```
SCANNER/
|-- invertir_v8.py         # Baseline scanner
|-- invertir_v9.py         # RSI tightened
|-- invertir_v10.py        # Volume filter added
|-- invertir_v11.py        # Champion (100% WR, 44 rounds)  <-- ACTIVE
|-- invertir_v12.py        # Composite scoring v1
`-- invertir_v13.py        # Extended motor, experimental   <-- ACTIVE
```

**Rule:** files here are immutable once promoted. Any new version → new file. Variants not yet promoted live in `scanner_variantes/`.

---

## ml_investigacion/

ML model research files. Each is a standalone module with its own `TradingEngine` class.

```
ml_investigacion/
|-- ml_trading_v22.py                 # Brain v9 — GBC+MLP, 4-fold WF (~222s/run)
|-- ml_trading_v23.py                 # Brain v10 — FastStackedEnsemble, 3-fold (~25s/run) <-- CURRENT
|-- ml_trading_TITAN_HYBRID.py        # Legacy ensemble variants
|-- ml_trading_TITAN_HYBRID_v3.py
|-- ml_trading_TITAN_HYBRID_v4.py
|-- ml_trading_TITAN_v5_QUANTUM.py    # V97 source
`-- ml_trading_titan_v2.py
```

---

## herramientas/

Operational adapters connecting research models to the Titan pipeline.

```
herramientas/
|-- auto_actualizar.py                          # Daily pipeline orchestrator
|-- refrescar_datos_dashboard.py                # Dashboard data refresh
|-- auditoria_integral_claude.py                # Full system audit
|-- competencia_modelos.py                      # Competition scoring engine
|-- competencia_topn_estandar.py                # Top-N selection standard
|-- aprendizaje_operativo_legacy_ml_base.py     # Base adapter (backfill, WF cache)
|-- aprendizaje_operativo_legacy_ml_brain_v10.py  # BRAIN_V10 adapter
|-- aprendizaje_operativo_legacy_ml_brain_v11.py  # BRAIN_V11 adapter
|-- aprendizaje_operativo_legacy_ml_brain_v11_optimized.py
|-- aprendizaje_operativo_legacy_ml_v37.py
|-- aprendizaje_operativo_legacy_ml_v39.py
|-- aprendizaje_operativo_legacy_ml_v39full.py
|-- aprendizaje_operativo_legacy_ml_v97.py
|-- aprendizaje_operativo_v11.py                # INVERTIR V11 adapter
|-- aprendizaje_operativo_v12.py
|-- aprendizaje_operativo_v13.py                # INVERTIR V13 adapter
`-- _build_c1pro.py                             # Dashboard C1 Pro builder
```

---

## titan_system/

Core infrastructure. Treat as a stable internal library — changes require audit.

```
titan_system/
|-- core/
|   |-- database.py        # TitanDB — PostgreSQL context manager (psycopg)
|   |-- data_loader.py     # Market data ingestion (yfinance + DB)
|   `-- models/            # ORM models (predictions, outcomes, pipeline_runs)
|-- data/                  # Local data cache
`-- __init__.py
```

---

## aprendizaje_operativo/

Model registry and competition configuration. Source of truth for which models are active.

```
aprendizaje_operativo/
|-- legacy_ml_models.json      # Registry of all Legacy ML models (status, config)
|-- observed_scanners.json     # Registry of INVERTIR scanner variants
`-- top_n_estandar_study.json  # Top-N selection research results
```

### legacy_ml_models.json — Active Models

| model_id | status | DB prefix |
|----------|--------|-----------|
| legacy_ml_v37 | enabled | LEGACY_ML_V37_SURGE_D1 |
| legacy_ml_v39 | enabled | LEGACY_ML_V39_TOP_D1 |
| legacy_ml_v39full | enabled | LEGACY_ML_V39FULL_TOP_D1 |
| legacy_ml_v94 | disabled | — |
| legacy_ml_v97 | enabled | LEGACY_ML_V97_SURGE_D3 |
| legacy_ml_brain_v9 | enabled | — |
| legacy_ml_brain_v10 | enabled | LEGACY_ML_BRAIN_V10_BUY_D5 |
| legacy_ml_brain_v11 | enabled | LEGACY_ML_BRAIN_V11_BUY_D5 |
| legacy_ml_brain_v11_optimized | enabled | LEGACY_ML_BRAIN_V11_OPT_BUY_D5 |

---

## analisis/

Generated HTML dashboard files. Published to GitHub Pages via CI.

```
analisis/
|-- preview_c1_pro.html             # Main dashboard (C1 Pro) — DEFAULT
|-- preview_h1_classic_full.html    # Heatmap variant 1
|-- preview_h2_families_compact.html
|-- preview_h3_dense_matrix.html
|-- preview_h4_ribbon_cards.html
|-- preview_h5_week_blocks.html
|-- preview_h6_champion_focus.html
|-- preview_h7_day_columns.html
|-- preview_h8_split_deck.html
|-- preview_h9_mini_calendars.html
|-- preview_h10_terminal_heat.html
`-- staging/                        # Test builds (not published)
```

**Important:** structural HTML/JS changes require staging review before promoting. Data-only refreshes (`refrescar_datos_dashboard.py`) can write directly.

---

## backtests/

Historical research scripts. Each file is a standalone investigation.

```
backtests/
|-- investigacion_v28_top_n_estandar.py   # Top-N policy research
|-- investigacion_v27_safe_pool_aggressive.py
|-- investigacion_v26_dynamic_special_frontier.py
|-- ... (v7-v28 research history)
|-- purged_cv_utils.py                    # Purged walk-forward utilities
`-- real_trades.py                        # Live trade tracking
```

---

## infra/

Database infrastructure.

```
infra/
|-- db/
|   |-- titandb_compat.py              # SQLite→PostgreSQL INSERT OR REPLACE rewrite
|   |-- migrate_sqlite_to_postgres.py  # One-time migration utility
|   `-- bootstrap_target.py           # DB bootstrap for new environments
`-- alembic/                           # Schema migration versions
```

---

## tests/

Automated test suite. Runs in CI on every push.

```
tests/
|-- test_operational_context.py        # Core system smoke tests
|-- test_db_runtime.py                 # DB connectivity tests
|-- test_db_config.py                  # Configuration tests
|-- test_competition_dashboard_visibility.py
|-- test_cloud_dashboard_integrity.py
`-- conftest.py
```

---

## docs/

Project documentation.

```
docs/
|-- ARCHITECTURE.md        # System architecture and data flow
|-- MODELS.md              # Model catalog with performance data
|-- ESTRUCTURA.md          # This file — repository structure guide
|-- TECNICAS_PROMPTING_AVANZADO_2025_2026.md  # AI-assisted dev techniques
`-- cloud/                 # Architecture Decision Records (ADRs)
    |-- README.md          # ADR index
    |-- ADR-001-free-professional-stack.md
    |-- ROADMAP_FREE_TIER.md
    `-- ...
```

---

## docs/cloud/ — Architecture Decision Records

This folder contains the Architecture Decision Records (ADRs) that defined the current stack. These are living historical documents — they explain *why* the system is built the way it is.

The migration they describe is **complete**. Current production stack:
- **Database:** PostgreSQL 16 (Docker local, GitHub Actions cloud service)
- **Pipeline:** GitHub Actions (daily batch + CI)
- **Dashboard:** GitHub Pages (static HTML, 24/7)
- **Source control:** GitHub (`waltermosqueda/PythiaxEngine`)

---

## bitacora/

```
bitacora/
`-- BITACORA.md    # Session-by-session development log
```

**Rule:** update at the end of every development session (CLAUDE.md rule #5).

---

## Naming Conventions

| Pattern | Meaning |
|---------|---------|
| `invertir_vN.py` | Production scanner version N |
| `invertir_vN_M.py` | Minor variant of scanner N |
| `ml_trading_vN.py` | ML research model version N |
| `investigacion_vN_*.py` | Research investigation |
| `aprendizaje_operativo_*.py` | Pipeline adapter |
| `_*.py` (underscore prefix) | Diagnostic / one-time utility script |
| `preview_*.html` | Dashboard variant |
