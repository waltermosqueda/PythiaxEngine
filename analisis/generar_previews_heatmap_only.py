#!/usr/bin/env python3
"""
Previews exclusivas de heatmap para elegir estilo visual sin tocar el dashboard general.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from generar_previews_finales import (
    OUTPUT_DIR,
    ROLE_LABELS,
    extract_dates,
    fmt_int,
    fmt_pct,
    freshness_badge,
    load_payload,
    model_status,
    normalize_models,
    role_badge,
    safe,
    short_date,
)


OUTPUTS = {
    "index": OUTPUT_DIR / "preview_h_index.html",
    "h1": OUTPUT_DIR / "preview_h1_classic_full.html",
    "h2": OUTPUT_DIR / "preview_h2_families_compact.html",
    "h3": OUTPUT_DIR / "preview_h3_dense_matrix.html",
    "h4": OUTPUT_DIR / "preview_h4_ribbon_cards.html",
    "h5": OUTPUT_DIR / "preview_h5_week_blocks.html",
    "h6": OUTPUT_DIR / "preview_h6_champion_focus.html",
    "h7": OUTPUT_DIR / "preview_h7_day_columns.html",
    "h8": OUTPUT_DIR / "preview_h8_split_deck.html",
    "h9": OUTPUT_DIR / "preview_h9_mini_calendars.html",
    "h10": OUTPUT_DIR / "preview_h10_terminal_heat.html",
}

VARIANTS = {
    "h1": ("Classic Full", "Heatmap total con colores de retorno y KPI fijos."),
    "h2": ("Families Compact", "Tres heatmaps por familia, compactos y mas legibles."),
    "h3": ("Dense Matrix", "Matriz ultra densa con prioridad total de espacio."),
    "h4": ("Ribbon Cards", "Una tarjeta por modelo con calendario horizontal deslizable."),
    "h5": ("Week Blocks", "Bloques por semana/segmento para lectura progresiva."),
    "h6": ("Champion Focus", "Champion y referencia anclados arriba, resto abajo."),
    "h7": ("Day Columns", "Vista inversa: por rueda, con modelos dentro de cada dia."),
    "h8": ("Split Deck", "Productivos y legacy separados en dos tableros compactos."),
    "h9": ("Mini Calendars", "Mini calendarios densos con KPIs en cabecera."),
    "h10": ("Terminal Heat", "Vista terminal profesional con cromatica fuerte."),
}


def split_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {"Productivos": [], "Scanners observados": [], "Legacy ML externos": []}
    for row in rows:
        groups.setdefault(str(row["role_group"]), []).append(row)
    return groups


def cell_theme(status: dict[str, Any]) -> tuple[str, str]:
    kind = str(status["kind"])
    if kind == "active":
        ret = float(status.get("ret") or 0.0)
        intensity = min(abs(ret) / 6.0, 1.0)
        if ret >= 0:
            bg = f"rgba(31, 191, 115, {0.14 + intensity * 0.52:.3f})"
            border = f"rgba(123, 244, 180, {0.22 + intensity * 0.44:.3f})"
            ink = "#f3fff9" if intensity > 0.32 else "#d8f8e7"
        else:
            bg = f"rgba(220, 72, 72, {0.14 + intensity * 0.56:.3f})"
            border = f"rgba(255, 156, 156, {0.22 + intensity * 0.42:.3f})"
            ink = "#fff1f1" if intensity > 0.32 else "#ffd4d4"
        return f"background:{bg};border:1px solid {border};color:{ink};", f"{ret:+.1f}"
    if kind == "nopick":
        return "background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.07);color:#95a4b8;", "NP"
    if kind == "stale":
        return "background:repeating-linear-gradient(135deg, rgba(242,192,87,0.18), rgba(242,192,87,0.18) 6px, rgba(255,255,255,0.03) 6px, rgba(255,255,255,0.03) 12px);border:1px solid rgba(242,192,87,0.22);color:#f3d48a;", "ST"
    return "background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.05);color:#6f8096;", "--"


def nav(active_key: str) -> str:
    items = []
    for key, (title, desc) in VARIANTS.items():
        cls = "tab active" if key == active_key else "tab"
        items.append(f"<a class='{cls}' href='{safe(OUTPUTS[key].name)}' title='{safe(desc)}'>{safe(title)}</a>")
    return f"<nav class='tabs'>{''.join(items)}</nav>"


def header(payload: dict[str, Any], active_key: str) -> str:
    integrity = payload["integrity"]
    date_from = short_date(extract_dates(payload, normalize_models(payload))[0])
    date_to = short_date(extract_dates(payload, normalize_models(payload))[-1])
    return (
        "<header class='hero'>"
        "<div>"
        "<div class='eyebrow'>Heatmap Lab</div>"
        "<h1>Previews enfocadas solo en el heatmap</h1>"
        f"<p>Sin tocar el dashboard general. Ventana actual: {safe(date_from)} a {safe(date_to)} | mercado {safe(integrity['latest_market_date'])}</p>"
        "</div>"
        "<div class='hero-kpis'>"
        f"<div class='kpi'><span>Modelos</span><strong>{fmt_int(12)}</strong></div>"
        f"<div class='kpi'><span>Predictions</span><strong>{fmt_int(integrity['predictions_count'])}</strong></div>"
        f"<div class='kpi'><span>Outcomes</span><strong>{fmt_int(integrity['outcomes_count'])}</strong></div>"
        f"<div class='kpi'><span>Snapshot</span><strong>{safe(payload['generated_at'][11:16])}</strong></div>"
        "</div>"
        "</header>"
        f"{nav(active_key)}"
    )


def shell(title: str, body: str, payload: dict[str, Any], active_key: str, extra_class: str = "") -> str:
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe(title)}</title>
  <style>{css()}</style>
</head>
<body class="{safe(extra_class)}">
  <main class="shell">
    {header(payload, active_key)}
    {body}
  </main>
  <div id="tip" class="tip"></div>
  <script>{tooltip_js()}</script>
</body>
</html>"""


