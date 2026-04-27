#!/usr/bin/env python3
"""
Genera 5 previews finales del dashboard para eleccion visual.

No toca el dashboard oficial. Lee el snapshot operativo ya auditado y
construye variantes HTML separadas para comparar visualmente.
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT_DIR = ROOT / "analisis"
from herramientas.dashboard_paths import SNAPSHOT_PATH

OUTPUTS = {
    "index": OUTPUT_DIR / "preview_d_index.html",
    "v1": OUTPUT_DIR / "preview_d1_calendar_wall.html",
    "v2": OUTPUT_DIR / "preview_d2_family_board.html",
    "v3": OUTPUT_DIR / "preview_d3_terminal_matrix.html",
    "v4": OUTPUT_DIR / "preview_d4_card_strips.html",
    "v5": OUTPUT_DIR / "preview_d5_daybook.html",
}

ROLE_LABELS = {
    "activo": "Activo",
    "referencia": "Referencia",
    "base": "Base",
    "observado": "Observado",
    "legacy_ml": "Legacy ML",
}

ROLE_COLORS = {
    "activo": "#20d7c8",
    "referencia": "#f2c057",
    "base": "#7fb8d8",
    "observado": "#60dc90",
    "legacy_ml": "#a88cff",
}

ROLE_GROUPS = {
    "activo": "Productivos",
    "referencia": "Productivos",
    "base": "Productivos",
    "observado": "Scanners observados",
    "legacy_ml": "Legacy ML externos",
}

VARIANT_META = {
    "v1": ("Calendar Wall", "Heatmap total con 12 modelos y panel lateral operativo."),
    "v2": ("Family Board", "Tres tableros por familia con jerarquia visual fuerte."),
    "v3": ("Terminal Matrix", "Vista extrema de escritorio de trading, compacta y densa."),
    "v4": ("Card Strips", "Grid de tarjetas con mini calendario por modelo."),
    "v5": ("Daybook Calendar", "Calendario por rueda con lectura dia por dia."),
}


def safe(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def fmt_int(value: Any) -> str:
    try:
        return f"{int(value or 0):,}"
    except Exception:
        return "0"


def fmt_pct(value: Any, digits: int = 2, signed: bool = False) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    if math.isnan(number):
        return "-"
    sign = "+" if signed else ""
    return f"{number:{sign}.{digits}f}%"


def short_date(value: str) -> str:
    if not value or len(value) < 10:
        return value or "-"
    return f"{value[8:10]}/{value[5:7]}"


def sparkline_svg(values: list[float], stroke: str, fill: str, width: int = 280, height: int = 70) -> str:
    if not values:
        return (
            f"<svg viewBox='0 0 {width} {height}' class='sparkline'>"
            f"<rect x='0' y='0' width='{width}' height='{height}' rx='16' fill='rgba(255,255,255,0.05)'/>"
            "</svg>"
        )
    low = min(values)
    high = max(values)
    span = high - low or 1.0
    points: list[tuple[float, float]] = []
    for index, value in enumerate(values):
        x = index * (width - 10) / max(len(values) - 1, 1) + 5
        y = height - 6 - ((value - low) / span) * (height - 12)
        points.append((x, y))
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"5,{height-4} " + line + f" {width-5},{height-4}"
    last_x, last_y = points[-1]
    return (
        f"<svg viewBox='0 0 {width} {height}' class='sparkline'>"
        f"<polyline points='0,{height-4} {width},{height-4}' fill='none' stroke='rgba(255,255,255,0.08)' stroke-width='1'/>"
        f"<polygon points='{area}' fill='{fill}' opacity='0.16'/>"
        f"<polyline points='{line}' fill='none' stroke='{stroke}' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/>"
        f"<circle cx='{last_x:.1f}' cy='{last_y:.1f}' r='3.5' fill='{stroke}'/>"
        "</svg>"
    )


def role_badge(role: str) -> str:
    label = ROLE_LABELS.get(role, role)
    return f"<span class='badge badge-{safe(role)}'>{safe(label)}</span>"


def freshness_badge(stale_days: int | None) -> str:
    if stale_days is None:
        return "<span class='badge badge-muted'>Sin fecha</span>"
    if stale_days <= 0:
        return "<span class='badge badge-fresh'>Al dia</span>"
    if stale_days == 1:
        return "<span class='badge badge-warn'>1 rueda atras</span>"
    return f"<span class='badge badge-stale'>{fmt_int(stale_days)} ruedas atras</span>"


def load_payload() -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        raise SystemExit(f"No existe snapshot operativo: {SNAPSHOT_PATH}")
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def extract_dates(payload: dict[str, Any], models: list[dict[str, Any]]) -> list[str]:
    champion_label = f"V{payload['active']['active_version']}"
    for row in models:
        if row["version"] != champion_label:
            continue
        calendar = (row.get("recent_15") or {}).get("calendar") or []
        if calendar:
            return [str(item["date"]) for item in calendar]
    for row in models:
        calendar = (row.get("recent_15") or {}).get("calendar") or []
        if calendar:
            return [str(item["date"]) for item in calendar]
    return []


def normalize_models(payload: dict[str, Any]) -> list[dict[str, Any]]:
    recent = payload["competition_recent"]
    rows = list(recent.get("dashboard_league_equalized") or recent["league_equalized"])
    active_version = payload["active"]["active_version"]
    reference_version = payload["active"].get("reference_version")
    champion_label = f"V{active_version}"
    reference_label = f"V{reference_version}" if reference_version else None

    def order_key(item: dict[str, Any]) -> tuple[int, int]:
        label = str(item["version"])
        role = str(item.get("role") or "")
        if label == champion_label:
            return (0, item.get("rank", 999))
        if reference_label and label == reference_label:
            return (1, item.get("rank", 999))
        if role == "base":
            return (2, item.get("rank", 999))
        if role == "observado":
            return (3, item.get("rank", 999))
        if role == "legacy_ml":
            return (4, item.get("rank", 999))
        return (5, item.get("rank", 999))

    rows.sort(key=order_key)
    for row in rows:
        calendar = (row.get("recent_15") or {}).get("calendar") or []
        row["calendar_map"] = {str(item["date"]): item for item in calendar}
        row["role_group"] = ROLE_GROUPS.get(str(row.get("role")), "Otros")
        row["color"] = ROLE_COLORS.get(str(row.get("role")), "#8aa0b5")
        row["eq"] = row.get("equalized_recent") or {}
        spark_values = row["eq"].get("spark_avg_return_pct") or row.get("recent_30", {}).get("spark_avg_return_pct") or []
        cumulative = []
        total = 0.0
        for value in spark_values:
            total += float(value or 0)
            cumulative.append(round(total, 4))
        row["spark_svg"] = sparkline_svg(cumulative, row["color"], row["color"], width=280, height=72)
    return rows


def model_status(row: dict[str, Any], date_text: str) -> dict[str, Any]:
    entry = row["calendar_map"].get(date_text)
    last_date = str(row.get("last_date") or "")
    if entry is None:
        if last_date and date_text > last_date:
            return {
                "kind": "stale",
                "text": "ST",
                "title": f"{row['version']} | {date_text}\\nSin corrida para esta rueda.\\nUltima fecha del modelo: {last_date}",
            }
        return {
            "kind": "empty",
            "text": "--",
            "title": f"{row['version']} | {date_text}\\nSin dato consolidado.",
        }

    picks = int(entry.get("picks") or 0)
    ret = entry.get("avg_return_pct")
    acc = entry.get("accuracy_pct")
    tickers = entry.get("tickers") or []
    ticker_text = ", ".join(tickers) if tickers else "Sin picks"

    if picks <= 0:
        kind = "stale" if last_date and date_text > last_date else "nopick"
        label = "ST" if kind == "stale" else "NP"
        reason = "Sin corrida para esta rueda" if kind == "stale" else "Sin picks ese dia"
        return {
            "kind": kind,
            "text": label,
            "title": (
                f"{row['version']} | {date_text}\\n"
                f"{reason}\\n"
                f"ret - | WR - | picks 0\\n"
                f"{ticker_text}"
            ),
            "ret": None,
            "picks": picks,
        }

    text = f"{float(ret):+.1f}" if ret is not None else "0.0"
    return {
        "kind": "active",
        "text": text,
        "title": (
            f"{row['version']} | {date_text}\\n"
            f"ret {fmt_pct(ret, 2, True)} | WR {fmt_pct(acc)} | picks {picks}\\n"
            f"{ticker_text}"
        ),
        "ret": float(ret or 0.0),
        "picks": picks,
        "tickers": tickers,
        "accuracy_pct": acc,
    }


def nav_tabs(active_key: str) -> str:
    links = []
    for key in ["v1", "v2", "v3", "v4", "v5"]:
        title, desc = VARIANT_META[key]
        cls = "nav-tab active" if key == active_key else "nav-tab"
        links.append(f"<a class='{cls}' href='{OUTPUTS[key].name}' title='{safe(desc)}'>{safe(title)}</a>")
    return "".join(links)


def render_header(payload: dict[str, Any], active_key: str) -> str:
    integrity = payload["integrity"]
    active = payload["active"]
    active_run = active.get("active_run") or {}
    live_results = list(active_run.get("results_d", [])) + list(active_run.get("results_e", []))
    return (
        "<header class='hero'>"
        "<div class='hero-copy'>"
        "<div class='hero-kicker'>Titan Machine Preview Lab</div>"
        "<h1>Variantes visuales finales del dashboard</h1>"
        f"<p>Mercado {safe(integrity['latest_market_date'])} | Champion V{fmt_int(active['active_version'])} | "
        f"Referencia V{fmt_int(active['reference_version'])} | Picks vivos {fmt_int(len(live_results))}</p>"
        "</div>"
        "<div class='hero-meta'>"
        f"<div class='meta-chip'><span>Predictions</span><strong>{fmt_int(integrity['predictions_count'])}</strong></div>"
        f"<div class='meta-chip'><span>Outcomes</span><strong>{fmt_int(integrity['outcomes_count'])}</strong></div>"
        f"<div class='meta-chip'><span>Regimes</span><strong>{fmt_int(integrity['regimes_count'])}</strong></div>"
        f"<div class='meta-chip'><span>Snapshot</span><strong>{safe(payload['generated_at'][11:16])}</strong></div>"
        "</div>"
        "</header>"
        f"<nav class='variant-nav'>{nav_tabs(active_key)}</nav>"
    )


def render_champion_panel(payload: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    champion_label = f"V{payload['active']['active_version']}"
    champion = next((row for row in rows if row["version"] == champion_label), None)
    if not champion:
        return ""
    active_run = payload["active"].get("active_run") or {}
    live_results = list(active_run.get("results_d", [])) + list(active_run.get("results_e", []))
    picks = "".join(
        f"<li><strong>{safe(item.get('ticker'))}</strong><span>{safe(item.get('signal') or item.get('setup') or '-')}</span></li>"
        for item in live_results[:8]
    ) or "<li><strong>Sin picks</strong><span>snapshot actual</span></li>"
    eq = champion["eq"]
    return (
        "<section class='champion-panel'>"
        "<div class='panel-head'>"
        f"<div><div class='eyebrow'>Champion vigente</div><h2>{safe(champion['version'])}</h2></div>"
        f"<div class='badges'>{role_badge(str(champion['role']))}{freshness_badge(champion.get('stale_market_days'))}</div>"
        "</div>"
        f"<div class='champion-chart'>{champion['spark_svg']}</div>"
        "<div class='champion-kpis'>"
        f"<div class='metric'><span>WR igualado</span><strong>{fmt_pct(eq.get('accuracy_pct'))}</strong></div>"
        f"<div class='metric'><span>Ret igualado</span><strong>{fmt_pct(eq.get('avg_return_pct'), 3, True)}</strong></div>"
        f"<div class='metric'><span>Hits</span><strong>{fmt_int(eq.get('hits'))}/{fmt_int(eq.get('evaluated'))}</strong></div>"
        f"<div class='metric'><span>Ultima fecha</span><strong>{safe(champion.get('last_date'))}</strong></div>"
        "</div>"
        "<div class='pick-box'>"
        f"<div class='pick-title'>Prediccion viva | target {safe(active_run.get('prediction_for'))}</div>"
        f"<ul class='pick-list'>{picks}</ul>"
        "</div>"
        "</section>"
    )


def render_top_rank_table(rows: list[dict[str, Any]], limit: int = 6) -> str:
    body = []
    for row in rows[:limit]:
        eq = row["eq"]
        body.append(
            "<tr>"
            f"<td><span class='rank-dot' style='background:{safe(row['color'])}'></span>{fmt_int(row.get('rank'))}</td>"
            f"<td><strong>{safe(row['version'])}</strong><div class='tiny'>{safe(ROLE_LABELS.get(str(row['role']), row['role']))}</div></td>"
            f"<td>{fmt_pct(eq.get('accuracy_pct'))}</td>"
            f"<td>{fmt_pct(eq.get('avg_return_pct'), 3, True)}</td>"
            f"<td>{fmt_int(eq.get('hits'))}/{fmt_int(eq.get('evaluated'))}</td>"
            "</tr>"
        )
    return (
        "<section class='table-panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Liga igualada</div><h3>Ranking total</h3></div></div>"
        "<table class='compact-table'><thead><tr><th>#</th><th>Modelo</th><th>WR</th><th>Ret</th><th>Hits</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></section>"
    )


def render_full_heatmap(rows: list[dict[str, Any]], dates: list[str], family_title: str | None = None) -> str:
    header = "".join(f"<th>{safe(short_date(date_text))}</th>" for date_text in dates)
    body_rows = []
    for row in rows:
        cells = [
            "<th class='row-sticky'>"
            f"<div class='hm-model'>{safe(row['version'])}</div>"
            f"<div class='hm-meta'>{role_badge(str(row['role']))}{freshness_badge(row.get('stale_market_days'))}</div>"
            "</th>"
        ]
        for date_text in dates:
            status = model_status(row, date_text)
            kind = safe(status["kind"])
            title = safe(status["title"])
            cells.append(
                f"<td class='hm-cell hm-{kind}' data-tip='{title}' title='{title}'>{safe(status['text'])}</td>"
            )
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    title_html = ""
    if family_title:
        title_html = f"<div class='panel-head'><div><div class='eyebrow'>Heatmap</div><h3>{safe(family_title)}</h3></div></div>"
    return (
        "<section class='table-panel'>"
        f"{title_html}"
        "<div class='heatmap-wrap'>"
        "<table class='heatmap-table'>"
        f"<thead><tr><th class='row-sticky'>Modelo</th>{header}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
        "<div class='legend'>"
        "<span><b>valor</b> = retorno medio del dia</span>"
        "<span><b>NP</b> = sin picks</span>"
        "<span><b>ST</b> = modelo atrasado para esa rueda</span>"
        "</div>"
        "</section>"
    )


def render_model_cards(rows: list[dict[str, Any]], dates: list[str]) -> str:
    cards = []
    for row in rows:
        strip = []
        for date_text in dates:
            status = model_status(row, date_text)
            strip.append(
                f"<span class='strip-cell strip-{safe(status['kind'])}' data-tip='{safe(status['title'])}' title='{safe(status['title'])}'>{safe(status['text'])}</span>"
            )
        cards.append(
            "<article class='model-card'>"
            "<div class='panel-head compact'>"
            f"<div><div class='eyebrow'>{safe(row['role_group'])}</div><h3>{safe(row['version'])}</h3></div>"
            f"<div class='badges'>{role_badge(str(row['role']))}{freshness_badge(row.get('stale_market_days'))}</div>"
            "</div>"
            f"<div class='card-spark'>{row['spark_svg']}</div>"
            "<div class='card-kpis'>"
            f"<div class='metric'><span>WR</span><strong>{fmt_pct(row['eq'].get('accuracy_pct'))}</strong></div>"
            f"<div class='metric'><span>Ret</span><strong>{fmt_pct(row['eq'].get('avg_return_pct'), 3, True)}</strong></div>"
            f"<div class='metric'><span>Hits</span><strong>{fmt_int(row['eq'].get('hits'))}/{fmt_int(row['eq'].get('evaluated'))}</strong></div>"
            f"<div class='metric'><span>Picks</span><strong>{fmt_int(row.get('latest_picks'))}</strong></div>"
            "</div>"
            f"<div class='latest-tickers'>{safe(', '.join(row.get('latest_tickers', [])[:10]) or 'Sin picks recientes')}</div>"
            f"<div class='mini-strip'>{''.join(strip)}</div>"
            "</article>"
        )
    return f"<section class='cards-grid'>{''.join(cards)}</section>"


def render_family_sections(rows: list[dict[str, Any]], dates: list[str]) -> str:
    ordered_groups = ["Productivos", "Scanners observados", "Legacy ML externos"]
    sections = []
    for group in ordered_groups:
        group_rows = [row for row in rows if row["role_group"] == group]
        if not group_rows:
            continue
        sections.append(
            "<section class='family-section'>"
            f"<div class='panel-head'><div><div class='eyebrow'>Familia</div><h2>{safe(group)}</h2></div>"
            f"<div class='meta-note'>{fmt_int(len(group_rows))} modelos</div></div>"
            f"{render_full_heatmap(group_rows, dates)}"
            f"{render_model_cards(group_rows, dates)}"
            "</section>"
        )
    return "".join(sections)


def render_terminal_table(rows: list[dict[str, Any]], dates: list[str]) -> str:
    header = "".join(f"<th>{safe(short_date(date_text))}</th>" for date_text in dates)
    body = []
    for row in rows:
        eq = row["eq"]
        cells = [
            "<td class='terminal-model'>"
            f"<strong>{safe(row['version'])}</strong>"
            f"<span>{safe(ROLE_LABELS.get(str(row['role']), row['role']))}</span>"
            "</td>",
            f"<td>{fmt_pct(eq.get('accuracy_pct'))}</td>",
            f"<td>{fmt_pct(eq.get('avg_return_pct'), 3, True)}</td>",
            f"<td>{fmt_int(eq.get('hits'))}/{fmt_int(eq.get('evaluated'))}</td>",
            f"<td>{safe(row.get('last_date'))}</td>",
        ]
        for date_text in dates:
            status = model_status(row, date_text)
            cells.append(f"<td class='tm-{safe(status['kind'])}' data-tip='{safe(status['title'])}' title='{safe(status['title'])}'>{safe(status['text'])}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    return (
        "<section class='table-panel terminal-panel'>"
        "<div class='panel-head'><div><div class='eyebrow'>Desk mode</div><h2>Matrix operativa completa</h2></div></div>"
        "<div class='heatmap-wrap'>"
        "<table class='terminal-table'>"
        "<thead><tr><th>Modelo</th><th>WR</th><th>Ret</th><th>Hits</th><th>Last</th>"
        f"{header}</tr></thead><tbody>{''.join(body)}</tbody></table></div></section>"
    )


def render_calendar_daybook(rows: list[dict[str, Any]], dates: list[str], payload: dict[str, Any]) -> str:
    champion_label = f"V{payload['active']['active_version']}"
    champion = next((row for row in rows if row["version"] == champion_label), None)
    cards = []
    for date_text in dates:
        statuses = [(row, model_status(row, date_text)) for row in rows]
        active_items = [(row, status) for row, status in statuses if status["kind"] == "active"]
        active_items.sort(key=lambda item: item[1].get("ret", float("-inf")), reverse=True)
        top = active_items[0] if active_items else None
        bottom = active_items[-1] if active_items else None
        champion_status = model_status(champion, date_text) if champion else {"kind": "empty", "text": "--", "title": "-"}
        pills = []
        for row, status in statuses:
            pills.append(
                f"<span class='day-pill day-{safe(status['kind'])}' data-tip='{safe(status['title'])}' title='{safe(status['title'])}'>"
                f"{safe(row['version'])} {safe(status['text'])}</span>"
            )
        cards.append(
            "<article class='day-card'>"
            f"<div class='day-date'>{safe(short_date(date_text))}<span>{safe(date_text[:4])}</span></div>"
            "<div class='day-core'>"
            f"<div class='day-champion'><span>Champion</span><strong>{safe(champion_label)} {safe(champion_status['text'])}</strong></div>"
            f"<div class='day-top'><span>Top</span><strong>{safe(top[0]['version']) if top else '-'} {safe(top[1]['text']) if top else '--'}</strong></div>"
            f"<div class='day-bottom'><span>Floor</span><strong>{safe(bottom[0]['version']) if bottom else '-'} {safe(bottom[1]['text']) if bottom else '--'}</strong></div>"
            "</div>"
            f"<div class='day-pills'>{''.join(pills)}</div>"
            "</article>"
        )
    return f"<section class='day-grid'>{''.join(cards)}</section>"


def base_shell(title: str, payload: dict[str, Any], active_key: str, body_html: str, mode_class: str) -> str:
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe(title)}</title>
  <style>{base_css(mode_class)}</style>
</head>
<body class="{safe(mode_class)}">
  <div class="site-shell">
    {render_header(payload, active_key)}
    {body_html}
  </div>
  <div id="tip" class="floating-tip"></div>
  <script>{tooltip_script()}</script>
</body>
</html>"""


