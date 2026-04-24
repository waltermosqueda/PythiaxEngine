"""
Build preview_c1_pro.html from dashboard_operativo_aurora_pro.html.
v4 – cambios respecto a v3:
  • Ham button: movido al INTERIOR del sidebar (top), no en topbar
  • Collapsed sidebar: iconos monocromáticos (sin colores), ham como primer icono
  • Hero row: 4 tarjetas (champion + WR leader + ret leader + Señales Vivas)
  • "Señales Vivas" = 4ª tarjeta hero con picks activos del champion
  • Sección "Predicción Viva" full-width ELIMINADA (fusionada en 4ª hero card)
  • Control Operativo ELIMINADO del row-picks
  • Liga expand: sparkline mini en fila expandida
  • Botón Exportar en sidebar con CSV/JSON/Print
  • Heatmap pending: sin animación pulsante, indicador sutil
  • Backup automático a analisis/staging/ antes de sobreescribir
  • Parser-reset absorber rule al inicio del EXTRA_CSS
"""
import argparse
import sys
import re, json, datetime, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.dashboard_c1_contract import (
    MARK_HERO_E,
    MARK_HERO_S,
    MARK_LIGA_E,
    MARK_LIGA_S,
    liga_static_meta,
)
from herramientas.dashboard_paths import EXECUTIVE_HTML, INDEX_HTML, LAB_HTML, dashboard_relative_href
BASE = ROOT / "dashboards" / "maquina_pensante" / "dashboard_operativo_aurora_pro.html"
PROD_OUT = ROOT / "analisis" / "preview_c1_pro.html"
STAGING_DIR = ROOT / "analisis" / "staging"
DEFAULT_TEST_OUT = STAGING_DIR / "preview_c1_pro_test.html"
SNAP = ROOT / "dashboards" / "maquina_pensante" / "tablero_maquina_pensante_snapshot.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Construye C1 Pro desde Aurora Pro. Por defecto escribe a staging/test.",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Permite escribir explicitamente en analisis/preview_c1_pro.html",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Ruta de salida alternativa. Si apunta a produccion, exige --promote.",
    )
    args = parser.parse_args()

    target = args.output if args.output is not None else (PROD_OUT if args.promote else DEFAULT_TEST_OUT)
    if not target.is_absolute():
        target = ROOT / target
    target = target.resolve()

    if args.promote and target != PROD_OUT.resolve():
        parser.error("--promote solo se puede usar con la salida canonica de produccion.")
    if target == PROD_OUT.resolve() and not args.promote:
        parser.error("Escritura a produccion bloqueada: usa --promote o deja la salida por defecto a staging.")

    args.target = target
    return args


ARGS = _parse_args()
OUT = ARGS.target


def _dashboard_href(target_path: Path) -> str:
    return dashboard_relative_href(OUT, target_path)


html = BASE.read_text(encoding='utf-8')

# ─── Leer snapshot para datos iniciales ────────────────────────────────────────
try:
    snap = json.loads(SNAP.read_text(encoding='utf-8'))
except Exception:
    snap = {}

league   = (snap.get('competition_recent') or {}).get('league_equalized') or []
active   = snap.get('active') or {}
run      = (active.get('active_run')) or {}
champion_ver = f"V{active.get('active_version', '13')}"

# Helpers
def _sfmt(v, digits=2, signed=False):
    if v is None: return '—'
    s = '+' if signed and float(v) >= 0 else ''
    return f"{s}{float(v):.{digits}f}%"

def _cumul(vals):
    total, out = 0.0, []
    for v in vals:
        total += float(v or 0)
        out.append(round(total, 2))
    return out

def _spark_from_row(row, color):
    r30  = row.get('recent_30') or {}
    sp   = r30.get('spark_avg_return_pct') or []
    cal  = r30.get('calendar') or []
    # trim trailing zeros
    last = next((i for i in range(len(sp)-1, -1, -1) if abs(sp[i] or 0) > 1e-9), -1)
    if last < 0: last = len(sp) - 1
    sp_t = [sp[i] for i in range(last+1)]
    dt_t = [c['date'] for c in cal[:last+1]]
    dates = [(d.split('-')[2]+'/'+d.split('-')[1]) for d in dt_t if len(d.split('-'))==3]
    vals  = _cumul(sp_t)
    d_json = json.dumps(dates).replace('"', "'")
    v_json = json.dumps(vals)
    # build polyline
    n = len(vals)
    if n < 1: return f"<svg viewBox='0 0 260 60' class='spark'><line x1='4' y1='30' x2='256' y2='30' stroke='{color}' stroke-width='1.5' stroke-dasharray='4,3'/></svg>"
    lo, hi = min(vals), max(vals)
    rng = hi - lo if hi != lo else 1
    pts = []
    for i, v in enumerate(vals):
        x = 4 + (i/(max(n-1,1)))*252
        y = 54 - (v - lo)/rng * 48
        pts.append(f"{x:.1f},{y:.1f}")
    poly = ' '.join(pts)
    lx, ly = pts[-1].split(',')
    return (
        f"<svg viewBox='0 0 260 60' class='spark' data-dates='{d_json}' data-values='{v_json}'>"
        f"<polygon points='4,57 {poly} {lx},57' fill='{color}' opacity='0.13'/>"
        f"<polyline points='{poly}' fill='none' stroke='{color}' stroke-width='2.4' "
        f"stroke-linecap='round' stroke-linejoin='round'/>"
        f"<circle cx='{lx}' cy='{ly}' r='3.5' fill='{color}'/>"
        f"</svg>"
    )

def _hero_card_data(row, color):
    eq  = row.get('equalized_recent') or row.get('window') or {}
    r30 = row.get('recent_30') or {}
    cal = r30.get('calendar') or []
    cal_with = sorted((e for e in cal if e.get('avg_return_pct') is not None), key=lambda e: e['date'])
    last = cal_with[-1] if cal_with else None
    lr_s, ld, lr_css = '—', '', 'neu'
    if last:
        lr = last['avg_return_pct']
        p = last['date'].split('-')
        ld = f"{p[2]}/{p[1]}" if len(p)==3 else last['date']
        lr_s = ('+' if lr >= 0 else '') + f"{lr:.2f}%"
        lr_css = 'pos' if lr >= 0 else 'neg'
    prev_tickers = []
    for e in reversed(cal_with[:-1]):
        for t in (e.get('tickers') or []):
            if t not in prev_tickers: prev_tickers.append(t)
        if len(prev_tickers) >= 5: break
    return {
        'spark': _spark_from_row(row, color),
        'wr_s':  _sfmt(eq.get('accuracy_pct'), 2),
        'ret_s': _sfmt(eq.get('avg_return_pct'), 3, signed=True),
        'best':  _sfmt(eq.get('best_day_return_pct'), 2, signed=True),
        'worst': _sfmt(eq.get('worst_day_return_pct'), 2, signed=True),
        'hits':  eq.get('hits', 0),
        'ev':    eq.get('evaluated', 0),
        'eq_d':  eq.get('equalized_days') or eq.get('active_days') or 0,
        'lr_s': lr_s, 'ld': ld, 'lr_css': lr_css,
        'prev':  ', '.join(prev_tickers[:4]) or '—',
        'picks': ', '.join((row.get('latest_tickers') or [])[:5]) or 'Sin picks',
    }

# Obtener los 3 modelos para hero cards
def _find_row(ver): return next((m for m in league if m.get('version')==ver), None)
def _leader_ret():
    valid = [m for m in league if (m.get('equalized_recent') or m.get('window') or {}).get('avg_return_pct') is not None]
    if not valid: return league[0] if league else None
    return max(valid, key=lambda m: float((m.get('equalized_recent') or m.get('window') or {}).get('avg_return_pct') or -1e18))

champ_row  = _find_row(champion_ver) or (league[0] if league else {})
leader_wr  = league[0] if league else {}
leader_ret = _leader_ret() or (league[0] if league else {})

# Picks vivos del champion
champ_live_tickers = []
for k in ['results_d','results_e','results_e_hw','results_c5','results_a']:
    for p in (run.get(k) or []):
        t = p.get('ticker')
        if t and t not in champ_live_tickers: champ_live_tickers.append(t)

