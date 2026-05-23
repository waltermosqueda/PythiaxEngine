#!/usr/bin/env python3
"""Sync staging with today productivo data — zero Supabase egress.
Copies DATA: blocks from preview_c1_pro.html (CI-generated today) into staging,
then patches the h7-strip header KPI values.
Ticker tape and signals chip HTML are NOT modified (fragile regex risk).
"""
import re
from pathlib import Path

PROD    = Path("C:/repos/PythiaxEngine/analisis/preview_c1_pro.html")
STAGING = Path("C:/repos/PythiaxEngine/analisis/_staging_h7t3b.html")

prod_html    = PROD.read_text(encoding="utf-8")
staging_html = STAGING.read_text(encoding="utf-8")
changes = []

# -- 1. Sync DATA: blocks from productivo ------------------------------------
DATA_BLOCKS = ["heatmap-css", "hero-row", "liga-table", "heatmap"]

for block in DATA_BLOCKS:
    s_marker = f"<!-- DATA:{block}-start -->"
    e_marker = f"<!-- DATA:{block}-end -->"

    ps = prod_html.find(s_marker)
    pe = prod_html.find(e_marker)
    if ps < 0 or pe < 0:
        changes.append(f"WARNING DATA:{block} not found in productivo")
        continue
    prod_content = prod_html[ps + len(s_marker):pe]

    ss = staging_html.find(s_marker)
    se = staging_html.find(e_marker)
    if ss < 0 or se < 0:
        changes.append(f"WARNING DATA:{block} not found in staging")
        continue

    staging_html = staging_html[:ss + len(s_marker)] + prod_content + staging_html[se:]
    changes.append(f"OK DATA:{block} synced ({len(prod_content):,} chars)")

# -- 2. Extract key values from productivo KPI strip -------------------------
new_ts = re.search(r'data-ts="([^"]+)"', prod_html).group(1)

m_leader = re.search(r'data-bid="kpi-leader".*?kc-value">(.*?)</div>.*?kc-sub">(WR [\d.]+%[^<]*)</div>', prod_html, re.DOTALL)
leader_sub = m_leader.group(2).strip()
new_wr  = re.search(r'WR ([\d.]+%)', leader_sub).group(1)
new_ret = re.search(r'ret (\+[\d.]+%)', leader_sub).group(1)

m_picks = re.search(r'data-bid="kpi-picks".*?kc-sub">(.*?)</div>', prod_html, re.DOTALL)
picks_sub = m_picks.group(1).strip()
new_breadth = re.search(r'breadth ([\d.]+%)', picks_sub).group(1)

changes.append(f"  Prod: WR={new_wr} ret={new_ret} breadth={new_breadth} ts={new_ts}")

# -- 3. Patch h7-strip KPI values (targeted single-line replacements only) ---
staging_html = re.sub(
    r'<div class="h7-cv gold">[\d.]+%</div>',
    f'<div class="h7-cv gold">{new_wr}</div>',
    staging_html, count=1
)
changes.append(f"OK h7-strip WR -> {new_wr}")

staging_html = re.sub(
    r'<div class="h7-cs">ML_V97 \xb7 WR \xb7 ret [^<]+</div>',
    f'<div class="h7-cs">ML_V97 \xb7 WR \xb7 ret {new_ret}</div>',
    staging_html, count=1
)
changes.append(f"OK h7-strip ret -> {new_ret}")

staging_html = re.sub(
    r'<div class="h7-cs">breadth [\d.]+%</div>',
    f'<div class="h7-cs">breadth {new_breadth}</div>',
    staging_html, count=1
)
changes.append(f"OK h7-strip breadth -> {new_breadth}")

staging_html = re.sub(
    r'(id="kpi-actualizacion"[^>]*data-ts=")[^"]*(")',
    lambda m: m.group(1) + new_ts + m.group(2),
    staging_html, count=1
)
changes.append(f"OK h7-strip data-ts -> {new_ts}")

# -- Write result ------------------------------------------------------------
STAGING.write_text(staging_html, encoding="utf-8")
print("=== Staging sync from productivo (zero egress) ===")
for c in changes:
    print(c)
print(f"\nFile: {len(staging_html):,} bytes | Source: {new_ts}")