def render_index_page() -> str:
    cards = []
    for key in ["v1", "v2", "v3", "v4", "v5"]:
        title, desc = VARIANT_META[key]
        cards.append(
            "<a class='index-card' href='{name}'>"
            "<span class='index-kicker'>Preview {key}</span>"
            "<h2>{title}</h2>"
            "<p>{desc}</p>"
            "<span class='index-cta'>Abrir vista</span>"
            "</a>".format(name=safe(OUTPUTS[key].name), key=safe(key.upper()), title=safe(title), desc=safe(desc))
        )
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Preview Lab Dashboard</title>
  <style>{index_css()}</style>
</head>
<body>
  <main class="index-shell">
    <div class="index-hero">
      <div class="eyebrow">Preview Lab</div>
      <h1>Elegi visualmente la proxima vista del dashboard</h1>
      <p>Estas paginas no reemplazan al dashboard oficial. Son variantes finales de prueba para elegir estilo, densidad y lectura.</p>
    </div>
    <section class="index-grid">{''.join(cards)}</section>
  </main>
</body>
</html>"""


def tooltip_script() -> str:
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
    const x = Math.min(window.innerWidth - 320, event.clientX + 14);
    const y = Math.min(window.innerHeight - 120, event.clientY + 18);
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  };
  const hide = () => tip.classList.remove("visible");
  document.addEventListener("mousemove", show);
  document.addEventListener("mouseleave", hide);
  document.addEventListener("mouseover", show);
})();
"""


