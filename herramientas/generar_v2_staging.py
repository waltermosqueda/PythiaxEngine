"""
generar_v2_staging.py
Genera analisis/_staging_v2_trading.html inyectando:
  - CSS: nuevo layout tipo trading terminal (5 paneles)
  - HTML: paneles vacíos (Overview, Performance, Market, Positions, Chart)
  - JS:   popula los paneles leyendo datos ya presentes en el DOM
Fuente: analisis/_staging_prod_preview.html (NUNCA modificar)
Destino: analisis/_staging_v2_trading.html
"""
import os, sys, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(ROOT, "analisis", "_staging_prod_preview.html")
DST  = os.path.join(ROOT, "analisis", "_staging_v2_trading.html")

with open(SRC, "r", encoding="utf-8") as f:
    html = f.read()

# ─────────────────────────────────────────────────────────────────────────
# 1.  NEW CSS
# ─────────────────────────────────────────────────────────────────────────
NEW_CSS = """
<style id="v2-tt-theme">
/* ══════════════════════════════════════════════════════════════
   TRADING TERMINAL V2 — override + new components
   ══════════════════════════════════════════════════════════════ */

/* ── token overrides (dark mode only) ─────────────────────── */
body:not(.theme-white) {
  --bg: #060912;
  --bg-gradient:
    radial-gradient(ellipse at 70% -8%, rgba(24,232,200,.09), transparent 28%),
    radial-gradient(ellipse at 5%  45%, rgba(99,102,241,.06), transparent 22%),
    linear-gradient(180deg, #070b1a 0%, #040710 100%);
  --panel: linear-gradient(180deg, rgba(10,16,32,.99) 0%, rgba(6,10,22,.99) 100%);
  --line: rgba(130,180,230,.17);
  --shadow: 0 28px 80px rgba(0,0,0,.75);
  --radius: 12px;
  --gap: 12px;
}

/* ── TRADING TERMINAL ROWS ─────────────────────────────────── */
.tt-row {
  display: grid;
  gap: var(--gap);
}
.tt-row-top {
  grid-template-columns: 248px 1fr 264px;
  align-items: start;
}
.tt-row-bottom {
  grid-template-columns: 1.45fr 1fr;
  align-items: start;
}
.tt-panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 14px 15px;
  box-shadow: var(--shadow);
  overflow: hidden;
  position: relative;
}

/* ── SHARED PANEL HEADER ───────────────────────────────────── */
.tt-ph {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 11px;
  padding-bottom: 9px;
  border-bottom: 1px solid var(--line);
}
.tt-ph-title {
  font-size: 9.5px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: .14em;
  color: var(--muted);
}
.tt-ph-badge {
  font-size: 9px;
  font-weight: 800;
  padding: 2px 7px;
  border-radius: 5px;
  background: rgba(24,232,200,.1);
  color: var(--cyan);
  border: 1px solid rgba(24,232,200,.22);
}

/* ── OVERVIEW PANEL ─────────────────────────────────────────── */
.tto-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 10px;
}
.tto-icon {
  width: 34px; height: 34px;
  border-radius: 9px;
  background: rgba(24,232,200,.12);
  border: 1px solid rgba(24,232,200,.25);
  display: flex; align-items: center; justify-content: center;
  font-size: 15px; flex-shrink: 0;
}
.tto-account { font-size: 11.5px; font-weight: 800; letter-spacing: .05em; }
.tto-type    { font-size: 9.5px; color: var(--muted); margin-top: 1px; }
.tto-stats   { display: flex; flex-direction: column; gap: 0; }
.tto-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 0;
  border-top: 1px solid rgba(255,255,255,.05);
  font-size: 11px;
}
.tto-row:first-child { border-top: none; }
.tto-label { color: var(--muted); }
.tto-value { font-weight: 800; }
.tto-actions {
  display: flex; gap: 7px;
  margin-top: 11px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}
.tto-btn {
  flex: 1; padding: 7px 4px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: rgba(255,255,255,.04);
  color: var(--ink);
  font-size: 10.5px; font-weight: 700;
  cursor: pointer; text-align: center;
  transition: background .12s;
}
.tto-btn:hover { background: rgba(255,255,255,.08); }
.tto-btn-primary {
  background: rgba(24,232,200,.14);
  border-color: rgba(24,232,200,.28);
  color: var(--cyan);
}

/* ── PERFORMANCE PANEL ──────────────────────────────────────── */
.ttp-legend {
  display: flex; gap: 12px;
  margin-bottom: 8px; flex-wrap: wrap;
}
.ttp-leg-item {
  display: flex; align-items: center; gap: 5px;
  font-size: 10px; color: var(--muted);
}
.ttp-leg-line {
  width: 18px; height: 2px; border-radius: 1px; flex-shrink: 0;
}
.ttp-chart-area { width: 100%; }
.ttp-chart-area svg { display: block; width: 100%; }

/* ── MARKET / MODEL VIEW ────────────────────────────────────── */
.ttm-table {
  width: 100%; border-collapse: collapse; font-size: 11px;
}
.ttm-table th {
  font-size: 8px;
  text-transform: uppercase;
  letter-spacing: .11em;
  color: var(--muted);
  padding: 0 5px 6px;
  text-align: right;
  font-weight: 700;
}
.ttm-table th:first-child { text-align: left; }
.ttm-table td {
  padding: 5.5px 5px;
  border-top: 1px solid rgba(255,255,255,.045);
  text-align: right;
  font-weight: 600;
  vertical-align: middle;
}
.ttm-table td:first-child { text-align: left; font-weight: 800; font-size: 11.5px; }
.ttm-table tbody tr:hover { background: rgba(255,255,255,.025); cursor: pointer; }
.ttm-wr-bar {
  display: inline-block;
  height: 3px; border-radius: 1px;
  margin-left: 4px;
  vertical-align: middle; opacity: .55;
}
.ttm-dot {
  display: inline-block;
  width: 7px; height: 7px;
  border-radius: 2px;
  margin-right: 5px;
  vertical-align: middle;
}

/* ── POSITIONS TABLE ────────────────────────────────────────── */
.ttp2-table {
  width: 100%; border-collapse: collapse; font-size: 11.5px;
}
.ttp2-table th {
  font-size: 8px;
  text-transform: uppercase;
  letter-spacing: .11em;
  color: var(--muted);
  font-weight: 700;
  padding: 0 6px 7px;
  text-align: left; white-space: nowrap;
}
.ttp2-table th.r { text-align: right; }
.ttp2-table td {
  padding: 6.5px 6px;
  border-top: 1px solid rgba(255,255,255,.05);
  vertical-align: middle;
}
.ttp2-table td.r { text-align: right; font-weight: 700; }
.ttp2-table tbody tr:hover { background: rgba(255,255,255,.03); }
.ttp2-m-dot {
  display: inline-block;
  width: 8px; height: 8px;
  border-radius: 2px;
  margin-right: 5px; vertical-align: middle;
}
.ttp2-ticker { font-weight: 800; font-size: 12.5px; }

/* ── CHART PANEL ────────────────────────────────────────────── */
.ttc-kpis {
  display: flex; gap: 12px; flex-wrap: wrap;
  margin: 8px 0 10px;
  padding-bottom: 9px;
  border-bottom: 1px solid var(--line);
}
.ttc-kpi { font-size: 10px; }
.ttc-kpi span { color: var(--muted); display: block; margin-bottom: 2px; }
.ttc-kpi strong { font-size: 12px; }
.ttc-chart-area { width: 100%; }
.ttc-chart-area svg { display: block; width: 100%; }

/* ── RESPONSIVE ─────────────────────────────────────────────── */
@media (max-width: 1280px) {
  .tt-row-top { grid-template-columns: 220px 1fr; }
  .tt-panel.tt-market { display: none; }
}
@media (max-width: 920px) {
  .tt-row-top, .tt-row-bottom { grid-template-columns: 1fr; }
}
</style>
"""

