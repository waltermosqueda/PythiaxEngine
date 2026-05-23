"""
generar_v2d_previews.py
Genera 3 variantes V2D del dashboard:
  Layout fijo por variante:
    TOP ROW (3 paneles): Portfolio Performance | Ranking Modelos | Señales Vivas
    FULL WIDTH:          Heatmap (panel prod existente)
    FULL WIDTH:          Overlap (panel prod existente)

Variantes:
  D1 _staging_v2d1_triforce.html   — balanceado, chart dominante (2fr 1.1fr 1.3fr)
  D2 _staging_v2d2_chartking.html  — chart muy ancho (2.6fr 1fr 1fr), ranking+signals compactos
  D3 _staging_v2d3_station.html    — chart izquierda alto | ranking (top) + signals (bottom) derecha

Fuente: analisis/_staging_prod_preview.html (INTOCABLE — solo lectura)
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(ROOT, "analisis", "_staging_prod_preview.html")

with open(SRC, "r", encoding="utf-8") as f:
    BASE = f.read()

ANCHOR   = "  <!-- KPI STRIP"
HEAD_END = "</head>"
BODY_END = "</body>"

# ════════════════════════════════════════════════════════════════════════
# SHARED CSS
# ════════════════════════════════════════════════════════════════════════
SHARED_CSS = r"""<style id="v2d-shared">
/* ── ocultar secciones legacy ── */
body.v2d .kpi-strip,
body.v2d .hero-card,
body.v2d [data-bid="liga-panel"],
body.v2d [data-bid="scanners-panel"],
body.v2d [data-bid="legacy-panel"],
body.v2d .ft-footer { display:none!important }

/* ── mostrar y resetear heatmap + overlap ── */
body.v2d [data-bid="heatmap-panel"],
body.v2d [data-bid="overlap-panel"] {
  display:block!important;
  margin:0 0 14px 0;
  border-radius:12px;
}

