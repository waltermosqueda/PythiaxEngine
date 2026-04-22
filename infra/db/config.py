from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = ROOT / "titan_system" / "data" / "titan.db"


@dataclass(frozen=True)
class DatabaseSettings:
    database_url: str
    sqlite_fallback_path: Path


def build_database_settings() -> DatabaseSettings:
    sqlite_fallback = Path(
        os.getenv("SQLITE_FALLBACK_PATH", str(DEFAULT_SQLITE_PATH))
    ).expanduser()
    database_url = os.getenv("DATABASE_URL", f"sqlite:///{sqlite_fallback.as_posix()}")
    return DatabaseSettings(
        database_url=database_url,
        sqlite_fallback_path=sqlite_fallback,
    )


def get_database_url() -> str:
    return build_database_settings().database_url