def table_heatmap(rows: list[dict[str, Any]], dates: list[str], title: str, compact: bool = False) -> str:
    head_dates = "".join(f"<th>{safe(short_date(date_text))}</th>" for date_text in dates)
    body = []
    for row in rows:
        eq = row["eq"]
        cells = [
            "<th class='sticky model-col'>"
            f"<div class='model-name'>{safe(row['version'])}</div>"
            f"<div class='model-meta'>{role_badge(str(row['role']))}{freshness_badge(row.get('stale_market_days'))}</div>"
            "</th>",
            f"<td class='metric-col'>{fmt_pct(eq.get('accuracy_pct'))}</td>",
            f"<td class='metric-col'>{fmt_pct(eq.get('avg_return_pct'), 3, True)}</td>",
            f"<td class='metric-col'>{fmt_int(eq.get('hits'))}/{fmt_int(eq.get('evaluated'))}</td>",
        ]
        for date_text in dates:
            status = model_status(row, date_text)
            style, text = cell_theme(status)
            cells.append(
                f"<td class='heat {('compact' if compact else '')}' style='{style}' data-tip='{safe(status['title'])}' title='{safe(status['title'])}'>{safe(text)}</td>"
            )
        body.append(f"<tr>{''.join(cells)}</tr>")
    return (
        "<section class='panel'>"
        f"<div class='panel-head'><div><div class='eyebrow'>Heatmap</div><h2>{safe(title)}</h2></div></div>"
        "<div class='scroll heat-scroll'>"
        "<table class='heat-table'>"
        f"<thead><tr><th class='sticky model-col'>Modelo</th><th>WR</th><th>Ret</th><th>Hits</th>{head_dates}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
        "<div class='legend'>"
        "<span class='lg pos'>positivo</span><span class='lg neg'>negativo</span><span class='lg muted'>NP sin picks</span><span class='lg stale'>ST atrasado</span>"
        "</div>"
        "</section>"
    )