/* ── base panel V2D ── */
.v2d-wrap { display:flex; flex-direction:column; gap:14px; padding:0 0 24px }
.v2d-panel {
  background:linear-gradient(180deg,rgba(8,13,28,.99) 0%,rgba(4,8,18,.99) 100%);
  border:1px solid rgba(120,170,220,.14);
  border-radius:12px; padding:15px 17px;
  box-shadow:0 24px 72px rgba(0,0,0,.70);
  overflow:hidden; position:relative;
}
.v2d-ph {
  font-size:8.5px; font-weight:800; text-transform:uppercase; letter-spacing:.18em;
  color:rgba(120,170,220,.50); margin-bottom:11px; padding-bottom:9px;
  border-bottom:1px solid rgba(120,170,220,.09);
  display:flex; justify-content:space-between; align-items:center;
}
.v2d-badge {
  font-size:8.5px; font-weight:800; padding:2px 9px; border-radius:5px;
}
.v2d-ba-c { background:rgba(24,232,200,.12); color:#18e8c8; border:1px solid rgba(24,232,200,.26) }
.v2d-ba-g { background:rgba(68,232,144,.12); color:#44e890; border:1px solid rgba(68,232,144,.26) }
.v2d-ba-y { background:rgba(245,184,51,.12);  color:#f5b833; border:1px solid rgba(245,184,51,.26) }
.v2d-ba-m { background:rgba(168,130,255,.12); color:#a882ff; border:1px solid rgba(168,130,255,.26) }

/* ── legend ── */
.v2d-legend { display:flex; gap:13px; flex-wrap:wrap; margin-bottom:9px }
.v2d-leg-item { display:flex; align-items:center; gap:5px; font-size:10px; color:rgba(120,170,220,.65) }
.v2d-leg-line { width:20px; height:2px; border-radius:2px; flex-shrink:0 }

/* ── señales scroll ── */
.v2d-sig-scroll {
  max-height:360px; overflow-y:auto;
  scrollbar-width:thin; scrollbar-color:rgba(24,232,200,.16) transparent;
}
.v2d-sig-scroll::-webkit-scrollbar { width:3px }
.v2d-sig-scroll::-webkit-scrollbar-thumb { background:rgba(24,232,200,.16); border-radius:2px }

/* ── señales vivas — model block ── */
.v2d-sig-model {
  padding:9px 10px; border-radius:8px;
  border:1px solid rgba(120,170,220,.09);
  background:rgba(255,255,255,.025);
  margin-bottom:6px;
}
.v2d-sig-model:last-child { margin-bottom:0 }
.v2d-sig-mhead {
  display:flex; align-items:center; gap:7px;
  margin-bottom:7px;
}
.v2d-sig-mname { font-weight:800; font-size:12px; color:#eef4fb }
.v2d-sig-mtm { font-size:11px; font-weight:700; margin-left:auto }
.v2d-sig-picks { display:flex; flex-direction:column; gap:3px }
.v2d-pick-row {
  display:flex; align-items:center; gap:8px;
  padding:4px 6px; border-radius:6px;
  background:rgba(255,255,255,.03);
  font-size:11px;
}
.v2d-pick-tk { font-weight:800; font-size:12px; min-width:44px }
.v2d-pick-pct { font-weight:700; min-width:50px }
.v2d-pick-tgt { color:rgba(120,170,220,.55); font-size:9.5px; margin-left:auto }
.v2d-pick-days { font-size:9px; text-align:right; min-width:26px }

/* ── ranking table ── */
.v2d-rank-tbl { width:100%; border-collapse:collapse; font-size:11px }
.v2d-rank-tbl th {
  font-size:7.5px; text-transform:uppercase; letter-spacing:.13em;
  color:rgba(120,170,220,.44); font-weight:700; padding:0 5px 7px; white-space:nowrap;
}
.v2d-rank-tbl th.r { text-align:right }
.v2d-rank-tbl td { padding:5.5px 5px; border-top:1px solid rgba(255,255,255,.05); vertical-align:middle }
.v2d-rank-tbl td.r { text-align:right; font-weight:700 }
.v2d-rank-tbl tbody tr:hover { background:rgba(255,255,255,.03) }
.v2d-dot { display:inline-block; width:7px; height:7px; border-radius:2px; margin-right:5px; vertical-align:middle }
</style>"""

# ════════════════════════════════════════════════════════════════════════
# SHARED JS
# ════════════════════════════════════════════════════════════════════════
SHARED_JS = r"""<script id="v2d-shared-js">
(function(){
var q=function(s,c){return(c||document).querySelector(s)};
var qa=function(s,c){return Array.from((c||document).querySelectorAll(s))};
var MC={V11:'#6ea8cc',V13:'#00ffe0',ML_V97:'#b070ff',ML_V39:'#06d6a0',
        ML_V39FULL:'#818cf8',ML_V94:'#f59e0b',ML_BRAIN_V11:'#f472b6',
        ML_BRAIN_V11_OPT:'#fb923c',ML_V37:'#94a3b8',ML_BRAIN_V10:'#64748b'};
var mc=function(n){return MC[n]||'#8080a0'};

function daysTo(tgt){
  if(!tgt||tgt==='—'||!tgt.includes('/'))return null;
  var p=tgt.split('/');if(p.length<2)return null;
  var t=new Date(2026,parseInt(p[1])-1,parseInt(p[0]));
  var now=new Date(2026,4,8);
  return Math.round((t-now)/86400000);
}

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
    var w30ret=(q('.wnd-ret',w30el)||{}).textContent||'—';
    var w30wr=(q('.wnd-wr',w30el)||{}).textContent||'—';
    var w30cls=(q('.wnd-pos',w30el)?'pos':(q('.wnd-neg',w30el)?'neg':''));
    var sv=[],sc=mc(name.trim()),sl=[];
    try{sv=JSON.parse(row.dataset.sparkVals||'[]')}catch(e){}
    try{sc=row.dataset.sparkColor||mc(name.trim())}catch(e){}
    try{sl=JSON.parse(row.dataset.sparkLabels||'[]')}catch(e){}
    return{model:name.trim(),wr:wr,wrCls:wrCls,wrNum:wrNum,ret:ret,
           last:last,lastCls:lastCls,w30ret:w30ret,w30wr:w30wr,w30cls:w30cls,
           sparkVals:sv,sparkColor:sc,sparkLabels:sl,
           sharpe:row.dataset.sharpe||'—',mdd:row.dataset.mdd||'—'};
  });
}

function getSignals(){
  var models=[];
  qa('.svb-row').forEach(function(row){
    var nameEl=q('.svb-rver',row);if(!nameEl)return;
    var model=nameEl.textContent.trim(),color=mc(model);
    var mtmEl=q('.svb-mtm-badge',row);
    var mtm=mtmEl?mtmEl.textContent.trim():'';
    var mtmCls=mtmEl?(mtmEl.classList.contains('pos')?'pos':'neg'):'';
    var openSep=q('.svb-sep-open',row);if(!openSep)return;
    var openN=parseInt((openSep.textContent.match(/(\d+)p/)||[,'0'])[1])||0;
    if(!openN)return;
    var picks=[];
    var el=openSep.nextElementSibling;
    while(el&&el.tagName!=='TABLE')el=el.nextElementSibling;
    if(el){
      qa('tr',el).forEach(function(tr){
        var tds=tr.querySelectorAll('td');if(tds.length<4)return;
        var tgt=tds[3].textContent.trim().replace('→','').trim();
        picks.push({ticker:tds[0].textContent.trim(),price:tds[1].textContent.trim(),
          pct:tds[2].textContent.trim(),pctCls:tds[2].classList.contains('pos')?'pos':'neg',
          target:tgt,days:daysTo(tgt)});
      });
    }
    models.push({model:model,color:color,mtm:mtm,mtmCls:mtmCls,openN:openN,picks:picks});
  });
  return models;
}

function getKPIs(){
  var ch=q('[data-bid="kpi-leader"]'),mo=q('[data-bid="kpi-champion"]');
  var pk=q('[data-bid="kpi-picks"]'),sy=q('[data-bid="kpi-sistema"]');
  var champModel=(q('.kc-value',ch)||{}).textContent||'—';
  var champSub=(q('.kc-sub',ch)||{}).textContent||'';
  var motorSub=(q('.kc-sub',mo)||{}).textContent||'';
  var picksHoy=parseInt((q('.kc-value',pk)||{}).textContent||'0');
  var sysEl=sy?q('.kc-value',sy):null;
  var sysScore=sysEl?sysEl.textContent.trim():'—';
  var sysColor=sysEl?sysEl.style.color:'var(--green)';
  var regime='SEGURO';
  var rp=q('.regime-pill');
  if(rp){qa('span',rp).forEach(function(sp){
    if(!sp.classList.contains('rp-dot')&&!sp.classList.contains('rp-breadth'))
      regime=sp.textContent.trim();
  });}
  var wrM=champSub.match(/([\d.]+)%/);
  var retM=champSub.match(/ret ([+\-\d.]+%)/);
  var retM2=motorSub.match(/ret ([+\-\d.]+%)/);
  return{champModel:champModel,champWR:wrM?wrM[0]:'—',champRet:retM?retM[1]:'—',
         motorRet:retM2?retM2[1]:'—',picksHoy:picksHoy,
         sysScore:sysScore,sysColor:sysColor,regime:regime};
}

/* ── NEON INTERACTIVE CHART ── */
function buildChart(id,datasets,opts){
  var el=document.getElementById(id);
  if(!el||!datasets||!datasets.length)return;
  el.style.position='relative';el.innerHTML='';
  opts=opts||{};
  var H=opts.height||200;
  var W=el.getBoundingClientRect().width||el.offsetWidth||600;
  if(W<80)W=600;
  var PAD={t:14,r:opts.endLabels!==false?74:14,b:26,l:44};
  var CW=W-PAD.l-PAD.r,CH=H-PAD.t-PAD.b;
  var allV=[];datasets.forEach(function(d){allV=allV.concat(d.vals)});
  if(!allV.length)return;
  var mn=Math.min.apply(null,allV),mx=Math.max.apply(null,allV);
  var rng=mx-mn||1;mn-=rng*.05;mx+=rng*.05;rng=mx-mn;
  var xp=function(i,n){return PAD.l+(n>1?i/(n-1):0.5)*CW};
  var yp=function(v){return PAD.t+CH*(1-(v-mn)/rng)};
  var svgParts=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+W+' '+H
    +'" preserveAspectRatio="none" style="width:100%;display:block;overflow:visible">'];
  svgParts.push('<defs>');
  datasets.forEach(function(d,i){
    svgParts.push('<filter id="gf'+id+i+'" x="-120%" y="-120%" width="340%" height="340%">');
    svgParts.push('<feGaussianBlur in="SourceGraphic" stdDeviation="3" result="b"/>');
    svgParts.push('<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>');
  });
  svgParts.push('</defs>');
  /* grid lines */
  [0,.25,.5,.75,1].forEach(function(f){
    var v=mn+rng*f,gy=yp(v).toFixed(1);
    var isZ=Math.abs(v)<rng*.06;
    svgParts.push('<line x1="'+PAD.l+'" y1="'+gy+'" x2="'+(PAD.l+CW)+'" y2="'+gy+'"'
      +' stroke="rgba(120,170,220,'+(isZ?.28:.06)+')" stroke-width="'+(isZ?1.2:.5)+'"/>');
    svgParts.push('<text x="'+(PAD.l-5)+'" y="'+(parseFloat(gy)+3).toFixed(1)+'"'
      +' text-anchor="end" fill="rgba(120,170,220,.38)" font-size="7.5">'
      +(v>=0?'+':'')+v.toFixed(0)+'%</text>');
  });
  /* series */
  datasets.forEach(function(ds,di){
    if(!ds.vals||ds.vals.length<2)return;
    var n=ds.vals.length,c=ds.color||'#00ffe0';
    var pts=ds.vals.map(function(v,i){return xp(i,n).toFixed(1)+','+yp(v).toFixed(1)}).join(' ');
    var zy=yp(0).toFixed(1),x0=PAD.l.toFixed(1),xN=xp(n-1,n).toFixed(1);
    svgParts.push('<polygon points="'+x0+','+zy+' '+pts+' '+xN+','+zy+'" fill="'+c+'" opacity=".08"/>');
    svgParts.push('<polyline points="'+pts+'" fill="none" stroke="'+c+'" stroke-width="2.5" opacity=".35"'
      +' stroke-linecap="round" stroke-linejoin="round" filter="url(#gf'+id+di+')"/>');
    svgParts.push('<polyline points="'+pts+'" fill="none" stroke="'+c+'" stroke-width="2"'
      +' stroke-linecap="round" stroke-linejoin="round"/>');
    var lv=ds.vals[n-1],ex=xp(n-1,n).toFixed(1),ey=yp(lv).toFixed(1);
    svgParts.push('<circle cx="'+ex+'" cy="'+ey+'" r="5" fill="'+c+'" opacity=".28" filter="url(#gf'+id+di+')"/>');
    svgParts.push('<circle cx="'+ex+'" cy="'+ey+'" r="3" fill="'+c+'"/>');
    if(opts.endLabels!==false){
      svgParts.push('<text x="'+(parseFloat(ex)+7)+'" y="'+(parseFloat(ey)+3.5).toFixed(1)+'"'
        +' fill="'+c+'" font-size="11" font-weight="800">'+(lv>=0?'+':'')+lv.toFixed(1)+'%</text>');
    }
  });
  /* crosshair */
  svgParts.push('<line id="cr_'+id+'" x1="'+PAD.l+'" y1="'+PAD.t+'" x2="'+PAD.l+'" y2="'+(PAD.t+CH)+'"'
    +' stroke="rgba(255,255,255,.22)" stroke-width="1" stroke-dasharray="4,3" style="display:none"/>');
  svgParts.push('<rect id="ov_'+id+'" x="'+PAD.l+'" y="'+PAD.t+'" width="'+CW+'" height="'+CH+'"'
    +' fill="transparent" style="cursor:crosshair"/>');
  svgParts.push('</svg>');
  el.innerHTML=svgParts.join('');
  /* tooltip */
  var tip=document.createElement('div');
  tip.style.cssText='position:absolute;background:rgba(2,6,18,.96);border:1px solid rgba(24,232,200,.18);'
    +'border-radius:8px;padding:9px 13px;font-size:10px;line-height:1.75;pointer-events:none;'
    +'display:none;z-index:60;white-space:nowrap;box-shadow:0 8px 40px rgba(0,0,0,.7)';
  el.appendChild(tip);
  var svg=el.querySelector('svg'),PAD_=PAD;
  var cr=document.getElementById('cr_'+id),ov=document.getElementById('ov_'+id);
  ov.addEventListener('mousemove',function(e){
    var rect=svg.getBoundingClientRect(),scX=W/rect.width;
    var mx2=(e.clientX-rect.left)*scX-PAD_.l;
    var fr=Math.max(0,Math.min(1,mx2/CW));
    var cx=(PAD_.l+fr*CW).toFixed(1);
    cr.setAttribute('x1',cx);cr.setAttribute('x2',cx);cr.style.display='block';
    var lines=[],dateStr='';
    datasets.forEach(function(ds){
      var idx=Math.round(fr*(ds.vals.length-1));
      var v=ds.vals[idx];
      if(!dateStr&&ds.labels&&ds.labels[idx])
        dateStr=ds.labels[idx].replace('2026-','').replace(/-/g,'/');
      lines.push('<div style="display:flex;justify-content:space-between;gap:16px">'
        +'<span style="color:'+ds.color+'">● '+(ds.label||'?')+'</span>'
        +'<b style="color:#f0f4ff">'+(v>=0?'+':'')+v.toFixed(2)+'%</b></div>');
    });
    if(dateStr)lines.unshift('<div style="color:rgba(255,255,255,.38);font-size:8.5px;margin-bottom:5px">📅 '+dateStr+'</div>');
    tip.innerHTML=lines.join('');tip.style.display='block';
    var tipW=tip.offsetWidth||150;
    var pxLeft=parseFloat(cx)/W*rect.width;
    tip.style.left=Math.max(0,Math.min(rect.width-tipW,pxLeft+(fr<.6?10:-tipW-10)))+'px';
    tip.style.top='4px';
  });
  ov.addEventListener('mouseleave',function(){cr.style.display='none';tip.style.display='none'});
}

/* ── mini sparkline inline SVG ── */
function msp(vals,color,w,h){
  if(!vals||vals.length<2)return '';
  var mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals),rng=mx-mn||1;
  var pts=vals.map(function(v,i){
    return (2+i/(vals.length-1)*(w-4)).toFixed(1)+','+(h-2-(v-mn)/rng*(h-4)).toFixed(1)
  }).join(' ');
  var lv=vals[vals.length-1],ey=(h-2-(lv-mn)/rng*(h-4)).toFixed(1);
  return '<svg viewBox="0 0 '+w+' '+h+'" width="'+w+'" height="'+h+'"'
    +' style="display:block;overflow:visible;flex-shrink:0">'
    +'<polyline points="'+pts+'" fill="none" stroke="'+color+'" stroke-width="2"'
    +' stroke-linecap="round" stroke-linejoin="round"'
    +' filter="drop-shadow(0 0 2px '+color+')"/>'
    +'<circle cx="'+(w-2)+'" cy="'+ey+'" r="2.5" fill="'+color+'"/>'
    +'</svg>';
}

/* ── render señales vivas ── */
function renderSignals(containerId, compact){
  var el=document.getElementById(containerId);if(!el)return 0;
  var sigs=getSignals();
  if(!sigs.length){
    el.innerHTML='<div style="text-align:center;color:rgba(120,170,220,.45);padding:20px 0">Sin señales activas</div>';
    return 0;
  }
  var total=0;
  el.innerHTML=sigs.map(function(m){
    total+=m.picks.length;
    var pickRows=m.picks.map(function(p){
      var dStr=p.days!=null?p.days+'d':'—';
      var dC=p.days!=null&&p.days<=2?'color:var(--rose)':'color:rgba(120,170,220,.45)';
      if(compact){
        return '<div class="v2d-pick-row">'
          +'<span class="v2d-pick-tk">'+p.ticker+'</span>'
          +'<span class="v2d-pick-pct '+p.pctCls+'">'+p.pct+'</span>'
          +'<span class="v2d-pick-tgt">→'+p.target+'</span>'
          +'<span class="v2d-pick-days" style="'+dC+'">'+dStr+'</span>'
          +'</div>';
      }
      return '<div class="v2d-pick-row">'
        +'<span class="v2d-pick-tk">'+p.ticker+'</span>'
        +'<span class="v2d-pick-pct '+p.pctCls+'">'+p.pct+'</span>'
        +'<span style="font-size:10px;color:rgba(120,170,220,.5)">'+p.price+'</span>'
        +'<span class="v2d-pick-tgt">→'+p.target+'</span>'
        +'<span class="v2d-pick-days" style="'+dC+'">'+dStr+'</span>'
        +'</div>';
    }).join('');
    return '<div class="v2d-sig-model">'
      +'<div class="v2d-sig-mhead">'
      +'<span class="v2d-dot" style="background:'+m.color+';display:inline-block;width:7px;height:7px;border-radius:2px;flex-shrink:0"></span>'
      +'<span class="v2d-sig-mname">'+m.model+'</span>'
      +'<span class="v2d-badge v2d-ba-c" style="font-size:8px;margin-left:5px">'+m.openN+'p</span>'
      +(m.mtm?'<span class="v2d-sig-mtm '+m.mtmCls+'">'+m.mtm+'</span>':'')
      +'</div>'
      +'<div class="v2d-sig-picks">'+pickRows+'</div>'
      +'</div>';
  }).join('');
  return total;
}

/* ── render ranking table ── */
function renderRanking(containerId, n, compactMode){
  var el=document.getElementById(containerId);if(!el)return;
  var league=getLeague(n||10);
  if(!league.length){el.innerHTML='<p style="color:var(--muted)">Sin datos</p>';return;}
  var medals=['🥇','🥈','🥉'];
  if(compactMode){
    /* ultra-compact: name + wr bar + ret only */
    el.innerHTML=league.map(function(m,i){
      var clr=mc(m.model);
      var spk=msp(m.sparkVals.slice(-14),m.sparkColor,62,20);
      return '<div style="display:flex;align-items:center;gap:6px;padding:5px 0;'
        +'border-top:1px solid rgba(255,255,255,.05)">'
        +(i===0?'<span style="font-size:8px;min-width:14px">🥇</span>':
          '<span style="font-size:9px;color:rgba(120,170,220,.38);min-width:14px">#'+(i+1)+'</span>')
        +'<span class="v2d-dot" style="background:'+clr+'"></span>'
        +'<span style="font-weight:800;font-size:11px;flex:1;color:#e8eef8">'+m.model+'</span>'
        +'<span class="'+m.wrCls+'" style="font-size:11px;font-weight:700;min-width:40px;text-align:right">'+m.wr+'</span>'
        +'<span class="'+m.lastCls+'" style="font-size:10px;min-width:40px;text-align:right;color:rgba(255,255,255,.55)">'+m.last+'</span>'
        +spk
        +'</div>';
    }).join('');
    return;
  }
  /* full ranking table */
  var rows=league.map(function(m,i){
    var clr=mc(m.model);
    var spk=msp(m.sparkVals.slice(-14),m.sparkColor,66,22);
    var wrW=Math.max(4,Math.round(m.wrNum*.65));
    return '<tr>'
      +'<td style="color:rgba(120,170,220,.38);font-size:9px">'+(medals[i]||'#'+(i+1))+'</td>'
      +'<td><span class="v2d-dot" style="background:'+clr+'"></span>'
        +'<span style="font-weight:800;color:#eef4fb">'+m.model+'</span></td>'
      +'<td class="r"><span class="'+m.wrCls+'">'+m.wr+'</span></td>'
      +'<td class="r" style="color:rgba(120,170,220,.6)">'+m.ret+'</td>'
      +'<td class="r"><span class="'+m.lastCls+'" style="font-size:10.5px">'+m.last+'</span></td>'
      +'<td class="r"><span class="'+m.w30cls+'" style="font-size:10px">'+m.w30ret+'</span></td>'
      +'<td><div style="width:54px;height:3px;background:rgba(255,255,255,.07);border-radius:2px;overflow:hidden">'
        +'<div style="height:100%;width:'+wrW+'%;background:'+clr+'"></div></div></td>'
      +'<td>'+spk+'</td>'
      +'</tr>';
  }).join('');
  el.innerHTML='<table class="v2d-rank-tbl"><thead><tr>'
    +'<th></th><th>Modelo</th><th class="r">WR</th><th class="r">Ret.</th>'
    +'<th class="r">Últ.</th><th class="r">30d</th><th>Bar</th><th>Curva</th>'
    +'</tr></thead><tbody>'+rows+'</tbody></table>';
}

window._v2d={getSignals:getSignals,getLeague:getLeague,getKPIs:getKPIs,
             getSpark:getSpark,buildChart:buildChart,msp:msp,mc:mc,
             renderSignals:renderSignals,renderRanking:renderRanking};
})();
</script>"""

# ════════════════════════════════════════════════════════════════════════
# VARIANTE D1 — "TRIFORCE"
# Grid: 2fr | 1.1fr | 1.3fr — chart dominante, ranking tabla completa, signals scroll
# Palette: navy-black + cyan + gold
# ════════════════════════════════════════════════════════════════════════
D1_CSS = r"""<style id="v2d1-css">
.v2d1-top { display:grid; grid-template-columns:2fr 1.1fr 1.3fr; gap:14px; align-items:start }
@media(max-width:1100px){ .v2d1-top { grid-template-columns:1fr } }
</style>"""

D1_HTML = r"""
<!-- ════════════ V2D1 · TRIFORCE ════════════ -->
<div class="v2d-wrap v2d1">
  <div class="v2d1-top">

    <!-- Portfolio Performance -->
    <div class="v2d-panel">
      <div class="v2d-ph">Portfolio Performance
        <span id="vd1-regime" class="v2d-badge">—</span>
      </div>
      <div class="v2d-legend" id="vd1-leg"></div>
      <div id="vd1-chart" style="position:relative"></div>
    </div>

    <!-- Ranking Modelos -->
    <div class="v2d-panel">
      <div class="v2d-ph">Ranking Modelos <span style="font-size:8px;color:rgba(120,170,220,.4)">competencia</span></div>
      <div id="vd1-ranking"></div>
    </div>

    <!-- Señales Vivas -->
    <div class="v2d-panel">
      <div class="v2d-ph">Señales Vivas
        <span class="v2d-badge v2d-ba-c" id="vd1-sig-n">—</span>
      </div>
      <div class="v2d-sig-scroll" id="vd1-signals"></div>
    </div>

  </div>
