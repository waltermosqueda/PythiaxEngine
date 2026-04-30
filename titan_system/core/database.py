"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TITAN SYSTEM — Módulo de Base de Datos (database.py)                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  CONCEPTOS CLAVE PARA APRENDER:                                             ║
║                                                                              ║
║  1. SQL (Structured Query Language):                                         ║
║     Es el idioma universal para hablar con bases de datos.                   ║
║     Los 4 comandos fundamentales son:                                        ║
║       CREATE TABLE → crea una tabla (como una hoja de Excel)                ║
║       INSERT INTO  → agrega filas de datos                                  ║
║       SELECT       → consulta/busca datos                                   ║
║       UPDATE       → modifica datos existentes                              ║
║                                                                              ║
║  2. Tablas:                                                                  ║
║     Una base de datos tiene TABLAS. Cada tabla es como una hoja de Excel:   ║
║     - Tiene COLUMNAS (campos) con un tipo de dato (texto, número, fecha)    ║
║     - Tiene FILAS (registros) que son los datos en sí                       ║
║                                                                              ║
║  3. Primary Key (Clave Primaria):                                            ║
║     Es la columna (o combinación de columnas) que identifica UNICAMENTE     ║
║     cada fila. Como un DNI para cada registro. No puede repetirse.          ║
║     Ejemplo: (ticker='AAPL', date='2024-01-15') es único — AAPL solo       ║
║     tiene UN precio de cierre para ese día.                                  ║
║                                                                              ║
║  4. Index (Índice):                                                          ║
║     Es como el índice de un libro — permite encontrar datos rápido          ║
║     sin tener que recorrer toda la tabla fila por fila.                      ║
║     Sin índice: buscar entre 1M de filas = recorrer 1M de filas            ║
║     Con índice: buscar entre 1M de filas = ~20 comparaciones (log2)         ║
║                                                                              ║
║  5. ORM vs SQL directo:                                                      ║
║     ORM (como SQLAlchemy) te deja escribir Python en vez de SQL.            ║
║     Nosotros usamos SQL DIRECTO porque:                                      ║
║     a) Aprendés SQL real (te sirve para entrevistas de trabajo)             ║
║     b) Es más eficiente para operaciones masivas (bulk insert)              ║
║     c) Tenés control total sobre lo que pasa                                ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import json
import threading
from datetime import datetime, date
from typing import Optional, List, Dict, Any
import pandas as pd
import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, OperationalError

from infra.db.config import get_database_url, get_sqlite_fallback_path
from infra.db.runtime import adapt_qmark_sql
from infra.db.titandb_compat import create_titandb_compat_connection

# ── Cache en proceso: evita re-fetchar los mismos precios/tickers N veces ──
# Vive mientras dure el proceso (cada CI run es un proceso nuevo → sin stale).
_prices_cache: dict[tuple, pd.DataFrame] = {}
_tickers_cache: list[str] | None = None
_db_cache_lock = threading.Lock()


def clear_db_process_cache() -> None:
    """Limpia el cache en proceso. Útil para tests o runs en loop."""
    global _tickers_cache
    with _db_cache_lock:
        _prices_cache.clear()
        _tickers_cache = None


