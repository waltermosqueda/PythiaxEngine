#!/usr/bin/env python3
"""
Genera 3 variantes visuales del dashboard Aurora para previsualización.
Uso: python analisis/generar_previews.py
Salida:
  - dashboards/maquina_pensante/dashboard_operativo_aurora_pro.html
  - analisis/preview_c2_dense.html
  - analisis/preview_c3_card.html
"""
from __future__ import annotations
import sys, html as _html, math, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import analisis.generar_tablero_maquina_pensante as _gen
from herramientas.dashboard_paths import AURORA_PRO_HTML, ensure_dashboard_dir

OUTPUT_DIR = ROOT / "analisis"

# ─── helpers (same as generator) ─────────────────────────────────────────────
def _s(v):   return _html.escape("" if v is None else str(v))
def _f(v, d=2, signed=False):
    try:
        n = float(v)
        if math.isnan(n): return "-"
        return f"{n:{'+' if signed else ''}.{d}f}%"
    except: return "-"
def _i(v):
    try: return f"{int(v or 0):,}"
    except: return "0"
def _ff(v, d=2):
    try:
        n = float(v)
        return f"{n:.{d}f}" if not math.isnan(n) else "-"
    except: return "-"

def spark(vals, stroke, fill="none", w=240, h=60):
    vals = [float(x) for x in vals if x is not None]
    if not vals:
        return f"<svg viewBox='0 0 {w} {h}' class='spark'><rect width='{w}' height='{h}' rx='4' fill='rgba(255,255,255,0.03)'/></svg>"
    lo, hi = min(vals), max(vals)
    span = hi - lo or 1.0
    pts = []
    for i, v in enumerate(vals):
        x = i * (w - 8) / max(len(vals)-1, 1) + 4
        y = h - 6 - ((v - lo)/span) * (h - 12)
        pts.append((x, y))
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"4,{h-3} " + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + f" {w-4},{h-3}"
    lx, ly = pts[-1]
    return (f"<svg viewBox='0 0 {w} {h}' class='spark'>"
            f"<polygon points='{area}' fill='{fill}' opacity='0.14'/>"
            f"<polyline points='{line}' fill='none' stroke='{stroke}' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'/>"
            f"<circle cx='{lx:.1f}' cy='{ly:.1f}' r='3' fill='{stroke}'/>"
            "</svg>")

def badge(role):
    cls = {"activo":"ba-active","referencia":"ba-ref","base":"ba-base","observado":"ba-obs","legacy_ml":"ba-ml"}.get(role,"ba-base")
    return f"<span class='badge {cls}'>{_s(role)}</span>"

def fresh(days):
    if days is None: return "<span class='badge ba-muted'>sin fecha</span>"
    if days == 0:    return "<span class='badge ba-fresh'>al día</span>"
    if days == 1:    return "<span class='badge ba-warn'>1 rueda</span>"
    return f"<span class='badge ba-stale'>{days} ruedas</span>"

def cumul(vals):
    t, out = 0.0, []
    for v in vals:
        t += float(v or 0)
        out.append(round(t, 4))
    return out

def tone(role):
    return {"activo":"#18e8c8","referencia":"#f5b833","legacy_ml":"#a882ff","observado":"#44e890"}.get(role,"#6ea8cc")

# ─── HTML builder ─────────────────────────────────────────────────────────────

