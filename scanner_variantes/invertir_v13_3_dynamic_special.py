#!/usr/bin/env python3
"""
INVERTIR V13_3 - Variante Dynamic Special sobre V13
===================================================

Variante ejecutable no promovida.
No reemplaza automaticamente a V13.

Hipotesis cristalizada desde investigacion_v26_dynamic_special_frontier.py:
  1. D mejora si excluye tickers Auto explicitamente.
  2. E_HW sigue siendo el sleeve RS base mas robusto.
  3. Los sleeves especiales RS deben activarse segun regimen y breadth:
     - E_AUTO   solo en SEGURO
     - E_TRAVEL solo en PELIGRO
     - E_TECH   solo en SEGURO y con breadth >= 55%

Arquitectura variante:
  - Signal A        : mean reversion con regime (igual a V13)
  - Signal C5       : crash + path quality (igual a V13)
  - Signal D        : liderazgo sin tickers Auto
  - Signal E_HW     : RS New High hardware (base estable)
  - Signal E_AUTO   : sleeve extra solo en SEGURO
  - Signal E_TRAVEL : sleeve extra solo en PELIGRO
  - Signal E_TECH   : sleeve extra solo en SEGURO con breadth >= 55%

Resultado de referencia (DB al 2026-04-13):
  - V13 base                 : Sharpe 1.66 | WR 61.2% | MDD -37.0%
  - V13_3 variante full      : Sharpe 1.96 | WR 62.2% | MDD -27.9%
  - WF                       : 4/7 y 7/10
  - Recientes                : mejora clara desde 2024+

Caveat honesto:
  - La variante balanceada gana fuerte en agregado y mejora drawdown,
    pero todavia no barre todos los anos por separado.
  - Por eso hoy vive como variante no promovida, no como champion oficial.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner_variantes import invertir_v13_2_auto_hygiene as base
from titan_system.core.database import TitanDB
from backtests.investigacion_v17_signal_d_audit import SECTOR_MAP


MODEL_NAME = "INVERTIR_V13_3"
LINE = base.LINE
SUBLINE = base.SUBLINE

AUTO_TICKERS = base.AUTO_TICKERS
E_HW_TICKERS = base.E_HW_TICKERS
TRAVEL_TICKERS = frozenset({"AAL", "ABNB", "CAR", "CCL", "DAL", "LVS", "SPCE", "TCOM", "TRIP", "UAL"})
TECH_TICKERS = frozenset(ticker for ticker, sector in SECTOR_MAP.items() if sector == "Tech")

TECH_MIN_BREADTH = 55.0
TECH_VOL_MAX = 2.0

ScanResult = base.ScanResult
Snapshot = base.Snapshot


def sector_label(signal_name: str) -> str:
    if signal_name.startswith("E_AUTO"):
        return "RS Auto (E)"
    if signal_name.startswith("E_TRAVEL"):
        return "RS Travel (E)"
    if signal_name.startswith("E_TECH"):
        return "RS Tech (E)"
    return "RS HW (E)"


def count_signal(results: list[ScanResult], prefix: str) -> int:
    return sum(1 for result in results if result.signal.startswith(prefix))


def active_special_sleeves(results: list[ScanResult]) -> list[str]:
    sleeves: list[str] = []
    if any(result.signal.startswith("E_AUTO") for result in results):
        sleeves.append("AUTO_SAFE")
    if any(result.signal.startswith("E_TRAVEL") for result in results):
        sleeves.append("TRAVEL_DANGER")
    if any(result.signal.startswith("E_TECH") for result in results):
        sleeves.append("TECH_SAFE_B55")
    return sleeves


def effective_slot_count(results: list[ScanResult]) -> int:
    return base.SIZING_BASE_SLOTS + len(active_special_sleeves(results))


def opportunities_summary(snapshot: Snapshot) -> str:
    total = len(snapshot.results_a) + len(snapshot.results_c5) + len(snapshot.results_d) + len(snapshot.results_e)
    return (
        f"Total {total} | Rebotes {len(snapshot.results_a)} | Crashes {len(snapshot.results_c5)} | "
        f"Liderazgo {len(snapshot.results_d)} | E_HW {count_signal(snapshot.results_e, 'E_HW')} | "
        f"E_AUTO {count_signal(snapshot.results_e, 'E_AUTO')} | "
        f"E_TRAVEL {count_signal(snapshot.results_e, 'E_TRAVEL')} | "
        f"E_TECH {count_signal(snapshot.results_e, 'E_TECH')}"
    )


def render_header(snapshot: Snapshot) -> str:
    lines = [
        LINE,
        f"  {MODEL_NAME} | Variante no promovida",
        LINE,
        base.labeled_line("Cierre analizado", base.format_spanish_date(snapshot.analyzed_date)),
        base.labeled_line("Ventana objetivo", base.prediction_target(snapshot)),
        base.labeled_line("Estado senal", base.prediction_status_text(snapshot)),
        base.labeled_line("BBDD", f"{base.format_spanish_datetime(snapshot.db_last_write)} | {snapshot.freshness}"),
        base.labeled_line("Oportunidades", opportunities_summary(snapshot)),
        base.labeled_line("Salud mercado", base.market_context(snapshot)),
        base.labeled_line(
            "Tesis V13_3",
            "D sin Auto + E_HW + Auto Safe + Travel Danger + Tech Safe breadth>=55",
        ),
    ]
    if snapshot.quality_alerts:
        lines.append(base.labeled_line("Alerta", base.quality_alert_summary(snapshot.quality_alerts[0])))
    lines.append(LINE)
    return "\n".join(lines)


def render_no_signals(snapshot: Snapshot) -> str:
    lines: list[str] = []
    if not base.snapshot_actionable(snapshot):
        lines.append(f"Atencion: {base.prediction_status(snapshot)[1]}")
        lines.append("No operar esta salida como si fuera la rueda vigente.")
    if snapshot.regime_label == "PELIGRO":
        lines.append("No hay senales preferred hoy. El mercado sigue en modo defensivo.")
    else:
        lines.append("No hay setups de calidad hoy. Esperar tambien es una decision valida.")
    lines.append("Que mirar igual:")
    lines.append("  - Liderazgo (D): tendencia relativa fuerte, con Auto explicitamente excluido.")
    lines.append("  - RS HW (E): sleeve RS base de continuidad.")
    lines.append("  - RS Auto (E): sleeve extra solo cuando SPY esta en SEGURO.")
    lines.append("  - RS Travel (E): sleeve extra solo cuando SPY esta en PELIGRO.")
    lines.append("  - RS Tech (E): sleeve extra solo si SPY esta en SEGURO y breadth>=55%.")
    lines.append("  - Crash (C5): caida fuerte filtrada por calidad.")
    return "\n".join(lines)


def setup_label(result: ScanResult) -> str:
    if result.signal.startswith("A"):
        return "Rebote (A)"
    if result.signal.startswith("C5"):
        return "Crash (C5)"
    if result.signal.startswith("D"):
        return "Liderazgo (D)"
    return sector_label(result.signal)


def render_body(snapshot: Snapshot) -> str:
    results = sorted(
        snapshot.results_a + snapshot.results_c5 + snapshot.results_d + snapshot.results_e,
        key=lambda item: (
            float(item.priority_score) if item.priority_score is not None else float(item.score),
        ),
        reverse=True,
    )

    if not results:
        return render_no_signals(snapshot)

    headers = [
        "#",
        "Ticker",
        "Setup",
        "Hold",
        "Precio",
        "Objetivo",
        "Stop",
        "Upside",
        "Riesgo",
        "RSI",
        "ROC20",
        "Rel20",
        "Vol",
        "Prio",
    ]
    rows: list[list[str]] = []
    for idx, result in enumerate(results, start=1):
        rows.append(
            [
                str(idx),
                result.ticker,
                setup_label(result),
                base.hold_label(result),
                base.money(result.price),
                base.money(result.target),
                base.money(result.stop),
                base.color_upside(result),
                base.color_risk(result),
                "-" if result.rsi is None else f"{result.rsi:.1f}",
                "-" if result.roc20 is None else f"{result.roc20:.1f}%",
                "-" if result.rel20 is None else f"{result.rel20:.1f}%",
                "-" if result.vol_ratio is None else f"{result.vol_ratio:.2f}x",
                base.color_priority(result),
            ]
        )

    lines: list[str] = []
    if not base.snapshot_actionable(snapshot):
        lines.append(f"Atencion: {base.prediction_status(snapshot)[1]}")
        lines.append("No operar esta salida como vigente; sirve solo como auditoria.")
        lines.append(SUBLINE)
    lines.append(base.render_table(headers, rows))
    lines.extend(base.render_blocked_details(snapshot))
    lines.append(SUBLINE)
    lines.append("Como leer esta tabla:")
    lines.append("  - D excluye Auto por higiene estadistica.")
    lines.append("  - E_AUTO es un sleeve extra solo en regimen SEGURO.")
    lines.append("  - E_TRAVEL es un sleeve extra solo en regimen PELIGRO.")
    lines.append("  - E_TECH es un sleeve extra solo en SEGURO y con breadth>=55%.")
    lines.append("  - Si un ticker dispara varias tesis, queda la de mayor prioridad.")
    lines.append("  - (*) C5 sale a +6% si ocurre antes del dia 7; sino al dia 7.")
    lines.append("  - Esta variante no fue promovida: sirve para contrastar contra V13 sin tocar el champion.")
    return "\n".join(lines)


def render_sizing_block(results: list[ScanResult], equity_base: float | None) -> str:
    if equity_base is None:
        return (
            SUBLINE + "\n"
            "  Sizing V13_3: no configurado. Ejecutar:\n"
            "    python herramientas/gestor_posiciones_v11.py config --equity-base TU_CAPITAL\n"
            f"  O correr: python {Path(__file__).as_posix()} --equity TU_CAPITAL\n"
        )
    if not results:
        return ""

    slot_count = effective_slot_count(results)
    sleeve_names = active_special_sleeves(results)
    sized: list[tuple[ScanResult, dict[str, float]]] = []
    for result in results:
        sizing = base.calc_sizing(result.atr_pct, equity_base, slot_count)
        shares = round(sizing["notional"] / result.price, 1) if result.price > 0 else 0.0
        gain_usd = round(shares * (result.target - result.price), 2)
        risk_usd = round(shares * (result.price - result.stop), 2) if result.stop > 0 else 0.0
        sized.append(
            (
                result,
                {
                    **sizing,
                    "shares": shares,
                    "gain_usd": gain_usd,
                    "gain_pct": round(gain_usd / equity_base * 100.0, 2),
                    "risk_usd": risk_usd,
                    "risk_pct": round(risk_usd / equity_base * 100.0, 2),
                },
            )
        )

    lines = [SUBLINE]
    lines.append(
        f"  Cuanto invertir | Equity: {base.money(equity_base)} | Slot base: {base.money(equity_base / slot_count)} | "
        f"Slots asumidos: {slot_count}"
    )
    if sleeve_names:
        lines.append(f"  Sleeves extra activos hoy: {', '.join(sleeve_names)}")
    else:
        lines.append("  Sleeves extra activos hoy: ninguno")
    lines.append("  Nota: 4 slots base + 1 slot por sleeve especial activo (Auto/Travel/Tech).")
    lines.append("  Si hay varias ideas dentro del mismo sleeve extra, priorizar primero la de arriba.")
    lines.append(SUBLINE)

    headers = ["#", "Ticker", "Setup", "Hold", "Comprar", "Invertir", "Si sube", "Si cae", "Riesgo eq."]
    rows: list[list[str]] = []
    for idx, (result, info) in enumerate(sized, start=1):
        risk_color = "91" if info["risk_pct"] > 3 else ("93" if info["risk_pct"] > 2 else "32")
        rows.append(
            [
                str(idx),
                result.ticker,
                setup_label(result),
                base.hold_label(result),
                f"{info['shares']:.0f} acc a {base.money(result.price)}",
                base.paint(base.money(info["notional"]), "1"),
                base.paint(f"+{base.money(info['gain_usd'])} (+{info['gain_pct']:.1f}%)", "92"),
                base.paint(f"-{base.money(info['risk_usd'])} (-{info['risk_pct']:.1f}%)", "91"),
                base.paint(f"{info['risk_pct']:.1f}%", risk_color),
            ]
        )

    lines.append(base.render_table(headers, rows))
    lines.append("")
    lines.append("  Orden: mayor prioridad arriba.")
    lines.append("  Monto: ajustado por ATR para emparejar riesgo entre posiciones.")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="INVERTIR V13_3 - variante dynamic special no promovida"
    )
    parser.add_argument(
        "--equity",
        type=float,
        default=None,
        help="Capital disponible en USD (sobreescribe el valor guardado en el gestor)",
    )
    return parser.parse_args()


def signal_e_sector_rs_new_high(
    ticker: str,
    df: pd.DataFrame,
    *,
    allowed_tickers: frozenset[str],
    signal_name: str,
    regime_safe: bool,
    require_safe: bool | None,
    breadth_pct: float,
    minimum_breadth: float | None = None,
    minimum_roc20: float = base.E_ROC20_MIN,
    maximum_vol_ratio: float = base.E_VOL_MAX,
) -> ScanResult | None:
    if ticker not in allowed_tickers:
        return None
    if require_safe is True and not regime_safe:
        return None
    if require_safe is False and regime_safe:
        return None
    if minimum_breadth is not None and breadth_pct < minimum_breadth:
        return None
    if len(df) < 260:
        return None

    row = df.iloc[-1]
    required_cols = [
        "RS_LINE",
        "RS_52W_MAX",
        "Close",
        "SMA50",
        "SMA200",
        "RSI",
        "VOL_RATIO",
        "ROC20",
        "ATR",
    ]
    if any(pd.isna(row.get(column, float("nan"))) for column in required_cols):
        return None

    corp_action = bool(row.get("CORP_ACTION_10D", False))
    if corp_action:
        return None

    price = float(row["Close"])
    sma50 = float(row["SMA50"])
    sma200 = float(row["SMA200"])
    rs_line = float(row["RS_LINE"])
    rs_52w_max = float(row["RS_52W_MAX"])
    rsi = float(row["RSI"])
    vol_ratio = float(row["VOL_RATIO"])
    roc20 = float(row["ROC20"])
    curr_atr = float(row["ATR"])

    if rs_line < rs_52w_max:
        return None
    if price <= sma50 or sma50 <= sma200:
        return None
    if rsi < base.E_RSI_MIN or rsi > base.E_RSI_MAX:
        return None
    if roc20 <= minimum_roc20:
        return None
    if vol_ratio < base.E_VOL_MIN or vol_ratio > maximum_vol_ratio:
        return None

    if pd.isna(curr_atr) or curr_atr <= 0:
        curr_atr = price * 0.03

    stop = price - 2.0 * curr_atr
    target = max(price * (1.0 + base.E_TARGET_PCT / 100.0), price + 2.0 * curr_atr)
    risk_pct = (1.0 - stop / price) * 100.0
    rs_excess = (rs_line / (rs_52w_max + 1e-10) - 1.0) * 100.0
    atr_pct = curr_atr / price * 100.0

    if require_safe is True:
        mode_note = "solo SEGURO"
    elif require_safe is False:
        mode_note = "solo PELIGRO"
    else:
        mode_note = "cualquier regimen"

    note_parts = [f"RS New High | hold {base.E_HOLDING_DAYS}d", mode_note, f"RS excess {rs_excess:+.1f}%"]
    if minimum_breadth is not None:
        note_parts.append(f"breadth>={minimum_breadth:.0f}%")

    return ScanResult(
        ticker=ticker,
        signal=signal_name,
        price=round(price, 2),
        sector=base.get_sector(ticker),
        rsi=round(rsi, 1),
        dist_sma50=round((price / sma50 - 1.0) * 100.0, 1),
        roc10=None,
        roc20=round(roc20, 1),
        rel20=None,
        vol_ratio=round(vol_ratio, 2),
        stop=round(stop, 2),
        target=round(target, 2),
        risk_pct=round(risk_pct, 1),
        score=float(roc20 + rs_excess * 0.5),
        note=" | ".join(note_parts),
        atr_pct=round(atr_pct, 2),
    )


def dedupe_by_ticker(results: list[ScanResult]) -> list[ScanResult]:
    ordered = base.assign_priority_scores(results)
    unique: list[ScanResult] = []
    seen: set[str] = set()
    for result in ordered:
        if result.ticker in seen:
            continue
        seen.add(result.ticker)
        unique.append(result)
    return unique


def main() -> None:
    args = parse_args()
    run_started = datetime.now()
    today = date.today()

    with TitanDB() as db:
        universe_data, _missing = base.load_universe_data(db, base.UNIVERSE)
        prepared = base.precompute_indicators(universe_data)

        if "SPY" not in prepared:
            print("ERROR: SPY no esta en titan.db. No se puede evaluar el regimen.")
            return

        latest_date_str = db.get_latest_date("SPY")
        latest_dt = datetime.strptime(latest_date_str, "%Y-%m-%d").date() if latest_date_str else None
        staleness = base.business_days_between(latest_dt, today) if latest_dt else None
        freshness = "AL DIA" if staleness is not None and staleness <= 1 else (
            f"STALE ({staleness} dias habiles)" if staleness is not None else "SIN DATO"
        )

        regime_safe, regime_info = base.check_regime(prepared["SPY"])
        breadth = base.compute_breadth(universe_data)
        breadth_pct = float(breadth["pct_above_sma50"])
        quality_alerts = base.recent_quality_alerts(prepared)
        market_status = db.get_market_data_status()
        db_last_write = None
        updated_at_text = market_status.get("market_data_updated_at")
        latest_prices_date = market_status.get("latest_prices_date")
        if updated_at_text and latest_prices_date == latest_date_str:
            db_last_write = datetime.strptime(updated_at_text, "%Y-%m-%d %H:%M:%S")

        raw_results: list[ScanResult] = []
        blocked_extreme: list[ScanResult] = []

        for ticker in sorted(ticker for ticker in prepared.keys() if ticker != "SPY"):
            df = prepared[ticker]

            if regime_safe:
                sig_a = base.signal_a_mean_reversion(ticker, df)
                if sig_a is not None:
                    raw_results.append(sig_a)

            d_candidate = base.signal_d_leadership(ticker, df)
            if d_candidate is not None:
                raw_results.append(d_candidate)

            e_hw_candidate = signal_e_sector_rs_new_high(
                ticker,
                df,
                allowed_tickers=E_HW_TICKERS,
                signal_name="E_HW (RS High)",
                regime_safe=regime_safe,
                require_safe=None,
                breadth_pct=breadth_pct,
            )
            if e_hw_candidate is not None:
                raw_results.append(e_hw_candidate)

            e_auto_candidate = signal_e_sector_rs_new_high(
                ticker,
                df,
                allowed_tickers=AUTO_TICKERS,
                signal_name="E_AUTO (RS High)",
                regime_safe=regime_safe,
                require_safe=True,
                breadth_pct=breadth_pct,
            )
            if e_auto_candidate is not None:
                raw_results.append(e_auto_candidate)

            e_travel_candidate = signal_e_sector_rs_new_high(
                ticker,
                df,
                allowed_tickers=TRAVEL_TICKERS,
                signal_name="E_TRAVEL (RS High)",
                regime_safe=regime_safe,
                require_safe=False,
                breadth_pct=breadth_pct,
            )
            if e_travel_candidate is not None:
                raw_results.append(e_travel_candidate)

            e_tech_candidate = signal_e_sector_rs_new_high(
                ticker,
                df,
                allowed_tickers=TECH_TICKERS,
                signal_name="E_TECH (RS High)",
                regime_safe=regime_safe,
                require_safe=True,
                breadth_pct=breadth_pct,
                minimum_breadth=TECH_MIN_BREADTH,
                maximum_vol_ratio=TECH_VOL_MAX,
            )
            if e_tech_candidate is not None:
                raw_results.append(e_tech_candidate)

            c_candidate = base.build_c5_candidate(ticker, df)
            if c_candidate is None:
                continue
            if base.c5_is_preferred(c_candidate):
                raw_results.append(c_candidate)
            else:
                blocked_extreme.append(c_candidate)

        all_results = dedupe_by_ticker(raw_results)
        results_a = [result for result in all_results if result.signal.startswith("A")]
        results_c5 = [result for result in all_results if result.signal.startswith("C5")]
        results_d = [result for result in all_results if result.signal.startswith("D")]
        results_e = [result for result in all_results if result.signal.startswith("E")]
        blocked_extreme.sort(key=lambda item: item.score, reverse=True)

        analyzed_date = prepared["SPY"].index[-1].date().isoformat()
        snapshot = Snapshot(
            run_started=run_started,
            run_finished=datetime.now(),
            analyzed_date=analyzed_date,
            db_last_write=db_last_write,
            freshness=freshness,
            regime_label="SEGURO" if regime_safe else "PELIGRO",
            breadth_pct=breadth_pct,
            results_a=results_a,
            results_c5=results_c5,
            results_d=results_d,
            results_e=results_e,
            blocked_extreme=blocked_extreme,
            quality_alerts=quality_alerts,
            is_panic=bool(regime_info.get("is_panic", False)),
        )

    print(render_header(snapshot))
    print(render_body(snapshot))

    all_signals = sorted(
        snapshot.results_a + snapshot.results_c5 + snapshot.results_d + snapshot.results_e,
        key=lambda item: (
            float(item.priority_score) if item.priority_score is not None else float(item.score),
        ),
        reverse=True,
    )

    if not all_signals:
        return

    if not base.snapshot_actionable(snapshot):
        print(SUBLINE)
        print("  Sizing omitido: la senal no esta vigente o la base esta stale.")
        return

    equity_base = args.equity
    if equity_base is None:
        saved = base.load_equity_base()
        print(SUBLINE)
        try:
            hint = f" (Enter = usar guardado ${saved:,.0f})" if saved else ""
            raw = input(f"  Capital disponible en USD{hint}: ").strip()
        except EOFError:
            raw = ""
        if raw:
            equity_base = float(raw)
        elif saved:
            equity_base = saved

    print(render_sizing_block(all_signals, equity_base))


if __name__ == "__main__":
    main()
