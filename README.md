# PythiaxEngine

**Motor de investigación cuantitativa de trading** — competencia live de forward-testing entre modelos de predicción basados en reglas y modelos ML sobre acciones del mercado estadounidense.

**Dashboard en vivo:** https://waltermosqueda.github.io/PythiaxEngine/

---

## Qué hace

PythiaxEngine ingesta datos de mercado diarios de 178 acciones de EE.UU., ejecuta modelos de predicción en competencia, evalúa resultados en múltiples períodos de tenencia y publica un ranking de performance transparente actualizado a diario.

La tesis central: poner modelos basados en reglas y modelos ML en competencia directa y honesta, con criterios de evaluación uniformes, datos compartidos y sin cherry-picking de ventanas.

---

## Arquitectura

```
Datos de mercado (yfinance)
        |
        v
PostgreSQL (TitanDB)          <-- fuente única de verdad
        |
        |-- Familia INVERTIR (scanners basados en reglas V8-V13)
        |       |-- señales RSI / SMA / Volumen / Momentum
        |
        |-- Familia Legacy ML (modelos ensemble)
                |-- V37, V39, V39FULL, V97, BRAIN_V11, BRAIN_V10
                        |-- XGBoost, HistGradientBoosting, RF/ET, LR
                                |-- etiquetas Triple Barrier, Walk-Forward CV
        |
        v
Evaluador de Outcomes (períodos D1 / D4 / D5 / D7 / D10 / D15)
        |
        v
Generador de Dashboard --> analisis/preview_c1_pro.html
        |
        v
GitHub Pages  (estático, público 24/7)
```

---

## Competencia de Modelos — 

---

## Stack Tecnológico

| Capa | Tecnología |
|------|------------|
| Lenguaje | Python 3.14 |
| Base de datos | PostgreSQL 16 (Docker local, Supabase cloud) |
| ML | XGBoost 3.2, scikit-learn (HistGBC, RF, ET, LR) |
| Pipeline | GitHub Actions (batch diario) |
| Dashboard | HTML/CSS/JS estático via GitHub Pages |
| Versionado | Git, GitHub |
| Contenedores | Docker, docker-compose |

---

## Setup Local

```bash
# 1. Levantar la base de datos
docker-compose up -d

# 2. Instalar dependencias
pip install -r requirements-prod.txt

# 3. Correr el pipeline diario
python herramientas/auto_actualizar.py

# 4. Actualizar el dashboard
python herramientas/refrescar_datos_dashboard.py
```

Copiar `.env.example` a `.env` y configurar `DATABASE_URL` antes de ejecutar.

---

## Estructura del Repositorio

```
PythiaxEngine/
|-- SCANNER/                  # Scanners basados en reglas promovidos (invertir_vN.py)
|-- ml_investigacion/         # Investigación de modelos ML (v22, v23/brain_v10, ...)
|-- herramientas/             # Adaptadores operacionales y pipeline diario
|-- titan_system/             # Infraestructura core (DB, cargador de datos, modelos)
|-- backtests/                # Investigación histórica y estudios walk-forward
|-- analisis/                 # HTML de salida del dashboard (GitHub Pages)
|-- aprendizaje_operativo/    # Registro de modelos (JSON) y config de competencia
|-- infra/                    # Migraciones DB (Alembic), capas de compatibilidad
|-- tests/                    # Suite de tests automatizados (CI)
|-- docs/                     # Documentación de arquitectura y ADRs
|-- bitacora/                 # Log de sesión
|-- ESTADO_ACTUAL.md          # Estado live para handoff (leer al inicio de sesión)
|-- AGENTS.md                 # Política operacional para agentes IA
`-- CLAUDE.md                 # Reglas de código y protocolos de decisión
```

---

## Principios de Diseño

1. **Competencia justa** — todos los modelos evaluados en la misma ventana, el mismo universo y las mismas reglas de entrada/salida.
2. **Sin look-ahead bias** — las señales se generan solo con datos disponibles al momento de la predicción.
3. **Validación walk-forward** — los modelos ML reentrenan semanalmente; sin split estático de train/test.
4. **Benchmark de simplicidad** — scanner de 4 reglas (Sharpe 14) vs ML de 40 features (Sharpe -0.65). La complejidad debe ganarse su lugar.
5. **Auditabilidad total** — cada predicción almacenada con model_name, ticker, prediction_date, target_date y outcome.

---

## Documentación

- [Arquitectura](docs/ARCHITECTURE.md)
- [Catálogo de Modelos](docs/MODELS.md)
- [Estructura del Proyecto](docs/ESTRUCTURA.md)
- [Architecture Decision Records](docs/cloud/README.md)
- [Bitácora de Sesión](bitacora/BITACORA.md)
- [Estado Actual / Handoff](ESTADO_ACTUAL.md)
