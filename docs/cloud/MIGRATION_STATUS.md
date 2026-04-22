# Migration Status

- Fecha de inicio: 2026-04-22
- Estado actual: `FASE 0 COMPLETADA / FASE 1 EN CURSO`
- Arquitectura objetivo: `GitHub + GitHub Actions + Neon Postgres + Cloudflare Pages + R2`

## Lo que ya quedo hecho en este corte

- definido el ADR de arquitectura objetivo
- creado el roadmap por fases
- inicializado `git` local con rama `main`
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

## Lo que falta inmediatamente

1. Revisar `git status` y consolidar el baseline local.
2. Crear el repo privado en GitHub.
3. Hacer el primer commit/tag de bootstrap.
4. Diseñar el schema `Postgres` equivalente a la DB actual.
5. Introducir una capa de acceso dual `SQLite/Postgres`.

## Bloqueadores conocidos

- el proyecto no estaba versionado con `git`
- hay dependencias legacy fuera del repo:
  - `Machine Winners`
- el acceso a datos todavia usa `sqlite3` directo en varios puntos

## Estrategia de rollback

- mientras no exista cutover, `SQLite` local sigue siendo la verdad operativa
- la tarea diaria local no debe apagarse hasta terminar shadow mode
- no se debe eliminar ningun artefacto local durante la fase 1/2

## Proximo corte recomendado

`FASE 1: baseline y remoto`

Pasos exactos:

1. revisar `git status`
2. primer commit: `chore: bootstrap repo for free-tier cloud migration`
3. crear repo privado remoto
4. push de `main`
5. activar GitHub Actions