# Override champion picks con live tickers
if champ_row and champ_live_tickers:
    champ_data = _hero_card_data(champ_row, '#18e8c8')
    champ_data['picks'] = ', '.join(champ_live_tickers[:5])
else:
    champ_data = _hero_card_data(champ_row, '#18e8c8') if champ_row else {}
wr_data  = _hero_card_data(leader_wr, '#44e890') if leader_wr else {}
ret_data = _hero_card_data(leader_ret, '#a882ff') if leader_ret else {}

def _hc(row, data, card_class, color, label):
    ver = row.get('version', '?') if row else '?'
    d = data or {}
    return (
        f"<div class='hero-card {card_class} editable-block' data-bid='hero-{ver.lower()}'>"
        f"<div class='hc-label'>{label}</div>"
        f"<div class='hc-model'>{ver}</div>"
        f"<div class='hc-spark'>{d.get('spark','')}</div>"
        f"<div class='hc-wr'>{d.get('wr_s','—')}</div>"
        f"<div class='hc-wr-label'>Win Rate &middot; {d.get('eq_d',0)} ruedas &middot; {d.get('ev',0)} picks</div>"
        f"<div class='hc-round'><span class='hc-round-label'>\u00dalt. rueda {d.get('ld','')}</span>"
        f"<span class='hc-round-val {d.get('lr_css','neu')}'>{d.get('lr_s','—')}</span></div>"
        f"<div class='hc-stats'>"
        f"<div class='kl'><span>Ret medio</span><strong>{d.get('ret_s','—')}</strong></div>"
        f"<div class='kl'><span>Hits</span><strong>{d.get('hits',0)} / {d.get('ev',0)}</strong></div>"
        f"<div class='kl'><span>Mejor rueda</span><strong class='pos'>{d.get('best','—')}</strong></div>"
        f"<div class='kl'><span>Peor rueda</span><strong class='neg'>{d.get('worst','—')}</strong></div>"
        f"</div>"
        f"<div class='hc-picks'>"
        f"<div class='hc-picks-lbl'>Picks anteriores</div>"
        f"<div class='hc-picks-prev'>{d.get('prev','—')}</div>"
        f"<div class='hc-picks-lbl' style='margin-top:6px'>Pr\u00f3ximos picks</div>"
        f"<div class='hc-picks-next'>{d.get('picks','Sin picks')}</div>"
        f"</div>"
        f"</div>"
    )

# ─── 1. TITLE ─────────────────────────────────────────────────────────────────
html = re.sub(r'<title>.*?</title>', '<title>C1 Pro \u00b7 Dashboard Operativo</title>', html, count=1)
html = html.replace('Titan \u00b7 Dashboard Operativo</div>', 'C1 Pro \u00b7 Dashboard Operativo</div>', 1)

# ─── 2. SIDEBAR: ham button + nav fixes + export button ──────────────────────
# Inject ham button at TOP of sidebar-inner (before brand-block)
html = html.replace(
    '<div class="sidebar-inner">\n\n    <div class="brand-block">',
    '<div class="sidebar-inner">\n'
    '    <button class="ham-btn" id="hamBtn" title="Ocultar / mostrar men\u00fa" data-tip="Men\u00fa">&#9776;</button>\n\n'
    '    <div class="brand-block">',
    1
)
# title= attrs on nav links for _apply_snapshot_sections compatibility
html = html.replace('href="#overview">', 'href="#overview" title="Dashboard" data-tip="Dashboard">', 1)
html = html.replace('href="#picks">', 'href="#picks" title="Picks hoy" data-tip="Picks hoy">', 1)
html = html.replace('href="#league">', 'href="#league" title="Liga" data-tip="Liga">', 1)
html = html.replace('href="#models">', 'href="#models" title="Modelos" data-tip="Modelos">', 1)
html = html.replace('href="#heatmap">', 'href="#heatmap" title="Heatmap" data-tip="Heatmap">', 1)
html = re.sub(
    r'href="(?:\.\./)?(?:dashboards/maquina_pensante/)?tablero_maquina_pensante\.html"',
    f'href="{_dashboard_href(INDEX_HTML)}"',
    html,
)
html = re.sub(
    r'href="(?:\.\./)?(?:dashboards/maquina_pensante/)?tablero_maquina_pensante_executive\.html"',
    f'href="{_dashboard_href(EXECUTIVE_HTML)}"',
    html,
)
html = re.sub(
    r'href="(?:\.\./)?(?:dashboards/maquina_pensante/)?tablero_maquina_pensante_lab\.html"',
    f'href="{_dashboard_href(LAB_HTML)}"',
    html,
)
# Add Export button + panel at bottom of sidebar-inner (before /sidebar-inner)
EXPORT_NAV = (
    '\n    <div class="side-section-label">Exportar</div>\n'
    '    <button class="export-toggle-btn" id="exportToggleBtn" title="Exportar datos" data-tip="Exportar">\n'
    '      <span class="sn-icon">\u2193</span><span>Exportar</span>\n'
    '    </button>\n'
    '    <div class="export-panel" id="exportPanel" style="display:none">\n'
    '      <button class="export-opt-btn" data-export="csv">\U0001f4cb CSV &mdash; Liga + Picks</button>\n'
    '      <button class="export-opt-btn" data-export="json">\U0001f4c4 JSON &mdash; Snapshot</button>\n'
    '      <button class="export-opt-btn" data-export="print">\U0001f5a8 PDF &mdash; Imprimir</button>\n'
    '    </div>\n'
)
html = html.replace('  </div><!-- /sidebar-inner -->', EXPORT_NAV + '  </div><!-- /sidebar-inner -->', 1)