</div><!-- /v2d1 -->
"""

D1_JS = r"""<script id="v2d1-init">
(function(){
  var d=window._v2d; if(!d)return;
  var kpis=d.getKPIs();
  /* regime badge */
  var rb=document.getElementById('vd1-regime');
  if(rb){rb.textContent=kpis.regime;rb.className='v2d-badge '+(kpis.regime==='SEGURO'?'v2d-ba-g':'v2d-ba-y')}
  /* chart — 4 main models */
  var models=[{n:'ML_V97'},{n:'V13'},{n:'V11'},{n:'ML_V39'},{n:'ML_BRAIN_V11'}];
  var datasets=[];
  models.forEach(function(m){
    var sp=d.getSpark(m.n);
    if(sp&&sp.vals.length)datasets.push({vals:sp.vals,color:sp.color,labels:sp.labels,label:m.n});
  });
  var legEl=document.getElementById('vd1-leg');
  if(legEl)legEl.innerHTML=datasets.map(function(ds){
    return '<div class="v2d-leg-item"><div class="v2d-leg-line" style="background:'+ds.color+'"></div><span>'+ds.label+'</span></div>';
  }).join('');
  setTimeout(function(){d.buildChart('vd1-chart',datasets,{height:225,endLabels:true})},60);
  window.addEventListener('resize',function(){setTimeout(function(){d.buildChart('vd1-chart',datasets,{height:225,endLabels:true})},120)});
  /* ranking — full table */
  d.renderRanking('vd1-ranking',10,false);
  /* signals */
  var total=d.renderSignals('vd1-signals',false);
  var sn=document.getElementById('vd1-sig-n');
  if(sn)sn.textContent=total+' abiertas';
})();
</script>"""

# ════════════════════════════════════════════════════════════════════════
# VARIANTE D2 — "CHART KING"
# Grid: 2.6fr | 1fr | 1fr — chart muy ancho con 6 modelos; ranking y signals ultra-compactos
# Palette: deep black + green neon
# ════════════════════════════════════════════════════════════════════════
D2_CSS = r"""<style id="v2d2-css">
.v2d2-top { display:grid; grid-template-columns:2.6fr 1fr 1fr; gap:14px; align-items:start }
.v2d2-sig-compact .v2d-pick-row { padding:3px 5px; font-size:10.5px }
.v2d2-sig-compact .v2d-pick-tk { font-size:11.5px; min-width:38px }
.v2d2-sig-compact .v2d-sig-model { padding:7px 8px }
@media(max-width:1100px){ .v2d2-top { grid-template-columns:1fr } }
</style>"""

D2_HTML = r"""
<!-- ════════════ V2D2 · CHART KING ════════════ -->
<div class="v2d-wrap v2d2">
  <div class="v2d2-top">

    <!-- Portfolio Performance — ancho con 6 modelos -->
    <div class="v2d-panel">
      <div class="v2d-ph">
        <span>Portfolio Performance · 6 modelos en competencia</span>
        <span class="v2d-badge v2d-ba-g" id="vd2-regime">—</span>
      </div>
      <div class="v2d-legend" id="vd2-leg"></div>
      <div id="vd2-chart" style="position:relative"></div>
    </div>

    <!-- Ranking — ultra compacto -->
    <div class="v2d-panel">
      <div class="v2d-ph">Ranking</div>
      <div id="vd2-ranking"></div>
    </div>

    <!-- Señales Vivas — compacto -->
    <div class="v2d-panel">
      <div class="v2d-ph">Señales Vivas
        <span class="v2d-badge v2d-ba-c" id="vd2-sig-n">—</span>
      </div>
      <div class="v2d-sig-scroll v2d2-sig-compact" id="vd2-signals"></div>
    </div>

  </div>
