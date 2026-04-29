from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = ROOT / "titan_system" / "data" / "titan.db"
ENV_FILE_PATH = ROOT / ".env"


@dataclass(frozen=True)
class DatabaseSettings:
    database_url: str
    sqlite_fallback_path: Path


def read_env_file(path: Path = ENV_FILE_PATH) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def resolve_setting(name: str, *, env_file_values: dict[str, str], default: str) -> str:
    runtime_value = os.getenv(name)
    if runtime_value not in (None, ""):
        return runtime_value

    file_value = env_file_values.get(name)
    if file_value not in (None, ""):
        return file_value

    return default


def normalize_database_url(database_url: str) -> str:
    url = database_url.strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def escape_database_url_for_configparser(database_url: str) -> str:
    return database_url.replace("%", "%%")


def resolve_sqlite_fallback_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def build_database_settings() -> DatabaseSettings:
    env_file_values = read_env_file()
    sqlite_fallback = resolve_sqlite_fallback_path(
        resolve_setting(
            "SQLITE_FALLBACK_PATH",
            env_file_values=env_file_values,
            default=str(DEFAULT_SQLITE_PATH),
        )
    )
    database_url = normalize_database_url(resolve_setting(
        "DATABASE_URL",
        env_file_values=env_file_values,
        default=f"sqlite:///{sqlite_fallback.as_posix()}",
    ))
    return DatabaseSettings(
        database_url=database_url,
        sqlite_fallback_path=sqlite_fallback,
    )


def get_database_url() -> str:
    return build_database_settings().database_url


def get_sqlite_fallback_path() -> Path:
    return build_database_settings().sqlite_fallback_path