# ─── 3. EXTRA CSS ────────────────────────────────────────────────────────────
EXTRA_CSS = """
/* C1PRO-INIT: absorber rule — must be FIRST to survive CSS parser error-recovery
   after the preceding DATA:heatmap-css-end HTML comment marker */
.c1pro-parser-reset{}

/* ═══════════════════════════════════════════════════════════════════════════
   C1 PRO EXTRA STYLES  v3
   ═══════════════════════════════════════════════════════════════════════════ */

/* ── SIDEBAR COLLAPSED → ICON STRIP (52px) ───────────────────────────────── */
body.sidebar-collapsed .sidebar{
  width:52px !important;
  min-width:52px !important;
}
body.sidebar-collapsed .sidebar-tab{
  right:-14px;
}
/* Hide text-only elements */
body.sidebar-collapsed .brand-sub,
body.sidebar-collapsed .side-section-label,
body.sidebar-collapsed .side-views,
body.sidebar-collapsed .side-drawer,
body.sidebar-collapsed .sn-link > span:not(.sn-icon),
body.sidebar-collapsed .sn-tag,
body.sidebar-collapsed .rp-breadth{
  display:none !important;
}
/* Brand: show only "T" */
body.sidebar-collapsed .brand-block{
  text-align:center;
  padding:12px 0 6px;
}
body.sidebar-collapsed .brand-name{
  font-size:11px;
  letter-spacing:.05em;
  text-align:center;
}
/* Regime pill: dot only */
body.sidebar-collapsed .regime-pill{
  justify-content:center;
  padding:5px 0;
  margin:0 6px;
}
/* Nav icons centered, larger */
body.sidebar-collapsed .side-nav{
  gap:2px;
  padding:6px 4px;
}
body.sidebar-collapsed .sn-link{
  justify-content:center;
  padding:11px 0;
  gap:0;
  border-radius:8px;
  position:relative;
}
body.sidebar-collapsed .sn-icon{
  font-size:20px !important;
  width:28px;
  height:28px;
  display:inline-flex;
  align-items:center;
  justify-content:center;
}
/* Tooltip on hover (collapsed mode) */
body.sidebar-collapsed .sn-link[data-tip]::after{
  content:attr(data-tip);
  position:absolute;
  left:56px;
  top:50%;
  transform:translateY(-50%);
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:6px;
  padding:5px 11px;
  font-size:12px;
  font-weight:600;
  color:var(--ink);
  white-space:nowrap;
  pointer-events:none;
  opacity:0;
  transition:opacity .15s;
  z-index:200;
  box-shadow:0 4px 14px rgba(0,0,0,.45);
}
body.sidebar-collapsed .sn-link[data-tip]:hover::after{
  opacity:1;
}

/* ── HAMBURGER BUTTON (inside sidebar) ───────────────────────────────────── */
.ham-btn{
  background:transparent;
  border:none;
  border-bottom:1px solid var(--line);
  border-radius:0;
  color:rgba(255,255,255,.55);
  cursor:pointer;
  font-size:18px;
  padding:10px 14px;
  line-height:1;
  transition:background .15s, color .15s;
  width:100%;
  text-align:left;
  display:flex;
  align-items:center;
  gap:10px;
  user-select:none;
}
.ham-btn:hover{ background:rgba(255,255,255,.06); color:rgba(255,255,255,.85); }

/* Collapsed: ham centered + icon only */
body.sidebar-collapsed .sidebar .ham-btn{
  justify-content:center;
  padding:10px 0;
  border-bottom:1px solid var(--line);
}

/* ── COLLAPSED SIDEBAR: ALL ICONS MONOCHROMATIC ───────────────────────────── */
body.sidebar-collapsed .sn-link{
  color:rgba(255,255,255,.42) !important;
}
body.sidebar-collapsed .sn-icon{
  color:rgba(255,255,255,.42) !important;
}
body.sidebar-collapsed .sn-link:hover,
body.sidebar-collapsed .sn-link.active{
  color:rgba(255,255,255,.85) !important;
  background:rgba(255,255,255,.07);
}
body.sidebar-collapsed .sn-tag{ display:none !important; }

/* ── LOGIN BUTTON ─────────────────────────────────────────────────────────── */
.login-btn{
  background:transparent;
  border:1px solid rgba(24,232,200,.30);
  border-radius:999px;
  color:var(--cyan);
  cursor:pointer;
  font-size:11px;
  font-weight:700;
  padding:7px 13px;
  line-height:1;
  transition:background .15s;
  white-space:nowrap;
}
.login-btn:hover{ background:rgba(24,232,200,.08); }

/* ── THEME TOGGLE BUTTON ─────────────────────────────────────────────────── */
.theme-toggle-btn{
  background:rgba(255,255,255,.06);
  border:1px solid var(--line);
  border-radius:var(--radius);
  color:var(--ink);
  cursor:pointer;
  font-size:12px;
  padding:7px 12px;
  line-height:1;
  transition:background .15s;
  white-space:nowrap;
}
.theme-toggle-btn:hover{ opacity:.8; }

/* ── LIGHT THEME (crema minimalista, contraste alto) ─────────────────────── */
body.theme-white{
  --bg:#f2efe8;
  --bg-gradient:linear-gradient(155deg,#f5f2ec 0%,#eceae2 100%);
  --panel:#ffffff;
  --border:#dedad1;
  --line:#dedad1;
  --ink:#1a1c21;
  --muted:#6b6a74;
  --shadow:0 2px 10px rgba(0,0,0,.07);
  --panel-hover:#f9f7f2;
  --kpi-bg:#ffffff;
  --cyan:#0bb69b;
  --green:#1fa862;
  --rose:#c84150;
  --gold:#b07c12;
  --accent-cyan-bg:rgba(11,182,155,.07);
  --accent-green-bg:rgba(31,168,98,.07);
  --accent-gold-bg:rgba(176,124,18,.07);
  --accent-rose-bg:rgba(200,65,80,.07);
}
body.theme-white .sidebar{
  background:#1d2030;
  border-right-color:#141620;
}
body.theme-white .topbar,
body.theme-white .panel,
body.theme-white .kpi-card{
  border-color:#dedad1;
  box-shadow:0 2px 8px rgba(0,0,0,.06);
}
body.theme-white .data-table thead th{
  background:#f5f2ec;
  color:#5a5962;
}
body.theme-white .data-table tbody tr:hover td{
  background:rgba(0,0,0,.025);
}
body.theme-white .tb-pill{
  background:rgba(0,0,0,.04);
  border-color:#ccc;
  color:#706f7a;
}
body.theme-white .ham-btn,
body.theme-white .theme-toggle-btn{
  border-color:#ccc;
}
body.theme-white .liga-detail-row td{
  background:rgba(0,0,0,.018);
}
body.theme-white .heat-tt{
  background:#fff;
  border-color:#dedad1;
  color:#1a1c21;
}
body.theme-white .hm-table td{
  border-radius:5px;
}

/* ── HERO ROW ─────────────────────────────────────────────────────────────── */
.hero-row{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:var(--gap);
  padding:0 var(--gap);
  margin-bottom:var(--gap);
}
@media(max-width:1024px){ .hero-row{ grid-template-columns:repeat(2,1fr); } }
@media(max-width:640px){  .hero-row{ grid-template-columns:1fr; } }

.hero-card{
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:var(--radius);
  padding:20px 18px 16px;
  display:flex;
  flex-direction:column;
  gap:7px;
  position:relative;
  overflow:hidden;
  box-shadow:var(--shadow);
}
.hero-card::before{
  content:'';
  position:absolute;
  top:0;left:0;right:0;height:3px;
  border-radius:var(--radius) var(--radius) 0 0;
}
.hc-cyan::before  { background:var(--cyan); }
.hc-green::before { background:var(--green); }
.hc-purple::before{ background:#a882ff; }

.hc-label { font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; }
.hc-model { font-size:26px; font-weight:900; letter-spacing:-.03em; line-height:1; }
.hc-cyan  .hc-model { color:var(--cyan); }
.hc-green .hc-model { color:var(--green); }
.hc-purple .hc-model{ color:#a882ff; }

.hc-spark        { width:100%; height:54px; cursor:crosshair; }
.hc-spark svg    { width:100%; height:100%; display:block; overflow:visible; }

.hc-wr      { font-size:32px; font-weight:900; line-height:1; }
.hc-cyan   .hc-wr { color:var(--cyan); }
.hc-green  .hc-wr { color:var(--green); }
.hc-purple .hc-wr { color:#a882ff; }
.hc-wr-label{ font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }

.hc-round{
  display:flex; align-items:center; gap:8px;
  padding:7px 10px; border-radius:6px;
  background:rgba(255,255,255,.03); border:1px solid var(--line);
}
.hc-round-label{ font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; flex:1; }
.hc-round-val{ font-size:17px; font-weight:900; }
.hc-round-val.pos{ color:var(--green); }
.hc-round-val.neg{ color:var(--rose,#f07080); }
.hc-round-val.neu{ color:var(--muted); }

.hc-picks{ margin-top:2px; }
.hc-picks-lbl{ font-size:9px; text-transform:uppercase; letter-spacing:.07em; color:var(--muted); margin-bottom:3px; }
.hc-picks-prev{ font-size:10px; color:var(--muted); line-height:1.4; }
.hc-picks-next{
  font-size:12px; font-weight:700; color:var(--ink);
  background:rgba(255,255,255,.05); padding:5px 8px;
  border-radius:4px; border-left:2px solid; margin-top:4px; line-height:1.4;
}
.hc-cyan   .hc-picks-next{ border-color:var(--cyan); }
.hc-green  .hc-picks-next{ border-color:var(--green); }
.hc-purple .hc-picks-next{ border-color:#a882ff; }
.hc-stats{
  display:grid; grid-template-columns:1fr 1fr;
  gap:3px 12px; margin-top:4px;
  border-top:1px solid var(--line); padding-top:8px;
}

/* ── SPARKLINE HOVER TOOLTIP ──────────────────────────────────────────────── */
#spark-tt{
  position:fixed;
  background:var(--panel,#1a1d24);
  border:1px solid var(--line,rgba(255,255,255,.10));
  border-radius:7px; padding:7px 11px; font-size:11px;
  pointer-events:none; z-index:1200; opacity:0;
  transition:opacity .08s; white-space:nowrap;
  box-shadow:0 4px 16px rgba(0,0,0,.45); min-width:110px;
}
#spark-tt.show{ opacity:1; }
.stt-date{ color:var(--muted,#7a8099); font-size:10px; margin-bottom:2px; }
.stt-val{ font-size:16px; font-weight:900; line-height:1.1; }

/* ── HEATMAP TOOLTIP HTML ─────────────────────────────────────────────────── */
.heat-tt{
  max-width:270px !important; line-height:1.5 !important;
  font-size:11.5px !important; padding:10px 13px !important;
  pointer-events:none;
}
.htt-title{ font-weight:800; font-size:12px; color:var(--cyan); margin-bottom:6px; }
.htt-row{ display:flex; justify-content:space-between; gap:12px;
          border-bottom:1px solid rgba(255,255,255,.06); padding:2px 0; }
.htt-row:last-child{ border-bottom:none; }
.htt-row span{ color:var(--muted); }

/* ── LIGA FULL-WIDTH ──────────────────────────────────────────────────────── */
.liga-full{ margin:0 var(--gap) var(--gap); }

/* ── LIGA BIGGER TRIANGLES + HOVER ───────────────────────────────────────── */
#league .data-table tbody tr.leag-row-clickable,
#league .data-table tbody tr.liga-main-row{
  cursor:pointer; transition:background .1s;
}
#league .data-table tbody tr.leag-row-clickable:hover td,
#league .data-table tbody tr.liga-main-row:hover td{
  background:rgba(255,255,255,.07);
}
#league .data-table tbody tr.leag-row-clickable td:first-child::after,
#league .data-table tbody tr.liga-main-row td:first-child::after{
  content:' \u25b6'; font-size:13px; color:var(--muted);
  margin-left:7px; vertical-align:middle;
}
#league .data-table tbody tr.leag-row-clickable.expanded td:first-child::after,
#league .data-table tbody tr.liga-main-row.expanded td:first-child::after{
  content:' \u25bc'; color:var(--cyan);
}

/* ── LIGA DETAIL ROW (RICHER) ─────────────────────────────────────────────── */
.liga-detail-row td{
  background:rgba(255,255,255,.025);
  padding:16px 20px 18px; border-bottom:1px solid var(--line);
}
.liga-detail-inner{
  display:grid; grid-template-columns:repeat(4,1fr); gap:10px 20px;
}
@media(max-width:900px){ .liga-detail-inner{ grid-template-columns:repeat(3,1fr); } }
@media(max-width:640px){ .liga-detail-inner{ grid-template-columns:repeat(2,1fr); } }
.liga-detail-inner .kl span{
  font-size:10px; color:var(--muted); text-transform:uppercase;
  letter-spacing:.06em; display:block; margin-bottom:2px;
}
.liga-detail-inner .kl strong{ font-size:13px; font-weight:700; }
.liga-detail-inner .kl strong.pos{ color:var(--green); }
.liga-detail-inner .kl strong.neg{ color:var(--rose,#f07080); }
.liga-detail-signal{
  grid-column:1/-1; background:rgba(255,255,255,.03);
  border:1px solid var(--line); border-radius:5px;
  padding:6px 10px; font-size:10px; color:var(--muted); margin-top:6px;
}
.liga-detail-signal b{ color:var(--cyan); }


/* ── SEÑALES VIVAS (4ª hero card) ─────────────────────────────────────────── */
.hc-gold::before{ background:#f5b833; }
.hc-gold .hc-model{ color:#f5b833; }
.hc-gold .hc-wr{ color:#f5b833; }
.sv-regime-row{
  display:flex; align-items:center; gap:8px; margin:6px 0;
}
.sv-pred-for{ font-size:11px; color:var(--muted); }
.sv-sig-block{ margin:6px 0; }
.sv-sig-name{
  font-size:9px; text-transform:uppercase; letter-spacing:.09em;
  color:var(--cyan); font-weight:800; margin-bottom:4px;
}
.sv-tickers{
  font-size:12px; font-weight:700; color:var(--ink);
  background:rgba(255,255,255,.04); padding:5px 8px;
  border-radius:4px; border-left:2px solid var(--cyan);
  line-height:1.5;
}
.hc-gold .sv-tickers{ border-left-color:#f5b833; }
.sv-footer{
  display:flex; justify-content:space-between; margin-top:8px;
  font-size:10px; color:var(--muted); border-top:1px solid var(--line); padding-top:6px;
}
.sv-empty{ color:var(--muted); font-style:italic; padding:16px 0; text-align:center; font-size:12px; }
/* ── SEÑALES VIVAS: signal board ────────────────────────────────────────── */
.svb-champion{
  background:rgba(255,255,255,.04); border-radius:7px;
  border:1px solid rgba(255,255,255,.09); padding:8px; margin:6px 0 4px;
}
.svb-champ-head{
  display:flex; align-items:center; gap:6px; margin-bottom:6px; flex-wrap:wrap;
}
.svb-champ-ver{ font-size:15px; font-weight:900; }
.svb-champ-badge{
  font-size:8px; font-weight:800; background:#18e8c818; color:#18e8c8;
  border:1px solid #18e8c830; border-radius:3px; padding:1px 5px;
  text-transform:uppercase; letter-spacing:.08em;
}
.svb-champ-kpi{ font-size:9px; color:var(--muted); margin-left:auto; }
.svb-sig-line{
  display:flex; align-items:center; gap:6px; min-height:20px; margin:2px 0;
}
.svb-sig-tag{
  font-size:8px; font-weight:800; border:1px solid; border-radius:3px;
  padding:1px 4px; flex-shrink:0; text-transform:uppercase;
  letter-spacing:.05em; min-width:30px; text-align:center;
}
.svb-sig-tickers{
  font-size:11px; font-weight:700; color:var(--ink);
  flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
.svb-sig-empty-lbl{ font-size:10px; color:var(--muted); font-style:italic; }
.svb-sig-n{ font-size:9px; color:var(--muted); flex-shrink:0; }
.svb-sig-off .svb-sig-tag{ opacity:.45; }
.svb-list{
  overflow-y:auto; max-height:200px; display:flex; flex-direction:column; gap:3px;
  scrollbar-width:thin; scrollbar-color:rgba(255,255,255,.1) transparent;
}
.svb-row{
  padding:5px 7px; border-radius:5px; background:rgba(255,255,255,.03);
  border:1px solid rgba(255,255,255,.05);
}
.svb-row:hover{ background:rgba(255,255,255,.07); }
.svb-row-head{ display:flex; align-items:center; gap:6px; margin-bottom:2px; }
.svb-rver{ font-size:12px; font-weight:800; }
.svb-rkpi{ font-size:9px; color:var(--muted); margin-left:auto; }
.svb-picks-now{ font-size:10px; color:var(--ink); margin:1px 0; }
.svb-picks-now strong{ font-weight:700; }
.svb-picks-prev{ font-size:9px; color:var(--muted); }
.svb-lbl{
  font-size:8px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--muted); font-weight:700; margin-right:3px;
}

/* ── EXPORT BUTTON ────────────────────────────────────────────────────────── */
.export-toggle-btn{
  width:calc(100% - 20px); margin:4px 10px 0;
  background:rgba(255,255,255,.04); border:1px solid var(--line);
  border-radius:6px; color:var(--muted); cursor:pointer;
  font-size:11px; font-weight:700; padding:8px 10px;
  display:flex; align-items:center; gap:8px;
  transition:background .13s, color .13s;
}
.export-toggle-btn:hover{ background:rgba(255,255,255,.09); color:var(--ink); }
.export-panel{
  margin:6px 10px; display:flex; flex-direction:column; gap:4px;
}
.export-opt-btn{
  background:rgba(255,255,255,.03); border:1px solid var(--line);
  border-radius:5px; color:var(--muted); cursor:pointer;
  font-size:10px; padding:6px 10px; text-align:left;
  transition:background .12s, color .12s;
}
.export-opt-btn:hover{ background:rgba(255,255,255,.08); color:var(--ink); }
body.sidebar-collapsed .export-toggle-btn,
body.sidebar-collapsed .export-panel{ display:none !important; }

/* ── HEATMAP PENDING: no animation, just subtle open indicator ───────────── */
.hm-active-pending{
  border:1px dashed rgba(24,232,200,.35) !important;
  background:rgba(24,232,200,.04) !important;
  animation:none !important;
}
.hm-active-pending .hm-ret{
  color:var(--muted) !important;
  font-size:9px !important;
  font-weight:600 !important;
}
.hm-active-pending .hm-meta{
  color:var(--muted) !important;
  opacity:.65 !important;
}
th.hm-active-pending-hdr{
  color:var(--muted) !important;
  opacity:.7 !important;
}

/* ── LIGA EXPAND SPARKLINE ────────────────────────────────────────────────── */
.liga-expand-spark{
  margin-top:12px; padding-top:10px;
  border-top:1px solid var(--line);
}
.liga-expand-spark svg{ width:100%; height:48px; display:block; overflow:visible; }
.liga-expand-spark-label{
  font-size:9px; color:var(--muted); text-transform:uppercase;
  letter-spacing:.07em; margin-bottom:4px;
}
"""
html = html.replace('</style>', EXTRA_CSS + '\n</style>', 1)

