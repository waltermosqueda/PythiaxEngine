# Cloud Migration Docs

Esta carpeta concentra la documentacion de la migracion a una arquitectura
free-tier, profesional y retomable por otros agentes.

- Identidad publica del proyecto: `PythiaxEngine`
- Repo objetivo: `https://github.com/waltermosqueda/PythiaxEngine`
- Decision operativa: toda mejora, analisis o correccion va contra `PythiaxEngine` en GitHub; la carpeta local `Claude/` queda solo como nombre historico del working copy.
- Nota: durante la transicion todavia existen nombres internos historicos como
  `Claude`, `titan_system` y `herramientas` para no romper compatibilidad.

Archivos clave:

- `ADR-001-free-professional-stack.md`: decision de arquitectura objetivo.
- `ROADMAP_FREE_TIER.md`: roadmap por fases y criterios de corte.
- `MIGRATION_STATUS.md`: estado vivo de la migracion, proximos pasos y rollback.
- `SCHEMA_INVENTORY.md`: inventario del schema actual y objetivo Postgres.
- `SQLITE_TO_POSTGRES_RUNBOOK.md`: procedimiento controlado para cargar Neon desde SQLite.
- `CLOUD_DAILY_OPERATIONS.md`: flujo diario cloud-first sobre GitHub Actions.
- `GITHUB_SECRETS_SETUP.md`: secretos y orden recomendado para activar workflows cloud.
- `DASHBOARD_BUILD_AUTOMATION.md`: build remoto auditable del dashboard.
- `GITHUB_PAGES_PUBLISH.md`: publicacion gratis del dashboard via GitHub Pages.
- `CUTOVER_PREFLIGHT_ONE_SHOT.md`: preflight local de un solo comando antes del salto real.
- `CUTOVER_DAY_CHECKLIST.md`: secuencia final de produccion, validacion y rollback.
