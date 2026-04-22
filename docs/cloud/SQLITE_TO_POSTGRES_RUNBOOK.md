# SQLite To Postgres Runbook

## Objetivo

Cargar la base historica actual desde `SQLite` hacia `Neon Postgres` de forma
reproducible, controlada y retomable.

Importante: esta primera carga conviene correrla localmente porque la fuente
`titan.db` vive en tu PC y no forma parte del repositorio.

## Principios

1. `SQLite` sigue siendo la fuente operativa hasta terminar shadow mode.
2. La primera carga a `Neon` no debe mezclar cambios de negocio.
3. Antes de migrar datos se debe crear el schema con `Alembic`.
4. Cada corrida debe dejar un reporte JSON con conteos por tabla.

## Precondiciones

- `DATABASE_URL` apuntando a la base `Neon` correcta.
- Dependencias `cloud` instaladas.
- Schema creado con:

```powershell
alembic upgrade head
```

## Smoke local opcional

Para validar la herramienta sin tocar Neon:

```powershell
python -m infra.db.migrate_sqlite_to_postgres `
  --target-url "sqlite:///./.cache/migration-smoke/target.db" `
  --allow-sqlite-target `
  --ensure-schema `
  --reset-target `
  --report-path ".cache/migration-smoke/report.json"
```

## Primera carga a Neon

```powershell
python -m infra.db.bootstrap_target `
  --target-url "$env:DATABASE_URL" `
  --reset-target `
  --report-path "docs/cloud/reports/sqlite_to_neon_bootstrap.json"
```

## Recomendacion operativa

- Usar `--ensure-schema` solo para smoke tests locales.
- En Neon real, preferir el wrapper `bootstrap_target`, que corre `Alembic`
  antes de la carga de datos.
- Guardar cada reporte para auditoria y comparacion entre corridas.

## Verificaciones minimas

1. Confirmar que el proceso termina con exit code `0`.
2. Revisar el reporte JSON y validar que `source_rows == target_rows`.
3. Chequear especialmente:
   - `prices`
   - `predictions`
   - `outcomes`
   - `model_metrics`
   - `regimes`
   - `data_status`
4. Recordar que `pipeline_runs` puede salir `SKIP` si todavia no existe en la fuente SQLite.

## Rollback

- Si la carga falla, no tocar la operacion local.
- Corregir schema o credenciales y rerunear con `--reset-target`.
- No apagar la tarea diaria local hasta completar shadow mode y validacion funcional.
