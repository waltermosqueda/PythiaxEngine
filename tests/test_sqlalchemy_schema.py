from infra.db import models  # noqa: F401
from infra.db.base import Base


def test_expected_tables_exist_in_metadata() -> None:
    expected = {
        "prices",
        "predictions",
        "outcomes",
        "model_metrics",
        "regimes",
        "data_status",
        "pipeline_runs",
    }

    assert expected.issubset(set(Base.metadata.tables))
