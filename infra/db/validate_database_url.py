from __future__ import annotations

import argparse
import json
import os
from typing import Any

from sqlalchemy.engine import make_url

from infra.db.config import normalize_database_url


def _provider_hints(host: str) -> list[str]:
    host = host.strip().lower()
    hints: list[str] = []
    if "pooler.supabase.com" in host:
        hints.append(
            "El host parece ser un pooler de Supabase. Para este repo usa `Direct connection`, no pooler."
        )
    if host.endswith(".supabase.co") and not host.startswith("db."):
        hints.append(
            "El host parece un `Project URL` de Supabase. Usa el `Direct connection string`, cuyo host suele empezar con `db.`."
        )
    return hints


def validate_database_url(raw_database_url: str | None) -> dict[str, Any]:
    raw_value = (raw_database_url or "").strip()
    if not raw_value:
        raise ValueError("DATABASE_URL esta vacio.")

    upper_value = raw_value.upper()
    if raw_value.startswith(("http://", "https://")):
        raise ValueError(
            "DATABASE_URL parece ser una URL web, no una conexion Postgres. "
            "En Supabase debes usar `Direct connection string`, no `Project URL`."
        )
    if "YOUR-PASSWORD" in upper_value:
        raise ValueError(
            "DATABASE_URL todavia contiene el placeholder `YOUR-PASSWORD`. "
            "Reemplazalo por la password real de la DB."
        )

    normalized_url = normalize_database_url(raw_value)
    parsed = make_url(normalized_url)
    backend = parsed.get_backend_name()
    if not backend.startswith("postgres"):
        raise ValueError(
            f"DATABASE_URL debe apuntar a Postgres. Backend detectado: {backend}."
        )

    if not parsed.username:
        raise ValueError("DATABASE_URL no tiene usuario.")
    if not parsed.password:
        raise ValueError("DATABASE_URL no tiene password.")
    if not parsed.host:
        raise ValueError("DATABASE_URL no tiene host.")
    if not parsed.database:
        raise ValueError("DATABASE_URL no tiene nombre de base.")

    hints = _provider_hints(parsed.host)
    if hints:
        raise ValueError(" ".join(hints))

    query = dict(parsed.query)
    return {
        "normalized_url": normalized_url,
        "redacted_url": parsed.render_as_string(hide_password=True),
        "backend": parsed.drivername,
        "username": parsed.username,
        "host": parsed.host,
        "port": parsed.port,
        "database": parsed.database,
        "query": query,
        "sslmode": query.get("sslmode"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valida DATABASE_URL y falla con diagnosticos claros para GitHub Actions."
    )
    parser.add_argument("--database-url", default=None, help="URL a validar. Default: env DATABASE_URL.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = validate_database_url(args.database_url or os.getenv("DATABASE_URL"))
    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())