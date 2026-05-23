"""
Genera analisis/_staging_ranking_preview.html
con 3 versiones de Tabla Quant (sin Sharpe/MDD, con sparkline chart).
T1 — Compacto Puro   : tabla mínima, línea fina
T2 — Bloomberg Pro   : barra WR de fondo, área con gradiente
T3 — Accent Stripe   : borde izquierdo color modelo, glow sparkline
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT  = os.path.join(ROOT, "analisis", "_staging_ranking_preview.html")

# ── Spark vals reales de Supabase ──────────────────────────────────────
SPARK_VALS = {
    "V11":              [0.0, 0.0, 0.0, 2.1521, 3.7425, 3.7425, 3.8331, 3.8331, 3.8331, 3.8331, 17.3684, 18.9588, 18.9588, 19.0494, 19.0494, 19.0494, 19.0494, 32.5847, 32.5847, 32.5847, 31.28, 30.284, 30.284, 30.4437, 30.8107, 31.1341, 30.4004, 29.0957, 28.0997],
    "ML_V97":           [2.0201, 14.9842, 18.6659, 37.834, 42.8472, 60.4851, 68.8513, 75.738, 68.1588, 90.973, 97.9047, 103.3315, 109.4317, 118.3407, 119.0324, 123.0283, 128.7803, 129.2997, 129.5294, 105.0773, 103.3241, 106.9871, 118.5674, 126.3289, 151.449, 157.2727, 172.2464, 170.4771, 180.0473, 177.949],
    "ML_V39":           [-1.0907, -2.9917, -3.4477, 0.4063, 1.091, 3.1204, 2.6116, 2.3994, 3.7852, 4.251, 6.4197, 7.5151, 8.106, 9.1508, 9.4808, 9.6387, 8.0353, 8.9519, 6.6337, 7.1458, 8.754, 11.044, 10.1929, 13.2675, 14.0911, 14.2166, 14.2166, 8.1018, 8.1018, 19.5515],
    "V13":              [12.9898, 28.4408, 27.4619, 23.4494, 23.2147, 33.9382, 47.7981, 74.0387, 89.7796, 111.7846, 117.6513, 120.376, 118.515, 131.8312, 126.3627, 124.2519, 104.5656, 113.4296, 136.5544, 169.1494, 224.1195, 236.3105, 253.9328, 271.3071, 292.0373, 315.1361, 329.2464, 354.4771, 377.6019, 374.3201],
    "ML_V39FULL":       [-2.9868, -2.326, -1.0653, -0.295, 1.0324, 2.1272, 2.4721, 3.0556, 3.8717, 5.1012, 4.8549, 7.4144, 8.9782, 9.1852, 7.859, 9.0831, 10.5759, 11.1889, 12.879, 11.2113, 10.6642, 9.6012, 9.757, 9.7874, 11.3844, 11.642, 11.642, 19.0853, 19.0853, 28.6204],
    "ML_V94":           [14.7557, 31.7187, 39.7117, 46.4749, 49.0278, 57.269, 59.1072, 59.7754, 71.2419, 75.0567, 78.5911, 93.8013, 117.9162, 123.6168, 126.3723, 122.4732, 124.5391, 120.8514, 113.4857, 113.4899, 110.0242, 119.4312, 123.9263, 121.4207, 130.8742, 146.738, 155.5614, 168.4211, 168.0205, 177.0454],
    "ML_BRAIN_V11":     [16.0991, 20.9883, 26.9063, 39.2331, 42.3277, 43.0189, 42.7671, 45.8317, 45.7129, 51.7295, 55.2941, 66.6024, 67.1877, 67.2623, 65.7733, 63.4061, 60.9021, 60.8899, 53.3666, 72.7814, 71.6309, 71.9968, 78.5661, 80.162, 83.1449, 101.212, 120.0588, 136.4437, 133.7137, 143.2483],
    "ML_BRAIN_V11_OPT": [8.5725, 14.7355, 20.1568, 26.9534, 20.4918, 23.7362, 24.9295, 29.437, 30.2275, 37.7553, 48.0755, 64.3012, 73.3744, 78.1693, 80.3687, 79.4562, 78.8741, 92.4454, 90.1179, 85.6189, 82.8302, 82.4815, 82.1297, 78.8372, 78.9577, 93.7007, 109.6615, 120.5404, 125.1517, 129.7817],
    "ML_V37":           [-2.1358, -4.5231, -9.6494, -7.149, -9.8435, -8.8427, -10.0516, -10.3807, -19.4299, -21.0065, -21.2693, -17.5863, -18.2555, -18.8308, -19.8912, -19.1514, -16.7123, -15.5824, -13.8117, -15.8564, -15.8722, -18.2931, -16.1363, -17.2024, -14.3345, -11.9542, -11.9542, -1.7564, -1.7564, 5.0902],
    "ML_BRAIN_V10":     [-0.1134, 0.3518, 3.0552, -0.8957, -3.3692, -5.8335, -4.4858, -6.9385, -8.6722, -11.4702, -12.9281, -11.9732, -12.2091, -14.194, -15.1748, -14.3779, -14.4284, -18.0003, -20.7285, -25.109, -28.1373, -31.2816, -30.6319, -26.1212, -18.5824, -9.8406, -10.9062, -9.1084, -4.4153, -4.8522],
}

# ── Data ───────────────────────────────────────────────────────────────
DATA = [
    {"r":1,  "n":"V11",              "c":"#6ea8cc","wr":"82.61","ret":"+5.261%","rp":1,"d30":"+2.51%", "d30p":1,"ult":"-1.00%", "up":0},
    {"r":2,  "n":"ML_V97",           "c":"#b070ff","wr":"79.55","ret":"+4.664%","rp":1,"d30":"+6.38%", "d30p":1,"ult":"-2.10%", "up":0},
    {"r":3,  "n":"ML_V39",           "c":"#06d6a0","wr":"65.56","ret":"+0.482%","rp":1,"d30":"+0.51%", "d30p":1,"ult":"+11.45%","up":1},
    {"r":4,  "n":"V13",              "c":"#00ffe0","wr":"60.81","ret":"+6.883%","rp":1,"d30":"+9.48%", "d30p":1,"ult":"-3.28%", "up":0},
    {"r":5,  "n":"ML_V39FULL",       "c":"#818cf8","wr":"59.55","ret":"+0.351%","rp":1,"d30":"+0.40%", "d30p":1,"ult":"+9.54%", "up":1},
    {"r":6,  "n":"ML_V94",           "c":"#f59e0b","wr":"59.52","ret":"+2.728%","rp":1,"d30":"+5.23%", "d30p":1,"ult":"+9.02%", "up":1},
    {"r":7,  "n":"ML_BRAIN_V11",     "c":"#f472b6","wr":"53.57","ret":"+1.853%","rp":1,"d30":"+3.33%", "d30p":1,"ult":"+9.53%", "up":1},
    {"r":8,  "n":"ML_BRAIN_V11_OPT", "c":"#fb923c","wr":"50.00","ret":"+1.312%","rp":1,"d30":"+3.16%", "d30p":1,"ult":"+4.63%", "up":1},
    {"r":9,  "n":"ML_V37",           "c":"#94a3b8","wr":"42.17","ret":"-0.165%","rp":0,"d30":"-0.24%", "d30p":0,"ult":"+6.85%", "up":1},
    {"r":10, "n":"ML_BRAIN_V10",     "c":"#64748b","wr":"39.29","ret":"-0.835%","rp":0,"d30":"-0.74%", "d30p":0,"ult":"-0.44%", "up":0},
]
MEDALS = {1:"🥇",2:"🥈",3:"🥉"}

def wr_color(m):
    v = float(m["wr"])
    if v >= 65: return "#44e890"
    if v >= 55: return "#f5b833"
    return "#fc5c7d"

def pc(pos): return "#44e890" if pos else "#fc5c7d"

# ── SVG Sparkline ──────────────────────────────────────────────────────
def make_spark(model_name, color, variant, prefix, w=84, h=30):
    vals = SPARK_VALS.get(model_name, [0] * 10)
    n = len(vals)
    if n < 2:
        return f'<svg width="{w}" height="{h}"></svg>'
    mn, mx = min(vals), max(vals)
    rng = mx - mn if mx != mn else 1.0
    px = lambda i: 2 + (i / (n - 1)) * (w - 4)
    py = lambda v: h - 3 - (v - mn) / rng * (h - 6)
    pts = [(px(i), py(v)) for i, v in enumerate(vals)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    lx, ly = pts[-1]
    uid = f"{prefix}_{model_name.replace('_','').replace(' ','')}"

    if variant == "line":
        return (
            f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" style="display:block;overflow:visible">'
            f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.2" fill="{color}"/>'
            f'</svg>'
        )
    elif variant == "area":
        pg = f'{pts[0][0]:.1f},{h} {poly} {lx:.1f},{h}'
        return (
            f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" style="display:block;overflow:visible">'
            f'<defs><linearGradient id="g{uid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="{color}" stop-opacity="0.38"/>'
            f'<stop offset="100%" stop-color="{color}" stop-opacity="0.02"/>'
            f'</linearGradient></defs>'
            f'<polygon points="{pg}" fill="url(#g{uid})"/>'
            f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.5" fill="{color}"/>'
            f'</svg>'
        )
    elif variant == "glow":
        return (
            f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" style="display:block;overflow:visible">'
            f'<defs><filter id="f{uid}" x="-25%" y="-80%" width="150%" height="260%">'
            f'<feGaussianBlur in="SourceGraphic" stdDeviation="2.5" result="b"/>'
            f'<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>'
            f'</filter></defs>'
            f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" filter="url(#f{uid})"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.5" fill="{color}" filter="url(#f{uid})"/>'
            f'</svg>'
        )
    return ""




# ── T1 — Compacto Puro (línea fina, ultra-minimal) ─────────────────────
def build_T1():
    rows = []
    for m in DATA:
        bg = "rgba(255,255,255,.02)" if m["r"] % 2 == 0 else "transparent"
        md = MEDALS.get(m["r"], str(m["r"]))
        wrc = wr_color(m)
        spark = make_spark(m["n"], m["c"], "line", "t1")
        rows.append(f"""