# ─── 4. TOPBAR: LOGIN + THEME TOGGLE (ham moved to sidebar in step 2) ────────
html = html.replace(
    '<button class="tb-edit-btn" id="editModeBtn"',
    '<button class="login-btn" id="loginBtn" title="Login">\u2299 Login</button>\n      '
    '<button class="theme-toggle-btn" id="themeToggle">\u2600 Claro</button>\n      '
    '<button class="tb-edit-btn" id="editModeBtn"'
)

# ─── 5. BUILD SEÑALES VIVAS (4ª hero card) ───────────────────────────────────
regime_label = run.get('regime_label', '—')
pred_for     = run.get('prediction_for', '—')
breadth      = run.get('breadth_pct')
breadth_s    = f"{float(breadth):.0f}%" if breadth is not None else '—'

def _senales_vivas_card():
    sigs = [
        ('Signal D &mdash; Liderazgo',       '#18e8c8', run.get('results_d') or []),
        ('Signal C5 &mdash; Crash',           '#44e890', run.get('results_c5') or []),
        ('Signal A &mdash; Mean Rev',         '#a882ff', run.get('results_a') or []),
        ('Signal E_HW &mdash; RS New High',   '#f5b833', run.get('results_e') or run.get('results_e_hw') or []),
    ]
    total_picks = sum(len(r) for _, _, r in sigs)
    regime_cls = 'regime-peligro' if regime_label.upper() == 'PELIGRO' else 'regime-seguro'
    parts = [
        f"<div class='sv-regime-row'>"
        f"<span class='pv-regime {regime_cls}'>{regime_label}</span>"
        f"<span class='sv-pred-for'>Para {pred_for}</span>"
        f"</div>"
    ]
    has = any(r for _, _, r in sigs)
    if not has:
        parts.append("<div class='sv-empty'>Sin se\u00f1ales activas hoy</div>")
    else:
        for sname, color, results in sigs:
            if not results: continue
            tickers = ' &middot; '.join(p.get('ticker', '?') for p in results[:6])
            parts.append(
                f"<div class='sv-sig-block'>"
                f"<div class='sv-sig-name' style='color:{color}'>{sname}</div>"
                f"<div class='sv-tickers' style='border-left-color:{color}'>{tickers}</div>"
                f"</div>"
            )
    mem = run.get('memory_context') or []
    if mem:
        parts.append(
            f"<div class='sv-footer'>"
            f"<span>breadth {breadth_s}</span>"
            f"<span>{total_picks} picks hoy</span>"
            f"</div>"
        )
    else:
        parts.append(
            f"<div class='sv-footer'>"
            f"<span>breadth {breadth_s}</span>"
            f"<span>{total_picks} picks</span>"
            f"</div>"
        )
    return (
        f"<div class='hero-card hc-gold editable-block' data-bid='hero-signals'>"
        f"<div class='hc-label'>\u26a1 Se\u00f1ales Vivas</div>"
        f"<div class='hc-model' style='font-size:20px'>V{active.get('active_version',13)}</div>"
        f"{''.join(parts)}"
        f"</div>"
    )

