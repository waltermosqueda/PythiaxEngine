from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from infra.db.config import normalize_database_url, read_env_file, resolve_setting
from infra.db.validate_database_url import validate_database_url


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-db-config" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_read_env_file_parses_basic_and_quoted_values() -> None:
    tmp_dir = make_workspace_tmp_dir()
    try:
        env_path = tmp_dir / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "# comment",
                    "DATABASE_URL=postgresql+psycopg://user:pass@host/db",
                    'SQLITE_FALLBACK_PATH="titan_system/data/titan.db"',
                    "",
                ]
            ),
            encoding="utf-8",
        )

        values = read_env_file(env_path)

        assert values["DATABASE_URL"] == "postgresql+psycopg://user:pass@host/db"
        assert values["SQLITE_FALLBACK_PATH"] == "titan_system/data/titan.db"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_resolve_setting_prefers_real_env_over_env_file(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://runtime/override")

    value = resolve_setting(
        "DATABASE_URL",
        env_file_values={"DATABASE_URL": "postgresql+psycopg://file/value"},
        default="sqlite:///fallback.db",
    )

    assert value == "postgresql+psycopg://runtime/override"


def test_normalize_database_url_rewrites_plain_postgresql_scheme() -> None:
    assert (
        normalize_database_url("postgresql://user:pass@host/db")
        == "postgresql+psycopg://user:pass@host/db"
    )


def test_normalize_database_url_rewrites_legacy_postgres_scheme() -> None:
    assert (
        normalize_database_url("postgres://user:pass@host/db")
        == "postgresql+psycopg://user:pass@host/db"
    )


def test_validate_database_url_accepts_redactable_postgres_url() -> None:
    payload = validate_database_url("postgresql://postgres:secret@db.project-ref.supabase.co:5432/postgres?sslmode=require")

    assert payload["backend"] == "postgresql+psycopg"
    assert payload["host"] == "db.project-ref.supabase.co"
    assert payload["sslmode"] == "require"
    assert payload["redacted_url"] == "postgresql+psycopg://postgres:***@db.project-ref.supabase.co:5432/postgres?sslmode=require"


def test_validate_database_url_rejects_supabase_project_url() -> None:
    try:
        validate_database_url("https://project-ref.supabase.co")
    except ValueError as exc:
        assert "Project URL" in str(exc)
    else:
        raise AssertionError("Se esperaba ValueError para Project URL de Supabase.")


def test_validate_database_url_rejects_password_placeholder() -> None:
    try:
        validate_database_url("postgresql://postgres:[YOUR-PASSWORD]@db.project-ref.supabase.co:5432/postgres")
    except ValueError as exc:
        assert "YOUR-PASSWORD" in str(exc)
    else:
        raise AssertionError("Se esperaba ValueError para placeholder de password.")


def test_validate_database_url_rejects_supabase_pooler_host() -> None:
    try:
        validate_database_url("postgresql://postgres:secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres")
    except ValueError as exc:
        assert "Direct connection" in str(exc)
    else:
        raise AssertionError("Se esperaba ValueError para pooler de Supabase.")
