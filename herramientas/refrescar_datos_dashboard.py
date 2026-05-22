# build: 2026-05-06
#!/usr/bin/env python3
"""
Refresca la plantilla canonica C1 Pro a partir del snapshot JSON.
Se invoca al final del pipeline diario (auto_actualizar.py).
Soporta footer .ft-footer (Quant Terminal, topbar + 3-col).

Qué hace:
  - Reemplaza heatmap, liga y cards visibles con datos frescos del snapshot auditado
    - Mantiene la UI C1 Pro sin cambios visuales intencionales
  - NO toca estilos, temas, editor ni ningún otro componente de UI

Uso standalone:
  python herramientas/refrescar_datos_dashboard.py
  python herramientas/refrescar_datos_dashboard.py --add-markers   # primera vez
"""
from __future__ import annotations
import sys, json, re, datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT      = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from herramientas.dashboard_paths import C1_PRO_TEMPLATE_HTML as DASHBOARD, SNAPSHOT_PATH as SNAPSHOT, ensure_dashboard_dir
from herramientas.dashboard_c1_contract import (
    MARK_CSS_E,
    MARK_CSS_S,
    MARK_HERO_E,
    MARK_HERO_S,
    MARK_HM_E,
    MARK_HM_S,
    MARK_LIGA_E,
    MARK_LIGA_S,
    MARK_PRED_E,
    MARK_PRED_S,
    REQUIRED_MARKER_PAIRS,
    liga_static_meta,
)


# ── helpers ──────────────────────────────────────────────────────────────────
def _esc(v: object) -> str:
    import html
    return html.escape("" if v is None else str(v))

def _ret_bg(ret: float | None) -> str:
    if ret is None:
        return "transparent"
    intens = min(abs(ret) / 5.0, 1.0)
    if ret >= 0:
        return f"rgba(68,232,144,{0.10 + intens*0.58:.2f})"
    return f"rgba(252,92,125,{0.10 + intens*0.58:.2f})"

def _cal_bg(ret: float | None) -> str:
    if ret is None:
        return "rgba(255,255,255,0.04)"
    intens = min(abs(ret) / 4.0, 1.0)
    if ret >= 0:
        return f"rgba(68,232,144,{0.08 + intens*0.50:.2f})"
    return f"rgba(252,92,125,{0.08 + intens*0.50:.2f})"

DOW_ES = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]
MES_ES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
          "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


# ── CSS nuevas reglas (se inyecta en sentinel css) ───────────────────────────
HEATMAP_CSS = """
/* ── HEATMAP: tabla mejorada ─────────────────────────────────── */
.hm-scroll{overflow-x:auto;overflow-y:hidden;padding-bottom:4px;
  scrollbar-width:thin;scrollbar-color:rgba(255,255,255,0.10) transparent}
.hm-table{width:100%;border-collapse:separate;border-spacing:3px;table-layout:fixed;min-width:620px}
.hm-table thead th{font-size:9px;color:var(--muted);padding:0 2px 6px 2px;text-align:center;white-space:nowrap}
.hm-date{display:block;font-size:9px;letter-spacing:.06em;font-weight:700}
.hm-dow{display:block;font-size:8px;color:var(--muted);opacity:.7;margin-top:1px}
.hm-table th.hm-label{text-align:left;font-size:10px;font-weight:700;color:var(--muted);
  white-space:nowrap;padding:0 6px 0 2px;width:120px;min-width:120px;overflow:hidden}
.hm-v{display:block;font-size:11px;font-weight:800;color:var(--ink)}
.hm-rl{display:block;font-size:8px;color:var(--muted);margin-top:1px}
.hm-table td{padding:5px 2px 4px;border-radius:6px;text-align:center;cursor:help;
  transition:opacity .12s,transform .10s;vertical-align:top}
.hm-table td:hover{opacity:.75;transform:scale(1.06)}
.hm-ret{font-size:11px;font-weight:800;line-height:1.1}
.hm-meta{font-size:8px;color:inherit;opacity:.78;margin-top:2px;line-height:1.1;display:none}
.hm-table td:hover .hm-meta{display:block}
.hm-empty .hm-ret{color:var(--muted);font-weight:400}
.hm-no-signal{border:1px dashed rgba(255,255,255,0.14)!important;background:rgba(255,255,255,0.03)!important}
.hm-no-signal .hm-ret{color:var(--muted);font-weight:700}
.hm-no-signal .hm-meta{display:block;color:var(--muted);opacity:.82}
.hm-stale-gap{border:1px solid rgba(252,92,125,0.35)!important;background:rgba(252,92,125,0.08)!important}
.hm-stale-gap .hm-ret{color:#f05070;font-weight:800}
.hm-stale-gap .hm-meta{display:block;color:#f6a6b4;opacity:.9}
.hm-pos .hm-ret{color:#1fcc80}
.hm-neg .hm-ret{color:#f05070}
body.theme-white .hm-pos .hm-ret{color:#0a8060}
body.theme-white .hm-neg .hm-ret{color:#c0203a}
body.theme-white .hm-no-signal{border-color:rgba(10,24,40,0.12)!important;background:rgba(10,24,40,0.03)!important}
body.theme-white .hm-stale-gap{border-color:rgba(192,32,58,0.28)!important;background:rgba(192,32,58,0.08)!important}
/* summary row */
.hm-table tr.hm-summary th{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.08em;padding-top:8px}
.hm-table tr.hm-summary td{border-radius:6px;font-size:10px;font-weight:700;padding:6px 3px;text-align:center;background:rgba(255,255,255,0.04);border-top:1px solid rgba(255,255,255,0.08)}
.hm-sum-pos{color:#1fcc80;display:block;font-size:12px;font-weight:800}
.hm-sum-neg{color:#f05070;display:block;font-size:12px;font-weight:800}
.hm-sum-wr{display:block;font-size:9px;color:var(--muted);margin-top:2px}
.hm-sum-pk{display:block;font-size:8px;color:var(--muted);opacity:.7}
body.theme-white .hm-sum-pos{color:#0a8060}
body.theme-white .hm-sum-neg{color:#c0203a}
/* pending future columns — empty (no picks) */
.hm-pending{opacity:.35;border:1px dashed rgba(255,255,255,0.18)!important;background:rgba(255,255,255,0.02)!important}
.hm-pending .hm-ret{color:var(--muted);font-weight:400}
th.hm-pending-hdr{opacity:.35;font-style:italic}
th.hm-today-hdr{color:#fbbf24!important;opacity:1!important;font-style:normal!important;font-weight:700!important}
/* active pending — picks open, return not yet computed */
.hm-active-pending{border:1px solid rgba(24,232,200,0.45)!important;
  background:rgba(24,232,200,0.07)!important;animation:hm-pulse 2.5s ease-in-out infinite}
.hm-active-pending .hm-ret{color:var(--cyan)!important;font-weight:700!important;font-size:13px!important}
.hm-active-pending .hm-meta{color:var(--cyan)!important;opacity:.85!important}
@keyframes hm-pulse{0%,100%{border-color:rgba(24,232,200,0.45)}50%{border-color:rgba(24,232,200,0.85)}}
body.theme-white .hm-active-pending{background:rgba(0,160,140,0.07)!important;border-color:rgba(0,160,140,0.45)!important}
th.hm-active-pending-hdr{color:var(--cyan)!important;opacity:1!important;font-style:normal!important}
/* today column — picks active, market open, result pending at 19:15 close */
.hm-today{border:1px solid rgba(251,191,36,0.50)!important;background:rgba(251,191,36,0.08)!important;cursor:help}
.hm-today .hm-ret{color:#fbbf24!important;font-weight:700!important;font-size:13px!important}
.hm-today .hm-meta{display:none;color:#fcd34d!important;opacity:.9!important;font-size:7.5px!important;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
.hm-table td.hm-today:hover .hm-meta{display:block}
.hm-today-empty{background:rgba(251,191,36,0.04)!important;border-color:rgba(251,191,36,0.25)!important}
.hm-today-empty .hm-ret{color:var(--muted)!important;font-weight:400!important;font-size:11px!important}
/* variant tabs */
.hm-tabbar{display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap}
.hm-vtab{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);
  border-radius:12px;padding:3px 10px;font-size:10px;font-weight:700;color:var(--muted);
  cursor:pointer;transition:background .14s,color .14s;white-space:nowrap}
.hm-vtab:hover{background:rgba(255,255,255,0.12);color:var(--ink)}
.hm-vtab.active{background:rgba(99,102,241,0.25);border-color:rgba(99,102,241,0.55);color:#a5b4fc}
body.theme-white .hm-vtab{background:rgba(0,0,0,0.05);border-color:rgba(0,0,0,0.15);color:#555}
body.theme-white .hm-vtab.active{background:rgba(99,102,241,0.15);border-color:#6366f1;color:#4338ca}
/* variant panes */
.hm-vpane{display:none}
.hm-vpane.active{display:block}
/* compact mode for wide tables (>20 cols) */
.hm-table.hm-compact td{padding:3px 1px 2px}
.hm-table.hm-compact .hm-ret{font-size:9px}
.hm-table.hm-compact .hm-meta{font-size:7px}
/* variant C trend table */
.hm-trend-table{width:100%;border-collapse:separate;border-spacing:0 3px}
.hm-trend-table th{font-size:9px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.07em;padding:4px 8px;text-align:left;white-space:nowrap}
.hm-trend-table th.hm-r{text-align:right}
.hm-trend-table td{font-size:11px;padding:5px 8px;background:rgba(255,255,255,0.03);vertical-align:middle}
.hm-trend-table tr:first-child td{border-top-left-radius:6px;border-top-right-radius:6px}
.hm-trend-up{color:#1fcc80;font-size:14px}
.hm-trend-dn{color:#f05070;font-size:14px}
.hm-trend-eq{color:var(--muted);font-size:13px}
body.theme-white .hm-trend-up{color:#0a8060}
body.theme-white .hm-trend-dn{color:#c0203a}
/* ── Heatmap inline label stat (ret · WR) ───────────────────── */
.hm-lbl-stat{display:block;font-size:8px;font-weight:700;margin-top:2px;
  white-space:nowrap;letter-spacing:.02em}
.hm-lbl-pos{color:#1fcc80}
.hm-lbl-neg{color:#f05070}
body.theme-white .hm-lbl-pos{color:#0a8060}
body.theme-white .hm-lbl-neg{color:#c0203a}
/* ── LIGA: nueva columna Últ. Rueda + badge legacy ──────────── */
.ult-rueda-td{white-space:nowrap;font-size:12px}
.ult-rueda-td small{display:block;margin-top:1px}
.ba-legacy{background:rgba(180,100,220,0.14);color:#b464dc}
body.theme-white .badge.ba-legacy{background:#f5eeff;color:#7020b0;border:1px solid #a060e040}
.ba-prov{background:rgba(251,191,36,0.18);color:#fbbf24;font-size:8px;padding:1px 4px;vertical-align:middle}
body.theme-white .badge.ba-prov{background:#fffbe0;color:#b45309;border:1px solid #d4960060}
/* ── LIGA: columnas de ventana 30d / 60d / 90d ──────────────────── */
.wnd-td{text-align:center;white-space:nowrap;font-size:11px;padding:3px 6px}
.wnd-wr{display:block;font-size:10px;font-weight:700}
.wnd-ret{display:block;font-size:10px;margin-top:1px}
.wnd-pos{color:#1fcc80}
.wnd-neg{color:#f05070}
.wnd-neu{color:var(--muted)}
body.theme-white .wnd-pos{color:#0a8060}
body.theme-white .wnd-neg{color:#c0203a}
.wnd-na{color:var(--muted);font-style:italic;font-size:10px}
/* ── HEATMAP: metodología legend card ───────────────────────── */
.hm-legend{display:flex;align-items:flex-start;gap:8px;margin-bottom:10px;
  padding:8px 12px;border-radius:8px;border:1px solid rgba(99,102,241,0.30);
  background:rgba(99,102,241,0.07);font-size:10px;line-height:1.5;color:var(--muted)}
.hm-legend-icon{font-size:14px;flex-shrink:0;margin-top:1px}
.hm-legend-text strong{color:var(--ink);font-weight:700;display:block;margin-bottom:3px;font-size:10px;text-transform:uppercase;letter-spacing:.07em}
.hm-legend-steps{display:flex;flex-wrap:wrap;gap:0 10px}
.hm-legend-step{display:flex;align-items:center;gap:4px;white-space:nowrap}
.hm-legend-step .hm-ls-num{background:rgba(99,102,241,0.25);color:#a5b4fc;border-radius:50%;
  width:16px;height:16px;display:inline-flex;align-items:center;justify-content:center;
  font-weight:800;font-size:9px;flex-shrink:0}
.hm-legend-step .hm-ls-txt{font-size:10px}
.hm-legend-arrow{color:rgba(99,102,241,0.60);font-weight:700;font-size:11px;margin:0 2px}
body.theme-white .hm-legend{background:rgba(99,102,241,0.06);border-color:rgba(99,102,241,0.25)}
body.theme-white .hm-legend-step .hm-ls-num{background:#ede9fe;color:#4338ca}
/* heatmap corner label */
.hm-corner-lbl{display:block;font-size:7.5px;color:rgba(99,102,241,0.70);text-transform:uppercase;letter-spacing:.07em;margin-top:3px;font-weight:600}
/* ── KPI STRIP: 4 cards (champion · leader · picks · sistema/semáforo) */
.kpi-strip{grid-template-columns:repeat(4,minmax(0,1fr))!important}
/* ── PICK PRICES: precio actual inline junto a cada ticker abierto ─────────── */
.hc-tk-price{font-size:9px;font-weight:600;color:rgba(255,255,255,.45);margin-left:1px;letter-spacing:.2px}
.svb-tk-price{font-size:10px;font-weight:600;color:rgba(255,255,255,.40);width:52px}
body.theme-white .hc-tk-price{color:rgba(0,0,0,.38)}
body.theme-white .svb-tk-price{color:rgba(0,0,0,.35)}
"""

ROLE_ICON = {"activo": "OBS", "referencia": "REF", "base": "BASE", "observado": "OBS", "legacy_ml": "ML"}
ROLE_BADGE_CLASS = {"activo": "ba-active", "referencia": "ba-ref", "base": "ba-base", "observado": "ba-obs", "legacy_ml": "ba-ml"}
ROLE_SPARK = {"activo": "#18e8c8", "referencia": "#f5b833", "base": "#6ea8cc", "observado": "#44e890", "legacy_ml": "#a882ff"}


def _fmt_pct(value: float | None, digits: int = 2, signed: bool = False) -> str:
    if value is None:
        return "—"
    sign = "+" if signed else ""
    return f"{float(value):{sign}.{digits}f}%"


def _fmt_ratio(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}"


def _fmt_int(value: int | None) -> str:
    return f"{int(value or 0):,}"


def _to_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return 0


def _window_calendar(window: dict | None) -> list[dict]:
    return list((window or {}).get("calendar") or [])


def _entry_tickers(entry: dict | None) -> list[str]:
    return [str(ticker) for ticker in ((entry or {}).get("tickers") or []) if ticker]


def _entry_picks_count(entry: dict | None) -> int:
    picks = _to_int((entry or {}).get("picks"))
    if picks > 0:
        return picks
    tickers = _entry_tickers(entry)
    if tickers:
        return len(tickers)
    evaluated_assets = (entry or {}).get("evaluated_assets") or []
    if isinstance(evaluated_assets, list) and evaluated_assets:
        return len(evaluated_assets)
    return 0


def _window_activity_entries(window: dict | None) -> list[dict]:
    return [
        entry
        for entry in _window_calendar(window)
        if _entry_picks_count(entry) > 0 or entry.get("avg_return_pct") is not None
    ]


def _window_return_entries(window: dict | None) -> list[dict]:
    return [entry for entry in _window_activity_entries(window) if entry.get("avg_return_pct") is not None]


def _window_provisional_days(window: dict | None) -> int:
    return sum(1 for entry in _window_activity_entries(window) if _entry_picks_count(entry) > 0)


def _window_provisional_picks(window: dict | None) -> int:
    return sum(_entry_picks_count(entry) for entry in _window_activity_entries(window))


def _window_provisional_avg_return_pct(window: dict | None) -> float | None:
    values = [float(entry.get("avg_return_pct")) for entry in _window_return_entries(window)]
    if not values:
        return None
    return sum(values) / len(values)


def _window_accuracy_label(window: dict | None, digits: int = 2) -> str:
    accuracy = (window or {}).get("accuracy_pct")
    if accuracy is not None:
        label = _fmt_pct(float(accuracy), digits)
        evaluated = _to_int((window or {}).get("evaluated"))
        if 0 < evaluated < 15:
            label += f" ({evaluated}p)"
        return label
    if _window_provisional_days(window) > 0:
        return "PROV"
    return "—"


def _window_return_label(window: dict | None, digits: int = 3, signed: bool = True) -> str:
    avg_return = (window or {}).get("avg_return_pct")
    if avg_return is not None:
        return _fmt_pct(float(avg_return), digits, signed)
    provisional_avg = _window_provisional_avg_return_pct(window)
    if provisional_avg is not None:
        return _fmt_pct(provisional_avg, digits, signed)
    return "—"


def _window_hits_label(window: dict | None) -> str:
    hits = _to_int((window or {}).get("hits"))
    evaluated = _to_int((window or {}).get("evaluated"))
    if evaluated > 0:
        return f"{_fmt_int(hits)}/{_fmt_int(evaluated)}"
    provisional_picks = _window_provisional_picks(window)
    if provisional_picks > 0:
        return f"prov {_fmt_int(provisional_picks)}"
    return "0/0"


def _window_activity_summary(window: dict | None, *, period_days: object | None = None) -> tuple[str, str]:
    total_days = _to_int((window or {}).get("window_days") or period_days)
    active_days = _to_int((window or {}).get("active_days"))
    evaluated = _to_int((window or {}).get("evaluated"))
    if active_days > 0 or evaluated > 0:
        return f"{_fmt_int(active_days)}/{_fmt_int(total_days)}", f"{_fmt_int(evaluated)} picks"
    provisional_days = _window_provisional_days(window)
    provisional_picks = _window_provisional_picks(window)
    if provisional_days > 0:
        return f"{_fmt_int(provisional_days)}/{_fmt_int(total_days)}", f"{_fmt_int(provisional_picks)} picks prov"
    return f"0/{_fmt_int(total_days)}", "0 picks"


