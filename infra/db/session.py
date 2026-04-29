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
        kwargs["pool_recycle"] = 300
        connect_args: dict[str, object] = {"connect_timeout": 15}
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
