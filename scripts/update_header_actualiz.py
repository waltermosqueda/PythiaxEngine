#!/usr/bin/env python3
"""Update 'Actualiz.' header snippets in analytic partials to current timestamp.

This updates static fragments like 'hace 72h' / '07/05 · 18:49 AR' to
show 'calculando…' and the current UTC/AR timestamp.
"""
from pathlib import Path
import re
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]

now = datetime.now(timezone.utc).replace(microsecond=0)
new_sub = f"{now.strftime('%Y-%m-%d %H:%M')} UTC · {(now - timedelta(hours=3)).strftime('%H:%M')} AR"

PAT_H7 = re.compile(r'(<div[^>]+class="h7-cl">Actualiz\.?</div>\s*<div[^>]+class="h7-cv[^"]*">)[^<]*(</div>\s*<div[^>]+class="h7-cs"[^>]*>)[^<]*(</div>)', re.I | re.DOTALL)
PAT_TK = re.compile(r'(<span class="tk-l">Actualiz\.?</span>\s*<span class="tk-v r">)[^<]*(</span>\s*<span[^>]*>)[^<]*(</span>)', re.I | re.DOTALL)

modified = []
for p in sorted((ROOT / 'analisis').rglob('*.html')):
    try:
        s = p.read_text(encoding='utf-8')
    except Exception:
        continue
    if 'Actualiz.' not in s:
        continue
    new_s = s
    new_s, n1 = PAT_H7.subn(r"\1calculando…\2" + new_sub + r"\3", new_s, count=0)
    new_s, n2 = PAT_TK.subn(r"\1calculando…\2" + new_sub + r"\3", new_s, count=0)
    if new_s != s:
        p.write_text(new_s, encoding='utf-8')
        modified.append((str(p.relative_to(ROOT)), n1 + n2))

print('Updated header Actualiz. in files:')
for m in modified:
    print(' -', m[0], ':', m[1], 'replacements')
if not modified:
    print(' (no files changed)')
