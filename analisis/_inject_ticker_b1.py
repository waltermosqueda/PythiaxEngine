"""Inyecta el ticker B1 (barra azul temporal) en el staging del dashboard."""
import sys, json, datetime

# ── datos reales del snapshot ──────────────────────────────────────────────
sys.path.insert(0, 'C:/repos/PythiaxEngine')
from herramientas.dashboard_paths import SNAPSHOT_PATH

with open(SNAPSHOT_PATH, encoding='utf-8') as f:
    snap = json.load(f)

active = snap.get('active', {})
ar = active.get('active_run', {}) or {}
competition = snap.get('competition_recent', {})
league = competition.get('dashboard_league_equalized') or competition.get('league_equalized') or []

# ── picks: primero los de results_d/e, luego los de latest_tickers de los modelos ──
live_picks_raw = list(ar.get('results_d') or []) + list(ar.get('results_e') or [])

# Construir picks de exhibition desde modelos del league (tienen latest_tickers + latest_target_date)
exhibition_picks = []
today_str = datetime.date.today().isoformat()  # "2026-05-10"
for row in league[:6]:
    ver = str(row.get('version', ''))
    tickers = row.get('latest_tickers') or []
    target_date = str(row.get('latest_prediction_for') or row.get('latest_target_date') or '2026-05-17')
    role = str(row.get('role') or '')
    for tk in tickers[:3]:
        exhibition_picks.append({
            'ticker': tk,
            'version': ver,
            'target_date': target_date,
            'role': role,
        })
    if len(exhibition_picks) >= 18:
        break

# ── helper: calcular días restantes ───────────────────────────────────────
def days_remaining(target_date_str):
    try:
        td = datetime.date.fromisoformat(target_date_str)
        today = datetime.date.today()
        return (td - today).days
    except Exception:
        return 0

def entry_date_from_target(target_date_str):
    try:
        td = datetime.date.fromisoformat(target_date_str)
        ed = td - datetime.timedelta(days=7)
        return ed.strftime('%d/%m')
    except Exception:
        return '??/??'

def target_fmt(target_date_str):
    try:
        td = datetime.date.fromisoformat(target_date_str)
        return td.strftime('%d/%m')
    except Exception:
        return '??/??'

# ── version → CSS mod class ────────────────────────────────────────────────
MOD_CSS = {
    'V11': 'mod-v11', 'V13': 'mod-v13', 'V94': 'mod-v94',
    'V39': 'mod-v39', 'V97': 'mod-v97',
}
def mod_cls(ver):
    return MOD_CSS.get(ver, 'mod-v11')

# ── sample PnL data (placeholder realista) ─────────────────────────────────
# En producción esto vendría de precios históricos en Supabase
SAMPLE_PNL = [
    ('+2.14%', '+$8.40', 'pos'),
    ('-1.53%', '-$4.20', 'neg'),
    ('+4.87%', '+$18.60', 'pos'),
    ('-2.31%', '-$5.80', 'neg'),
    ('+1.22%', '+$3.10', 'pos'),
    ('+3.66%', '+$12.90', 'pos'),
    ('-0.88%', '-$2.30', 'neg'),
    ('+5.21%', '+$24.50', 'pos'),
    ('+1.76%', '+$6.70', 'pos'),
    ('-3.14%', '-$9.80', 'neg'),
    ('+2.98%', '+$11.20', 'pos'),
    ('+0.64%', '+$2.10', 'pos'),
    ('-1.97%', '-$7.60', 'neg'),
    ('+3.42%', '+$14.30', 'pos'),
    ('+6.11%', '+$28.90', 'pos'),
    ('+1.09%', '+$3.80', 'pos'),
    ('-2.75%', '-$8.40', 'neg'),
    ('+4.33%', '+$19.70', 'pos'),
]

# ── construir cards HTML ───────────────────────────────────────────────────
def rest_label(days):
    if days < 0:
        return 'vencido', 'rgba(252,92,125,0.75)'
    if days == 0:
        return '¡hoy!', 'rgba(252,92,125,0.85)'
    return f'{days}d rest.', 'rgba(100,180,255,0.8)'