# ─────────────────────────────────────────────────────────────────────────
# 2.  NEW HTML PANELS (empty shells, JS fills them)
# ─────────────────────────────────────────────────────────────────────────
NEW_HTML = """
<!-- ═══════════════════════════════════════════════════════════════════
     TRADING TERMINAL V2 — Panels injected by generar_v2_staging.py
     ═══════════════════════════════════════════════════════════════════ -->

<!-- ROW 1: Overview · Performance · Market ──────────────────────────── -->
<div class="tt-row tt-row-top">

  <!-- 1. SYSTEM OVERVIEW -->
  <div class="tt-panel tt-overview">
    <div class="tt-ph">
      <span class="tt-ph-title">Sistema Overview</span>
      <span class="tt-ph-badge" id="tt-regime-badge">—</span>
    </div>
    <div class="tto-head">
      <div class="tto-icon">⚡</div>
      <div>
        <div class="tto-account">PYTHIAX ENGINE</div>
        <div class="tto-type">ML Trading Algorítmico</div>
      </div>
    </div>
    <div class="tto-stats" id="tt-overview-stats">
      <!-- JS populates -->
    </div>
    <div class="tto-actions">
      <button class="tto-btn tto-btn-primary"
              onclick="document.getElementById('hero').scrollIntoView({behavior:'smooth'})">⚡ Señales</button>
      <button class="tto-btn"
              onclick="document.getElementById('league').scrollIntoView({behavior:'smooth'})">Liga</button>
      <button class="tto-btn"
              onclick="document.getElementById('heatmap').scrollIntoView({behavior:'smooth'})">Heatmap</button>
    </div>
  </div>

  <!-- 2. PORTFOLIO PERFORMANCE -->
  <div class="tt-panel tt-performance">
    <div class="tt-ph">
      <div>
        <div class="tt-ph-title">Portfolio Performance</div>
        <div style="font-size:10px;color:var(--muted);margin-top:3px" id="tt-perf-sub">Curva acumulada — competencia</div>
      </div>
    </div>
    <div class="ttp-legend" id="tt-perf-legend"><!-- JS --></div>
    <div class="ttp-chart-area" id="tt-perf-chart"><!-- JS --></div>
  </div>

  <!-- 3. MODEL VIEW -->
  <div class="tt-panel tt-market">
    <div class="tt-ph">
      <span class="tt-ph-title">Model View</span>
      <span style="font-size:9px;color:var(--muted)">Top 5 · ranking</span>
    </div>
    <div id="tt-market-body"><!-- JS --></div>
  </div>

</div><!-- /tt-row-top -->

<!-- ROW 2: Positions · Champion Chart ──────────────────────────────── -->
<div class="tt-row tt-row-bottom">

  <!-- 4. OPEN POSITIONS -->
  <div class="tt-panel tt-positions">
    <div class="tt-ph">
      <span class="tt-ph-title">Posiciones Abiertas</span>
      <span class="tt-ph-badge" id="tt-pos-count">— picks</span>
    </div>
    <div class="tbl-scroll">
      <table class="ttp2-table">
        <thead>
          <tr>
            <th>Modelo</th>
            <th>Ticker</th>
            <th class="r">Precio</th>
            <th class="r">MTM%</th>
            <th>Vence</th>
            <th>Tendencia</th>
          </tr>
        </thead>
        <tbody id="tt-positions-body"><!-- JS --></tbody>
      </table>
    </div>
  </div>

  <!-- 5. CHAMPION CHART -->
  <div class="tt-panel tt-chart">
    <div id="tt-chart-head"><!-- JS --></div>
    <div class="ttc-chart-area" id="tt-chart-area"><!-- JS --></div>
  </div>

</div><!-- /tt-row-bottom -->

"""

