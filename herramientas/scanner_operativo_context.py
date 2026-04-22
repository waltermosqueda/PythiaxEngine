#!/usr/bin/env python3
"""
Contexto operativo canonico del scanner.

Centraliza la resolucion de:
  - scanner activo
  - referencia inmediata anterior
  - loops de aprendizaje que deben seguir vivos

La idea es evitar hardcodes dispersos en pipeline, auditoria y futuras
promociones de scanner.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "experimentos" / "scanner_ledger.json"
OBSERVED_SCANNERS_PATH = ROOT / "aprendizaje_operativo" / "observed_scanners.json"
SCANNER_DIR = ROOT / "SCANNER"
TOOLS_DIR = ROOT / "herramientas"
SCANNER_RE = re.compile(r"invertir_v(\d+)(?:_\d+)?\.py$")
LEARNING_RE = re.compile(r"aprendizaje_operativo_v(\d+)\.py$")
BASE_LEARNING_VERSION = 11


@dataclass(frozen=True)
class OperationalScannerContext:
    active_entry_id: str | None
    active_version: int
    active_scanner: Path
    reference_version: int | None
    reference_scanner: Path | None
    base_learning: Path | None
    reference_learning: Path | None
    active_learning: Path | None
    learning_chain: tuple[Path, ...]
    observed_versions: tuple[int, ...]
    observed_scanners: tuple[Path, ...]
    observed_learning_chain: tuple[Path, ...]


def _extract_version(filename: str, pattern: re.Pattern[str]) -> int | None:
    match = pattern.fullmatch(filename)
    if not match:
        return None
    return int(match.group(1))


def scanner_version_from_path(path: Path) -> int:
    version = _extract_version(path.name, SCANNER_RE)
    if version is None:
        raise ValueError(f"Nombre de scanner no canonico: {path}")
    return version


def learning_version_from_path(path: Path) -> int:
    version = _extract_version(path.name, LEARNING_RE)
    if version is None:
        raise ValueError(f"Nombre de aprendizaje no canonico: {path}")
    return version


def model_prefix_for_version(version: int) -> str:
    return f"INVERTIR_V{version}"


def run_dir_for_version(version: int) -> Path:
    return ROOT / "aprendizaje_operativo" / f"v{version}_runs"


def report_dir_for_version(version: int) -> Path:
    return ROOT / "aprendizaje_operativo" / f"v{version}_reports"


def learning_script_for_version(version: int) -> Path | None:
    path = TOOLS_DIR / f"aprendizaje_operativo_v{version}.py"
    return path if path.exists() else None


def scanner_script_for_version(version: int) -> Path | None:
    path = SCANNER_DIR / f"invertir_v{version}.py"
    return path.resolve() if path.exists() else None


def _load_ledger() -> dict:
    if not LEDGER_PATH.exists():
        return {}
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def _load_observed_registry() -> dict:
    if not OBSERVED_SCANNERS_PATH.exists():
        return {}
    return json.loads(OBSERVED_SCANNERS_PATH.read_text(encoding="utf-8"))


def load_observed_versions() -> tuple[int, ...]:
    registry = _load_observed_registry()
    observed_versions: list[int] = []
    for entry in registry.get("observed_scanners", []):
        if entry.get("status") != "enabled":
            continue
        version = entry.get("version")
        if not isinstance(version, int):
            continue
        if version not in observed_versions:
            observed_versions.append(version)
    return tuple(observed_versions)


def _discover_productive_scanners() -> list[Path]:
    if not SCANNER_DIR.exists():
        return []
    scanners = []
    for path in SCANNER_DIR.iterdir():
        if not path.is_file():
            continue
        if _extract_version(path.name, SCANNER_RE) is None:
            continue
        scanners.append(path.resolve())
    return sorted(scanners, key=scanner_version_from_path)


def _active_scanner_from_ledger(ledger: dict) -> tuple[str | None, Path | None]:
    active_state = ledger.get("active_state") or {}
    scanner_file = active_state.get("scanner_file")
    if not scanner_file:
        return active_state.get("scanner_entry_id"), None
    path = (ROOT / scanner_file).resolve()
    if not path.exists():
        return active_state.get("scanner_entry_id"), None
    return active_state.get("scanner_entry_id"), path


def resolve_operational_scanner_context() -> OperationalScannerContext:
    ledger = _load_ledger()
    active_entry_id, active_scanner = _active_scanner_from_ledger(ledger)
    productives = _discover_productive_scanners()

    if active_scanner is None:
        if not productives:
            raise RuntimeError("No hay scanners productivos canonicos en SCANNER/")
        active_scanner = productives[-1]

    active_version = scanner_version_from_path(active_scanner)
    reference_scanner = None
    reference_version = None
    for candidate in productives:
        candidate_version = scanner_version_from_path(candidate)
        if candidate_version < active_version:
            reference_scanner = candidate
            reference_version = candidate_version

    base_learning = learning_script_for_version(BASE_LEARNING_VERSION)
    reference_learning = learning_script_for_version(reference_version) if reference_version is not None else None
    active_learning = learning_script_for_version(active_version)

    chain: list[Path] = []
    for candidate in [base_learning, reference_learning, active_learning]:
        if candidate is None:
            continue
        if candidate not in chain:
            chain.append(candidate.resolve())

    observed_versions = load_observed_versions()
    observed_scanners: list[Path] = []
    observed_learning_scripts: list[Path] = []
    for version in observed_versions:
        scanner_path = scanner_script_for_version(version)
        learning_path = learning_script_for_version(version)
        if scanner_path is not None:
            observed_scanners.append(scanner_path)
        if learning_path is not None and learning_path.resolve() not in observed_learning_scripts:
            observed_learning_scripts.append(learning_path.resolve())

    return OperationalScannerContext(
        active_entry_id=active_entry_id,
        active_version=active_version,
        active_scanner=active_scanner.resolve(),
        reference_version=reference_version,
        reference_scanner=reference_scanner.resolve() if reference_scanner else None,
        base_learning=base_learning.resolve() if base_learning else None,
        reference_learning=reference_learning.resolve() if reference_learning else None,
        active_learning=active_learning.resolve() if active_learning else None,
        learning_chain=tuple(chain),
        observed_versions=observed_versions,
        observed_scanners=tuple(observed_scanners),
        observed_learning_chain=tuple(observed_learning_scripts),
    )