def base_css(mode_class: str) -> str:
    bg = {
        "calendar-wall": "linear-gradient(160deg, #08111d 0%, #0d1628 45%, #0a1322 100%)",
        "family-board": "radial-gradient(circle at top left, rgba(32,215,200,0.18), transparent 28%), linear-gradient(180deg, #0d1220 0%, #11182a 100%)",
        "terminal-matrix": "linear-gradient(180deg, #06090f 0%, #0b1018 100%)",
        "card-strips": "radial-gradient(circle at top right, rgba(168,140,255,0.16), transparent 22%), linear-gradient(180deg, #0e1220 0%, #121728 100%)",
        "daybook-calendar": "radial-gradient(circle at top left, rgba(242,192,87,0.18), transparent 24%), linear-gradient(180deg, #0c1220 0%, #131a2d 100%)",
    }.get(mode_class, "linear-gradient(180deg, #0e1220 0%, #13192a 100%)")
    return f"""
:root {{
  --bg: {bg};
  --panel: rgba(14, 20, 34, 0.82);
  --panel-strong: rgba(11, 17, 29, 0.94);
  --line: rgba(255,255,255,0.10);
  --line-soft: rgba(255,255,255,0.06);
  --ink: #e9eef7;
  --muted: #91a0b5;
  --radius: 22px;
  --shadow: 0 24px 60px rgba(0,0,0,0.32);
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; min-height: 100%; }}
body {{ font-family: "Aptos", "Segoe UI", sans-serif; background: var(--bg); color: var(--ink); }}
.site-shell {{ width: min(1680px, calc(100vw - 36px)); margin: 0 auto; padding: 20px 0 36px; }}
.hero {{ display: grid; grid-template-columns: 1.25fr 0.9fr; gap: 18px; align-items: start; background: var(--panel); border: 1px solid var(--line); border-radius: 28px; padding: 22px 24px; box-shadow: var(--shadow); }}
.hero-kicker, .eyebrow {{ color: #20d7c8; text-transform: uppercase; letter-spacing: .16em; font-size: 11px; font-weight: 700; }}
.hero h1 {{ margin: 8px 0 10px; font-size: clamp(26px, 4vw, 42px); line-height: 1.05; letter-spacing: -.04em; }}
.hero p {{ margin: 0; color: var(--muted); max-width: 72ch; }}
.hero-meta {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
.meta-chip, .metric {{ background: rgba(255,255,255,0.04); border: 1px solid var(--line-soft); border-radius: 18px; padding: 12px 14px; }}
.meta-chip span, .metric span {{ display: block; color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .12em; margin-bottom: 4px; }}
.meta-chip strong, .metric strong {{ font-size: 20px; }}
.variant-nav {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 14px 0 18px; }}
.nav-tab {{ display: inline-flex; align-items: center; padding: 10px 14px; border-radius: 999px; background: rgba(255,255,255,0.05); border: 1px solid var(--line); color: var(--ink); text-decoration: none; font-size: 12px; font-weight: 700; }}
.nav-tab.active {{ background: rgba(32,215,200,0.14); border-color: rgba(32,215,200,0.35); color: #dffef9; }}
.dashboard-grid {{ display: grid; gap: 18px; }}
.dashboard-grid.v1 {{ grid-template-columns: 0.98fr 1.3fr; align-items: start; }}
.stack {{ display: grid; gap: 18px; }}
.champion-panel, .table-panel, .family-section, .model-card, .day-card {{ background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow); }}
.champion-panel {{ padding: 18px; }}
.panel-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }}
.panel-head.compact {{ margin-bottom: 10px; }}
.panel-head h2, .panel-head h3 {{ margin: 5px 0 0; font-size: 26px; line-height: 1.05; letter-spacing: -.04em; }}
.meta-note {{ color: var(--muted); font-size: 12px; }}
.badges, .hm-meta {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.badge {{ display: inline-flex; align-items: center; padding: 5px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; border: 1px solid transparent; }}
.badge-activo {{ background: rgba(32,215,200,0.13); color: #8ef3e8; border-color: rgba(32,215,200,0.26); }}
.badge-referencia {{ background: rgba(242,192,87,0.12); color: #f2d68a; border-color: rgba(242,192,87,0.28); }}
.badge-base {{ background: rgba(127,184,216,0.12); color: #9ed4f7; border-color: rgba(127,184,216,0.26); }}
.badge-observado {{ background: rgba(96,220,144,0.12); color: #9df0bc; border-color: rgba(96,220,144,0.28); }}
.badge-legacy_ml {{ background: rgba(168,140,255,0.12); color: #ccb8ff; border-color: rgba(168,140,255,0.28); }}
.badge-fresh {{ background: rgba(32,215,200,0.12); color: #94f7ec; border-color: rgba(32,215,200,0.24); }}
.badge-warn {{ background: rgba(242,192,87,0.12); color: #f3d48a; border-color: rgba(242,192,87,0.24); }}
.badge-stale {{ background: rgba(255,129,143,0.12); color: #ffb0bc; border-color: rgba(255,129,143,0.24); }}
.badge-muted {{ background: rgba(255,255,255,0.06); color: #bcc7d6; border-color: rgba(255,255,255,0.10); }}
.champion-chart, .card-spark {{ margin: 12px 0 14px; }}
.champion-kpis, .card-kpis {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }}
.pick-box {{ margin-top: 14px; padding: 14px; border-radius: 18px; background: rgba(255,255,255,0.03); border: 1px solid var(--line-soft); }}
.pick-title {{ font-size: 12px; text-transform: uppercase; letter-spacing: .12em; color: var(--muted); margin-bottom: 10px; }}
.pick-list {{ list-style: none; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 0; padding: 0; }}
.pick-list li {{ display: flex; justify-content: space-between; gap: 8px; padding: 8px 10px; border-radius: 14px; background: rgba(255,255,255,0.04); }}
.pick-list span {{ color: var(--muted); font-size: 12px; }}
.table-panel {{ padding: 16px; }}
.compact-table, .heatmap-table, .terminal-table {{ width: 100%; border-collapse: collapse; }}
.compact-table th, .compact-table td, .terminal-table th, .terminal-table td {{ padding: 10px 10px; border-bottom: 1px solid var(--line-soft); font-size: 12px; text-align: left; }}
.compact-table tbody tr:last-child td, .terminal-table tbody tr:last-child td {{ border-bottom: 0; }}
.rank-dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 8px; }}
.tiny {{ color: var(--muted); font-size: 11px; margin-top: 2px; }}
.heatmap-wrap {{ overflow: auto; border-radius: 18px; border: 1px solid var(--line-soft); }}
.heatmap-table th, .heatmap-table td {{ min-width: 64px; padding: 10px 8px; border-bottom: 1px solid var(--line-soft); border-right: 1px solid var(--line-soft); text-align: center; font-size: 12px; }}
.heatmap-table thead th {{ position: sticky; top: 0; z-index: 2; background: rgba(11,17,29,0.98); }}
.row-sticky {{ position: sticky; left: 0; z-index: 3; min-width: 210px; text-align: left !important; background: rgba(11,17,29,0.98); }}
.hm-model {{ font-weight: 800; margin-bottom: 6px; }}
.hm-cell {{ font-weight: 800; letter-spacing: -.02em; }}
.hm-active {{ background: rgba(255,255,255,0.04); }}
.hm-nopick {{ background: rgba(255,255,255,0.04); color: #97a6bb; }}
.hm-stale {{ background: repeating-linear-gradient(135deg, rgba(255,255,255,0.06), rgba(255,255,255,0.06) 6px, rgba(255,255,255,0.03) 6px, rgba(255,255,255,0.03) 12px); color: #f0c57b; }}
.hm-empty {{ background: rgba(255,255,255,0.03); color: #748398; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin-top: 12px; color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .09em; }}
.family-section {{ padding: 18px; display: grid; gap: 16px; }}
.cards-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
.model-card {{ padding: 16px; }}
.latest-tickers {{ color: var(--muted); font-size: 12px; line-height: 1.5; margin: 10px 0 12px; min-height: 38px; }}
.mini-strip {{ display: grid; grid-template-columns: repeat(15, minmax(0, 1fr)); gap: 4px; }}
.strip-cell {{ display: flex; align-items: center; justify-content: center; min-height: 30px; border-radius: 10px; font-size: 10px; font-weight: 800; background: rgba(255,255,255,0.04); }}
.strip-active {{ color: var(--ink); }}
.strip-nopick {{ color: #92a1b6; }}
.strip-stale {{ color: #f0c57b; background: rgba(242,192,87,0.10); }}
.strip-empty {{ color: #708097; }}
.terminal-panel {{ background: rgba(6,10,16,0.96); }}
.terminal-table th, .terminal-table td {{ white-space: nowrap; font-size: 11px; padding: 8px 9px; }}
.terminal-model {{ min-width: 160px; }}
.terminal-model span {{ display: block; color: var(--muted); font-size: 10px; margin-top: 3px; }}
.tm-active {{ color: #eafef9; }}
.tm-nopick {{ color: #90a0b4; }}
.tm-stale {{ color: #f1cb80; background: rgba(242,192,87,0.08); }}
.tm-empty {{ color: #637387; }}
.day-grid {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; }}
.day-card {{ padding: 14px; display: grid; gap: 12px; }}
.day-date {{ display: flex; align-items: baseline; justify-content: space-between; font-size: 30px; font-weight: 900; letter-spacing: -.04em; }}
.day-date span {{ font-size: 12px; color: var(--muted); font-weight: 600; letter-spacing: .12em; }}
.day-core {{ display: grid; gap: 8px; }}
.day-core > div {{ display: flex; justify-content: space-between; gap: 8px; padding: 8px 10px; border-radius: 12px; background: rgba(255,255,255,0.04); }}
.day-core span {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }}
.day-pills {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.day-pill {{ display: inline-flex; align-items: center; padding: 6px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; background: rgba(255,255,255,0.05); }}
.day-active {{ color: #eafef9; }}
.day-nopick {{ color: #94a3b7; }}
.day-stale {{ color: #f1cb80; background: rgba(242,192,87,0.10); }}
.day-empty {{ color: #77869b; }}
.floating-tip {{ position: fixed; left: 0; top: 0; max-width: 300px; padding: 11px 12px; border-radius: 14px; background: rgba(9,14,22,0.96); border: 1px solid rgba(255,255,255,0.10); box-shadow: 0 18px 45px rgba(0,0,0,0.38); color: var(--ink); font-size: 12px; line-height: 1.45; white-space: pre-line; pointer-events: none; opacity: 0; transform: translateY(6px); transition: opacity .14s ease, transform .14s ease; z-index: 30; }}
.floating-tip.visible {{ opacity: 1; transform: translateY(0); }}
@media (max-width: 1320px) {{ .hero {{ grid-template-columns: 1fr; }} .dashboard-grid.v1 {{ grid-template-columns: 1fr; }} .cards-grid {{ grid-template-columns: 1fr; }} .day-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }} }}
@media (max-width: 980px) {{ .site-shell {{ width: min(100vw - 20px, 100%); }} .champion-kpis, .card-kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .pick-list {{ grid-template-columns: 1fr; }} .day-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
@media (max-width: 760px) {{ .day-grid {{ grid-template-columns: 1fr; }} .row-sticky {{ min-width: 170px; }} .heatmap-table th, .heatmap-table td {{ min-width: 58px; padding: 8px 6px; }} }}
"""


