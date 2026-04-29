# GitHub Secrets Setup

## Objetivo

Definir los secretos minimos para empezar a operar `PythiaxEngine` con una base
cloud en `Supabase` y dejar listo el camino hacia `R2` y `Cloudflare Pages`.

## Secreto requerido ahora

- `DATABASE_URL`
  - Debe apuntar a tu base `Supabase Postgres`.
  - Para GitHub Actions usa `Session pooler` de Supabase, no `Direct connection`.
  - `Direct connection` usa IPv6 por defecto y en GitHub Actions suele fallar con `Network is unreachable`.
  - No usar `Transaction pooler` (`:6543`) para este repo porque `alembic upgrade head` y los clientes persistentes necesitan `Session pooler` (`:5432`).
  - Debe incluir `sslmode=require` si Supabase no lo agrega automaticamente.
  - Este secreto ya habilita:
    - `alembic upgrade head`
    - `RuntimeDB` contra cloud
    - workflow manual `Cloud Postgres Smoke`
    - workflow `Dashboard Build`
    - workflow `GitHub Pages Publish`

## Paso manual que te toca ahora

Crear la cuenta/proyecto en `Supabase` y copiar el `DATABASE_URL`.

### Instrucciones exactas

1. Entrar a `https://supabase.com/dashboard` y crear cuenta.
2. Crear un proyecto nuevo.
3. Usar un nombre simple y estable, por ejemplo `pythiaxengine-prod`.
4. Elegir una region cercana a tu operacion. Si dudas, prioriza la mas cercana disponible en Sudamerica o East US.
5. Definir una password fuerte para la base y guardarla.
6. Esperar a que el proyecto termine de aprovisionarse.
7. Ir a `Project Settings > Database > Connection string > URI`.
8. Elegir `Session pooler`.
9. Copiar la URL completa y reemplazar `[YOUR-PASSWORD]` por tu password real si Supabase la deja templada.
10. Confirmar que el host termine en `pooler.supabase.com` y que el puerto sea `5432`.
11. Confirmar que la URL termine incluyendo `?sslmode=require` o agregarlo manualmente.
12. El usuario puede venir como `postgres.<project-ref>`; eso es normal en `Session pooler`.
13. En GitHub, abrir `Settings > Secrets and variables > Actions`.
14. Crear o actualizar el secret `DATABASE_URL` con esa URL.

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

1. Crear la cuenta/proyecto en `Supabase`.
2. Cargar `DATABASE_URL` en GitHub Secrets.
3. Ejecutar el workflow manual `Cloud Postgres Smoke`.
4. Correr desde tu PC el bootstrap inicial:

```powershell
python -m infra.db.bootstrap_target `
  --target-url "$env:DATABASE_URL" `
  --reset-target `
  --report-path "docs/cloud/reports/sqlite_to_supabase_bootstrap.json"
```

Alternativa local mas simple:

1. Crear un archivo `.env` en la raiz del repo.
2. Copiar ahi tu `DATABASE_URL` real.
3. Correr el mismo comando sin exportar nada en PowerShell.

Si tu PC tambien esta en una red sin IPv6, usa el mismo `Session pooler` localmente para evitar el mismo fallo.

5. Volver a correr `Cloud Postgres Smoke` para validar conteos.
6. Habilitar `Settings > Pages > Source: GitHub Actions`.
7. Ejecutar `Dashboard Build`.
8. Ejecutar `GitHub Pages Publish`.
9. Recien despues cargar secretos de `R2` y `Cloudflare`.

## Por que el bootstrap inicial es local

La fuente historica `titan.db` vive en tu PC y hoy no esta versionada en el
repo. Por eso la carga inicial a `Supabase` debe hacerse localmente una sola vez.

Despues del bootstrap:

- la PC deja de ser necesaria para servir el dashboard
- la DB cloud pasa a ser el target estable
- el siguiente objetivo es que los jobs cloud escriban directo sobre `Supabase`

## Nota sobre Supabase Free

- Supabase Free pausa proyectos tras 1 semana de inactividad.
- Este repo ya deja workflows programados para evitar que el proyecto quede dormido si la operacion diaria sigue activa.
- Lo importante para no repetir el problema de Neon no es solo el proveedor: tambien es no gastar egress de mas. Por eso el pipeline cloud ahora difiere el rebuild pesado del dashboard hasta confirmar que realmente hay algo nuevo para publicar.

## Nota sobre el dashboard remoto

La lectura del dashboard ya funciona con backend dual (`SQLite` o `Postgres`),
pero parte de los snapshots operativos todavia vive en carpetas locales no
versionadas como `aprendizaje_operativo/*_runs`.

Eso significa que:

- el schema y la DB cloud ya se pueden validar desde GitHub Actions
- ya existe una ruta gratis de publicacion con `GitHub Pages` para el dashboard
  estatico principal
- la publicacion cloud mas completa y flexible a futuro sigue siendo `Cloudflare Pages`
