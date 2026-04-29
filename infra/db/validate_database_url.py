from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any

from sqlalchemy.engine import make_url

from infra.db.config import normalize_database_url


def _provider_hints(host: str, port: int | None, *, github_actions: bool) -> list[str]:
    host = host.strip().lower()
    hints: list[str] = []
    if "pooler.supabase.com" in host:
        if port == 6543:
            hints.append(
                "El host parece ser el `Transaction pooler` de Supabase (puerto 6543). "
                "Para este repo usa `Session pooler` (puerto 5432), porque GitHub Actions y Alembic necesitan una conexion persistente compatible con IPv4."
            )
    elif host.endswith(".supabase.co") and not host.startswith("db."):
        hints.append(
            "El host parece un `Project URL` de Supabase. Usa el `Direct connection string`, cuyo host suele empezar con `db.`."
        )
    elif github_actions and host.startswith("db.") and host.endswith(".supabase.co"):
        hints.append(
            "El host parece ser el `Direct connection` de Supabase. Ese endpoint usa IPv6 por defecto y suele fallar en GitHub Actions con `Network is unreachable`. "
            "Para este repo en CI usa el `Session pooler` (host `aws-0-...pooler.supabase.com`, puerto 5432) o el add-on IPv4 de Supabase."
        )
    return hints


def validate_database_url(
    raw_database_url: str | None,
    *,
    github_actions: bool | None = None,
) -> dict[str, Any]:
    raw_value = (raw_database_url or "").strip()
    if not raw_value:
        raise ValueError("DATABASE_URL esta vacio.")

    if github_actions is None:
        github_actions = (os.getenv("GITHUB_ACTIONS") or "").strip().lower() == "true"

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

    authority_match = re.match(r"^[a-z0-9+]+://([^/?#]+)", raw_value, flags=re.IGNORECASE)
    authority = authority_match.group(1) if authority_match else ""
    if authority.count("@") > 1:
        raise ValueError(
            "DATABASE_URL parece tener una password con caracteres especiales sin escape. "
            "Si tu password contiene `@`, `:`, `/`, `?`, `#`, `%` o `&`, debes URL-encodearla antes de guardarla en el secret."
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
        if authority and ":" in authority and "@" in authority:
            raise ValueError(
                "DATABASE_URL no tiene password valida. Si pegaste la password real y contiene caracteres especiales "
                "como `@`, `:`, `/`, `?`, `#`, `%` o `&`, debes URL-encodearla antes de guardarla en el secret."
            )
        raise ValueError("DATABASE_URL no tiene password.")
    if not parsed.host:
        raise ValueError("DATABASE_URL no tiene host.")
    if not parsed.database:
        raise ValueError("DATABASE_URL no tiene nombre de base.")

    hints = _provider_hints(parsed.host, parsed.port, github_actions=github_actions)
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