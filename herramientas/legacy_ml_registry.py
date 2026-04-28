#!/usr/bin/env python3
"""
Helpers para la liga observada de modelos legacy ML.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY_ML_REGISTRY_PATH = ROOT / "aprendizaje_operativo" / "legacy_ml_models.json"


@dataclass(frozen=True)
class LegacyMLRegistryEntry:
    model_id: str
    label: str
    model_prefix: str
    signal_code: str
    status: str
    role: str
    source_path: str
    runner_script: str
    native_horizon: int
    evaluation_mode: str
    notes: str

    @property
    def runner_path(self) -> Path:
        return (ROOT / self.runner_script).resolve()

    @property
    def source_file(self) -> Path:
        path = Path(self.source_path)
        return path if path.is_absolute() else (ROOT / path).resolve()

    @property
    def model_name(self) -> str:
        return f"{self.model_prefix}_{self.signal_code}_D{self.native_horizon}"


def load_legacy_ml_registry() -> list[LegacyMLRegistryEntry]:
    if not LEGACY_ML_REGISTRY_PATH.exists():
        return []

    payload = json.loads(LEGACY_ML_REGISTRY_PATH.read_text(encoding="utf-8"))
    entries: list[LegacyMLRegistryEntry] = []
    for raw in payload.get("legacy_ml_models", []):
        try:
            entries.append(
                LegacyMLRegistryEntry(
                    model_id=str(raw["model_id"]),
                    label=str(raw["label"]),
                    model_prefix=str(raw["model_prefix"]),
                    signal_code=str(raw.get("signal_code", "BUY")),
                    status=str(raw.get("status", "disabled")),
                    role=str(raw.get("role", "legacy_ml_observed")),
                    source_path=str(raw["source_path"]),
                    runner_script=str(raw["runner_script"]),
                    native_horizon=int(raw.get("native_horizon", 1)),
                    evaluation_mode=str(raw.get("evaluation_mode", "close_on_target")),
                    notes=str(raw.get("notes", "")),
                )
            )
        except Exception:
            continue
    return entries


def load_enabled_legacy_ml_entries() -> list[LegacyMLRegistryEntry]:
    return [entry for entry in load_legacy_ml_registry() if entry.status == "enabled"]