# ─── 5b. BUILD HERO ROW HTML (4 cards, DATA markers) ─────────────────────────
HERO_ROW = f"""
  <!-- HERO ROW ─────────────────────────────────────────────────────────────── -->
  <section class="hero-row hero-row-4" id="hero">
{MARK_HERO_S}
{_hc(champ_row, champ_data, 'hc-cyan', '#18e8c8', '\U0001f3c6 Champion activo')}
{_hc(leader_wr, wr_data,    'hc-green', '#44e890', '\U0001f3af Mayor Win Rate')}
{_hc(leader_ret,ret_data,   'hc-purple', '#a882ff', '\U0001f4c8 Mayor Retorno')}
{_senales_vivas_card()}
{MARK_HERO_E}
  </section>
"""
# Add 4-col hero grid CSS
HERO_GRID_CSS = """
/* 4-column hero row */
.hero-row-4{ grid-template-columns:repeat(4,1fr) !important; }
@media(max-width:1200px){ .hero-row-4{ grid-template-columns:repeat(2,1fr) !important; } }
@media(max-width:640px){  .hero-row-4{ grid-template-columns:1fr !important; } }
"""
html = html.replace('</style>', HERO_GRID_CSS + '\n</style>', 1)

# ─── 7. BUILD FULL-WIDTH LIGA SECTION ─────────────────────────────────────────
def _liga_static(ver):
    return liga_static_meta(ver)

def _badge(role):
    MAP = {'activo':'ba-active','referencia':'ba-ref','base':'ba-base','observado':'ba-obs','legacy_ml':'ba-ml'}
    cls = MAP.get(role, 'ba-obs')
    label = role.replace('_',' ')
    return f"<span class='badge {cls}'>{label}</span>"

def _ult_cell(win):
    if not win: return '—'
    cal = win.get('calendar') or []
    for e in reversed(cal):
        r = e.get('avg_return_pct')
        if r is not None:
            p  = e.get('date','').split('-')
            df = f"{p[2]}/{p[1]}" if len(p)==3 else ''
            sg = '+' if r >= 0 else ''
            cs = 'pos' if r >= 0 else 'neg'
            return f"<strong class='{cs}'>{sg}{r:.2f}%</strong><br><small class='muted-td'>{df}</small>"
    return '—'

liga_leader = league[0] if league else {}
liga_leader_eq = (liga_leader.get('equalized_recent') or liga_leader.get('window') or {})
liga_leader_ver = liga_leader.get('version', '—')
liga_leader_wr  = _sfmt(liga_leader_eq.get('accuracy_pct'), 2)
liga_leader_ret = _sfmt(liga_leader_eq.get('avg_return_pct'), 3, signed=True)

