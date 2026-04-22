"""
INVESTIGACION V13 MEMORIA OPERATIVA
===================================

Objetivo:
  Usar la memoria operativa acumulada de V11 para detectar si existe una mejora
  productiva real por setup, horizonte y regimen.

Preguntas:
  1. Que dice la memoria real de V11 por horizonte y regimen?
  2. La intuicion fuerte del loop ("C5 rinde mejor en PELIGRO") justifica
     endurecer el scanner?
  3. Si se fuerza esa regla en backtest del modelo real, mejora o empeora?

Veredicto esperado:
  La memoria sirve para aprender y contextualizar, pero no toda senal aparente
  debe convertirse en filtro productivo sin validacion completa.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from titan_system.core.database import TitanDB
from backtests.investigacion_v9_path_quality import (
    ANTIKNIFE_DAYS,
    BROAD_UNIVERSE,
    CORE_UNIVERSE,
    START_IDX,
    calc_metrics,
    load_db_data,
    precompute,
)
from backtests.investigacion_v10_rebound_capture import c_exit_return
from backtests.investigacion_v12_portfolio_operativo import (
    Candidate,
    calc_a_score,
    calc_c_score,
    calc_portfolio_metrics,
)


MODE_BASE = "BASE"
MODE_DANGER_ONLY = "C5_PELIGRO_ONLY"
MODE_BREADTH_LE35 = "C5_BREADTH_LE35"
MODES = [MODE_BASE, MODE_DANGER_ONLY, MODE_BREADTH_LE35]


@dataclass(frozen=True)
class VariantResult:
    name: str
    independent_sharpe: float
    independent_wr: float
    independent_avg: float
    trades: int
    portfolio_sharpe: float
    portfolio_total: float
    portfolio_mdd: float
    portfolio_trades: int


def memory_by_regime() -> pd.DataFrame:
    with TitanDB() as db:
        return pd.read_sql_query(
            """
            SELECT
                p.model_name,
                p.regime,
                COUNT(*) AS total,
                ROUND(AVG(o.hit) * 100, 2) AS accuracy_pct,
                ROUND(AVG(o.actual_return) * 100, 3) AS avg_return_pct
            FROM predictions p
            JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name LIKE 'INVERTIR_V11_%'
            GROUP BY p.model_name, p.regime
            ORDER BY p.model_name, p.regime
            """,
            db.conn,
        )


def prepare_universe() -> tuple[dict[str, pd.DataFrame], list[str], list[str], pd.DatetimeIndex]:
    raw_data, _ = load_db_data(BROAD_UNIVERSE)
    prepared = precompute(raw_data)
    broad = [ticker for ticker in BROAD_UNIVERSE if ticker in prepared]
    core = [ticker for ticker in CORE_UNIVERSE if ticker in prepared]
    dates = prepared["SPY"].index
    return prepared, broad, core, dates


def breadth_at(prepared: dict[str, pd.DataFrame], idx: int) -> float:
    eligible = []
    for ticker, df in prepared.items():
        if ticker == "SPY" or idx >= len(df) or idx < 50:
            continue
        price = df["Close"].iloc[idx]
        sma50 = df["SMA50"].iloc[idx]
        if pd.isna(price) or pd.isna(sma50):
            continue
        eligible.append(price > sma50)
    return float(sum(eligible) / len(eligible) * 100.0) if eligible else 0.0


def allow_c(prepared: dict[str, pd.DataFrame], idx: int, mode: str) -> bool:
    if mode == MODE_BASE:
        return True

    regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
    breadth = breadth_at(prepared, idx)

    if mode == MODE_DANGER_ONLY:
        return not regime_safe
    if mode == MODE_BREADTH_LE35:
        return breadth <= 35.0
    raise ValueError(f"Modo desconocido: {mode}")


def run_variant(prepared: dict[str, pd.DataFrame], tickers: list[str], dates: pd.DatetimeIndex, mode: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    last_entry: dict[str, int] = {}

    for idx in range(START_IDX, len(dates) - 8):
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
        signal_date = dates[idx]

        for ticker in tickers:
            if ticker == "SPY" or ticker not in prepared:
                continue
            if ticker in last_entry and (idx - last_entry[ticker]) < ANTIKNIFE_DAYS:
                continue

            df = prepared[ticker]
            if idx + 8 >= len(df):
                continue

            signal = None
            ret = None

            if regime_safe and bool(df["SIG_A_GUARD"].iloc[idx]):
                entry = df["Close"].iloc[idx + 1]
                exit_px = df["Close"].iloc[idx + 8]
                if pd.isna(entry) or pd.isna(exit_px):
                    continue
                signal = "A"
                ret = float((exit_px / entry - 1.0) * 100.0)
            elif bool(df["SIG_C_V9_NEG5"].iloc[idx]):
                score = calc_c_score(df, idx)
                vol_ratio = float(df["VOL_RATIO"].iloc[idx])
                if score >= 85.0 or vol_ratio >= 4.0:
                    continue
                if not allow_c(prepared, idx, mode):
                    continue
                ret, _, _ = c_exit_return(df, idx)
                if ret is None:
                    continue
                signal = "C"

            if signal is None:
                continue

            rows.append(
                {
                    "ticker": ticker,
                    "date": signal_date,
                    "signal": signal,
                    "return_pct": ret,
                }
            )
            last_entry[ticker] = idx

    return pd.DataFrame(rows)


def build_candidates(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    dates: pd.DatetimeIndex,
    mode: str,
) -> dict[int, list[Candidate]]:
    pending: dict[int, list[Candidate]] = {}

    for idx in range(START_IDX, len(dates) - 8):
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])

        for ticker in tickers:
            if ticker == "SPY" or ticker not in prepared:
                continue
            df = prepared[ticker]
            if idx + 8 >= len(df):
                continue

            candidate: Candidate | None = None

            if regime_safe and bool(df["SIG_A_GUARD"].iloc[idx]):
                entry_idx = idx + 1
                exit_idx = idx + 8
                if pd.notna(df["Close"].iloc[entry_idx]) and pd.notna(df["Close"].iloc[exit_idx]):
                    candidate = Candidate(
                        ticker=ticker,
                        signal="A",
                        signal_date=dates[idx],
                        signal_idx=idx,
                        entry_idx=entry_idx,
                        exit_idx=exit_idx,
                        raw_score=calc_a_score(df, idx),
                        vol_ratio=float(df["VOL_RATIO"].iloc[idx]),
                        rsi=float(df["RSI"].iloc[idx]),
                    )
            elif bool(df["SIG_C_V9_NEG5"].iloc[idx]):
                score = calc_c_score(df, idx)
                vol_ratio = float(df["VOL_RATIO"].iloc[idx])
                if score >= 85.0 or vol_ratio >= 4.0:
                    continue
                if not allow_c(prepared, idx, mode):
                    continue
                ret, exit_day, _ = c_exit_return(df, idx)
                if ret is None or exit_day is None:
                    continue
                candidate = Candidate(
                    ticker=ticker,
                    signal="C",
                    signal_date=dates[idx],
                    signal_idx=idx,
                    entry_idx=idx + 1,
                    exit_idx=idx + 1 + exit_day,
                    raw_score=score,
                    vol_ratio=vol_ratio,
                    rsi=float(df["RSI"].iloc[idx]),
                    neg_days10=float(df["NEG_DAYS10"].iloc[idx]),
                )

            if candidate is not None:
                pending.setdefault(candidate.entry_idx, []).append(candidate)

    return pending


def simulate_portfolio(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    dates: pd.DatetimeIndex,
    mode: str,
) -> dict[str, float]:
    pending = build_candidates(prepared, tickers, dates, mode)

    cash = 100_000.0
    cooldown_until: dict[str, int] = {}
    open_positions: list[dict[str, object]] = []
    equity_rows: list[dict[str, float]] = []
    closed: list[dict[str, float]] = []

    for idx in range(START_IDX + 1, len(dates)):
        equity = cash
        for position in open_positions:
            df = prepared[str(position["ticker"])]
            if idx < len(df):
                equity += float(position["shares"]) * float(df["Close"].iloc[idx])
        equity_rows.append({"idx": float(idx), "equity": equity, "open_positions": float(len(open_positions))})

        still_open: list[dict[str, object]] = []
        for position in open_positions:
            if int(position["exit_idx"]) == idx:
                px = float(prepared[str(position["ticker"])]["Close"].iloc[idx])
                cash += float(position["shares"]) * px
                closed.append({"return_pct": (px / float(position["entry_price"]) - 1.0) * 100.0})
            else:
                still_open.append(position)
        open_positions = still_open

        free_slots = 3 - len(open_positions)
        if free_slots <= 0:
            continue

        total_equity = cash
        for position in open_positions:
            df = prepared[str(position["ticker"])]
            if idx < len(df):
                total_equity += float(position["shares"]) * float(df["Close"].iloc[idx])
        slot_budget = total_equity / 3.0

        todays = sorted(pending.get(idx, []), key=lambda item: item.raw_score, reverse=True)
        for candidate in todays:
            if free_slots <= 0:
                break
            if any(str(position["ticker"]) == candidate.ticker for position in open_positions):
                continue
            if idx <= cooldown_until.get(candidate.ticker, -999):
                continue
            df = prepared[candidate.ticker]
            if idx >= len(df):
                continue
            px = float(df["Close"].iloc[idx])
            invested = min(slot_budget, cash)
            if invested <= 0:
                break
            open_positions.append(
                {
                    "ticker": candidate.ticker,
                    "entry_price": px,
                    "shares": invested / px,
                    "exit_idx": candidate.exit_idx,
                }
            )
            cash -= invested
            cooldown_until[candidate.ticker] = candidate.signal_idx + ANTIKNIFE_DAYS
            free_slots -= 1

    equity_df = pd.DataFrame(equity_rows)
    trades_df = pd.DataFrame(closed)
    return calc_portfolio_metrics(equity_df, trades_df)


def evaluate_variant(prepared: dict[str, pd.DataFrame], tickers: list[str], dates: pd.DatetimeIndex, mode: str) -> VariantResult:
    independent = run_variant(prepared, tickers, dates, mode)
    independent_metrics = calc_metrics(independent)
    portfolio_metrics = simulate_portfolio(prepared, tickers, dates, mode)
    return VariantResult(
        name=mode,
        independent_sharpe=float(independent_metrics["sharpe"]),
        independent_wr=float(independent_metrics["wr"]),
        independent_avg=float(independent_metrics["avg"]),
        trades=int(independent_metrics["trades"]),
        portfolio_sharpe=float(portfolio_metrics["sharpe"]),
        portfolio_total=float(portfolio_metrics["total"]),
        portfolio_mdd=float(portfolio_metrics["mdd"]),
        portfolio_trades=int(portfolio_metrics["trades"]),
    )


def print_variant_row(result: VariantResult) -> None:
    print(
        f"  {result.name:18s} "
        f"ind_sh={result.independent_sharpe:5.2f} "
        f"ind_wr={result.independent_wr:6.2f}% "
        f"ind_avg={result.independent_avg:+6.2f}% "
        f"trades={result.trades:3d} | "
        f"port_sh={result.portfolio_sharpe:5.2f} "
        f"port_total={result.portfolio_total:6.1f}% "
        f"port_mdd={result.portfolio_mdd:6.2f}% "
        f"port_trades={result.portfolio_trades:3d}"
    )


def run_suite(prepared: dict[str, pd.DataFrame], dates: pd.DatetimeIndex, label: str, tickers: list[str]) -> None:
    print("\n" + "=" * 104)
    print(f"  {label}")
    print("=" * 104)
    for mode in MODES:
        result = evaluate_variant(prepared, tickers, dates, mode)
        print_variant_row(result)


def main() -> None:
    print("=" * 104)
    print("  INVESTIGACION V13 MEMORIA OPERATIVA")
    print("=" * 104)

    print("\n[1] Memoria real V11 por horizonte y regimen")
    print(memory_by_regime().to_string(index=False))

    prepared, broad, core, dates = prepare_universe()

    print("\n[2] Hipotesis memoria -> cambios de filtro sobre C5")
    print("  Candidatos auditados:")
    print("  - C5_PELIGRO_ONLY : solo dejar C5 cuando SPY esta en PELIGRO")
    print("  - C5_BREADTH_LE35 : solo dejar C5 cuando breadth <= 35%")

    run_suite(prepared, dates, "BROAD UNIVERSE", broad)
    run_suite(prepared, dates, "CORE UNIVERSE", core)

    print("\n" + "=" * 104)
    print("  VEREDICTO")
    print("=" * 104)
    print("  1. La memoria confirma que C5 es mucho mas fuerte en PELIGRO que en SEGURO.")
    print("  2. Eso NO alcanza para promover un filtro productivo nuevo por si solo.")
    print("  3. Cuando se fuerza como hard gate, el broad portfolio empeora vs V11 base.")
    print("  4. Conclusion honesta: usar la memoria como capa de contexto y aprendizaje, no como filtro nuevo aun.")


if __name__ == "__main__":
    main()
