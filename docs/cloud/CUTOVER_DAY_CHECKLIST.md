# Cutover Day Checklist

## Objetivo

Cerrar el salto real a produccion con la menor cantidad posible de pasos
manuales, manteniendo rollback claro y evidencia auditable.

## Prerrequisitos

- repo remoto sincronizado en `main`
- secret `DATABASE_URL` cargado en GitHub
- `Neon` creado y accesible
- `GitHub Pages` habilitado en `Settings > Pages > Source: GitHub Actions`
- tarea local actual todavia encendida como red de seguridad

## Orden recomendado

1. Exportar `DATABASE_URL` en tu PC para la sesion de cutover.
2. Correr el preflight local one-shot:

```powershell
python -m infra.cloud.cutover_preflight `
  --target-url "$env:DATABASE_URL" `
  --reset-target `
  --report-path "docs/cloud/reports/cutover_preflight_report.json"
```

3. Revisar que el reporte final deje:
   - `runtime_smoke.backend = postgresql`
   - conteos coherentes
   - `dashboard.ledger.persisted = true`
   - `cutover_ledger.persisted = true`
4. En GitHub correr `Production Release` con `deploy_pages=true`.
5. Verificar:
   - artifact `pythiax-production-release-<run_id>`
   - workflow verde
   - deploy exitoso a Pages
   - dashboard accesible publicamente
6. Recien despues iniciar un `shadow mode` corto comparando local vs cloud.

## Criterios de exito

- `Neon Schema Smoke` o `Production Release` pasan sin errores
- el dashboard remoto muestra datos frescos
- `pipeline_runs` registra `dashboard_build`, `github_pages_publish` y
  `cutover_preflight`
- el `site_bundle_manifest.json` existe y coincide con el snapshot servido

## Rollback

- no apagar la tarea local hasta completar el shadow mode
- si el workflow remoto falla, mantener `SQLite` local como fuente operativa
- si Pages publica mal, usar el artifact del workflow como ultimo bundle valido
- si Neon recibe datos inconsistentes, recrear el target y repetir
  `cutover_preflight --reset-target`
