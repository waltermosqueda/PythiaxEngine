# Migration Status

- Fecha de inicio: 2026-04-22
- Estado actual: `FASE 1 COMPLETADA / FASE 2 INICIADA / REMOTO SINCRONIZADO / CLOUD BOOTSTRAP READY / PAGES BRIDGE READY`
- Nombre publico del proyecto: `PythiaxEngine`
- Ruta local historica: `Claude/`
- Arquitectura objetivo: `GitHub + GitHub Actions + Neon Postgres + Cloudflare Pages + R2`
- Hosting puente gratis actual: `GitHub Pages`
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
- agregada utilidad reproducible de migracion `SQLite -> target` en:
  - `infra/db/migrate_sqlite_to_postgres.py`
- agregado wrapper de bootstrap local para target cloud:
  - `infra/db/bootstrap_target.py`
- agregado smoke test de migracion controlada:
  - `tests/test_sqlite_to_postgres_migration.py`
- agregado smoke test de bootstrap controlado:
  - `tests/test_bootstrap_target.py`
- documentado el procedimiento de carga inicial hacia Neon:
  - `docs/cloud/SQLITE_TO_POSTGRES_RUNBOOK.md`
- agregada capa runtime de lectura agnostica de backend:
  - `infra/db/runtime.py`
- migrados a runtime DB:
  - `analisis/generar_tablero_maquina_pensante.py`
  - `herramientas/competencia_modelos.py`
  - `herramientas/auditoria_integral_claude.py`
  - `herramientas/competencia_topn_estandar.py`
- agregada liga con fallback desde DB cuando faltan snapshots locales:
  - `herramientas/competencia_topn_estandar.py`
- agregado test de fallback DB para la liga:
  - `tests/test_competition_db_fallback.py`
- agregado fallback DB para `active_run` del dashboard cuando faltan snapshots:
  - `analisis/generar_tablero_maquina_pensante.py`
- agregado test de fallback DB para snapshot activo del dashboard:
  - `tests/test_dashboard_active_snapshot_fallback.py`
- agregada metadata de build y manifest auditable para el dashboard:
  - `analisis/generar_tablero_maquina_pensante.py`
  - `tests/test_dashboard_artifact_manifest.py`
- activado el ledger profesional `pipeline_runs` para builds del dashboard:
  - `infra/db/pipeline_runs.py`
  - `tests/test_pipeline_runs.py`
- agregado workflow remoto programado para generar el bundle del dashboard:
  - `.github/workflows/dashboard-build.yml`
- documentada la automatizacion del dashboard:
  - `docs/cloud/DASHBOARD_BUILD_AUTOMATION.md`
- agregado empaquetado estatico para publicacion web del dashboard:
  - `infra/publish/dashboard_site.py`
  - `tests/test_dashboard_site_publish.py`
- agregado workflow gratis de publicacion 24/7 via GitHub Pages:
  - `.github/workflows/github-pages-publish.yml`
- documentada la fase puente de hosting gratuito:
  - `docs/cloud/GITHUB_PAGES_PUBLISH.md`
- agregado registro de deploy de Pages en `pipeline_runs`:
  - `infra/publish/record_pages_publish.py`
  - `tests/test_pages_publish_ledger.py`
- agregado workflow manual de validacion cloud:
  - `.github/workflows/neon-schema-smoke.yml`
- documentado setup de secrets:
  - `docs/cloud/GITHUB_SECRETS_SETUP.md`

## Lo que falta inmediatamente

1. Instalar dependencias `dev/cloud` para correr CI local completa.
2. Verificar la primera corrida de GitHub Actions en remoto.
3. Ejecutar el bootstrap local inicial hacia Neon con reporte.
4. Verificar el primer `Dashboard Build` contra `DATABASE_URL` real.
5. Habilitar `GitHub Pages` y validar la primera publicacion remota.
6. Extender la capa dual a escrituras y piezas operativas restantes.
7. Desacoplar snapshots operativos restantes para poder publicar dashboard 100% cloud.

## Bloqueadores conocidos

- hay dependencias legacy fuera del repo:
  - `Machine Winners`
- la operacion sigue siendo `SQLite-first`; la capa dual real con `Postgres`
  todavia no llega a queries y escrituras profundas
- parte de los snapshots operativos del dashboard todavia vive fuera del repo:
  - `aprendizaje_operativo/*_runs`
- aunque falten esos snapshots, la liga competitiva ya puede reconstruirse desde
  la DB como fallback; todavia quedan bloques visuales que usan snapshots directos
- el `active_run` del dashboard ya tiene fallback DB-driven; todavia quedan
  otros artefactos de snapshot local fuera de esa ruta principal
- el workflow remoto de dashboard depende de `DATABASE_URL`; hasta bootstrapear
  Neon no puede generar el bundle real desde cloud
- el dashboard ya intenta persistir su corrida en `pipeline_runs`; en la SQLite
  historica actual hace `skip` limpio si esa tabla todavia no existe
- los `run_id` del ledger ya quedan namespaced por pipeline e intento para no
  chocar entre `dashboard_build` y `github_pages_publish`
- la publicacion por `GitHub Pages` tambien depende de `DATABASE_URL` y de
  habilitar `Settings > Pages > Source: GitHub Actions`
- `git` dentro de esta carpeta requiere comandos fuera del sandbox para escribir metadata

## Estrategia de rollback

- mientras no exista cutover, `SQLite` local sigue siendo la verdad operativa
- la tarea diaria local no debe apagarse hasta terminar shadow mode
- no se debe eliminar ningun artefacto local durante la fase 1/2
- si `GitHub Pages` falla, el bundle auditable del dashboard sigue quedando disponible como artifact del workflow

## Proximo corte recomendado

`FASE 2: bootstrap local a Neon + smoke remoto + dashboard build remoto + GitHub Pages`

Pasos exactos:

1. activar GitHub Actions
2. instalar dependencias `dev/cloud` para validar localmente
3. cargar secret `DATABASE_URL` en GitHub
4. correr `python -m infra.db.bootstrap_target`
5. validar con workflow `Neon Schema Smoke`
6. correr workflow `Dashboard Build`
7. habilitar `GitHub Pages`
8. correr workflow `GitHub Pages Publish`
