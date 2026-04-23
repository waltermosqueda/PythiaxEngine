# Cutover Preflight One Shot

## Objetivo

Reducir el salto real a cloud a una secuencia local controlada y repetible, con
un solo comando que haga:

1. bootstrap de `SQLite` hacia el target
2. smoke de conteos y backend
3. build real del dashboard contra el target
4. armado del site bundle para Pages
5. reporte JSON final auditable

## Comando principal

```powershell
python -m infra.cloud.cutover_preflight `
  --target-url "$env:DATABASE_URL" `
  --reset-target `
  --report-path "docs/cloud/reports/cutover_preflight_report.json"
```

## Que genera

- `docs/cloud/reports/sqlite_to_target_bootstrap.json`
- `docs/cloud/reports/cutover_preflight_report.json`
- bundle del dashboard en `dashboards/maquina_pensante/`
- site bundle listo para Pages en `dist/cutover-preflight-pages/`

## Uso de smoke local

Si queres probar todo el flujo sin tocar Neon:

```powershell
python -m infra.cloud.cutover_preflight `
  --target-url "sqlite:///./.cache/cutover-smoke/target.db" `
  --allow-sqlite-target `
  --reset-target `
  --report-path ".cache/cutover-smoke/cutover_preflight_report.json"
```

## Resultado esperado

El reporte final deja:

- resumen del bootstrap
- conteos del runtime target
- metadata y ledger del dashboard build
- site manifest para Pages
- ledger del propio `cutover_preflight`

## Estado validado

El `2026-04-23` el smoke local completo fue validado contra un target
`SQLite` temporal con estos resultados:

- `prices`: `425022`
- `predictions`: `28055`
- `outcomes`: `27837`
- `model_metrics`: `55`
- `regimes`: `1516`
- `data_status`: `2`
- `dashboard_build`: persistido en `pipeline_runs`
- `cutover_preflight`: persistido en `pipeline_runs`

## Nota operativa

Este preflight no publica todavia el sitio en GitHub Pages ni crea la base en
Neon. Su objetivo es dejar el target listo y validado localmente antes de los
pasos finales en GitHub.
