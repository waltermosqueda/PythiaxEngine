from __future__ import annotations

from types import SimpleNamespace

from herramientas.aprendizaje_operativo_legacy_ml_base import extract_sector_map_from_module, extract_universe_from_module


def test_extract_sector_map_from_module_supports_upper_and_lowercase_dicts() -> None:
    module = SimpleNamespace(
        ACTIVOS={"AAPL": "Apple", "MSFT": "Microsoft"},
        activos={"NVDA": "Nvidia"},
    )

    sector_map = extract_sector_map_from_module(module)

    assert sector_map == {
        "AAPL": "Apple",
        "MSFT": "Microsoft",
        "NVDA": "Nvidia",
    }


def test_extract_universe_from_module_supports_modern_list_names() -> None:
    module = SimpleNamespace(
        activos=["AAPL", "MSFT"],
        TRADABLE_UNIVERSE=["AAPL", "NVDA"],
        CONTEXT_TICKERS=["QQQ", "SPY"],
    )

    assert extract_universe_from_module(module) == ["AAPL", "MSFT", "NVDA", "QQQ", "SPY"]


def test_extract_universe_from_module_injects_spy_when_missing() -> None:
    module = SimpleNamespace(REQUESTED_UNIVERSE=["AAPL", "MSFT"])

    assert extract_universe_from_module(module) == ["SPY", "AAPL", "MSFT"]
