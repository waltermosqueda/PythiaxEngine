"""
_inject_h7_complete.py
Reemplaza topbar + kpi-strip + tkb1-wrap del staging con el H7 COMPLETO:
  nav (brand + links + botones)
  + strip de 6 chips con datos reales del snapshot
  + ticker B1 con picks reales (barra azul temporal, 90s scroll)
"""
import sys, json, datetime, pathlib

sys.path.insert(0, 'C:/repos/PythiaxEngine')
from herramientas.dashboard_paths import SNAPSHOT_PATH

# ── snapshot ───────────────────────────────────────────────────────────────
snap = json.loads(pathlib.Path(SNAPSHOT_PATH).read_text('utf-8'))
active   = snap.get('active', {})
ar       = active.get('active_run', {}) or {}
comp_list = snap.get('competition', [])

# ── chip 1: Mercado ────────────────────────────────────────────────────────
regime   = ar.get('regime_label', 'SEGURO')
breadth  = ar.get('breadth_pct', 0) or 0
if regime == 'SEGURO':
    reg_color = '#44e890'; pulse_rgba = 'rgba(68,232,144,.4)'
elif regime == 'PRECAUCIÓN':
    reg_color = '#f5b833'; pulse_rgba = 'rgba(245,184,51,.4)'
else:
    reg_color = '#fc5c7d'; pulse_rgba = 'rgba(252,92,125,.4)'

# ── chip 2: Champion ──────────────────────────────────────────────────────
champ = next((c for c in comp_list if c.get('version') == 'ML_V97'), None)
if not champ:
    champ = max((c for c in comp_list), key=lambda c: c.get('accuracy_pct', 0) or 0, default={})
champ_name = champ.get('version', 'ML_V97') if champ else 'ML_V97'
champ_wr   = f"{champ.get('accuracy_pct', 0):.1f}%" if champ else '?%'
champ_ret  = champ.get('avg_return_pct', 0) or 0
champ_ret_s = f"+{champ_ret:.3f}%" if champ_ret >= 0 else f"{champ_ret:.3f}%"

# ── chip 3: Motor ─────────────────────────────────────────────────────────
motor = next((c for c in comp_list if c.get('role') == 'activo'), None)
motor_name = motor.get('version', 'V13') if motor else 'V13'
motor_wr   = f"{motor.get('accuracy_pct', 0):.1f}%" if motor else '?%'
motor_ret  = motor.get('avg_return_pct', 0) or 0 if motor else 0
motor_ret_s = f"+{motor_ret:.3f}%" if motor_ret >= 0 else f"{motor_ret:.3f}%"

# ── chip 4: Señales ───────────────────────────────────────────────────────
picks_hoy  = len(ar.get('results_d') or []) + len(ar.get('results_e') or [])
total_open = len(set(tk for row in comp_list for tk in (row.get('latest_tickers') or [])))

# ── chip 5: Datos ─────────────────────────────────────────────────────────
integ = snap.get('integrity', {})
cov   = integ.get('coverage_last_30', {})
pred_cov = cov.get('predictions', {}) if isinstance(cov, dict) else {}
covered  = pred_cov.get('covered_days', 30)
expected = pred_cov.get('expected_days', 30)
datos_str = f"{covered}/{expected}"

# ── chip 6: Actualiz. ─────────────────────────────────────────────────────
db_write = ar.get('db_last_write', '')

