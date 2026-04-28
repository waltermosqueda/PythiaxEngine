from __future__ import annotations

from infra.db.session import create_db_engine


def test_create_db_engine_normalizes_postgresql_driver() -> None:
    engine = create_db_engine("postgresql://user:pass@localhost/testdb")
    try:
        assert engine.url.drivername == "postgresql+psycopg"
    finally:
        engine.dispose()


def test_create_db_engine_normalizes_legacy_postgres_driver() -> None:
    engine = create_db_engine("postgres://user:pass@localhost/testdb")
    try:
        assert engine.url.drivername == "postgresql+psycopg"
    finally:
        engine.dispose()
