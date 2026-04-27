# Migration Status

- Fecha de inicio: 2026-04-22
- Estado actual: `FASE 1 COMPLETADA / FASE 2 AVANZADA / NEON BOOTSTRAP COMPLETADO / DASHBOARD POSTGRES VALIDADO / CUTOVER PREFLIGHT OK / CLOUD DAILY OPS READY`
- Nombre publico del proyecto: `PythiaxEngine`
- Ruta local historica: `Claude/`
- Decision boundary: desde ahora `PythiaxEngine` en GitHub es la unica fuente de verdad; `Claude/` queda deprecado como proyecto separado y solo se revisa por emergencias criticas de migracion.
- Arquitectura objetivo activa: `GitHub + GitHub Actions + Neon Postgres + GitHub Pages`
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
- integrado `C1 Pro` al build oficial y al publish bridge:
  - `herramientas/_build_c1pro.py`
  - `analisis/generar_tablero_maquina_pensante.py`
  - `infra/publish/dashboard_site.py`
  - `.github/workflows/dashboard-build.yml`
  - `.github/workflows/github-pages-publish.yml`
  - `.github/workflows/production-release.yml`
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
- agregado preflight local de un solo comando para bootstrap + smoke + dashboard + Pages bundle:
  - `infra/cloud/cutover_preflight.py`
  - `docs/cloud/CUTOVER_PREFLIGHT_ONE_SHOT.md`
- agregado bootstrap inverso `target -> SQLite runner` para GitHub Actions:
  - `infra/db/bootstrap_sqlite_from_target.py`
- agregada auditoria reproducible DB vs snapshot/site:
  - `infra/cloud/audit_dashboard_integrity.py`
- agregado workflow diario cloud-first end-to-end:
  - `.github/workflows/cloud-daily-operations.yml`
- documentado el flujo diario cloud-first:
  - `docs/cloud/CLOUD_DAILY_OPERATIONS.md`
- agregado workflow manual de validacion cloud:
  - `.github/workflows/neon-schema-smoke.yml`
- agregado workflow manual one-shot para release remoto y publish opcional:
  - `.github/workflows/production-release.yml`
- documentado setup de secrets:
  - `docs/cloud/GITHUB_SECRETS_SETUP.md`
- documentada la secuencia final de cutover y rollback:
  - `docs/cloud/CUTOVER_DAY_CHECKLIST.md`
- validado el preflight integral contra target SQLite temporal:
  - bootstrap completo de `425022 prices`
  - runtime smoke correcto
  - dashboard build persistido en `pipeline_runs`
  - site bundle listo para Pages
  - `cutover_preflight` persistido en `pipeline_runs`
- completado bootstrap real a `Neon/Postgres` desde la SQLite local:
  - `prices`: `425022`
  - `predictions`: `28055`
  - `outcomes`: `27837`
  - `model_metrics`: `55`
  - `regimes`: `1516`
  - `data_status`: `2`
- validado build real del dashboard contra `Postgres` con `pipeline_runs` persistido
- validado `cutover_preflight --skip-bootstrap` contra `Postgres`:
  - `runtime_smoke.backend = postgresql`
  - site bundle listo en `dist/cutover-preflight-pages`
  - reporte final en `docs/cloud/reports/cutover_preflight_report.json`
- alineado `analisis/preview_c1_pro.html` con el snapshot productivo local
- definido `C1 Pro` como entrypoint productivo del bundle listo para publicar en el site
- integrado `dashboard_integrity_audit` a los workflows de build/publish del dashboard
- corregida una rotura real en `auto_actualizar` para permitir timeout explicito en sync cloud opcional

## Lo que falta inmediatamente

1. Confirmar `DATABASE_URL` real en GitHub.
2. Habilitar `GitHub Pages` via GitHub Actions si todavia no quedo activo.
3. Correr una primera vez `Cloud Daily Operations` por `workflow_dispatch`.
4. Verificar la primera publicacion remota y dejar `shadow mode`.
5. Desacoplar snapshots operativos restantes para que toda la capa visible viva solo de DB.
6. Si se quiere eliminar tambien la compatibilidad `SQLite`, migrar lecturas/escrituras legacy profundas a `Postgres` nativo.

## Bloqueadores conocidos

- hay dependencias legacy fuera del repo:
  - `Machine Winners`
- el motor historico sigue siendo `SQLite-first`, pero ahora ya puede correr
  cloud-first en GitHub Actions bootstrappeando una `SQLite` efimera desde
  `Postgres`; todavia falta eliminar esa capa de compatibilidad si se busca
  una arquitectura puramente `Postgres-native`
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
- el `cutover_preflight` sigue dependiendo de crear la base en Neon y cargar
  `DATABASE_URL`, porque esos pasos viven fuera del repo
- no hay `gh` CLI instalado en esta PC, asi que la activacion remota se apoya
  en la web de GitHub y en workflows ya dejados listos dentro del repo
- `git` dentro de esta carpeta requiere comandos fuera del sandbox para escribir metadata

## Estrategia de rollback

- mientras no exista cutover, `SQLite` local sigue siendo la verdad operativa
- la tarea diaria local no debe apagarse hasta terminar shadow mode
- no se debe eliminar ningun artefacto local durante la fase 1/2
- si `GitHub Pages` falla, el bundle auditable del dashboard sigue quedando disponible como artifact del workflow

## Proximo corte recomendado

`FASE 2: cloud daily operations + shadow mode`

Pasos exactos:

1. verificar secret `DATABASE_URL` en GitHub
2. habilitar `GitHub Pages`
3. correr workflow `Cloud Daily Operations`
4. validar dashboard publico y artifacts
5. mantener `shadow mode` antes de apagar la tarea local