def _row_latest_tickers(row: dict, limit: int = 10) -> list[str]:
    lt_tgt = row.get("latest_target_date") or ""
    cycle_active = bool(lt_tgt and lt_tgt >= datetime.date.today().isoformat())
    tickers = [str(ticker) for ticker in (row.get("latest_tickers") or []) if ticker]
    if tickers and cycle_active:
        return tickers[:limit]
    if not cycle_active:
        return []
    collected: list[str] = []
    for entry in reversed(_window_calendar(row.get("recent_30") or {})):
        recent_tickers = _entry_tickers(entry)
        for ticker in recent_tickers:
            if ticker not in collected:
                collected.append(ticker)
        if len(collected) >= limit:
            break
    return collected[:limit]


def _row_latest_picks(row: dict) -> int:
    latest_picks = _to_int(row.get("latest_picks"))
    if latest_picks > 0:
        return latest_picks
    return len(_row_latest_tickers(row, limit=999))


def _window_has_visible_activity(window: dict | None) -> bool:
    if not window:
        return False
    if window.get("accuracy_pct") is not None or window.get("avg_return_pct") is not None:
        return True
    if _to_int(window.get("evaluated")) > 0 or _to_int(window.get("active_days")) > 0:
        return True
    return _window_provisional_days(window) > 0


def _row_has_visible_activity(row: dict) -> bool:
    if _row_latest_picks(row) > 0:
        return True
    for key in ("equalized_recent", "window", "recent_15", "recent_30", "recent_60", "recent_90"):
        if _window_has_visible_activity(row.get(key) or {}):
            return True
    return False


def _parse_iso_date(value: object) -> datetime.date | None:
    if value in (None, ""):
        return None
    try:
        return datetime.date.fromisoformat(str(value))
    except Exception:
        return None


def _fmt_ddmm(value: object) -> str:
    date_value = _parse_iso_date(value)
    return date_value.strftime("%d/%m") if date_value else "--/--"


def _dashboard_league(snap: dict) -> list[dict]:
    cr = snap.get("competition_recent") or {}
    league = list(cr.get("dashboard_league_equalized") or cr.get("league_equalized") or [])
    visible = [row for row in league if _row_has_visible_activity(row)]
    return visible or league


def _competition_start_iso(snap: dict) -> str | None:
    cr = snap.get("competition_recent") or {}
    candidates: list[object] = [cr.get("competition_start")]
    for row in _dashboard_league(snap):
        eq = row.get("equalized_recent") or row.get("window") or {}
        candidates.extend([eq.get("competition_start"), eq.get("start_date")])
    parsed = [date_value for candidate in candidates if (date_value := _parse_iso_date(candidate)) is not None]
    if not parsed:
        return None
    return min(parsed).isoformat()


def _competition_period_suffix(snap: dict) -> str:
    start_iso = _competition_start_iso(snap)
    return f" (desde {_fmt_ddmm(start_iso)})" if start_iso else ""


def _observed_holiday(year: int, month: int, day: int) -> datetime.date:
    holiday = datetime.date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - datetime.timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + datetime.timedelta(days=1)
    return holiday


def _nth_weekday_of_month(year: int, month: int, weekday: int, nth: int) -> datetime.date:
    first_day = datetime.date(year, month, 1)
    offset = (weekday - first_day.weekday()) % 7
    return first_day + datetime.timedelta(days=offset + (nth - 1) * 7)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> datetime.date:
    if month == 12:
        next_month = datetime.date(year + 1, 1, 1)
    else:
        next_month = datetime.date(year, month + 1, 1)
    cursor = next_month - datetime.timedelta(days=1)
    while cursor.weekday() != weekday:
        cursor -= datetime.timedelta(days=1)
    return cursor


def _easter_sunday(year: int) -> datetime.date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime.date(year, month, day)


_NYSE_HOLIDAY_CACHE: dict[int, set[datetime.date]] = {}


def _nyse_holidays(year: int) -> set[datetime.date]:
    cached = _NYSE_HOLIDAY_CACHE.get(year)
    if cached is not None:
        return cached

    holidays = {
        _observed_holiday(year, 1, 1),
        _nth_weekday_of_month(year, 1, 0, 3),
        _nth_weekday_of_month(year, 2, 0, 3),
        _easter_sunday(year) - datetime.timedelta(days=2),
        _last_weekday_of_month(year, 5, 0),
        _observed_holiday(year, 7, 4),
        _nth_weekday_of_month(year, 9, 0, 1),
        _nth_weekday_of_month(year, 11, 3, 4),
        _observed_holiday(year, 12, 25),
    }
    if year >= 2022:
        holidays.add(_observed_holiday(year, 6, 19))

    _NYSE_HOLIDAY_CACHE[year] = holidays
    return holidays


def _is_nyse_trading_day(day: datetime.date) -> bool:
    return day.weekday() < 5 and day not in _nyse_holidays(day.year)


def _role_badge_card(role: str) -> str:
    cls = ROLE_BADGE_CLASS.get(role, "")
    return f"<span class='badge {cls}'>{_esc(role)}</span>"


def _freshness_badge_card(stale_days: int | None) -> str:
    if stale_days is None:
        return "<span class='badge ba-muted'>sin fecha</span>"
    if stale_days <= 0:
        return "<span class='badge ba-fresh'>al dia</span>"
    if stale_days == 1:
        return "<span class='badge ba-warn'>1 rueda</span>"
    return f"<span class='badge ba-stale'>{int(stale_days)} ruedas</span>"


def _model_bid(version: str) -> str:
    return "mc-" + version.lower().replace("_", "-")


def _sparkline_labels_from_window(window: dict | None) -> list[str]:
    if not window:
        return []
    labels: list[str] = []
    for entry in (window.get("calendar") or []):
        date_text = entry.get("date")
        if date_text:
            labels.append(str(date_text))
    return labels


def _trim_series_and_labels(values: list[float | None], labels: list[str] | None = None) -> tuple[list[float], list[str]]:
    series = [float(v or 0.0) for v in values]
    if not series:
        return [], []
    last = next((idx for idx in range(len(series) - 1, -1, -1) if abs(series[idx]) > 1e-9), -1)
    if last < 0:
        return [], []
    trimmed_series = series[: last + 1]
    trimmed_labels = list(labels or [])[: last + 1]
    return trimmed_series, trimmed_labels


def _sparkline_svg(
    values: list[float],
    stroke: str,
    fill: str | None = None,
    width: int = 260,
    height: int = 60,
    labels: list[str] | None = None,
    title: str | None = None,
    value_format: str = "pct",
    previewable: bool = False,
) -> str:
    series = [float(v) for v in values if v is not None]
    if not series:
        return f"<svg viewBox='0 0 {width} {height}' class='spark'><rect width='{width}' height='{height}' rx='4' fill='rgba(255,255,255,0.03)'/></svg>"
    normalized_labels = list(labels or [])
    if len(normalized_labels) < len(series):
        normalized_labels.extend(f"Punto {idx}" for idx in range(len(normalized_labels) + 1, len(series) + 1))
    lo = min(series)
    hi = max(series)
    span = hi - lo or 1.0
    pts: list[tuple[float, float]] = []
    for idx, value in enumerate(series):
        x = idx * (width - 8) / max(len(series) - 1, 1) + 4
        y = height - 6 - ((value - lo) / span) * (height - 12)
        pts.append((x, y))
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"4,{height-3} " + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + f" {width-4},{height-3}"
    lx, ly = pts[-1]
    fill = fill or stroke
    values_json = _esc(json.dumps([round(float(v), 6) for v in series], ensure_ascii=True))
    labels_json = _esc(json.dumps(normalized_labels[: len(series)], ensure_ascii=True))
    return (
        f"<svg viewBox='0 0 {width} {height}' class='spark' "
        f"data-values='{values_json}' "
        f"data-labels='{labels_json}' "
        f"data-title='{_esc(title or '')}' "
        f"data-format='{_esc(value_format)}' "
        f"data-previewable='{'1' if previewable else '0'}'>"
        f"<polygon points='{area}' fill='{fill}' opacity='0.14'/>"
        f"<polyline points='{line}' fill='none' stroke='{stroke}' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'/>"
        f"<circle cx='{lx:.1f}' cy='{ly:.1f}' r='3' fill='{stroke}'/>"
        "</svg>"
    )


def _sparkline_markup_from_window(
    window: dict | None,
    stroke: str,
    *,
    fill: str | None = None,
    width: int = 260,
    height: int = 60,
    title: str | None = None,
    value_format: str = "pct",
    previewable: bool = False,
) -> str:
    labels = _sparkline_labels_from_window(window)
    raw_series = [float(value or 0.0) for value in ((window or {}).get("spark_avg_return_pct") or [])]
    series, labels = _trim_series_and_labels(raw_series, labels)
    if not series and raw_series:
        series = raw_series
        labels = labels or _sparkline_labels_from_window(window)
    if not series:
        derived = [
            (float(entry.get("avg_return_pct")), str(entry.get("date")))
            for entry in _window_return_entries(window)
            if entry.get("date")
        ]
        series = [value for value, _ in derived]
        labels = [label for _, label in derived]
    return _sparkline_svg(
        _cumulative(series),
        stroke,
        fill=fill,
        width=width,
        height=height,
        labels=labels,
        title=title,
        value_format=value_format,
        previewable=previewable,
    )


def _cumulative(values: list[float | None]) -> list[float]:
    total = 0.0
    out: list[float] = []
    for value in values:
        total += float(value or 0.0)
        out.append(round(total, 4))
    return out


def _row_window(row: dict, key: str) -> dict:
    return (row.get(key) or {})


def _latest_closed_tickers(row: dict) -> list[str]:
    cal = (_row_window(row, "recent_30").get("calendar") or [])
    for entry in reversed(cal):
        if entry.get("avg_return_pct") is not None and entry.get("tickers"):
            return list(entry.get("tickers") or [])
    return []


def _hero_live_tickers(snap: dict) -> list[str]:
    active_run = (snap.get("active") or {}).get("active_run") or {}
    picks = list(active_run.get("results_d") or []) + list(active_run.get("results_e") or [])
    return [str(item.get("ticker")) for item in picks if item.get("ticker")]


def _leader_by_return(rows: list[dict]) -> dict | None:
    valid = [row for row in rows if (_row_window(row, "equalized_recent").get("avg_return_pct") is not None)]
    if not valid:
        return rows[0] if rows else None
    return max(valid, key=lambda row: float(_row_window(row, "equalized_recent").get("avg_return_pct") or -1e18))


def _render_topbar_meta(snap: dict) -> str:
    active = snap.get("active") or {}
    active_run = active.get("active_run") or {}
    latest_market = latest_market_date(snap) or "—"
    generated_at = snap.get("generated_at", "")
    generated_fmt = generated_at
    if generated_at:
        try:
            dt_utc = datetime.datetime.fromisoformat(generated_at.replace("Z", ""))
            dt_ar  = dt_utc - datetime.timedelta(hours=3)  # AR = UTC-3 fijo, sin DST
            utc_str = dt_utc.strftime("%Y-%m-%d %H:%M UTC")
            ar_label = dt_ar.strftime("%H:%M AR") if dt_ar.date() == dt_utc.date() else dt_ar.strftime("%H:%M AR") + " (" + dt_ar.strftime("%m-%d") + ")"
            generated_fmt = utc_str + "  ·  " + ar_label
        except ValueError:
            pass
    target = active_run.get("prediction_for")
    if not target and latest_market != "—":
        next_sessions = _next_trading_days(latest_market, 1)
        target = next_sessions[0] if next_sessions else None
    regime = str(active_run.get("regime_label") or "GLOBAL").upper()
    regime_cls = {"PELIGRO": "regime-peligro", "SEGURO": "regime-seguro"}.get(regime, "regime-global")
    return (
        f'<span class="tb-pill" id="generated-at-pill" data-ts="{generated_at if generated_at.endswith("Z") else generated_at + "Z"}">Generado {generated_fmt}</span>'
        f'<span class="tb-pill" id="meta-mercado">Mercado {latest_market}</span>'
        f'<span class="tb-pill" id="meta-target">Target {target or "—"}</span>'
        f'<span class="tb-pill tb-pill-regime {regime_cls}" id="meta-regime">{regime}</span>'
    )


def _render_regime_pill(snap: dict) -> str:
    active_run = (snap.get("active") or {}).get("active_run") or {}
    regime = str(active_run.get("regime_label") or "GLOBAL").upper()
    breadth = active_run.get("breadth_pct")
    regime_cls = {"PELIGRO": "regime-peligro", "SEGURO": "regime-seguro"}.get(regime, "regime-global")
    breadth_txt = f"breadth {float(breadth):.1f}%" if breadth is not None else "breadth —"
    return (
        f'<div class="regime-pill {regime_cls}">'
        '<span class="rp-dot"></span>'
        f"<span>{_esc(regime)}</span>"
        f'<span class="rp-breadth">{_esc(breadth_txt)}</span>'
        "</div>"
    )


def _render_sidebar_datos_db(snap: dict) -> str:
    integrity = snap.get("integrity") or {}
    return (
        '<div class="sd-body">'
        f'<div class="kl"><span>Mercado</span><strong>{_esc(integrity.get("latest_market_date") or "—")}</strong></div>'
        f'<div class="kl"><span>Predictions</span><strong>{_fmt_int(integrity.get("predictions_count"))}</strong></div>'
        f'<div class="kl"><span>Outcomes</span><strong>{_fmt_int(integrity.get("outcomes_count"))}</strong></div>'
        f'<div class="kl"><span>Regimes</span><strong>{_fmt_int(integrity.get("regimes_count"))}</strong></div>'
        f'<div class="kl"><span>Modelos</span><strong>{_fmt_int(integrity.get("prediction_models"))}</strong></div>'
        "</div>"
    )


def _render_sidebar_config(snap: dict) -> str:
    cr = snap.get("competition_recent") or {}
    active = snap.get("active") or {}
    return (
        '<div class="sd-body">'
        f'<div class="kl"><span>Motor Experimental</span><strong>V{_fmt_int(active.get("active_version"))}</strong></div>'
        f'<div class="kl"><span>Referencia</span><strong>V{_fmt_int(active.get("reference_version"))}</strong></div>'
        f'<div class="kl"><span>Per\u00edodo comp.</span><strong>{_fmt_int(cr.get("equalized_days"))} ruedas</strong></div>'
        f'<div class="kl"><span>Desde</span><strong>02/03/2026</strong></div>'
        "</div>"
    )


# ── SEMÁFORO DE DATOS ─────────────────────────────────────────────────────────

_VERIFY_PAYLOAD_PATH = ROOT / "analisis" / "verify_payload.json"


