# PythiaxEngine

PythiaxEngine es un motor cuantitativo liviano para ingesta de datos de mercado,
generacion de predicciones operativas y publicacion de dashboards estaticos.

## Stack objetivo

- `Python 3.12+`
- `GitHub` para source control y CI/CD
- `GitHub Actions` para pipeline batch diario
- `Neon Postgres` como base de datos principal
- `Cloudflare Pages` para dashboard 24/7
- `Cloudflare R2` para artefactos, backups y auditorias
- `Docker` para ejecucion reproducible

## Estado actual

- El proyecto ya esta versionado con `git`.
- Existe scaffolding inicial de `SQLAlchemy + Alembic`.
- La migracion cloud esta documentada en [`docs/cloud/`](docs/cloud/README.md).
- El motor historico todavia conserva nombres internos como `Claude`,
  `titan_system` y `herramientas` para evitar regresiones durante la transicion.

## Flujo profesional buscado

1. Desarrollar en ramas cortas y hacer merge a `main`.
2. Ejecutar CI automatica en cada cambio relevante.
3. Migrar persistencia desde `SQLite` a `Postgres` con shadow mode.
4. Publicar snapshots del dashboard sin depender de una PC encendida.
5. Mantener trazabilidad con `run_id`, `commit_sha`, backups y auditorias.

## Documentacion clave

- [Cloud migration docs](docs/cloud/README.md)
- [Arquitectura objetivo](docs/cloud/ADR-001-free-professional-stack.md)
- [Roadmap por fases](docs/cloud/ROADMAP_FREE_TIER.md)
- [Estado vivo de migracion](docs/cloud/MIGRATION_STATUS.md)