def ribbon_cards(rows: list[dict[str, Any]], dates: list[str], title: str) -> str:
    cards = []
    for row in rows:
        eq = row["eq"]
        cells = []
        for date_text in dates:
            status = model_status(row, date_text)
            style, text = cell_theme(status)
            cells.append(
                f"<span class='ribbon-cell' style='{style}' data-tip='{safe(status['title'])}' title='{safe(status['title'])}'>{safe(text)}</span>"
            )
        cards.append(
            "<article class='mini-card'>"
            "<div class='mini-head'>"
            f"<div><div class='eyebrow'>{safe(ROLE_LABELS.get(str(row['role']), row['role']))}</div><h3>{safe(row['version'])}</h3></div>"
            f"<div class='model-meta'>{freshness_badge(row.get('stale_market_days'))}</div>"
            "</div>"
            "<div class='mini-kpis'>"
            f"<span>WR {fmt_pct(eq.get('accuracy_pct'))}</span>"
            f"<span>Ret {fmt_pct(eq.get('avg_return_pct'), 3, True)}</span>"
            f"<span>Hits {fmt_int(eq.get('hits'))}/{fmt_int(eq.get('evaluated'))}</span>"
            "</div>"
            f"<div class='scroll ribbon'>{''.join(cells)}</div>"
            "</article>"
        )
    return f"<section class='panel'><div class='panel-head'><div><div class='eyebrow'>Heat ribbons</div><h2>{safe(title)}</h2></div></div><div class='card-grid'>{''.join(cards)}</div></section>"


def week_blocks(rows: list[dict[str, Any]], dates: list[str], title: str) -> str:
    chunks = [dates[i:i + 5] for i in range(0, len(dates), 5)]
    blocks = [table_heatmap(rows, chunk, f"{title} | bloque {index + 1}", compact=True) for index, chunk in enumerate(chunks)]
    return f"<section class='stack'>{''.join(blocks)}</section>"


def day_columns(rows: list[dict[str, Any]], dates: list[str]) -> str:
    columns = []
    for date_text in dates:
        entries = []
        for row in rows:
            status = model_status(row, date_text)
            style, text = cell_theme(status)
            entries.append(
                "<div class='day-row'>"
                f"<div class='day-model'>{safe(row['version'])}</div>"
                f"<div class='day-chip' style='{style}' data-tip='{safe(status['title'])}' title='{safe(status['title'])}'>{safe(text)}</div>"
                "</div>"
            )
        columns.append(
            "<section class='day-col'>"
            f"<div class='day-title'>{safe(short_date(date_text))}<span>{safe(date_text)}</span></div>"
            f"{''.join(entries)}"
            "</section>"
        )
    return f"<section class='scroll day-columns'>{''.join(columns)}</section>"


def mini_calendars(rows: list[dict[str, Any]], dates: list[str]) -> str:
    cards = []
    for row in rows:
        cells = []
        for date_text in dates:
            status = model_status(row, date_text)
            style, text = cell_theme(status)
            cells.append(
                f"<span class='mini-cell' style='{style}' data-tip='{safe(status['title'])}' title='{safe(status['title'])}'>{safe(text)}</span>"
            )
        cards.append(
            "<article class='micro-card'>"
            f"<div class='micro-title'>{safe(row['version'])}</div>"
            f"<div class='micro-sub'>{fmt_pct(row['eq'].get('accuracy_pct'))} | {fmt_pct(row['eq'].get('avg_return_pct'), 2, True)}</div>"
            f"<div class='micro-grid'>{''.join(cells)}</div>"
            "</article>"
        )
    return f"<section class='panel'><div class='panel-head'><div><div class='eyebrow'>Mini calendars</div><h2>Una vista muy compacta por modelo</h2></div></div><div class='micro-grid-wrap'>{''.join(cards)}</div></section>"


def build_index() -> str:
    cards = []
    for key, (title, desc) in VARIANTS.items():
        cards.append(
            f"<a class='idx-card' href='{safe(OUTPUTS[key].name)}'><span class='idx-kicker'>{safe(key.upper())}</span><h2>{safe(title)}</h2><p>{safe(desc)}</p><span class='idx-cta'>Abrir preview</span></a>"
        )
    return f"""<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Heatmap Preview Lab</title><style>{index_css()}</style></head>
<body><main class="idx-shell"><div class="idx-hero"><div class="eyebrow">Heatmap Lab</div><h1>10 opciones visuales solo para el heatmap</h1><p>Estas vistas no modifican el dashboard general. Sirven para elegir el siguiente estilo de presentacion del heatmap con data real.</p></div><section class="idx-grid">{''.join(cards)}</section></main></body>
</html>"""