liga_rows_html = []
for i, m in enumerate(league, 1):
    ver  = m.get('version', '?')
    role = m.get('role', '')
    eq   = m.get('equalized_recent') or m.get('window') or {}
    r30  = m.get('recent_30') or {}
    stale= m.get('stale_market_days')
    wr   = eq.get('accuracy_pct')
    ret  = eq.get('avg_return_pct')
    eq_d = eq.get('equalized_days') or eq.get('active_days') or 0
    ev   = eq.get('evaluated', 0)
    tickers = m.get('latest_tickers') or []
    wr_s  = _sfmt(wr, 2)
    ret_s = _sfmt(ret, 3, signed=True)
    wr_css = 'pos' if (wr or 0) >= 60 else ('neg' if (wr or 0) < 50 else '')
    tickers_s = ', '.join(tickers[:5]) or 'Sin picks'
    freshness = f"<span class='badge ba-fresh'>al d&iacute;a</span>" if (stale is None or stale == 0) else f"<span class='badge ba-warn'>{stale}d</span>"
    st = _liga_static(ver)
    best_raw  = eq.get('best_day_return_pct')
    worst_raw = eq.get('worst_day_return_pct')
    best_s  = ('+' if (best_raw or 0) >= 0 else '') + f"{best_raw:.2f}%" if best_raw is not None else '—'
    worst_s = ('+' if (worst_raw or 0) >= 0 else '') + f"{worst_raw:.2f}%" if worst_raw is not None else '—'
    # 30-round context from actual recent_30
    wr30   = r30.get('accuracy_pct')
    ret30  = r30.get('avg_return_pct')
    ad30   = r30.get('active_days') or r30.get('equalized_days') or 0
    w30_s  = f"{wr30:.0f}%/{'+' if (ret30 or 0)>=0 else ''}{ret30:.1f}% ({ad30}d)" if wr30 is not None and ret30 is not None else '—'
    # Sparkline data for expand row
    role_color = {'activo':'#18e8c8','referencia':'#f5b833','base':'#6ea8cc','observado':'#44e890','legacy_ml':'#a882ff'}.get(role,'#6ea8cc')
    sp_raw  = (r30.get('spark_avg_return_pct') or [])
    last_sp = next((i for i in range(len(sp_raw)-1,-1,-1) if abs(sp_raw[i] or 0)>1e-9), len(sp_raw)-1)
    sp_vals = _cumul([sp_raw[i] for i in range(last_sp+1)])
    sp_json = json.dumps(sp_vals)
    liga_rows_html.append(
        f"<tr data-bid='leag-{ver}' data-blabel='{ver}' class='leag-row-clickable editable-block' "
        f"data-sharpe='{st.get('sharpe','—')}' data-mdd='{st.get('mdd','—')}' "
        f"data-best='{best_s}' data-worst='{worst_s}' "
        f"data-signal='{st.get('signal','—')}' data-universe='{st.get('universe','—')}' "
        f"data-w30='{w30_s}' data-prev-picks='{st.get('prev','')}' "
        f"data-spark-vals='{sp_json}' data-spark-color='{role_color}'>"
        f"<td><span class='rank-num'>{i}</span></td>"
        f"<td><strong>{ver}</strong> {_badge(role)}</td>"
        f"<td>{freshness}</td>"
        f"<td><strong class='{wr_css}'>{wr_s}</strong><br><small>{ret_s}</small></td>"
        f"<td><small>{eq_d}/{eq_d} &middot; {ev} picks</small></td>"
        f"<td class='muted-td ticker-list'>{tickers_s}</td>"
        f"<td class='ult-rueda-td'>{_ult_cell(eq)}</td>"
        f"</tr>"
    )

LIGA_SECTION = f"""
  <!-- LIGA PRINCIPAL ──────────────────────────────────────────────────────── -->
  <section class="panel liga-full editable-block" data-bid="liga-panel" id="league">
    <div class="panel-head">
      <div>
        <div class="panel-label">Liga principal</div>
        <h2 class="panel-title">Ranking igualado &middot; {(league[0].get('equalized_recent') or league[0].get('window') or {}).get('equalized_days', 6) if league else 6} ruedas</h2>
      </div>
    </div>
    <div class="leader-strip">
      <div class="ls-info">
        <div class="ls-version">{liga_leader_ver}</div>
        <div class="ls-sub">l&iacute;der actual &middot; WR {liga_leader_wr} &middot; ret {liga_leader_ret}</div>
      </div>
    </div>
    <table class="data-table">
{MARK_LIGA_S}
<thead><tr><th>#</th><th>Modelo</th><th>Estado</th><th>WR / Ret</th><th>Muestra &middot; Picks</th><th>Picks actuales</th><th>&Uacute;lt. Rueda</th></tr></thead>
<tbody>
{''.join(liga_rows_html)}
</tbody>
{MARK_LIGA_E}
    </table>
  </section>
"""

# ─── 8. REPLACE row-2-3 WITH HERO (4 cards) + LIGA ──────────────────────────
row23_pat = re.compile(r'[ \t]*<!-- ROW 1: CHAMPION \+ LIGA.*?</div><!-- /row-2-3 -->', re.DOTALL)
m = row23_pat.search(html)
if m:
    html = html[:m.start()] + HERO_ROW + LIGA_SECTION + html[m.end():]
    print("[OK] Replaced row-2-3 with 4-card hero+liga (no pred-viva section)")
else:
    div_pat = re.compile(r'  <div class="row-2-3" id="champion">.*?</div><!-- /row-2-3 -->', re.DOTALL)
    m2 = div_pat.search(html)
    if m2:
        html = html[:m2.start()] + HERO_ROW + LIGA_SECTION + html[m2.end():]
        print("[OK fallback] Replaced row-2-3 with 4-card hero+liga")
    else:
        print("[WARN] Could not find row-2-3 block!")

# ─── 9. REORDER: HEATMAP BEFORE MODEL CARDS ─────────────────────────────────
# picks-panel (row-1-1) y DATA completa (liga completa) ya eliminados del HTML
marks = {
    'scanners_start':  re.search(r'  <!-- MODELOS SCANNER',                 html),
    'heatmap_start':   re.search(r'  <!-- HEATMAP',                         html),
    'overlap_start':   re.search(r'  <!-- OVERLAP MATRIX',                  html),
    'footer_start':    re.search(r'  <div class="page-footer">',            html),
    'mainwrap_end':    re.search(r'</div><!-- /main-wrap -->',               html),
}
missing = [k for k, v in marks.items() if v is None]
if missing:
    print(f"[WARN] Missing markers: {missing} — skipping reorder")
else:
    p_scan_s     = marks['scanners_start'].start()
    p_heat_s     = marks['heatmap_start'].start()
    p_overlap_s  = marks['overlap_start'].start()
    p_footer_s   = marks['footer_start'].start()
    p_mainwrap_e = marks['mainwrap_end'].end()

    prefix   = html[:p_heat_s]
    scanlega = html[p_scan_s  : p_heat_s]
    heatmap  = html[p_heat_s  : p_overlap_s]
    overlap  = html[p_overlap_s : p_footer_s]
    footer   = html[p_footer_s : p_mainwrap_e]
    suffix   = html[p_mainwrap_e:]

    html = (
        prefix +
        '\n' + heatmap +
        '\n\n' +
        scanlega +
        overlap +
        footer +
        suffix
    )
    print("[OK] Reordered: heatmap before models; picks-panel y DATA completa eliminados")

# ─── 10. ADD #spark-tt DIV ────────────────────────────────────────────────────
html = html.replace(
    '<div class="heat-tt" id="heatTT"></div>',
    '<div class="heat-tt" id="heatTT"></div>\n<div id="spark-tt"><div class="stt-date"></div><div class="stt-val"></div></div>'
)

