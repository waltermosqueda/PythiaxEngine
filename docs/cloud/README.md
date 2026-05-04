# Architecture Decision Records — PythiaxEngine

This folder documents the architecture decisions made to build the current production stack. These are historical records — the decisions described here are **implemented and live**.

---

## Current Production Stack (result of these decisions)

| Layer | Decision | Status |
|-------|----------|--------|
| Source control | GitHub (`waltermosqueda/PythiaxEngine`) | Live |
| CI/CD | GitHub Actions (daily batch + PR tests) | Live |
| Database | PostgreSQL 16 via Docker (local) / service container (CI) | Live |
| Dashboard hosting | GitHub Pages (static HTML, 24/7) | Live |
| Containers | Docker / docker-compose | Live |

---

## ADR Index

| File | Decision | Date |
|------|----------|------|
| [ADR-001](ADR-001-free-professional-stack.md) | Adopt free-tier professional stack (GitHub + Postgres + Pages) | 2026-04-22 |
| [ROADMAP_FREE_TIER.md](ROADMAP_FREE_TIER.md) | Phase-by-phase migration roadmap | 2026-04-22 |
| [SCHEMA_INVENTORY.md](SCHEMA_INVENTORY.md) | Database schema design | 2026-04-22 |
| [CLOUD_DAILY_OPERATIONS.md](CLOUD_DAILY_OPERATIONS.md) | Daily pipeline operations guide | 2026-04-22 |
| [DASHBOARD_BUILD_AUTOMATION.md](DASHBOARD_BUILD_AUTOMATION.md) | Dashboard build and publish automation | 2026-04-22 |
| [GITHUB_PAGES_PUBLISH.md](GITHUB_PAGES_PUBLISH.md) | GitHub Pages configuration | 2026-04-22 |
| [GITHUB_SECRETS_SETUP.md](GITHUB_SECRETS_SETUP.md) | CI secrets configuration | 2026-04-22 |

---

## Key Decisions

### Why PostgreSQL over SQLite

The system runs a live forward-testing competition across 9+ models with daily automated writes. PostgreSQL provides:
- Row-level locking for concurrent adapter writes
- Native `ON CONFLICT DO UPDATE` upsert semantics
- Proper sequence management for auto-increment PKs
- Full SQL standard compliance for analytics queries

SQLite remains available as a debugging fallback only (`infra/db/titandb_compat.py`).

### Why GitHub Pages over a live server

The dashboard is a static HTML file generated once per day. No real-time data, no user sessions, no backend needed. GitHub Pages gives 24/7 availability for free with zero operational overhead.

### Why Docker for local development

Reproducible, isolated PostgreSQL instance. Same major version (16) as the CI service container. `docker-compose up -d` is the only prerequisite beyond Python.

---

*For current system state and pending work, see [ESTADO_ACTUAL.md](../ESTADO_ACTUAL.md) at the repo root.*
