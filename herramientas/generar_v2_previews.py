"""
generar_v2_previews.py
Genera 3 variantes V2 del Trading Terminal Dashboard.
Fuente: analisis/_staging_prod_preview.html (INTOCABLE)
Destino: analisis/_staging_v2a_quant.html
         analisis/_staging_v2b_signal.html
         analisis/_staging_v2c_portfolio.html

Cambios respecto a v1:
 - Posiciones: max 10 filas visibles + scroll, fecha target + días restantes
 - Gráfico performance: neon + hover interactivo con fechas y valores
 - Overview reorganizado en secciones claras
 - Model view: híbrido con señales vivas
 - Sin panel V13 chart separado
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(ROOT, "analisis", "_staging_prod_preview.html")

with open(SRC, "r", encoding="utf-8") as f:
    BASE = f.read()

ANCHOR   = '  <!-- KPI STRIP'
HEAD_END = '</head>'
BODY_END = '</body>'

# ════════════════════════════════════════════════════════════════════════
# SHARED CSS — común a los 3 previews
# ════════════════════════════════════════════════════════════════════════
SHARED_CSS = r"""<style id="v2-shared">
body.v2 .kpi-strip,body.v2 section.hero-row,
body.v2 .liga-full,body.v2 [data-bid="heatmap-panel"],
body.v2 .ft-footer{display:none!important}
.v2-wrap{display:flex;flex-direction:column;gap:12px;padding:0 0 28px}
.v2-panel{background:linear-gradient(180deg,rgba(10,16,34,.99) 0%,rgba(6,10,22,.99) 100%);
  border:1px solid rgba(130,180,230,.15);border-radius:12px;padding:14px 16px;
  box-shadow:0 32px 96px rgba(0,0,0,.75);overflow:hidden;position:relative}
.v2-ph{font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.16em;
  color:rgba(130,180,230,.55);margin-bottom:10px;padding-bottom:8px;
  border-bottom:1px solid rgba(130,180,230,.10);display:flex;justify-content:space-between;align-items:center}
