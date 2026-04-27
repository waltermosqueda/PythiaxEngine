from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import herramientas.scanner_operativo_context as scanner_context


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-operational-context" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_operational_context_resolves_active_scanner(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    try:
        scanner_dir = tmp_dir / "SCANNER"
        tools_dir = tmp_dir / "herramientas"
        learning_dir = tmp_dir / "aprendizaje_operativo"
        experiment_dir = tmp_dir / "experimentos"

        for path in [scanner_dir, tools_dir, learning_dir, experiment_dir]:
            path.mkdir(parents=True, exist_ok=True)

        for version in [8, 10, 11, 12, 13]:
            (scanner_dir / f"invertir_v{version}.py").write_text("# scanner\n", encoding="utf-8")
        for version in [11, 12, 13]:
            (tools_dir / f"aprendizaje_operativo_v{version}.py").write_text(
                "# learning\n",
                encoding="utf-8",
            )

        (experiment_dir / "scanner_ledger.json").write_text(
            json.dumps(
                {
                    "active_state": {
                        "scanner_entry_id": "SCN-V13-SIGNAL-E-HW",
                        "scanner_file": "SCANNER/invertir_v13.py",
                    }
                }
            ),
            encoding="utf-8",
        )
        (learning_dir / "observed_scanners.json").write_text(
            json.dumps(
                {
                    "observed_scanners": [
                        {"version": 8, "status": "enabled"},
                        {"version": 10, "status": "enabled"},
                        {"version": 12, "status": "disabled"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(scanner_context, "ROOT", tmp_dir)
        monkeypatch.setattr(scanner_context, "LEDGER_PATH", experiment_dir / "scanner_ledger.json")
        monkeypatch.setattr(
            scanner_context,
            "OBSERVED_SCANNERS_PATH",
            learning_dir / "observed_scanners.json",
        )
        monkeypatch.setattr(scanner_context, "SCANNER_DIR", scanner_dir)
        monkeypatch.setattr(scanner_context, "TOOLS_DIR", tools_dir)

        context = scanner_context.resolve_operational_scanner_context()

        assert context.active_version == 13
        assert context.reference_version == 12
        assert context.base_learning is not None
        assert context.reference_learning is not None
        assert context.active_learning is not None
        assert context.observed_versions == (8, 10)
        assert [path.name for path in context.observed_scanners] == ["invertir_v8.py", "invertir_v10.py"]
        assert [path.name for path in context.learning_chain] == [
            "aprendizaje_operativo_v11.py",
            "aprendizaje_operativo_v12.py",
            "aprendizaje_operativo_v13.py",
        ]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_operational_context_falls_back_to_latest_productive_scanner(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    try:
        scanner_dir = tmp_dir / "SCANNER"
        tools_dir = tmp_dir / "herramientas"
        learning_dir = tmp_dir / "aprendizaje_operativo"

        for path in [scanner_dir, tools_dir, learning_dir]:
            path.mkdir(parents=True, exist_ok=True)

        for version in [11, 12, 13]:
            (scanner_dir / f"invertir_v{version}.py").write_text("# scanner\n", encoding="utf-8")
            (tools_dir / f"aprendizaje_operativo_v{version}.py").write_text(
                "# learning\n",
                encoding="utf-8",
            )

        monkeypatch.setattr(scanner_context, "ROOT", tmp_dir)
        monkeypatch.setattr(scanner_context, "LEDGER_PATH", tmp_dir / "missing_ledger.json")
        monkeypatch.setattr(
            scanner_context,
            "OBSERVED_SCANNERS_PATH",
            learning_dir / "missing_observed_scanners.json",
        )
        monkeypatch.setattr(scanner_context, "SCANNER_DIR", scanner_dir)
        monkeypatch.setattr(scanner_context, "TOOLS_DIR", tools_dir)

        context = scanner_context.resolve_operational_scanner_context()

        assert context.active_entry_id is None
        assert context.active_version == 13
        assert context.active_scanner.name == "invertir_v13.py"
        assert context.active_learning is not None
        assert context.learning_chain
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_operational_context_current_repo_state_is_consistent() -> None:
    context = scanner_context.resolve_operational_scanner_context()

    assert context.active_version >= 11
    assert context.active_scanner.name == "invertir_v13.py"
    assert context.active_learning is not None
    assert context.learning_chain
