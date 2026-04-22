# ADR-001: Stack Free-Tier Profesional

- Estado: Aceptada
- Fecha: 2026-04-22

## Contexto

El proyecto `PythiaxEngine` hoy opera desde una PC local con un nucleo
historico que todavia conserva nombres internos como `Claude`.

La operacion actual depende de:

- pipeline diario en `herramientas/auto_actualizar.py`
- persistencia principal en `SQLite` (`titan_system/data/titan.db`)
- dashboards HTML/JSON generados como artefactos estaticos
- scheduler local de Windows

El objetivo es migrar a una arquitectura gratis por ahora, pero alineada con
practicas que se consideran estandar en la industria:

- versionado serio del repo
- CI/CD
- base de datos relacional profesional
- backups y artefactos fuera del repo
- deploy reproducible
- trazabilidad de punta a punta

## Decision

Se adopta como arquitectura objetivo inicial:

- `GitHub` repositorio privado como source of truth
- `GitHub Actions` para CI y pipeline batch diario
- `Neon Postgres` como base de datos principal
- `Cloudflare Pages` para publicar el dashboard estatico 24/7
- `Cloudflare R2` para snapshots, backups y auditorias
- `Docker` como formato de ejecucion reproducible

## Motivacion

- `Postgres` da una senal de stack profesional superior a `SQLite`.
- `GitHub Actions` permite automatizacion gratis y muy reconocible en entrevistas.
- El dashboard actual es estatico, por lo que `Cloudflare Pages` aprovecha bien
  el free tier sin forzar un servidor 24/7.
- `R2` evita usar el repo como almacenamiento de snapshots y dumps.
- El proyecto es lo bastante liviano para entrar en este esquema sin pagar.

## Consecuencias

### Positivas

- Se desacopla computo batch de publicacion del dashboard.
- Se gana trazabilidad, versionado, CI y rollback por fases.
- Se deja una base lista para crecer luego a servicios pagos sin reescribir todo.

### Negativas

- La migracion a `Postgres` requiere introducir una capa de acceso compatible
  con ambos motores durante la transicion.
- `GitHub Actions schedule` no ofrece SLA; puede retrasarse o dropearse.
- Los modelos legacy que viven fuera del repo (`Machine Winners`) no son
  reproducibles en nube tal como estan.

## Decisiones derivadas

- Fase 1: no tocar logica del scanner activo.
- Fase 1: renombrar identidad publica y metadata sin forzar un rename total del
  nucleo historico.
- Fase 1: dejar fuera del camino critico cloud a los legacy ML externos.
- Fase 1: preparar el repo y el workflow antes de mover datos productivos.
- Fase 2: migrar de `SQLite` a `Postgres` con validacion y shadow mode.