def render_html(payload: dict, css: str) -> str:
    # CSS strings use {{ }} as Python f-string escapes — resolve to real braces before embedding
    css = css.replace('{{', '{').replace('}}', '}')
    ig  = payload["integrity"]
    act = payload["active"]
    rec = payload["competition_recent"]
    div = payload["divergence"]
    ov  = payload["overlap"]

    ar       = act.get("active_run") or {}
    live     = ar.get("results_d", []) + ar.get("results_e", [])
    av       = act["active_version"]
    rv       = act.get("reference_version")
    champ_lbl = f"V{av}"
    ref_lbl   = f"V{rv}" if rv else "-"
    rm       = {str(r["version"]): r for r in rec["league_equalized"]}
    champ    = rm.get(champ_lbl, {})
    ch_eq    = champ.get("equalized_recent") or {}
    ch_30    = champ.get("recent_30") or {}
    ch_ticks = set(champ.get("latest_tickers") or [])
    eq_days  = rec.get("equalized_days", 0)
    league   = rec["league_equalized"]
    hist_rows = [r for r in league if r.get("role") != "legacy_ml"]
    ml_rows   = [r for r in league if r.get("role") == "legacy_ml"]
    leader    = league[0] if league else {}
    lw        = leader.get("window") or {}
    ch_rank   = rec.get("rank_equalized",{}).get(champ_lbl,"-")
    ref_row   = rm.get(ref_lbl, {})
    ref_eq    = ref_row.get("equalized_recent") or {}

    regime   = ar.get("regime_label","GLOBAL")
    breadth  = ar.get("breadth_pct")
    pred_for = ar.get("prediction_for","-")

    # sparklines
    ch_curve_svg  = spark(cumul(ch_30.get("spark_avg_return_pct",[])), "#18e8c8","#18e8c8", 360, 72)
    leader_svg    = spark(cumul((leader.get("equalized_recent") or {}).get("spark_avg_return_pct",[])), "#f5b833","#f5b833", 200, 50)

    # pick rows
    def pick_rows():
        if not live:
            return "<tr><td colspan='6' class='muted-td'>Sin picks en el snapshot más reciente.</td></tr>"
        rows = []
        for it in live:
            rows.append(
                f"<tr><td><strong>{_s(it.get('ticker'))}</strong></td>"
                f"<td class='muted-td'>{_s(it.get('signal'))}</td>"
                f"<td class='muted-td'>{_s(it.get('sector') or '-')}</td>"
                f"<td>{_ff(it.get('priority_score') or it.get('score'),1)}</td>"
                f"<td>{_f(it.get('priority_expected_return'),2,True)}</td>"
                f"<td>{_f(it.get('risk_pct'),1)}</td></tr>"
            )
        return "".join(rows)

    # league table (compact)
    def league_compact(rows, limit=8):
        body = []
        for r in rows[:limit]:
            w  = r.get("window") or {}
            wr = _f(w.get("accuracy_pct"))
            rt = _f(w.get("avg_return_pct"),3,True)
            body.append(
                f"<tr data-bid='leag-{_s(r['version'])}' data-blabel='{_s(r['version'])}' class='editable-block'>"
                f"<td><span class='rank-num'>{_i(r.get('rank'))}</span></td>"
                f"<td><strong>{_s(r['version'])}</strong> {badge(str(r.get('role','')))}</td>"
                f"<td>{fresh(r.get('stale_market_days'))}</td>"
                f"<td><strong>{wr}</strong><br><small>{rt}</small></td>"
                f"<td><small>{_i(w.get('active_days'))}/{_i(w.get('window_days'))} · {_i(w.get('evaluated'))} picks</small></td>"
                f"<td class='muted-td ticker-list'>{', '.join(r.get('latest_tickers',[])[:5]) or '-'}</td>"
                "</tr>"
            )
        return "".join(body)

    # full league table
    def league_full():
        body = []
        for r in league:
            eq = r.get("equalized_recent") or {}
            t30 = r.get("recent_30") or {}
            body.append(
                f"<tr>"
                f"<td><strong>{_s(r['version'])}</strong> {badge(str(r.get('role','')))}</td>"
                f"<td>{fresh(r.get('stale_market_days'))}</td>"
                f"<td>{_f(eq.get('accuracy_pct'))} / {_f(eq.get('avg_return_pct'),3,True)}</td>"
                f"<td>{_i(eq.get('active_days'))}/{_i(eq.get('window_days'))} · {_i(eq.get('evaluated'))}</td>"
                f"<td>{_f(t30.get('accuracy_pct'))} / {_f(t30.get('avg_return_pct'),3,True)}</td>"
                f"<td>{_i(t30.get('active_days'))}/{_i(t30.get('window_days'))} · {_i(t30.get('evaluated'))}</td>"
                f"<td class='muted-td ticker-list'>{', '.join(r.get('latest_tickers',[])[:6]) or '-'}</td>"
                "</tr>"
            )
        return "".join(body)

    # model card
    def model_card(r):
        role  = str(r.get("role",""))
        eq    = r.get("equalized_recent") or {}
        t30   = r.get("recent_30") or {}
        clr   = tone(role)
        series = eq.get("spark_avg_return_pct") or t30.get("spark_avg_return_pct") or []
        curve  = spark(cumul(series), clr, clr, 260, 60)
        bid    = f"mc-{_gen.dom_id(r['version'])}"
        wr_val = eq.get("accuracy_pct")
        wr_cls = "pos" if (wr_val or 0) >= 55 else "neg" if (wr_val or 0) < 50 else ""
        tickers = ", ".join(r.get("latest_tickers",[])[:6]) or "–"
        return (
            f"<article class='model-card editable-block' data-bid='{bid}' data-blabel='{_s(r['version'])}'>"
            f"<div class='mc-head'>"
            f"<div class='mc-title'>{_s(r['version'])}</div>"
            f"<div class='mc-badges'>{badge(role)} {fresh(r.get('stale_market_days'))}</div>"
            f"<div class='rank-num mc-rank'>#{_i(r.get('rank'))}</div>"
            "</div>"
            f"<div class='mc-spark'>{curve}</div>"
            f"<div class='mc-kpis'>"
            f"<div class='mk'><span>WR</span><strong class='{wr_cls}'>{_f(eq.get('accuracy_pct'))}</strong></div>"
            f"<div class='mk'><span>Ret</span><strong>{_f(eq.get('avg_return_pct'),3,True)}</strong></div>"
            f"<div class='mk'><span>Hits</span><strong>{_i(eq.get('hits'))}/{_i(eq.get('evaluated'))}</strong></div>"
            f"<div class='mk'><span>Picks</span><strong>{_i(r.get('latest_picks'))}</strong></div>"
            "</div>"
            f"<div class='mc-tickers'>{_s(tickers)}</div>"
            f"<details class='mc-detail'><summary>Más datos</summary>"
            f"<div class='mc-detail-body'>"
            f"<div class='kl'><span>30 ruedas</span><strong>{_f(t30.get('accuracy_pct'))} / {_f(t30.get('avg_return_pct'),3,True)}</strong></div>"
            f"<div class='kl'><span>Mejor día</span><strong>{_f(t30.get('best_day_return_pct'),2,True)}</strong></div>"
            f"<div class='kl'><span>Peor día</span><strong>{_f(t30.get('worst_day_return_pct'),2,True)}</strong></div>"
            f"<div class='kl'><span>Universo</span><strong>{_i(r.get('unique_tickers'))} tickers</strong></div>"
            f"<div class='kl'><span>Última fecha</span><strong>{_s(r.get('last_date'))}</strong></div>"
            "</div></details>"
            "</article>"
        )

    # heatmap
    def heatmap():
        focus = [r for r in ([champ] + hist_rows[:3] + ml_rows[:2]) if r]
        # dates from champion calendar
        cal = (champ.get("recent_15") or {}).get("calendar") or []
        dates = [c["date"] for c in cal]
        if not dates: return "<p class='muted-td'>Sin datos de heatmap.</p>"
        header = "".join(f"<th>{_s(d[5:])}</th>" for d in dates)
        body = []
        for r in focus:
            cal_map = {str(c["date"]): c for c in ((r.get("recent_15") or {}).get("calendar") or [])}
            cells = [f"<th class='hm-label'>{_s(r['version'])}<br><small>{_s(r.get('role',''))}</small></th>"]
            for d in dates:
                it    = cal_map.get(d, {})
                ret   = it.get("avg_return_pct")
                acc   = it.get("accuracy_pct")
                picks = it.get("picks", 0)
                tks   = ", ".join(it.get("tickers") or [])
                text  = "-" if ret is None else f"{float(ret):+.1f}"
                if ret is None:
                    bg = "rgba(255,255,255,0.04)"
                elif float(ret) >= 0:
                    intens = min(abs(float(ret))/5.0, 1.0)
                    bg = f"rgba(68,232,144,{0.15+intens*0.50:.2f})"
                else:
                    intens = min(abs(float(ret))/5.0, 1.0)
                    bg = f"rgba(252,92,125,{0.15+intens*0.50:.2f})"
                title = f"{r['version']} {d} | ret {_f(ret,2,True)} WR {_f(acc)} picks {picks}\n{tks}"
                cells.append(f"<td style='background:{bg}' title='{_s(title)}'>{_s(text)}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        return (f"<table class='hm-table'><thead><tr><th></th>{header}</tr></thead>"
                f"<tbody>{''.join(body)}</tbody></table>")

    # overlap matrix
    def overlap_matrix():
        labels = ov.get("labels", [])
        matrix = ov.get("matrix", [])
        if not labels: return "<p class='muted-td'>Sin datos.</p>"
        header = "".join(f"<th>{_s(l)}</th>" for l in labels)
        rows = []
        for i, lbl in enumerate(labels):
            cells = [f"<th class='om-label'>{_s(lbl)}</th>"]
            for j, val in enumerate(matrix[i]):
                if val is None:
                    bg, text = "rgba(255,255,255,0.04)", "–"
                else:
                    c = max(0.0, min(1.0, float(val)))
                    bg = f"rgba(24,232,200,{0.08+c*0.55:.2f})"
                    text = f"{val:.2f}"
                cells.append(f"<td style='background:{bg}'>{_s(text)}</td>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return (f"<table class='om-table'><thead><tr><th></th>{header}</tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table>")

    # ── TEMPLATE ──────────────────────────────────────────────────────────────
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Titan · Dashboard Operativo</title>
  <style>{css}</style>
</head>
<body>

<!-- SIDEBAR ──────────────────────────────────────────────────── -->
<aside class="sidebar" id="sidebar">
  <div class="sidebar-inner">

    <div class="brand-block">
      <div class="brand-name">TITAN</div>
      <div class="brand-sub">Machine Dashboard</div>
    </div>

    <div class="regime-pill regime-{_s(regime.lower())}">
      <span class="rp-dot"></span>
      <span>{_s(regime)}</span>
      <span class="rp-breadth">breadth {_f(breadth,1) if breadth is not None else '-'}</span>
    </div>

    <nav class="side-nav">
      <a class="sn-link active" href="#overview">
        <span class="sn-icon">▦</span><span>Dashboard</span>
        <span class="sn-tag">{_s(champ_lbl)}</span>
      </a>
      <a class="sn-link" href="#picks">
        <span class="sn-icon">◎</span><span>Picks hoy</span>
        <span class="sn-tag">{len(live)}</span>
      </a>
      <a class="sn-link" href="#league">
        <span class="sn-icon">⬡</span><span>Liga</span>
        <span class="sn-tag">{eq_days}d</span>
      </a>
      <a class="sn-link" href="#models">
        <span class="sn-icon">◈</span><span>Modelos</span>
        <span class="sn-tag">{len(league)}</span>
      </a>
      <a class="sn-link" href="#heatmap">
        <span class="sn-icon">▤</span><span>Heatmap</span>
      </a>
      <a class="sn-link" href="#data">
        <span class="sn-icon">◻</span><span>Data</span>
      </a>
    </nav>

    <div class="side-section-label">Vistas</div>
    <div class="side-views">
      <a class="sv-btn" href="tablero_maquina_pensante_executive.html">Executive</a>
      <a class="sv-btn" href="tablero_maquina_pensante_lab.html">Lab</a>
    </div>

    <details class="side-drawer">
      <summary>Datos DB</summary>
      <div class="sd-body">
        <div class="kl"><span>Mercado</span><strong>{_s(ig['latest_market_date'])}</strong></div>
        <div class="kl"><span>Predictions</span><strong>{_i(ig['predictions_count'])}</strong></div>
        <div class="kl"><span>Outcomes</span><strong>{_i(ig['outcomes_count'])}</strong></div>
        <div class="kl"><span>Regimes</span><strong>{_i(ig['regimes_count'])}</strong></div>
        <div class="kl"><span>Modelos</span><strong>{_i(ig['prediction_models'])}</strong></div>
      </div>
    </details>

    <details class="side-drawer">
      <summary>Config</summary>
      <div class="sd-body">
        <div class="kl"><span>Champion</span><strong>{_s(champ_lbl)}</strong></div>
        <div class="kl"><span>Referencia</span><strong>{_s(ref_lbl)}</strong></div>
        <div class="kl"><span>Muestra común</span><strong>{eq_days} ruedas</strong></div>
      </div>
    </details>

    <details class="side-drawer">
      <summary>Metodología</summary>
      <div class="sd-body">
        La liga principal compara todos los modelos en la misma cantidad de días activos
        (muestra igualada). El contexto de 30 ruedas es complementario.
        Todos los números vienen de <code>predictions + outcomes</code> en SQLite.
      </div>
    </details>

  </div><!-- /sidebar-inner -->

  <!-- Toggle tab pegado al borde derecho del sidebar -->
  <button class="sidebar-tab" id="sidebarTab" title="Ocultar / mostrar menú">‹</button>
</aside>

<!-- MAIN ─────────────────────────────────────────────────────── -->
<div class="main-wrap" id="mainWrap">

  <!-- TOPBAR ──────────────────────────────────── -->
  <header class="topbar" id="overview">
    <div class="tb-left">
      <div class="tb-title">Titan · Dashboard Operativo</div>
      <div class="tb-meta">
        <span class="tb-pill">Generado {_s(payload["generated_at"][:16])}</span>
        <span class="tb-pill">Mercado {_s(ig['latest_market_date'])}</span>
        <span class="tb-pill">Target {_s(pred_for)}</span>
        <span class="tb-pill tb-pill-regime regime-{_s(regime.lower())}">{_s(regime)}</span>
      </div>
    </div>
    <div class="tb-right">
      <a class="tb-btn" href="#league">Ver liga</a>
      <a class="tb-btn tb-ghost" href="#data">Data</a>
      <button class="tb-edit-btn" id="editModeBtn" title="Activar modo edición">✎ Editar</button>
    </div>
  </header>

  <!-- KPI STRIP ───────────────────────────────── -->
  <section class="kpi-strip editable-block" data-bid="kpi-strip" data-blabel="Franja KPI">
    <div class="kpi-card accent-cyan editable-block" data-bid="kpi-champion" data-blabel="KPI Champion">
      <div class="kc-label">Champion activo</div>
      <div class="kc-value">{_s(champ_lbl)}</div>
      <div class="kc-sub">WR {_f(ch_eq.get('accuracy_pct'))} · ret {_f(ch_eq.get('avg_return_pct'),3,True)} · #{_i(ch_rank)}</div>
    </div>
    <div class="kpi-card accent-gold editable-block" data-bid="kpi-leader" data-blabel="KPI Líder">
      <div class="kc-label">Líder liga</div>
      <div class="kc-value">{_s(leader.get('version') or '-')}</div>
      <div class="kc-sub">WR {_f(lw.get('accuracy_pct'))} · ret {_f(lw.get('avg_return_pct'),3,True)}</div>
    </div>
    <div class="kpi-card accent-green editable-block" data-bid="kpi-picks" data-blabel="KPI Picks">
      <div class="kc-label">Picks hoy</div>
      <div class="kc-value">{len(live)}</div>
      <div class="kc-sub">{_s(regime)} · breadth {_f(breadth,1) if breadth is not None else '-'}</div>
    </div>
    <div class="kpi-card editable-block" data-bid="kpi-ref" data-blabel="KPI Referencia">
      <div class="kc-label">Referencia {_s(ref_lbl)}</div>
      <div class="kc-value">{_f(ref_eq.get('accuracy_pct'))}</div>
      <div class="kc-sub">ret {_f(ref_eq.get('avg_return_pct'),3,True)} · {_i(ref_row.get('latest_picks'))} picks</div>
    </div>
    <div class="kpi-card accent-rose editable-block" data-bid="kpi-db" data-blabel="KPI DB">
      <div class="kc-label">Outcomes DB</div>
      <div class="kc-value">{_i(ig['outcomes_count'])}</div>
      <div class="kc-sub">{_i(ig['predictions_count'])} pred · {_i(ig['regimes_count'])} regimes</div>
    </div>
    <div class="kpi-card editable-block" data-bid="kpi-integrity" data-blabel="KPI Integridad">
      <div class="kc-label">Integridad</div>
      <div class="kc-value">{ig['coverage_last_30']['predictions']['covered_days']}/{ig['coverage_last_30']['predictions']['expected_days']}</div>
      <div class="kc-sub">cobertura pred últimas 30 ruedas</div>
    </div>
  </section>

  <!-- ROW 1: CHAMPION + LIGA ──────────────────── -->
  <div class="row-2-3" id="champion">

    <section class="panel editable-block" data-bid="champion-panel" data-blabel="Panel Champion">
      <div class="panel-head">
        <div>
          <div class="panel-label">Champion activo</div>
          <h2 class="panel-title">{_s(champ_lbl)} · Curva reciente</h2>
        </div>
        <div class="head-badges">
          {badge("activo")} {fresh(champ.get("stale_market_days"))}
        </div>
      </div>
      <div class="ch-curve">{ch_curve_svg}</div>
      <div class="ch-grid">
        <div class="ch-box editable-block" data-bid="ch-equalized" data-blabel="Champion muestra igualada">
          <div class="ch-box-label">Muestra igualada</div>
          <div class="ch-box-val">{_f(ch_eq.get('accuracy_pct'))} · {_f(ch_eq.get('avg_return_pct'),3,True)}</div>
          <div class="kl"><span>Hits</span><strong>{_i(ch_eq.get('hits'))}/{_i(ch_eq.get('evaluated'))}</strong></div>
          <div class="kl"><span>Peor rueda</span><strong>{_f(ch_eq.get('worst_day_return_pct'),2,True)}</strong></div>
        </div>
        <div class="ch-box editable-block" data-bid="ch-context" data-blabel="Champion contexto 30">
          <div class="ch-box-label">Contexto 30 ruedas</div>
          <div class="ch-box-val">{_f(ch_30.get('accuracy_pct'))} · {_f(ch_30.get('avg_return_pct'),3,True)}</div>
          <div class="kl"><span>Universo</span><strong>{_i(champ.get('unique_tickers'))}</strong></div>
          <div class="kl"><span>Picks últimos</span><strong>{_i(champ.get('latest_picks'))}</strong></div>
        </div>
        <div class="ch-box editable-block" data-bid="ch-sleeve-d" data-blabel="Sleeve D">
          <div class="ch-box-label">Sleeve D (D10)</div>
          <div class="ch-box-val">{_f(act['active_d'].get('accuracy_pct'))}</div>
          <div class="kl"><span>Ret medio</span><strong>{_f(act['active_d'].get('avg_return_pct'),3,True)}</strong></div>
          <div class="kl"><span>Racha</span><strong>{_s(act['active_d'].get('streak',{}).get('streak_type','-'))} {_i(act['active_d'].get('streak',{}).get('current_streak'))}</strong></div>
        </div>
        <div class="ch-box editable-block" data-bid="ch-sleeve-e" data-blabel="Sleeve E">
          <div class="ch-box-label">Sleeve E (D15)</div>
          <div class="ch-box-val">{_f(act['active_e'].get('accuracy_pct'))}</div>
          <div class="kl"><span>Ret medio</span><strong>{_f(act['active_e'].get('avg_return_pct'),3,True)}</strong></div>
          <div class="kl"><span>n evaluados</span><strong>{_i(act['active_e'].get('total'))}</strong></div>
        </div>
      </div>
    </section>

    <section class="panel editable-block" data-bid="liga-panel" data-blabel="Panel Liga" id="league">
      <div class="panel-head">
        <div>
          <div class="panel-label">Liga principal</div>
          <h2 class="panel-title">Ranking igualado · {eq_days} ruedas</h2>
        </div>
      </div>
      <div class="leader-strip">
        <div class="ls-info">
          <div class="ls-version">{_s(leader.get('version') or '-')}</div>
          <div class="ls-sub">líder actual · WR {_f(lw.get('accuracy_pct'))} · ret {_f(lw.get('avg_return_pct'),3,True)}</div>
        </div>
        <div class="ls-spark">{leader_svg}</div>
      </div>
      <table class="data-table">
        <thead><tr><th>#</th><th>Modelo</th><th>Estado</th><th>WR / Ret</th><th>Muestra · Picks</th><th>Picks actuales</th></tr></thead>
        <tbody>{league_compact(league, 10)}</tbody>
      </table>
    </section>

  </div><!-- /row-2-3 -->

  <!-- ROW 2: PICKS + CONTROL ──────────────────── -->
  <div class="row-1-1" id="picks">

    <section class="panel editable-block" data-bid="picks-panel" data-blabel="Panel Picks vivos">
      <div class="panel-head">
        <div>
          <div class="panel-label">Predicción viva</div>
          <h2 class="panel-title">{_s(champ_lbl)} · Activos para {_s(pred_for)}</h2>
        </div>
        <span class="tb-pill tb-pill-regime regime-{_s(regime.lower())}">{_s(regime)}</span>
      </div>
      <table class="data-table">
        <thead><tr><th>Ticker</th><th>Setup</th><th>Sector</th><th>Priority</th><th>Ret esp.</th><th>Riesgo</th></tr></thead>
        <tbody>{pick_rows()}</tbody>
      </table>
    </section>

    <section class="panel editable-block" data-bid="control-panel" data-blabel="Panel Control">
      <div class="panel-head">
        <div>
          <div class="panel-label">Control operativo</div>
          <h2 class="panel-title">Estado del sistema</h2>
        </div>
      </div>
      <div class="ctrl-grid">
        <div class="ctrl-box editable-block" data-bid="ctrl-continuidad" data-blabel="Continuidad">
          <div class="ch-box-label">Cobertura pred</div>
          <div class="ch-box-val">{ig['coverage_last_30']['predictions']['covered_days']}/{ig['coverage_last_30']['predictions']['expected_days']}</div>
          <div class="kl"><span>Outcomes</span><strong>{ig['coverage_last_30']['outcomes']['covered_days']}/{ig['coverage_last_30']['outcomes']['expected_days']}</strong></div>
        </div>
        <div class="ctrl-box editable-block" data-bid="ctrl-snapshot" data-blabel="Snapshot">
          <div class="ch-box-label">Snapshot</div>
          <div class="ch-box-val">{_s(ar.get('regime_label','-'))}</div>
          <div class="kl"><span>Memoria</span><strong>{_i(len(ar.get('memory_context',[])))}</strong></div>
          <div class="kl"><span>DB write</span><strong>{_s(ar.get('db_last_write','')[:10] or '-')}</strong></div>
        </div>
        <div class="ctrl-box editable-block" data-bid="ctrl-divergencia" data-blabel="Divergencia">
          <div class="ch-box-label">V12 vs V13</div>
          <div class="ch-box-val">{'igual hoy' if div.get('latest_common_equal') else 'divergen hoy'}</div>
          <div class="kl"><span>Fechas distintas</span><strong>{_i(div.get('changed_dates'))}/{_i(div.get('common_dates'))}</strong></div>
        </div>
        <div class="ctrl-box editable-block" data-bid="ctrl-ref" data-blabel="Referencia">
          <div class="ch-box-label">Ref {_s(ref_lbl)}</div>
          <div class="ch-box-val">{_f(ref_eq.get('accuracy_pct'))} / {_f(ref_eq.get('avg_return_pct'),3,True)}</div>
          <div class="kl"><span>Picks</span><strong>{_i(ref_row.get('latest_picks'))}</strong></div>
          <div class="kl"><span>Fecha</span><strong>{_s(ref_row.get('last_date','-'))}</strong></div>
        </div>
      </div>
    </section>

  </div><!-- /row-1-1 -->

  <!-- MODELOS SCANNER ─────────────────────────── -->
  <section class="panel editable-block" data-bid="scanners-panel" data-blabel="Scanners históricos" id="models">
    <div class="panel-head">
      <div>
        <div class="panel-label">Scanners históricos</div>
        <h2 class="panel-title">Familia INVERTIR · Muestra igualada {eq_days} ruedas</h2>
      </div>
    </div>
    <div class="models-grid">{''.join(model_card(r) for r in hist_rows)}</div>
  </section>

  <!-- LEGACY ML ───────────────────────────────── -->
  <section class="panel editable-block" data-bid="legacy-panel" data-blabel="Legacy ML">
    <div class="panel-head">
      <div>
        <div class="panel-label">Legacy ML externos</div>
        <h2 class="panel-title">Modelos ML · Competencia cruzada</h2>
      </div>
    </div>
    <div class="models-grid">{''.join(model_card(r) for r in ml_rows)}</div>
  </section>

  <!-- HEATMAP ─────────────────────────────────── -->
  <section class="panel editable-block" data-bid="heatmap-panel" data-blabel="Heatmap" id="heatmap">
    <div class="panel-head">
      <div>
        <div class="panel-label">Heatmap</div>
        <h2 class="panel-title">Rendimiento por rueda · últimas 15 fechas</h2>
      </div>
    </div>
    {heatmap()}
    <div class="hm-legend">
      <span class="hml pos">Verde = retorno positivo</span>
      <span class="hml neg">Rojo = retorno negativo</span>
      <span class="hml muted-td">– = sin picks esa rueda</span>
    </div>
  </section>

  <!-- OVERLAP MATRIX ──────────────────────────── -->
  <section class="panel editable-block" data-bid="overlap-panel" data-blabel="Overlap matrix">
    <div class="panel-head">
      <div>
        <div class="panel-label">Overlap Jaccard</div>
        <h2 class="panel-title">Diversificación entre modelos · últimas 31 ruedas</h2>
      </div>
    </div>
    {overlap_matrix()}
    <div class="hm-legend"><span class="hml muted-td">Verde oscuro = mayor solapamiento de picks. Ideal: valores bajos fuera de la diagonal.</span></div>
  </section>

  <!-- LIGA COMPLETA ───────────────────────────── -->
  <section class="panel editable-block" data-bid="data-panel" data-blabel="Liga completa" id="data">
    <div class="panel-head">
      <div>
        <div class="panel-label">Data completa</div>
        <h2 class="panel-title">Liga · todos los modelos monitoreados</h2>
      </div>
    </div>
    <div class="tbl-scroll">
      <table class="data-table">
        <thead><tr>
          <th>Modelo</th><th>Estado</th>
          <th>Igualada WR/Ret</th><th>Igualada muestra</th>
          <th>30 ruedas WR/Ret</th><th>30 ruedas muestra</th>
          <th>Picks actuales</th>
        </tr></thead>
        <tbody>{league_full()}</tbody>
      </table>
    </div>
  </section>

  <div class="page-footer">
    Titan Machine Dashboard · generado {_s(payload["generated_at"])} · datos desde SQLite local
  </div>

</div><!-- /main-wrap -->

<!-- EDITOR PANEL ─────────────────────────────── -->
<div class="editor-panel" id="editorPanel" aria-hidden="true">
  <div class="ep-head">
    <div>
      <div class="ep-label">Editor visual</div>
      <div class="ep-title">Personalizar dashboard</div>
    </div>
    <button class="ep-close" id="editorClose">×</button>
  </div>

  <div class="ep-note">
    1 · Hacé clic en cualquier cuadro para seleccionarlo.<br>
    2 · Usá Subir/Bajar para reordenarlo en su sección.<br>
    3 · Doble clic en <em>textos</em> (títulos, labels) para editarlos.<br>
    4 · Los números y métricas vienen de la DB y no se modifican desde aquí.
  </div>

  <div class="ep-section">
    <div class="ep-section-title">Bloque seleccionado</div>
    <div class="ep-selected-name" id="epSelectedName">Ninguno seleccionado</div>
    <div class="ep-row">
      <button class="ep-btn" id="epMoveUp">↑ Subir</button>
      <button class="ep-btn" id="epMoveDown">↓ Bajar</button>
    </div>
    <div class="ep-field">
      <label for="epVisible">Visibilidad</label>
      <select id="epVisible">
        <option value="1">Visible</option>
        <option value="0">Oculto</option>
      </select>
    </div>
    <button class="ep-btn ep-apply" id="epApplyBlock">Aplicar</button>
  </div>

  <div class="ep-section">
    <div class="ep-section-title">Tema de color</div>
    <div class="ep-grid-2">
      <div class="ep-field"><label for="tc-bg">Fondo</label><input id="tc-bg" type="color"></div>
      <div class="ep-field"><label for="tc-panel">Panel</label><input id="tc-panel" type="color"></div>
      <div class="ep-field"><label for="tc-ink">Texto</label><input id="tc-ink" type="color"></div>
      <div class="ep-field"><label for="tc-muted">Muteado</label><input id="tc-muted" type="color"></div>
      <div class="ep-field"><label for="tc-accent">Acento</label><input id="tc-accent" type="color"></div>
      <div class="ep-field"><label for="tc-gold">Dorado</label><input id="tc-gold" type="color"></div>
      <div class="ep-field"><label for="tc-green">Verde</label><input id="tc-green" type="color"></div>
      <div class="ep-field"><label for="tc-rose">Rojo</label><input id="tc-rose" type="color"></div>
    </div>
    <div class="ep-field">
      <label for="tc-radius">Redondeo (px) <span id="radiusVal"></span></label>
      <input id="tc-radius" type="range" min="4" max="28" step="1">
    </div>
    <button class="ep-btn ep-apply" id="epApplyTheme">Aplicar tema</button>
  </div>

  <div class="ep-section">
    <div class="ep-grid-2">
      <button class="ep-btn ep-save" id="epSave">💾 Guardar</button>
      <button class="ep-btn" id="epReset">↺ Resetear</button>
    </div>
    <div class="ep-status" id="epStatus"></div>
  </div>
</div>

<!-- TOOLTIP heatmap -->
<div class="heat-tt" id="heatTT"></div>

<script>
/* ── SIDEBAR TOGGLE ───────────────────────────────────────────────────── */
(function(){{
  const sidebar  = document.getElementById('sidebar');
  const mainWrap = document.getElementById('mainWrap');
  const tab      = document.getElementById('sidebarTab');
  let collapsed  = JSON.parse(localStorage.getItem('titan-sidebar-collapsed') || 'false');

  function applyState(){{
    document.body.classList.toggle('sidebar-collapsed', collapsed);
    tab.textContent = collapsed ? '›' : '‹';
    tab.title       = collapsed ? 'Mostrar menú' : 'Ocultar menú';
  }}

  tab.addEventListener('click', function(){{
    collapsed = !collapsed;
    localStorage.setItem('titan-sidebar-collapsed', JSON.stringify(collapsed));
    applyState();
  }});

  applyState();
}})();

/* ── NAV LINKS: smooth scroll + active ──────────────────────────────── */
document.querySelectorAll('.sn-link').forEach(function(link){{
  link.addEventListener('click', function(){{
    document.querySelectorAll('.sn-link').forEach(function(l){{ l.classList.remove('active'); }});
    link.classList.add('active');
  }});
}});

/* ── HEATMAP TOOLTIP ─────────────────────────────────────────────────── */
(function(){{
  const tt = document.getElementById('heatTT');
  document.querySelectorAll('.hm-table td[title]').forEach(function(cell){{
    cell.addEventListener('mouseenter', function(e){{
      tt.textContent = cell.getAttribute('title');
      tt.classList.add('show');
    }});
    cell.addEventListener('mousemove', function(e){{
      tt.style.left = (e.clientX + 14) + 'px';
      tt.style.top  = (e.clientY - 8) + 'px';
    }});
    cell.addEventListener('mouseleave', function(){{ tt.classList.remove('show'); }});
  }});
}})();

/* ── EDITOR ──────────────────────────────────────────────────────────── */
(function(){{
  const STORE = 'titan-editor-v2';
  let state = loadState();
  let editMode  = false;
  let selectedId = null;

  function loadState(){{
    try {{ return JSON.parse(localStorage.getItem(STORE) || '{{}}'); }}
    catch(e) {{ return {{}}; }}
  }}
  function saveState(){{
    localStorage.setItem(STORE, JSON.stringify(state));
  }}
  function setStatus(msg){{
    const el = document.getElementById('epStatus');
    if(el){{ el.textContent = msg; setTimeout(function(){{ if(el.textContent===msg) el.textContent=''; }}, 2000); }}
  }}

  /* --- restore saved layout & theme on load --- */
  function restoreAll(){{
    applyThemeVars(state.theme || {{}});
    (state.hidden || []).forEach(function(bid){{
      const el = document.querySelector('[data-bid="'+bid+'"]');
      if(el) el.classList.add('block-hidden');
    }});
    Object.entries(state.order || {{}}).forEach(function([containerId, order]){{
      const container = document.querySelector('[data-container="'+containerId+'"]');
      if(!container) return;
      order.forEach(function(bid){{
        const el = document.querySelector('[data-bid="'+bid+'"]');
        if(el && el.parentElement===container) container.appendChild(el);
      }});
    }});
  }}

  /* --- toggle edit mode --- */
  const editBtn = document.getElementById('editModeBtn');
  editBtn.addEventListener('click', function(){{
    editMode = !editMode;
    document.body.classList.toggle('edit-mode', editMode);
    document.getElementById('editorPanel').classList.toggle('ep-open', editMode);
    editBtn.textContent = editMode ? '✓ Salir editor' : '✎ Editar';
  }});
  document.getElementById('editorClose').addEventListener('click', function(){{
    editMode = false;
    document.body.classList.remove('edit-mode');
    document.getElementById('editorPanel').classList.remove('ep-open');
    editBtn.textContent = '✎ Editar';
    deselectAll();
  }});

  /* --- block click (select) in edit mode --- */
  document.querySelectorAll('.editable-block').forEach(function(block){{
    block.addEventListener('click', function(e){{
      if(!editMode) return;
      e.stopPropagation();
      selectBlock(block.dataset.bid);
    }});
  }});

  function selectBlock(bid){{
    deselectAll();
    selectedId = bid;
    const el = document.querySelector('[data-bid="'+bid+'"]');
    if(el){{
      el.classList.add('block-selected');
      const nameEl = document.getElementById('epSelectedName');
      if(nameEl) nameEl.textContent = el.dataset.blabel || bid;
      const visEl = document.getElementById('epVisible');
      if(visEl) visEl.value = el.classList.contains('block-hidden') ? '0' : '1';
    }}
  }}
  function deselectAll(){{
    document.querySelectorAll('.block-selected').forEach(function(el){{ el.classList.remove('block-selected'); }});
    selectedId = null;
    const nameEl = document.getElementById('epSelectedName');
    if(nameEl) nameEl.textContent = 'Ninguno seleccionado';
  }}

  /* --- move up/down --- */
  document.getElementById('epMoveUp').addEventListener('click', function(){{
    if(!selectedId) return;
    const el = document.querySelector('[data-bid="'+selectedId+'"]');
    if(!el) return;
    const prev = el.previousElementSibling;
    if(prev) el.parentNode.insertBefore(el, prev);
  }});
  document.getElementById('epMoveDown').addEventListener('click', function(){{
    if(!selectedId) return;
    const el = document.querySelector('[data-bid="'+selectedId+'"]');
    if(!el) return;
    const next = el.nextElementSibling;
    if(next) el.parentNode.insertBefore(next, el);
  }});

  /* --- apply block visibility --- */
  document.getElementById('epApplyBlock').addEventListener('click', function(){{
    if(!selectedId) return;
    const el = document.querySelector('[data-bid="'+selectedId+'"]');
    if(!el) return;
    const vis = document.getElementById('epVisible').value;
    if(vis === '0') {{
      el.classList.add('block-hidden');
      if(!state.hidden) state.hidden = [];
      if(!state.hidden.includes(selectedId)) state.hidden.push(selectedId);
    }} else {{
      el.classList.remove('block-hidden');
      state.hidden = (state.hidden || []).filter(function(id){{ return id !== selectedId; }});
    }}
    setStatus('Bloque actualizado');
  }});

  /* --- text editing: dblclick on editable-text elements --- */
  document.querySelectorAll('.editable-text').forEach(function(el){{
    el.addEventListener('dblclick', function(e){{
      if(!editMode) return;
      e.stopPropagation();
      el.contentEditable = 'true';
      el.focus();
      el.classList.add('text-editing');
    }});
    el.addEventListener('blur', function(){{
      el.contentEditable = 'false';
      el.classList.remove('text-editing');
      if(!state.texts) state.texts = {{}};
      state.texts[el.dataset.tid || el.className] = el.textContent;
    }});
    el.addEventListener('keydown', function(e){{
      if(e.key === 'Enter' && !e.shiftKey) {{ e.preventDefault(); el.blur(); }}
      if(e.key === 'Escape') {{ el.blur(); }}
    }});
  }});

  /* --- theme vars --- */
  const THEME_MAP = [
    ['tc-bg',    '--bg'],
    ['tc-panel', '--panel'],
    ['tc-ink',   '--ink'],
    ['tc-muted', '--muted'],
    ['tc-accent','--cyan'],
    ['tc-gold',  '--gold'],
    ['tc-green', '--green'],
    ['tc-rose',  '--rose'],
  ];

  function normalizeHex(color){{
    try {{
      const span = document.createElement('span');
      span.style.color = color;
      document.body.appendChild(span);
      const rgb = getComputedStyle(span).color;
      document.body.removeChild(span);
      const m = rgb.match(/\\d+/g);
      if(!m) return '#888888';
      return '#' + m.slice(0,3).map(function(n){{ return parseInt(n).toString(16).padStart(2,'0'); }}).join('');
    }} catch(e) {{ return color; }}
  }}

  function syncThemeInputs(){{
    THEME_MAP.forEach(function(pair){{
      const input = document.getElementById(pair[0]);
      if(!input) return;
      const stored = (state.theme || {{}})[pair[1]];
      const cur = stored || getComputedStyle(document.documentElement).getPropertyValue(pair[1]).trim();
      input.value = normalizeHex(cur);
    }});
    const rInput = document.getElementById('tc-radius');
    const rVal   = document.getElementById('radiusVal');
    if(rInput){{
      const stored = (state.theme || {{}})['--radius'];
      rInput.value = stored ? parseInt(stored) : 16;
      if(rVal) rVal.textContent = rInput.value + 'px';
      rInput.addEventListener('input', function(){{ if(rVal) rVal.textContent = rInput.value + 'px'; }});
    }}
  }}

  function applyThemeVars(theme){{
    Object.entries(theme).forEach(function([k, v]){{
      document.documentElement.style.setProperty(k, v);
    }});
  }}

  document.getElementById('epApplyTheme').addEventListener('click', function(){{
    if(!state.theme) state.theme = {{}};
    THEME_MAP.forEach(function(pair){{
      const input = document.getElementById(pair[0]);
      if(input) state.theme[pair[1]] = input.value;
    }});
    const rInput = document.getElementById('tc-radius');
    if(rInput) state.theme['--radius'] = rInput.value + 'px';
    applyThemeVars(state.theme);
    setStatus('Tema aplicado');
  }});

  document.getElementById('epSave').addEventListener('click', function(){{
    /* save block order for each container */
    state.order = {{}};
    document.querySelectorAll('[data-container]').forEach(function(container){{
      const cid = container.dataset.container;
      state.order[cid] = Array.from(container.querySelectorAll(':scope > .editable-block'))
        .map(function(el){{ return el.dataset.bid; }}).filter(Boolean);
    }});
    saveState();
    setStatus('💾 Guardado');
  }});

  document.getElementById('epReset').addEventListener('click', function(){{
    localStorage.removeItem(STORE);
    state = {{}};
    location.reload();
  }});

  syncThemeInputs();
  restoreAll();
}})();
</script>
</body>
</html>"""


# ── CSS VARIANTES ─────────────────────────────────────────────────────────────

BASE_LAYOUT = """
/* ── RESET & BASE ──────────────────────────────────────── */
*{{box-sizing:border-box;margin:0;padding:0}}
body{{
  font-family:"Aptos","Segoe UI",system-ui,sans-serif;
  color:var(--ink);
  background:var(--bg-gradient);
  min-height:100vh;
  font-size:13px;
  line-height:1.5;
}}

/* ── LAYOUT ─────────────────────────────────────────────── */
body{{display:flex;min-height:100vh}}

/* SIDEBAR */
.sidebar{{
  width:var(--sidebar-w);
  min-width:var(--sidebar-w);
  height:100vh;
  position:sticky;
  top:0;
  display:flex;
  flex-direction:column;
  background:var(--sidebar-bg);
  border-right:1px solid var(--line);
  transition:width .25s ease, min-width .25s ease;
  overflow:hidden;
  z-index:10;
  flex-shrink:0;
}}
.sidebar-inner{{
  flex:1;
  overflow-y:auto;
  padding:18px 14px 24px 14px;
  display:flex;
  flex-direction:column;
  gap:4px;
  scrollbar-width:thin;
  scrollbar-color:rgba(255,255,255,0.10) transparent;
}}

/* Sidebar tab — botón de colapso pegado al borde derecho */
.sidebar-tab{{
  position:absolute;
  top:50%;
  right:-14px;
  transform:translateY(-50%);
  width:28px;
  height:52px;
  border:1px solid var(--line);
  border-left:none;
  border-radius:0 10px 10px 0;
  background:var(--sidebar-bg);
  color:var(--cyan);
  cursor:pointer;
  font-size:14px;
  font-weight:900;
  display:flex;
  align-items:center;
  justify-content:center;
  z-index:20;
  transition:background .15s;
}}
.sidebar-tab:hover{{background:var(--panel-hover)}}

body.sidebar-collapsed .sidebar{{
  width:0;
  min-width:0;
}}
body.sidebar-collapsed .sidebar-tab{{
  border-radius:0 10px 10px 0;
  right:-28px;
}}

/* MAIN WRAP */
.main-wrap{{
  flex:1;
  min-width:0;
  display:flex;
  flex-direction:column;
  gap:var(--gap);
  padding:var(--page-pad);
  overflow-x:hidden;
}}

/* ── TOPBAR ──────────────────────────────────────────────── */
.topbar{{
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:var(--radius);
  padding:14px 18px;
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:16px;
  flex-wrap:wrap;
  box-shadow:var(--shadow);
}}
.tb-title{{
  font-family:var(--font-title);
  font-size:20px;
  font-weight:800;
  letter-spacing:-.03em;
}}
.tb-meta{{display:flex;flex-wrap:wrap;gap:8px;margin-top:5px}}
.tb-pill{{
  display:inline-flex;align-items:center;
  padding:4px 9px;border-radius:999px;
  background:rgba(255,255,255,0.05);border:1px solid var(--line);
  font-size:11px;color:var(--muted);
}}
.tb-pill-regime.regime-peligro{{background:rgba(245,184,51,0.12);border-color:rgba(245,184,51,0.25);color:#f5b833}}
.tb-pill-regime.regime-seguro{{background:rgba(68,232,144,0.12);border-color:rgba(68,232,144,0.25);color:#44e890}}
.tb-pill-regime.regime-global{{background:rgba(100,160,220,0.12);border-color:rgba(100,160,220,0.20);color:#7ab8dc}}
.tb-right{{display:flex;align-items:center;gap:10px}}
.tb-btn{{
  display:inline-flex;align-items:center;text-decoration:none;
  padding:8px 14px;border-radius:999px;
  background:linear-gradient(135deg,var(--cyan),var(--cyan-2));
  color:#020c08;font-weight:800;font-size:12px;border:none;cursor:pointer;
}}
.tb-ghost{{background:rgba(255,255,255,0.05);border:1px solid var(--line);color:var(--ink)}}
.tb-edit-btn{{
  display:inline-flex;align-items:center;gap:6px;
  padding:8px 14px;border-radius:999px;border:1px solid rgba(255,255,255,0.10);
  background:rgba(255,255,255,0.05);color:var(--ink);cursor:pointer;
  font-weight:700;font-size:12px;transition:background .15s;
}}
.tb-edit-btn:hover{{background:rgba(255,255,255,0.09)}}

/* ── KPI STRIP ───────────────────────────────────────────── */
.kpi-strip{{
  display:grid;
  grid-template-columns:repeat(6,minmax(0,1fr));
  gap:var(--gap);
}}
.kpi-card{{
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:var(--radius);
  padding:12px 14px;
  box-shadow:var(--shadow);
  transition:transform .12s;
}}
.kpi-card:hover{{transform:translateY(-2px)}}
.kc-label{{font-size:10px;text-transform:uppercase;letter-spacing:.16em;color:var(--muted);font-weight:700}}
.kc-value{{font-size:22px;font-weight:800;letter-spacing:-.03em;margin-top:5px;line-height:1.05}}
.kc-sub{{font-size:11px;color:var(--muted);margin-top:4px;line-height:1.35}}
.accent-cyan{{border-top:2px solid var(--cyan);background:var(--accent-cyan-bg)}}
.accent-gold{{border-top:2px solid var(--gold);background:var(--accent-gold-bg)}}
.accent-green{{border-top:2px solid var(--green);background:var(--accent-green-bg)}}
.accent-rose{{border-top:2px solid var(--rose);background:var(--accent-rose-bg)}}

/* ── PANELS ──────────────────────────────────────────────── */
.panel{{
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:var(--radius);
  padding:16px 18px;
  box-shadow:var(--shadow);
}}
.panel-label{{font-size:10px;text-transform:uppercase;letter-spacing:.16em;color:var(--cyan);font-weight:800}}
.panel-title{{font-family:var(--font-title);font-size:18px;letter-spacing:-.03em;margin-top:3px}}
.panel-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:14px;flex-wrap:wrap}}
.head-badges{{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding-top:4px}}

/* ── GRIDS ───────────────────────────────────────────────── */
.row-2-3{{
  display:grid;
  grid-template-columns:5fr 7fr;
  gap:var(--gap);
  align-items:start;
}}
.row-1-1{{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:var(--gap);
  align-items:start;
}}
.models-grid{{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
  gap:var(--gap);
  margin-top:4px;
}}

/* ── CHAMPION ────────────────────────────────────────────── */
.ch-curve{{margin:4px 0 14px 0}}
.ch-grid{{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:10px;
}}
.ch-box{{
  background:var(--inset);
  border:1px solid var(--line);
  border-radius:calc(var(--radius) - 6px);
  padding:10px 12px;
}}
.ch-box-label{{font-size:9px;text-transform:uppercase;letter-spacing:.14em;color:var(--muted);font-weight:700;margin-bottom:4px}}
.ch-box-val{{font-size:14px;font-weight:800;margin-bottom:6px}}

/* ── LIGA ────────────────────────────────────────────────── */
.leader-strip{{
  display:flex;justify-content:space-between;align-items:center;gap:12px;
  background:var(--inset);border:1px solid var(--line);
  border-radius:calc(var(--radius)-4px);
  padding:10px 14px;
  margin-bottom:14px;
}}
.ls-version{{font-size:18px;font-weight:800;letter-spacing:-.02em}}
.ls-sub{{font-size:11px;color:var(--muted);margin-top:3px}}
.ls-spark{{flex-shrink:0}}

/* ── CONTROL ─────────────────────────────────────────────── */
.ctrl-grid{{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:10px;
}}
.ctrl-box{{
  background:var(--inset);
  border:1px solid var(--line);
  border-radius:calc(var(--radius) - 6px);
  padding:10px 12px;
}}

/* ── MODEL CARD ──────────────────────────────────────────── */
.model-card{{
  background:var(--panel-2);
  border:1px solid var(--line);
  border-radius:var(--radius);
  padding:12px 13px;
  box-shadow:var(--shadow);
  display:flex;
  flex-direction:column;
  gap:8px;
}}
.mc-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap}}
.mc-title{{font-size:16px;font-weight:800;letter-spacing:-.02em}}
.mc-badges{{display:flex;flex-wrap:wrap;gap:5px;align-items:center;margin-top:2px}}
.mc-rank{{margin-left:auto;flex-shrink:0}}
.mc-spark{{margin:2px 0}}
.mc-kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:5px}}
.mk{{
  background:var(--inset);
  border:1px solid var(--line);
  border-radius:8px;
  padding:6px 7px;
  text-align:center;
}}
.mk span{{display:block;font-size:9px;text-transform:uppercase;letter-spacing:.10em;color:var(--muted);font-weight:700}}
.mk strong{{display:block;font-size:12px;font-weight:800;margin-top:3px;line-height:1.1}}
.mc-tickers{{font-size:11px;color:var(--muted);line-height:1.45}}
.mc-detail{{margin-top:2px;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--inset)}}
.mc-detail summary{{list-style:none;cursor:pointer;padding:8px 11px;font-weight:700;font-size:11px;color:var(--muted)}}
.mc-detail summary::-webkit-details-marker{{display:none}}
.mc-detail-body{{padding:0 11px 11px 11px}}