</div><!-- /v2d2 -->
"""

D2_JS = r"""<script id="v2d2-init">
(function(){
  var d=window._v2d; if(!d)return;
  var kpis=d.getKPIs();
  var rb=document.getElementById('vd2-regime');
  if(rb){rb.textContent=kpis.regime;rb.className='v2d-badge '+(kpis.regime==='SEGURO'?'v2d-ba-g':'v2d-ba-y')}
  /* 6 modelos */
  var models=[{n:'ML_V97'},{n:'V13'},{n:'V11'},{n:'ML_V39'},{n:'ML_BRAIN_V11'},{n:'ML_V94'}];
  var datasets=[];
  models.forEach(function(m){
    var sp=d.getSpark(m.n);
    if(sp&&sp.vals.length)datasets.push({vals:sp.vals,color:sp.color,labels:sp.labels,label:m.n});
  });
  var legEl=document.getElementById('vd2-leg');
  if(legEl)legEl.innerHTML=datasets.map(function(ds){
    return '<div class="v2d-leg-item"><div class="v2d-leg-line" style="background:'+ds.color+'"></div><span>'+ds.label+'</span></div>';
  }).join('');
  setTimeout(function(){d.buildChart('vd2-chart',datasets,{height:260,endLabels:true})},60);
  window.addEventListener('resize',function(){setTimeout(function(){d.buildChart('vd2-chart',datasets,{height:260,endLabels:true})},120)});
  /* ultra-compact ranking */
  d.renderRanking('vd2-ranking',10,true);
  /* compact signals */
  var total=d.renderSignals('vd2-signals',true);
  var sn=document.getElementById('vd2-sig-n');
  if(sn)sn.textContent=total+' abiertas';
})();
</script>"""

# ════════════════════════════════════════════════════════════════════════
# VARIANTE D3 — "SIDE STATION"
# Left (60%): chart alto | Right (40%): ranking (top) + signals (bottom scroll)
# Palette: deep space + multi-neon
# ════════════════════════════════════════════════════════════════════════
D3_CSS = r"""<style id="v2d3-css">
.v2d3-top { display:grid; grid-template-columns:3fr 2fr; gap:14px; align-items:start }
.v2d3-right { display:flex; flex-direction:column; gap:14px }
.v2d3-ranking-wrap { max-height:240px; overflow-y:auto;
  scrollbar-width:thin; scrollbar-color:rgba(120,170,220,.14) transparent }