def build_pages(payload: dict[str, Any], rows: list[dict[str, Any]], dates: list[str]) -> dict[str, str]:
    groups = split_rows(rows)
    champion = [row for row in rows if row["version"] in {f"V{payload['active']['active_version']}", f"V{payload['active']['reference_version']}"}]
    non_champion = [row for row in rows if row not in champion]
    productives = groups["Productivos"]
    observed = groups["Scanners observados"]
    legacy = groups["Legacy ML externos"]
    return {
        "h1": shell("Heatmap H1", table_heatmap(rows, dates, "Liga completa | 12 modelos"), payload, "h1", "classic"),
        "h2": shell("Heatmap H2", table_heatmap(productives, dates, "Productivos", True) + table_heatmap(observed, dates, "Scanners observados", True) + table_heatmap(legacy, dates, "Legacy ML externos", True), payload, "h2", "families"),
        "h3": shell("Heatmap H3", table_heatmap(rows, dates, "Dense matrix", True), payload, "h3", "dense"),
        "h4": shell("Heatmap H4", ribbon_cards(rows, dates, "Tarjetas por modelo con heat ribbon"), payload, "h4", "ribbons"),
        "h5": shell("Heatmap H5", week_blocks(rows, dates, "Week blocks"), payload, "h5", "weeks"),
        "h6": shell("Heatmap H6", table_heatmap(champion, dates, "Champion + referencia") + table_heatmap(non_champion, dates, "Resto de competidores", True), payload, "h6", "focus"),
        "h7": shell("Heatmap H7", f"<section class='panel'><div class='panel-head'><div><div class='eyebrow'>Por rueda</div><h2>Columnas por dia</h2></div></div>{day_columns(rows, dates)}</section>", payload, "h7", "days"),
        "h8": shell("Heatmap H8", table_heatmap(productives + observed, dates, "Scanners") + table_heatmap(legacy, dates, "Legacy ML", True), payload, "h8", "split"),
        "h9": shell("Heatmap H9", mini_calendars(rows, dates), payload, "h9", "mini"),
        "h10": shell("Heatmap H10", table_heatmap(rows, dates, "Terminal heat", True), payload, "h10", "terminal"),
    }


def tooltip_js() -> str:
    return """
(() => {
  const tip = document.getElementById("tip");
  if (!tip) return;
  const show = (event) => {
    const target = event.target.closest("[data-tip]");
    if (!target) return;
    const text = target.getAttribute("data-tip") || "";
    if (!text) return;
    tip.textContent = text;
    tip.classList.add("visible");
    tip.style.left = Math.min(window.innerWidth - 320, event.clientX + 14) + "px";
    tip.style.top = Math.min(window.innerHeight - 140, event.clientY + 18) + "px";
  };
  const hide = () => tip.classList.remove("visible");
  document.addEventListener("mousemove", show);
  document.addEventListener("mouseover", show);
  document.addEventListener("mouseleave", hide);
})();
"""