def index_css() -> str:
    return """
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; }
body { font-family: "Aptos", "Segoe UI", sans-serif; background: radial-gradient(circle at top left, rgba(32,215,200,0.18), transparent 26%), radial-gradient(circle at top right, rgba(168,140,255,0.18), transparent 24%), linear-gradient(180deg, #0a0f1a 0%, #11182b 100%); color: #e9eef7; }
.index-shell { width: min(1240px, calc(100vw - 36px)); margin: 0 auto; padding: 42px 0 60px; }
.eyebrow { color: #20d7c8; text-transform: uppercase; letter-spacing: .16em; font-size: 11px; font-weight: 700; }
.index-hero h1 { margin: 8px 0 12px; font-size: clamp(34px, 5vw, 62px); line-height: 1.02; letter-spacing: -.05em; }
.index-hero p { margin: 0; color: #9ba9bc; font-size: 16px; max-width: 70ch; }
.index-grid { margin-top: 28px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.index-card { display: block; text-decoration: none; color: inherit; border-radius: 28px; padding: 22px; background: rgba(14, 20, 34, 0.82); border: 1px solid rgba(255,255,255,0.10); box-shadow: 0 24px 60px rgba(0,0,0,0.32); min-height: 210px; }
.index-kicker { display: inline-flex; padding: 6px 10px; border-radius: 999px; background: rgba(255,255,255,0.05); color: #9eabbd; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .12em; }
.index-card h2 { margin: 14px 0 10px; font-size: 34px; line-height: 1.02; letter-spacing: -.04em; }
.index-card p { color: #9ba9bc; margin: 0; line-height: 1.6; }
.index-cta { display: inline-flex; margin-top: 18px; padding: 10px 14px; border-radius: 999px; background: rgba(32,215,200,0.12); border: 1px solid rgba(32,215,200,0.28); color: #dffef9; font-size: 12px; font-weight: 700; }
@media (max-width: 900px) { .index-grid { grid-template-columns: 1fr; } }
"""