<tr style="background:{bg}">
  <td class="t-rk">{md}</td>
  <td class="t-mn">
    <span class="t-dot" style="background:{m['c']}"></span>
    {m['n']}
  </td>
  <td class="t-wr" style="color:{wrc}">{m['wr']}%</td>
  <td class="t-num" style="color:{pc(m['rp'])}">{m['ret']}</td>
  <td class="t-num" style="color:{pc(m['d30p'])}">{m['d30']}</td>
  <td class="t-num" style="color:{pc(m['up'])}">{m['ult']}</td>
  <td class="t-sp">{spark}</td>
</tr>""")
    hdr = '<tr class="t-hrow"><th></th><th class="t-mh">Modelo</th><th class="t-h">WR</th><th class="t-h">Ret</th><th class="t-h">30d</th><th class="t-h">Últ</th><th class="t-h" style="text-align:center">Curva</th></tr>'
    return f'<div class="r-panel"><div class="r-ph">T1 · Compacto Puro</div><table class="t-tbl">{"".join([hdr]+rows)}</table></div>'


# ── T2 — Bloomberg Pro (barra WR, area chart con gradiente) ─────────────
def build_T2():
    rows = []
    for m in DATA:
        wrc = wr_color(m)
        wr_pct = float(m["wr"])
        bg = "rgba(255,255,255,.022)" if m["r"] % 2 == 0 else "transparent"
        md = MEDALS.get(m["r"], str(m["r"]))
        spark = make_spark(m["n"], m["c"], "area", "t2")
        # WR cell: progress bar background
        bar_w = f"{wr_pct:.0f}%"
        wr_cell = (
            f'<td class="t-wrb">'
            f'<div class="wr-bar" style="width:{bar_w};background:{wrc};opacity:.15;"></div>'
            f'<span style="position:relative;color:{wrc};font-weight:900">{m["wr"]}%</span>'
            f'</td>'
        )
        rows.append(f"""