.v2-badge{font-size:9px;font-weight:800;padding:2px 8px;border-radius:5px}
.v2-ba-g{background:rgba(68,232,144,.14);color:#44e890;border:1px solid rgba(68,232,144,.28)}
.v2-ba-y{background:rgba(245,184,51,.14);color:#f5b833;border:1px solid rgba(245,184,51,.28)}
.v2-ba-c{background:rgba(24,232,200,.14);color:#18e8c8;border:1px solid rgba(24,232,200,.28)}
.v2-ba-m{background:rgba(168,130,255,.14);color:#a882ff;border:1px solid rgba(168,130,255,.28)}
/* Positions scroll */
.v2-pos-scroll{max-height:434px;overflow-y:auto;scrollbar-width:thin;
  scrollbar-color:rgba(24,232,200,.18) transparent}
.v2-pos-scroll::-webkit-scrollbar{width:4px}
.v2-pos-scroll::-webkit-scrollbar-thumb{background:rgba(24,232,200,.18);border-radius:2px}
/* Table base */
.v2-tbl{width:100%;border-collapse:collapse;font-size:11.5px}
.v2-tbl th{font-size:8px;text-transform:uppercase;letter-spacing:.12em;
  color:rgba(130,180,230,.5);font-weight:700;padding:0 6px 7px;white-space:nowrap}
.v2-tbl th.r{text-align:right}.v2-tbl td{padding:6px 6px;border-top:1px solid rgba(255,255,255,.05);vertical-align:middle}
.v2-tbl td.r{text-align:right;font-weight:700}
.v2-tbl tbody tr:hover{background:rgba(255,255,255,.03)}
.v2-dot{display:inline-block;width:7px;height:7px;border-radius:2px;margin-right:5px;vertical-align:middle}
.v2-tk{font-weight:800;font-size:12.5px}
.v2-chart{position:relative;width:100%}
.v2-chart svg{display:block;width:100%}
.v2-legend{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:9px}
.v2-leg-item{display:flex;align-items:center;gap:5px;font-size:10px;color:rgba(130,180,230,.7)}
.v2-leg-line{width:22px;height:2.5px;border-radius:2px;flex-shrink:0}
</style>"""

# ════════════════════════════════════════════════════════════════════════
# SHARED JS — data extraction + interactive chart engine
# ════════════════════════════════════════════════════════════════════════
SHARED_JS = r"""<script id="v2-shared-js">
(function(){
var q=function(s,c){return(c||document).querySelector(s)};
var qa=function(s,c){return Array.from((c||document).querySelectorAll(s))};
var C={V11:'#6ea8cc',V13:'#00ffe0',ML_V97:'#b070ff',ML_V39:'#06d6a0',
       ML_V39FULL:'#818cf8',ML_V94:'#f59e0b',ML_BRAIN_V11:'#f472b6',
       ML_BRAIN_V11_OPT:'#fb923c',ML_V37:'#94a3b8',ML_BRAIN_V10:'#64748b'};
var mc=function(n){return C[n]||'#8080a0'};

function getSpark(name){
  var rows=qa('.leag-row-clickable');
  for(var i=0;i<rows.length;i++){
    var n=(q('td:nth-child(2) strong',rows[i])||{}).textContent||'';
    if(n.trim()===name){
      var v=[],c=mc(name),l=[];
      try{v=JSON.parse(rows[i].dataset.sparkVals||'[]')}catch(e){}
      try{c=rows[i].dataset.sparkColor||mc(name)}catch(e){}
      try{l=JSON.parse(rows[i].dataset.sparkLabels||'[]')}catch(e){}
      return{vals:v,color:c,labels:l};
    }
  }return null;
}

function daysTo(tgt){
  if(!tgt||tgt==='—')return null;
  var p=tgt.split('/');if(p.length<2)return null;
  var t=new Date(2026,parseInt(p[1])-1,parseInt(p[0]));
  var now=new Date(2026,4,7);
  return Math.round((t-now)/86400000);
}

function getPositions(){
  var picks=[];
  qa('.svb-row').forEach(function(row){
    var me=q('.svb-rver',row);if(!me)return;
    var model=me.textContent.trim(),color=mc(model);
    var mtmEl=q('.svb-mtm-badge',row);
    var mtm=mtmEl?mtmEl.textContent.trim():'';
    var mtmCls=mtmEl?(mtmEl.classList.contains('pos')?'pos':'neg'):'';
    var openSep=q('.svb-sep-open',row);if(!openSep)return;
    var el=openSep.nextElementSibling;
    while(el&&el.tagName!=='TABLE')el=el.nextElementSibling;
    if(!el)return;
    qa('tr',el).forEach(function(tr){
      var tds=tr.querySelectorAll('td');if(tds.length<4)return;
      var tgt=tds[3].textContent.trim().replace('→','');
      var d=daysTo(tgt);
      picks.push({model:model,color:color,
        ticker:tds[0].textContent.trim(),
        price:tds[1].textContent.trim(),
        pct:tds[2].textContent.trim(),
        pctCls:tds[2].classList.contains('pos')?'pos':'neg',
        target:tgt,days:d,mtm:mtm,mtmCls:mtmCls});
    });
  });
  return picks;
}

function getLeague(n){
  return qa('.leag-row-clickable').slice(0,n||10).map(function(row){
    var name=(q('td:nth-child(2) strong',row)||{}).textContent||'?';
    var wrEl=q('td:nth-child(4) strong',row);
    var wr=wrEl?wrEl.textContent.trim():'—';
    var wrCls=wrEl?(wrEl.classList.contains('pos')?'pos':'neg'):'';
    var wrNum=parseFloat(wr)||0;
    var ret=(q('td:nth-child(4) small',row)||{}).textContent||'—';
    var le=q('.ult-rueda-td strong',row);
    var last=le?le.textContent.trim():'—';
    var lastCls=le?(le.classList.contains('pos')?'pos':'neg'):'';
    var w30el=qa('.wnd-td',row)[0];
    var w30wr=(q('.wnd-wr',w30el)||{}).textContent||'—';
    var w30ret=(q('.wnd-ret',w30el)||{}).textContent||'—';
    var w30cls=(q('.wnd-pos',w30el)?'pos':(q('.wnd-neg',w30el)?'neg':''));
    var sv=[],sc=mc(name.trim()),sl=[];
    try{sv=JSON.parse(row.dataset.sparkVals||'[]')}catch(e){}
    try{sc=row.dataset.sparkColor||mc(name.trim())}catch(e){}
    try{sl=JSON.parse(row.dataset.sparkLabels||'[]')}catch(e){}
    var picks=(q('.ticker-list',row)||{}).textContent||'—';
    /* Get open picks count from SVB */
    var svbRow=null;
    qa('.svb-row').forEach(function(r){
      var me=q('.svb-rver',r);
      if(me&&me.textContent.trim()===name.trim())svbRow=r;
    });
    var openSep=svbRow?q('.svb-sep-open',svbRow):null;
    var openN=openSep?(openSep.textContent.match(/(\d+)p/)||[,'0'])[1]:'0';
    var mtmEl=svbRow?q('.svb-mtm-badge',svbRow):null;
    var mtm=mtmEl?mtmEl.textContent.trim():'';
    var mtmCls=mtmEl?(mtmEl.classList.contains('pos')?'pos':'neg'):'';
    return{model:name.trim(),wr:wr,wrCls:wrCls,wrNum:wrNum,ret:ret,
           last:last,lastCls:lastCls,w30wr:w30wr,w30ret:w30ret,w30cls:w30cls,
           sparkVals:sv,sparkColor:sc,sparkLabels:sl,
           sharpe:row.dataset.sharpe||'—',mdd:row.dataset.mdd||'—',
           best:row.dataset.best||'—',worst:row.dataset.worst||'—',
           picks:picks,openN:parseInt(openN)||0,mtm:mtm,mtmCls:mtmCls};
  });
}

function getKPIs(){
  var ch=q('[data-bid="kpi-leader"]'),mo=q('[data-bid="kpi-champion"]');
  var pk=q('[data-bid="kpi-picks"]'),sy=q('[data-bid="kpi-sistema"]');
  var champModel=(q('.kc-value',ch)||{}).textContent||'—';
  var champSub=(q('.kc-sub',ch)||{}).textContent||'';
  var motorModel=(q('.kc-value',mo)||{}).textContent||'—';
  var motorSub=(q('.kc-sub',mo)||{}).textContent||'';
  var picksHoy=parseInt((q('.kc-value',pk)||{}).textContent||'0');
  var sysEl=sy?q('.kc-value',sy):null;
  var sysScore=sysEl?sysEl.textContent.trim():'—';
  var sysColor=sysEl?sysEl.style.color:'var(--green)';
  var regime='SEGURO',breadth='';
  var rp=q('.regime-pill');
  if(rp){qa('span',rp).forEach(function(sp){
    if(!sp.classList.contains('rp-dot')&&!sp.classList.contains('rp-breadth'))
      regime=sp.textContent.trim();
  });breadth=(q('.rp-breadth')||{}).textContent||'';}
  var wrM=champSub.match(/([\d.]+)%/);
  var retM=champSub.match(/ret ([+\-\d.]+%)/);
  var retM2=motorSub.match(/ret ([+\-\d.]+%)/);
  var wrM2=motorSub.match(/WR ([\d.]+)%/);
  return{champModel:champModel,champWR:wrM?wrM[0]:'—',champRet:retM?retM[1]:'—',
         motorModel:motorModel,motorRet:retM2?retM2[1]:'—',
         picksHoy:picksHoy,sysScore:sysScore,sysColor:sysColor,
         regime:regime,breadth:breadth,openCount:getPositions().length};
}

/* ── NEON INTERACTIVE CHART ────────────────────────────────────── */
function buildChart(id,datasets,opts){
  var el=document.getElementById(id);
  if(!el||!datasets||!datasets.length)return;
  el.style.position='relative';el.innerHTML='';
  opts=opts||{};
  var H=opts.height||180,W=el.offsetWidth||500;
  var PAD={t:16,r:opts.endLabels!==false?72:14,b:26,l:46};
  var CW=W-PAD.l-PAD.r,CH=H-PAD.t-PAD.b;
  var allV=[];datasets.forEach(function(d){allV=allV.concat(d.vals)});
  if(!allV.length)return;
  var mn=Math.min.apply(null,allV),mx=Math.max.apply(null,allV);
  var rng=mx-mn||1;mn-=rng*.04;mx+=rng*.04;rng=mx-mn;
  var xp=function(i,n){return PAD.l+(n>1?i/(n-1):0.5)*CW};
  var yp=function(v){return PAD.t+CH*(1-(v-mn)/rng)};
  var s=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+W+' '+H
    +'" preserveAspectRatio="none" style="width:100%;display:block;overflow:visible">'];
  s.push('<defs>');
  datasets.forEach(function(d,i){
    s.push('<filter id="vg'+id+i+'" x="-100%" y="-100%" width="300%" height="300%">');
    s.push('<feGaussianBlur in="SourceGraphic" stdDeviation="3.5" result="b"/>');
    s.push('<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>');
  });
  s.push('</defs>');
  /* grid */
  [0,.25,.5,.75,1].forEach(function(f){
    var v=mn+rng*f,gy=yp(v).toFixed(1);
    var isZ=Math.abs(v)<rng*.05;
    s.push('<line x1="'+PAD.l+'" y1="'+gy+'" x2="'+(PAD.l+CW)+'" y2="'+gy
      +'" stroke="rgba(130,180,230,'+(isZ?.30:.065)+')" stroke-width="'+(isZ?1.4:.6)+'"/>');
    s.push('<text x="'+(PAD.l-4)+'" y="'+(parseFloat(gy)+3.5).toFixed(1)
      +'" text-anchor="end" fill="rgba(130,180,230,.42)" font-size="8">'
      +(v>=0?'+':'')+v.toFixed(0)+'%</text>');
  });
  /* series */
  datasets.forEach(function(ds,di){
    if(!ds.vals||ds.vals.length<2)return;
    var n=ds.vals.length;
    var pts=ds.vals.map(function(v,i){return xp(i,n).toFixed(1)+','+yp(v).toFixed(1)}).join(' ');
    var zy=yp(0).toFixed(1),x0=PAD.l.toFixed(1),xN=xp(n-1,n).toFixed(1);
    var c=ds.color||'#00ffe0';
    s.push('<polygon points="'+x0+','+zy+' '+pts+' '+xN+','+zy+'" fill="'+c+'" opacity=".10"/>');
    s.push('<polyline points="'+pts+'" fill="none" stroke="'+c+'" stroke-width="2" opacity=".38"'
      +' stroke-linecap="round" stroke-linejoin="round" filter="url(#vg'+id+di+')"/>');
    s.push('<polyline points="'+pts+'" fill="none" stroke="'+c+'" stroke-width="2.2"'
      +' stroke-linecap="round" stroke-linejoin="round"/>');
    var lv=ds.vals[n-1],ex=xp(n-1,n).toFixed(1),ey=yp(lv).toFixed(1);
    s.push('<circle cx="'+ex+'" cy="'+ey+'" r="4.5" fill="'+c+'" opacity=".35" filter="url(#vg'+id+di+')"/>');
    s.push('<circle cx="'+ex+'" cy="'+ey+'" r="3.2" fill="'+c+'"/>');
    if(opts.endLabels!==false){
      s.push('<text x="'+(parseFloat(ex)+8)+'" y="'+(parseFloat(ey)+3.5).toFixed(1)
        +'" fill="'+c+'" font-size="11" font-weight="800">'+(lv>=0?'+':'')+lv.toFixed(1)+'%</text>');
    }
  });
  /* crosshair */
  s.push('<line id="vcr'+id+'" x1="'+PAD.l+'" y1="'+PAD.t+'" x2="'+PAD.l+'" y2="'+(PAD.t+CH)
    +'" stroke="rgba(255,255,255,.25)" stroke-width="1" stroke-dasharray="4,3" style="display:none"/>');
  /* overlay */
  s.push('<rect id="vov'+id+'" x="'+PAD.l+'" y="'+PAD.t+'" width="'+CW+'" height="'+CH
    +'" fill="transparent" style="cursor:crosshair"/>');
  s.push('</svg>');
  el.innerHTML=s.join('');
  /* tooltip */
  var tip=document.createElement('div');
  tip.style.cssText='position:absolute;background:rgba(3,7,20,.97);border:1px solid rgba(24,232,200,.20);'
    +'border-radius:8px;padding:8px 12px;font-size:10px;line-height:1.7;pointer-events:none;'
    +'display:none;z-index:50;white-space:nowrap;box-shadow:0 8px 32px rgba(0,0,0,.65)';
  el.appendChild(tip);
  var svg=el.querySelector('svg');
  var cr=document.getElementById('vcr'+id);
  var ov=document.getElementById('vov'+id);
  ov.addEventListener('mousemove',function(e){
    var rect=svg.getBoundingClientRect();
    var scX=W/rect.width;
    var mx2=(e.clientX-rect.left)*scX-PAD.l;
    var fr=Math.max(0,Math.min(1,mx2/CW));
    var cx=(PAD.l+fr*CW).toFixed(1);
    cr.setAttribute('x1',cx);cr.setAttribute('x2',cx);cr.style.display='block';
    var lines=[],dateStr='';
    datasets.forEach(function(ds){
      var idx=Math.round(fr*(ds.vals.length-1));
      var v=ds.vals[idx];
      if(!dateStr&&ds.labels&&ds.labels[idx])
        dateStr=ds.labels[idx].replace('2026-','').replace(/-/g,'/');
      lines.push('<div style="display:flex;justify-content:space-between;gap:14px;color:'+ds.color+'">'
        +'<span>● '+(ds.label||'?')+'</span><b style="color:#eef4fb">'+(v>=0?'+':'')+v.toFixed(2)+'%</b></div>');
    });
    if(dateStr)lines.unshift('<div style="color:rgba(255,255,255,.40);font-size:9px;margin-bottom:4px">📅 '+dateStr+'</div>');
    tip.innerHTML=lines.join('');tip.style.display='block';
    var tipW=tip.offsetWidth||140;
    var tipLeft=(parseFloat(cx)/W*rect.width)+(fr<.6?10:-tipW-10);
    tip.style.left=Math.max(0,Math.min(rect.width-tipW,tipLeft))+'px';
    tip.style.top='8px';
  });
  ov.addEventListener('mouseleave',function(){cr.style.display='none';tip.style.display='none'});
}

/* ── mini sparkline ── */
function msp(vals,color,w,h){
  if(!vals||vals.length<2)return '';
  var mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals),rng=mx-mn||1;
  var pts=vals.map(function(v,i){
    return (2+i/(vals.length-1)*(w-4)).toFixed(1)+','+(h-2-(v-mn)/rng*(h-4)).toFixed(1)
  }).join(' ');
  var lv=vals[vals.length-1],ey=(h-2-(lv-mn)/rng*(h-4)).toFixed(1);
  return '<svg viewBox="0 0 '+w+' '+h+'" width="'+w+'" height="'+h+'" style="display:block;overflow:visible">'
    +'<polyline points="'+pts+'" fill="none" stroke="'+color+'" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
    +' filter="drop-shadow(0 0 2.5px '+color+')"/>'
    +'<circle cx="'+(w-2)+'" cy="'+ey+'" r="2.5" fill="'+color+'"/>'
    +'</svg>';
}

window._v2={getPositions:getPositions,getLeague:getLeague,getKPIs:getKPIs,
            getSpark:getSpark,buildChart:buildChart,msp:msp,mc:mc,daysTo:daysTo};
})();
</script>"""

# ════════════════════════════════════════════════════════════════════════
# PREVIEW A — "QUANT TERMINAL"
# Layout: Left sidebar rail (stats + mini model bars) | Right main
#         Right: Perf chart top + (Model-signals hybrid 50% | Positions 50%) bottom
# Palette: Pure black + single cyan neon accent
# ════════════════════════════════════════════════════════════════════════
A_CSS = r"""<style id="v2a-css">
.v2a-root{display:grid;grid-template-columns:252px 1fr;gap:12px}
.v2a-left{display:flex;flex-direction:column;gap:12px}
.v2a-right{display:flex;flex-direction:column;gap:12px}
.v2a-bottom{display:grid;grid-template-columns:1fr 1fr;gap:12px}
/* overview section dividers */
.v2a-section{margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid rgba(130,180,230,.09)}
.v2a-section:last-child{margin-bottom:0;padding-bottom:0;border-bottom:none}
.v2a-sec-title{font-size:8.5px;text-transform:uppercase;letter-spacing:.18em;color:rgba(24,232,200,.55);
  font-weight:800;margin-bottom:8px;display:flex;align-items:center;gap:6px}
.v2a-sec-title::before{content:'';display:block;width:14px;height:1.5px;background:rgba(24,232,200,.4)}
.v2a-stat{display:flex;justify-content:space-between;padding:5px 0;
  border-top:1px solid rgba(255,255,255,.05);font-size:11px}
.v2a-stat:first-child{border-top:none}
.v2a-sl{color:rgba(130,180,230,.6)}
.v2a-sv{font-weight:800;text-align:right}
/* model mini rows */
.v2a-mrow{display:flex;align-items:center;gap:7px;padding:5px 0;
  border-top:1px solid rgba(255,255,255,.04);font-size:10.5px;cursor:pointer;
  transition:background .10s;border-radius:4px;padding:5px 4px}
.v2a-mrow:first-child{border-top:none}
.v2a-mrow:hover{background:rgba(255,255,255,.03)}
.v2a-mname{font-weight:800;font-size:11px;flex:0 0 auto;min-width:66px;color:#eef4fb}
.v2a-mwr-track{flex:1;height:3px;background:rgba(255,255,255,.07);border-radius:2px;overflow:hidden}
.v2a-mwr-fill{height:100%;border-radius:2px}
.v2a-mret{font-size:10px;text-align:right;flex:0 0 auto;min-width:38px}
@media(max-width:1100px){.v2a-root{grid-template-columns:1fr}.v2a-left{display:none}}
</style>"""

A_HTML = r"""
<!-- ═════════════════════ PREVIEW A: QUANT TERMINAL ═════════════════════ -->
<div class="v2-wrap v2a">
<div class="v2a-root">

  <!-- LEFT SIDEBAR ──────────────────────── -->
  <div class="v2a-left">

    <!-- Overview Panel -->
    <div class="v2-panel" style="flex:1">
      <div class="v2-ph">Sistema Overview<span id="va-regime" class="v2-badge">—</span></div>

      <div class="v2a-section">
        <div class="v2a-sec-title">Motor</div>
        <div id="va-motor-stats"></div>
      </div>

      <div class="v2a-section">
        <div class="v2a-sec-title">Mercado</div>
        <div id="va-market-stats"></div>
      </div>

      <div class="v2a-section">
        <div class="v2a-sec-title">Datos</div>
        <div id="va-data-stats"></div>
      </div>
    </div>

  </div><!-- /left -->

  <!-- RIGHT MAIN ─────────────────────────── -->
  <div class="v2a-right">

    <!-- Performance chart -->
    <div class="v2-panel">
      <div class="v2-ph">Portfolio Performance — Curva acumulada · competencia
        <span style="font-size:9px;color:rgba(130,180,230,.5)">hover para valores</span>
      </div>
      <div class="v2-legend" id="va-leg"></div>
      <div class="v2-chart" id="va-chart"></div>
    </div>

    <!-- Bottom: Model-signals hybrid + Positions -->
    <div class="v2a-bottom">

      <!-- Model + Signals hybrid -->
      <div class="v2-panel">
        <div class="v2-ph">Modelos · Ranking + Señales Activas</div>
        <div id="va-models"></div>
      </div>

      <!-- Positions -->
      <div class="v2-panel">
        <div class="v2-ph">Posiciones Abiertas
          <span class="v2-badge v2-ba-c" id="va-pos-n">—</span>
        </div>
        <div class="v2-pos-scroll">
          <table class="v2-tbl">
            <thead><tr>
              <th>Modelo</th><th>Ticker</th>
              <th class="r">Precio</th><th class="r">MTM%</th>
              <th class="r">Target</th><th class="r">D+</th><th>Trend</th>
            </tr></thead>
            <tbody id="va-pos-body"></tbody>
          </table>
        </div>
      </div>

    </div><!-- /bottom -->
  </div><!-- /right -->
</div><!-- /grid -->
</div><!-- /v2-wrap -->
"""

A_JS = r"""<script id="v2a-init">
(function(){
var d=window._v2;if(!d)return;
var kpis=d.getKPIs();
var league=d.getLeague(10);
var positions=d.getPositions();

/* ── regime badge ── */
var rb=document.getElementById('va-regime');
if(rb){rb.textContent=kpis.regime;
  rb.className='v2-badge '+(kpis.regime==='SEGURO'?'v2-ba-g':'v2-ba-y');}

/* ── overview sections ── */
function stats(id,rows){
  var el=document.getElementById(id);if(!el)return;
  el.innerHTML=rows.map(function(r){
    return '<div class="v2a-stat"><span class="v2a-sl">'+r[0]+'</span><span class="v2a-sv">'+r[1]+'</span></div>';
  }).join('');
}
stats('va-motor-stats',[
  ['Champion',   '<span class="pos">'+kpis.champModel+'</span> · '+kpis.champWR],
  ['Ret. medio', '<span class="pos">'+kpis.champRet+'</span>'],
  ['Motor V13',  '<span class="pos">'+kpis.motorRet+'</span>'],
]);
stats('va-market-stats',[
  ['Régimen',    '<span style="color:'+(kpis.regime==='SEGURO'?'var(--green)':'var(--gold)')+'">'+kpis.regime+'</span>'],
  ['Breadth',    kpis.breadth],
  ['Picks hoy',  kpis.picksHoy],
  ['Abiertas',   kpis.openCount+' posiciones'],
]);
stats('va-data-stats',[
  ['Calidad datos', '<span style="color:'+kpis.sysColor+'">'+kpis.sysScore+'</span>'],
  ['Modelos activos', league.length],
  ['Fecha datos', '2026-05-07'],
]);

/* ── performance chart ── */
var models=[
  {name:'ML_V97',label:'ML_V97'},
  {name:'V13',   label:'V13'},
  {name:'V11',   label:'V11'},
  {name:'ML_V39',label:'ML_V39'},
];
var datasets=[];
models.forEach(function(m){
  var sp=d.getSpark(m.name);
  if(sp&&sp.vals.length)datasets.push({vals:sp.vals,color:sp.color,labels:sp.labels,label:m.label});
});
var legEl=document.getElementById('va-leg');
if(legEl)legEl.innerHTML=datasets.map(function(ds){
  return '<div class="v2-leg-item"><div class="v2-leg-line" style="background:'+ds.color+'"></div><span>'+ds.label+'</span></div>';
}).join('');
setTimeout(function(){d.buildChart('va-chart',datasets,{height:200,endLabels:true})},50);

/* ── model+signals hybrid ── */
var modEl=document.getElementById('va-models');
if(modEl&&league.length){
  var medals=['🥇','🥈','🥉'];
  modEl.innerHTML=league.map(function(m,i){
    var clr=d.mc(m.model);
    var wrW=Math.max(4,Math.round(m.wrNum*.65));
    var spk=d.msp(m.sparkVals.slice(-15),m.sparkColor,70,22);
    var openBadge=m.openN?'<span class="v2-badge v2-ba-c" style="font-size:8px">'+m.openN+'p abiertas</span>':'';
    var mtmTxt=m.openN&&m.mtm?'<span class="'+(m.mtmCls)+'" style="font-size:9.5px">'+m.mtm+'</span>':'';
    return '<div style="display:flex;align-items:center;gap:8px;padding:5.5px 0;'
      +'border-top:1px solid rgba(255,255,255,.05);cursor:pointer" '
      +'onclick="document.getElementById(\'league\').scrollIntoView({behavior:\'smooth\'})">'
      +'<span style="font-size:9.5px;color:rgba(130,180,230,.4);min-width:16px">'+(medals[i]||'#'+(i+1))+'</span>'
      +'<span class="v2-dot" style="background:'+clr+'"></span>'
      +'<span style="font-weight:800;font-size:11px;min-width:90px;color:#eef4fb">'+m.model+'</span>'
      +'<div style="flex:1;height:3px;background:rgba(255,255,255,.07);border-radius:2px;overflow:hidden">'
      +'<div style="height:100%;width:'+wrW+'%;background:'+clr+';border-radius:2px"></div></div>'
      +'<span class="'+m.wrCls+'" style="font-size:10px;min-width:38px;text-align:right">'+m.wr+'</span>'
      +'<span class="'+m.lastCls+'" style="font-size:10px;min-width:40px;text-align:right">'+m.last+'</span>'
      +(spk?'<div>'+spk+'</div>':'')
      +(openBadge?'<div>'+openBadge+' '+mtmTxt+'</div>':'')
      +'</div>';
  }).join('');
}

/* ── positions table ── */
var posN=document.getElementById('va-pos-n');
if(posN)posN.textContent=positions.length+' abiertas';
var tbody=document.getElementById('va-pos-body');
if(tbody&&positions.length){
  tbody.innerHTML=positions.map(function(p){
    var spk=d.getSpark(p.model);
    var sparkHtml=spk?d.msp(spk.vals.slice(-12),spk.color,62,22):'';
    var daysStr=p.days!=null?'+'+p.days+'d':'—';
    var daysColor=p.days!=null&&p.days<=2?'color:var(--rose)':'color:rgba(130,180,230,.55)';
    return '<tr>'
      +'<td><span class="v2-dot" style="background:'+p.color+'"></span>'
      +'<span style="font-size:9.5px;color:rgba(130,180,230,.6)">'+p.model+'</span></td>'
      +'<td><span class="v2-tk">'+p.ticker+'</span></td>'
      +'<td class="r" style="font-size:11px">'+p.price+'</td>'
      +'<td class="r"><span class="'+p.pctCls+'" style="font-size:12px">'+p.pct+'</span></td>'
      +'<td class="r" style="font-size:10px;color:rgba(130,180,230,.7)">'+p.target+'</td>'
      +'<td class="r" style="font-size:9.5px;'+daysColor+'">'+daysStr+'</td>'
      +'<td>'+(sparkHtml||'—')+'</td>'
      +'</tr>';
  }).join('');
}else if(tbody){
  tbody.innerHTML='<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:18px">Sin posiciones abiertas</td></tr>';
}
window.addEventListener('resize',function(){
  setTimeout(function(){d.buildChart('va-chart',datasets,{height:200,endLabels:true})},100);
});
})();
</script>"""

# ════════════════════════════════════════════════════════════════════════
# PREVIEW B — "SIGNAL HUB"
# Layout: KPI pills row | Big full-width perf chart | Bottom 2-col (model-signals 55% | positions 45%)
# Palette: Multi-neon (cyan, purple, green, gold)
# ════════════════════════════════════════════════════════════════════════
B_CSS = r"""<style id="v2b-css">
.v2b-kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:0}
.v2b-kpi{border-radius:12px;padding:13px 15px;border:1px solid}
.v2b-kpi-label{font-size:8.5px;text-transform:uppercase;letter-spacing:.16em;font-weight:800;margin-bottom:7px;opacity:.7}
.v2b-kpi-value{font-size:24px;font-weight:900;letter-spacing:-.03em;line-height:1.05}
.v2b-kpi-sub{font-size:10px;margin-top:4px;opacity:.65}
.v2b-bottom{display:grid;grid-template-columns:56fr 44fr;gap:12px}
/* Model-signals cards */
.v2b-mcard{border:1px solid rgba(255,255,255,.08);border-radius:9px;padding:10px 12px;margin-bottom:7px;
  transition:border-color .12s;cursor:pointer}
.v2b-mcard:hover{border-color:rgba(24,232,200,.22)}
.v2b-mcard:last-child{margin-bottom:0}
.v2b-mc-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.v2b-mc-name{font-weight:800;font-size:13px}
.v2b-mc-kpis{display:flex;gap:14px;font-size:10px;margin-bottom:5px}
.v2b-mc-picks{font-size:10px;color:rgba(130,180,230,.7);margin-top:4px;line-height:1.5}
.v2b-mc-open{display:flex;gap:6px;flex-wrap:wrap;margin-top:4px}
.v2b-pick-chip{font-size:9.5px;font-weight:700;padding:2px 7px;border-radius:5px;
  background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.10)}
@media(max-width:1100px){.v2b-bottom{grid-template-columns:1fr}.v2b-kpis{grid-template-columns:repeat(3,1fr)}}
</style>"""

B_HTML = r"""
<!-- ═════════════════════ PREVIEW B: SIGNAL HUB ═════════════════════ -->
<div class="v2-wrap v2b">

  <!-- KPI PILLS ──────────────────────── -->
  <div class="v2b-kpis" id="vb-kpis"></div>

  <!-- BIG PERFORMANCE CHART ──────────── -->
  <div class="v2-panel">
    <div class="v2-ph" style="margin-bottom:6px">
      <span>Portfolio Performance — 6 modelos · competencia completa</span>
      <span style="font-size:9px;color:rgba(24,232,200,.6)">🎯 hover → valor exacto por modelo y fecha</span>
    </div>
    <div class="v2-legend" id="vb-leg"></div>
    <div class="v2-chart" id="vb-chart"></div>
  </div>

  <!-- BOTTOM ROW ─────────────────────── -->
  <div class="v2b-bottom">

    <!-- Model + Signals hybrid -->
    <div class="v2-panel">
      <div class="v2-ph">Modelos · Señales Vivas + Performance
        <span id="vb-total-open" class="v2-badge v2-ba-c">—</span>
      </div>
      <div id="vb-models"></div>
    </div>

    <!-- Positions -->
    <div class="v2-panel">
      <div class="v2-ph">Posiciones Abiertas
        <span class="v2-badge v2-ba-c" id="vb-pos-n">—</span>
      </div>
      <div class="v2-pos-scroll">
        <table class="v2-tbl">
          <thead><tr>
            <th>Ticker</th><th>Modelo</th>
            <th class="r">Precio</th><th class="r">MTM%</th>
            <th class="r">Target</th><th class="r">D+</th><th>Curva</th>
          </tr></thead>
          <tbody id="vb-pos-body"></tbody>
        </table>
      </div>
    </div>

  </div>
</div>
"""

B_JS = r"""<script id="v2b-init">
(function(){
var d=window._v2;if(!d)return;
var kpis=d.getKPIs();
var league=d.getLeague(8);
var positions=d.getPositions();

/* ── KPI pills ── */
var kpiEl=document.getElementById('vb-kpis');
if(kpiEl){
  var regColor=kpis.regime==='SEGURO'?'rgba(68,232,144,.14)':'rgba(245,184,51,.14)';
  var regBorder=kpis.regime==='SEGURO'?'rgba(68,232,144,.28)':'rgba(245,184,51,.28)';
  var regTxt=kpis.regime==='SEGURO'?'#44e890':'#f5b833';
  var pills=[
    {label:'Régimen Mercado',value:kpis.regime,sub:kpis.breadth,
     bg:regColor,border:regBorder,color:regTxt},
    {label:'Champion',value:kpis.champModel,sub:'WR '+kpis.champWR+' · '+kpis.champRet,
     bg:'rgba(24,232,200,.1)',border:'rgba(24,232,200,.25)',color:'#18e8c8'},
    {label:'Motor V13 · Ret.',value:kpis.motorRet,sub:'ret. medio por trade',
     bg:'rgba(0,255,224,.08)',border:'rgba(0,255,224,.20)',color:'#00ffe0'},
    {label:'Picks hoy',value:kpis.picksHoy,sub:kpis.openCount+' posiciones abiertas',
     bg:'rgba(168,130,255,.10)',border:'rgba(168,130,255,.25)',color:'#a882ff'},
    {label:'Calidad datos',value:kpis.sysScore,sub:'verificación 2026-05-07',
     bg:'rgba(68,232,144,.08)',border:'rgba(68,232,144,.20)',color:kpis.sysColor},
  ];
  kpiEl.innerHTML=pills.map(function(p){
    return '<div class="v2b-kpi" style="background:'+p.bg+';border-color:'+p.border+'">'
      +'<div class="v2b-kpi-label" style="color:'+p.color+'">'+p.label+'</div>'
      +'<div class="v2b-kpi-value" style="color:'+p.color+'">'+p.value+'</div>'
      +'<div class="v2b-kpi-sub">'+p.sub+'</div>'
      +'</div>';
  }).join('');
}

/* ── big performance chart ── */
var models=[
  {name:'ML_V97',label:'ML_V97'},{name:'V13',label:'V13'},
  {name:'V11',label:'V11'},{name:'ML_V39',label:'ML_V39'},
  {name:'ML_BRAIN_V11',label:'BRAIN_V11'},{name:'ML_V94',label:'ML_V94'},
];
var datasets=[];
models.forEach(function(m){
  var sp=d.getSpark(m.name);
  if(sp&&sp.vals.length)datasets.push({vals:sp.vals,color:sp.color,labels:sp.labels,label:m.label});
});
var legEl=document.getElementById('vb-leg');
if(legEl)legEl.innerHTML=datasets.map(function(ds){
  return '<div class="v2-leg-item"><div class="v2-leg-line" style="background:'+ds.color+'"></div><span>'+ds.label+'</span></div>';
}).join('');
setTimeout(function(){d.buildChart('vb-chart',datasets,{height:240,endLabels:true})},50);

/* ── model-signals hybrid ── */
var totOpen=0;positions.forEach(function(p){totOpen++});
var toEl=document.getElementById('vb-total-open');
if(toEl)toEl.textContent=totOpen+' abiertas';
var modEl=document.getElementById('vb-models');
if(modEl&&league.length){
  modEl.innerHTML=league.map(function(m,i){
    var clr=d.mc(m.model);
    /* get open tickers for this model */
    var myPicks=positions.filter(function(p){return p.model===m.model});
    var openChips=myPicks.slice(0,5).map(function(p){
      return '<span class="v2b-pick-chip"><span class="'+p.pctCls+'">'+p.ticker+' '+p.pct+'</span>'
        +' <span style="color:rgba(130,180,230,.45);font-size:8px">→'+p.target+'</span></span>';
    }).join('');
    if(myPicks.length>5)openChips+='<span class="v2b-pick-chip" style="color:var(--muted)">+'+( myPicks.length-5)+'</span>';
    var spk=d.msp(m.sparkVals.slice(-14),m.sparkColor,68,22);
    return '<div class="v2b-mcard" onclick="document.getElementById(\'league\').scrollIntoView({behavior:\'smooth\'})">'
      +'<div class="v2b-mc-head">'
      +'<div style="display:flex;align-items:center;gap:7px">'
      +'<span class="v2-dot" style="background:'+clr+'"></span>'
      +'<span class="v2b-mc-name">'+m.model+'</span>'
      +(m.openN?'<span class="v2-badge v2-ba-c" style="font-size:8px">'+m.openN+'p</span>':'')
      +'</div>'
      +'<div style="display:flex;align-items:center;gap:10px">'
      +(m.openN&&m.mtm?'<span class="'+m.mtmCls+'" style="font-size:11px;font-weight:700">'+m.mtm+'</span>':'')
      +spk+'</div></div>'
      +'<div class="v2b-mc-kpis">'
      +'<span class="'+m.wrCls+'">WR '+m.wr+'</span>'
      +'<span style="color:rgba(130,180,230,.6)">Ret '+m.ret+'</span>'
      +'<span style="color:rgba(130,180,230,.5)">30d: <span class="'+m.w30cls+'">'+m.w30ret+'</span></span>'
      +'<span style="color:rgba(130,180,230,.4)">Últ. '+m.last+'</span>'
      +'</div>'
      +(openChips?'<div class="v2b-mc-open">'+openChips+'</div>':'')
      +'</div>';
  }).join('');
}

/* ── positions table ── */
var posN=document.getElementById('vb-pos-n');if(posN)posN.textContent=positions.length+' abiertas';
var tbody=document.getElementById('vb-pos-body');
if(tbody&&positions.length){
  tbody.innerHTML=positions.map(function(p){
    var spk=d.getSpark(p.model);
    var sparkHtml=spk?d.msp(spk.vals.slice(-10),spk.color,55,20):'';
    var dStr=p.days!=null?'+'+p.days+'d':'—';
    var dC=p.days!=null&&p.days<=2?'color:var(--rose)':'color:rgba(130,180,230,.55)';
    return '<tr>'
      +'<td><span class="v2-tk">'+p.ticker+'</span></td>'
      +'<td><span class="v2-dot" style="background:'+p.color+'"></span>'
      +'<span style="font-size:9.5px;color:rgba(130,180,230,.65)">'+p.model+'</span></td>'
      +'<td class="r" style="font-size:11px">'+p.price+'</td>'
      +'<td class="r"><span class="'+p.pctCls+'" style="font-size:12px">'+p.pct+'</span></td>'
      +'<td class="r" style="font-size:10px;color:rgba(130,180,230,.7)">'+p.target+'</td>'
      +'<td class="r" style="font-size:9.5px;'+dC+'">'+dStr+'</td>'
      +'<td>'+(sparkHtml||'—')+'</td>'
      +'</tr>';
  }).join('');
}else if(tbody){
  tbody.innerHTML='<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:14px">Sin posiciones</td></tr>';
}
window.addEventListener('resize',function(){
  setTimeout(function(){d.buildChart('vb-chart',datasets,{height:240,endLabels:true})},100);
});
})();
</script>"""

# ════════════════════════════════════════════════════════════════════════
# PREVIEW C — "PORTFOLIO MONITOR"
# Layout: Row1: 4 metric cards | Row2: chart 60% + compact model table 40% | Row3: positions full
# Palette: Midnight + gold/green executive tone
# ════════════════════════════════════════════════════════════════════════
C_CSS = r"""<style id="v2c-css">
.v2c-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.v2c-card{border-radius:12px;padding:15px 17px;border:1px solid}
.v2c-card-label{font-size:8.5px;text-transform:uppercase;letter-spacing:.16em;font-weight:800;margin-bottom:8px}
.v2c-card-value{font-size:28px;font-weight:900;letter-spacing:-.04em;line-height:1}
.v2c-card-sub{font-size:10.5px;margin-top:6px;line-height:1.4}
.v2c-card-bar{height:3px;border-radius:2px;margin-top:9px;overflow:hidden;
  background:rgba(255,255,255,.07)}
.v2c-card-bar-fill{height:100%;border-radius:2px}
.v2c-mid{display:grid;grid-template-columns:60fr 40fr;gap:12px}
/* compact model table */
.v2c-mrow{display:flex;align-items:center;gap:8px;padding:6.5px 0;
  border-top:1px solid rgba(255,255,255,.05);font-size:11px}
.v2c-mrow:first-child{border-top:none}
.v2c-mname{font-weight:800;min-width:82px}
.v2c-mwr{flex:1;text-align:right}
.v2c-mret{min-width:44px;text-align:right;font-size:10.5px}
.v2c-mspark{flex-shrink:0}
/* positions full-width */
.v2c-pos-wrap{overflow-x:auto}
@media(max-width:1100px){.v2c-cards{grid-template-columns:repeat(2,1fr)}.v2c-mid{grid-template-columns:1fr}}
</style>"""

C_HTML = r"""
<!-- ═════════════════════ PREVIEW C: PORTFOLIO MONITOR ═════════════════════ -->
<div class="v2-wrap v2c">

  <!-- ROW 1: METRIC CARDS ───────────────── -->
  <div class="v2c-cards" id="vc-cards"></div>

  <!-- ROW 2: CHART + MODEL TABLE ────────── -->
  <div class="v2c-mid">

    <!-- Performance chart (wider) -->
    <div class="v2-panel">
      <div class="v2-ph">Portfolio Performance · Curva acumulada</div>
      <div class="v2-legend" id="vc-leg"></div>
      <div class="v2-chart" id="vc-chart"></div>
    </div>

    <!-- Compact model ranking -->
    <div class="v2-panel">
      <div class="v2-ph">Ranking Modelos
        <span style="font-size:9px;color:rgba(130,180,230,.5)">WR · Ret · 30d</span>
      </div>
      <div id="vc-models"></div>
    </div>

  </div>

  <!-- ROW 3: POSITIONS FULL WIDTH ───────── -->
  <div class="v2-panel">
    <div class="v2-ph">Posiciones Abiertas · Todos los modelos
      <span class="v2-badge v2-ba-c" id="vc-pos-n">—</span>
    </div>
    <div class="v2-pos-scroll v2c-pos-wrap">
      <table class="v2-tbl" style="min-width:700px">
        <thead><tr>
          <th>Modelo</th><th>Ticker</th>
          <th class="r">Precio actual</th><th class="r">MTM %</th>
          <th class="r">Target</th><th class="r">Días</th>
          <th>WR modelo</th><th>Curva modelo</th>
        </tr></thead>
        <tbody id="vc-pos-body"></tbody>
      </table>
    </div>
  </div>

</div>
"""

C_JS = r"""<script id="v2c-init">
(function(){
var d=window._v2;if(!d)return;
var kpis=d.getKPIs();
var league=d.getLeague(10);
var positions=d.getPositions();

/* ── metric cards ── */
var cardsEl=document.getElementById('vc-cards');
if(cardsEl){
  var regColor=kpis.regime==='SEGURO'?'#44e890':'#f5b833';
  var regBg=kpis.regime==='SEGURO'?'rgba(68,232,144,.10)':'rgba(245,184,51,.10)';
  var regBorder=kpis.regime==='SEGURO'?'rgba(68,232,144,.25)':'rgba(245,184,51,.25)';
  var cards=[
    {label:'Champion',value:kpis.champModel,
     sub:'WR '+kpis.champWR+'   Ret '+kpis.champRet,
     color:'#f5b833',bg:'rgba(245,184,51,.10)',border:'rgba(245,184,51,.25)',bar:parseFloat(kpis.champWR)||0},
    {label:'Motor Experimental',value:'V13',
     sub:'Ret. '+kpis.motorRet+' · activo',
     color:'#00ffe0',bg:'rgba(0,255,224,.08)',border:'rgba(0,255,224,.22)',bar:60},
    {label:'Señales activas',value:kpis.openCount,
     sub:kpis.picksHoy+' picks hoy · régimen '+kpis.regime,
     color:regColor,bg:regBg,border:regBorder,bar:kpis.picksHoy*10},
    {label:'Calidad Sistema',value:kpis.sysScore,
     sub:'verificación 2026-05-07',
     color:kpis.sysColor,bg:'rgba(68,232,144,.08)',border:'rgba(68,232,144,.20)',bar:parseFloat(kpis.sysScore)||0},
  ];
  cardsEl.innerHTML=cards.map(function(c){
    return '<div class="v2c-card" style="background:'+c.bg+';border-color:'+c.border+'">'
      +'<div class="v2c-card-label" style="color:'+c.color+'">'+c.label+'</div>'
      +'<div class="v2c-card-value" style="color:'+c.color+'">'+c.value+'</div>'
      +'<div class="v2c-card-sub">'+c.sub+'</div>'
      +'<div class="v2c-card-bar"><div class="v2c-card-bar-fill" style="width:'
      +Math.min(100,c.bar)+'%;background:'+c.color+'"></div></div>'
      +'</div>';
  }).join('');
}

/* ── perf chart ── */
var models=[
  {name:'ML_V97',label:'ML_V97'},{name:'V13',label:'V13'},
  {name:'V11',label:'V11'},{name:'ML_BRAIN_V11',label:'BRAIN_V11'},
];
var datasets=[];
models.forEach(function(m){
  var sp=d.getSpark(m.name);
  if(sp&&sp.vals.length)datasets.push({vals:sp.vals,color:sp.color,labels:sp.labels,label:m.label});
});
var legEl=document.getElementById('vc-leg');
if(legEl)legEl.innerHTML=datasets.map(function(ds){
  return '<div class="v2-leg-item"><div class="v2-leg-line" style="background:'+ds.color+'"></div><span>'+ds.label+'</span></div>';
}).join('');
setTimeout(function(){d.buildChart('vc-chart',datasets,{height:220,endLabels:true})},50);

/* ── compact model ranking ── */
var modEl=document.getElementById('vc-models');
if(modEl&&league.length){
  var medals=['🥇','🥈','🥉'];
  modEl.innerHTML=league.map(function(m,i){
    var clr=d.mc(m.model);
    var spk=d.msp(m.sparkVals.slice(-12),m.sparkColor,62,22);
    return '<div class="v2c-mrow">'
      +'<span style="font-size:9.5px;color:rgba(130,180,230,.4);min-width:18px">'+(medals[i]||''+(i+1))+'</span>'
      +'<span class="v2-dot" style="background:'+clr+'"></span>'
      +'<span class="v2c-mname" style="color:#eef4fb">'+m.model+'</span>'
      +'<div style="flex:1;height:3px;background:rgba(255,255,255,.07);border-radius:2px;overflow:hidden;margin:0 6px">'
      +'<div style="height:100%;width:'+Math.max(4,Math.round(m.wrNum*.65))+'%;background:'+clr+'"></div></div>'
      +'<span class="v2c-mwr '+m.wrCls+'">'+m.wr+'</span>'
      +'<span class="v2c-mret" style="color:rgba(130,180,230,.6)">'+m.w30ret+'</span>'
      +'<div class="v2c-mspark">'+spk+'</div>'
      +'</div>';
  }).join('');
}

/* ── positions full-width table ── */
var posN=document.getElementById('vc-pos-n');if(posN)posN.textContent=positions.length+' abiertas';
var tbody=document.getElementById('vc-pos-body');
if(tbody&&positions.length){
  tbody.innerHTML=positions.map(function(p){
    var spk=d.getSpark(p.model);
    var sparkHtml=spk?d.msp(spk.vals.slice(-14),spk.color,72,24):'';
    /* get WR for this model */
    var myLeague=null;
    league.forEach(function(l){if(l.model===p.model)myLeague=l;});
    var wrTxt=myLeague?myLeague.wr:'—';
    var wrCls=myLeague?myLeague.wrCls:'';
    var dStr=p.days!=null?p.days+'d':'—';
    var dC=p.days!=null&&p.days<=2?'color:var(--rose);font-weight:800':'color:rgba(130,180,230,.55)';
    return '<tr>'
      +'<td><span class="v2-dot" style="background:'+p.color+'"></span>'
      +'<span style="font-size:10px;color:rgba(130,180,230,.7)">'+p.model+'</span></td>'
      +'<td><span class="v2-tk" style="font-size:13px">'+p.ticker+'</span></td>'
      +'<td class="r" style="font-size:11.5px">'+p.price+'</td>'
      +'<td class="r"><span class="'+p.pctCls+'" style="font-size:13px;font-weight:800">'+p.pct+'</span></td>'
      +'<td class="r" style="font-size:11px;color:rgba(130,180,230,.7)">→'+p.target+'</td>'
      +'<td class="r" style="font-size:11px;'+dC+'">'+dStr+'</td>'
      +'<td style="min-width:70px"><span class="'+wrCls+'" style="font-size:12px;font-weight:800">'+wrTxt+'</span></td>'
      +'<td>'+(sparkHtml||'—')+'</td>'
      +'</tr>';
  }).join('');
}else if(tbody){
  tbody.innerHTML='<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:18px">Sin posiciones abiertas</td></tr>';
}
window.addEventListener('resize',function(){
  setTimeout(function(){d.buildChart('vc-chart',datasets,{height:220,endLabels:true})},100);
});
})();
</script>"""

# ════════════════════════════════════════════════════════════════════════
# GENERATOR
# ════════════════════════════════════════════════════════════════════════
def make(label, extra_css, body_html, body_js):
    h = BASE
    # Add v2 class to body
    h = h.replace('<body>', '<body class="v2">', 1)
    # CSS injection
    h = h.replace(HEAD_END, SHARED_CSS + '\n' + extra_css + '\n' + HEAD_END, 1)
    # HTML injection (before KPI strip)
    h = h.replace(ANCHOR, body_html + '\n' + ANCHOR, 1)
    # JS injection
    h = h.replace(BODY_END, SHARED_JS + '\n' + body_js + '\n' + BODY_END, 1)
    # Title
    h = h.replace('<title>Pythiax', '<title>[' + label + '] Pythiax', 1)
    return h

PREVIEWS = [
    ('a_quant',     'V2A · Quant Terminal',      A_CSS, A_HTML, A_JS),
    ('b_signal',    'V2B · Signal Hub',           B_CSS, B_HTML, B_JS),
    ('c_portfolio', 'V2C · Portfolio Monitor',   C_CSS, C_HTML, C_JS),
]

for pid, plabel, pcss, phtml, pjs in PREVIEWS:
    out_html = make(plabel, pcss, phtml, pjs)
    dst = os.path.join(ROOT, 'analisis', '_staging_v2'+pid+'.html')
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(out_html)
    sz = os.path.getsize(dst)
    print(f'[{plabel:28s}] → _staging_v2{pid}.html ({sz:,} bytes)')
    print(f'  URL: http://localhost:8765/_staging_v2{pid}.html')
    print()
