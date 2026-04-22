# GitHub Secrets Setup

## Objetivo

Definir los secretos minimos para empezar a operar `PythiaxEngine` con una base
cloud en `Neon` y dejar listo el camino hacia `R2` y `Cloudflare Pages`.

## Secreto requerido ahora

- `DATABASE_URL`
  - Debe apuntar a tu base `Neon Postgres`.
  - Este secreto ya habilita:
    - `alembic upgrade head`
    - `RuntimeDB` contra cloud
    - workflow manual `Neon Schema Smoke`

## Secretos recomendados para la siguiente fase

- `R2_BUCKET`
- `R2_ENDPOINT`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `CF_PAGES_PROJECT`
- `PUBLIC_DASHBOARD_BASE_URL`
- `CLOUDFLARE_API_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`

## Orden recomendado

1. Crear la base en `Neon`.
2. Cargar `DATABASE_URL` en GitHub Secrets.
3. Ejecutar el workflow manual `Neon Schema Smoke`.
4. Correr desde tu PC el bootstrap inicial:

```powershell
python -m infra.db.bootstrap_target `
  --target-url "$env:DATABASE_URL" `
  --reset-target `
  --report-path "docs/cloud/reports/sqlite_to_neon_bootstrap.json"
```

5. Volver a correr `Neon Schema Smoke` para validar conteos.
6. Recién después cargar secretos de `R2` y `Cloudflare`.

## Por que el bootstrap inicial es local

La fuente historica `titan.db` vive en tu PC y hoy no está versionada en el
repo. Por eso la carga inicial a `Neon` debe hacerse localmente una sola vez.

Después del bootstrap:

- la PC deja de ser necesaria para servir el dashboard
- la DB cloud pasa a ser el target estable
- el siguiente objetivo es que los jobs cloud escriban directo sobre `Neon`

## Nota sobre el dashboard remoto

La lectura del dashboard ya funciona con backend dual (`SQLite` o `Postgres`),
pero parte de los snapshots operativos todavia vive en carpetas locales no
versionadas como `aprendizaje_operativo/*_runs`.

Eso significa que:

- el schema y la DB cloud ya se pueden validar desde GitHub Actions
- la publicacion 100% cloud del dashboard necesita mover o persistir tambien
  esos snapshots fuera de la PC
