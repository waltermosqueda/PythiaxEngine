# PythiaxEngine

PythiaxEngine es un motor cuantitativo liviano para ingesta de datos de mercado,
generacion de predicciones operativas y publicacion de dashboards estaticos.

## Foco operativo

- La unica linea activa de trabajo es `PythiaxEngine` sobre `GitHub + Supabase + GitHub Pages`.
- La carpeta local `Claude/` es solo el nombre historico del working copy. No debe tratarse como un proyecto separado ni como fuente de verdad alternativa.
- Cualquier analisis, mejora, correccion o auditoria debe hacerse contra el repo remoto `waltermosqueda/PythiaxEngine` y su pipeline cloud-first.
- Solo se revisan dependencias locales o proyectos hermanos si aparece una rotura critica de migracion que bloquee la operacion cloud.

## Stack objetivo

- `Python 3.12+`
- `GitHub` para source control y CI/CD
- `GitHub Actions` para pipeline batch diario
- `Supabase Postgres` como base de datos principal
- `GitHub Pages` como bridge actual para dashboard 24/7
- `Cloudflare Pages + R2` como target futuro para hosting y artefactos
- `Docker` para ejecucion reproducible

## Estado actual

- El proyecto ya esta versionado con `git`.
- Existe scaffolding inicial de `SQLAlchemy + Alembic`.
- La migracion cloud esta documentada en [`docs/cloud/`](docs/cloud/README.md).
- El runtime actual ya puede leer desde `Postgres` cloud via `DATABASE_URL`.
- El runtime operativo ahora debe apuntar a `Supabase Postgres` por `DATABASE_URL`
  tanto en local como en cloud.
- `SQLite` queda solo como modo legacy explicito para debugging puntual,
  nunca como fallback silencioso del runtime principal.
- El bundle del dashboard ya se puede publicar 24/7 via `GitHub Pages`.
- El dashboard y el site bundle ya tienen auditoria reproducible DB vs snapshot/site.
- El motor historico todavia conserva nombres internos como `Claude`,
  `titan_system` y `herramientas` para evitar regresiones durante la transicion.

## Flujo profesional buscado

1. Desarrollar en ramas cortas y hacer merge a `main`.
2. Ejecutar CI automatica en cada cambio relevante.
3. Mantener `Supabase Postgres` como fuente de verdad en todos los entornos.
4. Publicar snapshots del dashboard sin depender de una PC encendida.
5. Mantener trazabilidad con `run_id`, `commit_sha`, backups y auditorias.

## Documentacion clave

- [Cloud migration docs](docs/cloud/README.md)
- [Arquitectura objetivo](docs/cloud/ADR-001-free-professional-stack.md)
- [Roadmap por fases](docs/cloud/ROADMAP_FREE_TIER.md)
- [Estado vivo de migracion](docs/cloud/MIGRATION_STATUS.md)
