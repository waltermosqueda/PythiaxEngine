"""
Preflight validator for refrescar_datos_dashboard.py.
Checks that all internal function calls (_render_*, _build_*, _card_*) 
resolve to defined functions in the same file.

Usage: py scripts/preflight_dashboard.py
Exit 0 = OK, Exit 1 = undefined call(s) found.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "herramientas" / "refrescar_datos_dashboard.py"

raw = TARGET.read_bytes()
if raw[:3] == b"\xef\xbb\xbf":
    print(f"::error::Preflight FAILED — UTF-8 BOM detected in {TARGET.name}. Use Python to write this file, NOT PowerShell Set-Content.", file=sys.stderr)
    sys.exit(1)

src = raw.decode("utf-8")
tree = ast.parse(src)
defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
errors = []
for node in ast.walk(tree):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = node.func.id
        if (
            name.startswith("_render_")
            or name.startswith("_build_")
            or name.startswith("_card_")
        ) and name not in defined:
            errors.append(f"  line ~{node.lineno}: '{name}' called but not defined")

# Verify _render_kpi_strip calls a function that renders the Sistema KPI card
strip_calls = []
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "_render_kpi_strip":
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                strip_calls.append(child.func.id)
kpi_card_calls = [c for c in strip_calls if c.startswith("_render_kpi_") and c != "_render_kpi_strip"]
if not kpi_card_calls:
    errors.append("  _render_kpi_strip does not call any _render_kpi_* card function — tooltip will be missing")

if errors:
    print(f"::error::Preflight FAILED — {len(errors)} issue(s) in {TARGET.name}:", file=sys.stderr)
    for e in errors:
        print(e, file=sys.stderr)
    sys.exit(1)

print(f"Preflight OK — all _render_/_build_/_card_ calls resolve ({len(defined)} funcs defined). KPI card: {kpi_card_calls[0]}")