def build_variant_v1(payload: dict[str, Any], rows: list[dict[str, Any]], dates: list[str]) -> str:
    body = (
        "<main class='dashboard-grid v1'>"
        "<div class='stack'>"
        f"{render_champion_panel(payload, rows)}"
        f"{render_top_rank_table(rows, limit=8)}"
        "</div>"
        f"{render_full_heatmap(rows, dates, family_title='Liga completa | 12 modelos')}"
        "</main>"
    )
    return base_shell("Preview V1 | Calendar Wall", payload, "v1", body, "calendar-wall")


def build_variant_v2(payload: dict[str, Any], rows: list[dict[str, Any]], dates: list[str]) -> str:
    body = (
        "<main class='stack'>"
        "<section class='dashboard-grid v1'>"
        f"{render_champion_panel(payload, rows)}"
        f"{render_top_rank_table(rows, limit=6)}"
        "</section>"
        f"{render_family_sections(rows, dates)}"
        "</main>"
    )
    return base_shell("Preview V2 | Family Board", payload, "v2", body, "family-board")


def build_variant_v3(payload: dict[str, Any], rows: list[dict[str, Any]], dates: list[str]) -> str:
    body = (
        "<main class='stack'>"
        "<section class='dashboard-grid v1'>"
        f"{render_champion_panel(payload, rows)}"
        f"{render_top_rank_table(rows, limit=10)}"
        "</section>"
        f"{render_terminal_table(rows, dates)}"
        "</main>"
    )
    return base_shell("Preview V3 | Terminal Matrix", payload, "v3", body, "terminal-matrix")