# ─── 11. ADD JS ───────────────────────────────────────────────────────────────
NEW_JS = r"""
/* ════════════════════════════════════════════════════════════════════════════
   C1 PRO EXTRA JS  v4
   ════════════════════════════════════════════════════════════════════════════ */

/* ── SIDEBAR data-tip para tooltips en modo colapsado ────────────────────── */
(function(){
  document.querySelectorAll('.sn-link,[data-tip]').forEach(function(el){
    if(!el.getAttribute('data-tip') && el.classList.contains('sn-link')){
      var textSpan = Array.from(el.querySelectorAll('span'))
        .find(function(s){ return !s.classList.contains('sn-icon') && !s.classList.contains('sn-tag'); });
      if(textSpan) el.setAttribute('data-tip', textSpan.textContent.trim());
    }
  });
})();

/* ── HAMBURGER BUTTON (inside sidebar, synced with sidebar-tab) ──────────── */
(function(){
  var hamBtn = document.getElementById('hamBtn');
  var tab    = document.getElementById('sidebarTab');
  if(!hamBtn || !tab) return;
  hamBtn.addEventListener('click', function(){ tab.click(); });
  function syncHam(){
    var c = document.body.classList.contains('sidebar-collapsed');
    hamBtn.title = c ? 'Mostrar men\u00fa' : 'Ocultar men\u00fa';
  }
  try{ new MutationObserver(syncHam).observe(document.body,{attributes:true,attributeFilter:['class']}); }catch(e){}
  syncHam();
})();

/* ── LOGIN BUTTON ─────────────────────────────────────────────────────────── */
(function(){
  var btn = document.getElementById('loginBtn');
  if(!btn) return;
  btn.addEventListener('click', function(){
    alert('Login: funci\u00f3n en desarrollo.');
  });
})();

/* ── THEME TOGGLE ─────────────────────────────────────────────────────────── */
(function(){
  var btn  = document.getElementById('themeToggle');
  var body = document.body;
  if(!btn) return;
  if(localStorage.getItem('titan-theme')==='white'){
    body.classList.add('theme-white'); btn.textContent='\uD83C\uDF19 Oscuro';
  }
  btn.addEventListener('click', function(){
    if(body.classList.contains('theme-white')){
      body.classList.remove('theme-white'); btn.textContent='\u2600 Claro';
      localStorage.setItem('titan-theme','dark');
    } else {
      body.classList.add('theme-white'); btn.textContent='\uD83C\uDF19 Oscuro';
      localStorage.setItem('titan-theme','white');
    }
  });
})();

/* ── HEATMAP TOOLTIP (data-tip + innerHTML) ──────────────────────────────── */
(function(){
  var tt = document.getElementById('heatTT');
  if(!tt) return;
  document.querySelectorAll('.hm-table td[data-tip]').forEach(function(cell){
    cell.addEventListener('mouseenter', function(){
      var raw = (cell.getAttribute('data-tip')||'').trim();
      if(!raw){ return; }
      var parts = raw.split(' | ');
      var head  = parts[0] || raw;
      var hsp   = head.split(' ');
      var model = hsp[0]; var date  = hsp.slice(1).join(' ');
      var html  = '<div class="htt-title">' + model +
                  '<span style="font-weight:400;font-size:10px;color:var(--muted);margin-left:6px">'+date+'</span></div>';
      for(var i=1;i<parts.length;i++){
        var p = parts[i].trim();
        var retM  = p.match(/^ret\s+(.+)$/i);
        var wrM   = p.match(/^WR\s+(.+)$/i);
        var pickM = p.match(/^(\d+)\s+picks?$/i);
        if(retM){
          var cls = retM[1].indexOf('-')===0 ? 'style="color:var(--rose,#f07080)"' : 'style="color:var(--green)"';
          html += '<div class="htt-row"><span>Retorno</span><strong '+cls+'>'+retM[1]+'</strong></div>';
        } else if(wrM){
          html += '<div class="htt-row"><span>Win Rate</span><strong>'+wrM[1]+'</strong></div>';
        } else if(pickM){
          html += '<div class="htt-row"><span>Picks</span><strong>'+pickM[1]+'</strong></div>';
        } else {
          html += '<div class="htt-row"><span>Activos</span><strong>'+p+'</strong></div>';
        }
      }
      tt.innerHTML = html;
      tt.classList.add('show');
    });
    cell.addEventListener('mousemove', function(e){
      tt.style.left=(e.clientX+14)+'px'; tt.style.top=(e.clientY-8)+'px';
    });
    cell.addEventListener('mouseleave', function(){ tt.classList.remove('show'); });
  });
})();

/* ── SPARKLINE HOVER (date + value tooltip) ──────────────────────────────── */
(function(){
  var tt = document.getElementById('spark-tt');
  if(!tt) return;
  document.querySelectorAll('.hc-spark svg[data-values]').forEach(function(svg){
    var rawD = svg.getAttribute('data-dates')  || '[]';
    var rawV = svg.getAttribute('data-values') || '[]';
    var dates, vals;
    try{ dates=JSON.parse(rawD.replace(/'/g,'"')); vals=JSON.parse(rawV); }catch(e){ return; }
    var n = Math.min(dates.length, vals.length);
    if(!n) return;
    var card  = svg.closest ? svg.closest('.hero-card') : null;
    var color = '#18e8c8';
    if(card){
      if(card.classList.contains('hc-green'))  color='#44e890';
      if(card.classList.contains('hc-purple')) color='#a882ff';
    }
    var NS='http://www.w3.org/2000/svg';
    var line = document.createElementNS(NS,'line');
    line.setAttribute('stroke',color); line.setAttribute('stroke-width','1');
    line.setAttribute('stroke-dasharray','3,3');
    line.setAttribute('y1','0'); line.setAttribute('y2','60');
    line.style.cssText='opacity:0;pointer-events:none;transition:opacity .08s';
    svg.appendChild(line);
    var dot = document.createElementNS(NS,'circle');
    dot.setAttribute('r','4'); dot.setAttribute('fill',color);
    dot.setAttribute('stroke','var(--bg,#0e1117)'); dot.setAttribute('stroke-width','1.5');
    dot.style.cssText='opacity:0;pointer-events:none;transition:opacity .08s';
    svg.appendChild(dot);
    var minV=Math.min.apply(null,vals), maxV=Math.max.apply(null,vals);
    function valToY(v){ if(maxV===minV) return 30; return 6+(1-(v-minV)/(maxV-minV))*48; }
    svg.addEventListener('mousemove',function(e){
      var rect=svg.getBoundingClientRect(); if(!rect.width) return;
      var ratio=(e.clientX-rect.left)/rect.width;
      var idx=Math.round(Math.max(0,Math.min(n-1,ratio*(n-1))));
      var px=4+idx/(n-1)*(256-4); var py=valToY(vals[idx]);
      line.setAttribute('x1',px); line.setAttribute('x2',px); line.style.opacity='0.75';
      dot.setAttribute('cx',px); dot.setAttribute('cy',py); dot.style.opacity='1';
      var v=vals[idx]; var sign=v>=0?'+':'';
      tt.querySelector('.stt-date').textContent='Sem. '+(dates[idx]||'—');
      tt.querySelector('.stt-val').textContent=sign+v.toFixed(1)+'% ret. acum.';
      tt.querySelector('.stt-val').style.color=color;
      tt.style.left=(e.clientX+16)+'px'; tt.style.top=(e.clientY-40)+'px';
      tt.classList.add('show');
    });
    svg.addEventListener('mouseleave',function(){
      line.style.opacity='0'; dot.style.opacity='0'; tt.classList.remove('show');
    });
  });
})();

/* ── LIGA EXPAND ROWS (with sparkline) ───────────────────────────────────── */
function buildLigaSpark(vals,color,w,h){
  if(!vals||vals.length<2) return '';
  var n=vals.length,lo=Math.min.apply(null,vals),hi=Math.max.apply(null,vals),rng=hi-lo||1,pts=[];
  for(var i=0;i<n;i++){ var x=4+(i/(n-1))*(w-8),y=h-4-((vals[i]-lo)/rng)*(h-8); pts.push(x.toFixed(1)+','+y.toFixed(1)); }
  var line=pts.join(' '),lx=pts[n-1].split(',')[0],ly=pts[n-1].split(',')[1];
  return '<svg viewBox="0 0 '+w+' '+h+'" style="width:100%;height:'+h+'px;display:block;overflow:visible">'
    +'<polygon points="4,'+(h-2)+' '+line+' '+lx+','+(h-2)+'" fill="'+color+'" opacity="0.12"/>'
    +'<polyline points="'+line+'" fill="none" stroke="'+color+'" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
    +'<circle cx="'+lx+'" cy="'+ly+'" r="3" fill="'+color+'"/></svg>';
}

function initLigaExpand(){
  var section=document.getElementById('league');
  if(!section) return;
  var tbody=section.querySelector('table tbody');
  if(!tbody) return;
  function attachExpand(){
    var rows=Array.from(tbody.querySelectorAll('tr.leag-row-clickable,tr.liga-main-row'));
    rows.forEach(function(row){
      if(row._expandAttached) return;
      row._expandAttached=true;
      row.addEventListener('click',function(e){
        if(e.target.tagName==='A') return;
        var wasExpanded=row.classList.contains('expanded');
        tbody.querySelectorAll('.liga-detail-row').forEach(function(dr){ dr.remove(); });
        tbody.querySelectorAll('tr').forEach(function(r){ r.classList.remove('expanded'); });
        if(!wasExpanded){
          row.classList.add('expanded');
          var cells=row.querySelectorAll('td');
          var estado=cells[2]?cells[2].textContent.trim():'—';
          var wrTxt=cells[3]?cells[3].innerText.trim():'—';
          var wrLines=wrTxt.split('\n');
          var wr=wrLines[0]||'—',ret=wrLines[1]||'—';
          var muestra=cells[4]?cells[4].textContent.trim():'—';
          var picks=cells[5]?cells[5].textContent.trim():'—';
          var ultRaw=cells[6]?cells[6].textContent.trim():'—';
          var ultCls=ultRaw.indexOf('-')===0?'neg':(ultRaw!=='—'&&ultRaw!==''?'pos':'');
          var sharpe=row.getAttribute('data-sharpe')||'—';
          var mdd=row.getAttribute('data-mdd')||'—';
          var best=row.getAttribute('data-best')||'—';
          var worst=row.getAttribute('data-worst')||'—';
          var signal=row.getAttribute('data-signal')||'—';
          var universe=row.getAttribute('data-universe')||'—';
          var w30=row.getAttribute('data-w30')||'—';
          var prevPicks=row.getAttribute('data-prev-picks')||'—';
          var sparkValsRaw=row.getAttribute('data-spark-vals')||'[]';
          var sparkColor=row.getAttribute('data-spark-color')||'#18e8c8';
          var retCls=ret.indexOf('-')===0?'neg':'pos';
          var bestCls=best.indexOf('-')===0?'neg':'pos';
          var worstCls=worst.indexOf('-')===0?'neg':'pos';
          var sparkHtml='';
          try{
            var sv=JSON.parse(sparkValsRaw);
            if(sv.length>1) sparkHtml='<div class="liga-expand-spark"><div class="liga-expand-spark-label">Retorno acumulado (30 ruedas)</div>'+buildLigaSpark(sv,sparkColor,560,44)+'</div>';
          }catch(ex){}
          var dr=document.createElement('tr');
          dr.className='liga-detail-row';
          dr.innerHTML='<td colspan="'+row.cells.length+'">'+
            '<div class="liga-detail-inner">'+
            '<div class="kl"><span>Win Rate</span><strong class="pos">'+wr+'</strong></div>'+
            '<div class="kl"><span>Ret. Promedio</span><strong class="'+retCls+'">'+ret+'</strong></div>'+
            '<div class="kl"><span>\u00dalt. Rueda</span><strong class="'+ultCls+'">'+ultRaw+'</strong></div>'+
            '<div class="kl"><span>Muestra</span><strong>'+muestra+'</strong></div>'+
            '<div class="kl"><span>Mejor rueda</span><strong class="'+bestCls+'">'+best+'</strong></div>'+
            '<div class="kl"><span>Peor rueda</span><strong class="'+worstCls+'">'+worst+'</strong></div>'+
            '<div class="kl"><span>Max Drawdown</span><strong class="neg">'+mdd+'</strong></div>'+
            '<div class="kl"><span>Sharpe</span><strong>'+sharpe+'</strong></div>'+
            '<div class="kl"><span>WR / Ret 30r</span><strong>'+w30+'</strong></div>'+
            '<div class="kl"><span>Estado</span><strong>'+estado+'</strong></div>'+
            '<div class="kl"><span>Universo</span><strong>'+universe+'</strong></div>'+
            '<div class="kl"><span>Picks actuales</span><strong>'+picks+'</strong></div>'+
            '<div class="kl"><span>Picks anteriores</span><span style="color:var(--muted);font-size:11px">'+prevPicks+'</span></div>'+
            '</div>'+
            '<div class="liga-detail-signal"><b>Se\u00f1al:</b> '+signal+'</div>'+
            sparkHtml+'</td>';
          row.insertAdjacentElement('afterend',dr);
        }
      });
    });
  }
  attachExpand(); setTimeout(attachExpand,800);
}
initLigaExpand();

/* ── EXPORT PANEL ─────────────────────────────────────────────────────────── */
(function(){
  var btn=document.getElementById('exportToggleBtn');
  var panel=document.getElementById('exportPanel');
  if(!btn||!panel) return;
  btn.addEventListener('click',function(){
    panel.style.display=panel.style.display==='none'?'flex':'none';
  });
  document.querySelectorAll('.export-opt-btn').forEach(function(ob){
    ob.addEventListener('click',function(){
      var type=ob.getAttribute('data-export');
      if(type==='csv') exportCSV();
      else if(type==='json') exportJSON();
      else if(type==='print') window.print();
      panel.style.display='none';
    });
  });
  function exportCSV(){
    var rows=[['Modelo','WR','Ret Prom','Muestra','Estado','Sharpe','MDD','Se\u00f1al']];
    document.querySelectorAll('#league tbody tr.leag-row-clickable').forEach(function(tr){
      var td=tr.querySelectorAll('td');
      rows.push([td[1]?td[1].textContent.split('\n')[0].trim():'',td[3]?td[3].textContent.split('\n')[0].trim():'',
        td[3]?td[3].textContent.split('\n').slice(1).join('').trim():'',td[4]?td[4].textContent.trim():'',
        td[2]?td[2].textContent.trim():'',tr.getAttribute('data-sharpe')||'',tr.getAttribute('data-mdd')||'',tr.getAttribute('data-signal')||'']);
    });
    var csv=rows.map(function(r){return r.map(function(c){return '"'+(c||'').replace(/"/g,'""')+'"';}).join(',');}).join('\n');
    var a=document.createElement('a');
    a.href=URL.createObjectURL(new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8'}));
    a.download='titan_liga_'+new Date().toISOString().split('T')[0]+'.csv'; a.click();
  }
  function exportJSON(){
    var data={exported_at:new Date().toISOString(),models:[]};
    document.querySelectorAll('#league tbody tr.leag-row-clickable').forEach(function(tr){
      var td=tr.querySelectorAll('td');
      data.models.push({version:td[1]?td[1].textContent.split('\n')[0].trim():'',wr:td[3]?td[3].textContent.split('\n')[0].trim():'',
        picks:td[5]?td[5].textContent.trim():'',sharpe:tr.getAttribute('data-sharpe'),mdd:tr.getAttribute('data-mdd'),signal:tr.getAttribute('data-signal')});
    });
    var a=document.createElement('a');
    a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    a.download='titan_snapshot_'+new Date().toISOString().split('T')[0]+'.json'; a.click();
  }
})();

/* ── AUTO-RELOAD 19:30 ───────────────────────────────────────────────────── */
(function(){
  setInterval(function(){
    var n=new Date();
    if(n.getHours()===19&&n.getMinutes()===30){ location.reload(); }
  },60000);
})();
"""

