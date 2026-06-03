from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from infra.db.config import get_database_url, normalize_database_url


def build_engine_kwargs(database_url: str) -> dict[str, object]:
    url = make_url(database_url)
    kwargs: dict[str, object] = {
        "future": True,
        "pool_pre_ping": True,
    }
    if url.get_backend_name().startswith("postgres"):
        # pool_recycle: 1800s (30 min) en vez de 300 — evita reconexiones
        # innecesarias durante runs largos de CI (~54 min) que disparan
        # queries de inicializacion como SELECT name FROM pg_timezone_names.
        kwargs["pool_recycle"] = 1800
        # pool_size + max_overflow: maximo 4 conexiones totales (Supabase
        # free tier permite 60; mantenerlo bajo ahorra RAM en el servidor).
        kwargs["pool_size"] = 2
        kwargs["max_overflow"] = 2
        connect_args: dict[str, object] = {
            "connect_timeout": 15,
            # Fijar timezone en la conexion evita que SQLAlchemy/psycopg2
            # ejecute SELECT name FROM pg_timezone_names al conectar.
            # idle_in_transaction_session_timeout=0: Supabase por defecto mata
            # sesiones que llevan >30s idle dentro de una transaccion. Durante
            # precompute_indicators (~60-90s de CPU puro) la conexion queda idle
            # in transaction y Supabase la elimina; la siguiente query cuelga
            # infinitamente porque TCP sigue vivo pero la sesion PG esta muerta.
            # Poner 0 desactiva ese timeout para nuestras sesiones.
            # statement_timeout=120000: si alguna query individual se cuelga,
            # falla en 120s con error (en vez de colgar hasta el timeout del
            # proceso de 600s). El error dispara el reconect en _read_sql_query.
            "options": "-c TimeZone=UTC -c idle_in_transaction_session_timeout=0 -c statement_timeout=120000",
            # Deshabilitar prepared statements: PgBouncer (Supabase pooler)
            # no soporta prepared statements en modo transaction pooling.
            # Sin esto: DuplicatePreparedStatement "_pg3_0" al reutilizar conexion.
            "prepare_threshold": None,
        }
        host = (url.host or "").strip().lower()
        is_local_host = host in {"", "localhost", "127.0.0.1", "::1"}
        if not is_local_host and "sslmode" not in url.query:
            connect_args["sslmode"] = "require"
        kwargs["connect_args"] = connect_args
    return kwargs


def create_db_engine(database_url: str | None = None, echo: bool = False) -> Engine:
    resolved_url = normalize_database_url(database_url or get_database_url())
    return create_engine(resolved_url, echo=echo, **build_engine_kwargs(resolved_url))


def create_session_factory(database_url: str | None = None, echo: bool = False) -> sessionmaker[Session]:
    return sessionmaker(bind=create_db_engine(database_url=database_url, echo=echo), expire_on_commit=False, future=True)
