# Schema Inventory

- Fecha de inventario: 2026-04-22
- Fuente: `titan_system/data/titan.db`
- Motor actual: `SQLite`
- Motor objetivo: `PostgreSQL`

## Tablas actuales

| Tabla | Filas | Rol |
| --- | ---: | --- |
| `prices` | 424737 | OHLCV historico |
| `predictions` | 28029 | predicciones de scanners/modelos |
| `outcomes` | 27773 | evaluacion de predicciones |
| `model_metrics` | 53 | metricas agregadas por modelo |
| `regimes` | 1515 | regimenes diarios |
| `data_status` | 2 | metadata de frescura |

## Indices actuales

### `prices`

- PK compuesta: `(ticker, date)`
- `idx_prices_ticker`
- `idx_prices_date`

### `predictions`

- PK: `id`
- unique: `(model_name, ticker, prediction_date, target_date)`
- `idx_pred_model`
- `idx_pred_date`
- `idx_pred_target`

### `outcomes`

- PK: `id`
- unique: `prediction_id`

### `model_metrics`

- PK: `id`
- unique: `(model_name, period_start, period_end)`

### `regimes`

- PK: `date`

### `data_status`

- PK: `key`

## Touchpoints de persistencia

El proyecto todavia no esta abstraido en una sola capa de datos.

### Capa principal

- `titan_system/core/database.py`

### Uso directo de `self.db.conn.execute(...)`

- `herramientas/aprendizaje_operativo_v11.py`
- `herramientas/aprendizaje_operativo_v12.py`
- `herramientas/aprendizaje_operativo_v13.py`
- `herramientas/aprendizaje_operativo_observado_base.py`
- `herramientas/aprendizaje_operativo_legacy_ml_base.py`

### Uso directo de `sqlite3.connect(...)`

- `herramientas/auto_actualizar.py`
- `herramientas/auditoria_integral_claude.py`
- `herramientas/competencia_modelos.py`
- `analisis/generar_tablero_maquina_pensante.py`

## Gap principal para migrar bien

Hoy el proyecto mezcla:

- `TitanDB` como wrapper
- `sqlite3` directo
- SQL crudo distribuido
- `pandas.read_sql_query(...)` contra conexiones SQLite

La migracion profesional no debe reemplazar `SQLite` de golpe. Debe introducir:

1. configuracion central de engine
2. schema versionado con `Alembic`
3. capa dual `SQLite/Postgres`
4. migracion de datos reproducible
5. shadow mode antes del cutover

## Schema objetivo inicial en Postgres

El scaffolding agregado en este corte replica estas tablas:

- `prices`
- `predictions`
- `outcomes`
- `model_metrics`
- `regimes`
- `data_status`

Y agrega una tabla nueva de operacion profesional:

- `pipeline_runs`

## Por que agregar `pipeline_runs`

Porque hoy la trazabilidad del pipeline vive sobre todo en archivos `.txt/.json`.
En entorno cloud conviene tener un ledger transaccional con:

- `run_id`
- `pipeline_name`
- `run_date`
- `status`
- `commit_sha`
- `scanner activo`
- `fecha objetivo de mercado`
- `ultima fecha real cargada`
- manifiesto de artefactos

Eso mejora:

- auditoria
- debugging
- observabilidad
- recuperacion ante fallos
- explicacion del flujo en entrevistas tecnicas