def bar_width(days, total=7):
    if days <= 0:
        return 0
    pct = min(100, int(days / total * 100))
    return pct

def build_card(pick, pnl_idx):
    tk  = pick['ticker']
    ver = pick['version']
    tgt = pick['target_date']
    days = days_remaining(tgt)
    pct_str, delta_str, side = SAMPLE_PNL[pnl_idx % len(SAMPLE_PNL)]
    rl, rc = rest_label(days)
    bw = bar_width(days)
    sign = '+' if side == 'pos' else ''
    return f'''      <div class="pk-b1 {side}">
        <div class="pk-row1"><span class="pk-sym">{tk}</span><span class="pk-mod {mod_cls(ver)}">{ver}</span><span class="pk-pnl {side}">{pct_str}</span></div>
        <div class="pk-row2"><span class="pk-entry">entrada →</span><span class="pk-curr {side}">actual</span><span class="pk-delta {side}">{delta_str}</span></div>
        <div class="pk-b1-row3"><span class="pk-b1-icon">⏱</span><span class="pk-b1-dates">{entry_date_from_target(tgt)} → {target_fmt(tgt)}</span><span class="pk-b1-rest" style="color:{rc}">{rl}</span></div>
        <div class="pk-b1-bar" style="width:{bw}%"></div>
      </div>'''

cards_html_list = [build_card(p, i) for i, p in enumerate(exhibition_picks)]
cards_html = '\n'.join(cards_html_list)
# Duplicar para loop seamless
cards_html_dup = cards_html + '\n' + cards_html

# Total picks abiertos
active_run_cr = competition.get('league_equalized') or []
total_open = len(set(
    tk for row in (snap.get('competition') or [])
    for tk in (row.get('latest_tickers') or [])
))

# ── CSS del ticker B1 ──────────────────────────────────────────────────────
TICKER_CSS = """
/* ── TICKER B1 (picks abiertos, barra azul temporal) ─── */
.tkb1-wrap{
  position:relative;overflow:hidden;height:62px;
  background:rgba(5,8,16,0.97);
  border-bottom:1px solid rgba(24,232,200,0.14);
  border-top:1px solid rgba(24,232,200,0.12);
  display:flex;align-items:stretch;
}
.tkb1-lbl{
  flex-shrink:0;display:flex;flex-direction:column;justify-content:center;
  padding:0 10px 0 14px;border-right:1px solid rgba(24,232,200,0.12);
  background:rgba(24,232,200,0.04);gap:1px;min-width:64px;z-index:2;
}
.tkb1-lbl-t{font-size:7px;text-transform:uppercase;letter-spacing:.16em;color:#18e8c8;font-weight:700}
.tkb1-lbl-n{font-size:17px;font-weight:900;color:#eef4fb;line-height:1}
.tkb1-lbl-s{font-size:7px;color:#6585a8;letter-spacing:.05em}
.tkb1-scroll{overflow:hidden;flex:1;display:flex;align-items:center}
.tkb1-inner{display:flex;align-items:center;white-space:nowrap;animation:tkb1 95s linear infinite;height:62px}
.tkb1-inner:hover{animation-play-state:paused;cursor:default}
@keyframes tkb1{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}
/* cards */
.pk-b1{display:inline-flex;flex-direction:column;justify-content:center;gap:2px;height:62px;border-right:1px solid rgba(130,180,230,0.07);padding:7px 14px;cursor:default;transition:background .14s;flex-shrink:0;position:relative;min-width:156px;overflow:hidden}
.pk-b1:hover{background:rgba(255,255,255,0.03)}
.pk-b1.pos{border-left:3px solid #44e890;background:rgba(68,232,144,0.03)}
.pk-b1.neg{border-left:3px solid #fc5c7d;background:rgba(252,92,125,0.03)}
.pk-row1{display:flex;align-items:center;gap:6px}
.pk-sym{font-size:15px;font-weight:900;color:#eef4fb;letter-spacing:-.02em;line-height:1}
.pk-mod{font-size:7px;padding:2px 5px;border-radius:3px;font-weight:700;letter-spacing:.05em}
.mod-v11{background:rgba(245,184,51,.18);color:#f5b833}
.mod-v13{background:rgba(24,232,200,.14);color:#18e8c8}
.mod-v97{background:rgba(68,232,144,.14);color:#44e890}
.mod-v39{background:rgba(168,130,255,.14);color:#a882ff}
.mod-v94{background:rgba(252,92,125,.14);color:#fc5c7d}
.pk-pnl{font-size:14px;font-weight:900;letter-spacing:-.02em;margin-left:auto;line-height:1}
.pk-pnl.pos{color:#44e890}.pk-pnl.neg{color:#fc5c7d}
.pk-row2{display:flex;align-items:center;gap:5px;font-size:9.5px}
.pk-entry{color:#6585a8}
.pk-curr{font-weight:700}
.pk-curr.pos{color:rgba(68,232,144,0.85)}.pk-curr.neg{color:rgba(252,92,125,0.85)}
.pk-delta{font-size:9.5px;font-weight:600;margin-left:auto}
.pk-delta.pos{color:rgba(68,232,144,0.65)}.pk-delta.neg{color:rgba(252,92,125,0.65)}
.pk-b1-row3{display:flex;align-items:center;gap:5px;font-size:7.5px}
.pk-b1-icon{font-size:8.5px;opacity:.5}
.pk-b1-dates{color:rgba(130,180,230,0.45);font-size:7.5px}
.pk-b1-rest{font-weight:700;font-size:8.5px;margin-left:auto}
.pk-b1-bar{position:absolute;bottom:0;left:0;height:2.5px;background:linear-gradient(90deg,rgba(80,160,255,0.25),rgba(120,200,255,0.6));transition:width .3s}
"""