class TitanDB:
    """
    Clase principal para manejar la base de datos del sistema TITAN.

    ¿QUÉ ES UNA CLASE?
    -------------------
    Una clase es un "molde" para crear objetos. Pensá en:
    - Clase = plano de una casa
    - Objeto = la casa construida

    Esta clase TitanDB es el plano. Cuando hacemos:
        db = TitanDB()
    Creamos un OBJETO 'db' que puede guardar y buscar datos.

    ¿POR QUÉ USAMOS UNA CLASE Y NO FUNCIONES SUELTAS?
    ---------------------------------------------------
    Porque la conexión a la base de datos es un "estado" que necesitamos
    mantener abierto mientras trabajamos. La clase encapsula ese estado.
    Es como abrir un archivo de Excel: lo abrís UNA vez, hacés muchas
    operaciones, y lo cerrás al final. No lo abrís y cerrás cada vez.

    PATRÓN "CONTEXT MANAGER" (with statement):
    -------------------------------------------
    Usamos 'with TitanDB() as db:' que automáticamente:
    1. Abre la conexión al crear el objeto
    2. Cierra la conexión al salir del bloque 'with'
    Esto GARANTIZA que la conexión se cierre incluso si hay un error.
    Es un patrón MUY usado en Python y te lo van a preguntar en entrevistas.
    """

    # La ruta donde se guarda el archivo de la base de datos
    # os.path.dirname(__file__) = la carpeta donde está ESTE archivo .py
    # Subimos 1 nivel (..) y entramos a 'data/'
    DEFAULT_DB_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),  # /core/
        '..',                                         # /titan_system/
        'data',                                       # /titan_system/data/
        'titan.db'                                    # /titan_system/data/titan.db
    )

    def __init__(self, db_path: Optional[str] = None):
        """
        Constructor — se ejecuta cuando creás el objeto: db = TitanDB()

        Parámetros:
        -----------
        db_path : str, opcional
            Ruta al archivo .db. Si no se pasa, usa la ruta por defecto.

        CONCEPTO — Type Hints (las anotaciones de tipo):
        ------------------------------------------------
        'db_path: Optional[str] = None' significa:
        - db_path es un string (str)
        - Optional = puede ser None (no se pasa nada)
        - = None = si no se pasa, el valor por defecto es None

        Los type hints NO hacen nada en runtime (Python los ignora),
        pero son MUY útiles para:
        1. Documentar qué espera cada función
        2. IDEs como VS Code te dan autocompletado
        3. Herramientas como mypy detectan errores antes de correr el código
        4. En entrevistas, demuestran que escribís código profesional
        """
        self._engine = None
        self.database_url = ""
        self.backend_name = "sqlite"
        self.using_sqlalchemy_compat = False

        if db_path is not None:
            self.db_path = str(os.path.abspath(db_path))
            self.database_url = f"sqlite:///{self.db_path.replace(os.sep, '/')}"
            self.backend_name = "sqlite"
        else:
            self.database_url = get_database_url()
            self.backend_name = make_url(self.database_url).get_backend_name()
            self.db_path = str(get_sqlite_fallback_path())

        force_sqlalchemy_compat = os.getenv("TITANDB_FORCE_SQLALCHEMY_COMPAT", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        if self.backend_name == "sqlite" and not force_sqlalchemy_compat:
            self._connect_sqlite_native()
        else:
            self._connect_runtime_backend()

    def _connect_sqlite_native(self):
        import sqlite3

        self.db_path = str(os.path.abspath(self.db_path))
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _connect_runtime_backend(self):
        self._engine, self.conn = create_titandb_compat_connection(self.database_url)
        self.using_sqlalchemy_compat = True

        if self.backend_name == "sqlite":
            database = make_url(self.database_url).database
            if database:
                self.db_path = str(os.path.abspath(database))

    def _reconnect_runtime_backend(self) -> None:
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
        if self._engine is not None:
            try:
                self._engine.dispose()
            except Exception:
                pass
        self._engine = None
        self.conn = None
        self._connect_runtime_backend()

    # ── Context Manager (para usar con 'with') ──────────────────────────────

    def __enter__(self):
        """Se ejecuta al entrar al bloque 'with'. Devuelve el objeto mismo."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Se ejecuta al SALIR del bloque 'with', incluso si hubo error.

        Parámetros (los pone Python automáticamente):
        - exc_type: tipo de excepción (None si no hubo error)
        - exc_val: valor de la excepción
        - exc_tb: traceback de la excepción

        Ejemplo de uso:
            with TitanDB() as db:
                db.guardar_precios(...)
            # Acá la conexión ya se cerró automáticamente
        """
        self.close()

    def close(self):
        """Cierra la conexión a la base de datos."""
        if self.conn:
            self.conn.close()
        if self._engine is not None:
            self._engine.dispose()

    @staticmethod
    def _normalize_scalar(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat(sep=" ", timespec="seconds")
        if isinstance(value, date):
            return value.isoformat()
        return value

    @staticmethod
    def _round_or_none(value: Any, digits: int) -> float | None:
        if value is None:
            return None
        return round(float(value), digits)

    def _normalize_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame
        normalized = frame.copy()
        for column in normalized.columns:
            if normalized[column].dtype == "object":
                normalized[column] = normalized[column].map(self._normalize_scalar)
        return normalized

    def _read_sql_query(self, query: str, params: Any = ()) -> pd.DataFrame:
        if not self.using_sqlalchemy_compat:
            return self._normalize_frame(pd.read_sql_query(query, self.conn, params=params))

        adapted_sql, adapted_params = adapt_qmark_sql(query, params)
        try:
            frame = pd.read_sql_query(text(adapted_sql), self.conn._connection, params=adapted_params)
        except (OperationalError, DBAPIError):
            if self.backend_name == "sqlite":
                raise
            self._reconnect_runtime_backend()
            frame = pd.read_sql_query(text(adapted_sql), self.conn._connection, params=adapted_params)
        return self._normalize_frame(frame)

    # ═══════════════════════════════════════════════════════════════════════════
    #  CREACIÓN DE TABLAS (Schema / Esquema)
    # ═══════════════════════════════════════════════════════════════════════════
    #
    #  El SCHEMA es la estructura de la base de datos: qué tablas hay,
    #  qué columnas tiene cada una, qué tipo de dato, etc.
    #
    #  Es como el plano de un edificio antes de construirlo.
    #  Diseñar un buen schema es FUNDAMENTAL — si lo hacés mal,
    #  después es muy difícil cambiarlo con datos adentro.
    #
    #  NUESTRAS TABLAS:
    #
    #  [prices]        → Precios históricos OHLCV de cada activo
    #  [predictions]   → Predicciones que genera cada modelo ML
    #  [outcomes]      → Qué pasó realmente después de cada predicción
    #  [model_metrics] → Métricas de performance acumuladas por modelo
    #  [regimes]       → Régimen de mercado detectado cada día
    #
    # ═══════════════════════════════════════════════════════════════════════════

    def _create_tables(self):
        """
        Crea todas las tablas del sistema.

        CONCEPTO — el guión bajo al inicio (_create_tables):
        ---------------------------------------------------
        En Python, un método que empieza con _ es "privado por convención".
        Significa: "este método es interno, no lo llames desde afuera".
        No es que Python te lo impida (no es Java), pero es una señal
        para otros programadores de que es un detalle de implementación.

        CONCEPTO — IF NOT EXISTS:
        -------------------------
        'CREATE TABLE IF NOT EXISTS' es idempotente: si la tabla ya existe,
        no hace nada. Esto permite correr _create_tables() muchas veces
        sin error. Es una práctica estándar en producción.
        """

        if self.using_sqlalchemy_compat:
            return

        cursor = self.conn.cursor()

        # ── TABLA 1: prices (precios históricos) ────────────────────────────
        #
        # Esta es la tabla más grande. Guardará AÑOS de datos OHLCV
        # para 260+ activos. Potencialmente 200,000+ filas.
        #
        # OHLCV significa:
        #   O = Open (precio de apertura del día)
        #   H = High (precio máximo del día)
        #   L = Low (precio mínimo del día)
        #   C = Close (precio de cierre del día)
        #   V = Volume (cantidad de acciones operadas)
        #
        # ¿Por qué guardamos Open/High/Low y no solo Close?
        # Porque los factores de nuestros modelos ML usan todos:
        #   - Garman-Klass volatility usa H y L
        #   - CLV (Close Location Value) usa H, L y C
        #   - Candlestick patterns usan O, H, L, C

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                ticker    TEXT    NOT NULL,
                date      TEXT    NOT NULL,
                open      REAL,
                high      REAL,
                low       REAL,
                close     REAL    NOT NULL,
                volume    INTEGER,
                adj_close REAL,

                -- PRIMARY KEY compuesta: la combinación ticker+date es única
                -- AAPL solo puede tener UN registro para 2024-01-15
                PRIMARY KEY (ticker, date)
            )
        """)

        # ÍNDICES: aceleran las consultas más frecuentes
        # Sin este índice, buscar "todos los precios de AAPL" recorrería
        # TODA la tabla. Con el índice, va directo a los registros de AAPL.
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_prices_ticker
            ON prices(ticker)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_prices_date
            ON prices(date)
        """)

        # ── TABLA 2: predictions (predicciones de los modelos) ──────────────
        #
        # Cada vez que un modelo ML genera predicciones, se guardan acá.
        # Esto es CLAVE: sin esto, nunca sabemos si el modelo acertó.
        #
        # Campos importantes:
        # - model_name: qué modelo hizo la predicción (TITAN_v5, TITAN_v4, etc)
        # - prediction_date: cuándo se hizo la predicción
        # - target_date: para qué día predice (puede ser T+1, T+2, T+3)
        # - direction: 'UP' o 'DOWN' (la predicción binaria)
        # - confidence: 0.0 a 1.0 (qué tan seguro está el modelo)
        # - score: el puntaje numérico crudo del modelo

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name      TEXT    NOT NULL,
                model_version   TEXT,
                ticker          TEXT    NOT NULL,
                prediction_date TEXT    NOT NULL,
                target_date     TEXT    NOT NULL,
                direction       TEXT    NOT NULL CHECK(direction IN ('UP', 'DOWN')),
                confidence      REAL    CHECK(confidence >= 0 AND confidence <= 1),
                score           REAL,
                regime          TEXT,
                sector          TEXT,
                created_at      TEXT    DEFAULT (datetime('now')),

                -- UNIQUE constraint: un modelo no puede hacer 2 predicciones
                -- para el mismo ticker y la misma fecha target
                UNIQUE(model_name, ticker, prediction_date, target_date)
            )
        """)

        # Índices para las consultas más comunes:
        # "Dame todas las predicciones del modelo X" → idx_pred_model
        # "Dame todas las predicciones para la fecha Y" → idx_pred_date
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pred_model
            ON predictions(model_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pred_date
            ON predictions(prediction_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pred_target
            ON predictions(target_date)
        """)

        # ── TABLA 3: outcomes (resultados reales) ───────────────────────────
        #
        # Después de que el mercado cierra, registramos QUÉ PASÓ REALMENTE.
        # Esto permite calcular: ¿el modelo acertó o no?
        #
        # prediction_id referencia a la tabla predictions (FOREIGN KEY).
        # Es como decir: "este resultado corresponde a ESTA predicción".

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS outcomes (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_id   INTEGER NOT NULL,
                actual_direction TEXT   NOT NULL CHECK(actual_direction IN ('UP', 'DOWN')),
                actual_return   REAL   NOT NULL,
                hit             INTEGER NOT NULL CHECK(hit IN (0, 1)),
                evaluated_at    TEXT   DEFAULT (datetime('now')),

                -- FOREIGN KEY: garantiza que prediction_id exista en predictions
                -- Si intentás insertar un outcome para una predicción inexistente → ERROR
                -- Esto mantiene la integridad de los datos
                FOREIGN KEY (prediction_id) REFERENCES predictions(id),

                -- Cada predicción solo puede tener UN resultado
                UNIQUE(prediction_id)
            )
        """)

        # ── TABLA 4: model_metrics (métricas acumuladas por modelo) ─────────
        #
        # Resumen de performance de cada modelo por período.
        # En vez de recalcular desde cero cada vez ("¿cuántas acertó TITAN v5
        # en enero?"), guardamos un resumen periódico.
        #
        # Métricas que guardamos:
        # - total_predictions: cuántas predicciones hizo
        # - correct_predictions: cuántas acertó
        # - accuracy: correct/total (el "win rate")
        # - avg_confidence: confianza promedio
        # - avg_return_when_right: retorno promedio cuando acierta
        # - avg_return_when_wrong: retorno promedio cuando se equivoca
        # - profit_factor: ganancias_brutas / pérdidas_brutas
        # - sharpe_ratio: retorno ajustado por riesgo

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_metrics (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name           TEXT NOT NULL,
                period_start         TEXT NOT NULL,
                period_end           TEXT NOT NULL,
                total_predictions    INTEGER DEFAULT 0,
                correct_predictions  INTEGER DEFAULT 0,
                accuracy             REAL DEFAULT 0,
                avg_confidence       REAL,
                avg_return_when_right REAL,
                avg_return_when_wrong REAL,
                profit_factor        REAL,
                sharpe_ratio         REAL,
                max_drawdown         REAL,
                calculated_at        TEXT DEFAULT (datetime('now')),

                UNIQUE(model_name, period_start, period_end)
            )
        """)

        # ── TABLA 5: regimes (régimen de mercado diario) ────────────────────
        #
        # Registra el régimen macro detectado cada día.
        # Esto es crucial para el análisis posterior:
        # "¿Mi modelo funciona mejor en BULL o BEAR market?"

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS regimes (
                date           TEXT PRIMARY KEY,
                trend_regime   TEXT,
                vol_regime     TEXT,
                credit_regime  TEXT,
                composite      TEXT,
                vix_level      REAL,
                spy_return_20d REAL,
                details        TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_status (
                key         TEXT PRIMARY KEY,
                value       TEXT,
                updated_at  TEXT DEFAULT (datetime('now'))
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_run_snapshots (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                model_key      TEXT NOT NULL,
                model_name     TEXT NOT NULL,
                model_version  TEXT,
                role           TEXT,
                analyzed_date  TEXT NOT NULL,
                prediction_for TEXT,
                freshness      TEXT,
                regime_label   TEXT,
                breadth_pct    REAL,
                signal_count   INTEGER DEFAULT 0,
                snapshot_json  TEXT NOT NULL,
                created_at     TEXT DEFAULT (datetime('now')),

                UNIQUE(model_key, analyzed_date)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_model_run_snapshots_model_key
            ON model_run_snapshots(model_key)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_model_run_snapshots_analyzed_date
            ON model_run_snapshots(analyzed_date)
        """)

        # Guardar cambios
        self.conn.commit()

    # ═══════════════════════════════════════════════════════════════════════════
    #  OPERACIONES CON PRECIOS
    # ═══════════════════════════════════════════════════════════════════════════

    def save_prices(self, df: pd.DataFrame, ticker: str):
        """
        Guarda precios históricos de UN ticker en la base de datos.

        CONCEPTO — INSERT OR REPLACE:
        -----------------------------
        Si ya existe un registro para (ticker, date), lo REEMPLAZA
        con los datos nuevos. Si no existe, lo INSERTA.
        Esto es "upsert" (update + insert) y es muy útil porque:
        - No da error si corrés el descargador 2 veces
        - Siempre tenés el dato más reciente

        CONCEPTO — executemany():
        -------------------------
        En vez de hacer 1 INSERT por fila (lento: 500 filas = 500 queries),
        hacemos 1 solo executemany con todas las filas (rápido).
        Es como mandar 500 cartas en 1 sobre vs 500 sobres individuales.

        Parámetros:
        -----------
        df : pd.DataFrame
            DataFrame con columnas Open, High, Low, Close, Volume, Adj Close
            y un DatetimeIndex (el formato que devuelve yfinance)
        ticker : str
            El símbolo del activo (ej: 'AAPL', 'MSFT')
        """
        if df is None or df.empty:
            return 0

        # Preparar los datos como lista de tuplas
        # Cada tupla es una fila: (ticker, date, open, high, low, close, volume, adj_close)
        records = []
        for idx, row in df.iterrows():
            # idx es el DatetimeIndex → lo convertimos a string 'YYYY-MM-DD'
            date_str = idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx)[:10]
            open_price = float(row.get('Open', 0)) if pd.notna(row.get('Open')) else None
            high_price = float(row.get('High', 0)) if pd.notna(row.get('High')) else None
            low_price = float(row.get('Low', 0)) if pd.notna(row.get('Low')) else None
            close_price = float(row['Close']) if pd.notna(row.get('Close')) else None
            volume = int(row.get('Volume', 0)) if pd.notna(row.get('Volume')) else None
            adj_close = (
                float(row.get('Adj Close', row.get('Close', 0)))
                if pd.notna(row.get('Adj Close', row.get('Close')))
                else None
            )

            # Regla reproducible de saneo:
            # cualquier barra diaria debe envolver al menos open/close.
            # Si Yahoo entrega high/low inconsistentes, expandimos solo el
            # rango minimo necesario sin tocar open/close.
            if open_price is not None and close_price is not None:
                envelope_high = max(open_price, close_price)
                envelope_low = min(open_price, close_price)
                high_price = envelope_high if high_price is None else max(high_price, envelope_high)
                low_price = envelope_low if low_price is None else min(low_price, envelope_low)

            records.append((
                ticker,
                date_str,
                open_price,
                high_price,
                low_price,
                close_price,
                volume,
                adj_close,
            ))

        # Filtrar registros sin precio de cierre (datos inválidos)
        records = [r for r in records if r[5] is not None]

        if not records:
            return 0

        # INSERT OR REPLACE: si ya existe (ticker, date), reemplaza
        self.conn.executemany("""
            INSERT OR REPLACE INTO prices
                (ticker, date, open, high, low, close, volume, adj_close)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, records)

        self.conn.commit()
        return len(records)

    def repair_ohlcv_bounds(self, start_date: Optional[str] = None,
                            end_date: Optional[str] = None) -> int:
        """
        Repara barras con OHLC inconsistente de forma conservadora.

        Regla:
        - high = max(high, open, close)
        - low  = min(low, open, close)

        Solo toca filas donde open/close ya existen y el problema es
        puramente de limites del rango. Esto deja una reparacion simple,
        deterministica y reproducible entre maquinas.
        """
        query = """
            SELECT ticker, date, open, high, low, close
            FROM prices
            WHERE open IS NOT NULL AND close IS NOT NULL
              AND high IS NOT NULL AND low IS NOT NULL
        """
        params: list[str] = []
        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)

        rows = self.conn.execute(query, params).fetchall()
        updates = []
        for row in rows:
            ticker = row[0]
            date_str = row[1]
            open_price = float(row[2])
            high_price = float(row[3])
            low_price = float(row[4])
            close_price = float(row[5])
            repaired_high = max(high_price, open_price, close_price)
            repaired_low = min(low_price, open_price, close_price)
            if repaired_high != high_price or repaired_low != low_price:
                updates.append((repaired_high, repaired_low, ticker, date_str))

        if not updates:
            return 0

        self.conn.executemany("""
            UPDATE prices
            SET high = ?, low = ?
            WHERE ticker = ? AND date = ?
        """, updates)
        self.conn.commit()
        return len(updates)

    def get_prices(self, ticker: str, start_date: Optional[str] = None,
                   end_date: Optional[str] = None) -> pd.DataFrame:
        """
        Obtiene precios históricos de la base de datos.

        CONCEPTO — Parámetros opcionales con filtros SQL:
        ------------------------------------------------
        Si pasás start_date y end_date, filtra por rango.
        Si no pasás nada, devuelve TODO el historial del ticker.

        Construimos el SQL dinámicamente agregando condiciones WHERE.

        CONCEPTO — SQL Injection y parámetros seguros:
        -----------------------------------------------
        NUNCA hagas: f"SELECT * WHERE ticker = '{ticker}'"
        Porque si alguien pasa ticker = "'; DROP TABLE prices; --"
        ¡te borra toda la tabla! (SQL Injection attack)

        SIEMPRE usá placeholders (?): "WHERE ticker = ?"
        SQLite escapa los valores automáticamente y es seguro.
        En entrevistas de trabajo, SIEMPRE mencioná SQL injection.

        Returns:
        --------
        pd.DataFrame con columnas OHLCV y DatetimeIndex
        """
        cache_key = (ticker, start_date or "", end_date or "")
        with _db_cache_lock:
            if cache_key in _prices_cache:
                return _prices_cache[cache_key].copy()

        query = "SELECT * FROM prices WHERE ticker = ?"
        params: list = [ticker]

        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)

        query += " ORDER BY date ASC"

        # pd.read_sql_query: ejecuta SQL y devuelve un DataFrame directamente
        # Es la forma más cómoda de pasar de SQL a pandas
        df = self._read_sql_query(query, params)

        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')

        with _db_cache_lock:
            _prices_cache[cache_key] = df.copy()
        return df

    def get_all_tickers(self) -> List[str]:
        """Devuelve lista de todos los tickers que tenemos en la DB."""
        global _tickers_cache
        with _db_cache_lock:
            if _tickers_cache is not None:
                return list(_tickers_cache)
        cursor = self.conn.execute(
            "SELECT DISTINCT ticker FROM prices ORDER BY ticker"
        )
        result = [row[0] for row in cursor.fetchall()]
        with _db_cache_lock:
            _tickers_cache = result
        return list(result)

    def get_latest_date(self, ticker: str) -> Optional[str]:
        """
        Devuelve la fecha más reciente que tenemos para un ticker.
        Útil para saber desde cuándo descargar datos nuevos.

        CONCEPTO — MAX() en SQL:
        ------------------------
        MAX(date) devuelve el valor máximo de la columna date.
        Como las fechas están en formato 'YYYY-MM-DD', el orden
        alfabético coincide con el orden cronológico. Esto es
        intencional y una buena práctica de diseño de schemas.
        """
        cursor = self.conn.execute(
            "SELECT MAX(date) FROM prices WHERE ticker = ?", (ticker,)
        )
        result = cursor.fetchone()
        return self._normalize_scalar(result[0]) if result and result[0] else None

    def get_all_latest_dates(self) -> Dict[str, str]:
        """
        Devuelve un dict {ticker: ultima_fecha} para TODOS los tickers en la DB.
        Usa una sola query SQL en vez de una por ticker — mucho más eficiente.
        Llamar desde el hilo principal antes de lanzar workers para evitar
        el error 'SQLite objects created in a thread can only be used in that thread'.
        """
        cursor = self.conn.execute(
            "SELECT ticker, MAX(date) FROM prices GROUP BY ticker"
        )
        return {row[0]: self._normalize_scalar(row[1]) for row in cursor.fetchall()}

    def count_prices(self) -> Dict[str, int]:
        """
        Cuenta cuántos registros hay por ticker.

        CONCEPTO — GROUP BY:
        --------------------
        GROUP BY agrupa filas con el mismo valor y permite usar
        funciones de agregación (COUNT, SUM, AVG, etc.)

        SELECT ticker, COUNT(*) FROM prices GROUP BY ticker
        Es como: "para cada ticker, contá cuántas filas tiene"

        Resultado ejemplo:
        {'AAPL': 504, 'MSFT': 504, 'GOOGL': 502, ...}
        """
        cursor = self.conn.execute(
            "SELECT ticker, COUNT(*) as cnt FROM prices GROUP BY ticker ORDER BY ticker"
        )
        return {row[0]: row[1] for row in cursor.fetchall()}

    # ═══════════════════════════════════════════════════════════════════════════
    #  OPERACIONES CON PREDICCIONES
    # ═══════════════════════════════════════════════════════════════════════════

    def save_prediction(self, model_name: str, ticker: str,
                        prediction_date: str, target_date: str,
                        direction: str, confidence: float = None,
                        score: float = None, regime: str = None,
                        sector: str = None, model_version: str = None) -> int:
        """
        Guarda UNA predicción de un modelo.

        Returns: el ID de la predicción insertada

        CONCEPTO — AUTOINCREMENT:
        -------------------------
        El campo 'id' se genera automáticamente (1, 2, 3, ...).
        lastrowid nos da el ID del último registro insertado.
        Esto es útil para después crear el outcome (resultado)
        asociado a esta predicción.
        """
        cursor = self.conn.execute("""
            INSERT OR REPLACE INTO predictions
                (model_name, model_version, ticker, prediction_date,
                 target_date, direction, confidence, score, regime, sector)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (model_name, model_version, ticker, prediction_date,
              target_date, direction.upper(), confidence, score, regime, sector))

        self.conn.commit()
        lastrowid = getattr(cursor, "lastrowid", None)
        if lastrowid:
            return int(lastrowid)

        row = self.conn.execute(
            """
            SELECT id
            FROM predictions
            WHERE model_name = ? AND ticker = ? AND prediction_date = ? AND target_date = ?
            """,
            (model_name, ticker, prediction_date, target_date),
        ).fetchone()
        return int(row[0]) if row else 0

    def save_predictions_bulk(self, predictions: List[Dict[str, Any]]) -> int:
        """
        Guarda MUCHAS predicciones de una vez (bulk insert).

        CONCEPTO — Bulk Operations:
        ---------------------------
        Insertar 1000 predicciones una por una = 1000 transacciones = LENTO
        Insertarlas todas juntas en 1 transacción = RÁPIDO (10-100x más)

        En el mundo real y en entrevistas, optimizar escrituras masivas
        es una pregunta clásica. La respuesta siempre es: batch/bulk.

        Parámetros:
        -----------
        predictions : list of dicts
            Cada dict tiene: model_name, ticker, prediction_date,
            target_date, direction, confidence, score, regime, sector
        """
        records = []
        for p in predictions:
            records.append((
                p['model_name'],
                p.get('model_version'),
                p['ticker'],
                p['prediction_date'],
                p['target_date'],
                p['direction'].upper(),
                p.get('confidence'),
                p.get('score'),
                p.get('regime'),
                p.get('sector'),
            ))

        self.conn.executemany("""
            INSERT OR REPLACE INTO predictions
                (model_name, model_version, ticker, prediction_date,
                 target_date, direction, confidence, score, regime, sector)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)

        self.conn.commit()
        return len(records)

    def get_predictions(self, model_name: Optional[str] = None,
                        prediction_date: Optional[str] = None,
                        target_date: Optional[str] = None,
                        evaluated: Optional[bool] = None) -> pd.DataFrame:
        """
        Consulta predicciones con filtros opcionales.

        CONCEPTO — LEFT JOIN:
        ---------------------
        JOIN conecta dos tablas por una columna en común.
        LEFT JOIN dice: "traeme TODAS las predicciones, y SI tienen
        un outcome asociado, traelo también. Si no tienen, poné NULL."

        Esto nos permite ver predicciones con y sin resultado en 1 query.

        Los tipos de JOIN son pregunta CLÁSICA de entrevista:
        - INNER JOIN: solo filas que matchean en AMBAS tablas
        - LEFT JOIN: todas las de la izquierda + match de la derecha
        - RIGHT JOIN: todas las de la derecha + match de la izquierda
        - FULL JOIN: todas las de ambas tablas
        """
        query = """
            SELECT
                p.*,
                o.actual_direction,
                o.actual_return,
                o.hit
            FROM predictions p
            LEFT JOIN outcomes o ON p.id = o.prediction_id
            WHERE 1=1
        """
        # WHERE 1=1 es un truco clásico: siempre es verdadero,
        # y permite agregar condiciones con AND sin preocuparse
        # de si es la primera condición o no. Elegante y práctico.

        params: list = []

        if model_name:
            query += " AND p.model_name = ?"
            params.append(model_name)
        if prediction_date:
            query += " AND p.prediction_date = ?"
            params.append(prediction_date)
        if target_date:
            query += " AND p.target_date = ?"
            params.append(target_date)
        if evaluated is True:
            query += " AND o.hit IS NOT NULL"
        elif evaluated is False:
            query += " AND o.hit IS NULL"

        query += " ORDER BY p.prediction_date DESC, p.confidence DESC"

        return self._read_sql_query(query, params)

    # ═══════════════════════════════════════════════════════════════════════════
    #  OPERACIONES CON OUTCOMES (RESULTADOS REALES)
    # ═══════════════════════════════════════════════════════════════════════════

    def save_outcome(self, prediction_id: int, actual_direction: str,
                     actual_return: float):
        """
        Registra el resultado real de una predicción.

        El campo 'hit' se calcula automáticamente:
        1 si la predicción acertó, 0 si falló.

        CONCEPTO — Subquery:
        --------------------
        Usamos un subquery (SELECT dentro de otro SQL) para obtener
        la dirección predicha y compararla con la real, todo en 1 operación.
        """
        # Primero obtenemos la dirección predicha
        cursor = self.conn.execute(
            "SELECT direction FROM predictions WHERE id = ?",
            (prediction_id,)
        )
        row = cursor.fetchone()
        if not row:
            return

        predicted = row[0]
        actual = actual_direction.upper()
        hit = 1 if predicted == actual else 0

        self.conn.execute("""
            INSERT OR REPLACE INTO outcomes
                (prediction_id, actual_direction, actual_return, hit)
            VALUES (?, ?, ?, ?)
        """, (prediction_id, actual, actual_return, hit))

        self.conn.commit()

    def evaluate_pending_predictions(self, target_date: str) -> Dict[str, Any]:
        """
        Evalúa TODAS las predicciones pendientes para una fecha target.

        Este es el método que corre DESPUÉS de que el mercado cierra:
        1. Busca predicciones cuyo target_date es hoy
        2. Busca el precio real del activo
        3. Calcula si subió o bajó
        4. Guarda el outcome

        CONCEPTO — Transaction (Transacción):
        -------------------------------------
        Todas las operaciones dentro de evaluate van dentro de UNA
        transacción. Si algo falla a mitad de camino, se deshace TODO
        (rollback). Esto garantiza que la DB nunca quede en un estado
        inconsistente (ej: algunas predicciones evaluadas y otras no).
        """
        # Buscar predicciones sin evaluar para esta fecha target
        pending = self.conn.execute("""
            SELECT p.id, p.ticker, p.direction, p.prediction_date, p.confidence
            FROM predictions p
            LEFT JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.target_date = ? AND o.id IS NULL
        """, (target_date,)).fetchall()

        if not pending:
            return {'evaluated': 0, 'message': 'No hay predicciones pendientes'}

        results = {'evaluated': 0, 'hits': 0, 'misses': 0, 'errors': 0, 'details': []}

        for pred in pending:
            pred_id = pred[0]
            ticker = pred[1]
            predicted_dir = pred[2]
            pred_date = pred[3]

            # Buscar precios para calcular el retorno real
            # Necesitamos: precio en prediction_date y precio en target_date
            prices = self.conn.execute("""
                SELECT date, close FROM prices
                WHERE ticker = ? AND date IN (?, ?)
                ORDER BY date ASC
            """, (ticker, pred_date, target_date)).fetchall()

            if len(prices) < 2:
                results['errors'] += 1
                continue

            price_before = prices[0][1]
            price_after = prices[1][1]

            if price_before is None or price_before == 0:
                results['errors'] += 1
                continue

            actual_return = (price_after - price_before) / price_before
            actual_direction = 'UP' if actual_return >= 0 else 'DOWN'
            hit = 1 if predicted_dir == actual_direction else 0

            self.conn.execute("""
                INSERT OR REPLACE INTO outcomes
                    (prediction_id, actual_direction, actual_return, hit)
                VALUES (?, ?, ?, ?)
            """, (pred_id, actual_direction, actual_return, hit))

            results['evaluated'] += 1
            if hit:
                results['hits'] += 1
            else:
                results['misses'] += 1

            results['details'].append({
                'ticker': ticker,
                'predicted': predicted_dir,
                'actual': actual_direction,
                'return': actual_return,
                'hit': bool(hit),
            })

        self.conn.commit()
        return results

    # ═══════════════════════════════════════════════════════════════════════════
    #  OPERACIONES CON RÉGIMEN DE MERCADO
    # ═══════════════════════════════════════════════════════════════════════════

    def save_regime(self, date_str: str, trend: str, vol: str,
                    credit: str, composite: str, vix: float = None,
                    spy_ret: float = None, details: str = None):
        """Guarda el régimen de mercado detectado para un día."""
        self.conn.execute("""
            INSERT OR REPLACE INTO regimes
                (date, trend_regime, vol_regime, credit_regime, composite,
                 vix_level, spy_return_20d, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (date_str, trend, vol, credit, composite, vix, spy_ret, details))
        self.conn.commit()

    def save_market_data_update(self, latest_prices_date: str,
                                updated_at: Optional[str] = None):
        """
        Guarda metadata de la ultima actualizacion real de PRECIOS de mercado.

        Importante:
        ----------
        Esto NO debe confundirse con la ultima escritura del archivo SQLite,
        porque el archivo tambien cambia cuando se insertan predictions,
        outcomes o regimes.
        """
        updated_at = updated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = [
            ("latest_prices_date", latest_prices_date, updated_at),
            ("market_data_updated_at", updated_at, updated_at),
        ]
        self.conn.executemany("""
            INSERT OR REPLACE INTO data_status (key, value, updated_at)
            VALUES (?, ?, ?)
        """, rows)
        self.conn.commit()

    def get_market_data_status(self) -> Dict[str, Optional[str]]:
        """Lee metadata de la ultima actualizacion real de precios."""
        rows = self.conn.execute("""
            SELECT key, value FROM data_status
            WHERE key IN ('latest_prices_date', 'market_data_updated_at')
        """).fetchall()
        status = {row[0]: row[1] for row in rows}
        return {
            'latest_prices_date': status.get('latest_prices_date'),
            'market_data_updated_at': status.get('market_data_updated_at'),
        }

    def save_model_metrics_bulk(self, metrics: List[Dict[str, Any]]) -> int:
        """Guarda metricas agregadas por modelo para un periodo."""
        if not metrics:
            return 0

        records = []
        for metric in metrics:
            records.append((
                metric['model_name'],
                metric['period_start'],
                metric['period_end'],
                metric.get('total_predictions', 0),
                metric.get('correct_predictions', 0),
                metric.get('accuracy'),
                metric.get('avg_confidence'),
                metric.get('avg_return_when_right'),
                metric.get('avg_return_when_wrong'),
                metric.get('profit_factor'),
                metric.get('sharpe_ratio'),
                metric.get('max_drawdown'),
            ))

        self.conn.executemany("""
            INSERT OR REPLACE INTO model_metrics
                (model_name, period_start, period_end, total_predictions,
                 correct_predictions, accuracy, avg_confidence,
                 avg_return_when_right, avg_return_when_wrong,
                 profit_factor, sharpe_ratio, max_drawdown)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)
        self.conn.commit()
        return len(records)

    def save_model_run_snapshot(
        self,
        *,
        model_key: str,
        model_name: str,
        analyzed_date: str,
        snapshot_payload: Dict[str, Any],
        model_version: Optional[str] = None,
        role: Optional[str] = None,
        prediction_for: Optional[str] = None,
        freshness: Optional[str] = None,
        regime_label: Optional[str] = None,
        breadth_pct: Optional[float] = None,
        signal_count: Optional[int] = None,
    ) -> int:
        snapshot_json = json.dumps(snapshot_payload, ensure_ascii=True, default=str)
        cursor = self.conn.execute(
            """
            INSERT OR REPLACE INTO model_run_snapshots
                (model_key, model_name, model_version, role, analyzed_date,
                 prediction_for, freshness, regime_label, breadth_pct,
                 signal_count, snapshot_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_key,
                model_name,
                model_version,
                role,
                analyzed_date,
                prediction_for,
                freshness,
                regime_label,
                breadth_pct,
                int(signal_count or 0),
                snapshot_json,
            ),
        )
        self.conn.commit()
        lastrowid = getattr(cursor, "lastrowid", None)
        if lastrowid:
            return int(lastrowid)

        row = self.conn.execute(
            """
            SELECT id
            FROM model_run_snapshots
            WHERE model_key = ? AND analyzed_date = ?
            """,
            (model_key, analyzed_date),
        ).fetchone()
        return int(row[0]) if row else 0

    # ═══════════════════════════════════════════════════════════════════════════
    #  CONSULTAS DE ANÁLISIS (las más interesantes para aprender SQL)
    # ═══════════════════════════════════════════════════════════════════════════

    def get_model_accuracy(self, model_name: str,
                           start_date: Optional[str] = None,
                           end_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Calcula la accuracy (precisión) de un modelo.

        CONCEPTO — Funciones de Agregación:
        -----------------------------------
        COUNT(*) = cuenta filas
        SUM(hit) = suma todos los 1s (aciertos)
        AVG(hit) = promedio de 0s y 1s = accuracy
        AVG(actual_return) = retorno promedio

        CONCEPTO — CASE WHEN (el IF/ELSE de SQL):
        ------------------------------------------
        CASE WHEN hit = 1 THEN actual_return END
        Es como: "si acertó, tomá el retorno; si no, ignorá (NULL)"
        AVG() ignora NULLs, así que AVG solo calcula sobre aciertos.
        """
        query = """
            SELECT
                COUNT(*) as total,
                SUM(o.hit) as aciertos,
                AVG(o.hit) * 100 as accuracy_pct,
                AVG(o.actual_return) * 100 as avg_return_pct,
                AVG(CASE WHEN o.hit = 1 THEN o.actual_return END) * 100 as avg_return_right,
                AVG(CASE WHEN o.hit = 0 THEN o.actual_return END) * 100 as avg_return_wrong,
                AVG(p.confidence) * 100 as avg_confidence
            FROM predictions p
            INNER JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name = ?
        """
        params: list = [model_name]

        if start_date:
            query += " AND p.target_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND p.target_date <= ?"
            params.append(end_date)

        row = self.conn.execute(query, params).fetchone()

        if not row or row[0] == 0:
            return {'total': 0, 'accuracy': 0, 'message': 'Sin datos evaluados'}

        return {
            'total': row[0],
            'aciertos': row[1],
            'accuracy_pct': self._round_or_none(row[2], 2),
            'avg_return_pct': self._round_or_none(row[3], 4),
            'avg_return_when_right': self._round_or_none(row[4], 4),
            'avg_return_when_wrong': self._round_or_none(row[5], 4),
            'avg_confidence': self._round_or_none(row[6], 2),
        }

    def get_accuracy_by_sector(self, model_name: str) -> pd.DataFrame:
        """
        Accuracy desglosada por sector.
        Responde: "¿En qué sectores acierta más mi modelo?"

        CONCEPTO — GROUP BY con múltiples agregaciones:
        Esta query agrupa por sector y calcula estadísticas para cada uno.
        """
        query = """
            SELECT
                p.sector,
                COUNT(*) as total,
                SUM(o.hit) as aciertos,
                AVG(o.hit) * 100 as accuracy_pct,
                AVG(o.actual_return) * 100 as avg_return_pct
            FROM predictions p
            INNER JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name = ? AND p.sector IS NOT NULL
            GROUP BY p.sector
            ORDER BY accuracy_pct DESC
        """
        frame = self._read_sql_query(query, [model_name])
        if "accuracy_pct" in frame.columns:
            frame["accuracy_pct"] = frame["accuracy_pct"].apply(lambda value: self._round_or_none(value, 2))
        if "avg_return_pct" in frame.columns:
            frame["avg_return_pct"] = frame["avg_return_pct"].apply(lambda value: self._round_or_none(value, 4))
        return frame

    def get_accuracy_by_regime(self, model_name: str) -> pd.DataFrame:
        """
        Accuracy desglosada por régimen de mercado.
        Responde: "¿Mi modelo funciona mejor en bull o bear market?"
        """
        query = """
            SELECT
                p.regime,
                COUNT(*) as total,
                SUM(o.hit) as aciertos,
                AVG(o.hit) * 100 as accuracy_pct,
                AVG(o.actual_return) * 100 as avg_return_pct
            FROM predictions p
            INNER JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name = ? AND p.regime IS NOT NULL
            GROUP BY p.regime
            ORDER BY accuracy_pct DESC
        """
        frame = self._read_sql_query(query, [model_name])
        if "accuracy_pct" in frame.columns:
            frame["accuracy_pct"] = frame["accuracy_pct"].apply(lambda value: self._round_or_none(value, 2))
        if "avg_return_pct" in frame.columns:
            frame["avg_return_pct"] = frame["avg_return_pct"].apply(lambda value: self._round_or_none(value, 4))
        return frame

    def get_accuracy_by_confidence(self, model_name: str,
                                    bins: int = 5) -> pd.DataFrame:
        """
        Accuracy desglosada por nivel de confianza.
        Responde: "¿Cuando el modelo dice que está MUY seguro, acierta más?"

        Si la respuesta es SÍ → el modelo está bien calibrado.
        Si la respuesta es NO → el confidence score no sirve.

        CONCEPTO — NTILE / Buckets:
        ---------------------------
        Dividimos las predicciones en 'bins' grupos iguales según confidence.
        Grupo 1 = las de menos confianza, Grupo 5 = las de más confianza.
        Si el modelo está bien calibrado, el grupo 5 debería tener más accuracy.
        """
        query = """
            SELECT
                NTILE(?) OVER (ORDER BY p.confidence) as confidence_bucket,
                COUNT(*) as total,
                MIN(p.confidence) * 100 as conf_min,
                MAX(p.confidence) * 100 as conf_max,
                AVG(o.hit) * 100 as accuracy_pct,
                AVG(o.actual_return) * 100 as avg_return_pct
            FROM predictions p
            INNER JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name = ?
            GROUP BY confidence_bucket
            ORDER BY confidence_bucket
        """
        frame = self._read_sql_query(query, [bins, model_name])
        for column, digits in {
            "conf_min": 1,
            "conf_max": 1,
            "accuracy_pct": 2,
            "avg_return_pct": 4,
        }.items():
            if column in frame.columns:
                frame[column] = frame[column].apply(lambda value, d=digits: self._round_or_none(value, d))
        return frame

    def get_daily_performance(self, model_name: str) -> pd.DataFrame:
        """
        Performance día a día de un modelo.
        Útil para graficar la curva de equity (como se acumula la ganancia).
        """
        query = """
            SELECT
                p.target_date as date,
                COUNT(*) as n_predictions,
                SUM(o.hit) as aciertos,
                AVG(o.hit) * 100 as accuracy_pct,
                SUM(o.actual_return) * 100 as total_return_pct,
                AVG(o.actual_return) * 100 as avg_return_pct
            FROM predictions p
            INNER JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name = ?
            GROUP BY p.target_date
            ORDER BY p.target_date ASC
        """
        frame = self._read_sql_query(query, [model_name])
        for column, digits in {
            "accuracy_pct": 2,
            "total_return_pct": 4,
            "avg_return_pct": 4,
        }.items():
            if column in frame.columns:
                frame[column] = frame[column].apply(lambda value, d=digits: self._round_or_none(value, d))
        return frame

    def get_streak(self, model_name: str) -> Dict[str, int]:
        """
        Calcula la racha actual del modelo (aciertos o fallos consecutivos).
        Útil para detectar si el modelo está "en racha" o "descompuesto".
        """
        query = """
            SELECT o.hit
            FROM predictions p
            INNER JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name = ?
            ORDER BY p.target_date DESC
            LIMIT 50
        """
        rows = self.conn.execute(query, (model_name,)).fetchall()

        if not rows:
            return {'current_streak': 0, 'streak_type': 'none'}

        first = rows[0][0]
        streak = 0
        for row in rows:
            if row[0] == first:
                streak += 1
            else:
                break

        return {
            'current_streak': streak,
            'streak_type': 'wins' if first == 1 else 'losses',
        }

    # ═══════════════════════════════════════════════════════════════════════════
    #  UTILIDADES
    # ═══════════════════════════════════════════════════════════════════════════

    def db_stats(self) -> Dict[str, Any]:
        """
        Estadísticas generales de la base de datos.
        Útil para verificar que todo está funcionando.
        """
        stats = {}

        for table in ['prices', 'predictions', 'outcomes', 'regimes']:
            count = self.conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            stats[f'{table}_count'] = count

        stats['model_run_snapshots_count'] = self.conn.execute(
            "SELECT COUNT(*) FROM model_run_snapshots"
        ).fetchone()[0]

        # Rango de fechas en precios
        row = self.conn.execute(
            "SELECT MIN(date), MAX(date) FROM prices"
        ).fetchone()
        stats['price_date_range'] = f"{row[0]} -> {row[1]}" if row[0] else "Sin datos"

        # Modelos registrados
        models = self.conn.execute(
            "SELECT DISTINCT model_name FROM predictions"
        ).fetchall()
        stats['models'] = [m[0] for m in models]

        # Tamaño del archivo DB
        if self.backend_name == "sqlite" and os.path.exists(self.db_path):
            size_mb = os.path.getsize(self.db_path) / (1024 * 1024)
            stats['db_size_mb'] = round(size_mb, 2)

        return stats

    def execute_raw(self, query: str, params: tuple = ()) -> pd.DataFrame:
        """
        Ejecuta SQL crudo y devuelve DataFrame.
        Para consultas ad-hoc y exploración.

        IMPORTANTE: solo usá esto para SELECT, nunca para INSERT/UPDATE/DELETE
        desde fuera de la clase.
        """
        return self._read_sql_query(query, params)


# ═══════════════════════════════════════════════════════════════════════════════
#  TEST RÁPIDO — se ejecuta si corrés este archivo directamente
# ═══════════════════════════════════════════════════════════════════════════════
#
#  CONCEPTO — if __name__ == '__main__':
#  -------------------------------------
#  Esto solo se ejecuta si corrés: python database.py
#  NO se ejecuta si alguien importa el módulo: from database import TitanDB
#
#  Es el patrón estándar de Python para tests rápidos y demos.
#  En una entrevista, si te preguntan "¿qué hace if __name__ == '__main__'?"
#  la respuesta es: "permite que el archivo funcione tanto como módulo
#  importable como script ejecutable independiente".

if __name__ == '__main__':
    print("=" * 60)
    print("  TEST DE BASE DE DATOS TITAN")
    print("=" * 60)

    with TitanDB() as db:
        stats = db.db_stats()
        print(f"\n  DB ubicación: {db.db_path}")
        print(f"  DB tamaño:    {stats.get('db_size_mb', 0)} MB")
        print(f"  Precios:      {stats['prices_count']} registros")
        print(f"  Predicciones: {stats['predictions_count']} registros")
        print(f"  Outcomes:     {stats['outcomes_count']} registros")
        print(f"  Regímenes:    {stats['regimes_count']} registros")
        print(f"  Rango fechas: {stats['price_date_range']}")
        print(f"  Modelos:      {stats['models']}")

        print("\n  [OK] Base de datos funcionando correctamente")

    print("=" * 60)