last_close = html.rfind('</script>')
if last_close != -1:
    html = html[:last_close] + NEW_JS + '\n</script>' + html[last_close+9:]
    print("[OK] Added full C1 Pro JS v4")
else:
    print("[WARN] </script> not found")

# ─── 12. BACKUP + WRITE OUTPUT ────────────────────────────────────────────────
# Safety rule: always backup current production HTML to staging/ before overwriting
STAGING_DIR.mkdir(parents=True, exist_ok=True)
OUT.parent.mkdir(parents=True, exist_ok=True)

is_promote = OUT == PROD_OUT.resolve()
if is_promote and PROD_OUT.exists():
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = STAGING_DIR / f'preview_c1_pro_{ts}.html'
    shutil.copy2(PROD_OUT, backup)
    print(f"  [backup] Production backup saved: {backup.name}")
    old = sorted(STAGING_DIR.glob('preview_c1_pro_*.html'))[:-5]
    for f in old:
        f.unlink()

OUT.write_text(html, encoding='utf-8')
mode_label = "PRODUCTION PROMOTE" if is_promote else "STAGING TEST BUILD"
print(f"\n[MODE] {mode_label}")
print(f"[DONE] Written to {OUT}")
print(f"       Size: {len(html):,} chars / ~{len(html.encode('utf-8'))//1024} KB")
if is_promote:
    print(f"       Production backups retained: {len(list(STAGING_DIR.glob('preview_c1_pro_*.html')))}")
else:
    print("       Review this staging file before any explicit promotion with --promote")