.v2d3-ranking-wrap::-webkit-scrollbar { width:3px }
.v2d3-ranking-wrap::-webkit-scrollbar-thumb { background:rgba(120,170,220,.14); border-radius:2px }
@media(max-width:1100px){ .v2d3-top { grid-template-columns:1fr } }
</style>"""

D3_HTML = r"""
<!-- ════════════ V2D3 · SIDE STATION ════════════ -->
<div class="v2d-wrap v2d3">
  <div class="v2d3-top">

    <!-- LEFT: Portfolio Performance (tall) -->
    <div class="v2d-panel">
      <div class="v2d-ph">Portfolio Performance
        <span class="v2d-badge v2d-ba-c" id="vd3-regime">—</span>
      </div>
      <div class="v2d-legend" id="vd3-leg"></div>
      <div id="vd3-chart" style="position:relative"></div>
      <!-- mini KPI strip below chart -->
      <div id="vd3-kpi-strip" style="display:flex;gap:14px;flex-wrap:wrap;margin-top:14px;padding-top:12px;border-top:1px solid rgba(120,170,220,.09)"></div>
    </div>

    <!-- RIGHT: Ranking + Signals stacked -->
    <div class="v2d3-right">

      <!-- Ranking Modelos -->
      <div class="v2d-panel">
        <div class="v2d-ph">Ranking Modelos</div>
        <div class="v2d3-ranking-wrap" id="vd3-ranking"></div>
      </div>

      <!-- Señales Vivas -->
      <div class="v2d-panel" style="flex:1">
        <div class="v2d-ph">Señales Vivas
          <span class="v2d-badge v2d-ba-c" id="vd3-sig-n">—</span>
        </div>
        <div class="v2d-sig-scroll" id="vd3-signals"></div>
      </div>

    </div><!-- /right -->
  </div>
