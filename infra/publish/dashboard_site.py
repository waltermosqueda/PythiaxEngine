from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
from time import sleep
from typing import Any

from herramientas.dashboard_paths import C1_PRO_BUNDLE_HTML, EXECUTIVE_HTML, INDEX_HTML, LAB_HTML, MANIFEST_PATH, SNAPSHOT_PATH


ROOT = Path(__file__).resolve().parents[2]
SITE_MANIFEST_NAME = "site_bundle_manifest.json"
ENTRYPOINT_NAME = "index.html"
NOJEKYLL_NAME = ".nojekyll"
REQUIRED_SOURCE_FILES = [
    SNAPSHOT_PATH.name,
    INDEX_HTML.name,
    EXECUTIVE_HTML.name,
    LAB_HTML.name,
    C1_PRO_BUNDLE_HTML.name,
    MANIFEST_PATH.name,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepara un site bundle estatico para GitHub Pages.")
    parser.add_argument("--source-dir", required=True, help="Directorio con el bundle generado del dashboard.")
    parser.add_argument("--output-dir", required=True, help="Directorio destino del site bundle.")
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_required_source_files(source_dir: Path) -> None:
    missing = [name for name in REQUIRED_SOURCE_FILES if not (source_dir / name).exists()]
    if missing:
        raise FileNotFoundError(
            f"Faltan archivos requeridos en el bundle fuente {source_dir}: {', '.join(sorted(missing))}"
        )


def safe_rmtree(path: Path) -> None:
    resolved = path.resolve()
    if resolved == ROOT or not resolved.is_relative_to(ROOT):
        raise ValueError(f"Refusing to remove output directory outside workspace: {resolved}")
    if resolved.exists():
        def onerror(func: Any, target: str, exc_info: Any) -> None:
            target_path = Path(target)
            if target_path.exists():
                os.chmod(target_path, stat.S_IWRITE)
                func(target)

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                shutil.rmtree(resolved, onexc=onerror)
                return
            except PermissionError as exc:
                last_error = exc
                sleep(attempt)
        if last_error is not None:
            raise last_error


def build_site_manifest(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    source_manifest = read_json(source_dir / MANIFEST_PATH.name)
    published_files = sorted(
        path.name for path in output_dir.iterdir() if path.is_file() and path.name != SITE_MANIFEST_NAME
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entrypoint": ENTRYPOINT_NAME,
        "entrypoint_source": C1_PRO_BUNDLE_HTML.name,
        "source_dir": str(source_dir.resolve()),
        "output_dir": str(output_dir.resolve()),
        "source_manifest_name": MANIFEST_PATH.name,
        "source_artifact_count": source_manifest.get("artifact_count"),
        "build": source_manifest.get("build") or {},
        "published_files": published_files,
    }


def stage_dashboard_site(source_dir: Path, output_dir: Path) -> list[Path]:
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    assert_required_source_files(source_dir)
    safe_rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for name in REQUIRED_SOURCE_FILES:
        src = source_dir / name
        dst = output_dir / name
        shutil.copy2(src, dst)
        written.append(dst)

    index_alias = output_dir / ENTRYPOINT_NAME
    shutil.copy2(source_dir / C1_PRO_BUNDLE_HTML.name, index_alias)
    written.append(index_alias)

    nojekyll = output_dir / NOJEKYLL_NAME
    nojekyll.write_text("", encoding="utf-8")
    written.append(nojekyll)

    site_manifest = build_site_manifest(source_dir, output_dir)
    site_manifest_path = output_dir / SITE_MANIFEST_NAME
    site_manifest_path.write_text(json.dumps(site_manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    written.append(site_manifest_path)
    return written


def main() -> int:
    args = parse_args()
    written = stage_dashboard_site(Path(args.source_dir), Path(args.output_dir))
    print("GitHub Pages site bundle preparado:")
    for path in written:
        print(f" - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
