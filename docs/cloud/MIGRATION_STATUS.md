# Migration Status

- Fecha de inicio: 2026-04-22
- Estado actual: `FASE 1 COMPLETADA / FASE 2 INICIADA`
- Arquitectura objetivo: `GitHub + GitHub Actions + Neon Postgres + Cloudflare Pages + R2`
- Baseline local: commit `071c246`

## Lo que ya quedo hecho

- definido el ADR de arquitectura objetivo
- creado el roadmap por fases
- inicializado `git` local con rama `main`
- creado el baseline local versionado del proyecto
- agregado scaffolding base del repo:
  - `.gitignore`
  - `.dockerignore`
  - `.env.example`
  - `pyproject.toml`
  - `requirements-prod.txt`
  - `requirements-dev.txt`
  - `requirements-research.txt`
  - `Dockerfile`
  - `.pre-commit-config.yaml`
  - `.github/workflows/ci.yml`
  - `tests/test_operational_context.py`
- agregado scaffolding de persistencia profesional:
  - `infra/db/`
  - `alembic.ini`
  - `alembic/`
  - `docs/cloud/SCHEMA_INVENTORY.md`

## Lo que falta inmediatamente

1. Crear el repo privado en GitHub.
2. Hacer push del baseline local.
3. Instalar dependencias `dev/cloud` para correr CI local completa.
4. Introducir una capa de acceso dual `SQLite/Postgres`.
5. Preparar la migracion inicial de datos hacia Neon.

## Bloqueadores conocidos

- hay dependencias legacy fuera del repo:
  - `Machine Winners`
- el acceso a datos todavia usa `sqlite3` directo en varios puntos
- `git` dentro de esta carpeta requiere comandos fuera del sandbox para escribir metadata

## Estrategia de rollback

- mientras no exista cutover, `SQLite` local sigue siendo la verdad operativa
- la tarea diaria local no debe apagarse hasta terminar shadow mode
- no se debe eliminar ningun artefacto local durante la fase 1/2

## Proximo corte recomendado

`FASE 2: remoto + capa dual de DB`

Pasos exactos:

1. crear repo privado remoto
2. push de `main`
3. activar GitHub Actions
4. agregar wrapper de configuracion DB en runtime
5. empezar a reemplazar los `sqlite3.connect(...)` directos
