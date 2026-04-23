from __future__ import annotations

from pathlib import Path

from infra.db.config import normalize_database_url, read_env_file, resolve_setting


def test_read_env_file_parses_basic_and_quoted_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
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