<tr style="background:{bg}">
  <td class="t-rk">{md}</td>
  <td class="t-mn2">
    <span class="t-dot2" style="background:{m['c']}"></span>
    <span class="t-label">{m['n']}</span>
  </td>
  {wr_cell}
  <td class="t-num2" style="color:{pc(m['rp'])}">{m['ret']}</td>
  <td class="t-num2" style="color:{pc(m['d30p'])}">{m['d30']}</td>
  <td class="t-num2" style="color:{pc(m['up'])}">{m['ult']}</td>
  <td class="t-sp">{spark}</td>
</tr>""")
    hdr = '<tr class="t-hrow"><th></th><th class="t-mh">Modelo</th><th class="t-h">WR</th><th class="t-h">Ret</th><th class="t-h">30d</th><th class="t-h">Últ</th><th class="t-h" style="text-align:center">Curva</th></tr>'
    return f'<div class="r-panel"><div class="r-ph">T2 · Bloomberg Pro</div><table class="t-tbl">{"".join([hdr]+rows)}</table></div>'


# ── T3 — Accent Stripe (borde color modelo, WR pill, glow chart) ────────
def build_T3():
    rows = []
    for m in DATA:
        wrc = wr_color(m)
        mc = m["c"]
        md = MEDALS.get(m["r"], str(m["r"]))
        spark = make_spark(m["n"], m["c"], "glow", "t3")
        # subtle tinted row background from model color
        row_bg = f"rgba({int(mc[1:3],16)},{int(mc[3:5],16)},{int(mc[5:7],16)},.04)"
        rows.append(f"""