def css() -> str:
    return """
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; }
body { font-family: "Aptos", "Segoe UI", sans-serif; background: radial-gradient(circle at top left, rgba(32,215,200,.12), transparent 26%), radial-gradient(circle at top right, rgba(110,90,255,.12), transparent 22%), linear-gradient(180deg, #09101b 0%, #101827 100%); color: #e8eef7; }
.shell { width: min(1680px, calc(100vw - 28px)); margin: 0 auto; padding: 18px 0 34px; display: grid; gap: 16px; }
.hero, .panel { background: rgba(13, 20, 34, 0.84); border: 1px solid rgba(255,255,255,.09); border-radius: 24px; box-shadow: 0 18px 46px rgba(0,0,0,.28); }
.hero { display: grid; grid-template-columns: 1.25fr .95fr; gap: 18px; padding: 18px 20px; }
.eyebrow { color: #20d7c8; text-transform: uppercase; letter-spacing: .16em; font-size: 11px; font-weight: 700; }
.hero h1, .panel h2, .panel h3 { margin: 8px 0 0; line-height: 1.04; letter-spacing: -.04em; }
.hero h1 { font-size: clamp(26px, 4vw, 40px); }
.hero p, .micro-sub { margin: 8px 0 0; color: #94a4ba; }
.hero-kpis { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 10px; }
.kpi { padding: 12px 14px; border-radius: 16px; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.07); }
.kpi span, .micro-sub { display: block; font-size: 11px; text-transform: uppercase; letter-spacing: .12em; color: #9aabc0; }
.kpi strong { font-size: 20px; }
.tabs { display: flex; flex-wrap: wrap; gap: 10px; }
.tab { text-decoration: none; color: #e8eef7; background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.09); border-radius: 999px; padding: 10px 14px; font-size: 12px; font-weight: 700; }
.tab.active { background: rgba(32,215,200,.14); border-color: rgba(32,215,200,.28); color: #dffef9; }
.panel { padding: 14px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; }
.panel h2 { font-size: 26px; }
.stack { display: grid; gap: 16px; }
.scroll { overflow: auto; }
.heat-table { width: 100%; border-collapse: collapse; }
.heat-table th, .heat-table td { padding: 8px 7px; border-bottom: 1px solid rgba(255,255,255,.05); border-right: 1px solid rgba(255,255,255,.04); text-align: center; font-size: 11px; white-space: nowrap; }
.heat-table thead th { position: sticky; top: 0; z-index: 2; background: rgba(9,14,22,.98); }
.sticky { position: sticky; left: 0; z-index: 3; background: rgba(9,14,22,.98); }
.model-col { min-width: 190px; text-align: left !important; }
.metric-col { background: rgba(255,255,255,.03); color: #dce7f4; font-weight: 700; }
.model-name { font-size: 14px; font-weight: 800; margin-bottom: 6px; }
.model-meta { display: flex; gap: 6px; flex-wrap: wrap; }
.badge { display: inline-flex; align-items: center; padding: 4px 8px; border-radius: 999px; font-size: 10px; font-weight: 700; border: 1px solid transparent; }
.badge-activo { background: rgba(32,215,200,.13); color: #8ef3e8; border-color: rgba(32,215,200,.26); }
.badge-referencia { background: rgba(242,192,87,.12); color: #f2d68a; border-color: rgba(242,192,87,.28); }
.badge-base { background: rgba(127,184,216,.12); color: #9ed4f7; border-color: rgba(127,184,216,.26); }
.badge-observado { background: rgba(96,220,144,.12); color: #9df0bc; border-color: rgba(96,220,144,.28); }
.badge-legacy_ml { background: rgba(168,140,255,.12); color: #ccb8ff; border-color: rgba(168,140,255,.28); }
.badge-fresh { background: rgba(32,215,200,.12); color: #94f7ec; border-color: rgba(32,215,200,.24); }
.badge-warn { background: rgba(242,192,87,.12); color: #f3d48a; border-color: rgba(242,192,87,.24); }
.badge-stale { background: rgba(255,129,143,.12); color: #ffb0bc; border-color: rgba(255,129,143,.24); }
.badge-muted { background: rgba(255,255,255,.06); color: #bcc7d6; border-color: rgba(255,255,255,.10); }
.heat { min-width: 56px; font-weight: 800; letter-spacing: -.02em; border-radius: 10px; }
.heat.compact { min-width: 48px; padding: 6px 5px; font-size: 10px; }
.legend { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; color: #93a4ba; font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
.lg { padding: 6px 10px; border-radius: 999px; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.07); }
.lg.pos { color: #96f3c2; } .lg.neg { color: #ffb3b3; } .lg.stale { color: #f3d48a; } .lg.muted { color: #a1b1c5; }
.card-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 14px; }
.mini-card, .micro-card, .day-col { background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.07); border-radius: 18px; padding: 14px; }
.mini-head { display: flex; justify-content: space-between; gap: 8px; align-items: start; }
.mini-head h3, .micro-title { margin: 6px 0 0; font-size: 22px; letter-spacing: -.04em; }
.mini-kpis { display: flex; flex-wrap: wrap; gap: 8px; color: #a2b3c7; font-size: 11px; margin: 10px 0; text-transform: uppercase; letter-spacing: .08em; }
.ribbon { display: grid; grid-auto-flow: column; grid-auto-columns: 56px; gap: 6px; padding-bottom: 4px; }
.ribbon-cell, .mini-cell, .day-chip { display: inline-flex; align-items: center; justify-content: center; min-height: 42px; border-radius: 12px; font-weight: 800; font-size: 11px; }
.day-columns { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(220px, 1fr); gap: 12px; padding-bottom: 4px; }
.day-title { font-size: 26px; font-weight: 900; letter-spacing: -.04em; margin-bottom: 12px; }
.day-title span { display: block; font-size: 11px; color: #97a8bd; letter-spacing: .12em; margin-top: 4px; }
.day-row { display: grid; grid-template-columns: 1fr 62px; gap: 8px; align-items: center; margin-bottom: 8px; }
.day-model { font-size: 12px; font-weight: 700; color: #dce6f2; }
.micro-grid-wrap { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 12px; }
.micro-grid { display: grid; grid-template-columns: repeat(5, minmax(0,1fr)); gap: 5px; margin-top: 10px; }
.mini-cell { min-height: 34px; font-size: 10px; }
.tip { position: fixed; left: 0; top: 0; max-width: 320px; padding: 11px 12px; border-radius: 14px; background: rgba(9,14,22,.96); border: 1px solid rgba(255,255,255,.10); box-shadow: 0 18px 45px rgba(0,0,0,.38); color: #e8eef7; font-size: 12px; line-height: 1.45; white-space: pre-line; pointer-events: none; opacity: 0; transform: translateY(6px); transition: opacity .14s ease, transform .14s ease; z-index: 40; }
.tip.visible { opacity: 1; transform: translateY(0); }
body.dense .panel, body.terminal .panel { background: rgba(8, 12, 19, 0.92); }
body.dense .heat-table th, body.dense .heat-table td, body.terminal .heat-table th, body.terminal .heat-table td { padding: 6px 5px; font-size: 10px; }
body.dense .heat, body.terminal .heat { min-width: 42px; }
body.terminal { background: linear-gradient(180deg, #05080e 0%, #0b0f16 100%); }
@media (max-width: 1280px) { .hero { grid-template-columns: 1fr; } .card-grid, .micro-grid-wrap { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .shell { width: min(100vw - 18px, 100%); } .hero-kpis { grid-template-columns: repeat(2, minmax(0,1fr)); } .model-col { min-width: 160px; } }
"""


