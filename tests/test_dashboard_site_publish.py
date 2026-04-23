from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from herramientas.dashboard_paths import EXECUTIVE_HTML, INDEX_HTML, LAB_HTML, MANIFEST_PATH, SNAPSHOT_PATH
from infra.publish.dashboard_site import ENTRYPOINT_NAME, NOJEKYLL_NAME, SITE_MANIFEST_NAME, stage_dashboard_site


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-dashboard-site" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_stage_dashboard_site_creates_pages_ready_bundle() -> None:
    tmp_dir = make_workspace_tmp_dir()
    source_dir = tmp_dir / "source"
    output_dir = tmp_dir / "output"
    source_dir.mkdir(parents=True, exist_ok=True)
    try:
        files = {
            SNAPSHOT_PATH.name: '{"generated_at":"2026-04-23T03:17:00"}\n',
            INDEX_HTML.name: "<html><body>main</body></html>\n",
            EXECUTIVE_HTML.name: "<html><body>executive</body></html>\n",
            LAB_HTML.name: "<html><body>lab</body></html>\n",
            MANIFEST_PATH.name: json.dumps(
                {
                    "generated_at": "2026-04-23T03:17:00",
                    "artifact_count": 4,
                    "build": {"build_source": "github_actions", "commit_short": "abc1234"},
                    "artifacts": [],
                }
            )
            + "\n",
        }
        for name, content in files.items():
            (source_dir / name).write_text(content, encoding="utf-8")

        written = stage_dashboard_site(source_dir, output_dir)
        site_manifest = json.loads((output_dir / SITE_MANIFEST_NAME).read_text(encoding="utf-8"))

        assert (output_dir / ENTRYPOINT_NAME).read_text(encoding="utf-8") == files[INDEX_HTML.name]
        assert (output_dir / INDEX_HTML.name).read_text(encoding="utf-8") == files[INDEX_HTML.name]
        assert (output_dir / EXECUTIVE_HTML.name).exists()
        assert (output_dir / LAB_HTML.name).exists()
        assert (output_dir / SNAPSHOT_PATH.name).exists()
        assert (output_dir / MANIFEST_PATH.name).exists()
        assert (output_dir / NOJEKYLL_NAME).exists()
        assert site_manifest["entrypoint"] == ENTRYPOINT_NAME
        assert site_manifest["source_manifest_name"] == MANIFEST_PATH.name
        assert site_manifest["build"]["commit_short"] == "abc1234"
        assert SNAPSHOT_PATH.name in site_manifest["published_files"]
        assert ENTRYPOINT_NAME in site_manifest["published_files"]
        assert any(path.name == SITE_MANIFEST_NAME for path in written)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
