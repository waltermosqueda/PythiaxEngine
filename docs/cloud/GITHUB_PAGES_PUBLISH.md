# GitHub Pages Publish

## Objetivo

Tener una publicacion web gratuita y 24/7 del dashboard sin depender de una PC
encendida, usando `GitHub Pages` como hosting puente de costo cero.

## Por que existe esta fase

La arquitectura objetivo de mas largo plazo sigue siendo:

- `GitHub + GitHub Actions + Supabase Postgres + Cloudflare Pages + R2`

Pero para una fase gratis, simple y presentable en entrevista, `GitHub Pages`
permite publicar el dashboard estatico desde Actions sin agregar secretos de
hosting ni costos extra.

## Workflow

- archivo: `.github/workflows/github-pages-publish.yml`
- disparadores:
  - `push` a `main` cuando el cambio toca codigo/pipeline relevante
  - `workflow_dispatch`
- secreto requerido:
  - `DATABASE_URL`

## Requisitos fuera del repo

1. En GitHub, abrir `Settings > Pages`.
2. En `Build and deployment`, elegir `Source: GitHub Actions`.
3. Confirmar que el repo tenga cargado el secret `DATABASE_URL`.

## Bundle publicado

El workflow:

1. genera el dashboard desde `Supabase/Postgres`
2. arma un site bundle para Pages
3. publica ese bundle

Archivos principales publicados:

- `index.html`
- `preview_c1_pro.html`
- `tablero_maquina_pensante.html`
- `tablero_maquina_pensante_executive.html`
- `tablero_maquina_pensante_lab.html`
- `tablero_maquina_pensante_snapshot.json`
- `tablero_maquina_pensante_artifact_manifest.json`
- `site_bundle_manifest.json`

El bundle preparado por este flujo deja `index.html` como alias byte a byte de
`preview_c1_pro.html`, para que `C1 Pro` sea la vista productiva principal
en cloud sin perder la navegacion hacia las variantes clasica, executive y lab.

Ese cambio queda visible en el site publico recien despues de una corrida
exitosa de `GitHub Pages Publish` o `Production Release` con deploy habilitado.

## Trazabilidad

La publicacion conserva:

- metadata de build en el snapshot
- manifest de artefactos del dashboard
- manifest del site bundle para Pages

Eso deja un camino auditable desde:

- corrida de GitHub Actions
- commit exacto
- bundle generado
- sitio publicado

Ademas, despues del deploy el workflow registra una corrida separada en
`pipeline_runs` con pipeline `github_pages_publish`, incluyendo `page_url`,
archivos publicados y referencia al `dashboard_build` que genero el bundle.

## Nota estrategica

`GitHub Pages` en esta fase funciona como hosting puente gratis.

Cuando la parte cloud quede mas madura, el bundle estatico ya va a estar
preparado para mover la publicacion a `Cloudflare Pages` con muy pocos cambios.
