from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from infra.db.migrate_sqlite_to_postgres import resolve_insert_chunk_size


def make_engine_stub(name: str) -> SimpleNamespace:
    return SimpleNamespace(dialect=SimpleNamespace(name=name))


def test_resolve_insert_chunk_size_caps_large_sqlite_multi_insert() -> None:
    frame = pd.DataFrame(columns=["a", "b", "c", "d", "e", "f", "g", "h"])

    assert (
        resolve_insert_chunk_size(
            target_engine=make_engine_stub("sqlite"),
            normalized_chunk=frame,
            requested_chunk_size=5000,
        )
        == 112
    )


def test_resolve_insert_chunk_size_keeps_requested_for_non_sqlite() -> None:
    frame = pd.DataFrame(columns=["a", "b", "c"])

    assert (
        resolve_insert_chunk_size(
            target_engine=make_engine_stub("postgresql"),
            normalized_chunk=frame,
            requested_chunk_size=5000,
        )
        == 5000
    )