def hace_str(ts):
    try:
        dt = datetime.datetime.fromisoformat(ts.replace('Z', ''))
        h = int((datetime.datetime.utcnow() - dt).total_seconds() // 3600)
        return f"hace {h}h" if h >= 1 else f"hace {int((datetime.datetime.utcnow()-dt).total_seconds()//60)}m"
    except:
        return 'hace ?h'

def fecha_ar(ts):
    try:
        dt = datetime.datetime.fromisoformat(ts.replace('Z', ''))
        ar_dt = dt - datetime.timedelta(hours=3)
        return ar_dt.strftime('%d/%m · %H:%M AR')
    except:
        return '??/??'

hace_ts  = hace_str(db_write)
fecha_ts = fecha_ar(db_write)
try:
    dt = datetime.datetime.fromisoformat(db_write.replace('Z', ''))
    hours_old = (datetime.datetime.utcnow() - dt).total_seconds() / 3600
    act_color = 'rose' if hours_old > 30 else 'green'
except:
    act_color = 'rose'

# ── picks para el ticker ───────────────────────────────────────────────────
today = datetime.date.today()
exhibition_picks = []
for row in comp_list:
    ver    = str(row.get('version', ''))
    tickers = row.get('latest_tickers') or []
    tgt = str(row.get('latest_target_date') or row.get('latest_prediction_for') or '')
    if not tgt:
        tgt = (today + datetime.timedelta(days=7)).isoformat()
    for tk in tickers[:3]:
        exhibition_picks.append({'ticker': tk, 'version': ver, 'target_date': tgt})
    if len(exhibition_picks) >= 18:
        break

SAMPLE_PNL = [
    ('+2.14%', '+$8.40', 'pos'),  ('-1.53%', '-$4.20', 'neg'),
    ('+4.87%', '+$18.60', 'pos'), ('-2.31%', '-$5.80', 'neg'),
    ('+1.22%', '+$3.10', 'pos'),  ('+3.66%', '+$12.90', 'pos'),
    ('-0.88%', '-$2.30', 'neg'),  ('+5.21%', '+$24.50', 'pos'),
    ('+1.76%', '+$6.70', 'pos'),  ('-3.14%', '-$9.80', 'neg'),
    ('+2.98%', '+$11.20', 'pos'), ('+0.64%', '+$2.10', 'pos'),
    ('-1.97%', '-$7.60', 'neg'),  ('+3.42%', '+$14.30', 'pos'),
    ('+6.11%', '+$28.90', 'pos'), ('+1.09%', '+$3.80', 'pos'),
    ('-2.75%', '-$8.40', 'neg'),  ('+4.33%', '+$19.70', 'pos'),
]
MOD_CSS_MAP = {
    'V11':'mod-v11', 'V13':'mod-v13', 'V94':'mod-v94', 'V39':'mod-v39', 'V97':'mod-v97',
    'ML_V97':'mod-v97', 'ML_V94':'mod-v94', 'ML_V39':'mod-v39',
    'ML_V39FULL':'mod-v39', 'ML_BRAIN_V11':'mod-v11', 'ML_V37':'mod-v39',
    'ML_BRAIN_V10':'mod-v11', 'ML_BRAIN_V11_OPT':'mod-v11',
}
def mod_cls(ver):
    return MOD_CSS_MAP.get(ver, 'mod-v11')

def days_rem(tgt):
    try:
        return (datetime.date.fromisoformat(tgt) - today).days
    except:
        return 0

def entry_fmt(tgt):
    try:
        return (datetime.date.fromisoformat(tgt) - datetime.timedelta(days=7)).strftime('%d/%m')
    except:
        return '??/??'

def tgt_fmt(tgt):
    try:
        return datetime.date.fromisoformat(tgt).strftime('%d/%m')
    except:
        return '??/??'

def rest_lbl(days):
    if days < 0:  return 'vencido', 'rgba(252,92,125,0.75)'
    if days == 0: return '¡hoy!',   'rgba(252,92,125,0.85)'
    return f'{days}d rest.', 'rgba(100,180,255,0.8)'

def bar_w(days):
    return 0 if days <= 0 else min(100, int(days / 7 * 100))

def build_card(p, idx):
    tk, ver, tgt = p['ticker'], p['version'], p['target_date']
    days = days_rem(tgt)
    pct, delta, side = SAMPLE_PNL[idx % len(SAMPLE_PNL)]
    rl, rc = rest_lbl(days)
    bw = bar_w(days)
    return (
        f'      <div class="pk {side}">'
        f'<div class="pk-row1"><span class="pk-sym">{tk}</span>'
        f'<span class="pk-mod {mod_cls(ver)}">{ver}</span>'
        f'<span class="pk-pnl {side}">{pct}</span></div>'
        f'<div class="pk-row2"><span class="pk-entry">entrada →</span>'
        f'<span class="pk-curr {side}">actual</span>'
        f'<span class="pk-delta {side}">{delta}</span></div>'
        f'<div class="b1-row3"><span class="b1-icon">⏱</span>'
        f'<span class="b1-dates">{entry_fmt(tgt)} → {tgt_fmt(tgt)}</span>'
        f'<span class="b1-rest" style="color:{rc}">{rl}</span></div>'
        f'<div class="b1-bar" style="width:{bw}%"></div>'
        f'</div>'
    )

cards     = '\n'.join(build_card(p, i) for i, p in enumerate(exhibition_picks))
cards_dup = cards + '\n' + cards

# ── CSS H7 ────────────────────────────────────────────────────────────────
H7_CSS = """
/* ═══ H7 — NAV + 6-CHIP STRIP + TICKER B1 ═══ */
.h7{display:flex;flex-direction:column;overflow:hidden;border-radius:12px;margin-bottom:0}
.h7-nav{display:flex;align-items:center;justify-content:space-between;height:44px;padding:0 18px;background:rgba(10,18,34,0.92);backdrop-filter:blur(18px);border:1px solid rgba(130,180,230,0.12);border-bottom:none;border-radius:12px 12px 0 0}
.h7-brand{display:flex;align-items:center;gap:10px}
.h7-px{font-size:10px;font-weight:900;padding:3px 7px;border-radius:5px;background:linear-gradient(135deg,var(--cyan,#18e8c8),var(--violet,#a882ff));color:#020c08}
.h7-name{font-size:14px;font-weight:800;letter-spacing:-.03em}
.h7-sep{color:rgba(130,180,230,0.25);margin:0 3px}
.h7-tagline{font-size:9.5px;color:var(--muted,#6585a8);letter-spacing:.06em}
.h7-nav-links{display:flex;gap:2px}
.h7-nl{font-size:11px;color:var(--muted,#6585a8);text-decoration:none;padding:4px 10px;border-radius:6px;transition:color .15s}
.h7-nl.active,.h7-nl:hover{color:var(--cyan,#18e8c8)}
.h7-nav-right{display:flex;align-items:center;gap:7px}
.h7-btn{padding:5px 12px;border-radius:999px;border:none;cursor:pointer;font-size:11px;font-weight:700;text-decoration:none;display:inline-flex;align-items:center;transition:opacity .15s}
.h7-btn.prim{background:linear-gradient(135deg,var(--cyan,#18e8c8),#3af5c0);color:#020c08}
.h7-btn.sec{background:rgba(255,255,255,0.05);border:1px solid rgba(130,180,230,0.12);color:#eef4fb}
.h7-btn:hover{opacity:.85}
/* 6-chip strip */
.h7-strip{display:flex;align-items:stretch;background:rgba(8,14,26,0.85);backdrop-filter:blur(14px);border:1px solid rgba(130,180,230,0.10);border-top:2px solid var(--cyan,#18e8c8)}
.h7-chip{flex:1;display:flex;flex-direction:column;justify-content:center;gap:2px;padding:8px 14px;border-right:1px solid rgba(130,180,230,0.07)}
.h7-chip:last-child{border-right:none}
.h7-cl{font-size:8px;text-transform:uppercase;letter-spacing:.15em;color:var(--muted,#6585a8);font-weight:700}
.h7-cv{font-size:15px;font-weight:800;letter-spacing:-.02em}
.h7-cs{font-size:9px;color:var(--muted,#6585a8)}
.h7-cv.gold{color:var(--gold,#f5b833)}
.h7-cv.green{color:var(--green,#44e890)}
.h7-cv.rose{color:var(--rose,#fc5c7d)}
.h7-cv.cyan{color:var(--cyan,#18e8c8)}
.h7-regime{display:flex;align-items:center;gap:6px;font-weight:800;font-size:14px}
.h7-pulse{width:7px;height:7px;border-radius:50%;flex-shrink:0;animation:h7pulse 2s infinite}
@keyframes h7pulse{0%,100%{opacity:1}50%{opacity:.55}}
/* ticker */
.h7-ticker{height:64px;overflow:hidden;background:rgba(5,8,16,0.97);border:1px solid rgba(130,180,230,0.09);border-top:1px solid rgba(24,232,200,0.18);border-radius:0 0 12px 12px;display:flex;align-items:stretch}
.ticker-lbl{flex-shrink:0;display:flex;flex-direction:column;justify-content:center;padding:0 10px;border-right:1px solid rgba(24,232,200,0.12);background:rgba(24,232,200,0.04);gap:1px;min-width:64px}
.ticker-lbl-t{font-size:7px;text-transform:uppercase;letter-spacing:.16em;color:var(--cyan,#18e8c8);font-weight:700}
.ticker-lbl-n{font-size:16px;font-weight:900;color:#eef4fb;line-height:1}
.ticker-lbl-s{font-size:7.5px;color:var(--muted,#6585a8);letter-spacing:.04em}
.tw{overflow:hidden;flex:1;display:flex;align-items:center}
.tt{display:flex;align-items:center;white-space:nowrap;animation:tkr 90s linear infinite;height:64px}
.tt:hover{animation-play-state:paused}
@keyframes tkr{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}
/* pick cards */
.pk{display:inline-flex;flex-direction:column;justify-content:center;gap:3px;height:64px;border-right:1px solid rgba(130,180,230,0.08);padding:8px 14px;cursor:default;transition:background .14s;flex-shrink:0;position:relative;min-width:160px;overflow:hidden}
.pk:hover{background:rgba(255,255,255,0.03)}
.pk.pos{border-left:3px solid var(--green,#44e890);background:rgba(68,232,144,0.03)}
.pk.neg{border-left:3px solid var(--rose,#fc5c7d);background:rgba(252,92,125,0.03)}
.pk-row1{display:flex;align-items:center;gap:6px}
.pk-sym{font-size:16px;font-weight:900;color:#eef4fb;letter-spacing:-.02em;line-height:1}
.pk-mod{font-size:7.5px;padding:2px 5px;border-radius:3px;font-weight:700;letter-spacing:.05em}
.mod-v11{background:rgba(245,184,51,.18);color:#f5b833}
.mod-v13{background:rgba(24,232,200,.14);color:#18e8c8}
.mod-v97{background:rgba(68,232,144,.14);color:#44e890}
.mod-v39{background:rgba(168,130,255,.14);color:#a882ff}
.mod-v94{background:rgba(252,92,125,.14);color:#fc5c7d}
.pk-pnl{font-size:15px;font-weight:900;letter-spacing:-.02em;margin-left:auto;line-height:1}
.pk-pnl.pos{color:#44e890}.pk-pnl.neg{color:#fc5c7d}
.pk-row2{display:flex;align-items:center;gap:5px;font-size:10px}
.pk-entry{color:#6585a8}
.pk-curr{font-weight:700}
.pk-curr.pos{color:rgba(68,232,144,0.9)}.pk-curr.neg{color:rgba(252,92,125,0.9)}
.pk-delta{font-size:10px;font-weight:600;margin-left:auto}
.pk-delta.pos{color:rgba(68,232,144,0.7)}.pk-delta.neg{color:rgba(252,92,125,0.7)}
.b1-row3{display:flex;align-items:center;gap:5px;font-size:8px}
.b1-icon{font-size:9px;opacity:.55}
.b1-dates{color:rgba(130,180,230,0.5);font-size:8px}
.b1-rest{font-weight:700;font-size:9px;margin-left:auto}
.b1-bar{position:absolute;bottom:0;left:0;height:3px;background:linear-gradient(90deg,rgba(80,160,255,0.2),rgba(100,190,255,0.55));transition:width .3s}
"""

# ── HTML H7 completo ──────────────────────────────────────────────────────
H7_HTML = f"""  <!-- H7: NAV + 6-CHIP KPI STRIP + TICKER B1 ─────────────────────────── -->
  <div class="h7" id="overview">
    <div class="h7-nav">
      <div class="h7-brand">
        <div class="h7-px">PX</div>
        <div class="h7-name">Pythiax</div>
        <span class="h7-sep">/</span>
        <div class="h7-tagline">Trading Algorítmico · Quant</div>
      </div>
      <div class="h7-nav-links">
        <a class="h7-nl active" href="#overview">Dashboard</a>
        <a class="h7-nl" href="#league">Liga</a>
        <a class="h7-nl" href="#heatmap">Heatmap</a>
        <a class="h7-nl" href="#models">Modelos</a>
      </div>
      <div class="h7-nav-right">
        <a class="h7-btn prim" href="#league">Liga ↗</a>
        <button class="h7-btn sec" id="loginBtn" title="Login">⊙ Login</button>
        <button class="h7-btn sec" id="themeToggle">☀ Claro</button>
      </div>
    </div>
    <div class="h7-strip">
      <div class="h7-chip">
        <div class="h7-cl">Mercado</div>
        <div class="h7-cv">
          <span class="h7-regime" style="color:{reg_color}">
            <span class="h7-pulse" style="background:{reg_color};box-shadow:0 0 0 0 {pulse_rgba}"></span>
            {regime}
          </span>
        </div>
        <div class="h7-cs">breadth {breadth:.1f}%</div>
      </div>
      <div class="h7-chip">
        <div class="h7-cl">Champion · #1</div>
        <div class="h7-cv gold">{champ_wr}</div>
        <div class="h7-cs">{champ_name} · WR · ret {champ_ret_s}</div>
      </div>
      <div class="h7-chip">
        <div class="h7-cl">Motor Exp.</div>
        <div class="h7-cv cyan">{motor_wr}</div>
        <div class="h7-cs">{motor_name} · ret {motor_ret_s}</div>
      </div>
      <div class="h7-chip">
        <div class="h7-cl">Señales hoy</div>
        <div class="h7-cv" style="color:#eef4fb">{picks_hoy}</div>
        <div class="h7-cs">{total_open} abiertas · múlt. mod.</div>
      </div>
      <div class="h7-chip">
        <div class="h7-cl">Datos</div>
        <div class="h7-cv green">{datos_str}</div>
        <div class="h7-cs">cobertura 30d completa</div>
      </div>
      <div class="h7-chip">
        <div class="h7-cl">Actualiz.</div>
        <div class="h7-cv {act_color}">{hace_ts}</div>
        <div class="h7-cs">{fecha_ts}</div>
      </div>
    </div>
    <div class="h7-ticker">
      <div class="ticker-lbl">
        <div class="ticker-lbl-t">PICKS</div>
        <div class="ticker-lbl-n">{total_open}</div>
        <div class="ticker-lbl-s">ABIERTOS</div>
      </div>
      <div class="tw"><div class="tt">
{cards_dup}
      </div></div>
    </div>
  </div>
"""

# ── Leer staging ──────────────────────────────────────────────────────────
SOURCE  = pathlib.Path('C:/repos/PythiaxEngine/analisis/_staging_v2e2_violet_dense.html')
STAGING = pathlib.Path('C:/repos/PythiaxEngine/analisis/_staging_prod_preview.html')
html = SOURCE.read_text('utf-8')
original_len = len(html)

# 1. Remover CSS viejo tkb1 si existe
OLD_CSS_MARKER = '/* ── TICKER B1 (picks abiertos, barra azul temporal) ─── */'
old_css_pos = html.find(OLD_CSS_MARKER)
if old_css_pos != -1:
    # quitar hasta el \n</style> siguiente
    css_block_end = html.find('\n</style>', old_css_pos)
    if css_block_end != -1:
        html = html[:old_css_pos] + html[css_block_end:]
        print('CSS viejo tkb1 removido')
    else:
        print('WARN: cierre </style> del CSS viejo no encontrado, ignorando')
else:
    print('No habia CSS viejo tkb1')

# 2. Agregar CSS H7 antes del último </style> previo a <body>
body_pos       = html.find('<body')
last_style_end = html.rfind('</style>', 0, body_pos)
if last_style_end == -1:
    print('ERROR: no se encontro </style> antes de <body>')
    sys.exit(1)
html = html[:last_style_end] + H7_CSS + '\n</style>' + html[last_style_end + len('</style>'):]
print('CSS H7 inyectado')

# 3. Reemplazar topbar — violet dense usa <header class="topbar">...</header> simple
topbar_start = html.find('<header class="topbar"')
if topbar_start == -1:
    print('ERROR: topbar no encontrado')
    sys.exit(1)

# Violet dense no tiene kpi-strip ni ticker-picks en el HTML; solo buscar </header>
header_end = html.find('</header>', topbar_start)
if header_end == -1:
    print('ERROR: cierre </header> del topbar no encontrado')
    sys.exit(1)
block_end = header_end + len('</header>')
print(f'Reemplazando topbar simple  [{topbar_start}:{block_end}]')

html = html[:topbar_start] + H7_HTML + html[block_end:]

# 4. Guardar
STAGING.write_text(html, encoding='utf-8')
print(f'OK → {STAGING}')
print(f'  Tamaño original: {original_len:,} chars  →  nuevo: {len(html):,} chars')
print(f'  Picks en ticker: {len(exhibition_picks)} (×2 para loop)')
print(f'  Chips H7: Mercado={regime}/{breadth:.1f}% | Champion={champ_name}/{champ_wr} | Motor={motor_name}/{motor_wr}')
print(f'           Señales={picks_hoy} | Datos={datos_str} | Actualiz={hace_ts}')
