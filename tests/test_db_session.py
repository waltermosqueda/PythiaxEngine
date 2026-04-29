from __future__ import annotations

from infra.db.session import build_engine_kwargs, create_db_engine


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


def test_build_engine_kwargs_requires_ssl_for_remote_postgres_without_sslmode() -> None:
    kwargs = build_engine_kwargs("postgresql+psycopg://user:pass@ep-fresh-neon.us-east-1.aws.neon.tech/testdb")

    assert kwargs["pool_recycle"] == 300
    assert kwargs["connect_args"] == {
        "connect_timeout": 15,
        "sslmode": "require",
    }


def test_build_engine_kwargs_keeps_local_postgres_without_forced_ssl() -> None:
    kwargs = build_engine_kwargs("postgresql+psycopg://user:pass@localhost/testdb")

    assert kwargs["connect_args"] == {"connect_timeout": 15}


def test_build_engine_kwargs_respects_explicit_sslmode_in_url() -> None:
    kwargs = build_engine_kwargs("postgresql+psycopg://user:pass@remote.example/testdb?sslmode=disable")

    assert kwargs["connect_args"] == {"connect_timeout": 15}