<tr style="background:{row_bg};box-shadow:inset 2px 0 0 {mc}">
  <td class="t-rk3">{md}</td>
  <td class="t-mn3">
    <span class="t-label3">{m['n']}</span>
  </td>
  <td class="t-wrp">
    <span class="wr-pill" style="background:rgba({int(wrc[1:3],16) if wrc.startswith('#') else 68},{int(wrc[3:5],16) if wrc.startswith('#') else 232},{int(wrc[5:7],16) if wrc.startswith('#') else 144},.15);color:{wrc}">{m['wr']}%</span>
  </td>
  <td class="t-num3" style="color:{pc(m['rp'])}">{m['ret']}</td>
  <td class="t-num3" style="color:{pc(m['d30p'])}">{m['d30']}</td>
  <td class="t-num3" style="color:{pc(m['up'])}">{m['ult']}</td>
  <td class="t-sp3">{spark}</td>
</tr>""")
    hdr = '<tr class="t-hrow3"><th></th><th class="t-mh3">Modelo</th><th class="t-h3">WR</th><th class="t-h3">Ret</th><th class="t-h3">30d</th><th class="t-h3">Últ</th><th class="t-h3" style="text-align:center">Curva</th></tr>'
    return f'<div class="r-panel r-panel3"><div class="r-ph">T3 · Accent Stripe</div><table class="t-tbl3">{"".join([hdr]+rows)}</table></div>'


# ── HTML SHELL ─────────────────────────────────────────────────────────
HTML = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ranking · 3 versiones tabla</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#050810;color:#c8d8f0;
  font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  padding:32px 24px;min-height:100vh}}
.page-title{{
  text-align:center;font-size:10px;font-weight:900;text-transform:uppercase;
  letter-spacing:.26em;color:rgba(120,165,215,.42);margin-bottom:6px}}
.page-sub{{
  text-align:center;font-size:13px;color:rgba(200,220,255,.55);margin-bottom:32px}}
.compare-grid{{
  display:grid;grid-template-columns:repeat(3,1fr);gap:22px;
  max-width:1360px;margin:0 auto}}
.col-label{{
  font-size:9px;font-weight:900;text-transform:uppercase;letter-spacing:.22em;
  text-align:center;padding:10px 12px;margin-bottom:12px;border-radius:9px;cursor:pointer}}
.col-a .col-label{{background:rgba(24,232,200,.1);color:#18e8c8;border:1px solid rgba(24,232,200,.3)}}
.col-b .col-label{{background:rgba(168,130,255,.1);color:#a882ff;border:1px solid rgba(168,130,255,.3)}}
.col-c .col-label{{background:rgba(245,184,51,.1);color:#f5b833;border:1px solid rgba(245,184,51,.3)}}

/* ── Panel shell ── */
.r-panel{{
  background:linear-gradient(180deg,rgba(9,14,30,.99) 0%,rgba(4,7,16,.99) 100%);
  border:1px solid rgba(120,165,215,.15);border-radius:12px;
  padding:14px 13px;overflow:hidden;
  box-shadow:0 24px 60px rgba(0,0,0,.65)}}
.r-panel3{{
  background:linear-gradient(180deg,rgba(8,12,26,.99) 0%,rgba(3,6,15,.99) 100%);
  border:1px solid rgba(120,165,215,.18);border-radius:12px;
  padding:14px 13px;overflow:hidden;
  box-shadow:0 24px 60px rgba(0,0,0,.65)}}
.r-ph{{
  font-size:8px;font-weight:900;text-transform:uppercase;letter-spacing:.2em;
  color:rgba(120,165,215,.42);margin-bottom:11px;padding-bottom:9px;
  border-bottom:1px solid rgba(120,165,215,.1)}}

/* ══════════════════════════════════════
   SHARED TABLE HEADER ROW
══════════════════════════════════════ */
.t-hrow th,.t-hrow3 th{{
  font-size:7px;font-weight:900;text-transform:uppercase;letter-spacing:.16em;
  color:rgba(120,165,215,.4);padding:0 4px 8px;
  border-bottom:1px solid rgba(120,165,215,.14);white-space:nowrap}}
.t-h,.t-h3{{text-align:right}}
.t-mh,.t-mh3{{text-align:left;padding-left:10px}}

/* ══════════════════════════════════════
   T1 — COMPACTO PURO
══════════════════════════════════════ */
.t-tbl{{width:100%;border-collapse:collapse}}
.t-tbl tr{{border-bottom:1px solid rgba(120,165,215,.045);transition:background .1s}}
.t-tbl tr:last-child{{border-bottom:none}}
.t-tbl tr:hover{{background:rgba(255,255,255,.035)!important}}
.t-rk{{width:22px;text-align:center;padding:6px 2px 6px 0;font-size:10px;color:rgba(200,220,255,.45)}}
.t-dot{{display:inline-block;width:6px;height:6px;border-radius:2px;margin-right:5px;flex-shrink:0;vertical-align:middle}}
.t-mn{{padding:6px 4px;white-space:nowrap;font-size:10.5px;font-weight:700;color:#dce8fb;max-width:110px}}
.t-wr{{text-align:right;padding:6px 5px;font-size:12px;font-weight:900;letter-spacing:-.01em;white-space:nowrap}}
.t-num{{text-align:right;padding:6px 4px;font-size:10.5px;font-weight:600;white-space:nowrap}}
.t-sp{{padding:5px 2px 5px 8px;text-align:center;vertical-align:middle}}

/* ══════════════════════════════════════
   T2 — BLOOMBERG PRO
══════════════════════════════════════ */
.t-tbl2{{width:100%;border-collapse:collapse;table-layout:fixed}}
.t-tbl{{table-layout:auto}}
.t-wrb{{position:relative;overflow:hidden;text-align:right;padding:6px 5px;white-space:nowrap;min-width:52px}}
.wr-bar{{position:absolute;top:0;left:0;height:100%;border-radius:2px;transition:width .3s}}
.t-dot2{{display:inline-block;width:8px;height:8px;border-radius:3px;margin-right:6px;vertical-align:middle;flex-shrink:0}}
.t-mn2{{padding:6px 4px;white-space:nowrap;font-size:10.5px;color:#dce8fb;max-width:110px}}
.t-label{{font-weight:700;color:#dce8fb;font-size:10.5px;vertical-align:middle}}
.t-num2{{text-align:right;padding:6px 4px;font-size:10.5px;font-weight:600;white-space:nowrap}}

/* ══════════════════════════════════════
   T3 — ACCENT STRIPE
══════════════════════════════════════ */
.t-tbl3{{width:100%;border-collapse:collapse}}
.t-tbl3 tr{{border-bottom:1px solid rgba(120,165,215,.04);transition:filter .1s}}
.t-tbl3 tr:last-child{{border-bottom:none}}
.t-tbl3 tr:hover{{filter:brightness(1.35)}}
.t-rk3{{width:22px;text-align:center;padding:7px 2px 7px 0;font-size:10px;color:rgba(200,220,255,.45);padding-left:6px}}
.t-mn3{{padding:7px 5px;white-space:nowrap;max-width:112px}}
.t-label3{{font-size:10.5px;font-weight:800;color:#dce8fb}}
.t-wrp{{text-align:right;padding:7px 4px;white-space:nowrap}}
.wr-pill{{
  display:inline-block;padding:2px 7px;border-radius:20px;
  font-size:11.5px;font-weight:900;letter-spacing:-.01em}}
.t-num3{{text-align:right;padding:7px 4px;font-size:10.5px;font-weight:600;white-space:nowrap}}
.t-sp3{{padding:5px 2px 5px 8px;text-align:center;vertical-align:middle}}

@media(max-width:960px){{.compare-grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="page-title">Ranking Panel — 3 versiones Tabla + Sparkline</div>
<div class="page-sub">Elegí el diseño · Columnas: Modelo · WR · Ret · 30d · Últ · Curva</div>

<div class="compare-grid">
  <div class="col col-a">
    <div class="col-label">T1 · Compacto Puro</div>
    {build_T1()}
  </div>
  <div class="col col-b">
    <div class="col-label">T2 · Bloomberg Pro</div>
    {build_T2()}
  </div>
  <div class="col col-c">
    <div class="col-label">T3 · Accent Stripe</div>
    {build_T3()}
  </div>
</div>

</body>
</html>"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"OK → {OUT}")
print(f"URL: http://localhost:8765/_staging_ranking_preview.html")