</div><!-- /v2d3 -->
"""

D3_JS = r"""<script id="v2d3-init">
(function(){
  var d=window._v2d; if(!d)return;
  var kpis=d.getKPIs();
  var rb=document.getElementById('vd3-regime');
  if(rb){rb.textContent=kpis.regime;rb.className='v2d-badge '+(kpis.regime==='SEGURO'?'v2d-ba-g':'v2d-ba-y')}
  /* chart 5 models, tall */
  var models=[{n:'ML_V97'},{n:'V13'},{n:'V11'},{n:'ML_V39'},{n:'ML_BRAIN_V11'}];
  var datasets=[];
  models.forEach(function(m){
    var sp=d.getSpark(m.n);
    if(sp&&sp.vals.length)datasets.push({vals:sp.vals,color:sp.color,labels:sp.labels,label:m.n});
  });
  var legEl=document.getElementById('vd3-leg');
  if(legEl)legEl.innerHTML=datasets.map(function(ds){
    return '<div class="v2d-leg-item"><div class="v2d-leg-line" style="background:'+ds.color+'"></div><span>'+ds.label+'</span></div>';
  }).join('');
  setTimeout(function(){d.buildChart('vd3-chart',datasets,{height:270,endLabels:true})},60);
  window.addEventListener('resize',function(){setTimeout(function(){d.buildChart('vd3-chart',datasets,{height:270,endLabels:true})},120)});
  /* mini KPI strip below chart */
  var kpiEl=document.getElementById('vd3-kpi-strip');
  if(kpiEl){
    var regC=kpis.regime==='SEGURO'?'#44e890':'#f5b833';
    var items=[
      {l:'Champion',v:kpis.champModel,c:'#f5b833'},
      {l:'Ret. champ.',v:kpis.champRet,c:'#f5b833'},
      {l:'Motor V13',v:kpis.motorRet,c:'#00ffe0'},
      {l:'Picks hoy',v:kpis.picksHoy,c:'#a882ff'},
      {l:'Calidad',v:kpis.sysScore,c:kpis.sysColor},
      {l:'Régimen',v:kpis.regime,c:regC},
    ];
    kpiEl.innerHTML=items.map(function(it){
      return '<div style="flex:1;min-width:90px">'
        +'<div style="font-size:7.5px;text-transform:uppercase;letter-spacing:.14em;color:rgba(120,170,220,.45);margin-bottom:3px">'+it.l+'</div>'
        +'<div style="font-size:14px;font-weight:800;color:'+it.c+'">'+it.v+'</div>'
        +'</div>';
    }).join('');
  }
  /* ranking full table in scroll */
  d.renderRanking('vd3-ranking',10,false);
  /* signals */
  var total=d.renderSignals('vd3-signals',false);
  var sn=document.getElementById('vd3-sig-n');
  if(sn)sn.textContent=total+' abiertas';
})();
</script>"""

# ════════════════════════════════════════════════════════════════════════
# GENERATOR
# ════════════════════════════════════════════════════════════════════════
def make(label, extra_css, body_html, body_js):
    h = BASE
    h = h.replace('<body>', '<body class="v2d">', 1)
    h = h.replace(HEAD_END, SHARED_CSS + '\n' + extra_css + '\n' + HEAD_END, 1)
    h = h.replace(ANCHOR, body_html + '\n' + ANCHOR, 1)
    h = h.replace(BODY_END, SHARED_JS + '\n' + body_js + '\n' + BODY_END, 1)
    h = h.replace('<title>Pythiax', '<title>[' + label + '] Pythiax', 1)
    return h

VARIANTS = [
    ('d1_triforce',    'D1 · Triforce',     D1_CSS, D1_HTML, D1_JS),
    ('d2_chartking',   'D2 · Chart King',   D2_CSS, D2_HTML, D2_JS),
    ('d3_station',     'D3 · Side Station', D3_CSS, D3_HTML, D3_JS),
]

for vid, vlabel, vcss, vhtml, vjs in VARIANTS:
    out_html = make(vlabel, vcss, vhtml, vjs)
    dst = os.path.join(ROOT, 'analisis', '_staging_v2' + vid + '.html')
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(out_html)
    sz = os.path.getsize(dst)
    print(f'[{vlabel:22s}] → _staging_v2{vid}.html ({sz:,} bytes)')
    print(f'  URL: http://localhost:8765/_staging_v2{vid}.html')
    print()
