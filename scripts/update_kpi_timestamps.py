#!/usr/bin/env python3
"""Update `data-ts` on elements with id="kpi-actualizacion" and the
`kpi-fresh-sub` text across HTML files under the repo.

Usage: run from repo root `py scripts/update_kpi_timestamps.py`
"""
from pathlib import Path
import re
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]

DIV_TS_RE = re.compile(r'(id="kpi-actualizacion"[^>]*data-ts=")([^"]+)(")', re.I)
SUB_RE = re.compile(r'(<div[^>]*id="kpi-fresh-sub"[^>]*>)([^<]*)(</div>)', re.I)

now_utc = datetime.now(timezone.utc).replace(microsecond=0)
new_ts = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
ar = now_utc - timedelta(hours=3)
new_sub = f"{now_utc.strftime('%Y-%m-%d %H:%M')} UTC · {ar.strftime('%H:%M')} AR"

modified = []
for p in sorted(ROOT.rglob('*.html')):
    try:
        s = p.read_text(encoding='utf-8')
    except Exception:
        continue
    if 'id="kpi-actualizacion"' not in s:
        continue
    old_ts_match = DIV_TS_RE.search(s)
    old_sub_match = SUB_RE.search(s)
    if not old_ts_match and not old_sub_match:
        continue
    old_ts = old_ts_match.group(2) if old_ts_match else None
    new_s = s
    if old_ts_match:
        new_s = DIV_TS_RE.sub(r'\1' + new_ts + r'\3', new_s, count=1)
    if old_sub_match:
        new_s = SUB_RE.sub(r'\1' + new_sub + r'\3', new_s, count=1)
    if new_s != s:
        p.write_text(new_s, encoding='utf-8')
        modified.append((str(p.relative_to(ROOT)), old_ts, new_ts))

print('Updated kpi timestamps in files:')
for m in modified:
    print(' -', m[0], ':', m[1], '→', m[2])
if not modified:
    print(' (no files changed)')