def _load_verify_payload() -> dict:
    """Lee el payload de auditoría si existe. Retorna dict vacío si no está listo."""
    try:
        if _VERIFY_PAYLOAD_PATH.exists():
            return json.loads(_VERIFY_PAYLOAD_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _render_kpi_sistema_card(ts_with_z: str = "", regime: str = "SEGURO", regime_color: str = "var(--green)", generated_at: str = "") -> str:
    """Card unificado Sistema (Datos + Sync) con tooltip hover."""
    vp = _load_verify_payload()
    if not vp:
        return (
            f'<div class="kpi-card editable-block" id="kpi-actualizacion"'
            f' data-bid="kpi-verify" data-blabel="KPI Sistema" data-ts="{ts_with_z}">'
            '<div class="kc-label">Sistema</div>'
            '<div class="kc-value" id="kpi-fresh-value" style="color:var(--muted)">\u2014</div>'
            f'<div class="kc-sub" id="kpi-fresh-sub" style="margin-top:4px">gen. {ts_with_z[:16].replace("T", " ") if ts_with_z else "\u2014"} UTC</div>'
            f'<div class="kc-sub" id="kpi-fresh-regime" style="margin-top:4px;font-weight:700;color:{regime_color}">{regime}</div>'
            "</div>"
        )
    score = vp.get("confidence_score", 0)
    status = vp.get("status", "error")
    summary = vp.get("summary") or {}
    checks = vp.get("checks") or {}

    # Color según score
    if score >= 85:
        color = "var(--green)"
        dot = "🟢"
    elif score >= 65:
        color = "#f5b833"
        dot = "🟡"
    else:
        color = "var(--red, #fc5c7d)"
        dot = "🔴"

    # Texto de sublínea resumida
    fresh_days = summary.get("freshness_stale_days")
    fresh_date = summary.get("freshness_latest_date") or "—"
    open_ok = summary.get("open_mtm_ok", 0)
    open_v = summary.get("open_mtm_verified", 0)
    out_ok = summary.get("outcomes_ok", 0)
    out_v = summary.get("outcomes_verified", 0)
    unclosed = summary.get("unclosed_count", 0)

    fresh_label = (
        f"precios hoy" if fresh_days == 0
        else f"+{fresh_days}d atraso" if fresh_days
        else "—"
    )
    mtm_label = f"MTM {open_ok}/{open_v} ok" if open_v else "sin abiertos"
    out_label = f"hist {out_ok}/{out_v} ok" if out_v else ""
    orphan_label = f"· {unclosed} sin cerrar" if unclosed else ""

    # data-verify para que JS del dashboard pueda expandir detalle
    open_warn = summary.get("open_mtm_warn", 0)
    open_crit = summary.get("open_mtm_crit", 0)
    cross = summary.get("cross_inconsistencies", 0)
    data_verify = json.dumps({
        "score": score,
        "status": status,
        "freshness": {
            "date": fresh_date,
            "stale": fresh_days,
        },
        "open_mtm": {"ok": open_ok, "verified": open_v,
                     "warn": open_warn,
                     "crit": open_crit},
        "outcomes": {"ok": out_ok, "verified": out_v,
                     "warn": summary.get("outcomes_warn", 0),
                     "crit": summary.get("outcomes_crit", 0)},
        "unclosed": unclosed,
        "cross_inconsistencies": cross,
    }, separators=(",", ":"))

    # ── Fecha legible en español (hoy 6 may) ──────────────────────────────────
    _months_es = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]
    if fresh_days == 0:
        try:
            _dt = datetime.date.fromisoformat(str(fresh_date))
            fresh_human = f"hoy {_dt.day} {_months_es[_dt.month - 1]}"
        except Exception:
            fresh_human = "hoy"
    elif fresh_days:
        fresh_human = f"+{fresh_days} d&iacute;as de atraso"
    else:
        fresh_human = "—"

    # ── Líneas de detalle C1 ───────────────────────────────────────────────────
    _ok  = '<span style="color:var(--green,#44e890)">&#10003;</span>'
    _wrn = '<span style="color:#f5b833">&#9888;</span>'
    _crt = '<span style="color:var(--red,#fc5c7d)">&#9888;</span>'
    detail_lines = [
        f'{_ok} Precios al d&iacute;a ({fresh_human}) &mdash; todos los modelos',
        f'{_ok} {open_ok}/{open_v} picks activos verificados',
    ]
    if open_crit > 0:
        detail_lines.append(
            f'<span style="color:var(--red,#fc5c7d)">&nbsp;&nbsp;&nbsp;{_crt} {open_crit} con diferencia importante (revisar)</span>'
        )
    elif open_warn > 0:
        detail_lines.append(
            f'<span style="color:#f5b833">&nbsp;&nbsp;&nbsp;{_wrn} {open_warn} con dif. menor de precio (&lt;1%)</span>'
        )
    if out_v > 0:
        detail_lines.append(f'{_ok} {out_ok}/{out_v} operaciones cerradas confirmadas')
    if unclosed == 0:
        detail_lines.append(f'{_ok} Sin picks pendientes de cerrar')
    else:
        detail_lines.append(
            f'<span style="color:#f5b833">&nbsp;&nbsp;&nbsp;{_wrn} {unclosed} picks sin cerrar (revisar)</span>'
        )
    if cross > 0:
        detail_lines.append(
            f'<span style="color:#f5b833">&nbsp;&nbsp;&nbsp;{_wrn} {cross} conflictos entre modelos</span>'
        )
    detail_html = "<br>".join(detail_lines)

    # ── Fecha en español para el tooltip ──────────────────────────────────────
    _days_es_full = ["lunes","martes","mi\u00e9rcoles","jueves","viernes","s\u00e1bado","domingo"]
    _months_es_full = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto",
                       "septiembre","octubre","noviembre","diciembre"]
    fecha_tooltip = "hoy"
    fecha_footer = "\u2014"
    if generated_at:
        try:
            _gdt = datetime.datetime.fromisoformat(generated_at.replace("Z",""))
            _gar = _gdt - datetime.timedelta(hours=3)
            _dia = f"{_days_es_full[_gar.weekday()]} {_gar.day} de {_months_es_full[_gar.month-1]}"
            fecha_tooltip = (
                f"{_dia} a las "
                f'<b style="color:#eef4fb">{_gar.strftime("%H:%M")} AR</b>'
                f" ({_gdt.strftime('%H:%M')} UTC)"
            )
            fecha_footer = (
                f"{_gdt.strftime('%Y-%m-%d')} {_gdt.strftime('%H:%M')} UTC"
                f" \u00b7 {_gar.strftime('%H:%M')} AR"
            )
        except Exception:
            pass

    # ── Pills ──────────────────────────────────────────────────────────────────
    _ps = ('style="font-size:0.6rem;font-weight:700;padding:2px 7px;border-radius:20px;'
           'background:rgba(68,232,144,0.12);color:var(--green,#44e890);'
           'border:1px solid rgba(68,232,144,0.25)"')
    pill_tickers = f'<span {_ps}>{open_v}/{open_v} &#10003; tickers</span>'
    pill_hist    = f'<span {_ps}>{out_ok}/{out_v} hist.</span>' if out_v else ''

    # ── Tooltip lines ──────────────────────────────────────────────────────────
    _dg = ('<span style="width:6px;height:6px;border-radius:50%;'
           'background:var(--green,#44e890);flex-shrink:0;margin-top:6px;display:inline-block"></span>')
    _dm = ('<span style="width:6px;height:6px;border-radius:50%;'
           'background:#6585a8;flex-shrink:0;margin-top:6px;display:inline-block"></span>')
    _ro = '<div style="font-size:0.7rem;line-height:1.8;display:flex;align-items:flex-start;gap:8px'
    tip = [
        (f'<div style="font-size:0.65rem;color:var(--accent,#18e8c8);margin-bottom:10px;'
         f'font-weight:700;letter-spacing:0.08em">'
         f'{score:.0f}% &mdash; datos &iacute;ntegros y al d&iacute;a</div>'),
        f'{_ro}">{_dg}<span>Cotizaciones al {fecha_tooltip}</span></div>',
        (f'{_ro};margin-top:6px">{_dg}'
         f'<span><b style="color:#eef4fb">{open_v} de {open_v} tickers activos</b>'
         f' verificados contra precio real de mercado</span></div>'),
    ]
    if open_warn + open_crit > 0:
        _wn = open_warn + open_crit
        tip.append(
            f'{_ro};margin-top:2px;padding-left:14px">{_dm}'
            f'<span style="color:#6585a8">{_wn} ticker{"s" if _wn > 1 else ""}'
            f' con diferencia &lt;1% &mdash; ruido normal de mercado</span></div>'
        )
    if out_v > 0:
        tip.append(
            f'{_ro};margin-top:6px">{_dg}'
            f'<span><b style="color:#eef4fb">{out_ok} de {out_v} operaciones cerradas</b>'
            f' tienen resultado final registrado (ganada\u00a0/\u00a0perdida)</span></div>'
        )
    tip.append(
        f'<div style="margin-top:10px;padding-top:8px;border-top:1px solid #1e2d42;'
        f'font-size:0.62rem;color:#6585a8">'
        f'&Uacute;ltima verificaci\u00f3n \u00b7 {fecha_footer}'
        f' \u00b7 r\u00e9gimen Mercado'
        f' <b style="color:var(--green,#44e890)">{regime}</b></div>'
    )
    tip_html = "".join(tip)

    # position:fixed + JS-calculated coords → escapa cualquier overflow:hidden ancestral
    _tip_show = (
        "clearTimeout(window._kpiTh);"
        "var t=this.querySelector('.kpi-sistema-tooltip');"
        "if(t){"
        "var r=this.getBoundingClientRect();"
        "t.style.position='fixed';"
        "t.style.top=(r.bottom+6)+'px';"
        "t.style.left=Math.max(8,Math.min(r.left+r.width/2-155,window.innerWidth-318))+'px';"
        "t.style.transform='none';"
        "t.style.opacity='1';"
        "t.style.pointerEvents='auto';}"
    )
    _tip_hide = (
        "var el=this;window._kpiTh=setTimeout(function(){"
        "var t=el.querySelector('.kpi-sistema-tooltip');"
        "if(t){t.style.opacity='0';t.style.pointerEvents='none';}},300);"
    )
    _tooltip_enter = "clearTimeout(window._kpiTh)"
    _tooltip_leave = (
        "var t=this;window._kpiTh=setTimeout(function(){"
        "t.style.opacity='0';t.style.pointerEvents='none';},100)"
    )
    return (
        f'<div class="kpi-card editable-block kpi-sistema-card" id="kpi-actualizacion"'
        f' data-bid="kpi-sistema" data-blabel="KPI Sistema" data-ts="{ts_with_z}"'
        f' data-verify=\'{data_verify}\''
        f' onmouseenter="{_tip_show}" onmouseleave="{_tip_hide}"'
        f' style="position:relative;overflow:visible;z-index:200">'
        '<div class="kc-label">Sistema'
        ' <span style="font-size:0.58rem;color:var(--muted,#6585a8);'
        'border:1px solid var(--border,#1e2d42);border-radius:50%;width:13px;height:13px;'
        'display:inline-flex;align-items:center;justify-content:center;'
        'vertical-align:middle;cursor:default" title="Hover para ver detalles">i</span>'
        '</div>'
        f'<div class="kc-value" style="color:{color}">{score:.0f}%</div>'
        f'<div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:4px">'
        f'{pill_tickers}{pill_hist}</div>'
        '<div class="kc-sub" style="margin-top:5px;font-size:0.65rem">actualizado'
        ' <span id="kpi-fresh-value" style="color:var(--green,#44e890)">&mdash;</span>'
        ' &middot; Mercado &middot; r&eacute;gimen'
        f' <span id="kpi-fresh-regime" style="font-weight:700;color:{regime_color}">{regime}</span>'
        '</div>'
        f'<div class="kpi-sistema-tooltip"'
        f' onmouseenter="{_tooltip_enter}"'
        f' onmouseleave="{_tooltip_leave}"'
        ' style="position:fixed;top:0;left:0;width:310px;background:#141e30;'
        'border:1px solid #1e2d42;border-radius:10px;padding:14px 16px;z-index:9999;'
        'opacity:0;pointer-events:none;transition:opacity 0.18s ease;'
        'box-shadow:0 8px 32px rgba(0,0,0,0.55)">'
        f'{tip_html}'
        '</div>'
        '</div>'
    )
def _render_kpi_strip(snap: dict) -> str:
    cr = snap.get("competition_recent") or {}
    league = _dashboard_league(snap)
    if not league:
        return ""
    active = snap.get("active") or {}
    integrity = snap.get("integrity") or {}
    champion_ver = f"V{active.get('active_version')}"
    champion = next((row for row in league if row.get("version") == champion_ver), league[0])
    leader = league[0]
    champion_rank = cr.get("rank_equalized", {}).get(champion_ver, champion.get("rank"))
    champion_eq = _row_window(champion, "equalized_recent")
    leader_eq = _row_window(leader, "equalized_recent")
    live_tickers = _hero_live_tickers(snap)
    coverage = ((integrity.get("coverage_last_30") or {}).get("predictions") or {})
    covered = coverage.get("covered_days")
    expected = coverage.get("expected_days")
    active_run = active.get("active_run") or {}
    breadth = active_run.get("breadth_pct")
    regime = str(active_run.get("regime_label") or "GLOBAL").upper()
    generated_at = snap.get("generated_at", "")
    ts_with_z = (generated_at if generated_at.endswith("Z") else generated_at + "Z") if generated_at else ""
    generated_fmt = generated_at
    if generated_at:
        try:
            dt_utc = datetime.datetime.fromisoformat(generated_at.replace("Z", ""))
            dt_ar  = dt_utc - datetime.timedelta(hours=3)  # AR = UTC-3 fijo, sin DST
            utc_str = dt_utc.strftime("%Y-%m-%d %H:%M UTC")
            ar_label = dt_ar.strftime("%H:%M AR") if dt_ar.date() == dt_utc.date() else dt_ar.strftime("%H:%M AR") + " (" + dt_ar.strftime("%m-%d") + ")"
            generated_fmt = utc_str + "  ·  " + ar_label
        except ValueError:
            pass
    latest_market = latest_market_date(snap) or "\u2014"
    target = active_run.get("prediction_for") or "\u2014"
    regime_color = "var(--green)" if regime == "SEGURO" else "#f5b833" if regime == "PELIGRO" else "var(--muted)"
    _cards_before = (
        '<div class="kpi-card accent-cyan editable-block" data-bid="kpi-champion" data-blabel="KPI Champion">'
        '<div class="kc-label">Motor Experimental</div>'
        f'<div class="kc-value">{_esc(champion_ver)}</div>'
        f'<div class="kc-sub">WR {_window_accuracy_label(champion_eq)} · ret {_fmt_pct(champion_eq.get("avg_return_pct"), 3, True)} · #{_esc(champion_rank)}</div>'
        "</div>"
        '<div class="kpi-card accent-gold editable-block" data-bid="kpi-leader" data-blabel="KPI Líder">'
        '<div class="kc-label">Champion #1</div>'
        f'<div class="kc-value">{_esc(leader.get("version"))}</div>'
        f'<div class="kc-sub">WR {_window_accuracy_label(leader_eq)} · ret {_fmt_pct(leader_eq.get("avg_return_pct"), 3, True)}</div>'
        "</div>"
        '<div class="kpi-card accent-green editable-block" data-bid="kpi-picks" data-blabel="KPI Picks">'
        '<div class="kc-label">Picks hoy</div>'
        f'<div class="kc-value">{_fmt_int(len(live_tickers))}</div>'
        f'<div class="kc-sub">{_esc(regime)} · breadth {_fmt_ratio(breadth, 1)}%</div>'
        "</div>"
    )
    return _cards_before + _render_kpi_sistema_card(ts_with_z=ts_with_z, regime=regime, regime_color=regime_color, generated_at=generated_at)


def _hero_card_html(row: dict, *, label: str, card_class: str, subtitle: str, picks_override: int | None = None, live_override: list[str] | None = None) -> str:
    role = str(row.get("role") or "")
    eq = _row_window(row, "equalized_recent")
    recent = _row_window(row, "recent_30")
    version = str(row.get("version") or "")
    spark = _sparkline_markup_from_window(
        recent,
        ROLE_SPARK.get(role, "#6ea8cc"),
        title=f"{version} | 30 ruedas",
        value_format="pct",
    )
    rank = row.get("rank") or row.get("rank_equalized") or "—"
    picks_count = picks_override if picks_override is not None else int(row.get("latest_picks") or 0)
    closed = _latest_closed_tickers(row)
    _lt_tgt = row.get("latest_target_date") or ""
    if live_override is not None:
        live = live_override
    elif _lt_tgt and _lt_tgt >= datetime.date.today().isoformat():
        live = list(row.get("latest_tickers") or [])
    else:
        live = []
        picks_count = 0
    best = recent.get("best_day_return_pct")
    worst = recent.get("worst_day_return_pct")
    return (
        f'<div class="hero-card {card_class}">'
        '<div class="hc-top">'
        f"<span class=\"hc-label\">{_esc(label)}</span>"
        f"{_role_badge_card(role)}"
        "</div>"
        '<div class="hc-title-row">'
        f"<span class=\"hc-ver\">{_esc(version)}</span>"
        f"<span class=\"hc-sub\">{_esc(subtitle)}</span>"
        "</div>"
        f"<div class=\"hc-spark-wrap\">{spark}</div>"
        '<div class="hc-big-row">'
        f'<div><div class="hc-big-num hc-accent-val">{_window_accuracy_label(eq)}</div><div class="hc-big-lbl">Win Rate igualada</div></div>'
        f'<div><div class="hc-big-num">{_fmt_pct(eq.get("avg_return_pct"), 2, True)}</div><div class="hc-big-lbl">Ret. promedio/trade</div></div>'
        "</div>"
        '<div class="hc-stats">'
        f'<div class="hc-stat"><span>Hits</span><strong>{_fmt_int(eq.get("hits"))}/{_fmt_int(eq.get("evaluated"))}</strong></div>'
        f'<div class="hc-stat"><span>Picks hoy</span><strong>{_fmt_int(picks_count)}</strong></div>'
        f'<div class="hc-stat"><span>Mejor rueda</span><strong class="pos">{_fmt_pct(best, 2, True)}</strong></div>'
        f'<div class="hc-stat"><span>Peor rueda</span><strong class="neg">{_fmt_pct(worst, 2, True)}</strong></div>'
        f'<div class="hc-stat"><span>Rank liga</span><strong>#{_esc(rank)}</strong></div>'
        "</div>"
        '<div class="hc-picks">'
        '<div class="hc-picks-row">'
        '<div class="hc-picks-lbl">Anteriores cerrados</div>'
        f'<div class="hc-picks-prev">{_esc(" · ".join(closed[:6]) or "—")}</div>'
        "</div>"
        '<div class="hc-picks-row">'
        f'<div class="hc-picks-lbl">Vigentes activos · {_fmt_int(picks_count)}</div>'
        f'<div class="hc-picks-live">{_esc(" · ".join(live[:8]) or "—")}</div>'
        "</div>"
        "</div>"
        "</div>"
    )


def _render_hero_panel(snap: dict) -> str:
    cr = snap.get("competition_recent") or {}
    league = _dashboard_league(snap)
    if not league:
        return ""
    active = snap.get("active") or {}
    champion_ver = f"V{active.get('active_version')}"
    eq_days = _fmt_int(cr.get("equalized_days"))
    period_suffix = _competition_period_suffix(snap)
    rank1 = league[0] if len(league) > 0 else {}
    rank2 = league[1] if len(league) > 1 else {}
    rank3 = league[2] if len(league) > 2 else {}
    champion_live = _hero_live_tickers(snap)
    return (
        '<div class="panel-head">'
        '<div>'
        '<div class="panel-label">Podio de rendimiento</div>'
        f'<h2 class="panel-title">Top 3 ranking global · Período competencia {eq_days} ruedas{period_suffix}</h2>'
        "</div>"
        "</div>"
        '<div class="hero-row">'
        + _hero_card_html(
            rank1,
            label="🥇 Champion 1°",
            card_class="hc-green",
            subtitle=f"Ranking #1 · {eq_days} ruedas",
        )
        + _hero_card_html(
            rank2,
            label="🥈 2°",
            card_class="hc-purple",
            subtitle=f"Ranking #2 · {eq_days} ruedas",
        )
        + _hero_card_html(
            rank3,
            label="🥉 3°",
            card_class="hc-cyan",
            subtitle=f"Ranking #3 · {eq_days} ruedas",
        )
        + "</div>"
    )


