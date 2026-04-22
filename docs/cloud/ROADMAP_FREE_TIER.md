# Roadmap Free-Tier Profesional

## Objetivo

Llevar el proyecto a una operacion siempre accesible y con mejor señal
profesional, sin pagar por ahora y sin reescribir el negocio de golpe.

## Arquitectura objetivo

```text
GitHub (repo privado)
  ├─ CI: smoke tests, sintaxis, checks de PR
  ├─ CD batch: workflow diario / manual
  │    ├─ actualiza datos
  │    ├─ valida integridad
  │    ├─ corre aprendizaje + scanner + gestor
  │    ├─ genera snapshot del dashboard
  │    ├─ backup a R2
  │    └─ publica dashboard
  ├─ Neon Postgres
  │    ├─ prices
  │    ├─ predictions
  │    ├─ outcomes
  │    ├─ model_metrics
  │    └─ pipeline_runs
  ├─ Cloudflare R2
  │    ├─ dumps de DB
  │    ├─ snapshot JSON
  │    └─ auditorias y reportes
  └─ Cloudflare Pages
       └─ dashboard estatico publico
```

## Principios de migracion

1. No mezclar cambios de estrategia con cambios de infraestructura.
2. Un corte pequeno y reversible por fase.
3. El estado debe quedar retomable por otro agente en cualquier momento.
4. Todo workflow nuevo debe ser idempotente.
5. El dashboard publico solo debe publicar el ultimo snapshot valido.

## Fases

### Fase 0: Bootstrap del repo

- agregar `.gitignore`
- agregar `pyproject.toml`
- agregar archivos de dependencias
- agregar `Dockerfile`
- agregar `CI` basica
- documentar ADR y estado vivo

### Fase 1: Gobierno del repositorio

- inicializar `git`
- crear repo privado en GitHub
- definir ramas (`main`, feature branches)
- configurar secrets del repo
- subir el primer baseline etiquetado

### Fase 2: Persistencia profesional

- mapear schema actual de `SQLite`
- introducir `SQLAlchemy + Alembic`
- crear schema `Postgres`
- migrar datos historicos
- agregar tabla `pipeline_runs`
- mantener `SQLite` como fallback temporal durante el shadow mode

### Fase 3: Pipeline cloud

- separar el pipeline critico de los legacy externos
- crear workflow diario en `GitHub Actions`
- generar artefactos firmados por `run_id`, `date`, `commit_sha`
- subir backups y reportes a `R2`

### Fase 4: Dashboard 24/7

- desacoplar snapshot/publicacion del repo
- publicar HTML/JSON en `Cloudflare Pages`
- mostrar metadata operacional visible:
  - fecha de datos
  - commit
  - estado de auditoria
  - run_id

### Fase 5: Shadow mode y cutover

- correr local + cloud en paralelo varias ruedas habiles
- comparar:
  - fecha maxima de datos
  - cantidad de señales
  - snapshots
  - auditorias
- apagar la tarea local solo cuando el paralelo sea consistente

## Fuera de alcance en la primera ola

- Kubernetes
- microservicios
- reescritura del scanner activo
- legacy ML externos como dependencia critica del pipeline cloud

## Riesgos conocidos

- `GitHub Actions schedule` no es hard real-time.
- `Neon Free` sigue siendo free tier.
- El proyecto hoy tiene consultas `sqlite3` directas y no solo `TitanDB`.
- Los wrappers legacy dependen de paths Windows fuera del repo.

## Criterio de exito

La migracion fase 1/2 se considera bien encaminada cuando:

- el repo esta versionado y con CI basica
- existe un baseline limpio para retomar trabajo
- la ruta a `Postgres` esta definida y documentada
- el dashboard queda listo para ser publicado sin depender de la PC encendida