def build_variant_v4(payload: dict[str, Any], rows: list[dict[str, Any]], dates: list[str]) -> str:
    productive = [row for row in rows if row["role_group"] == "Productivos"]
    observed = [row for row in rows if row["role_group"] == "Scanners observados"]
    legacy = [row for row in rows if row["role_group"] == "Legacy ML externos"]
    body = (
        "<main class='stack'>"
        "<section class='dashboard-grid v1'>"
        f"{render_champion_panel(payload, rows)}"
        f"{render_top_rank_table(rows, limit=7)}"
        "</section>"
        "<section class='family-section'>"
        "<div class='panel-head'><div><div class='eyebrow'>Card strips</div><h2>Productivos y observados</h2></div>"
        "<div class='meta-note'>KPIs + mini calendario por modelo</div></div>"
        f"{render_model_cards(productive + observed, dates)}"
        "</section>"
        "<section class='family-section'>"
        "<div class='panel-head'><div><div class='eyebrow'>Legacy</div><h2>Competidores externos</h2></div>"
        "<div class='meta-note'>Familia ML historica</div></div>"
        f"{render_model_cards(legacy, dates)}"
        "</section>"
        "</main>"
    )
    return base_shell("Preview V4 | Card Strips", payload, "v4", body, "card-strips")