# ── HTML del ticker ────────────────────────────────────────────────────────
TICKER_HTML = f"""
  <!-- TICKER B1: PICKS ABIERTOS ──────────────────────────────── -->
  <div class="tkb1-wrap" id="ticker-picks">
    <div class="tkb1-lbl">
      <div class="tkb1-lbl-t">PICKS</div>
      <div class="tkb1-lbl-n">{total_open or len(exhibition_picks)}</div>
      <div class="tkb1-lbl-s">ABIERTOS</div>
    </div>
    <div class="tkb1-scroll">
      <div class="tkb1-inner">
{cards_html_dup}
      </div>
    </div>
  </div>
"""

# ── Leer staging ───────────────────────────────────────────────────────────
STAGING = 'C:/repos/PythiaxEngine/analisis/_staging_prod_preview.html'
with open(STAGING, encoding='utf-8') as f:
    html = f.read()

# 1. Inyectar CSS antes de </style> (el último </style> antes del body)
body_pos = html.find('<body')
last_style_end = html.rfind('</style>', 0, body_pos)
if last_style_end == -1:
    print("ERROR: no </style> encontrado antes de <body>")
    sys.exit(1)
html = html[:last_style_end] + TICKER_CSS + '\n</style>' + html[last_style_end + len('</style>'):]
print(f"CSS inyectado en posición {last_style_end}")

# 2. Inyectar HTML después de la sección kpi-strip
INJECT_AFTER = '</section>'
# Encontrar el cierre del kpi-strip (es la primera </section> después del kpi-strip div)
kpi_pos = html.find('kpi-strip')
close_pos = html.find(INJECT_AFTER, kpi_pos)
if close_pos == -1:
    print("ERROR: no </section> encontrado después de kpi-strip")
    sys.exit(1)
insert_at = close_pos + len(INJECT_AFTER)
html = html[:insert_at] + '\n' + TICKER_HTML + html[insert_at:]
print(f"Ticker HTML inyectado en posición {insert_at}")

# 3. Guardar staging modificado
with open(STAGING, 'w', encoding='utf-8') as f:
    f.write(html)
print("OK: staging actualizado →", STAGING)
print(f"Total picks en ticker: {len(exhibition_picks)} (× 2 para loop)")
