# Cloud Daily Operations

Objetivo: correr el flujo diario completo sin depender de una PC local,
manteniendo compatibilidad con el motor legacy que hoy sigue siendo
`SQLite-first` por dentro.

Decision operativa actual: el target cloud pasa a ser `Supabase Postgres`.

Workflow principal:

- `.github/workflows/cloud-daily-operations.yml`

Que hace en cada corrida:

1. aplica `alembic upgrade head` sobre `DATABASE_URL`
2. ejecuta `herramientas/auto_actualizar.py --skip-dashboard-refresh`
3. decide si realmente hace falta republicar mirando `latest_prices_date` y snapshots nuevos posteriores al ultimo publish exitoso
4. solo si hace falta, genera el dashboard
5. arma el site bundle para `GitHub Pages`
6. corre auditoria de integridad DB vs snapshot/site
7. publica el site y registra el deploy en `pipeline_runs`

Secretos y precondiciones:

- `DATABASE_URL` configurado en GitHub
- `Settings > Pages > Source: GitHub Actions`

Reportes clave:

- `docs/cloud/reports/target_to_sqlite_bootstrap.json`
- `docs/cloud/reports/dashboard_integrity_audit.json`

Lectura operativa:

- esto ya elimina la dependencia de la PC local para la corrida diaria
- todavia no elimina la capa de compatibilidad `SQLite` interna del motor
- el refresh pesado del dashboard ya no corre en todas las vueltas del cron: ahora solo corre cuando hay evidencia nueva para publicar, lo que baja consumo de DB y egress en `Supabase Free`
- el siguiente salto arquitectonico, si se busca simplificar mas, es reemplazar
  esa compatibilidad por escrituras/lecturas nativas sobre `Postgres`
