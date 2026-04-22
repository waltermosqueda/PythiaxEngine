#!/usr/bin/env python3
"""
PREVIEW VISUAL V11
==================

Prototipo no definitivo para comparar layouts del scanner activo V11.

Layouts:
  - minimal : tabla limpia y muy rapida de leer
  - cards   : fichas por activo, mas amigable para novato
  - expert  : vista compacta con mas densidad tecnica
  - gallery : imprime las 3 versiones para comparar

Uso:
  python analisis/preview_v11_visual.py
  python analisis/preview_v11_visual.py --layout gallery --demo
  python analisis/preview_v11_visual.py --layout gallery --showcase
  python analisis/preview_v11_visual.py --layout cards --date 2026-03-20
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from pathlib import Path
import re
import sys
import time

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import SCANNER.invertir_v11 as v11
from titan_system.core.database import TitanDB


LINE = "=" * 100
SUBLINE = "-" * 100
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
USE_COLOR = sys.stdout.isatty() and os.getenv("NO_COLOR") is None
WEEKDAY_ES = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]


@dataclass
class Snapshot:
    run_started: datetime
    run_finished: datetime
    elapsed_sec: float
    analyzed_date: str
    latest_db_date: str | None
    db_last_write: datetime | None
    freshness: str
    regime_label: str
    breadth_pct: float
    coverage_count: int
    missing_count: int
    results_a: list[v11.ScanResult]
    results_c5: list[v11.ScanResult]
    blocked_extreme: list[v11.ScanResult]
    quality_alerts: list[dict[str, object]]
    demo_mode: bool
    mode_label: str = "LIVE"
    preview_note: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview visual del scanner V11")
    parser.add_argument(
        "--layout",
        choices=["minimal", "cards", "expert", "gallery"],
        default="gallery",
        help="Layout visual a mostrar",
    )
    parser.add_argument("--date", help="Fecha de analisis YYYY-MM-DD")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Busca una fecha reciente con senales para comparar layouts aunque hoy no haya picks",
    )
    parser.add_argument(
        "--showcase",
        action="store_true",
        help="Usa una muestra completa con activos reales y datos de ejemplo para evaluar el diseno",
    )
    parser.add_argument(
        "--minimal-header-variant",
        choices=["actual", "split", "focus", "panel"],
        default="panel",
        help="Variante del encabezado para la vista minimal",
    )
    parser.add_argument(
        "--minimal-header-gallery",
        action="store_true",
        help="Compara varias versiones del encabezado de la vista minimal",
    )
    return parser.parse_args()


def format_runtime(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    return f"{seconds:.2f} s"


def pct_to_text(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.1f}%"


def money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"${value:.2f}"


def trim(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: max(0, width - 3)] + "..."


def paint(text: str, style: str) -> str:
    if not USE_COLOR:
        return text
    return f"\x1b[{style}m{text}\x1b[0m"


def visible_len(text: str) -> int:
    return len(ANSI_RE.sub("", text))


def pad_visible(text: str, width: int) -> str:
    padding = max(0, width - visible_len(text))
    return text + (" " * padding)


def labeled_line(label: str, value: str, width: int = 24) -> str:
    return f"  {label.ljust(width)}: {value}"


def split_banner(left_text: str, right_text: str, total_width: int = len(LINE)) -> str:
    gap = total_width - visible_len(left_text) - visible_len(right_text)
    if gap < 3:
        return f"{left_text} | {right_text}"
    return left_text + (" " * gap) + right_text


def execution_summary(snapshot: Snapshot) -> str:
    start_text = snapshot.run_started.strftime("%Y-%m-%d %H:%M:%S")
    finish_text = snapshot.run_finished.strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"Inicio {start_text} | Finalizacion {finish_text} | "
        f"Actualizado al cierre : {format_spanish_date(snapshot.analyzed_date)}"
    )


def format_spanish_date(date_text: str | None) -> str:
    if not date_text:
        return "-"
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return f"{WEEKDAY_ES[dt.weekday()]} {dt.strftime('%Y-%m-%d')}"


def format_spanish_datetime(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    return f"{WEEKDAY_ES[dt.weekday()]} {dt.strftime('%Y-%m-%d %H:%M:%S')}"


def next_business_day(date_text: str | None) -> str:
    if not date_text:
        return "-"
    cursor = datetime.strptime(date_text, "%Y-%m-%d").date() + timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor += timedelta(days=1)
    return cursor.isoformat()


def prediction_summary(snapshot: Snapshot) -> str:
    next_day = next_business_day(snapshot.analyzed_date)
    return f"{format_spanish_date(next_day)} | Horizonte : 4 a 7 ruedas"


def prediction_target(snapshot: Snapshot) -> str:
    next_day = next_business_day(snapshot.analyzed_date)
    return format_spanish_date(next_day)


def market_context(snapshot: Snapshot) -> str:
    regime = "favorable (SEGURO)" if snapshot.regime_label == "SEGURO" else "defensivo (PELIGRO)"
    if snapshot.regime_label == "SEGURO":
        regime = paint(regime, "1;92")
    else:
        regime = paint(regime, "1;93")
    pct_text = paint(f"{snapshot.breadth_pct:.1f}%", "96")
    return f"Mercado {regime} | Activos arriba de SMA50: {pct_text}"


def opportunities_summary(snapshot: Snapshot) -> str:
    total = len(snapshot.results_a) + len(snapshot.results_c5)
    return (
        f"Total {total} Detectadas | Rebotes tecnicos {len(snapshot.results_a)} | "
        f"Crashes filtrados {len(snapshot.results_c5)}"
    )


def quality_alert_summary(alert: dict[str, object]) -> str:
    ticker = str(alert["ticker"])
    date_text = format_spanish_date(str(alert["date"]))
    ret1 = alert.get("ret1")
    intraday = alert.get("intraday")
    metrics = ""
    if ret1 is not None and intraday is not None:
        metrics = f" ({float(ret1):+.1f}% | intraday {float(intraday):+.1f}%)"
    return (
        f"{ticker}{metrics} | Posible split o ajuste ocurrido el {date_text} | "
        "No usar esa caida como oportunidad, realizar seguimiento por el momento."
    )


def execution_window(snapshot: Snapshot) -> str:
    start_text = snapshot.run_started.strftime("%Y-%m-%d %H:%M:%S")
    finish_text = snapshot.run_finished.strftime("%Y-%m-%d %H:%M:%S")
    return f"Inicio {start_text} | Finalizacion {finish_text}"


def closing_update(snapshot: Snapshot) -> str:
    if snapshot.db_last_write is None:
        return "Actualizado : -"
    updated_text = format_spanish_datetime(snapshot.db_last_write)
    return f"Actualizado : {updated_text}"


def setup_label(result: v11.ScanResult) -> str:
    if result.signal.startswith("A"):
        return "Rebote (A)"
    return "Crash (C5)"


def signal_breakdown(snapshot: Snapshot) -> str:
    total = len(snapshot.results_a) + len(snapshot.results_c5)
    return (
        f"{total} detectadas ({len(snapshot.results_a)} rebotes tecnicos + "
        f"{len(snapshot.results_c5)} crashes filtrados)"
    )


def make_result(
    ticker: str,
    signal: str,
    price: float,
    sector: str,
    rsi: float | None,
    dist_sma50: float | None,
    roc10: float | None,
    vol_ratio: float | None,
    stop: float,
    target: float,
    risk_pct: float,
    score: float,
    note: str,
) -> v11.ScanResult:
    return v11.ScanResult(
        ticker=ticker,
        signal=signal,
        price=price,
        sector=sector,
        rsi=rsi,
        dist_sma50=dist_sma50,
        roc10=roc10,
        vol_ratio=vol_ratio,
        stop=stop,
        target=target,
        risk_pct=risk_pct,
        score=score,
        note=note,
    )


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        widths = [visible_len(header) for header in headers]
    else:
        widths = [visible_len(header) for header in headers]
        for row in rows:
            widths = [max(width, visible_len(value)) for width, value in zip(widths, row)]

    def fmt(row: list[str]) -> str:
        return " | ".join(pad_visible(value, width) for value, width in zip(row, widths))

    parts = [fmt(headers), "-+-".join("-" * width for width in widths)]
    parts.extend(fmt(row) for row in rows)
    return "\n".join(parts)


def recent_demo_date(prepared: dict[str, pd.DataFrame]) -> str | None:
    spy = prepared["SPY"]
    best_any: tuple[str, int] | None = None
    for offset in range(1, min(len(spy), 160)):
        idx = -offset
        spy_cut = spy.iloc[: idx + 1] if idx != -1 else spy
        if len(spy_cut) < 60:
            continue
        regime_safe, _ = v11.check_regime(spy_cut)
        count = 0
        for ticker in sorted(t for t in prepared.keys() if t != "SPY"):
            df = prepared[ticker].iloc[: idx + 1] if idx != -1 else prepared[ticker]
            if len(df) < 60:
                continue
            added = False
            if regime_safe:
                sig_a = v11.signal_a_mean_reversion(ticker, df)
                if sig_a is not None:
                    count += 1
                    added = True
            c = v11.build_c5_candidate(ticker, df)
            if c is not None and v11.c5_is_preferred(c) and not added:
                count += 1
        if count > 0 and best_any is None:
            best_any = (spy_cut.index[-1].date().isoformat(), count)
        if count >= 3:
            return spy_cut.index[-1].date().isoformat()
    return best_any[0] if best_any else None


def gather_snapshot(date_override: str | None, demo: bool) -> Snapshot:
    started = datetime.now()
    t0 = time.perf_counter()

    with TitanDB() as db:
        universe_data, missing = v11.load_universe_data(db, v11.UNIVERSE)
        prepared = v11.precompute_indicators(universe_data)
        latest_db_date = db.get_latest_date("SPY")
        db_last_write = datetime.fromtimestamp(Path(db.db_path).stat().st_mtime)

    if "SPY" not in prepared:
        raise RuntimeError("SPY no esta disponible en titan.db")

    analyzed_date = date_override
    if analyzed_date is None and demo:
        analyzed_date = recent_demo_date(prepared)

    if analyzed_date is not None:
        cutoff = pd.Timestamp(analyzed_date)
        prepared = {ticker: df.loc[:cutoff].copy() for ticker, df in prepared.items() if not df.loc[:cutoff].empty}
        universe_data = {ticker: df.loc[:cutoff].copy() for ticker, df in universe_data.items() if not df.loc[:cutoff].empty}

    regime_safe, regime_info = v11.check_regime(prepared["SPY"])
    breadth = v11.compute_breadth(universe_data)
    quality_alerts = v11.recent_quality_alerts(prepared)

    results_a: list[v11.ScanResult] = []
    results_c5: list[v11.ScanResult] = []
    blocked_extreme: list[v11.ScanResult] = []

    for ticker in sorted(t for t in prepared.keys() if t != "SPY"):
        df = prepared[ticker]
        if len(df) < 60:
            continue

        if regime_safe:
            sig_a = v11.signal_a_mean_reversion(ticker, df)
            if sig_a is not None:
                results_a.append(sig_a)

        c_candidate = v11.build_c5_candidate(ticker, df)
        if c_candidate is None:
            continue
        if any(existing.ticker == ticker for existing in results_a):
            continue
        if v11.c5_is_preferred(c_candidate):
            results_c5.append(c_candidate)
        else:
            blocked_extreme.append(c_candidate)

    all_results = results_a + results_c5
    all_results.sort(key=lambda item: item.score, reverse=True)
    results_a = [result for result in all_results if result.signal.startswith("A")]
    results_c5 = [result for result in all_results if result.signal.startswith("C5")]
    blocked_extreme.sort(key=lambda item: item.score, reverse=True)

    finished = datetime.now()
    elapsed = time.perf_counter() - t0
    latest_view = prepared["SPY"].index[-1].date().isoformat()
    freshness = "AL DIA" if latest_db_date == latest_view else f"VISTA HISTORICA ({latest_view})"
    regime_label = "SEGURO" if regime_info.get("safe") else "PELIGRO"

    return Snapshot(
        run_started=started,
        run_finished=finished,
        elapsed_sec=elapsed,
        analyzed_date=latest_view,
        latest_db_date=latest_db_date,
        db_last_write=db_last_write,
        freshness=freshness,
        regime_label=regime_label,
        breadth_pct=float(breadth["pct_above_sma50"]),
        coverage_count=len(prepared) - 1,
        missing_count=len(missing),
        results_a=results_a,
        results_c5=results_c5,
        blocked_extreme=blocked_extreme,
        quality_alerts=quality_alerts,
        demo_mode=demo or (date_override is not None),
        mode_label="DEMO / PREVIEW" if (demo or (date_override is not None)) else "LIVE",
    )


def build_showcase_snapshot() -> Snapshot:
    snapshot = gather_snapshot(None, False)
    snapshot.results_a = [
        make_result(
            ticker="AMD",
            signal="A",
            price=142.80,
            sector="Tecnologia",
            rsi=22.8,
            dist_sma50=-13.4,
            roc10=-11.7,
            vol_ratio=1.12,
            stop=136.20,
            target=154.20,
            risk_pct=4.6,
            score=89.4,
            note="Rebote tecnico con RSI extremo y mejora de impulso.",
        ),
        make_result(
            ticker="NKE",
            signal="A",
            price=91.40,
            sector="Consumo",
            rsi=24.6,
            dist_sma50=-11.1,
            roc10=-10.4,
            vol_ratio=0.96,
            stop=86.80,
            target=98.70,
            risk_pct=5.0,
            score=81.7,
            note="Mean reversion prolijo en activo defensivo castigado.",
        ),
        make_result(
            ticker="PYPL",
            signal="A",
            price=77.20,
            sector="Finanzas",
            rsi=23.9,
            dist_sma50=-12.7,
            roc10=-13.3,
            vol_ratio=1.21,
            stop=72.60,
            target=83.40,
            risk_pct=6.0,
            score=76.8,
            note="Rebote premium de 7 ruedas con momentum mejorando.",
        ),
    ]
    snapshot.results_c5 = [
        make_result(
            ticker="PAAS",
            signal="C5",
            price=46.66,
            sector="Materiales",
            rsi=28.2,
            dist_sma50=-18.9,
            roc10=-21.7,
            vol_ratio=3.16,
            stop=38.87,
            target=48.99,
            risk_pct=16.7,
            score=73.1,
            note="Crash controlado con probabilidad de rebote rapido.",
        ),
        make_result(
            ticker="AEM",
            signal="C5",
            price=179.13,
            sector="Materiales",
            rsi=28.9,
            dist_sma50=-16.3,
            roc10=-18.9,
            vol_ratio=2.66,
            stop=154.79,
            target=188.09,
            risk_pct=13.6,
            score=53.4,
            note="Caida fuerte pero aun dentro de cap operativa aceptable.",
        ),
        make_result(
            ticker="HMY",
            signal="C5",
            price=13.32,
            sector="Materiales",
            rsi=24.2,
            dist_sma50=-21.5,
            roc10=-32.0,
            vol_ratio=2.35,
            stop=10.76,
            target=13.99,
            risk_pct=19.2,
            score=83.3,
            note="Capitulacion fuerte con chance de rebote tecnico corto.",
        ),
        make_result(
            ticker="CDE",
            signal="C5",
            price=17.67,
            sector="Materiales",
            rsi=31.5,
            dist_sma50=-17.8,
            roc10=-22.0,
            vol_ratio=2.51,
            stop=14.32,
            target=18.55,
            risk_pct=19.0,
            score=56.9,
            note="Shock de precio sin romper el filtro de calidad.",
        ),
        make_result(
            ticker="NEM",
            signal="C5",
            price=95.80,
            sector="Materiales",
            rsi=26.9,
            dist_sma50=-14.5,
            roc10=-17.6,
            vol_ratio=2.62,
            stop=84.35,
            target=100.59,
            risk_pct=11.9,
            score=49.9,
            note="Crash mas defensivo, con menor upside pero mejor estabilidad.",
        ),
    ]
    snapshot.blocked_extreme = [
        make_result(
            ticker="NG",
            signal="C5X",
            price=8.90,
            sector="Materiales",
            rsi=19.8,
            dist_sma50=-34.0,
            roc10=-41.7,
            vol_ratio=5.42,
            stop=6.10,
            target=9.34,
            risk_pct=31.5,
            score=96.2,
            note="Descartado por violencia excesiva del crash.",
        ),
        make_result(
            ticker="MUX",
            signal="C5X",
            price=18.51,
            sector="Materiales",
            rsi=27.4,
            dist_sma50=-26.2,
            roc10=-27.9,
            vol_ratio=4.36,
            stop=14.69,
            target=19.44,
            risk_pct=20.6,
            score=88.7,
            note="Descartado por cap operativa de volumen.",
        ),
    ]
    snapshot.quality_alerts = [
        {
            "ticker": "BKNG",
            "date": "2026-04-02",
            "ret1": -96.0,
            "intraday": 1.2,
        }
    ]
    snapshot.demo_mode = True
    snapshot.mode_label = "SHOWCASE / PREVIEW"
    snapshot.preview_note = "Muestra visual con activos reales y datos de ejemplo. No usar para operar."
    snapshot.analyzed_date = snapshot.latest_db_date or snapshot.analyzed_date
    snapshot.regime_label = "SEGURO"
    snapshot.breadth_pct = 58.4
    return snapshot


def render_header(snapshot: Snapshot, title: str, subtitle: str) -> str:
    lines = [
        LINE,
        f"  {title}",
        LINE,
        f"  {subtitle}",
        SUBLINE,
        f"  Ejecucion del analisis : {execution_summary(snapshot)}",
        f"  Fecha analizada  : {snapshot.analyzed_date}",
        f"  Ultima fecha DB  : {snapshot.latest_db_date}",
        f"  Modo             : {snapshot.mode_label}",
        f"  Regimen          : {snapshot.regime_label}",
        f"  Breadth > SMA50  : {snapshot.breadth_pct:.1f}% | Cobertura {snapshot.coverage_count} tickers",
        f"  Senales          : {signal_breakdown(snapshot)}",
    ]
    if snapshot.preview_note:
        lines.append(f"  Nota preview     : {snapshot.preview_note}")
    if snapshot.blocked_extreme:
        lines.append(f"  Bloqueadas       : {len(snapshot.blocked_extreme)} crashes extremos fuera de cap")
    if snapshot.quality_alerts:
        alert = snapshot.quality_alerts[0]
        lines.append(
            f"  Alerta calidad   : {alert['ticker']} {alert['date']} | ret1 {alert['ret1']:+.1f}% | intraday {alert['intraday']:+.1f}%"
        )
    lines.append(LINE)
    return "\n".join(lines)


def render_minimal_header(snapshot: Snapshot, variant: str = "panel") -> str:
    lines = [
        LINE,
        "  PREVIEW V11 - MINIMAL",
        LINE,
    ]
    if variant == "actual":
        lines.extend(
            [
                SUBLINE,
                f"  Ejecucion del analisis : {execution_summary(snapshot)}",
                f"  Prediccion para        : {prediction_summary(snapshot)}",
            ]
        )
    elif variant == "split":
        lines.extend(
            [
                SUBLINE,
                f"  Ejecucion del analisis : {execution_window(snapshot)}",
                f"  Cierre base            : {closing_update(snapshot)}",
                f"  Prediccion para        : {prediction_summary(snapshot)}",
            ]
        )
    elif variant == "focus":
        lines.extend(
            [
                SUBLINE,
                f"  Prediccion para        : {prediction_summary(snapshot)}",
                f"  Cierre base            : {closing_update(snapshot)}",
                f"  Ejecucion del analisis : {execution_window(snapshot)}",
            ]
        )
    elif variant == "panel":
        pred_left = f"Prediccion para : {prediction_target(snapshot)}"
        pred_right = "Horizonte : 4 a 7 ruedas"
        lines.extend(
            [
                split_banner(pred_left, pred_right),
                SUBLINE,
                "  Control del informe",
                labeled_line("Datos ejecucion", execution_window(snapshot)),
                labeled_line("BBDD", closing_update(snapshot)),
                SUBLINE,
            ]
        )
    else:
        raise ValueError(variant)

    lines.extend(
        [
            labeled_line("Oportunidades", opportunities_summary(snapshot)),
            labeled_line("Salud del mercado", market_context(snapshot)),
        ]
    )
    if snapshot.quality_alerts:
        alert = snapshot.quality_alerts[0]
        lines.append(labeled_line("Alerta", quality_alert_summary(alert)))
    lines.append(LINE)
    return "\n".join(lines)


def render_minimal_header_gallery(snapshot: Snapshot) -> str:
    variants = [
        ("actual", "Version A - Inline actual"),
        ("split", "Version B - Separado por funcion"),
        ("focus", "Version C - Prediccion primero"),
        ("panel", "Version D - Mini bloque de control"),
    ]
    parts = []
    for variant, label in variants:
        header = render_minimal_header(snapshot, variant=variant).splitlines()
        if len(header) >= 2:
            header[1] = f"  {label}"
        parts.append("\n".join(header))
    return ("\n\n" + LINE + "\n\n").join(parts)


def render_no_signals(snapshot: Snapshot) -> str:
    if snapshot.regime_label == "PELIGRO":
        msg = "No hay senales preferred hoy. El mercado sigue en modo defensivo."
    else:
        msg = "No hay setups de calidad hoy. Esperar tambien es una decision valida."
    lines = [
        msg,
        "Que mirar igual:",
        "  - Si aparece una caida fuerte filtrada por calidad, priorizar prioridad, volumen y riesgo.",
        "  - Revisar el gestor de posiciones si ya hay trades abiertos.",
    ]
    if snapshot.blocked_extreme:
        tickers = ", ".join(result.ticker for result in snapshot.blocked_extreme[:5])
        lines.append(f"  - Hoy hubo crashes extremos bloqueados: {tickers}")
    return "\n".join(lines)


def result_rows(snapshot: Snapshot) -> list[v11.ScanResult]:
    return sorted(snapshot.results_a + snapshot.results_c5, key=lambda item: item.score, reverse=True)


def result_decision(result: v11.ScanResult) -> str:
    if result.signal.startswith("A"):
        return "Rebote premium 7d"
    return "Crash preferred + TP"


def upside_pct(result: v11.ScanResult) -> float:
    if result.price == 0:
        return 0.0
    return (result.target / result.price - 1.0) * 100.0


def color_setup_label(result: v11.ScanResult) -> str:
    return setup_label(result)


def color_upside(result: v11.ScanResult) -> str:
    return paint(f"{upside_pct(result):+.1f}%", "92")


def color_risk(result: v11.ScanResult) -> str:
    risk_text = f"{result.risk_pct:.1f}%"
    if result.risk_pct >= 15:
        return paint(risk_text, "93")
    if result.risk_pct >= 8:
        return paint(risk_text, "33")
    return risk_text


def color_priority(result: v11.ScanResult) -> str:
    score_text = f"{result.score:.1f}"
    if result.score >= 80:
        return paint(score_text, "92")
    if result.score >= 65:
        return paint(score_text, "36")
    return score_text


def blocked_reason(result: v11.ScanResult) -> str:
    reasons = []
    if result.score >= v11.C_SCORE_MAX:
        reasons.append(f"score extremo ({result.score:.1f})")
    if result.vol_ratio is not None and float(result.vol_ratio) >= v11.C_VOL_RATIO_CAP:
        reasons.append(f"volumen fuera de cap ({result.vol_ratio:.2f}x)")
    if not reasons:
        reasons.append("fuera de cap operativa")
    return " + ".join(reasons)


def render_blocked_details(snapshot: Snapshot) -> list[str]:
    if not snapshot.blocked_extreme:
        return []
    lines = [SUBLINE, "Activos bloqueados hoy:"]
    for result in snapshot.blocked_extreme[:4]:
        lines.append(f"  - {result.ticker}: {blocked_reason(result)}")
    extra = len(snapshot.blocked_extreme) - 4
    if extra > 0:
        lines.append(f"  - +{extra} bloqueados adicionales")
    lines.append("  - Lectura: activaron crash, pero el modelo los descarta por demasiado violentos para consumir slot.")
    return lines


def render_minimal(snapshot: Snapshot, header_variant: str = "panel") -> str:
    lines = [render_minimal_header(snapshot, variant=header_variant)]
    results = result_rows(snapshot)
    if not results:
        lines.append(render_no_signals(snapshot))
        lines.extend(render_blocked_details(snapshot))
        lines.append(SUBLINE)
        lines.append("Guia rapida:")
        lines.append("  - Rebote (A): rebote tecnico en mercado mas sano.")
        lines.append("  - Crash (C5): caida fuerte filtrada por calidad para buscar recuperacion.")
        lines.append("  - Salud del mercado: porcentaje de activos que siguen arriba de su media de 50 ruedas.")
        return "\n".join(lines)

    headers = ["#", "Ticker", "Precio ref.", "Objetivo", "Stop", "Setup", "Upside", "Riesgo", "RSI", "ROC10d", "Vol", "Prioridad"]
    rows = []
    for idx, result in enumerate(results, start=1):
        rows.append(
            [
                str(idx),
                result.ticker,
                money(result.price),
                money(result.target),
                money(result.stop),
                color_setup_label(result),
                color_upside(result),
                color_risk(result),
                "-" if result.rsi is None else f"{result.rsi:.1f}",
                "-" if result.roc10 is None else f"{result.roc10:.1f}%",
                "-" if result.vol_ratio is None else f"{result.vol_ratio:.2f}x",
                color_priority(result),
            ]
        )
    lines.append(render_table(headers, rows))
    lines.extend(render_blocked_details(snapshot))
    lines.append(SUBLINE)
    lines.append("Como leer esta tabla:")
    lines.append("  - Setup: Rebote (A) = rebote tecnico | Crash (C5) = caida fuerte filtrada por calidad.")
    lines.append("  - Precio ref.: ultimo cierre usado como referencia de entrada. No implica comprar exactamente en ese numero.")
    lines.append("  - Objetivo / Stop: salida esperada y limite defensivo propuestos por el modelo.")
    lines.append("  - Upside / Riesgo: ganancia potencial hasta objetivo y distancia estimada hasta stop.")
    lines.append("  - RSI: sobreventa de corto plazo. ROC10d: cambio en 10 ruedas. Vol: volumen vs promedio de 20 ruedas.")
    lines.append("  - Prioridad: puntaje interno del modelo; mas alto = setup relativamente mejor dentro del dia.")
    lines.append("  - Color suave: verde = mejor upside o prioridad | amarillo = riesgo mas exigente.")
    return "\n".join(lines)


def render_cards(snapshot: Snapshot) -> str:
    lines = [render_header(snapshot, "PREVIEW V11 - CARDS", "Version 2: fichas visuales, mas amigable para novato")]
    results = result_rows(snapshot)
    if not results:
        lines.append(render_no_signals(snapshot))
        return "\n".join(lines)

    for idx, result in enumerate(results, start=1):
        tier = "PREMIUM" if result.signal.startswith("A") else "PREFERRED"
        lines.append(f"[{idx}] {result.ticker}  |  {tier}  |  {result.signal}")
        lines.append(f"  Invertir si        : el setup sigue vigente al abrir / cierre siguiente")
        lines.append(f"  Precio actual      : {money(result.price)}")
        lines.append(f"  Objetivo posible   : {money(result.target)}  ({upside_pct(result):+.1f}%)")
        lines.append(f"  Stop defensivo     : {money(result.stop)}  (riesgo {result.risk_pct:.1f}%)")
        lines.append(f"  Sector             : {result.sector}")
        lines.append(
            f"  Valores tecnicos   : RSI {result.rsi if result.rsi is not None else '-'} | "
            f"vs SMA50 {pct_to_text(result.dist_sma50)} | ROC10d {pct_to_text(result.roc10)} | "
            f"Vol {('-' if result.vol_ratio is None else f'{result.vol_ratio:.2f}x')}"
        )
        lines.append(f"  Score del setup    : {result.score:.1f}")
        lines.append(f"  Lectura simple     : {result_decision(result)}")
        lines.append(f"  Nota del modelo    : {result.note}")
        lines.append(SUBLINE)
    return "\n".join(lines[:-1])


def render_expert(snapshot: Snapshot) -> str:
    lines = [render_header(snapshot, "PREVIEW V11 - EXPERT", "Version 3: vista compacta con mas densidad tecnica")]
    results = result_rows(snapshot)
    if not results:
        lines.append(render_no_signals(snapshot))
        return "\n".join(lines)

    headers = ["Ticker", "Sig", "Sector", "Px", "Stop", "Tgt", "R", "RSI", "dSMA50", "ROC10", "Vol", "Score", "Setup", "Nota"]
    rows = []
    for result in results:
        rows.append(
            [
                result.ticker,
                "A" if result.signal.startswith("A") else "C5",
                trim(result.sector, 10),
                money(result.price),
                money(result.stop),
                money(result.target),
                f"{result.risk_pct:.1f}%",
                "-" if result.rsi is None else f"{result.rsi:.1f}",
                pct_to_text(result.dist_sma50),
                pct_to_text(result.roc10),
                "-" if result.vol_ratio is None else f"{result.vol_ratio:.2f}x",
                f"{result.score:.1f}",
                trim(result_decision(result), 24),
                trim(result.note, 36),
            ]
        )
    lines.append(render_table(headers, rows))
    if snapshot.blocked_extreme:
        lines.append(SUBLINE)
        lines.append("Bloqueadas por cap operativa:")
        blocked_rows = []
        for result in snapshot.blocked_extreme[:5]:
            blocked_rows.append(
                [
                    result.ticker,
                    money(result.price),
                    pct_to_text(result.roc10),
                    "-" if result.vol_ratio is None else f"{result.vol_ratio:.2f}x",
                    f"{result.score:.1f}",
                ]
            )
        lines.append(render_table(["Ticker", "Px", "ROC10", "Vol", "Score"], blocked_rows))
    return "\n".join(lines)


def render_layout(snapshot: Snapshot, layout: str, header_variant: str = "panel") -> str:
    if layout == "minimal":
        return render_minimal(snapshot, header_variant=header_variant)
    if layout == "cards":
        return render_cards(snapshot)
    if layout == "expert":
        return render_expert(snapshot)
    raise ValueError(layout)


def main() -> None:
    args = parse_args()
    snapshot = build_showcase_snapshot() if args.showcase else gather_snapshot(args.date, args.demo)

    if args.minimal_header_gallery:
        print(render_minimal_header_gallery(snapshot))
        return

    layouts = ["minimal", "cards", "expert"] if args.layout == "gallery" else [args.layout]
    rendered = [render_layout(snapshot, layout, header_variant=args.minimal_header_variant) for layout in layouts]
    print(("\n\n" + LINE + "\n\n").join(rendered))


if __name__ == "__main__":
    main()