def index_css() -> str:
    return """
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; }
body { font-family: "Aptos", "Segoe UI", sans-serif; background: radial-gradient(circle at top left, rgba(32,215,200,.12), transparent 24%), radial-gradient(circle at top right, rgba(110,90,255,.14), transparent 22%), linear-gradient(180deg, #09101b 0%, #111a2b 100%); color: #e8eef7; }
.idx-shell { width: min(1280px, calc(100vw - 32px)); margin: 0 auto; padding: 40px 0 60px; }
.eyebrow { color: #20d7c8; text-transform: uppercase; letter-spacing: .16em; font-size: 11px; font-weight: 700; }
.idx-hero h1 { margin: 8px 0 12px; font-size: clamp(34px, 5vw, 58px); line-height: 1.02; letter-spacing: -.05em; }
.idx-hero p { margin: 0; color: #97a8bd; max-width: 72ch; }
.idx-grid { margin-top: 28px; display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 16px; }
.idx-card { display: block; text-decoration: none; color: inherit; background: rgba(13, 20, 34, 0.84); border: 1px solid rgba(255,255,255,.09); border-radius: 24px; padding: 20px; box-shadow: 0 18px 46px rgba(0,0,0,.28); }
.idx-kicker { display: inline-flex; padding: 6px 10px; border-radius: 999px; background: rgba(255,255,255,.05); color: #9dafc3; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .11em; }
.idx-card h2 { margin: 14px 0 8px; font-size: 30px; letter-spacing: -.04em; }
.idx-card p { margin: 0; color: #97a8bd; line-height: 1.6; }
.idx-cta { display: inline-flex; margin-top: 16px; padding: 10px 14px; border-radius: 999px; background: rgba(32,215,200,.12); border: 1px solid rgba(32,215,200,.28); color: #dffef9; font-size: 12px; font-weight: 700; }
@media (max-width: 900px) { .idx-grid { grid-template-columns: 1fr; } }
"""


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def main() -> None:
    payload = load_payload()
    rows = normalize_models(payload)
    dates = extract_dates(payload, rows)
    pages = build_pages(payload, rows, dates)
    write(OUTPUTS["index"], build_index())
    for key, html in pages.items():
        write(OUTPUTS[key], html)
    print("Generated heatmap previews:")
    for key, path in OUTPUTS.items():
        print(f" - {key}: {path}")


if __name__ == "__main__":
    main()