/* ── HEATMAP ─────────────────────────────────────────────── */
.hm-table{{width:100%;border-collapse:separate;border-spacing:3px;table-layout:fixed}}
.hm-table th{{font-size:9px;text-transform:uppercase;letter-spacing:.10em;color:var(--muted);padding:0 2px 5px 2px;text-align:center}}
.hm-table td{{padding:6px 3px;border-radius:6px;text-align:center;font-size:11px;font-weight:800;cursor:help;transition:opacity .12s}}
.hm-table td:hover{{opacity:.8}}
.hm-label{{background:none!important;border:none!important;text-align:left!important;padding-left:0!important;font-size:11px;min-width:80px;white-space:nowrap}}
.hm-legend{{display:flex;gap:16px;margin-top:10px;font-size:11px}}
.hml{{padding:3px 8px;border-radius:4px}}
.hml.pos{{background:rgba(68,232,144,0.14);color:#44e890}}
.hml.neg{{background:rgba(252,92,125,0.14);color:#fc5c7d}}

/* ── OVERLAP MATRIX ──────────────────────────────────────── */
.om-table{{width:100%;border-collapse:separate;border-spacing:4px;table-layout:fixed}}
.om-table th{{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;text-align:center}}
.om-table td{{text-align:center;padding:9px 4px;border-radius:7px;font-weight:800;font-size:11px}}
.om-label{{background:none!important;text-align:left!important;padding-left:0!important;font-size:11px}}

/* ── TABLES ──────────────────────────────────────────────── */
.data-table{{width:100%;border-collapse:collapse;font-size:12px}}
.data-table th,.data-table td{{padding:8px 7px;border-top:1px solid var(--line);text-align:left;vertical-align:middle}}
.data-table thead th{{border-top:none;font-size:10px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);padding-bottom:8px}}
.data-table tbody tr:hover{{background:rgba(255,255,255,0.025)}}
.tbl-scroll{{overflow-x:auto}}
.muted-td{{color:var(--muted)}}
.ticker-list{{max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font-size:11px}}

/* ── SIDEBAR ELEMENTS ────────────────────────────────────── */
.brand-block{{padding:2px 0 14px 0;border-bottom:1px solid var(--line)}}
.brand-name{{font-family:var(--font-title);font-size:20px;font-weight:800;letter-spacing:-.03em;color:var(--ink)}}
.brand-sub{{font-size:10px;text-transform:uppercase;letter-spacing:.18em;color:var(--muted);margin-top:4px}}

.regime-pill{{
  display:flex;align-items:center;gap:8px;
  padding:8px 10px;border-radius:10px;
  background:var(--inset);border:1px solid var(--line);
  font-size:12px;font-weight:700;
  margin:10px 0;
}}
.regime-pill.regime-peligro{{border-color:rgba(245,184,51,0.25);color:#f5b833}}
.regime-pill.regime-seguro{{border-color:rgba(68,232,144,0.25);color:#44e890}}
.regime-pill.regime-global{{border-color:rgba(100,160,220,0.20);color:#7ab8dc}}
.rp-dot{{width:7px;height:7px;border-radius:50%;background:currentColor;flex-shrink:0}}
.rp-breadth{{font-size:10px;color:var(--muted);margin-left:auto}}

.side-nav{{display:flex;flex-direction:column;gap:4px;margin:6px 0 10px 0}}
.sn-link{{
  display:flex;align-items:center;gap:9px;text-decoration:none;
  padding:9px 10px;border-radius:10px;border:1px solid transparent;
  color:var(--muted);font-weight:600;font-size:13px;transition:all .15s;
}}
.sn-link:hover{{background:rgba(255,255,255,0.04);border-color:var(--line);color:var(--ink)}}
.sn-link.active{{background:rgba(24,232,200,0.12);border-color:rgba(24,232,200,0.22);color:var(--cyan)}}
.sn-icon{{font-size:14px;width:18px;text-align:center;flex-shrink:0}}
.sn-tag{{margin-left:auto;font-size:10px;font-weight:800;color:var(--muted)}}
.sn-link.active .sn-tag{{color:var(--cyan)}}

.side-section-label{{font-size:10px;text-transform:uppercase;letter-spacing:.16em;color:var(--muted);font-weight:700;padding:8px 2px 4px 2px}}
.side-views{{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px}}
.sv-btn{{
  display:flex;align-items:center;justify-content:center;text-decoration:none;
  padding:8px;border-radius:8px;border:1px solid var(--line);
  background:rgba(255,255,255,0.03);color:var(--muted);font-size:12px;font-weight:700;
  transition:background .15s;
}}
.sv-btn:hover{{background:rgba(255,255,255,0.07);color:var(--ink)}}

.side-drawer{{
  border:1px solid var(--line);border-radius:10px;
  overflow:hidden;margin-bottom:6px;background:rgba(255,255,255,0.02);
}}
.side-drawer summary{{list-style:none;cursor:pointer;padding:9px 12px;font-weight:700;font-size:12px;color:var(--muted)}}
.side-drawer summary::-webkit-details-marker{{display:none}}
.side-drawer summary:hover{{color:var(--ink)}}
.sd-body{{padding:0 12px 12px 12px;font-size:11px;color:var(--muted);line-height:1.6}}
.sd-body code{{background:rgba(255,255,255,0.07);padding:1px 4px;border-radius:3px;font-size:10px}}

/* ── SMALL UTILITIES ─────────────────────────────────────── */
.kl{{display:flex;justify-content:space-between;gap:10px;padding:4px 0;border-top:1px solid rgba(255,255,255,0.05);font-size:11px;color:var(--muted)}}
.kl:first-child{{border-top:none;padding-top:0}}
.kl strong{{color:var(--ink);font-weight:700}}
.rank-num{{
  display:inline-flex;align-items:center;justify-content:center;
  min-width:22px;height:22px;border-radius:999px;
  background:rgba(24,232,200,0.14);color:var(--cyan);
  font-size:11px;font-weight:800;
}}
.badge{{display:inline-flex;align-items:center;padding:2px 7px;border-radius:999px;font-size:9px;text-transform:uppercase;letter-spacing:.08em;font-weight:800}}
.ba-active{{background:rgba(24,232,200,0.14);color:#18e8c8}}
.ba-ref{{background:rgba(245,184,51,0.14);color:#f5b833}}
.ba-base{{background:rgba(255,255,255,0.09);color:#b0c8d8}}
.ba-obs{{background:rgba(68,232,144,0.14);color:#44e890}}
.ba-ml{{background:rgba(168,130,255,0.14);color:#a882ff}}
.ba-fresh{{background:rgba(68,232,144,0.14);color:#44e890}}
.ba-warn{{background:rgba(245,184,51,0.14);color:#f5b833}}
.ba-stale{{background:rgba(252,92,125,0.14);color:#fc5c7d}}
.ba-muted{{background:rgba(255,255,255,0.07);color:#6080a0}}
.pos{{color:#44e890}}
.neg{{color:#fc5c7d}}
.spark{{display:block;width:100%;height:auto}}

/* ── EDITOR PANEL ────────────────────────────────────────── */
.editor-panel{{
  position:fixed;right:-360px;top:0;bottom:0;width:340px;z-index:100;
  background:var(--sidebar-bg);border-left:1px solid var(--line);
  box-shadow:-8px 0 30px rgba(0,0,0,0.4);
  overflow-y:auto;padding:20px 18px;
  transition:right .25s ease;
  scrollbar-width:thin;
}}
.editor-panel.ep-open{{right:0}}
.ep-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:16px}}
.ep-label{{font-size:10px;text-transform:uppercase;letter-spacing:.16em;color:var(--cyan);font-weight:800}}
.ep-title{{font-size:20px;font-weight:800;margin-top:2px}}
.ep-close{{
  border:1px solid var(--line);background:rgba(255,255,255,0.05);
  color:var(--ink);border-radius:999px;width:32px;height:32px;
  cursor:pointer;font-size:18px;font-weight:800;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
}}
.ep-note{{
  background:var(--inset);border:1px solid var(--line);border-radius:10px;
  padding:12px 14px;font-size:11px;color:var(--muted);line-height:1.6;margin-bottom:14px;
}}
.ep-section{{
  background:rgba(255,255,255,0.03);border:1px solid var(--line);
  border-radius:12px;padding:13px;margin-bottom:12px;
}}
.ep-section-title{{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-weight:800;margin-bottom:10px}}
.ep-selected-name{{font-size:15px;font-weight:800;margin-bottom:10px;min-height:22px}}
.ep-row{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}}
.ep-grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
.ep-field{{display:flex;flex-direction:column;gap:4px;margin-bottom:8px}}
.ep-field label{{font-size:10px;text-transform:uppercase;letter-spacing:.10em;color:var(--muted);font-weight:800}}
.ep-field input,.ep-field select{{
  width:100%;border-radius:8px;border:1px solid var(--line);
  background:rgba(255,255,255,0.04);color:var(--ink);
  padding:8px 10px;font:inherit;font-size:12px;
}}
.ep-field input[type="color"]{{padding:3px;height:38px}}
.ep-field input[type="range"]{{padding:4px 0}}
.ep-btn{{
  display:flex;align-items:center;justify-content:center;
  border:1px solid var(--line);border-radius:8px;
  padding:9px 12px;cursor:pointer;font-weight:800;font-size:12px;
  background:rgba(255,255,255,0.05);color:var(--ink);width:100%;margin-bottom:8px;
}}
.ep-btn:hover{{background:rgba(255,255,255,0.09)}}
.ep-apply{{background:rgba(24,232,200,0.14)!important;color:var(--cyan)!important}}
.ep-save{{background:rgba(68,232,144,0.14)!important;color:#44e890!important;margin-bottom:0}}
.ep-status{{font-size:11px;color:var(--cyan);font-weight:800;min-height:18px;margin-top:8px;text-align:center}}

/* ── EDITOR EDIT-MODE STATES ─────────────────────────────── */
.editable-block{{position:relative;transition:outline .12s}}
body.edit-mode .editable-block:not(.block-selected){{outline:1px dashed rgba(24,232,200,0.18)}}
body.edit-mode .editable-block:not(.block-selected):hover{{outline-color:rgba(24,232,200,0.45);cursor:pointer}}
.block-selected{{outline:2px solid var(--cyan)!important;box-shadow:0 0 0 3px rgba(24,232,200,0.12)!important}}
.block-hidden{{display:none!important}}
.editable-text{{transition:background .12s}}
body.edit-mode .editable-text{{cursor:text}}
.text-editing{{
  contenteditable:true;
  outline:none;
  background:rgba(24,232,200,0.07)!important;
  border-radius:4px;
  padding:1px 3px;
  box-shadow:inset 0 -2px 0 var(--cyan);
}}

/* ── HEAT TOOLTIP ────────────────────────────────────────── */
.heat-tt{{
  position:fixed;z-index:200;max-width:280px;
  padding:9px 12px;border-radius:10px;
  background:rgba(4,8,16,0.97);border:1px solid rgba(24,232,200,0.16);
  color:var(--ink);font-size:11px;line-height:1.45;
  pointer-events:none;opacity:0;white-space:pre-line;
  transition:opacity .08s ease;
}}
.heat-tt.show{{opacity:1}}

/* ── PAGE FOOTER ─────────────────────────────────────────── */
.page-footer{{
  text-align:center;font-size:11px;color:var(--muted);
  padding:16px 0 8px 0;border-top:1px solid var(--line);
  margin-top:4px;
}}

/* ── RESPONSIVE ──────────────────────────────────────────── */
@media(max-width:1440px){{
  .row-2-3{{grid-template-columns:1fr 1fr}}
  .kpi-strip{{grid-template-columns:repeat(3,1fr)}}
}}
@media(max-width:1100px){{
  .row-2-3,.row-1-1{{grid-template-columns:1fr}}
  .kpi-strip{{grid-template-columns:repeat(2,1fr)}}
  .models-grid{{grid-template-columns:repeat(2,1fr)}}
}}
@media(max-width:760px){{
  .kpi-strip{{grid-template-columns:1fr 1fr}}
  .models-grid,.ch-grid,.ctrl-grid{{grid-template-columns:1fr}}
  .mc-kpis{{grid-template-columns:repeat(2,1fr)}}
}}
"""

# ── Variante C1: Aurora Pro (tipografía Georgia, colores cálidos) ─────────────
CSS_C1 = BASE_LAYOUT + """
:root{{
  --bg:#050810;
  --bg-gradient:radial-gradient(circle at 75% 0%,rgba(24,232,200,0.10),transparent 22%),radial-gradient(circle at 8% 35%,rgba(168,130,255,0.08),transparent 20%),linear-gradient(180deg,#070b16 0%,#040710 100%);
  --sidebar-bg:linear-gradient(160deg,rgba(8,16,30,0.99) 0%,rgba(4,8,18,0.99) 100%);
  --panel:linear-gradient(180deg,rgba(14,24,42,0.99) 0%,rgba(8,14,26,0.99) 100%);
  --panel-2:linear-gradient(180deg,rgba(11,20,36,0.99) 0%,rgba(7,12,22,0.99) 100%);
  --panel-hover:rgba(14,24,42,0.99);
  --inset:rgba(255,255,255,0.035);
  --ink:#eef4fb;
  --muted:#6585a8;
  --line:rgba(130,180,230,0.11);
  --cyan:#18e8c8;
  --cyan-2:#3af5c0;
  --gold:#f5b833;
  --green:#44e890;
  --rose:#fc5c7d;
  --violet:#a882ff;
  --shadow:0 16px 44px rgba(0,0,0,0.50);
  --radius:16px;
  --sidebar-w:260px;
  --gap:13px;
  --page-pad:13px 16px 20px 16px;
  --font-title:"Georgia","Times New Roman",serif;
  --accent-cyan-bg:linear-gradient(180deg,rgba(24,232,200,0.12) 0%,rgba(14,24,42,0.99) 100%);
  --accent-gold-bg:linear-gradient(180deg,rgba(245,184,51,0.12) 0%,rgba(14,24,42,0.99) 100%);
  --accent-green-bg:linear-gradient(180deg,rgba(68,232,144,0.12) 0%,rgba(14,24,42,0.99) 100%);
  --accent-rose-bg:linear-gradient(180deg,rgba(252,92,125,0.12) 0%,rgba(14,24,42,0.99) 100%);
}}
"""

# ── Variante C2: Aurora Dense (compacta, monospace, máxima info) ──────────────
CSS_C2 = BASE_LAYOUT + """
:root{{
  --bg:#06090f;
  --bg-gradient:radial-gradient(circle at 85% 5%,rgba(0,212,255,0.09),transparent 20%),radial-gradient(circle at 5% 40%,rgba(0,230,118,0.06),transparent 18%),#06090f;
  --sidebar-bg:rgba(4,6,12,0.99);
  --panel:rgba(10,15,24,0.99);
  --panel-2:rgba(8,13,21,0.99);
  --panel-hover:rgba(12,18,28,0.99);
  --inset:rgba(255,255,255,0.03);
  --ink:#d8eaf5;
  --muted:#4e6a80;
  --line:rgba(80,140,200,0.10);
  --cyan:#00d4ff;
  --cyan-2:#18ecd8;
  --gold:#ffc107;
  --green:#00e676;
  --rose:#ff5252;
  --violet:#9c60ff;
  --shadow:0 8px 24px rgba(0,0,0,0.60);
  --radius:8px;
  --sidebar-w:230px;
  --gap:9px;
  --page-pad:9px 12px 16px 12px;
  --font-title:"Consolas","JetBrains Mono","Cascadia Code",monospace;
  --accent-cyan-bg:rgba(0,212,255,0.07);
  --accent-gold-bg:rgba(255,193,7,0.07);
  --accent-green-bg:rgba(0,230,118,0.07);
  --accent-rose-bg:rgba(255,82,82,0.07);
}}
body{{font-size:12px}}
.kc-value{{font-size:18px}}
.panel-title{{font-size:15px}}
.tb-title{{font-size:17px}}
.ls-version{{font-size:15px}}
.mc-title{{font-size:14px}}
.sidebar-tab{{border-radius:0 6px 6px 0}}
.brand-name{{font-size:17px}}
.panel,.kpi-card,.model-card,.ch-box,.ctrl-box{{border-radius:var(--radius)!important}}
.rank-num{{border-radius:4px}}
.badge{{border-radius:3px}}
.sn-link{{border-radius:6px}}
.side-drawer{{border-radius:6px}}
.mc-detail{{border-radius:6px}}
.mk{{border-radius:5px}}
.accent-cyan,.accent-gold,.accent-green,.accent-rose{{border-top-width:3px}}
"""

# ── Variante C3: Aurora Card (más espaciada, tarjetas con glow, tipografía grande) ──
CSS_C3 = BASE_LAYOUT + """
:root{{
  --bg:#030610;
  --bg-gradient:
    radial-gradient(ellipse at 80% 0%,rgba(24,232,200,0.16),transparent 28%),
    radial-gradient(ellipse at 0% 60%,rgba(168,130,255,0.12),transparent 25%),
    radial-gradient(ellipse at 50% 100%,rgba(245,184,51,0.08),transparent 25%),
    linear-gradient(180deg,#050a1a 0%,#020510 100%);
  --sidebar-bg:linear-gradient(170deg,rgba(6,12,28,0.99) 0%,rgba(2,5,12,0.99) 100%);
  --panel:linear-gradient(180deg,rgba(12,22,42,0.99) 0%,rgba(7,13,27,0.99) 100%);
  --panel-2:linear-gradient(180deg,rgba(9,18,34,0.99) 0%,rgba(5,10,20,0.99) 100%);
  --panel-hover:rgba(12,22,42,0.99);
  --inset:rgba(24,232,200,0.04);
  --ink:#f0f6fc;
  --muted:#5a80a8;
  --line:rgba(24,232,200,0.10);
  --cyan:#18e8c8;
  --cyan-2:#3af5c0;
  --gold:#f5b833;
  --green:#44e890;
  --rose:#fc5c7d;
  --violet:#a882ff;
  --shadow:0 20px 60px rgba(0,0,0,0.55),0 0 0 1px rgba(24,232,200,0.04);
  --radius:20px;
  --sidebar-w:270px;
  --gap:15px;
  --page-pad:15px 18px 24px 18px;
  --font-title:"Georgia","Times New Roman",serif;
  --accent-cyan-bg:linear-gradient(135deg,rgba(24,232,200,0.15) 0%,rgba(12,22,42,0.99) 100%);
  --accent-gold-bg:linear-gradient(135deg,rgba(245,184,51,0.15) 0%,rgba(12,22,42,0.99) 100%);
  --accent-green-bg:linear-gradient(135deg,rgba(68,232,144,0.15) 0%,rgba(12,22,42,0.99) 100%);
  --accent-rose-bg:linear-gradient(135deg,rgba(252,92,125,0.15) 0%,rgba(12,22,42,0.99) 100%);
}}
/* glows en cards activas */
.accent-cyan{{box-shadow:0 0 30px rgba(24,232,200,0.12),var(--shadow)!important}}
.accent-gold{{box-shadow:0 0 30px rgba(245,184,51,0.12),var(--shadow)!important}}
.accent-green{{box-shadow:0 0 30px rgba(68,232,144,0.12),var(--shadow)!important}}
.accent-rose{{box-shadow:0 0 30px rgba(252,92,125,0.12),var(--shadow)!important}}
/* sidebar con borde glowing */
.sidebar{{border-right:1px solid rgba(24,232,200,0.12);box-shadow:2px 0 30px rgba(24,232,200,0.06)}}
.sidebar-tab{{border-color:rgba(24,232,200,0.20)}}
/* topbar mayor */
.topbar{{padding:16px 20px}}
.tb-title{{font-size:22px}}
/* kpi cards más altas */
.kpi-card{{padding:14px 16px}}
.kc-value{{font-size:26px}}
/* panels */
.panel{{padding:18px 20px}}
.panel-title{{font-size:20px}}
/* model cards con glow sutil */
.model-card{{box-shadow:0 0 20px rgba(0,0,0,0.40),0 0 0 1px rgba(255,255,255,0.04)}}
"""

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import analisis.generar_tablero_maquina_pensante as gen
    print("Generando payload con datos reales...")
    payload = gen.build_dashboard_payload()
    ensure_dashboard_dir()
    print("Renderizando variantes...")
    for letter, name, css, path in [
        ("C1", "Aurora Pro   (Georgia, gradientes cálidos)", CSS_C1, AURORA_PRO_HTML),
        ("C2", "Aurora Dense (monospace, ultra-compacta)",   CSS_C2, OUTPUT_DIR / "preview_c2_dense.html"),
        ("C3", "Aurora Card  (espaciada, glows, tipografía grande)", CSS_C3, OUTPUT_DIR / "preview_c3_card.html"),
    ]:
        html = render_html(payload, css)
        path.write_text(html, encoding="utf-8")
        print(f"  [{letter}] {name} -> {path.relative_to(ROOT)}")
    print("\nAbri los 3 archivos y decime cuál preferís (C1, C2 o C3).")
    print("Luego integro ese diseño al generador principal.")
