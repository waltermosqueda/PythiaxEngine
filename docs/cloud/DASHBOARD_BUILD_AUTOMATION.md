# Dashboard Build Automation

## Objetivo

Generar el dashboard de `PythiaxEngine` desde GitHub Actions usando la base cloud
como fuente de verdad, sin depender de una PC encendida.

## Workflow

- archivo: `.github/workflows/dashboard-build.yml`
- disparadores:
  - `workflow_dispatch`
  - `schedule`: `17 03 * * 2-6` UTC
- secret requerido:
  - `DATABASE_URL`

## Artefactos generados

El workflow construye y sube como artifact:

- `dashboards/maquina_pensante/tablero_maquina_pensante_snapshot.json`
- `dashboards/maquina_pensante/tablero_maquina_pensante.html`
- `dashboards/maquina_pensante/tablero_maquina_pensante_executive.html`
- `dashboards/maquina_pensante/tablero_maquina_pensante_lab.html`
- `dashboards/maquina_pensante/tablero_maquina_pensante_artifact_manifest.json`

## Metadata de build

El snapshot ahora incluye un bloque `build` con:

- `build_source`
- `db_backend`
- `commit_sha`
- `commit_short`
- `run_id`
- `run_attempt`
- `workflow`
- `actor`

Eso permite saber exactamente que commit y que corrida produjeron cada bundle.

## Manifest auditable

El archivo `tablero_maquina_pensante_artifact_manifest.json` incluye:

- `generated_at`
- metadata de build
- `artifact_count`
- lista de artefactos con:
  - `relative_path`
  - `size_bytes`
  - `sha256`

Con eso el bundle ya tiene una cadena minima de trazabilidad y verificacion de
integridad antes de conectarlo a un hosting publico como Cloudflare Pages.
