from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import analisis.generar_tablero_maquina_pensante as dashboard


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-dashboard-manifest" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_build_dashboard_metadata_prefers_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv("PYTHIAX_COMMIT_SHA", "abcdef1234567890")
    monkeypatch.setenv("PYTHIAX_RUN_ID", "9001")
    monkeypatch.setenv("PYTHIAX_RUN_ATTEMPT", "2")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_WORKFLOW", "Dashboard Build")
    monkeypatch.setenv("GITHUB_ACTOR", "waltermosqueda")

    payload = dashboard.build_dashboard_metadata("postgresql")

    assert payload["build_source"] == "github_actions"
    assert payload["db_backend"] == "postgresql"
    assert payload["commit_sha"] == "abcdef1234567890"
    assert payload["commit_short"] == "abcdef1"
    assert payload["run_id"] == "9001"
    assert payload["pipeline_run_id"] == "9001"
    assert payload["run_attempt"] == "2"
    assert payload["workflow"] == "Dashboard Build"
    assert payload["actor"] == "waltermosqueda"


def test_build_artifact_manifest_hashes_written_files() -> None:
    tmp_dir = make_workspace_tmp_dir()
    try:
        artifact = tmp_dir / "artifact.txt"
        artifact.write_text("pythiax-manifest\n", encoding="utf-8")

        manifest = dashboard.build_artifact_manifest(
            {
                "generated_at": "2026-04-23T10:20:30",
                "build": {"build_source": "local", "db_backend": "sqlite", "commit_short": "abc1234"},
            },
            [artifact],
        )

        assert manifest["artifact_count"] == 1
        assert manifest["build"]["commit_short"] == "abc1234"
        assert manifest["artifacts"][0]["name"] == "artifact.txt"
        assert manifest["artifacts"][0]["relative_path"].endswith("artifact.txt")
        assert manifest["artifacts"][0]["size_bytes"] == artifact.stat().st_size
        assert manifest["artifacts"][0]["sha256"] == dashboard.file_sha256(artifact)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
