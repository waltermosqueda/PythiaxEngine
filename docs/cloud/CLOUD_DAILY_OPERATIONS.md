# Cloud Daily Operations

Objetivo: correr el flujo diario completo sin depender de una PC local,
manteniendo compatibilidad con el motor legacy que hoy sigue siendo
`SQLite-first` por dentro.

Workflow principal:

- `.github/workflows/cloud-daily-operations.yml`

Que hace en cada corrida:

1. aplica `alembic upgrade head` sobre `DATABASE_URL`
2. bootstrappea una `SQLite` runner-local desde `Postgres`
3. ejecuta `herramientas/auto_actualizar.py --force-pipeline`
4. sincroniza resultados a `Postgres`
5. genera el dashboard
6. arma el site bundle para `GitHub Pages`
7. corre auditoria de integridad DB vs snapshot/site
8. publica el site y registra el deploy en `pipeline_runs`

Secretos y precondiciones:

- `DATABASE_URL` configurado en GitHub
- `Settings > Pages > Source: GitHub Actions`

Reportes clave:

- `docs/cloud/reports/target_to_sqlite_bootstrap.json`
- `docs/cloud/reports/dashboard_integrity_audit.json`

Lectura operativa:

- esto ya elimina la dependencia de la PC local para la corrida diaria
- todavia no elimina la capa de compatibilidad `SQLite` interna del motor
- el siguiente salto arquitectonico, si se busca simplificar mas, es reemplazar
  esa compatibilidad por escrituras/lecturas nativas sobre `Postgres`
