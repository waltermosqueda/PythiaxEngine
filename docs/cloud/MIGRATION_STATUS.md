# Migration Status

- Fecha de inicio: 2026-04-22
- Estado actual: `FASE 1 COMPLETADA / FASE 2 INICIADA / REMOTO SINCRONIZADO`
- Nombre publico del proyecto: `PythiaxEngine`
- Ruta local historica: `Claude/`
- Arquitectura objetivo: `GitHub + GitHub Actions + Neon Postgres + Cloudflare Pages + R2`
- Repo remoto objetivo: `https://github.com/waltermosqueda/PythiaxEngine`
- Baseline local: commit `071c246`

## Lo que ya quedo hecho

- definido el ADR de arquitectura objetivo
- creado el roadmap por fases
- inicializado `git` local con rama `main`
- creado el baseline local versionado del proyecto
- configurado `origin` hacia `waltermosqueda/PythiaxEngine`
- configurada autoria local de `git` para `Walter Mosqueda`
- completado el primer push de `main` hacia GitHub
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
- centralizada la resolucion de SQLite fallback en `infra/db/sqlite_compat.py`
- conectados a la capa central los scripts criticos:
  - `titan_system/core/database.py`
  - `herramientas/auto_actualizar.py`
  - `herramientas/auditoria_integral_claude.py`
  - `herramientas/competencia_modelos.py`
- reforzada `CI` con `workflow_dispatch` y compilacion de `infra/alembic/tests`
- agregados tests de runtime DB en `tests/test_db_runtime.py`

## Lo que falta inmediatamente

1. Instalar dependencias `dev/cloud` para correr CI local completa.
2. Verificar la primera corrida de GitHub Actions en remoto.
3. Introducir una capa de acceso dual `SQLite/Postgres` en queries mas profundas.
4. Preparar la migracion inicial de datos hacia Neon.
5. Definir secrets cloud minimos para el primer pipeline remoto.

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

`FASE 2: CI remota + capa dual de DB`

Pasos exactos:

1. activar GitHub Actions
2. instalar dependencias `dev/cloud` para validar localmente
3. extender la capa dual a queries y escrituras no abstraidas
4. empezar a reemplazar los `sqlite3.connect(...)` directos restantes
5. preparar migracion inicial hacia Neon
