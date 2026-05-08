"""
generar_v2e_previews.py
Basado en V2D2 (2.6fr/1fr/1fr). Mejoras:
  - Gráfico Performance con botones de temporalidad (4 períodos)
  - Ejes claros: fechas en X, porcentajes en Y con línea 0
  - Normalización por período (retorno desde inicio del período = 0%)
  - Ranking SIN columna bar, CON Sharpe, MDD, best/worst, 30d
  - Señales intactas
3 variantes: E1 Cyan Pro | E2 Violet Dense | E3 Gold Executive
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
SHARED_CSS = r"""<style id="v2e-shared">
/* ── ocultar legacy ── */
body.v2e .kpi-strip, body.v2e .hero-card,
body.v2e [data-bid="liga-panel"],
body.v2e [data-bid="scanners-panel"],
body.v2e [data-bid="legacy-panel"],
body.v2e .ft-footer { display:none!important }
/* ── exponer heatmap + overlap ── */
body.v2e [data-bid="heatmap-panel"],
body.v2e [data-bid="overlap-panel"] {
  display:block!important; margin:0 0 14px; border-radius:12px }
/* ── panel base ── */
.v2e-wrap { display:flex; flex-direction:column; gap:14px; padding:0 0 24px }
.v2e-panel {
  background:linear-gradient(180deg,rgba(7,12,26,.99) 0%,rgba(4,7,16,.99) 100%);
  border:1px solid rgba(120,165,215,.14); border-radius:12px;
  padding:15px 17px; box-shadow:0 28px 80px rgba(0,0,0,.72);
  overflow:hidden; position:relative;
}
.v2e-ph {
  font-size:8.5px; font-weight:800; text-transform:uppercase; letter-spacing:.18em;
  color:rgba(120,165,215,.48); margin-bottom:11px; padding-bottom:9px;
  border-bottom:1px solid rgba(120,165,215,.09);
  display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap;
}
.v2e-badge {
  font-size:8.5px; font-weight:800; padding:2px 9px; border-radius:5px; white-space:nowrap
}
.v2e-ba-c { background:rgba(24,232,200,.12); color:#18e8c8; border:1px solid rgba(24,232,200,.25) }
.v2e-ba-g { background:rgba(68,232,144,.12); color:#44e890; border:1px solid rgba(68,232,144,.25) }
.v2e-ba-y { background:rgba(245,184,51,.12);  color:#f5b833; border:1px solid rgba(245,184,51,.25) }
.v2e-ba-m { background:rgba(168,130,255,.12); color:#a882ff; border:1px solid rgba(168,130,255,.25) }
/* ── period buttons container ── */
.v2e-periods { display:flex; align-items:center; gap:5px; flex-wrap:wrap }
.v2e-period-lbl {
  font-size:8px; font-weight:800; text-transform:uppercase; letter-spacing:.14em;
  color:rgba(120,165,215,.4); margin-right:2px
}
/* ── legend ── */
.v2e-legend { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:8px }
.v2e-leg-item { display:flex; align-items:center; gap:5px; font-size:10px; color:rgba(120,165,215,.65) }
.v2e-leg-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0 }
/* ── period stat strip ── */
.v2e-pstat {
  margin-top:8px; padding-top:8px; border-top:1px solid rgba(120,165,215,.08);
  font-size:10px; color:rgba(120,165,215,.6);
  display:flex; gap:14px; flex-wrap:wrap; align-items:center;
}
/* ── signals scroll ── */
.v2e-sig-scroll {
  max-height:360px; overflow-y:auto; scrollbar-width:thin;
  scrollbar-color:rgba(24,232,200,.14) transparent
}
.v2e-sig-scroll::-webkit-scrollbar { width:3px }
.v2e-sig-scroll::-webkit-scrollbar-thumb { background:rgba(24,232,200,.14); border-radius:2px }
.v2e-sig-model {
  padding:9px 10px; border-radius:8px;
  border:1px solid rgba(120,165,215,.09); background:rgba(255,255,255,.024);
  margin-bottom:6px
}
.v2e-sig-model:last-child { margin-bottom:0 }
.v2e-sig-mhead { display:flex; align-items:center; gap:7px; margin-bottom:6px }
.v2e-sig-mname { font-weight:800; font-size:12px; color:#eef4fb }
.v2e-sig-mtm { font-size:11px; font-weight:700; margin-left:auto }
.v2e-pick-row {
  display:flex; align-items:center; gap:8px; padding:4px 6px;
  border-radius:6px; background:rgba(255,255,255,.03); font-size:11px; margin-bottom:2px
}
.v2e-pick-row:last-child { margin-bottom:0 }
.v2e-pick-tk { font-weight:800; font-size:12px; min-width:44px }
.v2e-pick-pct { font-weight:700; min-width:50px }
.v2e-pick-tgt { color:rgba(120,165,215,.52); font-size:9.5px; margin-left:auto }
.v2e-pick-days { font-size:9px; text-align:right; min-width:26px }
/* ── ranking 2-row layout ── */
.v2e-rk-item {
  padding:5.5px 0; border-top:1px solid rgba(255,255,255,.05);
}
.v2e-rk-item:first-child { border-top:none }
.v2e-rk-row1 { display:flex; align-items:center; gap:6px; margin-bottom:3px }
.v2e-rk-row2 { display:flex; gap:8px; flex-wrap:wrap; padding-left:20px }
.v2e-rk-medal { font-size:9.5px; min-width:16px; flex-shrink:0 }
.v2e-dot { display:inline-block; width:7px; height:7px; border-radius:2px; flex-shrink:0 }
.v2e-rk-name { font-weight:800; font-size:11.5px; color:#eef4fb; flex:1 }
.v2e-rk-wr { font-size:12px; font-weight:700; min-width:44px; text-align:right }
.v2e-rk-ret { font-size:10.5px; min-width:42px; text-align:right; color:rgba(180,210,255,.65) }
.v2e-rk-stat { font-size:9.5px; color:rgba(120,165,215,.55); white-space:nowrap }
.v2e-rk-stat b { color:rgba(180,210,255,.8) }
/* ── Bloomberg Pro WR bar ── */
.v2rk-wrb { position:relative; overflow:hidden; text-align:right; padding:3px 2px; border-radius:3px; }
.v2rk-wr-bar { position:absolute; top:0; left:0; height:100%; opacity:.16; border-radius:3px; }
/* ── heatmap + overlap harmony ── */
body.v2e [data-bid="heatmap-panel"],
body.v2e [data-bid="overlap-panel"] {
  background:linear-gradient(180deg,rgba(7,12,26,.99) 0%,rgba(4,7,16,.99) 100%) !important;
  border:1px solid rgba(120,165,215,.14) !important;
  border-radius:12px !important;
  padding:0 !important;
  overflow:hidden !important;
  box-shadow:0 28px 80px rgba(0,0,0,.72) !important;
}
body.v2e [data-bid="heatmap-panel"] .panel-head,
body.v2e [data-bid="overlap-panel"] .panel-head {
  background:transparent !important;
  padding:13px 17px 11px !important;
  border-bottom:1px solid rgba(120,165,215,.09) !important;
  margin:0 !important;
}
body.v2e [data-bid="heatmap-panel"] .panel-label,
body.v2e [data-bid="overlap-panel"] .panel-label {
  font-size:8.5px !important; text-transform:uppercase !important;
  letter-spacing:.18em !important; font-weight:800 !important;
  color:rgba(120,165,215,.45) !important;
}
body.v2e [data-bid="heatmap-panel"] .panel-title,
body.v2e [data-bid="overlap-panel"] .panel-title {
  color:rgba(220,235,255,.82) !important; font-size:13px !important;
  margin:0 !important;
}
body.v2e .hm-tabbar {
  background:transparent !important;
  border-bottom:1px solid rgba(120,165,215,.08) !important;
  padding:8px 17px !important;
}
body.v2e [data-bid="heatmap-panel"] > *:not(.panel-head),
body.v2e [data-bid="overlap-panel"] > *:not(.panel-head) {
  padding-left:14px; padding-right:14px;
}
</style>"""

# ════════════════════════════════════════════════════════════════════════
# SHARED JS — buildChartPro + period registry + data helpers + ranking
# ════════════════════════════════════════════════════════════════════════
SHARED_JS = r"""<script id="v2e-shared-js">
(function(){
/* ── Period registry ── */
var _REG = {};
window._v2e_reg = function(id, datasets, opts) {
  _REG[id] = {ds:datasets, opts:opts, period:0};
  setTimeout(function(){ window._v2e_sp(id, 0); }, 80);
};
window._v2e_sp = function(id, p) {
  if(!_REG[id]) return;
  _REG[id].period = p;
  document.querySelectorAll('[data-cpid="'+id+'"]').forEach(function(b){
    b.classList.toggle('v2e-period-active', parseInt(b.dataset.cp)===p);
  });
  buildChartPro(id, _REG[id].ds, p, _REG[id].opts);
};
/* ── buildChartPro ── */
function buildChartPro(id, fullDs, period, opts) {
  var el = document.getElementById(id);
  if(!el || !fullDs || !fullDs.length) return;
  opts = opts||{};
  /* slice + normalize so first point of period = 0% */
  var datasets = fullDs.map(function(ds){
    var v = (period>0 ? ds.vals.slice(-period) : ds.vals).slice();
    var l = (period>0 ? (ds.labels||[]).slice(-period) : (ds.labels||[])).slice();
    if(v.length){ var b=v[0]; v=v.map(function(x){return x-b;}); }
    return {vals:v, labels:l, color:ds.color, label:ds.label, isChamp:!!ds.isChamp};
  });
  el.style.position='relative'; el.innerHTML='';
  var H = opts.height||240;
  var W = Math.max(200, el.getBoundingClientRect().width||el.offsetWidth||700);
  var _rp=opts.endLabels!==false?(opts.labelStyle==='pill'?118:opts.labelStyle==='nameVal'?90:78):14;
  var PAD = {t:14, r:_rp, b:32, l:48};
  var CW=W-PAD.l-PAD.r, CH=H-PAD.t-PAD.b;
  var allV=[];
  datasets.forEach(function(d){allV=allV.concat(d.vals);});
  if(!allV.length)return;
  var mn=Math.min.apply(null,allV), mx=Math.max.apply(null,allV);
  var rng=mx-mn||1; mn-=rng*.07; mx+=rng*.07; rng=mx-mn;
  var xp=function(i,n){return PAD.l+(n>1?i/(n-1):0.5)*CW;};
  var yp=function(v){return PAD.t+CH*(1-(v-mn)/rng);};
  var s=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+W+' '+H
    +'" preserveAspectRatio="none" style="width:100%;display:block;overflow:visible">'];
  /* defs */
  s.push('<defs>');
  datasets.forEach(function(d,i){
    var std=d.isChamp?4.5:2.5;
    s.push('<filter id="vef'+id+i+'" x="-140%" y="-140%" width="380%" height="380%">');
    s.push('<feGaussianBlur in="SourceGraphic" stdDeviation="'+std+'" result="b"/>');
    s.push('<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>');
  });
  s.push('</defs>');
  /* Y gridlines — nice numbers targeting ~6 gridlines */
  var _rs=rng/6, _mag=Math.pow(10,Math.floor(Math.log10(_rs||1)));
  var _nr=_rs/_mag;
  var yStep=(_nr<=1.5?1:_nr<=3.5?2:_nr<=7.5?5:10)*_mag;
  if(yStep<1) yStep=1;
  var yStart = Math.ceil(mn/yStep)*yStep;
  for(var yv=yStart; yv<=mx+0.001; yv+=yStep){
    var gy=yp(yv).toFixed(1);
    var isZ=Math.abs(yv)<yStep*0.12;
    s.push('<line x1="'+PAD.l+'" y1="'+gy+'" x2="'+(PAD.l+CW)+'" y2="'+gy
      +'" stroke="rgba(120,165,215,'+(isZ?.32:.075)+')" stroke-width="'+(isZ?1.4:.55)+'"'
      +(isZ?' stroke-dasharray="5,3"':'')+' />');
    s.push('<text x="'+(PAD.l-5)+'" y="'+(parseFloat(gy)+3.5).toFixed(1)+'"'
      +' text-anchor="end" fill="rgba(140,190,240,'+(isZ?.72:.50)+')" font-size="9"'
      +' font-weight="'+(isZ?700:400)+'">'+(yv>0?'+':'')+yv.toFixed(0)+'%</text>');
  }
  /* X axis line */
  s.push('<line x1="'+PAD.l+'" y1="'+(PAD.t+CH)+'" x2="'+(PAD.l+CW)+'" y2="'+(PAD.t+CH)
    +'" stroke="rgba(120,165,215,.18)" stroke-width=".8"/>');
  /* X date ticks from first dataset labels */
  var dLabels=[];
  datasets.forEach(function(d){if(d.labels&&d.labels.length&&!dLabels.length)dLabels=d.labels;});
  if(dLabels.length>1){
    var nL=dLabels.length, NT=Math.min(7, nL);
    for(var ti=0;ti<NT;ti++){
      var idx=Math.round(ti*(nL-1)/(NT-1));
      if(!dLabels[idx])continue;
      var ds=dLabels[idx].replace('2026-','').replace(/-/g,'/');
      var tx=xp(idx,nL).toFixed(1);
      s.push('<line x1="'+tx+'" y1="'+(PAD.t+CH)+'" x2="'+tx+'" y2="'+(PAD.t+CH+4)+'"'
        +' stroke="rgba(120,165,215,.22)" stroke-width=".7"/>');
      s.push('<text x="'+tx+'" y="'+(H-3)+'"'
        +' text-anchor="middle" fill="rgba(155,195,245,.55)" font-size="8.5">'+ds+'</text>');
    }
  }
  /* series */
  var _lps=[];
  datasets.forEach(function(ds,di){
    if(!ds.vals||ds.vals.length<2)return;
    var n=ds.vals.length, c=ds.color||'#00ffe0';
    var sw=ds.isChamp?3.2:2;
    var pts=ds.vals.map(function(v,i){return xp(i,n).toFixed(1)+','+yp(v).toFixed(1);}).join(' ');
    var zy2=yp(Math.max(mn,0)).toFixed(1);
    var x0=xp(0,n).toFixed(1), xN=xp(n-1,n).toFixed(1);
    /* area fill */
    s.push('<polygon points="'+x0+','+zy2+' '+pts+' '+xN+','+zy2+'"'
      +' fill="'+c+'" opacity="'+(ds.isChamp?.13:.065)+'"/>');
    /* glow pass */
    s.push('<polyline points="'+pts+'" fill="none" stroke="'+c+'" stroke-width="'+(sw+1.5)+'"'
      +' opacity=".26" stroke-linecap="round" stroke-linejoin="round" filter="url(#vef'+id+di+')"/>');
    /* sharp pass */
    s.push('<polyline points="'+pts+'" fill="none" stroke="'+c+'" stroke-width="'+sw+'"'
      +' stroke-linecap="round" stroke-linejoin="round"/>');
    /* end dot */
    var lv=ds.vals[n-1], ex=xp(n-1,n).toFixed(1), ey=yp(lv).toFixed(1);
    s.push('<circle cx="'+ex+'" cy="'+ey+'" r="5.5" fill="'+c+'" opacity=".2" filter="url(#vef'+id+di+')"/>');
    s.push('<circle cx="'+ex+'" cy="'+ey+'" r="3" fill="'+c+'"/>');
    if(opts.endLabels!==false){
      _lps.push({lx:parseFloat(ex)+8,ly:parseFloat(ey),lv:lv,c:c,lbl:ds.label,champ:ds.isChamp,dot_y:parseFloat(ey)});
    }
  });
  /* end labels — anti-overlap */
  if(opts.endLabels!==false && _lps.length){
    var lStyle=opts.labelStyle||'val';
    var _mg=(lStyle==='nameVal')?24:(lStyle==='pill')?20:18;
    _lps.sort(function(a,b){return a.ly-b.ly;});
    for(var _pi=1;_pi<_lps.length;_pi++){
      if(_lps[_pi].ly-_lps[_pi-1].ly<_mg) _lps[_pi].ly=_lps[_pi-1].ly+_mg;
    }
    var _maxY=PAD.t+CH+2;
    for(var _pi=_lps.length-1;_pi>=0;_pi--){
      if(_lps[_pi].ly>_maxY){ _lps[_pi].ly=_maxY; _maxY-=_mg; }
    }
    _lps.forEach(function(lp){
      var lx=lp.lx,ly=lp.ly,c=lp.c,lv=lp.lv;
      if(Math.abs(ly-lp.dot_y)>5)
        s.push('<line x1="'+(lx-5)+'" y1="'+lp.dot_y.toFixed(1)+'" x2="'+(lx-5)+'" y2="'+ly.toFixed(1)+'" stroke="'+c+'" stroke-width=".7" opacity=".35"/>');
      if(lStyle==='nameVal'){
        s.push('<text x="'+lx+'" y="'+(ly-4).toFixed(1)+'" fill="'+c+'" font-size="8" font-weight="900" letter-spacing=".06em">'+lp.lbl+'</text>');
        s.push('<text x="'+lx+'" y="'+(ly+8).toFixed(1)+'" fill="'+c+'" font-size="9" font-weight="700" opacity=".8">'+(lv>=0?'+':'')+lv.toFixed(1)+'%</text>');
      } else if(lStyle==='pill'){
        var lbl=lp.lbl+'  '+(lv>=0?'+':'')+lv.toFixed(1)+'%';
        var bw=lbl.length*5.5+14;
        s.push('<rect x="'+lx+'" y="'+(ly-8)+'" width="'+bw.toFixed(0)+'" height="16" rx="8" fill="'+c+'" opacity=".18"/>');
        s.push('<text x="'+(lx+7)+'" y="'+(ly+3.5)+'" fill="'+c+'" font-size="9.5" font-weight="800">'+lbl+'</text>');
      } else if(lStyle==='name'){
        s.push('<text x="'+lx+'" y="'+(ly+3.5)+'" fill="'+c+'" font-size="'+(lp.champ?11.5:10.5)+'" font-weight="900" letter-spacing=".03em">'+lp.lbl+'</text>');
      } else {
        s.push('<text x="'+lx+'" y="'+(ly+3.5).toFixed(1)+'" fill="'+c+'" font-size="'+(lp.champ?12:10.5)+'" font-weight="800">'+(lv>=0?'+':'')+lv.toFixed(1)+'%</text>');
      }
    });
  }
  /* crosshair */
  s.push('<line id="vexcr_'+id+'" x1="'+PAD.l+'" y1="'+PAD.t+'" x2="'+PAD.l+'" y2="'+(PAD.t+CH)+'"'
    +' stroke="rgba(255,255,255,.22)" stroke-width="1" stroke-dasharray="4,3" style="display:none"/>');
  s.push('<rect id="vexov_'+id+'" x="'+PAD.l+'" y="'+PAD.t+'" width="'+CW+'" height="'+CH+'"'
    +' fill="transparent" style="cursor:crosshair"/>');
  s.push('</svg>');
  el.innerHTML=s.join('');
  /* tooltip */
  var tip=document.createElement('div');
  tip.style.cssText='position:absolute;background:rgba(2,5,18,.97);'
    +'border:1px solid rgba(24,232,200,.16);border-radius:9px;padding:9px 13px;'
    +'font-size:10px;line-height:1.8;pointer-events:none;display:none;z-index:70;'
    +'white-space:nowrap;box-shadow:0 12px 48px rgba(0,0,0,.75)';
  el.appendChild(tip);
  var svg=el.querySelector('svg');
  var cr=document.getElementById('vexcr_'+id);
  var ov=document.getElementById('vexov_'+id);
  var W_=W, CW_=CW, PAD_=PAD;
  ov.addEventListener('mousemove',function(e){
    var rect=svg.getBoundingClientRect(), scX=W_/rect.width;
    var mx2=(e.clientX-rect.left)*scX-PAD_.l;
    var fr=Math.max(0,Math.min(1,mx2/CW_));
    var cx=(PAD_.l+fr*CW_).toFixed(1);
    cr.setAttribute('x1',cx);cr.setAttribute('x2',cx);cr.style.display='block';
    var lines=[], dateStr='';
    datasets.forEach(function(ds){
      var idx=Math.round(fr*(ds.vals.length-1));
      var v=ds.vals[idx];
      if(!dateStr&&ds.labels&&ds.labels[idx])
        dateStr=ds.labels[idx].replace('2026-','').replace(/-/g,'/');
      lines.push('<div style="display:flex;justify-content:space-between;gap:18px">'
        +'<span style="color:'+ds.color+'">● '+(ds.label||'?')+'</span>'
        +'<b style="color:#eef4fb">'+(v>=0?'+':'')+v.toFixed(2)+'%</b></div>');
    });
    if(dateStr)lines.unshift(
      '<div style="color:rgba(255,255,255,.35);font-size:8.5px;margin-bottom:4px">📅 '+dateStr+'</div>');
    tip.innerHTML=lines.join('');tip.style.display='block';
    var tipW=tip.offsetWidth||160;
    var pxL=parseFloat(cx)/W_*rect.width;
    tip.style.left=Math.max(0,Math.min(rect.width-tipW,pxL+(fr<.6?10:-tipW-10)))+'px';
    tip.style.top='4px';
  });
  ov.addEventListener('mouseleave',function(){cr.style.display='none';tip.style.display='none';});
  /* update period stat */
  var statEl=document.getElementById('vest_'+id);
  if(statEl&&datasets.length){
    var best=null, bestV=-1e9;
    datasets.forEach(function(ds){
      if(!ds.vals.length)return;
      var v=ds.vals[ds.vals.length-1];
      if(v>bestV){bestV=v;best=ds;}
    });
    if(best){
      var nLabel=period>0?period+'R':'Todo';
      statEl.innerHTML='🏆 <span style="color:'+best.color+'">'+best.label+'</span>'
        +' lidera en <b>'+nLabel+'</b>: '
        +'<span style="color:'+(bestV>=0?'var(--green)':'var(--rose)')+'">'
        +(bestV>=0?'+':'')+bestV.toFixed(1)+'%</span>';
    }
  }
}
window._v2e_build=buildChartPro;

/* ── Data helpers ── */
var q=function(s,c){return(c||document).querySelector(s);};
var qa=function(s,c){return Array.from((c||document).querySelectorAll(s));};
var MC={V11:'#6ea8cc',V13:'#00ffe0',ML_V97:'#b070ff',ML_V39:'#06d6a0',
        ML_V39FULL:'#818cf8',ML_V94:'#f59e0b',ML_BRAIN_V11:'#f472b6',
        ML_BRAIN_V11_OPT:'#fb923c',ML_V37:'#94a3b8',ML_BRAIN_V10:'#64748b'};
var mc=function(n){return MC[n]||'#8080a0';};
function daysTo(tgt){
  if(!tgt||!tgt.includes('/'))return null;
  var p=tgt.split('/');if(p.length<2)return null;
  var t=new Date(2026,parseInt(p[1])-1,parseInt(p[0]));
  return Math.round((t-new Date(2026,4,8))/86400000);
}
function getSpark(name){
  var rows=qa('.leag-row-clickable');
  for(var i=0;i<rows.length;i++){
    var n=(q('td:nth-child(2) strong',rows[i])||{}).textContent||'';
    if(n.trim()===name){
      var v=[],c=mc(name),l=[];
      try{v=JSON.parse(rows[i].dataset.sparkVals||'[]');}catch(e){}
      try{c=rows[i].dataset.sparkColor||mc(name);}catch(e){}
      try{l=JSON.parse(rows[i].dataset.sparkLabels||'[]');}catch(e){}
      return{vals:v,color:c,labels:l};
    }
  }return null;
}
function getLeagueEnhanced(n){
  return qa('.leag-row-clickable').slice(0,n||10).map(function(row){
    var ds=row.dataset;
    var name=(q('td:nth-child(2) strong',row)||{}).textContent||'?';
    var wrEl=q('td:nth-child(4) strong',row);
    var wr=wrEl?wrEl.textContent.trim():'—';
    var wrCls=wrEl?(wrEl.classList.contains('pos')?'pos':'neg'):'';
    var wrNum=parseFloat(wr)||0;
    var ret=(q('td:nth-child(4) small',row)||{}).textContent||'—';
    var le=q('.ult-rueda-td strong',row);
    var last=le?le.textContent.trim():'—';
    var lastCls=le?(le.classList.contains('pos')?'pos':'neg'):'';
    var wnd30el=qa('.wnd-td',row)[0];
    var w30wr=(q('.wnd-wr',wnd30el)||{}).textContent||'—';
    var w30ret=(q('.wnd-ret',wnd30el)||{}).textContent||'—';
    var w30cls=(q('.wnd-pos',wnd30el)?'pos':(q('.wnd-neg',wnd30el)?'neg':''));
    var sv=[],sc=mc(name.trim()),sl=[];
    try{sv=JSON.parse(ds.sparkVals||'[]');}catch(e){}
    try{sc=ds.sparkColor||mc(name.trim());}catch(e){}
    try{sl=JSON.parse(ds.sparkLabels||'[]');}catch(e){}
    return{
      model:name.trim(), color:sc,
      wr:wr, wrCls:wrCls, wrNum:wrNum, ret:ret,
      last:last, lastCls:lastCls,
      w30wr:w30wr, w30ret:w30ret, w30cls:w30cls,
      sharpe:ds.sharpe||'—', mdd:ds.mdd||'—',
      best:ds.best||'—', worst:ds.worst||'—',
      sparkVals:sv, sparkColor:sc, sparkLabels:sl
    };
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
    if(el){qa('tr',el).forEach(function(tr){
      var tds=tr.querySelectorAll('td');if(tds.length<4)return;
      var tgt=tds[3].textContent.trim().replace('→','').trim();
      picks.push({ticker:tds[0].textContent.trim(),price:tds[1].textContent.trim(),
        pct:tds[2].textContent.trim(),pctCls:tds[2].classList.contains('pos')?'pos':'neg',
        target:tgt,days:daysTo(tgt)});
    });}
    models.push({model:model,color:color,mtm:mtm,mtmCls:mtmCls,openN:openN,picks:picks});
  });
  return models;
}
function getKPIs(){
  var ch=q('[data-bid="kpi-leader"]'),pk=q('[data-bid="kpi-picks"]'),sy=q('[data-bid="kpi-sistema"]');
  var regime='SEGURO';
  var rp=q('.regime-pill');
  if(rp)qa('span',rp).forEach(function(sp){
    if(!sp.classList.contains('rp-dot')&&!sp.classList.contains('rp-breadth'))
      regime=sp.textContent.trim();
  });
  return{
    regime:regime,
    champ:(q('.kc-value',ch)||{}).textContent||'—',
    picks:parseInt((q('.kc-value',pk)||{}).textContent||'0'),
    sysScore:(q('.kc-value',sy)||{}).textContent||'—',
    sysColor:(q('.kc-value',sy)||{style:{}}).style.color||'var(--green)',
  };
}
function msp(vals,color,w,h){
  if(!vals||vals.length<2)return '';
  var mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals),rng=mx-mn||1;
  var pts=vals.map(function(v,i){
    return(2+i/(vals.length-1)*(w-4)).toFixed(1)+','+(h-2-(v-mn)/rng*(h-4)).toFixed(1);
  }).join(' ');
  var lv=vals[vals.length-1],ey=(h-2-(lv-mn)/rng*(h-4)).toFixed(1);
  return '<svg viewBox="0 0 '+w+' '+h+'" width="'+w+'" height="'+h
    +'" style="display:block;overflow:visible;flex-shrink:0">'
    +'<polyline points="'+pts+'" fill="none" stroke="'+color+'" stroke-width="2"'
    +' stroke-linecap="round" stroke-linejoin="round"'
    +' filter="drop-shadow(0 0 2.5px '+color+')"/>'
    +'<circle cx="'+(w-2)+'" cy="'+ey+'" r="2.5" fill="'+color+'"/>'
    +'</svg>';
}
function mspArea(vals,color,w,h){
  if(!vals||vals.length<2)return '';
  var mn=Math.min.apply(null,vals),mx=Math.max.apply(null,vals),rng=mx-mn||1;
  var pts=vals.map(function(v,i){
    return(2+i/(vals.length-1)*(w-4)).toFixed(1)+','+(h-2-(v-mn)/rng*(h-4)).toFixed(1);
  }).join(' ');
  var lv=vals[vals.length-1],ey=(h-2-(lv-mn)/rng*(h-4)).toFixed(1);
  var uid='ga'+Math.abs(color.charCodeAt(1)||0)+vals.length+(mn*7|0);
  var pg='2,'+(h-2)+' '+pts+' '+(w-2)+','+(h-2);
  return '<svg viewBox="0 0 '+w+' '+h+'" width="'+w+'" height="'+h
    +'" style="display:block;overflow:visible;flex-shrink:0">'
    +'<defs><linearGradient id="'+uid+'" x1="0" y1="0" x2="0" y2="1">'
    +'<stop offset="0%" stop-color="'+color+'" stop-opacity="0.35"/>'
    +'<stop offset="100%" stop-color="'+color+'" stop-opacity="0.02"/>'
    +'</linearGradient></defs>'
    +'<polygon points="'+pg+'" fill="url(#'+uid+')"/>'
    +'<polyline points="'+pts+'" fill="none" stroke="'+color+'" stroke-width="1.8"'
    +' stroke-linecap="round" stroke-linejoin="round"/>'
    +'<circle cx="'+(w-2)+'" cy="'+ey+'" r="2.5" fill="'+color+'"/>'
    +'</svg>';
}
function renderSignals(id){
  var el=document.getElementById(id);if(!el)return 0;
  var sigs=getSignals(),total=0;
  if(!sigs.length){
    el.innerHTML='<div style="text-align:center;color:rgba(120,165,215,.4);padding:22px 0">Sin señales activas</div>';
    return 0;
  }
  el.innerHTML=sigs.map(function(m){
    total+=m.picks.length;
    var rows=m.picks.map(function(p){
      var dStr=p.days!=null?p.days+'d':'—';
      var dC=p.days!=null&&p.days<=2?'color:var(--rose)':'color:rgba(120,165,215,.45)';
      return '<div class="v2e-pick-row">'
        +'<span class="v2e-pick-tk">'+p.ticker+'</span>'
        +'<span class="v2e-pick-pct '+p.pctCls+'">'+p.pct+'</span>'
        +'<span style="font-size:10px;color:rgba(120,165,215,.45)">'+p.price+'</span>'
        +'<span class="v2e-pick-tgt">→'+p.target+'</span>'
        +'<span class="v2e-pick-days" style="'+dC+'">'+dStr+'</span>'
        +'</div>';
    }).join('');
    return '<div class="v2e-sig-model">'
      +'<div class="v2e-sig-mhead">'
      +'<span class="v2e-dot" style="background:'+m.color+'"></span>'
      +'<span class="v2e-sig-mname">'+m.model+'</span>'
      +'<span class="v2e-badge v2e-ba-c" style="font-size:8px">'+m.openN+'p</span>'
      +(m.mtm?'<span class="v2e-sig-mtm '+m.mtmCls+'">'+m.mtm+'</span>':'')
      +'</div><div>'+rows+'</div></div>';
  }).join('');
  return total;
}
/* ── renderRanking 2-row style (sin bar) ── */
function renderRanking(id, n, style){
  var el=document.getElementById(id);if(!el)return;
  var league=getLeagueEnhanced(n||10);
  var medals=['🥇','🥈','🥉'];
  el.innerHTML=league.map(function(m,i){
    var clr=m.color;
    var spk=msp(m.sparkVals.slice(-14),m.sparkColor,60,20);
    var sharpeStr=m.sharpe!=='—'?parseFloat(m.sharpe).toFixed(2):'—';
    var mddStr=m.mdd!=='—'?m.mdd:'—';
    var bestStr=m.best!=='—'?m.best:'—';
    var sharpeColor=m.sharpe!=='—'?(parseFloat(m.sharpe)>=1.5?'var(--green)':parseFloat(m.sharpe)>=0?'var(--gold)':'var(--rose)'):'rgba(120,165,215,.45)';
    /* row2 content varies by style */
    var row2parts=[];
    if(style==='full'){
      row2parts=['30d: <b class="'+m.w30cls+'">'+m.w30ret+'</b>',
        'Sh: <b style="color:'+sharpeColor+'">'+sharpeStr+'</b>',
        'MDD: <b style="color:var(--rose)">'+mddStr+'</b>',
        'Best: <b class="pos">'+bestStr+'</b>'];
    } else if(style==='risk'){
      row2parts=['30d WR: <b class="'+m.w30cls+'">'+m.w30wr+'</b>',
        'Sh: <b style="color:'+sharpeColor+'">'+sharpeStr+'</b>',
        'MDD: <b style="color:var(--rose)">'+mddStr+'</b>',
        'Worst: <b class="neg">'+m.worst+'</b>'];
    } else {
      /* default */
      row2parts=['Ret: <b style="color:rgba(180,210,255,.8)">'+m.ret+'</b>',
        '30d: <b class="'+m.w30cls+'">'+m.w30ret+'</b>',
        'Sh: <b style="color:'+sharpeColor+'">'+sharpeStr+'</b>',
        'Últ: <b class="'+m.lastCls+'">'+m.last+'</b>'];
    }
    return '<div class="v2e-rk-item">'
      +'<div class="v2e-rk-row1">'
      +'<span class="v2e-rk-medal">'+(medals[i]||'#'+(i+1))+'</span>'
      +'<span class="v2e-dot" style="background:'+clr+'"></span>'
      +'<span class="v2e-rk-name">'+m.model+'</span>'
      +'<span class="v2e-rk-wr '+m.wrCls+'">'+m.wr+'</span>'
      +(style==='risk'?'<span class="v2e-rk-ret '+m.lastCls+'">'+m.last+'</span>':'')
      +spk
      +'</div>'
      +'<div class="v2e-rk-row2">'
      +row2parts.map(function(r){return '<span class="v2e-rk-stat">'+r+'</span>';}).join('')
      +'</div></div>';
  }).join('');
}
/* ── renderRankingCols — Bloomberg Pro (WR bar + area spark, sin Sharpe/MDD) ── */
function renderRankingCols(id, n){
  var el=document.getElementById(id); if(!el)return;
  var league=getLeagueEnhanced(n||10);
  var medals=['🥇','🥈','🥉'];
  var HL0='font-size:7px;font-weight:800;text-transform:uppercase;letter-spacing:.14em;color:rgba(120,165,215,.42)';
  var cols='18px minmax(62px,1fr) 50px 42px 36px 38px 76px';
  var hdr='<div style="display:grid;grid-template-columns:'+cols+';gap:0 5px;padding:2px 7px 7px;border-bottom:1px solid rgba(168,130,255,.22);margin-bottom:4px">'
    +'<span></span>'
    +'<span style="'+HL0+'">Modelo</span>'
    +'<span style="'+HL0+';text-align:right">WR</span>'
    +'<span style="'+HL0+';text-align:right">Ret</span>'
    +'<span style="'+HL0+';text-align:right">30d</span>'
    +'<span style="'+HL0+';text-align:right">Últ</span>'
    +'<span style="'+HL0+';text-align:center">Curva</span>'
    +'</div>';
  el.innerHTML=hdr+league.map(function(m,i){
    var wrNum=m.wrNum;
    var wrC=wrNum>=65?'#44e890':wrNum>=55?'#f5b833':'#fc5c7d';
    var bg=i%2===0?'rgba(255,255,255,.022)':'transparent';
    var spkC=i<3?'#44e890':i<7?'#f5b833':'#fc5c7d';
    var spk=mspArea(m.sparkVals,spkC,72,26);
    return '<div style="background:'+bg+';border-radius:5px;margin-bottom:1px">'  
      +'<div style="display:grid;grid-template-columns:'+cols+';gap:0 5px;align-items:center;padding:5px 7px">'
        +'<span style="font-size:8.5px;text-align:center;line-height:1">'+(medals[i]||'#'+(i+1))+'</span>'
        +'<div style="display:flex;align-items:center;gap:5px;min-width:0;overflow:hidden">'
          +'<span class="v2e-dot" style="background:'+m.color+';flex-shrink:0"></span>'
          +'<span style="font-weight:800;font-size:10px;color:#dce8f8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+m.model+'</span>'
        +'</div>'
        +'<div class="v2rk-wrb">'
          +'<div class="v2rk-wr-bar" style="width:'+wrNum.toFixed(0)+'%;background:'+wrC+'"></div>'
          +'<span style="position:relative;color:'+wrC+';font-weight:900;font-size:10.5px">'+m.wr+'</span>'
        +'</div>'
        +'<span style="font-size:9.5px;font-weight:700;text-align:right;color:rgba(185,215,255,.75)">'+m.ret+'</span>'
        +'<span style="font-size:9.5px;font-weight:600;text-align:right" class="'+m.w30cls+'">'+m.w30ret+'</span>'
        +'<span style="font-size:9.5px;font-weight:600;text-align:right" class="'+m.lastCls+'">'+m.last+'</span>'
        +'<div style="display:flex;justify-content:center;align-items:center">'+spk+'</div>'
      +'</div>'
    +'</div>';
  }).join('');
}
window._v2e={getSpark:getSpark,getLeagueEnhanced:getLeagueEnhanced,getKPIs:getKPIs,
             getSignals:getSignals,renderSignals:renderSignals,renderRanking:renderRanking,
             renderRankingCols:renderRankingCols,mc:mc,msp:msp,mspArea:mspArea,daysTo:daysTo};
})();
</script>"""

# ════════════════════════════════════════════════════════════════════════
# HELPERS para HTML — period buttons
# ════════════════════════════════════════════════════════════════════════
def pills_html(chart_id, extra_cls=""):
    """4 period buttons, generic markup — styling handled per-variant CSS."""
    items = [("1 Sem","5","5 ruedas"), ("2 Sem","10","10 ruedas"),
             ("1 Mes","20","20 ruedas"), ("Todo","0","30 ruedas")]
    btns = ''.join(
        '<button class="v2e-pbtn{ec}" data-cpid="{id}" data-cp="{v}" '
        'onclick="_v2e_sp(\'{id}\',{v})" title="{tt}">{l}</button>'.format(
            ec=" "+extra_cls if extra_cls else "", id=chart_id, v=it[1], l=it[0], tt=it[2])
        for it in items)
    return '<div class="v2e-periods"><span class="v2e-period-lbl">Período</span>'+btns+'</div>'

# ════════════════════════════════════════════════════════════════════════
# VARIANTE E1 — "PRO CYAN"
# 2.6fr/1fr/1fr | pill buttons | 6 modelos | ranking 2-row full | señales
# Accent: cyan #18e8c8
# ════════════════════════════════════════════════════════════════════════
E1_CSS = r"""<style id="v2e1-css">
.v2e1-top { display:grid; grid-template-columns:2.6fr 1fr 1fr; gap:14px; align-items:start }
/* pill buttons */
.v2e1 .v2e-pbtn {
  font-size:9px; font-weight:800; padding:4px 12px; border-radius:20px; cursor:pointer;
  border:1px solid rgba(24,232,200,.22); color:rgba(120,165,215,.55);
  background:transparent; transition:all .15s; letter-spacing:.06em;
}
.v2e1 .v2e-pbtn:hover { border-color:rgba(24,232,200,.42); color:rgba(24,232,200,.8) }
.v2e1 .v2e-period-active {
  background:rgba(24,232,200,.14)!important; color:#18e8c8!important;
  border-color:rgba(24,232,200,.55)!important;
  box-shadow:0 0 10px rgba(24,232,200,.18);
}
@media(max-width:1100px){ .v2e1-top{ grid-template-columns:1fr } }
</style>"""

E1_HTML = """
<!-- ════════ V2E1 · PRO CYAN ════════ -->
<div class="v2e-wrap v2e1">
<div class="v2e1-top">

  <!-- Portfolio Performance -->
  <div class="v2e-panel">
    <div class="v2e-ph">
      <span>Portfolio Performance · Ret. normalizado por período</span>
      <span id="ve1-regime" class="v2e-badge v2e-ba-g">—</span>
    </div>
    {pills}
    <div class="v2e-legend" id="ve1-leg" style="margin-top:8px"></div>
    <div id="ve1-chart" style="position:relative;margin-top:4px"></div>
    <div class="v2e-pstat" id="vest_ve1-chart"></div>
  </div>

  <!-- Ranking Modelos -->
  <div class="v2e-panel">
    <div class="v2e-ph">Ranking Modelos <span style="font-size:8px;color:rgba(24,232,200,.4)">36 ruedas</span></div>
    <div id="ve1-ranking"></div>
  </div>

  <!-- Señales Vivas -->
  <div class="v2e-panel">
    <div class="v2e-ph">Señales Vivas
      <span class="v2e-badge v2e-ba-c" id="ve1-sig-n">—</span>
    </div>
    <div class="v2e-sig-scroll" id="ve1-signals"></div>
  </div>

</div>
</div>
""".format(pills=pills_html("ve1-chart"))

E1_JS = r"""<script id="v2e1-init">
(function(){
  var d=window._v2e; if(!d)return;
  var kpis=d.getKPIs();
  var rb=document.getElementById('ve1-regime');
  if(rb){rb.textContent=kpis.regime;rb.className='v2e-badge '+(kpis.regime==='SEGURO'?'v2e-ba-g':'v2e-ba-y');}
  /* 6 modelos con champion marcado */
  var mods=[{n:'ML_V97'},{n:'V13'},{n:'V11'},{n:'ML_V39'},{n:'ML_BRAIN_V11'},{n:'ML_V94'}];
  var datasets=[];
  mods.forEach(function(m){
    var sp=d.getSpark(m.n);
    if(sp&&sp.vals.length)datasets.push({vals:sp.vals,color:sp.color,labels:sp.labels,label:m.n,isChamp:m.n==='V11'});
  });
  var legEl=document.getElementById('ve1-leg');
  if(legEl)legEl.innerHTML=datasets.map(function(ds){
    return '<div class="v2e-leg-item"><div class="v2e-leg-dot" style="background:'+ds.color+'"></div><span>'+ds.label+'</span></div>';
  }).join('');
  window._v2e_reg('ve1-chart',datasets,{height:255,endLabels:true});
  window.addEventListener('resize',function(){
    setTimeout(function(){window._v2e_build('ve1-chart',datasets,_REG_P('ve1-chart'),{height:255,endLabels:true});},150);
  });
  /* ranking 2-row full style */
  d.renderRanking('ve1-ranking',10,'full');
  /* signals */
  var total=d.renderSignals('ve1-signals');
  var sn=document.getElementById('ve1-sig-n');if(sn)sn.textContent=total+' abiertas';
  function _REG_P(id){ return window._v2e_reg._regp?window._v2e_reg._regp(id):0; }
})();
</script>"""

# ════════════════════════════════════════════════════════════════════════
# VARIANTE E2 — "VIOLET DENSE"
# 2.4fr/1.1fr/1.1fr | segmented tabs | 5 modelos | ranking 2-row risk | señales
# Accent: violet #a882ff
# ════════════════════════════════════════════════════════════════════════
E2_CSS = r"""<style id="v2e2-css">
.v2e2-top { display:grid; grid-template-columns:2.4fr 1.1fr 1.1fr; gap:14px; align-items:stretch }
/* segmented control */
.v2e2 .v2e-periods { gap:0; display:inline-flex; border:1px solid rgba(168,130,255,.25); border-radius:9px; overflow:hidden }
.v2e2 .v2e-period-lbl { display:none }
.v2e2 .v2e-pbtn {
  font-size:9px; font-weight:800; padding:5px 13px; cursor:pointer;
  border:none; border-right:1px solid rgba(168,130,255,.15);
  color:rgba(120,165,215,.50); background:transparent;
  transition:all .14s; letter-spacing:.06em;
}
.v2e2 .v2e-pbtn:last-child { border-right:none }
.v2e2 .v2e-pbtn:hover { background:rgba(168,130,255,.08); color:rgba(168,130,255,.8) }
.v2e2 .v2e-period-active {
  background:rgba(168,130,255,.18)!important; color:#c084fc!important;
  box-shadow:inset 0 1px 4px rgba(168,130,255,.2);
}
/* ── re-show ft-footer + kpi-strip for V2E2 ── */
body.v2e2 .ft-footer { display:block!important }
body.v2e2 .kpi-strip {
  display:grid!important;
  grid-template-columns:repeat(4,minmax(0,1fr))!important;
  gap:10px; margin-bottom:14px;
  border-bottom:1px solid rgba(168,130,255,.12);
  padding-bottom:14px;
}
/* violet accent for kpi cards */
body.v2e2 .kpi-strip .kpi-card { border-color:rgba(168,130,255,.18)!important }
body.v2e2 .kpi-strip .accent-cyan { border-left-color:rgba(168,130,255,.55)!important }
body.v2e2 .kpi-strip .accent-gold { border-left-color:rgba(168,130,255,.35)!important }
body.v2e2 .kpi-strip .accent-green { border-left-color:rgba(68,232,144,.45)!important }
/* ── V2E2 footer ── */
.v2e2-footer {
  margin-top:18px;
  border-top:1px solid rgba(168,130,255,.14);
  padding:9px 4px;
  display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;
  font-size:9.5px; color:rgba(120,165,215,.42); letter-spacing:.03em;
}
.v2e2-footer .v2e2-ft-brand {
  font-weight:800; letter-spacing:.08em; text-transform:uppercase;
  color:rgba(168,130,255,.5);
}
.v2e2-footer .v2e2-ft-right { display:flex; gap:14px; align-items:center; flex-wrap:wrap }
.v2e2-footer .v2e2-ft-regime { font-weight:700 }
/* ── señales panel: flex-column para no inflar la fila del grid ── */
.v2e2-top > .v2e-panel:last-child { display:flex; flex-direction:column; }
.v2e2-top > .v2e-panel:last-child .v2e-ph { flex-shrink:0; }
.v2e2 .v2e-sig-scroll { flex:1; min-height:0; overflow-y:auto; }
/* ── rich signal rows ── */
.v2e2-sr { border-left:2px solid rgba(168,130,255,.3); border-bottom:1px solid rgba(255,255,255,.04); padding:6px 4px 6px 8px; }
.v2e2-sr:last-child { border-bottom:none }
.v2e2-sr-head { display:flex; align-items:center; gap:5px; flex-wrap:wrap; margin-bottom:3px; }
.v2e2-sr-rank { font-size:8.5px; font-weight:800; color:rgba(168,130,255,.6); min-width:16px; flex-shrink:0; }
.v2e2-sr-name { font-size:12px; font-weight:900; }
.v2e2-sr-champ { font-size:7px; font-weight:800; padding:1px 5px; border-radius:3px; text-transform:uppercase; letter-spacing:.05em; background:rgba(245,184,51,.15); color:#f5b833; border:1px solid rgba(245,184,51,.3); flex-shrink:0; }
.v2e2-sr-right { margin-left:auto; display:flex; align-items:center; gap:5px; flex-wrap:wrap; justify-content:flex-end; }
.v2e2-sr-kpi { font-size:9px; color:rgba(120,165,215,.5); white-space:nowrap; }
.v2e2-sr-mtm { font-size:9.5px; font-weight:800; padding:1px 5px; border-radius:3px; background:rgba(255,255,255,.05); white-space:nowrap; }
.v2e2-sr-mtm.pos { color:#44e890 } .v2e2-sr-mtm.neg { color:#f07080 }
/* separator */
.v2e2-sr-sep { display:flex; align-items:center; gap:5px; font-size:7.5px; font-weight:800; text-transform:uppercase; letter-spacing:.07em; margin:3px 0 2px; color:rgba(24,232,200,.65); }
.v2e2-sr-sep-line { flex:1; height:1px; background:currentColor; opacity:.2; }
/* picks — variant A (full: ticker pct price date) */
.v2e2-sr-pk { display:flex; align-items:center; font-size:10px; padding:1.5px 0; border-bottom:1px solid rgba(255,255,255,.03); gap:0; }
.v2e2-sr-pk:last-child { border-bottom:none }
.v2e2-sr-tk { font-weight:800; min-width:42px; }
.v2e2-sr-pct { font-weight:700; min-width:40px; }
.v2e2-sr-pct.pos { color:#44e890 } .v2e2-sr-pct.neg { color:#f07080 }
.v2e2-sr-pr { color:rgba(120,165,215,.45); font-size:9px; flex:1; padding:0 4px; }
.v2e2-sr-dt { font-size:8.5px; color:rgba(120,165,215,.4); white-space:nowrap; }
/* picks — variant B (compact: ticker pct date inline) */
.v2e2-sr-pk-b { font-size:9.5px; padding:1px 0; border-bottom:1px solid rgba(255,255,255,.03); display:flex; gap:4px; align-items:center; }
.v2e2-sr-pk-b:last-child { border-bottom:none }
.v2e2-sr-tk-b { font-weight:800; min-width:38px; }
.v2e2-sr-pct-b { font-weight:700; min-width:36px; }
.v2e2-sr-pct-b.pos { color:#44e890 } .v2e2-sr-pct-b.neg { color:#f07080 }
.v2e2-sr-dt-b { font-size:8px; color:rgba(120,165,215,.38); margin-left:auto; }
/* picks — variant C (summary only per model, no picks table) */
.v2e2-sr-c { border-left:2px solid rgba(168,130,255,.25); padding:7px 6px 7px 10px; border-bottom:1px solid rgba(255,255,255,.04); display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
.v2e2-sr-c:last-child { border-bottom:none }
.v2e2-sr-c .v2e2-sr-rank { min-width:20px; }
.v2e2-sr-c-bar { flex:1; height:4px; border-radius:2px; background:rgba(168,130,255,.12); margin:0 4px; min-width:20px; overflow:hidden; }
.v2e2-sr-c-fill { height:100%; border-radius:2px; }
@media(max-width:1100px){ .v2e2-top{ grid-template-columns:1fr } }
</style>"""

E2_HTML = """
<!-- ════════ V2E2 · VIOLET DENSE ════════ -->
<div class="v2e-wrap v2e2">
<div class="v2e2-top">

  <!-- Portfolio Performance -->
  <div class="v2e-panel">
    <div class="v2e-ph">
      <span>Portfolio Performance · Curva normalizada</span>
      <div style="display:flex;align-items:center;gap:10px">
        {pills}
        <span id="ve2-regime" class="v2e-badge v2e-ba-g">—</span>
      </div>
    </div>
    <div class="v2e-legend" id="ve2-leg"></div>
    <div id="ve2-chart" style="position:relative"></div>
    <div class="v2e-pstat" id="vest_ve2-chart"></div>
  </div>

  <!-- Ranking Modelos -->
  <div class="v2e-panel">
    <div class="v2e-ph">Ranking · Riesgo/Retorno</div>
    <div id="ve2-ranking"></div>
  </div>

  <!-- Señales Vivas -->
  <div class="v2e-panel">
    <div class="v2e-ph">Señales Vivas
      <span class="v2e-badge v2e-ba-m" id="ve2-sig-n">—</span>
    </div>
    <div class="v2e-sig-scroll" id="ve2-signals"></div>
  </div>

</div>
</div>
<!-- V2E2 footer -->
<footer class="v2e2-footer">
  <span class="v2e2-ft-brand">PythiaxEngine · Quant Terminal</span>
  <div class="v2e2-ft-right">
    <span id="ve2-footer-score"></span>
    <span id="ve2-footer-regime" class="v2e2-ft-regime"></span>
    <span id="ve2-footer-ts"></span>
  </div>
</footer>
""".format(pills=pills_html("ve2-chart"))

E2_JS = r"""<script id="v2e2-init">
(function(){
  /* mover kpi-strip al inicio del v2e2-wrap para que aparezca arriba */
  var kpiSec=document.querySelector('[data-bid="kpi-strip"]');
  var vwrap=document.querySelector('.v2e-wrap.v2e2');
  if(kpiSec&&vwrap&&vwrap.parentNode){
    document.body.classList.add('v2e2');
    vwrap.parentNode.insertBefore(kpiSec,vwrap);
    kpiSec.style.cssText+='display:grid!important;grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:10px;margin-bottom:14px;';
  }
  var d=window._v2e; if(!d)return;
  var kpis=d.getKPIs();
  var rb=document.getElementById('ve2-regime');
  if(rb){rb.textContent=kpis.regime;rb.className='v2e-badge '+(kpis.regime==='SEGURO'?'v2e-ba-g':'v2e-ba-y');}
  /* top 4 dinámico del ranking — 4 colores distintos */
  var TOP4=['#f5b833','#44e890','#6ea8cc','#b070ff'];
  var top4=d.getLeagueEnhanced(4);
  var datasets=top4.filter(function(m){return m.sparkVals&&m.sparkVals.length;}).map(function(m,i){
    return {vals:m.sparkVals,color:TOP4[i]||m.color,labels:m.sparkLabels,label:m.model,isChamp:i===0};
  });
  var legEl=document.getElementById('ve2-leg');
  if(legEl)legEl.innerHTML=datasets.map(function(ds){
    return '<div class="v2e-leg-item"><div class="v2e-leg-dot" style="background:'+ds.color+'"></div><span>'+ds.label+'</span></div>';
  }).join('');
  var _opts268A={height:268,endLabels:true,labelStyle:'nameVal'};
  window._v2e_reg('ve2-chart',datasets,_opts268A);
  window.addEventListener('resize',function(){
    setTimeout(function(){window._v2e_build('ve2-chart',datasets,0,_opts268A);},150);
  });
  /* ranking columnar style */
  d.renderRankingCols('ve2-ranking',10);
  var total=d.renderSignals('ve2-signals');
  var sn=document.getElementById('ve2-sig-n');if(sn)sn.textContent=total+' abiertas';
  /* footer */
  var fsc=document.getElementById('ve2-footer-score');
  var frg=document.getElementById('ve2-footer-regime');
  var fts=document.getElementById('ve2-footer-ts');
  if(fsc)fsc.textContent='Calidad datos: '+kpis.sysScore;
  if(frg){frg.textContent='Régimen: '+kpis.regime;frg.style.color=kpis.regime==='SEGURO'?'#44e890':'#f5b833';}
  if(fts){
    var syCard=document.querySelector('[data-bid="kpi-sistema"]');
    var ts=syCard&&syCard.getAttribute('data-ts');
    if(ts){
      try{
        var dt=new Date(ts);
        var ar=new Date(dt.getTime()-3*3600000);
        var pad=function(n){return String(n).padStart(2,'0');};
        fts.textContent='Gen. '+dt.getFullYear()+'-'+pad(dt.getMonth()+1)+'-'+pad(dt.getDate())+' '+pad(dt.getHours())+':'+pad(dt.getMinutes())+' UTC  ·  '+pad(ar.getUTCHours())+':'+pad(ar.getUTCMinutes())+' AR';
      }catch(e){}
    }
  }
})();
</script>"""

# ════════════════════════════════════════════════════════════════════════
# VARIANTE E3 — "GOLD EXECUTIVE"
# 2.6fr/1.05fr/1.05fr | block buttons | 4 modelos champion highlighted | ranking default 2-row
# Accent: gold #f5b833
# ════════════════════════════════════════════════════════════════════════
E3_CSS = r"""<style id="v2e3-css">
.v2e3-top { display:grid; grid-template-columns:2.6fr 1.05fr 1.05fr; gap:14px; align-items:start }
/* block/square buttons */
.v2e3 .v2e-pbtn {
  font-size:9px; font-weight:800; padding:5px 10px; border-radius:6px; cursor:pointer;
  border:none; color:rgba(120,165,215,.48);
  background:rgba(255,255,255,.06); transition:all .14s; letter-spacing:.06em;
}
.v2e3 .v2e-pbtn:hover { background:rgba(245,184,51,.1); color:rgba(245,184,51,.8) }
.v2e3 .v2e-period-active {
  background:rgba(245,184,51,.18)!important; color:#f5b833!important;
  box-shadow:0 0 8px rgba(245,184,51,.16);
}
/* exec header strip */
.v2e3-header {
  display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:14px
}
.v2e3-kpi {
  border-radius:10px; padding:11px 13px;
  border:1px solid rgba(120,165,215,.12);
  background:rgba(255,255,255,.025);
}
.v2e3-kpi-l { font-size:7.5px; text-transform:uppercase; letter-spacing:.15em; font-weight:800; margin-bottom:5px; opacity:.55 }
.v2e3-kpi-v { font-size:18px; font-weight:900; letter-spacing:-.03em }
.v2e3-kpi-s { font-size:9.5px; margin-top:3px; opacity:.6 }
@media(max-width:1100px){ .v2e3-top{ grid-template-columns:1fr } .v2e3-header{ grid-template-columns:repeat(2,1fr) } }
</style>"""

E3_HTML = """
<!-- ════════ V2E3 · GOLD EXECUTIVE ════════ -->
<div class="v2e-wrap v2e3">

  <!-- Executive KPI header strip -->
  <div class="v2e3-header" id="ve3-header"></div>

  <div class="v2e3-top">

    <!-- Portfolio Performance -->
    <div class="v2e-panel">
      <div class="v2e-ph">
        <span>Portfolio Performance · Top 6 modelos</span>
        {pills}
      </div>
      <div class="v2e-legend" id="ve3-leg"></div>
      <div id="ve3-chart" style="position:relative"></div>
      <div class="v2e-pstat" id="vest_ve3-chart"></div>
    </div>

    <!-- Ranking Modelos -->
    <div class="v2e-panel">
      <div class="v2e-ph">Ranking <span style="font-size:8px;color:rgba(245,184,51,.4)">completo</span></div>
      <div id="ve3-ranking"></div>
    </div>

    <!-- Señales Vivas -->
    <div class="v2e-panel">
      <div class="v2e-ph">Señales Vivas
        <span class="v2e-badge v2e-ba-y" id="ve3-sig-n">—</span>
      </div>
      <div class="v2e-sig-scroll" id="ve3-signals"></div>
    </div>

  </div>
</div>
""".format(pills=pills_html("ve3-chart"))

E3_JS = r"""<script id="v2e3-init">
(function(){
  var d=window._v2e; if(!d)return;
  var kpis=d.getKPIs();
  var league=d.getLeagueEnhanced(4);
  /* exec header */
  var hdr=document.getElementById('ve3-header');
  if(hdr&&league.length){
    var regC=kpis.regime==='SEGURO'?'#44e890':'#f5b833';
    var items=[
      {l:'Champion',v:kpis.champ,s:'líder en competencia',c:'#f5b833'},
      {l:'Señales hoy',v:kpis.picks,s:'picks generados hoy',c:'#a882ff'},
      {l:'Calidad datos',v:kpis.sysScore,s:'verificación sistema',c:kpis.sysColor},
      {l:'Régimen',v:kpis.regime,s:'condición de mercado',c:regC},
    ];
    hdr.innerHTML=items.map(function(it){
      return '<div class="v2e3-kpi" style="border-color:'+it.c+'22">'
        +'<div class="v2e3-kpi-l" style="color:'+it.c+'">'+it.l+'</div>'
        +'<div class="v2e3-kpi-v" style="color:'+it.c+'">'+it.v+'</div>'
        +'<div class="v2e3-kpi-s">'+it.s+'</div>'
        +'</div>';
    }).join('');
  }
  /* 6 modelos, champion highlighted */
  var mods=[{n:'ML_V97',ch:true},{n:'V13'},{n:'V11'},{n:'ML_V39'},{n:'ML_BRAIN_V11'},{n:'ML_V94'}];
  var datasets=[];
  mods.forEach(function(m){
    var sp=d.getSpark(m.n);
    if(sp&&sp.vals.length)datasets.push({vals:sp.vals,color:sp.color,labels:sp.labels,label:m.n,isChamp:!!m.ch});
  });
  var legEl=document.getElementById('ve3-leg');
  if(legEl)legEl.innerHTML=datasets.map(function(ds){
    return '<div class="v2e-leg-item"><div class="v2e-leg-dot" style="background:'+ds.color+'"></div><span>'+ds.label+'</span></div>';
  }).join('');
  window._v2e_reg('ve3-chart',datasets,{height:255,endLabels:true});
  window.addEventListener('resize',function(){
    setTimeout(function(){window._v2e_build('ve3-chart',datasets,0,{height:255,endLabels:true});},150);
  });
  /* ranking default 2-row */
  d.renderRanking('ve3-ranking',10,'default');
  var total=d.renderSignals('ve3-signals');
  var sn=document.getElementById('ve3-sig-n');if(sn)sn.textContent=total+' abiertas';
})();
</script>"""

# ════════════════════════════════════════════════════════════════════════
# GENERATOR
# ════════════════════════════════════════════════════════════════════════
def make(label, extra_css, body_html, body_js):
    h = BASE
    h = h.replace('<body>', '<body class="v2e">', 1)
    h = h.replace(HEAD_END, SHARED_CSS + '\n' + extra_css + '\n' + HEAD_END, 1)
    h = h.replace(ANCHOR, body_html + '\n' + ANCHOR, 1)
    h = h.replace(BODY_END, SHARED_JS + '\n' + body_js + '\n' + BODY_END, 1)
    h = h.replace('<title>Pythiax', '<title>[' + label + '] Pythiax', 1)
    return h

# ── Color palette comparison variants (Label A / nameVal, sin amarillo) ──
_TOP4 = "var TOP4=['#f5b833','#44e890','#6ea8cc','#b070ff']"
E2_JS_D1 = E2_JS.replace(_TOP4, "var TOP4=['#ff4d6d','#00e5ff','#b388ff','#ff9100']")
E2_JS_D2 = E2_JS.replace(_TOP4, "var TOP4=['#f72585','#4cc9f0','#80ffdb','#ff6b35']")
E2_JS_D3 = E2_JS.replace(_TOP4, "var TOP4=['#e040fb','#18e8c8','#c5f82a','#ff7043']")
# D4: V13=lila(top) ML_V97=verde V11=cyan ML_V39=gris (por rendimiento chart)
E2_JS_D4 = E2_JS.replace(_TOP4, "var TOP4=['#00aacc','#44e890','#8899aa','#b070ff']")

# Signal rendering variants (A=full, B=compact, C=summary cards)
_OLD_RENDER_SIGS = "  var total=d.renderSignals('ve2-signals');\n  var sn=document.getElementById('ve2-sig-n');if(sn)sn.textContent=total+' abiertas';"
_RENDER_SIG_A = """
    /* ── renderSigRich variant A: full (ticker | pct | price | →date) ── */
    (function(){
      var sigs=d.getSignals();
      var league=d.getLeagueEnhanced(20);
      var rankMap={},infoMap={};
      league.forEach(function(m,i){rankMap[m.model]=i+1;infoMap[m.model]={wr:m.wr,ret:m.ret};});
      var html='',total=0;
      sigs.forEach(function(m){
        var rank=rankMap[m.model]||0;
        var isChamp=rank===1;
        var info=infoMap[m.model]||{};
        total+=m.openN;
        html+='<div class="v2e2-sr" style="border-left-color:'+m.color+'">';
        html+='<div class="v2e2-sr-head">';
        if(rank) html+='<span class="v2e2-sr-rank">'+rank+'°</span>';
        html+='<span class="v2e2-sr-name" style="color:'+m.color+'">'+m.model+'</span>';
        if(isChamp) html+='<span class="v2e2-sr-champ">Champion</span>';
        html+='<span class="v2e2-sr-right">';
        if(info.wr) html+='<span class="v2e2-sr-kpi">'+info.wr+' · '+info.ret+'</span>';
        html+='<span class="v2e2-sr-mtm '+m.mtmCls+'">'+m.mtm+'</span>';
        html+='</span></div>';
        if(m.openN){
          html+='<div class="v2e2-sr-sep"><span>⚡</span>ABIERTOS '+m.openN+'p<span class="v2e2-sr-sep-line"></span></div>';
          html+='<div>';
          m.picks.forEach(function(p){
            html+='<div class="v2e2-sr-pk">';
            html+='<span class="v2e2-sr-tk">'+p.ticker+'</span>';
            html+='<span class="v2e2-sr-pct '+p.pctCls+'">'+p.pct+'</span>';
            html+='<span class="v2e2-sr-pr">'+p.price+'</span>';
            html+='<span class="v2e2-sr-dt">→'+p.target+(p.days?'·'+p.days+'d':'')+'</span>';
            html+='</div>';
          });
          html+='</div>';
        }
        html+='</div>';
      });
      var el=document.getElementById('ve2-signals');
      if(el)el.innerHTML=html;
      var sn=document.getElementById('ve2-sig-n');
      if(sn)sn.textContent=total+' abiertas';
    })();""".strip()
_RENDER_SIG_B = """
    /* ── renderSigRich variant B: compact (ticker · pct · →date, no price) ── */
    (function(){
      var sigs=d.getSignals();
      var league=d.getLeagueEnhanced(20);
      var rankMap={},infoMap={};
      league.forEach(function(m,i){rankMap[m.model]=i+1;infoMap[m.model]={wr:m.wr,ret:m.ret};});
      var html='',total=0;
      sigs.forEach(function(m){
        var rank=rankMap[m.model]||0;
        var isChamp=rank===1;
        var info=infoMap[m.model]||{};
        total+=m.openN;
        html+='<div class="v2e2-sr" style="border-left-color:'+m.color+'">';
        html+='<div class="v2e2-sr-head">';
        if(rank) html+='<span class="v2e2-sr-rank">'+rank+'°</span>';
        html+='<span class="v2e2-sr-name" style="color:'+m.color+'">'+m.model+'</span>';
        if(isChamp) html+='<span class="v2e2-sr-champ">Champion</span>';
        html+='<span class="v2e2-sr-right">';
        if(info.wr) html+='<span class="v2e2-sr-kpi">'+info.wr+' · '+info.ret+'</span>';
        html+='<span class="v2e2-sr-mtm '+m.mtmCls+'">'+m.mtm+'</span>';
        html+='</span></div>';
        if(m.openN){
          html+='<div class="v2e2-sr-sep"><span>⚡</span>'+m.openN+'p<span class="v2e2-sr-sep-line"></span></div>';
          html+='<div>';
          m.picks.forEach(function(p){
            html+='<div class="v2e2-sr-pk-b">';
            html+='<span class="v2e2-sr-tk-b">'+p.ticker+'</span>';
            html+='<span class="v2e2-sr-pct-b '+p.pctCls+'">'+p.pct+'</span>';
            html+='<span class="v2e2-sr-dt-b">→'+p.target+(p.days?'·'+p.days+'d':'')+'</span>';
            html+='</div>';
          });
          html+='</div>';
        }
        html+='</div>';
      });
      var el=document.getElementById('ve2-signals');
      if(el)el.innerHTML=html;
      var sn=document.getElementById('ve2-sig-n');
      if(sn)sn.textContent=total+' abiertas';
    })();""".strip()
_RENDER_SIG_C = """
    /* ── renderSigRich variant C: summary cards (WR bar, no individual picks) ── */
    (function(){
      var sigs=d.getSignals();
      var league=d.getLeagueEnhanced(20);
      var rankMap={},infoMap={};
      league.forEach(function(m,i){rankMap[m.model]=i+1;infoMap[m.model]={wr:m.wr,wrNum:m.wrNum,ret:m.ret};});
      var html='',total=0;
      sigs.forEach(function(m){
        var rank=rankMap[m.model]||0;
        var isChamp=rank===1;
        var info=infoMap[m.model]||{};
        var wrPct=info.wrNum||0;
        total+=m.openN;
        html+='<div class="v2e2-sr-c" style="border-left-color:'+m.color+'">';
        if(rank) html+='<span class="v2e2-sr-rank">'+rank+'°</span>';
        html+='<span class="v2e2-sr-name" style="color:'+m.color+';font-size:11px">'+m.model+'</span>';
        if(isChamp) html+='<span class="v2e2-sr-champ">Champion</span>';
        html+='<div class="v2e2-sr-c-bar"><div class="v2e2-sr-c-fill" style="width:'+Math.min(100,wrPct)+'%;background:'+m.color+';opacity:.7"></div></div>';
        if(info.wr) html+='<span class="v2e2-sr-kpi">'+info.wr+'</span>';
        html+='<span class="v2e2-sr-mtm '+m.mtmCls+'">'+m.openN+'p · '+m.mtm+'</span>';
        html+='</div>';
      });
      var el=document.getElementById('ve2-signals');
      if(el)el.innerHTML=html;
      var sn=document.getElementById('ve2-sig-n');
      if(sn)sn.textContent=total+' abiertas';
    })();""".strip()
E2_JS_SIG_A = E2_JS_D4.replace(_OLD_RENDER_SIGS, _RENDER_SIG_A)
E2_JS_SIG_B = E2_JS_D4.replace(_OLD_RENDER_SIGS, _RENDER_SIG_B)
E2_JS_SIG_C = E2_JS_D4.replace(_OLD_RENDER_SIGS, _RENDER_SIG_C)

VARIANTS = [
    ('e1_pro_cyan',       'E1 · Pro Cyan',          E1_CSS, E1_HTML, E1_JS),
    ('e2_violet_dense',   'E2 · Violet Dense',       E2_CSS, E2_HTML, E2_JS_SIG_A),
    ('e3_gold_executive', 'E3 · Gold Executive',     E3_CSS, E3_HTML, E3_JS),
    # Color palette previews (Label A, sin amarillo)
    ('e2_color_d1',       'E2 · Paleta D1 Cyber',    E2_CSS, E2_HTML, E2_JS_D1),
    ('e2_color_d2',       'E2 · Paleta D2 Marine',   E2_CSS, E2_HTML, E2_JS_D2),
    ('e2_color_d3',       'E2 · Paleta D3 Space',    E2_CSS, E2_HTML, E2_JS_D3),
    ('e2_color_d4',       'E2 · Paleta D4 Classic',  E2_CSS, E2_HTML, E2_JS_D4),
    # Señales Vivas variants (A=full, B=compact, C=summary)
    ('e2_sig_a',          'E2 · Señales A (Full)',    E2_CSS, E2_HTML, E2_JS_SIG_A),
    ('e2_sig_b',          'E2 · Señales B (Compact)', E2_CSS, E2_HTML, E2_JS_SIG_B),
    ('e2_sig_c',          'E2 · Señales C (Summary)', E2_CSS, E2_HTML, E2_JS_SIG_C),
]

for vid, vlabel, vcss, vhtml, vjs in VARIANTS:
    out = make(vlabel, vcss, vhtml, vjs)
    dst = os.path.join(ROOT, 'analisis', '_staging_v2'+vid+'.html')
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(out)
    sz = os.path.getsize(dst)
    print(f'[{vlabel:24s}] → _staging_v2{vid}.html ({sz:,} bytes)')
    print(f'  URL: http://localhost:8765/_staging_v2{vid}.html')
    print()

# cleanup temp file
try: os.remove(os.path.join(ROOT, 'inspect_liga.py'))
except: pass