def build_variant_v5(payload: dict[str, Any], rows: list[dict[str, Any]], dates: list[str]) -> str:
    body = (
        "<main class='stack'>"
        "<section class='dashboard-grid v1'>"
        f"{render_champion_panel(payload, rows)}"
        f"{render_top_rank_table(rows, limit=5)}"
        "</section>"
        "<section class='family-section'>"
        "<div class='panel-head'><div><div class='eyebrow'>Calendar daybook</div><h2>Lectura por rueda</h2></div>"
        "<div class='meta-note'>Champion + top/floor + todos los modelos por fecha</div></div>"
        f"{render_calendar_daybook(rows, dates, payload)}"
        "</section>"
        f"{render_full_heatmap(rows, dates, family_title='Apoyo visual | heatmap total')}"
        "</main>"
    )
    return base_shell("Preview V5 | Daybook Calendar", payload, "v5", body, "daybook-calendar")


def write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def main() -> None:
    payload = load_payload()
    rows = normalize_models(payload)
    dates = extract_dates(payload, rows)

    if not rows:
        raise SystemExit("Snapshot sin modelos para renderizar.")
    if not dates:
        raise SystemExit("Snapshot sin calendario reciente para renderizar.")

    write(OUTPUTS["index"], render_index_page())
    write(OUTPUTS["v1"], build_variant_v1(payload, rows, dates))
    write(OUTPUTS["v2"], build_variant_v2(payload, rows, dates))
    write(OUTPUTS["v3"], build_variant_v3(payload, rows, dates))
    write(OUTPUTS["v4"], build_variant_v4(payload, rows, dates))
    write(OUTPUTS["v5"], build_variant_v5(payload, rows, dates))

    print("Generated preview pages:")
    for key, path in OUTPUTS.items():
        print(f" - {key}: {path}")


if __name__ == "__main__":
    main()