# ─────────────────────────────────────────────────────────────────────────
# 3.  NEW JS — populates panels from existing DOM data
# ─────────────────────────────────────────────────────────────────────────
NEW_JS = r"""
<script id="v2-tt-init">
(function(){
  /* ── micro helpers ───────────────────────────────────────── */
  var q  = function(sel,ctx){ return (ctx||document).querySelector(sel); };
  var qa = function(sel,ctx){ return Array.from((ctx||document).querySelectorAll(sel)); };
  var esc = function(s){
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  };

  /* ── model colour palette ───────────────────────────────── */
  var MODEL_CLR = {
    V11:'#6ea8cc', V13:'#18e8c8', ML_V97:'#a882ff', ML_V39:'#5dd5b4',
    ML_V39FULL:'#818cf8', ML_V94:'#f59e0b', ML_BRAIN_V11:'#ec4899',
    ML_BRAIN_V11_OPT:'#f97316', ML_V37:'#94a3b8', ML_BRAIN_V10:'#64748b'
  };
  var mc = function(name){ return MODEL_CLR[name] || '#6080a0'; };

  /* ── extract open picks from the signals hero card ──────── */
  function getOpenPicks(){
    var picks = [];
    qa('.svb-row').forEach(function(row){
      var modelEl = q('.svb-rver', row);
      if(!modelEl) return;
      var model = modelEl.textContent.trim();
      var color = modelEl.style.color || mc(model);

      /* find the table that immediately follows svb-sep-open */
      var openSep = q('.svb-sep-open', row);
      if(!openSep) return;
      var el = openSep.nextElementSibling;
      while(el && el.tagName !== 'TABLE') el = el.nextElementSibling;
      if(!el || el.tagName !== 'TABLE') return;

      qa('tr', el).forEach(function(tr){
        var tds = tr.querySelectorAll('td');
        if(tds.length < 4) return;
        var ticker = tds[0].textContent.trim();
        var price  = tds[1].textContent.trim();
        var pct    = tds[2].textContent.trim();
        var pctCls = tds[2].classList.contains('pos') ? 'pos' : 'neg';
        var tgt    = tds[3].textContent.trim();
        picks.push({ model:model, color:color, ticker:ticker,
                     price:price, pct:pct, pctCls:pctCls, target:tgt });
      });
    });
    return picks;
  }

  /* ── extract top-N models from league table ─────────────── */
  function getLeague(n){
    return qa('.leag-row-clickable').slice(0, n||5).map(function(row){
      var name  = (q('td:nth-child(2) strong', row)||{}).textContent||'?';
      var wrEl  = q('td:nth-child(4) strong', row);
      var wr    = wrEl ? wrEl.textContent.trim() : '—';
      var wrCls = wrEl ? (wrEl.classList.contains('pos')?'pos':'neg') : '';
      var ret   = (q('td:nth-child(4) small', row)||{}).textContent||'—';
      var last  = (q('.ult-rueda-td strong', row)||{}).textContent||'—';
      var lastCls = (q('.ult-rueda-td strong', row)||{classList:{contains:function(){return false;}}}).classList.contains('pos') ? 'pos' : 'neg';
      var sparkVals  = [];
      var sparkColor = mc(name.trim());
      try{ sparkVals  = JSON.parse(row.dataset.sparkVals||'[]'); }catch(e){}
      try{ sparkColor = row.dataset.sparkColor || mc(name.trim()); }catch(e){}
      return { model:name.trim(), wr:wr, wrCls:wrCls, ret:ret,
               last:last, lastCls:lastCls, sparkVals:sparkVals, sparkColor:sparkColor };
    });
  }

  /* ── get spark series for a named model ─────────────────── */
  function getModelSpark(name){
    var rows = qa('.leag-row-clickable');
    for(var i=0; i<rows.length; i++){
      var n = (q('td:nth-child(2) strong', rows[i])||{}).textContent||'';
      if(n.trim() === name){
        var vals=[], color=mc(name);
        try{ vals  = JSON.parse(rows[i].dataset.sparkVals||'[]'); }catch(e){}
        try{ color = rows[i].dataset.sparkColor || mc(name); }catch(e){}
        return { vals:vals, color:color };
      }
    }
    return null;
  }

  /* ── build a minimal SVG sparkline ──────────────────────── */
  function miniSpark(vals, color, w, h){
    if(!vals || vals.length < 2) return '';
    var mn=Math.min.apply(null,vals), mx=Math.max.apply(null,vals);
    var rng = mx-mn || 1;
    var pts = vals.map(function(v,i){
      var x = 2 + i/(vals.length-1)*(w-4);
      var y = h-2 - (v-mn)/rng*(h-4);
      return x.toFixed(1)+','+y.toFixed(1);
    }).join(' ');
    return '<svg viewBox="0 0 '+w+' '+h+'" width="'+w+'" height="'+h+'"><polyline points="'+pts
      +'" fill="none" stroke="'+color+'" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }

  /* ── build a multi-series area chart SVG ────────────────── */
  function buildChart(datasets, w, h){
    var allV = [];
    datasets.forEach(function(d){ allV = allV.concat(d.vals); });
    if(!allV.length) return '<svg viewBox="0 0 '+w+' '+h+'"></svg>';

    var mn=Math.min.apply(null,allV), mx=Math.max.apply(null,allV);
    var rng = mx-mn || 1;
    var pad = {t:10, r:10, b:26, l:40};
    var cw  = w-pad.l-pad.r;
    var ch  = h-pad.t-pad.b;
    var svg = '<svg viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none">';

    /* Y-grid */
    var yticks = 4;
    for(var i=0; i<=yticks; i++){
      var frac = i/yticks;
      var gy   = (pad.t + ch*(1-frac)).toFixed(1);
      var gv   = mn + rng*frac;
      var isZ  = Math.abs(gv) < rng*0.05;
      svg += '<line x1="'+pad.l+'" y1="'+gy+'" x2="'+(pad.l+cw)+'" y2="'+gy
           + '" stroke="rgba(130,180,230,'+(isZ?'.28':'.07')+')" stroke-width="'+(isZ?1.5:.7)+'"/>';
      svg += '<text x="'+(pad.l-4)+'" y="'+(parseFloat(gy)+3.5)+'" text-anchor="end"'
           + ' font-size="8" fill="rgba(130,180,230,.5)">'
           + (gv>=0?'+':'')+gv.toFixed(0)+'%</text>';
    }

    /* series */
    datasets.forEach(function(ds){
      if(!ds.vals || ds.vals.length < 2) return;
      var n  = ds.vals.length;
      var pts = ds.vals.map(function(v,i){
        var x = pad.l + i/(n-1)*cw;
        var y = pad.t + ch*(1-(v-mn)/rng);
        return x.toFixed(1)+','+y.toFixed(1);
      }).join(' ');
      var zeroY = (pad.t + ch*(1-(0-mn)/rng)).toFixed(1);
      var x0    = pad.l, xN = (pad.l+cw).toFixed(1);
      svg += '<polygon points="'+x0+','+zeroY+' '+pts+' '+xN+','+zeroY+'"'
           + ' fill="'+ds.color+'" opacity=".11"/>';
      svg += '<polyline points="'+pts+'" fill="none" stroke="'+ds.color
           + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>';
      var lv = ds.vals[n-1];
      var ex = (pad.l+cw).toFixed(1);
      var ey = (pad.t + ch*(1-(lv-mn)/rng)).toFixed(1);
      svg += '<circle cx="'+ex+'" cy="'+ey+'" r="3" fill="'+ds.color+'"/>';
    });

    svg += '</svg>';
    return svg;
  }

  /* ── PANEL 1: Overview ───────────────────────────────────── */
  function doOverview(){
    var statsEl = document.getElementById('tt-overview-stats');
    var badgeEl = document.getElementById('tt-regime-badge');
    if(!statsEl) return;

    /* champion KPI */
    var champKPI = q('[data-bid="kpi-leader"]');
    var champModel= (q('.kc-value', champKPI)||{}).textContent||'—';
    var champSub  = (q('.kc-sub',   champKPI)||{}).textContent||'';
    var wrM  = champSub.match(/([\d.]+)%/);
    var retM = champSub.match(/ret ([+\-][\d.]+%)/);

    /* motor KPI */
    var motorKPI = q('[data-bid="kpi-champion"]');
    var motorSub = (q('.kc-sub', motorKPI)||{}).textContent||'';
    var motorRetM = motorSub.match(/ret ([+\-][\d.]+%)/);

    /* picks hoy */
    var picksKPI = q('[data-bid="kpi-picks"]');
    var picksHoy = (q('.kc-value', picksKPI)||{}).textContent||'0';

    /* regime */
    var regimePill = q('.regime-pill');
    var regime = '';
    if(regimePill){
      qa('span', regimePill).forEach(function(sp){
        if(!sp.classList.contains('rp-dot') && !sp.classList.contains('rp-breadth'))
          regime = sp.textContent.trim();
      });
    }
    var breadth = (q('.rp-breadth')||{}).textContent||'';

    /* sistema */
    var sisKPI = q('[data-bid="kpi-sistema"]');
    var sisScore = (q('.kc-value', sisKPI)||{}).textContent||'—';
    var sisColor = (q('.kc-value', sisKPI)||{style:{color:''}}).style.color || 'var(--green)';

    /* total open picks */
    var openCount = getOpenPicks().length;

    var rows = [
      ['Champion',    '<strong class="tto-value pos">'+esc(champModel)+'</strong>'
                      +(wrM?' <span style="font-size:9.5px;color:var(--muted)">'+esc(wrM[0])+'</span>':'')],
      ['Mejor retorno',  '<strong class="tto-value pos">'+(retM?esc(retM[1]):'—')+'</strong>'],
      ['Motor V13',      '<strong class="tto-value pos">'+(motorRetM?esc(motorRetM[1]):'—')+'</strong>'],
      ['Picks hoy',      '<strong class="tto-value">'+esc(picksHoy)+'</strong>'],
      ['Posiciones abiertas', '<strong class="tto-value">'+openCount+'</strong>'],
      ['Régimen',        '<strong class="tto-value" style="color:'+(regime==='SEGURO'?'var(--green)':'var(--gold)')+'">'+esc(regime)+'</strong>'
                         +'<span style="font-size:9px;color:var(--muted);margin-left:4px">'+esc(breadth)+'</span>'],
      ['Sistema',        '<strong class="tto-value" style="color:'+sisColor+'">'+esc(sisScore)+'</strong>'],
    ];
    statsEl.innerHTML = rows.map(function(r){
      return '<div class="tto-row"><span class="tto-label">'+esc(r[0])+'</span>'+r[1]+'</div>';
    }).join('');

    if(badgeEl){
      badgeEl.textContent = regime||'—';
      if(regime==='SEGURO'){
        badgeEl.style.cssText='font-size:9px;font-weight:800;padding:2px 7px;border-radius:5px;'
          +'background:rgba(68,232,144,.14);color:var(--green);border:1px solid rgba(68,232,144,.28)';
      } else {
        badgeEl.style.cssText='font-size:9px;font-weight:800;padding:2px 7px;border-radius:5px;'
          +'background:rgba(245,184,51,.14);color:var(--gold);border:1px solid rgba(245,184,51,.28)';
      }
    }
  }

  /* ── PANEL 2: Performance Chart ─────────────────────────── */
  function doPerformance(){
    var chartEl  = document.getElementById('tt-perf-chart');
    var legendEl = document.getElementById('tt-perf-legend');
    if(!chartEl) return;

    var models = [
      {name:'ML_V97', label:'ML_V97 (Top rett.)'},
      {name:'V13',    label:'V13 (Motor)'},
      {name:'V11',    label:'V11 (Champion)'}
    ];
    var datasets = [];
    models.forEach(function(m){
      var d = getModelSpark(m.name);
      if(d && d.vals.length) datasets.push({vals:d.vals, color:d.color, label:m.label});
    });
    if(!datasets.length) return;

    var w = chartEl.offsetWidth || 460, h = 160;
    chartEl.innerHTML = buildChart(datasets, w, h);

    legendEl.innerHTML = datasets.map(function(d){
      return '<div class="ttp-leg-item">'
           + '<div class="ttp-leg-line" style="background:'+d.color+'"></div>'
           + '<span>'+esc(d.label)+'</span></div>';
    }).join('');
  }

  /* ── PANEL 3: Market / Model View ───────────────────────── */
  function doMarket(){
    var body = document.getElementById('tt-market-body');
    if(!body) return;
    var league = getLeague(7);
    if(!league.length) return;

    var medals = ['🥇','🥈','🥉','','','',''];
    var html = '<table class="ttm-table"><thead><tr>'
             + '<th>Modelo</th><th class="r">WR</th><th class="r">Ret</th><th class="r">Últ.</th>'
             + '</tr></thead><tbody>';
    league.forEach(function(m, i){
      var clr = mc(m.model);
      var wrNum = parseFloat(m.wr)||0;
      var barW  = Math.max(2, Math.round(wrNum * 0.55));
      html += '<tr onclick="document.getElementById(\'league\').scrollIntoView({behavior:\'smooth\'})">'
            + '<td><span class="ttm-dot" style="background:'+clr+'"></span>'+(medals[i]||'')+'<strong>'+esc(m.model)+'</strong></td>'
            + '<td class="r"><span class="'+m.wrCls+'">'+esc(m.wr)+'</span>'
            + '<span class="ttm-wr-bar" style="width:'+barW+'px;background:'+clr+'"></span></td>'
            + '<td class="r"><small>'+esc(m.ret)+'</small></td>'
            + '<td class="r"><span class="'+m.lastCls+'">'+esc(m.last)+'</span></td>'
            + '</tr>';
    });
    body.innerHTML = html + '</tbody></table>';
  }

  /* ── PANEL 4: Positions ─────────────────────────────────── */
  function doPositions(){
    var tbody   = document.getElementById('tt-positions-body');
    var counter = document.getElementById('tt-pos-count');
    if(!tbody) return;

    var all = getOpenPicks();
    /* deduplicate by model:ticker */
    var seen = {}, unique = [];
    all.forEach(function(p){
      var k = p.model+':'+p.ticker;
      if(!seen[k]){ seen[k]=true; unique.push(p); }
    });

    if(counter) counter.textContent = unique.length + ' posiciones';

    if(!unique.length){
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:18px">Sin posiciones abiertas</td></tr>';
      return;
    }

    var sparkCache = {};
    tbody.innerHTML = unique.map(function(p){
      var clr = mc(p.model);
      if(!sparkCache[p.model]) sparkCache[p.model] = getModelSpark(p.model);
      var sd   = sparkCache[p.model];
      var spk  = sd ? miniSpark(sd.vals.slice(-12), sd.color, 62, 22) : '';
      return '<tr>'
           + '<td><span class="ttp2-m-dot" style="background:'+clr+'"></span>'
           + '<span style="font-size:9.5px;color:var(--muted)">'+esc(p.model)+'</span></td>'
           + '<td><span class="ttp2-ticker">'+esc(p.ticker)+'</span></td>'
           + '<td class="r" style="font-size:11px">'+esc(p.price)+'</td>'
           + '<td class="r"><span class="'+p.pctCls+'" style="font-size:12px">'+esc(p.pct)+'</span></td>'
           + '<td style="font-size:9.5px;color:var(--muted)">'+esc(p.target)+'</td>'
           + '<td>'+spk+'</td>'
           + '</tr>';
    }).join('');
  }

  /* ── PANEL 5: Champion Chart ─────────────────────────────── */
  function doChart(){
    var headEl  = document.getElementById('tt-chart-head');
    var chartEl = document.getElementById('tt-chart-area');
    if(!chartEl) return;

    var chartModel = 'V13';   /* Motor — most active, biggest raw move */
    var data = getModelSpark(chartModel);
    if(!data || !data.vals.length) return;

    /* pull KPI fields from league row data-* attributes */
    var row  = q('[data-bid="leag-'+chartModel+'"]');
    var wr   = row ? (q('td:nth-child(4) strong', row)||{}).textContent||'—' : '—';
    var ret  = row ? (q('td:nth-child(4) small',  row)||{}).textContent||'—' : '—';
    var best = row ? (row.dataset.best||'—')   : '—';
    var worst= row ? (row.dataset.worst||'—')  : '—';
    var shar = row ? (row.dataset.sharpe||'—') : '—';
    var clr  = data.color;

    if(headEl){
      headEl.innerHTML =
        '<div class="tt-ph">'
        + '<div>'
        + '<div style="font-size:15px;font-weight:800;color:'+clr+'">'+esc(chartModel)+'</div>'
        + '<div style="font-size:9.5px;color:var(--muted);margin-top:1px">Motor Experimental</div>'
        + '</div>'
        + '<span class="tt-ph-badge" style="color:'+clr+';border-color:'+clr+'40;background:'+clr+'14">AL DÍA</span>'
        + '</div>'
        + '<div class="ttc-kpis">'
        + '<div class="ttc-kpi"><span>Win Rate</span><strong class="pos">'+esc(wr)+'</strong></div>'
        + '<div class="ttc-kpi"><span>Ret. medio</span><strong class="pos">'+esc(ret)+'</strong></div>'
        + '<div class="ttc-kpi"><span>Mejor</span><strong class="pos">'+esc(best)+'</strong></div>'
        + '<div class="ttc-kpi"><span>Peor</span><strong class="neg">'+esc(worst)+'</strong></div>'
        + '<div class="ttc-kpi"><span>Sharpe</span><strong>'+esc(shar)+'</strong></div>'
        + '</div>';
    }

    var w = chartEl.offsetWidth || 360, h = 180;
    chartEl.innerHTML = buildChart([{vals:data.vals, color:clr, label:chartModel}], w, h);
  }

  /* ── re-render performance chart on resize ──────────────── */
  var _resizeT;
  window.addEventListener('resize', function(){
    clearTimeout(_resizeT);
    _resizeT = setTimeout(function(){
      doPerformance();
      doChart();
    }, 220);
  });

  /* ── init ────────────────────────────────────────────────── */
  function init(){
    doOverview();
    doPerformance();
    doMarket();
    doPositions();
    doChart();
  }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /* expose for console debugging */
  window._v2tt = { doOverview:doOverview, doPerformance:doPerformance,
                   doMarket:doMarket, doPositions:doPositions, doChart:doChart };
})();
</script>
"""