def _render_liga_tab2_tbody(snap: dict) -> str:
    league = _dashboard_league(snap)
    rows = []
    _tab2_today = datetime.date.today().isoformat()
    for row in league:
        eq = _row_window(row, "equalized_recent")
        recent = _row_window(row, "recent_30")
        _tab2_lt_tgt = row.get("latest_target_date") or ""
        _tab2_tks = (row.get("latest_tickers") or [])[:6] if (_tab2_lt_tgt and _tab2_lt_tgt >= _tab2_today) else []
        rows.append(
            "<tr>"
            f"<td><strong>{_esc(row.get('version'))}</strong> {_role_badge_card(str(row.get('role') or ''))}</td>"
            f"<td>{_freshness_badge_card(row.get('stale_market_days'))}</td>"
            f"<td>{_window_accuracy_label(eq)} / {_fmt_pct(eq.get('avg_return_pct'), 3, True)}</td>"
            f"<td>{_fmt_int(eq.get('active_days'))}/{_fmt_int((snap.get('competition_recent') or {}).get('equalized_days'))} · {_fmt_int(eq.get('evaluated'))}</td>"
            f"<td>{_window_accuracy_label(recent)} / {_fmt_pct(recent.get('avg_return_pct'), 3, True)}</td>"
            f"<td>{_fmt_int(recent.get('active_days'))}/30 · {_fmt_int(recent.get('evaluated'))}</td>"
            f"<td class='muted-td ticker-list'>{_esc(', '.join(_tab2_tks) or 'Sin picks')}</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_legacy_grid(snap: dict) -> str:
    """Build model-card HTML for legacy-panel (legacy_ml role only)."""
    league = _dashboard_league(snap)
    ml_rows = [m for m in league if str(m.get("role") or "") == "legacy_ml"]
    cards = []
    for row in ml_rows:
        role = "legacy_ml"
        version = str(row.get("version") or "")
        eq = _row_window(row, "equalized_recent")
        recent = _row_window(row, "recent_30")
        latest_tickers = _row_latest_tickers(row, limit=10)
        eq_wr_css = "pos" if eq.get("accuracy_pct") is not None and float(eq.get("accuracy_pct") or 0) >= 60 else ""
        cards.append(
            f"<article class='model-card editable-block' data-bid='{_model_bid(version)}' data-blabel='{_esc(version)}'>"
            "<div class='mc-head'>"
            f"<div class='mc-title'>{_esc(version)}</div>"
            f"<div class='mc-badges'>{_role_badge_card(role)} {_freshness_badge_card(row.get('stale_market_days'))}</div>"
            f"<div class='rank-num mc-rank'>#{_fmt_int(row.get('rank'))}</div>"
            "</div>"
            f"<div class='mc-spark'>{_sparkline_markup_from_window(recent, ROLE_SPARK.get(role, '#6ea8cc'), title=f'{version} | curva 30 ruedas', value_format='pct')}</div>"
            "<div class='mc-kpis'>"
            f"<div class='mk'><span>WR</span><strong class='{eq_wr_css}'>{_window_accuracy_label(eq)}</strong></div>"
            f"<div class='mk'><span>Ret</span><strong>{_window_return_label(eq)}</strong></div>"
            f"<div class='mk'><span>Hits</span><strong>{_window_hits_label(eq)}</strong></div>"
            f"<div class='mk'><span>Picks</span><strong>{_fmt_int(_row_latest_picks(row))}</strong></div>"
            "</div>"
            f"<div class='mc-tickers'>{_esc(', '.join(latest_tickers) or 'Sin picks recientes')}</div>"
            "<details class='mc-detail'><summary>Mas datos</summary><div class='mc-detail-body'>"
            f"<div class='kl'><span>30 ruedas</span><strong>{_window_accuracy_label(recent)} / {_window_return_label(recent)}</strong></div>"
            f"<div class='kl'><span>Mejor rueda</span><strong>{_fmt_pct(recent.get('best_day_return_pct'), 2, True)}</strong></div>"
            f"<div class='kl'><span>Peor rueda</span><strong>{_fmt_pct(recent.get('worst_day_return_pct'), 2, True)}</strong></div>"
            f"<div class='kl'><span>Universo</span><strong>{_fmt_int(row.get('unique_tickers'))} tickers</strong></div>"
            f"<div class='kl'><span>Ultima fecha</span><strong>{_esc(row.get('last_date') or '—')}</strong></div>"
            "</div></details></article>"
        )
    return "".join(cards)


def _render_overlap_table_content(snap: dict) -> str:
    """Build thead+tbody for om-table (without outer <table> tags)."""
    ovl = snap.get("overlap") or {}
    labels = ovl.get("labels") or []
    matrix = ovl.get("matrix") or []
    visible_versions = {str(row.get("version") or "") for row in _dashboard_league(snap)}
    if labels and matrix and visible_versions:
        keep_indices = [idx for idx, label in enumerate(labels) if str(label) in visible_versions]
        if keep_indices:
            labels = [labels[idx] for idx in keep_indices]
            trimmed_rows = []
            for idx in keep_indices:
                row_vals = list(matrix[idx]) if idx < len(matrix) and isinstance(matrix[idx], (list, tuple)) else []
                trimmed_rows.append([row_vals[col_idx] if col_idx < len(row_vals) else None for col_idx in keep_indices])
            matrix = trimmed_rows
    if not labels or not matrix:
        return ""

    def _cell_bg(v: float) -> str:
        return f"rgba(24,232,200,{round(0.08 + v * 0.55, 2)})"

    def _render_cell(value: object) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return "<td class='om-missing'>--</td>"
        return f"<td style='background:{_cell_bg(numeric)}'>{numeric:.2f}</td>"

    header = "<thead><tr><th></th>" + "".join(f"<th>{_esc(lbl)}</th>" for lbl in labels) + "</tr></thead>"
    rows = []
    for i, row_vals in enumerate(matrix):
        lbl = labels[i] if i < len(labels) else str(i)
        values = list(row_vals) if isinstance(row_vals, (list, tuple)) else []
        if len(values) < len(labels):
            values.extend([None] * (len(labels) - len(values)))
        cells = "".join(_render_cell(value) for value in values[: len(labels)])
        rows.append(f"<tr><th class='om-label'>{_esc(lbl)}</th>{cells}</tr>")
    return header + "<tbody>" + "".join(rows) + "</tbody>"


def _render_models_grid(snap: dict) -> str:
    league = _dashboard_league(snap)
    cards = []
    for row in league:
        role = str(row.get("role") or "")
        if role == "legacy_ml":
            continue  # ML models go to the legacy panel, not here
        version = str(row.get("version") or "")
        eq = _row_window(row, "equalized_recent")
        recent = _row_window(row, "recent_30")
        _mg_lt_tgt = row.get("latest_target_date") or ""
        _mg_tks = (row.get("latest_tickers") or [])[:10] if (_mg_lt_tgt and _mg_lt_tgt >= datetime.date.today().isoformat()) else []
        cards.append(
            f"<article class='model-card editable-block' data-bid='{_model_bid(version)}' data-blabel='{_esc(version)}'>"
            "<div class='mc-head'>"
            f"<div class='mc-title'>{_esc(version)}</div>"
            f"<div class='mc-badges'>{_role_badge_card(role)} {_freshness_badge_card(row.get('stale_market_days'))}</div>"
            f"<div class='rank-num mc-rank'>#{_fmt_int(row.get('rank'))}</div>"
            "</div>"
            f"<div class='mc-spark'>{_sparkline_markup_from_window(recent, ROLE_SPARK.get(role, '#6ea8cc'), title=f'{version} | curva 30 ruedas', value_format='pct')}</div>"
            "<div class='mc-kpis'>"
            f"<div class='mk'><span>WR</span><strong class='{'pos' if (eq.get('accuracy_pct') or 0) >= 60 else ''}'>{_window_accuracy_label(eq)}</strong></div>"
            f"<div class='mk'><span>Ret</span><strong>{_fmt_pct(eq.get('avg_return_pct'), 3, True)}</strong></div>"
            f"<div class='mk'><span>Hits</span><strong>{_fmt_int(eq.get('hits'))}/{_fmt_int(eq.get('evaluated'))}</strong></div>"
            f"<div class='mk'><span>Picks</span><strong>{_fmt_int(row.get('latest_picks'))}</strong></div>"
            "</div>"
            f"<div class='mc-tickers'>{_esc(', '.join(_mg_tks) or 'Sin picks recientes')}</div>"
            "<details class='mc-detail'><summary>Mas datos</summary><div class='mc-detail-body'>"
            f"<div class='kl'><span>30 ruedas</span><strong>{_window_accuracy_label(recent)} / {_fmt_pct(recent.get('avg_return_pct'), 3, True)}</strong></div>"
            f"<div class='kl'><span>Mejor rueda</span><strong>{_fmt_pct(recent.get('best_day_return_pct'), 2, True)}</strong></div>"
            f"<div class='kl'><span>Peor rueda</span><strong>{_fmt_pct(recent.get('worst_day_return_pct'), 2, True)}</strong></div>"
            f"<div class='kl'><span>Universo</span><strong>{_fmt_int(row.get('unique_tickers'))} tickers</strong></div>"
            f"<div class='kl'><span>Ultima fecha</span><strong>{_esc(row.get('last_date') or '—')}</strong></div>"
            "</div></details></article>"
        )
    return "".join(cards)


def _replace_once(html: str, pattern: str, repl: str) -> str:
    return re.sub(pattern, repl, html, count=1, flags=re.S)


def _apply_snapshot_sections(html: str, snap: dict) -> str:
    cr = snap.get("competition_recent") or {}
    league = _dashboard_league(snap)
    active = snap.get("active") or {}
    leader = league[0] if league else {}
    leader_eq = _row_window(leader, "equalized_recent")
    leader_spark_title = f'{str(leader.get("version") or "Lider")} | liga reciente'
    live_tickers = _hero_live_tickers(snap)
    competition_period_suffix = _competition_period_suffix(snap)

    html = _replace_once(html, r'<div class="regime-pill [^"]*">.*?</div>', _render_regime_pill(snap))
    html = _replace_once(
        html,
        r'(<a class="sn-link" href="#overview" title="Dashboard">.*?<span class="sn-tag">).*?(</span>)',
        r"\1V" + _fmt_int(active.get("active_version")) + r"\2",
    )
    html = _replace_once(
        html,
        r'(<a class="sn-link" href="#picks" title="Picks hoy">.*?<span class="sn-tag">).*?(</span>)',
        r"\g<1>" + _fmt_int(len(live_tickers)) + r"\g<2>",
    )
    html = _replace_once(
        html,
        r'(<a class="sn-link" href="#league" title="Liga">.*?<span class="sn-tag">).*?(</span>)',
        r"\g<1>" + _fmt_int(cr.get("equalized_days")) + "d" + r"\g<2>",
    )
    html = _replace_once(
        html,
        r'(<a class="sn-link" href="#models" title="Modelos">.*?<span class="sn-tag">).*?(</span>)',
        r"\g<1>" + _fmt_int(len(league)) + r"\g<2>",
    )
    html = _replace_once(
        html,
        r'(<details class="side-drawer">\s*<summary>Datos DB</summary>\s*)<div class="sd-body">.*?</div>(\s*</details>)',
        r"\1" + _render_sidebar_datos_db(snap) + r"\2",
    )
    html = _replace_once(
        html,
        r'(<details class="side-drawer">\s*<summary>Config</summary>\s*)<div class="sd-body">.*?</div>(\s*</details>)',
        r"\1" + _render_sidebar_config(snap) + r"\2",
    )
    html = _replace_once(html, r'(<section class="kpi-strip[^>]*>).*?(</section>)', r"\1" + _render_kpi_strip(snap) + r"\2")
    html = _replace_once(html, r'(<section class="panel editable-block" data-bid="hero-panel"[^>]*>).*?(</section>)', r"\1" + _render_hero_panel(snap) + r"\2")
    html = _replace_once(
        html,
        r'(<h2 class="panel-title">)Ranking igualado .*?(</h2>)',
        r"\1Ranking · período competencia · " + _fmt_int(cr.get("equalized_days")) + " ruedas" + competition_period_suffix + r"\2",
    )
    html = _replace_once(
        html,
        r'(<div class="leader-strip">).*?(</div>\s*<table class="data-table">)',
        r"\1\2",
    )
    html = _replace_once(
        html,
        r'(<div class="liga-tab-pane" id="ligaTabPane2">.*?<table class="data-table">.*?<tbody>).*?(</tbody>)',
        r"\1" + _render_liga_tab2_tbody(snap) + r"\2",
    )
    _hm_cal = ((league[0].get("recent_30") or {}).get("calendar") or []) if league else []
    _hm_n   = len(_hm_cal)
    _hm_last = _hm_cal[-1]["date"] if _hm_cal else None
    _hm_pend = len(_next_trading_days(_hm_last, 5)) if _hm_last else 5
    _hm_title_repl = rf"\g<1>Rendimiento por rueda · {_hm_n} ruedas + {_hm_pend} próximas\2"
    html = _replace_once(html, r'(<h2 class="panel-title">)Rendimiento por rueda .*?(</h2>)', _hm_title_repl)
    # SCANNERS PANEL: anchor the replacement to the explicit panel, not to the first
    # `.models-grid` found in the document. This keeps future layout changes safer.
    html = _replace_once(
        html,
        r'(data-bid="scanners-panel".*?<div class="models-grid">).*?(</div>\s*</section>)',
        r"\1" + _render_models_grid(snap) + r"\2",
    )
    # ── SCANNERS PANEL H2: "Muestra igualada N ruedas" ───────────────────────
    eq_days_n = cr.get("equalized_days") or 0
    html = _replace_once(
        html,
        r'(<h2 class="panel-title">Familia INVERTIR · (?:Muestra igualada|Período competencia) )\d+( ruedas</h2>)',
        rf"\g<1>{eq_days_n}\g<2>",
    )
    # ── LEGACY PANEL: ML-only models-grid ────────────────────────────────────
    html = _replace_once(
        html,
        r'(data-bid="legacy-panel".*?<div class="models-grid">).*?(</div>\s*</section>)',
        r"\1" + _render_legacy_grid(snap) + r"\2",
    )
    # ── OVERLAP TABLE ─────────────────────────────────────────────────────────
    html = _replace_once(
        html,
        r"(<table class='om-table'>).*?(</table>)",
        r"\1" + _render_overlap_table_content(snap) + r"\2",
    )
    # ── OVERLAP PANEL H2: "últimas N ruedas" ─────────────────────────────────
    ovl = snap.get("overlap") or {}
    ovl_cd = ovl.get("common_days") or []
    ovl_n = max((max(row) for row in ovl_cd if row), default=0)
    html = _replace_once(
        html,
        r'(<h2 class="panel-title">Diversificaci[oó]n entre modelos · [uú]ltimas )\d+( ruedas</h2>)',
        rf"\g<1>{ovl_n}\g<2>",
    )
    # ── PAGE FOOTER TIMESTAMP ─────────────────────────────────────────────────
    gen_ts = snap.get("generated_at") or ""
    build_meta = snap.get("build") or {}
    db_backend = str(build_meta.get("db_backend") or "").lower()
    source_label = "Postgres/Supabase" if db_backend.startswith("postgres") else "runtime no cloud"
    html = _replace_once(
        html,
        r"(gen\. )[^<]+",
        rf"\g<1>{gen_ts} · {source_label}",
    )
    return html


# ── helpers for heatmap ───────────────────────────────────────────────────────
def _next_trading_days(date_str: str, n: int) -> list[str]:
    """Return next N NYSE trading sessions after date_str."""
    d = datetime.date.fromisoformat(date_str)
    result = []
    while len(result) < n:
        d += datetime.timedelta(days=1)
        if _is_nyse_trading_day(d):
            result.append(d.isoformat())
    return result


def _abbrev_ver(ver: str, limit: int = 11) -> str:
    """Shorten long version strings for heatmap labels."""
    if len(ver) <= limit:
        return ver
    keep_end = 4
    return ver[:limit - keep_end - 1] + "\u2026" + ver[-keep_end:]


def _build_variant_a(focus: list[dict], dates: list[str], pending: list[str], rank_1_ver: str | None = None) -> str:
    """Variant A — 30d full table + 5 future pending cols. All 12 models."""
    all_dates = dates + pending
    compact_cls = " hm-compact" if len(all_dates) > 20 else ""
    # Map each date to its immediately preceding market date in the calendar.
    # Used to distinguish "trailing edge" (model 1 day behind) from real gaps.
    dates_prev: dict[str, str | None] = {d: (dates[i - 1] if i > 0 else None) for i, d in enumerate(dates)}

    # header
    hdr = ""
    for d in dates:
        hdr += (
            f"<th><span class='hm-date'>{d[8:]}/{d[5:7]}</span>"
            f"<span class='hm-dow'>{DOW_ES[datetime.date.fromisoformat(d).weekday()]}</span></th>"
        )
    today_iso   = datetime.date.today().isoformat()
    next_session = pending[0] if pending else None
    for d in pending:
        if d == next_session:
            # Next trading day: highlight as "próxima rueda activa"
            hdr_cls = "hm-today-hdr"
            date_label = f"\u25b8 {d[8:]}/{d[5:7]}"
        elif d == today_iso:
            hdr_cls = "hm-today-hdr"
            date_label = d[8:] + "/" + d[5:7]
        else:
            hdr_cls = "hm-pending-hdr"
            date_label = d[8:] + "/" + d[5:7]
        hdr += (
            f"<th class='{hdr_cls}'><span class='hm-date'>{date_label}</span>"
            f"<span class='hm-dow'>{DOW_ES[datetime.date.fromisoformat(d).weekday()]}</span></th>"
        )

    body_rows = ""
    for rank_i, r in enumerate(focus, 1):
        ver  = r.get("version", "")
        role = r.get("role", "")
        is_champ = bool(rank_1_ver and ver == rank_1_ver)
        icon = "\U0001f3c6" if is_champ else ROLE_ICON.get(role, role[:3].upper())
        champ_tag = "<span style='font-size:9px;font-weight:700;color:#f5b833;display:block'>Champion</span>" if is_champ else ""
        latest_snapshot_date = str(r.get("latest_snapshot_date") or "")
        cmap = {c["date"]: c for c in ((r.get("recent_30") or {}).get("calendar") or [])}
        ver_disp = _abbrev_ver(ver)
        _r30 = [c for c in cmap.values() if _entry_picks_count(c) > 0]
        _r30_rets = [float(c["avg_return_pct"]) for c in _r30 if c.get("avg_return_pct") is not None]
        _r30_wrs  = [float(c["accuracy_pct"])   for c in _r30 if c.get("accuracy_pct")   is not None]
        _r30_ret  = sum(_r30_rets) / len(_r30_rets) if _r30_rets else None
        _r30_wr   = sum(_r30_wrs)  / len(_r30_wrs)  if _r30_wrs  else None
        _r30_ev   = _to_int((r.get("recent_30") or {}).get("evaluated"))
        if _r30_wr is not None and 0 < _r30_ev < 15:
            _wr_lbl = f"{_r30_wr:.0f}% WR ({_r30_ev}p)"
        elif _r30_wr is not None:
            _wr_lbl = f"{_r30_wr:.0f}% WR"
        else:
            _wr_lbl = ""
        if _r30_ret is None:
            _lbl_s = ''
        elif _r30_ret >= 0:
            _lbl_s = (f"<span class='hm-lbl-stat hm-lbl-pos'>+{_r30_ret:.1f}%"
                      + (f" · {_wr_lbl}" if _wr_lbl else "")
                      + "</span>")
        else:
            _lbl_s = (f"<span class='hm-lbl-stat hm-lbl-neg'>{_r30_ret:.1f}%"
                      + (f" · {_wr_lbl}" if _wr_lbl else "")
                      + "</span>")
        cells = f"<th class='hm-label'><span class='hm-rank' style='font-size:9px;color:#888;display:block'>{rank_i}°</span><span class='hm-v'>{_esc(ver_disp)}</span><span class='hm-rl'>{icon}</span>{champ_tag}{_lbl_s}</th>"
        for d in dates:
            it    = cmap.get(d, {})
            ret   = it.get("avg_return_pct")
            acc   = it.get("accuracy_pct")
            picks = _entry_picks_count(it)
            tks   = ", ".join(_entry_tickers(it))
            is_prov = bool(it.get("is_provisional", False))
            if ret is None and not picks:
                if latest_snapshot_date and d <= latest_snapshot_date:
                    tip_none = _esc(f"{ver} · {d} | 0 picks | snapshot fresco sin señal")
                    cells += (
                        f"<td class='hm-no-signal' data-tip='{tip_none}'>"
                        "<div class='hm-ret'>0p</div>"
                        "<div class='hm-meta'>sin señal</div>"
                        "</td>"
                    )
                elif d >= today_iso:
                    # today (or future): model hasn't run yet — not stale
                    tip_hoy = _esc(f"{ver} · {d} | sin datos aún — rueda en curso")
                    cells += (
                        f"<td class='hm-no-signal' data-tip='{tip_hoy}'>"
                        "<div class='hm-ret'>—</div>"
                        "<div class='hm-meta'>hoy</div>"
                        "</td>"
                    )
                elif (dates_prev.get(d) is not None
                      and latest_snapshot_date >= dates_prev[d]):
                    # model ran on the immediately preceding market date —
                    # this is a trailing edge, not a genuine gap → sin señal
                    tip_trail = _esc(f"{ver} · {d} | sin datos (último run: {latest_snapshot_date})")
                    cells += (
                        f"<td class='hm-no-signal' data-tip='{tip_trail}'>"
                        "<div class='hm-ret'>—</div>"
                        "<div class='hm-meta'>sin datos</div>"
                        "</td>"
                    )
                else:
                    tip_gap = _esc(f"{ver} · {d} | sin snapshot fresco para esta rueda")
                    cells += (
                        f"<td class='hm-stale-gap' data-tip='{tip_gap}'>"
                        "<div class='hm-ret'>!</div>"
                        "<div class='hm-meta'>stale</div>"
                        "</td>"
                    )
                continue
            if ret is None and picks:
                _it_lt_tgt = it.get("latest_target_date") or ""
                if _it_lt_tgt and _it_lt_tgt < today_iso:
                    # target date passed but no return recorded — stale unevaluated entry
                    _it_tgt_fmt = f"{_it_lt_tgt[8:]}/{_it_lt_tgt[5:7]}" if len(_it_lt_tgt) == 10 else _it_lt_tgt
                    tip_stale = _esc(f"{ver} · {d[8:]}/{d[5:7]} | {picks} picks sin retorno (evaluación vencida {_it_tgt_fmt})")
                    cells += (
                        f"<td class='hm-stale-gap' data-tip='{tip_stale}'>"
                        "<div class='hm-ret'>!</div>"
                        "<div class='hm-meta'>sin ret</div>"
                        "</td>"
                    )
                else:
                    tip_cur = _esc(f"{ver} {d} | {picks} picks activos | {tks} | retorno pendiente")
                    cells += (
                        f"<td class='hm-active-pending' data-tip='{tip_cur}'>"
                        f"<div class='hm-ret'>⏳</div>"
                        f"<div class='hm-meta'>{picks}p</div>"
                        "</td>"
                    )
                continue
            bg    = _ret_bg(None if ret is None else float(ret))
            if ret is None:
                cls, ret_txt = "hm-empty", "—"
            elif float(ret) >= 0:
                cls = "hm-pos hm-provisional" if is_prov else "hm-pos"
                ret_txt = f"~+{float(ret):.1f}" if is_prov else f"+{float(ret):.1f}"
            else:
                cls = "hm-neg hm-provisional" if is_prov else "hm-neg"
                ret_txt = f"~{float(ret):.1f}" if is_prov else f"{float(ret):.1f}"
            wr_txt = f"{float(acc):.0f}%" if acc is not None else ""
            pk_txt = f"{picks}p" if picks else ""
            prov_badge = "MTM" if is_prov else ""
            meta   = " · ".join(filter(None, [wr_txt, pk_txt, prov_badge]))
            # Build enriched tooltip with per-ticker entry/exit context
            eval_assets = it.get("evaluated_assets") or []
            lt_tgt_date = it.get("latest_target_date") or ""
            # entry = OPEN of the day AFTER the signal date (d)
            # We show: "SEÑAL dd/mm → OPEN día siguiente → CIERRE target"
            d_fmt = f"{d[8:]}/{d[5:7]}"  # dd/mm format
            if eval_assets and not is_prov:
                lines = [f"📌 Señal: {d_fmt}  (entrada = OPEN día siguiente → CIERRE al vencimiento)"]
                for a in eval_assets[:6]:
                    a_ret   = float(a.get("actual_return", 0)) * 100
                    a_hit   = "✓" if int(a.get("hit", 0)) == 1 else "✗"
                    a_sign  = "+" if a_ret >= 0 else ""
                    a_tgt   = str(a.get("target_date") or "")
                    a_tgt_f = f"→ cierre {a_tgt[8:]}/{a_tgt[5:7]}" if a_tgt else ""
                    lines.append(f"  {a_hit} {a.get('ticker','')}: {a_sign}{a_ret:.1f}% {a_tgt_f}")
                if len(eval_assets) > 6:
                    lines.append(f"  … y {len(eval_assets)-6} más")
                lines.append(f"  Promedio: {ret_txt}%  |  WR: {wr_txt}")
                tip = _esc("\n".join(lines))
            elif is_prov:
                if lt_tgt_date and lt_tgt_date < today_iso:
                    _lt_tgt_fmt = f"{lt_tgt_date[8:]}/{lt_tgt_date[5:7]}" if len(lt_tgt_date) == 10 else lt_tgt_date
                    tip = _esc(f"{ver} · {d_fmt} | ret MTM {ret_txt}% | {picks} picks (evaluación vencida {_lt_tgt_fmt}) | {tks}")
                else:
                    tip_suffix = " | en curso (MTM provisional)"
                    tip = _esc(f"{ver} · {d_fmt} | ret estimado {ret_txt}% | {picks} picks abiertos | {tks}{tip_suffix}")
            else:
                tip = _esc(f"{ver} · {d_fmt} | ret {ret_txt}% | WR {wr_txt} | {picks} picks | {tks}")
            cells += (
                f"<td class='{cls}' style='background:{bg}' data-tip='{tip}'>"
                f"<div class='hm-ret'>{ret_txt}</div>"
                + (f"<div class='hm-meta'>{meta}</div>" if meta else "")
                + "</td>"
            )
        # pending cells — the FIRST pending day (next trading day after last_date) always shows
        # active picks so the user can see which signals are open going into the next session,
        # regardless of whether today's data is already in the DB or not.
        next_session = pending[0] if pending else None
        for pd in pending:
            if pd == next_session:
                lt_tks = r.get("latest_tickers") or []
                lt_n   = r.get("latest_picks") or 0
                lt_tgt = r.get("latest_target_date") or ""
                if lt_n and lt_tks and lt_tgt >= today_iso:
                    tks_str   = _esc(", ".join(lt_tks[:6]))
                    tip_next  = _esc(
                        f"{ver} {pd} | {lt_n} picks activos en cartera"
                        f" | {', '.join(lt_tks[:6])}"
                        + (f" | target {lt_tgt}" if lt_tgt else "")
                        + " | retorno se calcula al cierre"
                    )
                    cells += (
                        f"<td class='hm-today' data-tip='{tip_next}'>"
                        f"<div class='hm-ret'>{lt_n}\u25b8</div>"
                        f"<div class='hm-meta'>{tks_str}</div>"
                        "</td>"
                    )
                else:
                    tip_next = _esc(f"{ver} {pd} | sin picks activos | sin posiciones abiertas")
                    cells += (
                        f"<td class='hm-today hm-today-empty hm-no-signal' data-tip='{tip_next}'>"
                        "<div class='hm-ret'>0▸</div>"
                        "<div class='hm-meta'>sin posición</div>"
                        "</td>"
                    )
            else:
                cells += "<td class='hm-pending'><div class='hm-ret'>\u2014</div></td>"
        body_rows += f"<tr>{cells}</tr>"

    # summary row (tfoot) — per DATE cross-model average (35 cells = 30 dates + 5 pending)
    # NOTE: was previously per-MODEL (12 cells), which misaligned with the 35-column header.
    tfoot_cells = "<th class='hm-label'><span class='hm-v'>avg/día</span><span class='hm-rl'>Σ</span></th>"
    # pre-build cmaps for all models once
    all_cmaps = [{c["date"]: c for c in ((r.get("recent_30") or {}).get("calendar") or [])} for r in focus]
    latest_snapshot_dates = [str(r.get("latest_snapshot_date") or "") for r in focus]
    for d in dates:
        day_rets: list[float] = []
        day_wrs:  list[float] = []
        pending_models = 0
        has_picks = False
        covered_models = 0
        stale_models = 0
        for cmap_r, latest_snapshot_date in zip(all_cmaps, latest_snapshot_dates, strict=False):
            it = cmap_r.get(d, {})
            picks = _entry_picks_count(it)
            if latest_snapshot_date and d <= latest_snapshot_date:
                covered_models += 1
            elif latest_snapshot_date and d < today_iso:
                # only stale if model is 2+ market days behind (genuine gap,
                # not just trailing 1 day behind the last run)
                d_prev = dates_prev.get(d)
                if d_prev is None or latest_snapshot_date < d_prev:
                    stale_models += 1
            if picks > 0:
                has_picks = True
                ret = it.get("avg_return_pct")
                acc = it.get("accuracy_pct")
                if ret is None:
                    pending_models += 1
                else:
                    day_rets.append(float(ret))
                    if acc is not None:
                        day_wrs.append(float(acc))
        if not has_picks:
            if stale_models == 0:
                # no past gaps — either all covered or today not yet processed
                tfoot_cells += (
                    "<td class='hm-no-signal'>"
                    "<div class='hm-ret'>0p</div>"
                    "<div class='hm-meta'>sin señal</div>"
                    "</td>"
                )
            else:
                tfoot_cells += (
                    "<td class='hm-stale-gap'>"
                    "<div class='hm-ret'>!</div>"
                    "<div class='hm-meta'>stale</div>"
                    "</td>"
                )
        elif day_rets:
            avg_ret = sum(day_rets) / len(day_rets)
            avg_wr  = sum(day_wrs)  / len(day_wrs) if day_wrs else None
            ret_str = f"+{avg_ret:.1f}" if avg_ret >= 0 else f"{avg_ret:.1f}"
            wr_str  = f"{avg_wr:.0f}%" if avg_wr is not None else ""
            sum_cls = "hm-sum-pos" if avg_ret >= 0 else "hm-sum-neg"
            tfoot_cells += (
                f"<td>"
                f"<span class='{sum_cls}'>{ret_str}</span>"
                + (f"<span class='hm-sum-wr'>{wr_str} WR</span>" if wr_str else "")
                + "</td>"
            )
        else:
            # all picks for this date are still pending resolution
            if d < today_iso:
                # date is past but no returns recorded — stale
                tfoot_cells += (
                    "<td class='hm-stale-gap'>"
                    "<div class='hm-ret'>!</div>"
                    "<div class='hm-meta'>sin ret</div>"
                    "</td>"
                )
            else:
                tfoot_cells += (
                    "<td class='hm-active-pending'>"
                    "<div class='hm-ret'>⏳</div>"
                    "</td>"
                )
    for pd in pending:
        tfoot_cells += "<td class='hm-pending'><div class='hm-ret'>—</div></td>"

    return (
        "<div class='hm-scroll'>"
        f"<table class='hm-table{compact_cls}'>"
        f"<thead><tr><th class='hm-label'><span class='hm-corner-lbl'>↓ Fecha señal</span></th>{hdr}</tr></thead>"
        f"<tbody>{body_rows}</tbody>"
        f"<tfoot><tr class='hm-summary'>{tfoot_cells}</tr></tfoot>"
        "</table></div>"
    )


def _build_variant_b(focus: list[dict], dates: list[str], rank_1_ver: str | None = None) -> str:
    """Variant B — Group 30d by ISO week. One column per week."""
    import collections

    # Group dates by ISO week key (year, week)
    week_map: dict[tuple, list[str]] = collections.OrderedDict()
    for d in dates:
        dt = datetime.date.fromisoformat(d)
        key = dt.isocalendar()[:2]  # (year, week)
        week_map.setdefault(key, []).append(d)

    # Week header labels: "W15 Abr 7-11"
    MES_ABR = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
               "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

    def week_label(key: tuple, day_list: list[str]) -> str:
        _, wk = key
        first = datetime.date.fromisoformat(day_list[0])
        last  = datetime.date.fromisoformat(day_list[-1])
        mes   = MES_ABR[first.month]
        return f"W{wk} {mes} {first.day}-{last.day}"

    hdr = "".join(
        f"<th><span class='hm-date'>{week_label(k, v)}</span></th>"
        for k, v in week_map.items()
    )

    ROLE_ICON_B = {"activo": "OBS", "referencia": "REF", "base": "BASE",
                  "legacy_ml": "ML", "observado": "OBS"}
    body_rows = ""
    for rank_i, r in enumerate(focus, 1):
        ver  = r.get("version", "")
        role = r.get("role", "")
        is_champ = bool(rank_1_ver and ver == rank_1_ver)
        icon = "\U0001f3c6" if is_champ else ROLE_ICON_B.get(role, role[:3].upper())
        champ_tag = "<span style='font-size:9px;font-weight:700;color:#f5b833;display:block'>Champion</span>" if is_champ else ""
        cmap = {c["date"]: c for c in ((r.get("recent_30") or {}).get("calendar") or [])}
        ver_disp = _abbrev_ver(ver)
        _rb = [c for c in cmap.values() if _entry_picks_count(c) > 0]
        _rb_rets = [float(c["avg_return_pct"]) for c in _rb if c.get("avg_return_pct") is not None]
        _rb_wrs  = [float(c["accuracy_pct"])   for c in _rb if c.get("accuracy_pct")   is not None]
        _rb_ret  = sum(_rb_rets) / len(_rb_rets) if _rb_rets else None
        _rb_wr   = sum(_rb_wrs)  / len(_rb_wrs)  if _rb_wrs  else None
        _rb_ev   = _to_int((r.get("recent_30") or {}).get("evaluated"))
        if _rb_wr is not None and 0 < _rb_ev < 15:
            _wr_lbl_b = f"{_rb_wr:.0f}% WR ({_rb_ev}p)"
        elif _rb_wr is not None:
            _wr_lbl_b = f"{_rb_wr:.0f}% WR"
        else:
            _wr_lbl_b = ""
        if _rb_ret is None:
            _lbl_sb = ''
        elif _rb_ret >= 0:
            _lbl_sb = (f"<span class='hm-lbl-stat hm-lbl-pos'>+{_rb_ret:.1f}%"
                       + (f" · {_wr_lbl_b}" if _wr_lbl_b else "")
                       + "</span>")
        else:
            _lbl_sb = (f"<span class='hm-lbl-stat hm-lbl-neg'>{_rb_ret:.1f}%"
                       + (f" · {_wr_lbl_b}" if _wr_lbl_b else "")
                       + "</span>")
        cells = f"<th class='hm-label'><span class='hm-rank' style='font-size:9px;color:#888;display:block'>{rank_i}°</span><span class='hm-v'>{_esc(ver_disp)}</span><span class='hm-rl'>{icon}</span>{champ_tag}{_lbl_sb}</th>"
        for key, day_list in week_map.items():
            week_days_with_picks = [d for d in day_list if d in cmap and _entry_picks_count(cmap[d]) > 0]
            rets  = [float(cmap[d]["avg_return_pct"]) for d in week_days_with_picks if cmap[d].get("avg_return_pct") is not None]
            wrs   = [float(cmap[d]["accuracy_pct"])   for d in week_days_with_picks if cmap[d].get("accuracy_pct") is not None]
            total_picks = sum(_entry_picks_count(cmap[d]) for d in day_list if d in cmap)
            avg_ret = sum(rets) / len(rets) if rets else None
            avg_wr  = sum(wrs)  / len(wrs)  if wrs  else None
            bg = _ret_bg(avg_ret)
            if avg_ret is None:
                cls, ret_txt = "hm-empty", "—"
            elif avg_ret >= 0:
                cls, ret_txt = "hm-pos", f"+{avg_ret:.1f}"
            else:
                cls, ret_txt = "hm-neg", f"{avg_ret:.1f}"
            wr_txt = f"{avg_wr:.0f}%" if avg_wr is not None else ""
            pk_txt = f"{total_picks}p" if total_picks else ""
            meta   = " · ".join(filter(None, [wr_txt, pk_txt]))
            tip    = _esc(f"{ver} {week_label(key, day_list)} | ret {ret_txt}% | WR {wr_txt} | {total_picks} picks")
            cells += (
                f"<td class='{cls}' style='background:{bg}' data-tip='{tip}'>"
                f"<div class='hm-ret'>{ret_txt}</div>"
                + (f"<div class='hm-meta'>{meta}</div>" if meta else "")
                + "</td>"
            )
        body_rows += f"<tr>{cells}</tr>"

    return (
        "<div class='hm-scroll'>"
        "<table class='hm-table'>"
        f"<thead><tr><th class='hm-label'></th>{hdr}</tr></thead>"
        f"<tbody>{body_rows}</tbody>"
        "</table></div>"
    )


def _build_variant_c(focus: list[dict], rank_1_ver: str | None = None) -> str:
    """Variant C — Comparison table: 15d vs 30d WR/Ret + Trend arrow. Sorted by 30d WR desc."""

    def _summary(r: dict, key: str) -> dict:
        cal = _window_calendar(r.get(key) or {})
        active = [c for c in cal if _entry_picks_count(c) > 0]
        rets = [float(c["avg_return_pct"]) for c in active if c.get("avg_return_pct") is not None]
        wrs  = [float(c["accuracy_pct"])   for c in active if c.get("accuracy_pct") is not None]
        picks = sum(_entry_picks_count(c) for c in cal)
        return {
            "wr":  sum(wrs)  / len(wrs)  if wrs  else None,
            "ret": sum(rets) / len(rets) if rets else None,
            "picks": picks,
        }

    ROLE_ICON_C = {"activo": "OBS", "referencia": "REF", "base": "BASE",
                   "legacy_ml": "ML", "observado": "OBS"}

    rows_data = []
    for r in focus:
        ver  = r.get("version", "")
        role = r.get("role", "")
        is_champ = bool(rank_1_ver and ver == rank_1_ver)
        icon = "\U0001f3c6" if is_champ else ROLE_ICON_C.get(role, role[:3].upper())
        s15 = _summary(r, "recent_15")
        s30 = _summary(r, "recent_30")
        rows_data.append((ver, icon, s15, s30))

    # Sort by 30d WR desc (None last)
    rows_data.sort(key=lambda x: (x[3]["wr"] is None, -(x[3]["wr"] or 0)))

    def trend_arrow(wr15: float | None, wr30: float | None) -> str:
        if wr15 is None or wr30 is None:
            return "<span class='hm-trend-eq'>→</span>"
        diff = wr15 - wr30  # positive = 15d better than 30d baseline = improving recently
        if diff >= 10:
            return "<span class='hm-trend-up'>↑</span>"
        elif diff >= 4:
            return "<span class='hm-trend-up'>↗</span>"
        elif diff <= -10:
            return "<span class='hm-trend-dn'>↓</span>"
        elif diff <= -4:
            return "<span class='hm-trend-dn'>↘</span>"
        else:
            return "<span class='hm-trend-eq'>→</span>"

    def fmt_ret(v: float | None) -> str:
        if v is None:
            return "—"
        return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

    def fmt_wr(v: float | None) -> str:
        return f"{v:.0f}%" if v is not None else "—"

    tbody = ""
    for rank_i, (ver, icon, s15, s30) in enumerate(rows_data, 1):
        ver_disp = _abbrev_ver(ver)
        wr15_cls  = "hm-pos" if (s15["wr"]  or 0) >= 60 else ("hm-neg" if (s15["wr"]  or 0) > 0 and s15["wr"] < 50 else "")
        wr30_cls  = "hm-pos" if (s30["wr"]  or 0) >= 60 else ("hm-neg" if (s30["wr"]  or 0) > 0 and s30["wr"] < 50 else "")
        tbody += (
            f"<tr>"
            f"<td><span class='hm-rank' style='font-size:9px;color:#888;margin-right:4px'>{rank_i}°</span><span class='hm-v'>{_esc(ver_disp)}</span></td>"
            f"<td><span class='hm-rl'>{icon}</span></td>"
            f"<td class='{wr15_cls}' style='text-align:right;font-weight:700'>{fmt_wr(s15['wr'])}</td>"
            f"<td style='text-align:right'>{fmt_ret(s15['ret'])}</td>"
            f"<td class='{wr30_cls}' style='text-align:right;font-weight:700'>{fmt_wr(s30['wr'])}</td>"
            f"<td style='text-align:right'>{fmt_ret(s30['ret'])}</td>"
            f"<td style='text-align:right'>{s15['picks']}p</td>"
            f"<td style='text-align:center'>{trend_arrow(s15['wr'], s30['wr'])}</td>"
            f"</tr>"
        )

    return (
        "<div class='hm-scroll'>"
        "<table class='hm-trend-table'>"
        "<thead><tr>"
        "<th>Modelo</th><th>Rol</th>"
        "<th class='hm-r'>15d WR%</th><th class='hm-r'>15d Ret</th>"
        "<th class='hm-r'>30d WR%</th><th class='hm-r'>30d Ret</th>"
        "<th class='hm-r'>15d Picks</th><th style='text-align:center'>Trend</th>"
        "</tr></thead>"
        f"<tbody>{tbody}</tbody>"
        "</table></div>"
    )


# ── build liga principal table ───────────────────────────────────────────────
def _freshness_badge(stale_days: int | None, role: str = "") -> str:
    if stale_days is None:
        return "<span class='badge ba-muted'>N/D</span>"
    if stale_days == 0:
        return "<span class='badge ba-fresh'>AL DÍA</span>"
    is_legacy = (role or "").lower() == "legacy_ml"
    if stale_days <= 2:
        label = "1d sin señal" if stale_days == 1 else f"{stale_days}d sin señal"
        cls = "ba-legacy" if is_legacy else "ba-warn"
        return f"<span class='badge {cls}'>{label}</span>"
    if stale_days <= 7:
        label = f"{stale_days}d sin señal"
        return f"<span class='badge ba-warn'>{label}</span>"
    return f"<span class='badge ba-stale'>{stale_days}d sin señal</span>"


def _freshness_date(row: dict) -> object:
    return row.get("latest_snapshot_date") or row.get("last_date")


def _role_badge_liga(role: str) -> str:
    role = (role or "").lower()
    if role == "active":    return "<span class='badge ba-active'>activo</span>"
    if role == "reference": return "<span class='badge ba-ref'>referencia</span>"
    if role == "base":      return "<span class='badge ba-base'>base</span>"
    if role in ("observado", "observed"): return "<span class='badge ba-obs'>observado</span>"
    if role == "legacy_ml": return "<span class='badge ba-legacy'>legacy_ml</span>"
    return f"<span class='badge'>{_esc(role)}</span>"


def _last_round_cell(window: dict | None) -> str:
    if not window:
        return "<span class='muted-td'>—</span>"
    cal = window.get("calendar") or []
    for entry in reversed(cal):
        ret = entry.get("avg_return_pct")
        if ret is not None:
            d = entry.get("date", "")
            date_fmt = ""
            if d:
                p = d.split("-")
                date_fmt = f"<br><small class='muted-td'>{p[2]}/{p[1]}</small>"
            sign = "+" if ret >= 0 else ""
            css = "pos" if ret >= 0 else "neg"
            return f"<strong class='{css}'>{sign}{ret:.2f}%</strong>{date_fmt}"
    return "<span class='muted-td'>—</span>"


def _last_round_cell_fresh(r30: dict | None, win: dict | None) -> str:
    """Show most recent round from recent_30 (incl. provisional) with prov marker.
    Falls back to equalized window if recent_30 has no data."""
    for source, allow_prov in [(r30, True), (win, False)]:
        if not source:
            continue
        cal = source.get("calendar") or []
        for entry in reversed(cal):
            ret = entry.get("avg_return_pct")
            if ret is None:
                continue
            d = entry.get("date", "")
            date_fmt = ""
            if d:
                p = d.split("-")
                date_fmt = f"<br><small class='muted-td'>{p[2]}/{p[1]}</small>"
            sign = "+" if ret >= 0 else ""
            css = "pos" if ret >= 0 else "neg"
            prov_badge = " <span class='badge ba-prov'>prov</span>" if entry.get("is_provisional") else ""
            return f"<strong class='{css}'>{sign}{ret:.2f}%</strong>{prov_badge}{date_fmt}"
    return "<span class='muted-td'>—</span>"


def _window_cell(w: dict | None) -> str:
    """Build a compact 30d/60d/90d cell: WR% on top, avg return below."""
    if not w:
        return "<td class='wnd-td'><span class='wnd-na'>\u2014</span></td>"
    wr  = w.get("accuracy_pct")
    ret = w.get("avg_return_pct")
    ev  = _to_int(w.get("evaluated"))
    provisional_days = _window_provisional_days(w)
    provisional_picks = _window_provisional_picks(w)
    if wr is None and ret is None and provisional_days == 0:
        return "<td class='wnd-td'><span class='wnd-na'>s/d</span></td>"
    ret_value = float(ret) if ret is not None else (_window_provisional_avg_return_pct(w) or 0.0)
    wr_css  = "wnd-pos" if wr is not None and float(wr) >= 60 else ("wnd-neg" if wr is not None and float(wr) < 50 else "wnd-neu")
    ret_css = "wnd-pos" if ret_value >= 0 else "wnd-neg"
    wr_s  = f"{float(wr):.0f}% WR" if wr is not None else ("PROV" if provisional_days > 0 else "\u2014")
    ret_s = _window_return_label(w, digits=2)
    if wr is None and provisional_days > 0:
        tip = f"Actividad provisional | {provisional_days} ruedas | {provisional_picks} picks abiertos | ret {ret_s}"
    else:
        tip = f"WR {wr_s} | ret {ret_s} | {ev} picks evaluados"
    return (
        f"<td class='wnd-td' title='{_esc(tip)}'>"
        f"<span class='{wr_css} wnd-wr'>{wr_s}</span>"
        f"<span class='{ret_css} wnd-ret'>{ret_s}</span>"
        f"</td>"
    )


def build_liga_table(snap: dict) -> str:
    cr = snap.get("competition_recent", {})
    league = _dashboard_league(snap)
    if not league:
        return ""

    thead = (
        "<thead><tr>"
        "<th>#</th><th>Modelo</th><th>Estado</th>"
        "<th>WR / Ret</th><th title='D\u00edas activos / per\u00edodo competencia \u00b7 picks evaluados'>Comp. \u00b7 Picks</th>"
        "<th>Picks actuales</th><th>\u00dat. rueda eval.</th>"
        "<th title='\u00daltimos 30 d\u00edas de mercado'>30d</th>"
        "<th title='\u00daltimos 60 d\u00edas de mercado'>60d</th>"
        "<th title='\u00daltimos 90 d\u00edas de mercado'>90d</th>"
        "<th>Curva</th>"
        "</tr></thead>"
    )

    rows = []
    for i, m in enumerate(league, start=1):
        ver   = _esc(m.get("version", "?"))
        role  = m.get("role", "")
        stale = m.get("stale_market_days")
        win   = m.get("window") or {}
        r30   = m.get("recent_30") or {}
        wr    = win.get("accuracy_pct")
        eq_d  = win.get("equalized_days") or win.get("active_days") or 0
        tickers = _row_latest_tickers(m, limit=5)
        comp_activity, comp_picks = _window_activity_summary(win, period_days=win.get("equalized_days") or win.get("window_days") or eq_d)

        wr_str  = _window_accuracy_label(win)
        ret_str = _window_return_label(win)
        wr_css  = "pos" if wr is not None and float(wr) >= 60 else ("neg" if wr is not None and float(wr) < 50 else "")
        tickers_str = ", ".join(tickers[:5]) if tickers else "Sin picks"

        # Rich data-* attributes for the expand detail panel
        st = liga_static_meta(ver)
        best_raw  = win.get("best_day_return_pct")
        worst_raw = win.get("worst_day_return_pct")
        best_s  = (("+" if best_raw >= 0 else "") + f"{best_raw:.2f}%") if best_raw is not None else "\u2014"
        worst_s = (("+" if worst_raw >= 0 else "") + f"{worst_raw:.2f}%") if worst_raw is not None else "\u2014"
        w30_accuracy = _window_accuracy_label(r30, digits=0)
        w30_return = _window_return_label(r30, digits=1)
        w30_s   = f"{w30_accuracy}/{w30_return}" if (w30_accuracy != "—" or w30_return != "—") else "\u2014"
        # Dynamic prev-picks from recent_30 calendar (replaces hardcoded fallback when available)
        r30_cal_with = sorted(
            (e for e in (r30.get("calendar") or []) if e.get("avg_return_pct") is not None),
            key=lambda e: e["date"],
        )
        prev_tks: list[str] = []
        for _e in reversed(r30_cal_with[:-1]):
            for _t in (_e.get("tickers") or []):
                if _t not in prev_tks:
                    prev_tks.append(_t)
            if len(prev_tks) >= 5:
                break
        prev_picks_s = " ".join(prev_tks[:5]) or st.get("prev", "")
        # Sparkline data for liga expand row
        sp_series = [float(value or 0.0) for value in (r30.get("spark_avg_return_pct") or [])]
        sp_labels = _sparkline_labels_from_window(r30)
        sp_series, sp_labels = _trim_series_and_labels(sp_series, sp_labels)
        if not sp_series and (r30.get("spark_avg_return_pct") or []):
            sp_series = [float(value or 0.0) for value in (r30.get("spark_avg_return_pct") or [])]
            sp_labels = _sparkline_labels_from_window(r30)
        if not sp_series:
            derived = [
                (float(entry.get("avg_return_pct")), str(entry.get("date")))
                for entry in _window_return_entries(r30)
                if entry.get("date")
            ]
            sp_series = [value for value, _ in derived]
            sp_labels = [label for _, label in derived]
        sp_vals   = _cumulative(sp_series)
        sp_json   = json.dumps(sp_vals)
        sp_labels_json = json.dumps(sp_labels, ensure_ascii=True)
        sp_color  = ROLE_SPARK.get(role, "#6ea8cc")
        curve_svg = _sparkline_svg(
            sp_vals,
            sp_color,
            width=220,
            height=68,
            labels=sp_labels,
            title=f"{ver} | curva reciente",
            value_format="pct",
            previewable=True,
        )

        rows.append(
            f"<tr data-bid='leag-{ver}' data-blabel='{ver}' "
            f"class='leag-row-clickable editable-block' "
            f"data-sharpe='{st.get('sharpe', '\u2014')}' "
            f"data-mdd='{st.get('mdd', '\u2014')}' "
            f"data-best='{best_s}' data-worst='{worst_s}' "
            f"data-signal='{st.get('signal', '\u2014')}' "
            f"data-universe='{st.get('universe', '\u2014')}' "
            f"data-w30='{w30_s}' "
            f"data-prev-picks='{_esc(prev_picks_s)}' "
            f"data-spark-vals='{sp_json}' "
            f"data-spark-labels='{_esc(sp_labels_json)}' "
            f"data-spark-color='{sp_color}'>"
            f"<td><span class='rank-num'>{i}</span></td>"
            f"<td><strong>{ver}</strong> {_role_badge_liga(role)}</td>"
            f"<td>{_freshness_badge(stale, role)}</td>"
            f"<td><strong class='{wr_css}'>{wr_str}</strong>"
            f"<br><small>{ret_str}</small></td>"
            f"<td><small>{_esc(comp_activity)} \u00b7 {_esc(comp_picks)}</small></td>"
            f"<td class='muted-td ticker-list'>{_esc(tickers_str)}</td>"
            f"<td class='ult-rueda-td'>{_last_round_cell_fresh(r30, win)}</td>"
            f"{_window_cell(m.get('recent_30'))}"
            f"{_window_cell(m.get('recent_60'))}"
            f"{_window_cell(m.get('recent_90'))}"
            f"<td class='league-spark-cell'>{curve_svg}</td>"
            f"</tr>"
        )

    return thead + "<tbody>" + "".join(rows) + "</tbody>"


# ── build heatmap HTML ────────────────────────────────────────────────────────
def build_heatmap(snap: dict) -> str:
    cr     = snap.get("competition_recent", {})
    league = _dashboard_league(snap)
    act    = snap.get("active", {})
    # Try both top-level active and operational_context
    av = act.get("active_version", "") or snap.get("operational_context", {}).get("active_version", "")
    champ_ver = f"V{av}" if av else None

    # Pure rank order — no visual priority for experimental motor
    focus: list[dict] = list(league)

    if not focus:
        return "<p style='color:var(--muted);padding:20px;text-align:center'>Sin datos de heatmap.</p>"

    # Dates from champion's recent_30 (fallback: first model)
    champ_cal30 = (focus[0].get("recent_30") or {}).get("calendar") or []
    dates = [c["date"] for c in champ_cal30]

    if not dates:
        return "<p style='color:var(--muted);padding:16px'>Sin fechas en recent_30.</p>"

    last_date = dates[-1]
    pending   = _next_trading_days(last_date, 5)

    # Build the 3 variants — pass rank_1_ver so Champion badge appears on correct row
    rank_1_ver = focus[0].get("version") if focus else None
    var_a = _build_variant_a(focus, dates, pending, rank_1_ver)
    var_b = _build_variant_b(focus, dates, rank_1_ver)
    var_c = _build_variant_c(focus, rank_1_ver)

    # Methodology legend — always visible, explains entry/exit logic to non-technical users
    metodologia = (
        "<div class='hm-legend'>"
        "<span class='hm-legend-icon'>📌</span>"
        "<div class='hm-legend-text'>"
        "<strong>Cómo leer el heatmap</strong>"
        "<div class='hm-legend-steps'>"
        "<div class='hm-legend-step'>"
        "<span class='hm-ls-num'>1</span>"
        "<span class='hm-ls-txt'>Columna = <b>fecha de señal</b> (día en que el modelo detectó la oportunidad)</span>"
        "</div>"
        "<span class='hm-legend-arrow'>→</span>"
        "<div class='hm-legend-step'>"
        "<span class='hm-ls-num'>2</span>"
        "<span class='hm-ls-txt'>Entrada = <b>OPEN del día siguiente</b> (precio real de entrada)</span>"
        "</div>"
        "<span class='hm-legend-arrow'>→</span>"
        "<div class='hm-legend-step'>"
        "<span class='hm-ls-num'>3</span>"
        "<span class='hm-ls-txt'>Salida = <b>CLOSE al vencimiento</b> del hold period (D1/D4/D7/D10/D15)</span>"
        "</div>"
        "<span class='hm-legend-arrow'>→</span>"
        "<div class='hm-legend-step'>"
        "<span class='hm-ls-num'>%</span>"
        "<span class='hm-ls-txt'><b>% = (CLOSE salida − OPEN entrada) / OPEN entrada</b> &nbsp;·&nbsp; hover sobre celda para ver detalle por ticker</span>"
        "</div>"
        "</div>"
        "</div>"
        "</div>"
    )

    tab_js = """<script>
(function(){
  function showTab(id){
    document.querySelectorAll('.hm-vpane').forEach(function(p){p.classList.remove('active')});
    document.querySelectorAll('.hm-vtab').forEach(function(b){b.classList.remove('active')});
    var pane = document.getElementById(id);
    var btn  = document.querySelector('[data-hm-tab="'+id+'"]');
    if(pane) pane.classList.add('active');
    if(btn)  btn.classList.add('active');
  }
  window._hmShowTab = showTab;
  showTab('hm-pane-a');
})();
</script>"""

    html = (
        "<div class='hm-tabbar'>"
        "<button class='hm-vtab' data-hm-tab='hm-pane-a' onclick='_hmShowTab(\"hm-pane-a\")'>30d Completo</button>"
        "<button class='hm-vtab' data-hm-tab='hm-pane-b' onclick='_hmShowTab(\"hm-pane-b\")'>Por Semana</button>"
        "<button class='hm-vtab' data-hm-tab='hm-pane-c' onclick='_hmShowTab(\"hm-pane-c\")'>Tendencia 15/30d</button>"
        "</div>"
        f"{metodologia}"
        f"<div class='hm-vpane' id='hm-pane-a'>{var_a}</div>"
        f"<div class='hm-vpane' id='hm-pane-b'>{var_b}</div>"
        f"<div class='hm-vpane' id='hm-pane-c'>{var_c}</div>"
        + tab_js
    )
    return html


# ── update dates ──────────────────────────────────────────────────────────────
def latest_market_date(snap: dict) -> str | None:
    integrity = snap.get("integrity") or {}
    if integrity.get("latest_market_date"):
        return str(integrity["latest_market_date"])
    cr     = snap.get("competition_recent", {})
    league = _dashboard_league(snap)
    best   = None
    for r in league:
        for key in ("recent_30", "recent_15"):
            cal = (r.get(key) or {}).get("calendar") or []
            if cal:
                last = cal[-1].get("date")
                if last and (best is None or last > best):
                    best = last
                break
    if best:
        return best
    return None


def update_dates(html: str, snap: dict) -> str:
    return html


# ── inject into HTML via sentinels ────────────────────────────────────────────
# ── C1 PRO: hero row + predicción viva builders ──────────────────────────────

def _sfmt_c1(v, digits: int = 2, signed: bool = False) -> str:
    """Format a number as percentage string."""
    if v is None:
        return "—"
    s = "+" if signed and float(v) >= 0 else ""
    return f"{s}{float(v):.{digits}f}%"


def _cumul_c1(vals: list) -> list:
    total, out = 0.0, []
    for v in vals:
        total += float(v or 0)
        out.append(round(total, 2))
    return out


def _make_sparkline_c1pro(row: dict, color: str) -> str:
    """Build an SVG sparkline with data-dates/data-values attrs for hover tooltip."""
    r30 = row.get("recent_30") or {}
    sp  = r30.get("spark_avg_return_pct") or []
    cal = r30.get("calendar") or []
    sp_t, dt_t = _trim_series_and_labels(
        sp,
        [str(c.get("date")) for c in cal if c.get("date")],
    )
    dates = [(d.split("-")[2] + "/" + d.split("-")[1]) for d in dt_t if len(d.split("-")) == 3]
    vals  = _cumul_c1(sp_t)
    d_json = json.dumps(dates).replace('"', "'")
    v_json = json.dumps(vals)
    l_json = _esc(json.dumps(dates, ensure_ascii=True))
    n = len(vals)
    if n < 1:
        return (
            f"<svg viewBox='0 0 260 60' class='spark'>"
            f"<line x1='4' y1='30' x2='256' y2='30' stroke='{color}' "
            f"stroke-width='1.5' stroke-dasharray='4,3'/></svg>"
        )
    lo, hi = min(vals), max(vals)
    rng = hi - lo if hi != lo else 1
    pts = []
    for i, v in enumerate(vals):
        x = 4 + (i / max(n - 1, 1)) * 252
        y = 54 - (v - lo) / rng * 48
        pts.append(f"{x:.1f},{y:.1f}")
    poly = " ".join(pts)
    lx, ly = pts[-1].split(",")
    return (
        f"<svg viewBox='0 0 260 60' class='spark' "
        f"data-dates='{d_json}' data-values='{v_json}' "
        f"data-labels='{l_json}' data-title='{_esc(str(row.get('version') or 'Modelo'))} | curva visible' "
        f"data-format='pct' data-previewable='0'>"
        f"<polygon points='4,57 {poly} {lx},57' fill='{color}' opacity='0.13'/>"
        f"<polyline points='{poly}' fill='none' stroke='{color}' stroke-width='2.4' "
        f"stroke-linecap='round' stroke-linejoin='round'/>"
        f"<circle cx='{lx}' cy='{ly}' r='3.5' fill='{color}'/>"
        f"</svg>"
    )


def _c1pro_card_data(row: dict, color: str) -> dict:
    eq   = row.get("equalized_recent") or row.get("window") or {}
    r30  = row.get("recent_30") or {}
    cal  = r30.get("calendar") or []
    cal_sorted = sorted(cal, key=lambda e: e.get("date", ""))

    # Last round with a realized return (for the "Últ. rueda eval." widget)
    cal_with = [e for e in cal_sorted if e.get("avg_return_pct") is not None]
    last = cal_with[-1] if cal_with else None
    lr_s, ld, lr_css = "—", "", "neu"
    if last:
        lr = last["avg_return_pct"]
        p  = last["date"].split("-")
        ld = f"{p[2]}/{p[1]}" if len(p) == 3 else last["date"]
        lr_s = ("+" if lr >= 0 else "") + f"{lr:.2f}%"
        lr_css = "pos" if lr >= 0 else "neg"

    # ── Last TRULY CLOSED session (is_provisional != True, ret ≠ None) ───────
    closed_info: dict = {}
    for e in reversed(cal_sorted):
        if e.get("is_provisional") is not True and e.get("avg_return_pct") is not None and e.get("tickers"):
            ret_v = float(e["avg_return_pct"])
            p = e.get("date", "").split("-")
            # Per-ticker actual returns (actual_return is a ratio, ×100 = %)
            ev_assets = e.get("evaluated_assets") or []
            closed_tk_rets: dict[str, float] = {
                str(a["ticker"]): float(a["actual_return"]) * 100.0
                for a in ev_assets
                if a.get("ticker") and a.get("actual_return") is not None
            }
            # latest_target_date = evaluation/closing date of this batch
            ltgt = e.get("latest_target_date") or ""
            ptgt = ltgt.split("-")
            closed_info = {
                "tickers": list(e["tickers"])[:6],
                "ret_s": ("+" if ret_v >= 0 else "") + f"{ret_v:.2f}%",
                "ret_css": "pos" if ret_v >= 0 else "neg",
                "date_s": f"{p[2]}/{p[1]}" if len(p) == 3 else e.get("date", ""),
                "ticker_rets": closed_tk_rets,
                "latest_target_date_s": f"{ptgt[2]}/{ptgt[1]}" if len(ptgt) == 3 else ltgt,
            }
            break

    # ── ALL currently open/pending tickers across the full calendar ──────────
    # A calendar entry is "open" if:
    #   a) is_provisional=True  → pick active, has intraday MTM
    #   b) is_provisional=False AND avg_return_pct=None AND tickers → pending,
    #      no price yet (e.g. D10 pick opened today, close price not yet in DB)
    # We scan backwards and collect all unique tickers from open entries.
    # Weighted-average MTM is computed only over provisional entries (those with
    # an actual avg_return_pct).  Pending entries contribute tickers but no MTM.
    all_open_tickers: list[str] = []
    seen_open: set[str] = set()
    prov_rets: list[tuple[float, int]] = []   # (avg_ret_pct, n_tickers_in_entry)
    ticker_mtm: dict[str, float | None] = {}  # ticker → individual provisional MTM %
    ticker_target_date: dict[str, str] = {}   # ticker → expected evaluation date (DD/MM)
    ticker_price: dict[str, float | None] = {}  # ticker → latest_close price

    today_iso = datetime.date.today().isoformat()
    for e in reversed(cal_sorted):
        tickers_e   = list(e.get("tickers") or [])
        ret_v       = e.get("avg_return_pct")
        is_prov     = e.get("is_provisional") is True
        is_pending  = (not is_prov) and (ret_v is None) and bool(tickers_e)
        is_closed   = (not is_prov) and (ret_v is not None)

        # Skip entries whose evaluation target date already passed.
        # Stale provisional/pending batches are NOT active picks regardless
        # of is_provisional status (pipeline may have failed to close them).
        _e_lt_tgt = e.get("latest_target_date") or ""
        if _e_lt_tgt and _e_lt_tgt < today_iso:
            continue

        if is_prov:
            # Format this entry's target date (when picks will be evaluated)
            _ltgt = e.get("latest_target_date") or ""
            _ptgt = _ltgt.split("-")
            _tgt_s = f"{_ptgt[2]}/{_ptgt[1]}" if len(_ptgt) == 3 else _ltgt
            for t in tickers_e:
                if t not in seen_open:
                    seen_open.add(t)
                    all_open_tickers.append(t)
                    if _tgt_s and t not in ticker_target_date:
                        ticker_target_date[t] = _tgt_s
            if ret_v is not None and tickers_e:
                prov_rets.append((float(ret_v), len(tickers_e)))
            # Collect individual ticker MTM (mtm_return is a ratio, ×100 for %)
            for asset in (e.get("mtm_assets") or []):
                tk = str(asset.get("ticker") or "")
                mtm = asset.get("mtm_return")
                if tk and tk not in ticker_mtm:
                    ticker_mtm[tk] = float(mtm) * 100.0 if mtm is not None else None
                if tk and tk not in ticker_price:
                    lc = asset.get("latest_close")
                    ticker_price[tk] = float(lc) if lc is not None else None
        elif is_pending:
            _ltgt = e.get("latest_target_date") or ""
            _ptgt = _ltgt.split("-")
            _tgt_s = f"{_ptgt[2]}/{_ptgt[1]}" if len(_ptgt) == 3 else _ltgt
            for t in tickers_e:
                if t not in seen_open:
                    seen_open.add(t)
                    all_open_tickers.append(t)
                    if _tgt_s and t not in ticker_target_date:
                        ticker_target_date[t] = _tgt_s
        elif is_closed:
            # Skip closed entries — keep scanning for older batches still open
            # (overlapping hold periods: e.g. D10 batch from 04/25 still open
            # even though a 04/20 batch already closed on 04/30)
            continue

    _cpc_lt_tgt = row.get("latest_target_date") or ""
    if all_open_tickers:
        open_tickers = all_open_tickers
    elif _cpc_lt_tgt and _cpc_lt_tgt >= datetime.date.today().isoformat():
        open_tickers = list(row.get("latest_tickers") or [])
    else:
        open_tickers = []

    # Weighted-average MTM across all provisional entries
    prov_ret_s, prov_ret_css = "", "neu"
    if prov_rets:
        total_n = sum(n for _, n in prov_rets)
        weighted = sum(r * n for r, n in prov_rets) / total_n if total_n else 0.0
        prov_ret_s  = ("+" if weighted >= 0 else "") + f"{weighted:.2f}%"
        prov_ret_css = "pos" if weighted >= 0 else "neg"

    # ── Previous closed picks (for the history line) ──────────────────────────
    prev_tickers: list[str] = []
    closed_tickers_set = set(closed_info.get("tickers", []))
    for e in reversed(cal_sorted[:-1] if cal_sorted else []):
        if e.get("is_provisional") is True:
            continue
        for t in (e.get("tickers") or []):
            if t not in prev_tickers and t not in closed_tickers_set:
                prev_tickers.append(t)
        if len(prev_tickers) >= 5:
            break

    return {
        "spark":        _make_sparkline_c1pro(row, color),
        "wr_s":         _sfmt_c1(eq.get("accuracy_pct"), 2),
        "ret_s":        _sfmt_c1(eq.get("avg_return_pct"), 3, signed=True),
        "best":         _sfmt_c1(eq.get("best_day_return_pct"), 2, signed=True),
        "worst":        _sfmt_c1(eq.get("worst_day_return_pct"), 2, signed=True),
        "hits":         eq.get("hits", 0),
        "ev":           eq.get("evaluated", 0),
        "eq_d":         eq.get("equalized_days") or eq.get("active_days") or 0,
        "lr_s":         lr_s,
        "ld":           ld,
        "lr_css":       lr_css,
        # open picks (ALL unresolved across all open calendar entries)
        "open_tickers": open_tickers,
        "open_s":       " · ".join(open_tickers[:12]) or "Sin picks activos",
        "ticker_mtm":   ticker_mtm,
        "prov_ret_s":   prov_ret_s,
        "prov_ret_css": prov_ret_css,
        # last closed session
        "closed_tickers_s":     " · ".join(closed_info.get("tickers", [])[:6]) or "—",
        "closed_ret_s":         closed_info.get("ret_s", "—"),
        "closed_ret_css":       closed_info.get("ret_css", "neu"),
        "closed_date_s":        closed_info.get("date_s", ""),
        "closed_target_date_s": closed_info.get("latest_target_date_s", ""),
        "closed_ticker_rets":   closed_info.get("ticker_rets") or {},
        # open picks dates
        "ticker_target_date":   ticker_target_date,
        # open picks current prices
        "ticker_price":         ticker_price,
        # history (keep for backwards compat)
        "prev":   ", ".join(prev_tickers[:4]) or "—",
        "picks":  " · ".join(open_tickers[:5]) or "Sin picks",
    }


def _build_open_tickers_html(d: dict) -> str:
    """Render open/provisional tickers with individual MTM % and target date."""
    tickers: list[str] = d.get("open_tickers") or []
    ticker_mtm: dict[str, float | None] = d.get("ticker_mtm") or {}
    ticker_target_date: dict[str, str] = d.get("ticker_target_date") or {}
    ticker_price: dict[str, float | None] = d.get("ticker_price") or {}
    if not tickers:
        return "Sin picks activos"
    parts = []
    for t in tickers[:12]:
        mtm = ticker_mtm.get(t)
        tgt = ticker_target_date.get(t, "")
        price = ticker_price.get(t)
        piece = _esc(t)
        if price is not None:
            piece += f"<small class='hc-tk-price'> ${price:.2f}</small>"
        if mtm is not None:
            _css  = "pos" if mtm >= 0 else "neg"
            _sign = "+" if mtm >= 0 else ""
            piece += f"<small class='hc-tk-pct {_css}'> {_sign}{mtm:.1f}%</small>"
        if tgt:
            piece += f"<small class='hc-tk-date'> \u2192{tgt}</small>"
        parts.append(piece)
    return " &middot; ".join(parts)


def _build_open_tickers_table(d: dict) -> str:
    """Render open tickers as a table row per ticker (Option B layout)."""
    tickers: list[str] = d.get("open_tickers") or []
    ticker_mtm: dict[str, float | None] = d.get("ticker_mtm") or {}
    ticker_target_date: dict[str, str] = d.get("ticker_target_date") or {}
    ticker_price: dict[str, float | None] = d.get("ticker_price") or {}
    if not tickers:
        return "<div class='svb-no-picks'>Sin picks activos</div>"
    rows = ""
    for t in tickers[:12]:
        mtm = ticker_mtm.get(t)
        tgt = ticker_target_date.get(t, "")
        price = ticker_price.get(t)
        pct_cell = ""
        if mtm is not None:
            _css  = "pos" if mtm >= 0 else "neg"
            _sign = "+" if mtm >= 0 else ""
            pct_cell = f"<td class='svb-tk-pct {_css}'>{_sign}{mtm:.1f}%</td>"
        else:
            pct_cell = "<td class='svb-tk-pct neu'>\u2014</td>"
        price_cell = f"<td class='svb-tk-price'>${price:.2f}</td>" if price is not None else "<td class='svb-tk-price'></td>"
        date_cell = f"<td class='svb-tk-date'>\u2192{_esc(tgt)}</td>" if tgt else "<td class='svb-tk-date'></td>"
        rows += f"<tr><td class='svb-tk-name'>{_esc(t)}</td>{price_cell}{pct_cell}{date_cell}</tr>"
    return f"<table class='svb-tickers-table'>{rows}</table>"


def _build_closed_tickers_compact(d: dict) -> str:
    """Render last-closed tickers as compact inline line (Option B layout)."""
    tickers_s = d.get("closed_tickers_s") or ""
    ticker_rets: dict[str, float] = d.get("closed_ticker_rets") or {}
    tickers = [t.strip() for t in tickers_s.split(" \u00b7 ") if t.strip() and t.strip() != "\u2014"]
    if not tickers:
        return ""
    parts = []
    for t in tickers:
        ret = ticker_rets.get(t)
        if ret is not None:
            css  = "pos" if ret >= 0 else "neg"
            sign = "+" if ret >= 0 else ""
            parts.append(f"{_esc(t)} <span class='{css}'>{sign}{ret:.1f}%</span>")
        else:
            parts.append(_esc(t))
    return "<div class='svb-closed-line'>" + " &middot; ".join(parts) + "</div>"


def _build_closed_tickers_html(d: dict) -> str:
    """Render last-closed tickers with individual actual return %."""
    tickers_s = d.get("closed_tickers_s") or ""
    ticker_rets: dict[str, float] = d.get("closed_ticker_rets") or {}
    tickers = [t.strip() for t in tickers_s.split(" · ") if t.strip() and t.strip() != "—"]
    if not tickers:
        return _esc(tickers_s) or "—"
    parts = []
    for t in tickers:
        ret = ticker_rets.get(t)
        if ret is not None:
            css  = "pos" if ret >= 0 else "neg"
            sign = "+" if ret >= 0 else ""
            parts.append(f"{_esc(t)}<small class='hc-tk-pct {css}'> {sign}{ret:.1f}%</small>")
        else:
            parts.append(_esc(t))
    return " &middot; ".join(parts)


def _c1pro_hero_card(row: dict, d: dict, card_class: str, color: str, label: str) -> str:
    ver = row.get("version", "?") if row else "?"
    # ── Open picks block ────────────────────────────────────────────────────
    open_count   = len(d.get("open_tickers") or [])
    open_s       = _esc(d.get("open_s") or "Sin picks activos")
    open_html = _build_open_tickers_html(d)
    prov_ret_s   = d.get("prov_ret_s", "")
    prov_ret_css = d.get("prov_ret_css", "neu")
    prov_badge   = (
        f"<span class='hc-prov-ret {prov_ret_css}'>MTM {_esc(prov_ret_s)}</span>"
        if prov_ret_s else
        "<span class='hc-prov-ret neu'>en curso</span>"
    )
    open_count_s = f"{open_count} pick{'s' if open_count != 1 else ''}" if open_count else ""
    open_header_parts = ["\u26a1 Activos"]
    if open_count_s:
        open_header_parts.append(open_count_s)
    open_lbl = " &middot; ".join(open_header_parts)

    # ── Closed picks block ───────────────────────────────────────────────────
    closed_s      = _esc(d.get("closed_tickers_s") or "—")
    closed_ret_s  = d.get("closed_ret_s", "—")
    closed_ret_css = d.get("closed_ret_css", "neu")
    closed_date_s = d.get("closed_date_s", "")
    closed_target_date_s = d.get("closed_target_date_s", "")
    closed_lbl_parts = ["\u2713 Cerrado"]
    if closed_date_s and closed_target_date_s and closed_date_s != closed_target_date_s:
        closed_lbl_parts.append(f"{closed_date_s}\u2192{closed_target_date_s}")
    elif closed_date_s:
        closed_lbl_parts.append(closed_date_s)
    closed_lbl = " &middot; ".join(closed_lbl_parts)

    return (
        f"<div class='hero-card {card_class} editable-block' data-bid='hero-{ver.lower()}'>"
        f"<div class='hc-rank-badge'>{label}</div>"
        f"<div class='hc-model'>{ver}</div>"
        f"<div class='hc-spark'>{d.get('spark', '')}</div>"
        f"<div class='hc-wr'>{d.get('wr_s', '—')}</div>"
        f"<div class='hc-wr-label'>Win Rate &middot; {d.get('eq_d', 0)} ruedas &middot; {d.get('ev', 0)} picks</div>"
        f"<div style='font-size:1.5rem;font-weight:800;letter-spacing:-0.5px;margin:6px 0 2px;color:{color}'>{d.get('ret_s', '—')}</div>"
        f"<div class='hc-wr-label' style='margin-bottom:6px'>Ret. medio por trade</div>"
        f"<div class='hc-round'>"
        f"<span class='hc-round-label'>\u00dalt. rueda eval. {d.get('ld', '')}</span>"
        f"<span class='hc-round-val {d.get('lr_css', 'neu')}'>{d.get('lr_s', '—')}</span>"
        f"</div>"
        f"<div class='hc-stats'>"
        f"<div class='kl'><span>Hits</span><strong>{d.get('hits', 0)} / {d.get('ev', 0)}</strong></div>"
        f"<div class='kl'><span>Mejor rueda</span><strong class='pos'>{d.get('best', '—')}</strong></div>"
        f"<div class='kl'><span>Peor rueda</span><strong class='neg'>{d.get('worst', '—')}</strong></div>"
        f"</div>"
        f"<div class='hc-picks'>"
        # ── Active / open picks (prominent) ──
        f"<div class='hc-open-row'>"
        f"<div class='hc-open-header'>"
        f"<span class='hc-picks-lbl hc-open-lbl'>{open_lbl}</span>"
        f"{prov_badge}"
        f"</div>"
        f"<div class='hc-picks-live'>{open_html}</div>"
        f"</div>"
        # ── Last closed session (with per-ticker individual %) ──
        f"<div class='hc-closed-row'>"
        f"<span class='hc-picks-lbl'>{closed_lbl}"
        f"<span class='hc-closed-ret {closed_ret_css}'> {_esc(closed_ret_s)}</span>"
        f"</span>"
        f"<div class='hc-closed-tickers'>{_build_closed_tickers_html(d)}</div>"
        f"</div>"
        f"</div>"
        f"</div>"
    )


def _build_c1pro_senales_vivas_card(snap: dict) -> str:
    """Build Señales Vivas: signal board with active picks per model (no charts)."""
    active = snap.get("active") or {}
    run    = (active.get("active_run")) or {}
    regime_label = str(run.get("regime_label") or "—")
    pred_for     = run.get("prediction_for") or "—"
    regime_cls   = "regime-peligro" if regime_label.upper() == "PELIGRO" else "regime-seguro"
    champion_ver = f"V{active.get('active_version', 13)}"
    league = _dashboard_league(snap)

    rank_1_ver = league[0].get("version") if league else None

    # Map color → left-border CSS class for Option B design
    _BORDER_CLS = {"#6ea8cc": "ver-base", "#18e8c8": "ver-v13", "#a882ff": "ver-ml"}

    rows_html: list[str] = []
    for rank, row in enumerate(league, start=1):
        ver   = row.get("version", "?")
        role  = row.get("role", "")
        color = ROLE_SPARK.get(role, "#6ea8cc")
        border_cls = _BORDER_CLS.get(color, "ver-ml")
        eq    = row.get("equalized_recent") or row.get("window") or {}
        wr    = eq.get("accuracy_pct")
        ret   = eq.get("avg_return_pct")
        ev_sv = _to_int(eq.get("evaluated"))

        if wr is not None and 0 < ev_sv < 15:
            wr_s2 = f"{float(wr):.0f}% ({ev_sv}p)"
        else:
            wr_s2 = f"{float(wr):.0f}%" if wr is not None else "\u2014"
        ret_s2  = (("+" if float(ret) >= 0 else "") + f"{float(ret):.1f}%") if ret is not None else "\u2014"
        ret_css = "pos" if (ret is not None and float(ret) >= 0) else ("neg" if ret is not None else "neu")

        badges = ""
        if ver == rank_1_ver:
            badges += "<span class='svb-badge-champ'>CHAMPION</span>"
        if ver == champion_ver:
            badges += "<span class='svb-badge-activo'>ACTIVO</span>"

        # ── Rich pick data (open tickers + MTM + last closed) ──────────────
        d = _c1pro_card_data(row, color)

        _open_tickers = d.get("open_tickers") or []
        open_count    = len(_open_tickers)

        # MTM badge
        prov_ret_s   = d.get("prov_ret_s", "")
        prov_ret_css = d.get("prov_ret_css", "neu")
        if prov_ret_s:
            mtm_badge = f"<span class='svb-mtm-badge {prov_ret_css}'>MTM {_esc(prov_ret_s)}</span>"
        elif open_count > 0:
            mtm_badge = "<span class='svb-mtm-badge neu'>en curso</span>"
        else:
            mtm_badge = ""

        # Open section: separator + table of tickers
        open_count_s = f"{open_count}p" if open_count > 0 else ""
        open_sep_lbl = f"&#x26a1; Abiertos {open_count_s}" if open_count_s else "&#x26a1; Abiertos"
        open_section = (
            f"<div class='svb-section-sep svb-sep-open'>"
            f"<span>{open_sep_lbl}</span><span class='svb-sep-line'></span></div>"
            + _build_open_tickers_table(d)
        )

        # Closed section: separator + compact inline line
        closed_tickers_s = d.get("closed_tickers_s", "")
        closed_ret_s     = d.get("closed_ret_s", "\u2014")
        closed_ret_css   = d.get("closed_ret_css", "neu")
        closed_date_s    = d.get("closed_date_s", "")
        closed_target_date_s = d.get("closed_target_date_s", "")

        if closed_tickers_s and closed_tickers_s != "\u2014":
            closed_lbl = "Cerrado"
            if closed_date_s and closed_target_date_s and closed_date_s != closed_target_date_s:
                closed_lbl += f" {closed_date_s}\u202f\u2192\u202f{closed_target_date_s}"
            elif closed_date_s:
                closed_lbl += f" {closed_date_s}"
            closed_section = (
                f"<div class='svb-section-sep svb-sep-closed'>"
                f"<span>&#x2713; {_esc(closed_lbl)}</span>"
                f"<span class='svb-sep-line'></span>"
                f"<span class='svb-sep-ret {closed_ret_css}'>{_esc(closed_ret_s)}</span>"
                f"</div>"
                + _build_closed_tickers_compact(d)
            )
        else:
            closed_section = ""

        rows_html.append(
            f"<div class='svb-row {border_cls}'>"
            f"<div class='svb-row-head'>"
            f"<span class='svb-rank-lbl'>{rank}&#xb0;</span>"
            f"<span class='svb-rver' style='color:{color}'>{_esc(ver)}</span>"
            f"{badges}"
            f"<div class='svb-head-right'>"
            f"<span class='svb-kpi-line'>{_esc(wr_s2)} &middot; <span class='{ret_css}'>{_esc(ret_s2)}</span></span>"
            f"{mtm_badge}"
            f"</div>"
            f"</div>"
            + open_section
            + closed_section
            + "</div>"
        )

    return (
        "<div class='hero-card hc-gold editable-block' data-bid='hero-signals'>"
        "<div class='hc-label'>\u26a1 Se\u00f1ales Vivas \u00b7 Todos los modelos</div>"
        f"<div class='sv-regime-row'>"
        f"<span class='pv-regime {regime_cls}'>{_esc(regime_label)}</span>"
        f"<span class='sv-pred-for'>Para {_esc(pred_for)}</span>"
        f"</div>"
        "<div class='svb-list'>" + "".join(rows_html) + "</div>"
        "</div>"
    )

def _build_c1pro_hero_row(snap: dict) -> str:
    """Build the 4 hero cards: champion, WR leader, return leader, Señales Vivas."""
    league = _dashboard_league(snap)
    active = snap.get("active") or {}
    run    = (active.get("active_run")) or {}
    champion_ver = f"V{active.get('active_version', '13')}"

    def _find(ver: str) -> dict:
        return next((m for m in league if m.get("version") == ver), league[0] if league else {})

    def _leader_ret() -> dict:
        valid = [m for m in league if (m.get("equalized_recent") or m.get("window") or {}).get("avg_return_pct") is not None]
        if not valid:
            return league[0] if league else {}
        return max(valid, key=lambda m: float((m.get("equalized_recent") or m.get("window") or {}).get("avg_return_pct") or -1e18))

    # Top 3 del ranking global equalized
    rank1 = league[0] if len(league) > 0 else {}
    rank2 = league[1] if len(league) > 1 else {}
    rank3 = league[2] if len(league) > 2 else {}

    # Live tickers del scanner activo
    live: list[str] = []
    for k in ["results_d", "results_e", "results_e_hw", "results_c5", "results_a"]:
        for p in (run.get(k) or []):
            t = p.get("ticker")
            if t and t not in live:
                live.append(t)

    rank1_d = _c1pro_card_data(rank1, "#44e890") if rank1 else {}
    # Inyectar picks vivos solo si rank1 es el scanner activo
    if live and rank1.get("version") == champion_ver:
        rank1_d["picks"] = ", ".join(live[:5])
    rank2_d = _c1pro_card_data(rank2, "#a882ff") if rank2 else {}
    rank3_d = _c1pro_card_data(rank3, "#18e8c8") if rank3 else {}

    return "\n".join([
        _c1pro_hero_card(rank1, rank1_d, "hc-green",  "#44e890", "\U0001f947 Champion 1\u00b0"),
        _c1pro_hero_card(rank2, rank2_d, "hc-purple", "#a882ff", "\U0001f948 2\u00b0"),
        _c1pro_hero_card(rank3, rank3_d, "hc-cyan",   "#18e8c8", "\U0001f949 3\u00b0"),
        _build_c1pro_senales_vivas_card(snap),
    ])


def _build_pred_viva(snap: dict) -> str:
    """Build the Predicción Viva section content."""
    active = snap.get("active") or {}
    run    = (active.get("active_run")) or {}
    regime_label = str(run.get("regime_label") or "—")
    pred_for     = run.get("prediction_for") or "—"

    def _pick_html(pick: dict) -> str:
        ticker = pick.get("ticker", "?")
        price  = pick.get("price")
        target = pick.get("target")
        stop   = pick.get("stop")
        rsi    = pick.get("rsi")
        risk   = pick.get("risk_pct")
        score  = pick.get("score")
        note   = str(pick.get("note") or "").split("|")[0].strip()
        p_s  = f"${price:.2f}" if price is not None else "—"
        t_s  = f"${target:.2f}" if target is not None else "—"
        s_s  = f"${stop:.2f}" if stop is not None else "—"
        r_s  = f"{rsi:.1f}" if rsi is not None else "—"
        rk_s = f"{risk:.1f}%" if risk is not None else "—"
        sc_s = f"{score:.0f}" if score is not None else "—"
        return (
            f"<div class='pv-pick'>"
            f"<div class='pv-ticker'>{_esc(ticker)}</div>"
            f"<div class='pv-price'>{p_s}</div>"
            f"<div class='pv-row'><span>Target</span><strong class='pos'>{t_s}</strong></div>"
            f"<div class='pv-row'><span>Stop</span><strong class='neg'>{s_s}</strong></div>"
            f"<div class='pv-row'><span>RSI</span><strong>{r_s}</strong></div>"
            f"<div class='pv-row'><span>Riesgo</span><strong>{rk_s}</strong></div>"
            f"<div class='pv-row'><span>Score</span><strong>{sc_s}</strong></div>"
            f"<div class='pv-hold'>{_esc(note)}</div>"
            f"</div>"
        )

    parts = [
        f"<div class='pv-header'>"
        f"<span class='pv-for'>Para {_esc(pred_for)}</span>"
        f"<span class='pv-regime regime-{regime_label.lower()}'>{_esc(regime_label)}</span>"
        f"</div>"
    ]
    sigs = [
        ("Signal D &mdash; Liderazgo",          run.get("results_d") or []),
        ("Signal C5 &mdash; Crash + Rebound",   run.get("results_c5") or []),
        ("Signal A &mdash; Mean Reversion",     run.get("results_a") or []),
        ("Signal E_HW &mdash; RS New High HW",  run.get("results_e") or run.get("results_e_hw") or []),
    ]
    has_any = any(rs for _, rs in sigs)
    if not has_any:
        parts.append("<div class='pv-empty'>Sin se\u00f1ales activas para este per\u00edodo.</div>")
    else:
        for sname, results in sigs:
            if not results:
                continue
            parts.append(f"<div class='pv-sig-label'>{sname}</div><div class='pv-picks-grid'>")
            for p in results[:8]:
                parts.append(_pick_html(p))
            parts.append("</div>")
    mem = run.get("memory_context") or []
    if mem:
        parts.append("<div class='pv-memory'><div class='pv-memory-label'>Contexto hist\u00f3rico</div>")
        for m in mem:
            parts.append(f"<div class='pv-memory-item'>{_esc(str(m))}</div>")
        parts.append("</div>")
    return "\n".join(parts)


def inject(html: str, marker_s: str, marker_e: str, content: str) -> str:
    s = html.find(marker_s)
    e = html.find(marker_e)
    if s < 0 or e < 0:
        return html  # markers not present, skip
    return html[: s + len(marker_s)] + "\n" + content + "\n" + html[e:]


def _missing_required_markers(html: str) -> list[str]:
    missing: list[str] = []
    for label, marker_s, marker_e in REQUIRED_MARKER_PAIRS:
        has_start = marker_s in html
        has_end = marker_e in html
        if has_start and has_end:
            continue
        if has_start != has_end:
            missing.append(f"{label} (par incompleto)")
        else:
            missing.append(label)
    return missing


def _strip_marker_pair(html: str, marker_s: str, marker_e: str) -> str:
    return html.replace(marker_s, "").replace(marker_e, "")


def _wrap_marker_block(
    html: str,
    pattern: str,
    marker_s: str,
    marker_e: str,
    label: str,
    *,
    verbose: bool = True,
) -> tuple[str, bool]:
    html = _strip_marker_pair(html, marker_s, marker_e)
    match = re.search(pattern, html, flags=re.S)
    if not match:
        if verbose:
            print(f"  [markers] WARNING: {label} anchor not found, markers NOT added")
        return html, False
    inner = match.group(2).strip("\n")
    replacement = match.group(1) + "\n" + marker_s + "\n" + inner + "\n" + marker_e + "\n" + match.group(3)
    html = html[:match.start()] + replacement + html[match.end():]
    if verbose:
        print(f"  [markers] {label} markers added")
    return html, True


# ── add markers (first-time setup) ───────────────────────────────────────────
def add_markers(html: str, *, verbose: bool = True) -> str:
    # Heatmap sentinel
    if MARK_HM_S not in html or MARK_HM_E not in html:
        html = _strip_marker_pair(html, MARK_HM_S, MARK_HM_E)
        hm_s = html.find("<table class='hm-table'>")
        if hm_s >= 0:
            hm_e = html.find("</table>", hm_s) + len("</table>")
            # also include the legend div right after, if present
            after_table = html[hm_e: hm_e + 300]
            legend_end = after_table.find("</div>")
            if "hm-legend" in after_table and legend_end >= 0:
                hm_e = hm_e + legend_end + len("</div>")
            html = (html[:hm_s] + MARK_HM_S + "\n"
                    + html[hm_s:hm_e] + "\n" + MARK_HM_E + html[hm_e:])
            if verbose:
                print("  [markers] heatmap markers added")
        else:
            if verbose:
                print("  [markers] WARNING: hm-table not found, heatmap markers NOT added")

    # CSS sentinel — place just before the FIRST </style> (main CSS block, not JS strings)
    if MARK_CSS_S not in html or MARK_CSS_E not in html:
        html = _strip_marker_pair(html, MARK_CSS_S, MARK_CSS_E)
        first_script = html.find("<script")
        search_in = html if first_script < 0 else html[:first_script]
        style_end = search_in.rfind("</style>")
        if style_end >= 0:
            html = (html[:style_end]
                    + MARK_CSS_S + "\n" + MARK_CSS_E + "\n"
                    + html[style_end:])
            if verbose:
                print("  [markers] CSS markers added")
        else:
            if verbose:
                print("  [markers] WARNING: </style> not found, CSS markers NOT added")

    if MARK_HERO_S not in html or MARK_HERO_E not in html:
        html, _ = _wrap_marker_block(
            html,
            r'(<section\b[^>]*\bid="hero"[^>]*>)(.*?)(</section>)',
            MARK_HERO_S,
            MARK_HERO_E,
            "hero-row",
            verbose=verbose,
        )

    if MARK_LIGA_S not in html or MARK_LIGA_E not in html:
        html, _ = _wrap_marker_block(
            html,
            r'(<section\b[^>]*\bid="league"[^>]*>.*?<table class="data-table">)(.*?)(</table>)',
            MARK_LIGA_S,
            MARK_LIGA_E,
            "liga-table",
            verbose=verbose,
        )

    return html


def render_dashboard_html(html: str, snap: dict, *, verbose: bool = False) -> str:
    """Renderiza la plantilla completa de C1 Pro desde el snapshot sobre un HTML base."""
    missing_markers = _missing_required_markers(html)
    if missing_markers:
        if verbose:
            print("Markers not found — adding them now...")
        html = add_markers(html, verbose=verbose)
        missing_markers = _missing_required_markers(html)
        if missing_markers:
            raise ValueError("critical dashboard markers still missing: " + ", ".join(missing_markers))

    # Inject CSS
    html = inject(html, MARK_CSS_S, MARK_CSS_E, HEATMAP_CSS)

    # Inject heatmap
    new_hm = build_heatmap(snap)
    html = inject(html, MARK_HM_S, MARK_HM_E, new_hm)

    # Inject liga principal table (thead + tbody with fresh data + Últ. Rueda column)
    new_liga = build_liga_table(snap)
    if new_liga:
        html = inject(html, MARK_LIGA_S, MARK_LIGA_E, new_liga)

    # ── C1 Pro: inject hero row + predicción viva ──────────────────────────────
    html = inject(html, MARK_HERO_S, MARK_HERO_E, _build_c1pro_hero_row(snap))
    if verbose:
        print("  [c1pro] Hero row injected")

    if MARK_PRED_S in html and MARK_PRED_E in html:
        html = inject(html, MARK_PRED_S, MARK_PRED_E, _build_pred_viva(snap))
        if verbose:
            print("  [c1pro] Predicción Viva injected")

    html = _apply_snapshot_sections(html, snap)

    # ── Embed verify payload (SEMÁFORO DE DATOS) como JSON inline ──────────────
    vp = _load_verify_payload()
    vp_json = json.dumps(vp, ensure_ascii=False, separators=(",", ":"))
    verify_tag = (
        f'<script id="verify-payload" type="application/json">{vp_json}</script>'
    )
    if '<script id="verify-payload"' in html:
        # Reemplazar el existente
        html = re.sub(
            r'<script id="verify-payload"[^>]*>.*?</script>',
            verify_tag,
            html,
            count=1,
            flags=re.DOTALL,
        )
    else:
        # Insertar antes de </body>
        html = html.replace("</body>", verify_tag + "\n</body>", 1)

    # Update dates
    return update_dates(html, snap)


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ensure_dashboard_dir()
    if not SNAPSHOT.exists():
        print(f"ERROR: snapshot not found: {SNAPSHOT}")
        return 1
    if not DASHBOARD.exists():
        print(f"ERROR: dashboard not found: {DASHBOARD}")
        return 1

    with open(SNAPSHOT, "r", encoding="utf-8") as f:
        snap = json.load(f)
    with open(DASHBOARD, "r", encoding="utf-8") as f:
        html = f.read()

    try:
        html = render_dashboard_html(html, snap, verbose=True)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    with open(DASHBOARD, "w", encoding="utf-8") as f:
        f.write(html)

    # Keep local preview in sync (dashboards/maquina_pensante/preview_c1_pro.html)
    LOCAL_PREVIEW = ROOT / "dashboards" / "maquina_pensante" / "preview_c1_pro.html"
    LOCAL_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_PREVIEW.write_text(html, encoding="utf-8")
    print("  [sync] Local preview updated")

    lm = latest_market_date(snap)
    gen = snap.get("generated_at", "?")
    print(f"Dashboard refreshed OK | snapshot={gen} | latest_market={lm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# chore: trigger deploy 2026-05-05
