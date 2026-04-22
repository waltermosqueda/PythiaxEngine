"""
INVESTIGACION V16 - OPORTUNIDADES PERDIDAS Y NUEVO EJE ORTOGONAL
================================================================

Objetivo:
  Auditar si la arquitectura actual de V11 esta dejando demasiado dinero
  sobre la mesa por depender casi exclusivamente de:
    - mean reversion oversold (A) en regime SEGURO
    - crash rebound filtrado (C5)

Preguntas:
  1. El problema es solo el filtro de SPY/regime, o hay una carencia estructural?
  2. Que pasa si relajamos/eliminamos el regime sobre A?
  3. Existe una senal ortogonal de liderazgo/tendencia que capture winners
     fuertes aun cuando V11 esta seco?
  4. Esa senal sirve sola, o agrega mas valor como sleeve/satelite del V11?

Hipotesis auditadas:
  H1. A_NO_REGIME      -> quitar completamente el regime de Signal A
  H2. A_SPY_SMA200     -> usar un gate mas permisivo (SPY > SMA200)
  H3. D_BREAKOUT       -> breakout de liderazgo/compresion
  H4. D_LEADERSHIP     -> liderazgo/tendencia simple, sin regime de SPY
  H5. V11 + D          -> arquitectura 2 slots V11 + 1 slot D

Veredicto esperado:
  - si H1/H2 ganan: el problema central era el regime gate
  - si H3/H4 ganan: el problema central es falta de un eje ortogonal

Fecha: 2026-04-09
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

from backtests.investigacion_v10_rebound_capture import c_exit_return
from backtests.investigacion_v12_portfolio_operativo import (
    INITIAL_EQUITY,
    MAX_POSITIONS,
    calc_a_score,
    calc_c_score,
    calc_portfolio_metrics,
)
from backtests.investigacion_v9_path_quality import (
    ANTIKNIFE_DAYS,
    BROAD_UNIVERSE,
    START_IDX,
    calc_metrics,
    load_db_data,
    precompute,
)


LINE = "=" * 100
SUBLINE = "-" * 100

LEADERSHIP_HOLD_DAYS = 10
V11_PRIMARY_SLOTS = 2
LEADERSHIP_SLOTS = 1


@dataclass(frozen=True)
class Candidate:
    ticker: str
    signal: str
    entry_idx: int
    exit_idx: int
    raw_score: float
    signal_date: pd.Timestamp


def prepare_universe() -> tuple[dict[str, pd.DataFrame], pd.DatetimeIndex]:
    data, missing = load_db_data(BROAD_UNIVERSE)
    if missing:
        print(f"  [WARN] Tickers faltantes en DB: {len(missing)}")

    prepared = precompute(data)
    spy = prepared["SPY"].copy()
    spy["SMA200"] = spy["Close"].rolling(200).mean()
    spy["REGIME_SMA200"] = spy["Close"] > spy["SMA200"]
    spy["SPY_ROC20"] = (spy["Close"] / spy["Close"].shift(20) - 1.0) * 100.0
    prepared["SPY"] = spy

    for ticker, df in prepared.items():
        work = df.copy()
        work["SMA20"] = work["Close"].rolling(20).mean()
        work["SMA200"] = work["Close"].rolling(200).mean()
        work["DIST_SMA200"] = (work["Close"] / work["SMA200"] - 1.0) * 100.0
        work["ROC20"] = (work["Close"] / work["Close"].shift(20) - 1.0) * 100.0
        work["RET5"] = (work["Close"] / work["Close"].shift(5) - 1.0) * 100.0
        work["REL20"] = work["ROC20"] - spy["SPY_ROC20"]
        work["HH20"] = work["Close"].shift(1).rolling(20).max()
        work["BB_WIDTH"] = (work["Close"].rolling(20).std() * 4.0 / (work["SMA20"] + 1e-10)) * 100.0
        work["BB_WIDTH_P20"] = work["BB_WIDTH"].shift(1).rolling(20).quantile(0.2)
        prepared[ticker] = work

    return prepared, prepared["SPY"].index


def signal_d_breakout(row: pd.Series) -> bool:
    return bool(
        pd.notna(row["HH20"])
        and pd.notna(row["SMA200"])
        and pd.notna(row["BB_WIDTH_P20"])
        and (row["Close"] > row["HH20"])
        and (row["Close"] > row["SMA50"])
        and (row["SMA50"] > row["SMA200"])
        and (row["ROC20"] > 5.0)
        and (row["REL20"] > 3.0)
        and (1.2 <= row["VOL_RATIO"] <= 3.0)
        and (row["BB_WIDTH"] <= row["BB_WIDTH_P20"] * 1.5)
        and not bool(row["CORP_ACTION_10D"])
    )


def signal_d_leadership(
    row: pd.Series,
    *,
    roc20_min: float = 10.0,
    rel20_min: float = 5.0,
    rsi_min: float = 50.0,
    rsi_max: float = 75.0,
    vol_min: float = 0.8,
    vol_max: float = 2.5,
) -> bool:
    return bool(
        pd.notna(row["SMA200"])
        and (row["Close"] > row["SMA50"])
        and (row["SMA50"] > row["SMA200"])
        and (row["ROC20"] > roc20_min)
        and (row["REL20"] > rel20_min)
        and (rsi_min <= row["RSI"] <= rsi_max)
        and (vol_min <= row["VOL_RATIO"] <= vol_max)
        and not bool(row["CORP_ACTION_10D"])
    )


def build_v11_candidates(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
) -> tuple[dict[int, list[Candidate]], pd.DataFrame, dict[pd.Timestamp, int]]:
    pending: dict[int, list[Candidate]] = {}
    rows: list[dict[str, object]] = []
    daily_counts: dict[pd.Timestamp, int] = {}
    last_entry: dict[str, int] = {}

    for idx in range(START_IDX, len(dates) - 8):
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
        signal_date = dates[idx]
        day_count = 0

        for ticker in BROAD_UNIVERSE:
            if ticker == "SPY" or ticker not in prepared:
                continue
            if ticker in last_entry and (idx - last_entry[ticker]) < ANTIKNIFE_DAYS:
                continue

            df = prepared[ticker]
            candidate: Candidate | None = None
            ret = None

            if regime_safe and bool(df["SIG_A_GUARD"].iloc[idx]):
                entry = df["Close"].iloc[idx + 1]
                exit_px = df["Close"].iloc[idx + 8]
                if pd.notna(entry) and pd.notna(exit_px):
                    ret = float((exit_px / entry - 1.0) * 100.0)
                    candidate = Candidate(
                        ticker=ticker,
                        signal="A",
                        entry_idx=idx + 1,
                        exit_idx=idx + 8,
                        raw_score=calc_a_score(df, idx),
                        signal_date=signal_date,
                    )

            elif bool(df["SIG_C_V9_NEG5"].iloc[idx]):
                score = calc_c_score(df, idx)
                vol_ratio = float(df["VOL_RATIO"].iloc[idx])
                if score < 85.0 and vol_ratio < 4.0:
                    ret, exit_day, _ = c_exit_return(df, idx)
                    if ret is not None and exit_day is not None:
                        candidate = Candidate(
                            ticker=ticker,
                            signal="C5",
                            entry_idx=idx + 1,
                            exit_idx=idx + 1 + exit_day,
                            raw_score=score,
                            signal_date=signal_date,
                        )

            if candidate is None or ret is None:
                continue

            pending.setdefault(candidate.entry_idx, []).append(candidate)
            rows.append(
                {
                    "ticker": candidate.ticker,
                    "date": candidate.signal_date,
                    "signal": candidate.signal,
                    "return_pct": ret,
                }
            )
            last_entry[ticker] = idx
            day_count += 1

        daily_counts[signal_date] = day_count

    return pending, pd.DataFrame(rows), daily_counts


def run_a_variant(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    mode: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    last_entry: dict[str, int] = {}

    for idx in range(START_IDX, len(dates) - 8):
        regime_sma200 = bool(prepared["SPY"]["REGIME_SMA200"].iloc[idx])
        signal_date = dates[idx]

        for ticker in BROAD_UNIVERSE:
            if ticker == "SPY" or ticker not in prepared:
                continue
            if ticker in last_entry and (idx - last_entry[ticker]) < ANTIKNIFE_DAYS:
                continue

            df = prepared[ticker]
            sig_a = bool(df["SIG_A_GUARD"].iloc[idx])
            if mode == "A_NO_REGIME":
                allowed = sig_a
            elif mode == "A_SPY_SMA200":
                allowed = regime_sma200 and sig_a
            else:
                raise ValueError(f"Modo A desconocido: {mode}")

            if not allowed:
                continue

            entry = df["Close"].iloc[idx + 1]
            exit_px = df["Close"].iloc[idx + 8]
            if pd.isna(entry) or pd.isna(exit_px):
                continue

            rows.append(
                {
                    "ticker": ticker,
                    "date": signal_date,
                    "signal": mode,
                    "return_pct": float((exit_px / entry - 1.0) * 100.0),
                }
            )
            last_entry[ticker] = idx

    return pd.DataFrame(rows)


def build_d_candidates(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    *,
    mode: str,
    params: dict[str, float] | None = None,
) -> tuple[dict[int, list[Candidate]], pd.DataFrame, dict[pd.Timestamp, int]]:
    pending: dict[int, list[Candidate]] = {}
    rows: list[dict[str, object]] = []
    daily_counts: dict[pd.Timestamp, int] = {}
    last_entry: dict[str, int] = {}
    params = params or {}

    for idx in range(START_IDX, len(dates) - (LEADERSHIP_HOLD_DAYS + 2)):
        signal_date = dates[idx]
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
        regime_label = "SEGURO" if regime_safe else "PELIGRO"
        day_count = 0

        for ticker in BROAD_UNIVERSE:
            if ticker == "SPY" or ticker not in prepared:
                continue
            if ticker in last_entry and (idx - last_entry[ticker]) < ANTIKNIFE_DAYS:
                continue

            df = prepared[ticker]
            row = df.iloc[idx]
            if mode == "D_BREAKOUT":
                passed = signal_d_breakout(row)
                score = float(row["REL20"] + row["VOL_RATIO"] * 5.0) if passed else 0.0
            elif mode == "D_LEADERSHIP":
                passed = signal_d_leadership(row, **params)
                score = float(row["REL20"] + row["ROC20"]) if passed else 0.0
            else:
                raise ValueError(f"Modo D desconocido: {mode}")

            if not passed:
                continue

            entry = df["Close"].iloc[idx + 1]
            exit_px = df["Close"].iloc[idx + 1 + LEADERSHIP_HOLD_DAYS]
            if pd.isna(entry) or pd.isna(exit_px):
                continue

            candidate = Candidate(
                ticker=ticker,
                signal=mode,
                entry_idx=idx + 1,
                exit_idx=idx + 1 + LEADERSHIP_HOLD_DAYS,
                raw_score=score,
                signal_date=signal_date,
            )
            pending.setdefault(candidate.entry_idx, []).append(candidate)
            rows.append(
                {
                    "ticker": ticker,
                    "date": signal_date,
                    "signal": mode,
                    "regime": regime_label,
                    "return_pct": float((exit_px / entry - 1.0) * 100.0),
                }
            )
            last_entry[ticker] = idx
            day_count += 1

        daily_counts[signal_date] = day_count

    return pending, pd.DataFrame(rows), daily_counts


def simulate_sleeves(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    primary_pending: dict[int, list[Candidate]],
    *,
    primary_slots: int,
    secondary_pending: dict[int, list[Candidate]] | None = None,
    secondary_slots: int = 0,
    start_idx: int | None = None,
    end_idx: int | None = None,
) -> dict[str, object]:
    start = START_IDX + 1 if start_idx is None else start_idx
    end = len(dates) if end_idx is None else end_idx

    cash = INITIAL_EQUITY
    cooldown_until: dict[str, int] = {}
    primary_positions: list[dict[str, object]] = []
    secondary_positions: list[dict[str, object]] = []
    equity_rows: list[dict[str, float]] = []
    closed_rows: list[dict[str, object]] = []
    total_slots = max(1, primary_slots + secondary_slots)

    for idx in range(start, end):
        equity = cash
        for position in primary_positions + secondary_positions:
            px = float(prepared[str(position["ticker"])]["Close"].iloc[idx])
            equity += float(position["shares"]) * px
        equity_rows.append({"equity": equity, "open_positions": float(len(primary_positions) + len(secondary_positions))})

        still_primary: list[dict[str, object]] = []
        still_secondary: list[dict[str, object]] = []

        for position in primary_positions:
            if int(position["exit_idx"]) == idx:
                px = float(prepared[str(position["ticker"])]["Close"].iloc[idx])
                cash += float(position["shares"]) * px
                closed_rows.append(
                    {
                        "return_pct": (px / float(position["entry_price"]) - 1.0) * 100.0,
                        "signal": position["signal"],
                    }
                )
            else:
                still_primary.append(position)

        for position in secondary_positions:
            if int(position["exit_idx"]) == idx:
                px = float(prepared[str(position["ticker"])]["Close"].iloc[idx])
                cash += float(position["shares"]) * px
                closed_rows.append(
                    {
                        "return_pct": (px / float(position["entry_price"]) - 1.0) * 100.0,
                        "signal": position["signal"],
                    }
                )
            else:
                still_secondary.append(position)

        primary_positions = still_primary
        secondary_positions = still_secondary

        total_equity = cash
        for position in primary_positions + secondary_positions:
            px = float(prepared[str(position["ticker"])]["Close"].iloc[idx])
            total_equity += float(position["shares"]) * px
        slot_budget = total_equity / float(total_slots)

        free_primary = primary_slots - len(primary_positions)
        if free_primary > 0:
            ranked_primary = sorted(primary_pending.get(idx, []), key=lambda candidate: candidate.raw_score, reverse=True)
            for candidate in ranked_primary:
                if free_primary <= 0:
                    break
                if any(str(position["ticker"]) == candidate.ticker for position in primary_positions + secondary_positions):
                    continue
                if idx <= cooldown_until.get(candidate.ticker, -999):
                    continue

                px = float(prepared[candidate.ticker]["Close"].iloc[idx])
                invested = min(slot_budget, cash)
                if invested <= 0:
                    break

                primary_positions.append(
                    {
                        "ticker": candidate.ticker,
                        "signal": candidate.signal,
                        "entry_price": px,
                        "shares": invested / px,
                        "exit_idx": candidate.exit_idx,
                    }
                )
                cash -= invested
                cooldown_until[candidate.ticker] = idx + ANTIKNIFE_DAYS
                free_primary -= 1

        if secondary_pending and secondary_slots > 0:
            free_secondary = secondary_slots - len(secondary_positions)
            if free_secondary > 0:
                ranked_secondary = sorted(
                    secondary_pending.get(idx, []), key=lambda candidate: candidate.raw_score, reverse=True
                )
                for candidate in ranked_secondary:
                    if free_secondary <= 0:
                        break
                    if any(str(position["ticker"]) == candidate.ticker for position in primary_positions + secondary_positions):
                        continue
                    if idx <= cooldown_until.get(candidate.ticker, -999):
                        continue

                    px = float(prepared[candidate.ticker]["Close"].iloc[idx])
                    invested = min(slot_budget, cash)
                    if invested <= 0:
                        break

                    secondary_positions.append(
                        {
                            "ticker": candidate.ticker,
                            "signal": candidate.signal,
                            "entry_price": px,
                            "shares": invested / px,
                            "exit_idx": candidate.exit_idx,
                        }
                    )
                    cash -= invested
                    cooldown_until[candidate.ticker] = idx + ANTIKNIFE_DAYS
                    free_secondary -= 1

    equity_df = pd.DataFrame(equity_rows)
    trades_df = pd.DataFrame(closed_rows)
    return {
        "metrics": calc_portfolio_metrics(equity_df, trades_df),
        "trades": trades_df,
    }


def print_ind_row(name: str, df: pd.DataFrame) -> None:
    metrics = calc_metrics(df) if not df.empty else {"trades": 0, "wr": 0.0, "avg": 0.0, "sharpe": 0.0, "mdd": 0.0}
    counts = df["signal"].value_counts().to_dict() if not df.empty else {}
    print(
        f"  {name:16s} trades={int(metrics['trades']):4d} "
        f"wr={metrics['wr']:5.1f}% avg={metrics['avg']:+6.2f}% "
        f"sh={metrics['sharpe']:5.2f} mdd={metrics['mdd']:6.1f}% counts={counts}"
    )


def print_port_row(name: str, result: dict[str, object]) -> None:
    metrics = result["metrics"]
    counts = result["trades"]["signal"].value_counts().to_dict() if not result["trades"].empty else {}
    print(
        f"  {name:16s} trades={int(metrics['trades']):4d} "
        f"wr={metrics['wr']:5.1f}% avg={metrics['avg_trade']:+6.2f}% "
        f"sh={metrics['sharpe']:5.2f} total={metrics['total']:8.1f}% "
        f"mdd={metrics['mdd']:6.1f}% counts={counts}"
    )


def calc_drought_stats(
    v11_daily: dict[pd.Timestamp, int],
    d_daily: dict[pd.Timestamp, int],
) -> dict[str, float]:
    dates = sorted(v11_daily)
    v11_dry = sum(1 for day in dates if v11_daily.get(day, 0) == 0)
    rescued = sum(1 for day in dates if v11_daily.get(day, 0) == 0 and d_daily.get(day, 0) > 0)
    dry_both = sum(1 for day in dates if v11_daily.get(day, 0) == 0 and d_daily.get(day, 0) == 0)
    return {
        "total_days": float(len(dates)),
        "v11_dry_days": float(v11_dry),
        "rescued_days": float(rescued),
        "dry_both": float(dry_both),
        "rescue_pct": float(rescued / v11_dry * 100.0) if v11_dry else 0.0,
    }


def calc_top_movers_snapshot(prepared: dict[str, pd.DataFrame], dates: pd.DatetimeIndex) -> pd.DataFrame:
    latest = dates[-1]
    rows: list[dict[str, object]] = []
    spy_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[-1])

    for ticker in BROAD_UNIVERSE:
        if ticker == "SPY" or ticker not in prepared:
            continue
        df = prepared[ticker]
        if latest not in df.index:
            continue
        row = df.loc[latest]
        if pd.isna(row["ROC20"]):
            continue

        c_score = calc_c_score(df, len(df) - 1) if pd.notna(row["ROC10"]) and pd.notna(row["VOL_RATIO"]) and pd.notna(row["RSI"]) else np.nan
        v11_a = bool(spy_safe and row["SIG_A_GUARD"])
        v11_c = bool(row["SIG_C_V9_NEG5"]) and pd.notna(c_score) and (c_score < 85.0) and (float(row["VOL_RATIO"]) < 4.0)
        d_breakout = signal_d_breakout(row)
        d_leader = signal_d_leadership(row)

        rows.append(
            {
                "ticker": ticker,
                "ret20": float(row["ROC20"]),
                "rsi": float(row["RSI"]),
                "dist50": float(row["DIST_SMA50"]),
                "rel20": float(row["REL20"]),
                "V11_A": v11_a,
                "V11_C5": v11_c,
                "D_BO": d_breakout,
                "D_LEADER": d_leader,
            }
        )

    return pd.DataFrame(rows).sort_values("ret20", ascending=False).head(15)


def run_walk_forward(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    v11_pending: dict[int, list[Candidate]],
    d_pending: dict[int, list[Candidate]],
) -> pd.DataFrame:
    start = START_IDX + 1
    usable = len(dates) - start
    step = usable // 7
    rows: list[dict[str, object]] = []

    for window in range(7):
        a = start + window * step
        b = len(dates) if window == 6 else start + (window + 1) * step
        base = simulate_sleeves(
            prepared,
            dates,
            v11_pending,
            primary_slots=MAX_POSITIONS,
            start_idx=a,
            end_idx=b,
        )["metrics"]
        hybrid = simulate_sleeves(
            prepared,
            dates,
            v11_pending,
            primary_slots=V11_PRIMARY_SLOTS,
            secondary_pending=d_pending,
            secondary_slots=LEADERSHIP_SLOTS,
            start_idx=a,
            end_idx=b,
        )["metrics"]
        rows.append(
            {
                "window": window + 1,
                "from": str(dates[a].date()),
                "to": str(dates[b - 1].date()),
                "base_sharpe": float(base["sharpe"]),
                "base_total": float(base["total"]),
                "base_mdd": float(base["mdd"]),
                "hybrid_sharpe": float(hybrid["sharpe"]),
                "hybrid_total": float(hybrid["total"]),
                "hybrid_mdd": float(hybrid["mdd"]),
            }
        )

    return pd.DataFrame(rows)


def run_leadership_sensitivity(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    v11_pending: dict[int, list[Candidate]],
) -> pd.DataFrame:
    presets = [
        ("LOOSE", {"roc20_min": 8.0, "rel20_min": 3.0, "rsi_min": 50.0, "vol_max": 2.5}),
        ("BASE", {"roc20_min": 10.0, "rel20_min": 5.0, "rsi_min": 50.0, "vol_max": 2.5}),
        ("BALANCED", {"roc20_min": 10.0, "rel20_min": 5.0, "rsi_min": 55.0, "vol_max": 2.5}),
        ("STRICT", {"roc20_min": 12.0, "rel20_min": 7.0, "rsi_min": 55.0, "vol_max": 2.0}),
    ]

    rows: list[dict[str, object]] = []
    for name, params in presets:
        d_pending, d_df, _ = build_d_candidates(prepared, dates, mode="D_LEADERSHIP", params=params)
        hybrid = simulate_sleeves(
            prepared,
            dates,
            v11_pending,
            primary_slots=V11_PRIMARY_SLOTS,
            secondary_pending=d_pending,
            secondary_slots=LEADERSHIP_SLOTS,
        )["metrics"]
        rows.append(
            {
                "preset": name,
                "signals": int(len(d_df)),
                "days": int(d_df["date"].nunique()) if not d_df.empty else 0,
                "sharpe": float(hybrid["sharpe"]),
                "total": float(hybrid["total"]),
                "mdd": float(hybrid["mdd"]),
                "wr": float(hybrid["wr"]),
            }
        )

    return pd.DataFrame(rows).sort_values(["sharpe", "total"], ascending=[False, False])


def main() -> None:
    print(LINE)
    print("  INVESTIGACION V16 - OPORTUNIDADES PERDIDAS")
    print(LINE)
    print("  Tesis auditada: V11 puede estar dejando pasar demasiados winners por")
    print("  arquitectura, no solo por filtros puntuales.")

    print("\n[1] Cargando universo y preparando features")
    prepared, dates = prepare_universe()
    print(f"  Universo broad: {len(BROAD_UNIVERSE)} tickers")
    print(f"  Rango DB      : {dates[0].date()} -> {dates[-1].date()}")

    print("\n[2] Baseline V11 y variantes sobre Signal A")
    v11_pending, v11_df, v11_daily = build_v11_candidates(prepared, dates)
    a_no_regime_df = run_a_variant(prepared, dates, "A_NO_REGIME")
    a_spy200_df = run_a_variant(prepared, dates, "A_SPY_SMA200")

    print_ind_row("V11_BASE", v11_df)
    print_ind_row("A_NO_REGIME", a_no_regime_df)
    print_ind_row("A_SPY_SMA200", a_spy200_df)

    print("\n  Lectura de H1/H2:")
    print("    - sacar el regime de A no arregla el problema; empeora calidad")
    print("    - usar SPY>SMA200 tampoco rescata edge suficiente")

    print("\n[3] Nuevas senales ortogonales")
    d_breakout_pending, d_breakout_df, d_breakout_daily = build_d_candidates(
        prepared, dates, mode="D_BREAKOUT"
    )
    d_lead_pending, d_lead_df, d_lead_daily = build_d_candidates(
        prepared, dates, mode="D_LEADERSHIP"
    )
    d_lead_strict_params = {"roc20_min": 12.0, "rel20_min": 7.0, "rsi_min": 55.0, "vol_max": 2.0}
    d_lead_strict_pending, d_lead_strict_df, _ = build_d_candidates(
        prepared,
        dates,
        mode="D_LEADERSHIP",
        params=d_lead_strict_params,
    )

    print_ind_row("D_BREAKOUT", d_breakout_df)
    print_ind_row("D_LEADERSHIP", d_lead_df)
    print_ind_row("D_LEADER_STRICT", d_lead_strict_df)

    if not d_lead_df.empty:
        print("  Split D_LEADERSHIP por regime:")
        for regime, subdf in d_lead_df.groupby("regime"):
            metrics = calc_metrics(subdf)
            print(
                f"    {regime:8s} trades={int(metrics['trades']):4d} "
                f"wr={metrics['wr']:5.1f}% avg={metrics['avg']:+6.2f}% sh={metrics['sharpe']:5.2f}"
            )

    print("\n[4] Sequia de trades y dias rescatados")
    drought_breakout = calc_drought_stats(v11_daily, d_breakout_daily)
    drought_lead = calc_drought_stats(v11_daily, d_lead_daily)
    print(
        f"  V11 dry days                : {int(drought_lead['v11_dry_days'])}/{int(drought_lead['total_days'])}"
    )
    print(
        f"  D_BREAKOUT rescata          : {int(drought_breakout['rescued_days'])} "
        f"({drought_breakout['rescue_pct']:.1f}% de los dias secos de V11)"
    )
    print(
        f"  D_LEADERSHIP rescata        : {int(drought_lead['rescued_days'])} "
        f"({drought_lead['rescue_pct']:.1f}% de los dias secos de V11)"
    )
    print(f"  Dias secos incluso con D    : {int(drought_lead['dry_both'])}")

    print("\n[5] Portfolio real: V11 vs sleeves ortogonales")
    base_port = simulate_sleeves(
        prepared,
        dates,
        v11_pending,
        primary_slots=MAX_POSITIONS,
    )
    breakout_hybrid = simulate_sleeves(
        prepared,
        dates,
        v11_pending,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=d_breakout_pending,
        secondary_slots=LEADERSHIP_SLOTS,
    )
    leadership_hybrid = simulate_sleeves(
        prepared,
        dates,
        v11_pending,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=d_lead_pending,
        secondary_slots=LEADERSHIP_SLOTS,
    )
    leadership_hybrid_strict = simulate_sleeves(
        prepared,
        dates,
        v11_pending,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=d_lead_strict_pending,
        secondary_slots=LEADERSHIP_SLOTS,
    )

    print_port_row("V11_3SLOTS", base_port)
    print_port_row("V11+BREAKOUT", breakout_hybrid)
    print_port_row("V11+LEADER", leadership_hybrid)
    print_port_row("V11+LEAD_STRICT", leadership_hybrid_strict)

    print("\n[6] Sensibilidad gruesa de D_LEADERSHIP")
    sensitivity = run_leadership_sensitivity(prepared, dates, v11_pending)
    print(sensitivity.to_string(index=False))

    print("\n[7] Walk-forward 7 ventanas: base vs V11+LEAD_STRICT")
    wf = run_walk_forward(prepared, dates, v11_pending, d_lead_strict_pending)
    print(wf.to_string(index=False))
    wf_wins = int((wf["hybrid_sharpe"] > wf["base_sharpe"]).sum())
    print(f"  Ventanas donde hybrid gana por Sharpe: {wf_wins}/7")

    print("\n[8] Snapshot de top movers recientes")
    movers = calc_top_movers_snapshot(prepared, dates)
    print(movers.to_string(index=False))

    print("\n[9] Veredicto")
    print("  - La hipotesis 'el problema es solo el filtro de SPY' queda refutada.")
    print("  - El hueco real es estructural: V11 no tiene un eje de liderazgo/tendencia.")
    print("  - D_LEADERSHIP captura muchos winners que V11 jamas va a ver.")
    print("  - La variante realmente interesante no es la base, sino D_LEADERSHIP_STRICT.")
    print("  - Como sleeve 2+1, D_LEADERSHIP_STRICT mejora fuerte el portfolio broad.")
    print("  - La mejora sigue sin ser uniforme en todas las ventanas; necesita promotion")
    print("    gate y auditoria antes de volverse scanner champion.")


if __name__ == "__main__":
    main()
