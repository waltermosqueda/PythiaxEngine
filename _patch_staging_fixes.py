#!/usr/bin/env python3
"""Apply all 3 integrity fixes to the staging dashboard _staging_h7t3b.html.
Run once, then re-run _tmp_render_staging.py to inject fresh snapshot data.
"""
import re
from pathlib import Path

STAGING = Path("C:/repos/PythiaxEngine/analisis/_staging_h7t3b.html")

html = STAGING.read_text(encoding="utf-8")
changes = []

# ── Fix #3: add id="overlap" to the overlap section ─────────────────────────
OLD_OVERLAP = '<section class="panel editable-block" data-bid="overlap-panel" data-blabel="Overlap matrix">'
NEW_OVERLAP = '<section class="panel editable-block" data-bid="overlap-panel" data-blabel="Overlap matrix" id="overlap">'
if OLD_OVERLAP in html:
    html = html.replace(OLD_OVERLAP, NEW_OVERLAP, 1)
    changes.append("✅ Fix #3: id=overlap added to overlap section")
else:
    changes.append("⚠️  Fix #3: overlap section not found — already patched?")

# ── Fix h7-strip: breadth (59.4% → 61.9%) ───────────────────────────────────
OLD_BREADTH = '<div class="h7-cs">breadth 59.4%</div>'
NEW_BREADTH = '<div class="h7-cs">breadth 61.9%</div>'
if OLD_BREADTH in html:
    html = html.replace(OLD_BREADTH, NEW_BREADTH, 1)
    changes.append("✅ h7-strip breadth: 59.4% → 61.9%")
else:
    changes.append("⚠️  h7-strip breadth: not found (already patched?)")

# ── Fix h7-strip: champion WR (76.1% → 76.36%) ──────────────────────────────
#!/usr/bin/env python3
"""Neutralized staging patcher.

This file was disabled on 2026-05-29 to prevent manual HTML mutations of
the staging/preview pages. Restoration is possible from
`_patch_staging_fixes.py.orig` if needed for a controlled run.
"""
import sys

def main():
    print("Neutralized _patch_staging_fixes.py — no automatic HTML patches will run.")
    print("To restore behavior: copy _patch_staging_fixes.py.orig -> _patch_staging_fixes.py")
    return 0

if __name__ == '__main__':
    sys.exit(main())