# ─────────────────────────────────────────────────────────────────────────
# 4.  INJECT INTO HTML
# ─────────────────────────────────────────────────────────────────────────

# 4a. CSS → just before </head>
assert '</head>' in html, "ERROR: </head> not found"
html = html.replace('</head>', NEW_CSS + '\n</head>', 1)

# 4b. HTML → after topbar </header>, before the KPI STRIP comment
ANCHOR = '  <!-- KPI STRIP'
assert ANCHOR in html, f"ERROR: anchor '{ANCHOR}' not found"
html = html.replace(ANCHOR, NEW_HTML + '\n' + ANCHOR, 1)

# 4c. JS → just before </body>
assert '</body>' in html, "ERROR: </body> not found"
html = html.replace('</body>', NEW_JS + '\n</body>', 1)

# 4d. Title badge
html = html.replace(
    '<title>Pythiax · Trading Algorítmico</title>',
    '<title>[V2 STAGING] Pythiax · Trading Terminal</title>',
    1
)

# ─────────────────────────────────────────────────────────────────────────
# 5.  WRITE OUTPUT
# ─────────────────────────────────────────────────────────────────────────
with open(DST, 'w', encoding='utf-8') as f:
    f.write(html)

size = os.path.getsize(DST)
print(f"[V2] Generado: {DST}")
print(f"[V2] Tamaño:   {size:,} bytes")
print(f"[V2] URL:      http://localhost:8765/_staging_v2_trading.html")
