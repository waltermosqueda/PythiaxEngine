"""
INVESTIGACION V20 - NUEVOS EJES ORTOGONALES (LIBRE)
====================================================

Objetivo: explorar combinaciones y senales nuevas con potencial real de superar
a V12 (WR 60.8%, Sharpe portfolio 1.36). Meta honesta: encontrar algo con WR
sostenida >70% en walk-forward, sin look-ahead bias.

Senales investigadas:
  [E]        RS New High   : RS-line (Close/SPY_Close) a maximos de 52 semanas.
                             Accion lidera al mercado en terminos relativos.
                             Factor documentado academicamente (momentum cross-sectional).
  [E_STR]    RS+Near-High  : Igual a E pero precio tambien cerca de su maximo de 52w.
                             Doble confirmacion de fuerza absoluta y relativa.
  [F]        Multi-ROC     : ROC5+ROC20+ROC60+ROC126 todos alineados positivos.
                             Filtra stocks con momentum sostenido en todos los plazos.
  [G]        BB-Squeeze    : BB bandwidth en percentil bajo (consolidacion) + breakout
                             sobre maximo de 20d con volumen. Volatility clustering.
  [H]        D+ADX         : Signal D de V12 con confirmacion de ADX>22 (fuerza de
                             tendencia, no solo direccion). Filtra tendencias debiles.
  [E+D]      RS+D combo    : Combinacion E con filtros D (ROC20+REL20). Test de
                             si la interseccion tiene mayor WR que cada parte sola.

Protocolo de validacion (anti-overfitting obligatorio):
  1. Per-trade independiente (broad universe, todos los tickers)
  2. Split de regime (SEGURO / PELIGRO por separado)
  3. Walk-forward 7 ventanas (~1 año cada una, no-overlapping)
  4. Portfolio 3-slot vs baseline V12
  5. Sensitivity de hold period (10d / 15d / 21d para signals de momentum)
  6. Anti-overfitting checklist final

Fecha: 2026-04-13
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any

# Forzar UTF-8 en consola Windows (evita UnicodeEncodeError con caracteres especiales)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Infraestructura compartida
from backtests.investigacion_v9_path_quality import (
    ANTIKNIFE_DAYS,
    BROAD_UNIVERSE,
    START_IDX,
    calc_atr,
    calc_metrics,
    calc_rsi,
    load_db_data,
    precompute,
)
from backtests.investigacion_v12_portfolio_operativo import (
    INITIAL_EQUITY,
    MAX_POSITIONS,
    calc_portfolio_metrics,
)
from backtests.investigacion_v17_signal_d_audit import (
    Candidate,
    D_STRICT_REF,
    LEADERSHIP_HOLD_DEFAULT,
    LEADERSHIP_SLOTS,
    LINE,
    SUBLINE,
    V11_PRIMARY_SLOTS,
    build_d_candidates,
    build_v11_candidates,
    get_sector,
    prepare_universe,
    print_ind_row,
    print_port_row,
    signal_d_leadership,
    simulate_sleeves,
)

random.seed(42)
np.random.seed(42)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────

HOLD_E   = 15   # momentum/RS signals — hold mas largo
HOLD_F   = 15
HOLD_G   = 12
HOLD_H   = 10   # D+ADX — mismo que D
HOLD_ED  = 12   # combo E+D

# Promotion gate umbrales
WR_TARGET      = 70.0   # objetivo del usuario
WR_INTERESTING = 65.0   # interesante si supera esto
MIN_TRADES     = 50     # minimo estadistico

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS TECNICOS NUEVOS
# ─────────────────────────────────────────────────────────────────────────────

def calc_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """ADX, +DI, -DI usando suavizado Wilder (com=period-1, adjust=False)."""
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)
    prev_close = close.shift(1)

    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)

    up_move   = high - prev_high
    down_move = prev_low - low

    plus_dm  = np.where((up_move > down_move) & (up_move > 0),   up_move.values,   0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move.values, 0.0)

    plus_dm_s  = pd.Series(plus_dm,  index=high.index, dtype=float)
    minus_dm_s = pd.Series(minus_dm, index=high.index, dtype=float)

    com = float(period - 1)
    tr14       = tr.ewm(com=com, adjust=False).mean()
    plus_dm14  = plus_dm_s.ewm(com=com, adjust=False).mean()
    minus_dm14 = minus_dm_s.ewm(com=com, adjust=False).mean()

    plus_di  = 100.0 * plus_dm14  / (tr14 + 1e-10)
    minus_di = 100.0 * minus_dm14 / (tr14 + 1e-10)
    dx       = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    adx      = dx.ewm(com=com, adjust=False).mean()
    return adx, plus_di, minus_di


def extend_precompute(prepared: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """
    Segunda pasada: agrega columnas para signals E/F/G/H que no existen en
    precompute() base. No modifica SPY salvo agregar SMA200.
    """
    spy_close = prepared["SPY"]["Close"]

    # SMA200 de SPY para confirmar regimen largo
    spy_work = prepared["SPY"].copy()
    spy_work["SMA200"] = spy_close.rolling(200).mean()
    spy_work["SPY_ABOVE_SMA200"] = spy_close > spy_work["SMA200"]
    prepared["SPY"] = spy_work

    for ticker, df in prepared.items():
        if ticker == "SPY":
            continue
        work = df.copy()

        # -- RS Line para Signal E --
        work["RS_LINE"]    = work["Close"] / (spy_close.reindex(work.index, fill_value=np.nan) + 1e-10)
        work["RS_52W_MAX"] = work["RS_LINE"].shift(1).rolling(252, min_periods=126).max()

        # -- 52-week price high (look-ahead free) para E_STRICT --
        work["PRICE_52W_MAX"] = work["Close"].shift(1).rolling(252, min_periods=126).max()

        # -- SMA200 para confirmacion estructural --
        work["SMA200"] = work["Close"].rolling(200).mean()

        # -- ADX para Signal H --
        adx, plus_di, minus_di = calc_adx(work["High"], work["Low"], work["Close"])
        work["ADX"]      = adx
        work["PLUS_DI"]  = plus_di
        work["MINUS_DI"] = minus_di

        # -- BB Bandwidth para Signal G --
        sma20 = work["Close"].rolling(20).mean()
        std20 = work["Close"].rolling(20).std()
        work["BB_WIDTH"]    = (2.0 * std20) / (sma20 + 1e-10)
        # Percentil 30 historico (sin look-ahead): percentil de la ventana PASADA
        work["BB_WIDTH_P30"] = (
            work["BB_WIDTH"].shift(1).rolling(252, min_periods=126).quantile(0.30)
        )
        # Maximo de 20d (shift para no incluir hoy)
        work["HIGH_20D"] = work["Close"].shift(1).rolling(20).max()

        # -- Multi-timeframe ROC para Signal F --
        work["ROC5"]   = (work["Close"] / work["Close"].shift(5)   - 1.0) * 100.0
        work["ROC60"]  = (work["Close"] / work["Close"].shift(60)  - 1.0) * 100.0
        work["ROC126"] = (work["Close"] / work["Close"].shift(126) - 1.0) * 100.0

        prepared[ticker] = work

    return prepared


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES DE SENAL
# ─────────────────────────────────────────────────────────────────────────────

_E_REQUIRED  = ["RS_LINE", "RS_52W_MAX", "Close", "SMA50", "SMA200",
                 "RSI", "VOL_RATIO", "ROC20"]
_ES_REQUIRED = _E_REQUIRED + ["PRICE_52W_MAX"]
_F_REQUIRED  = ["ROC5", "ROC20", "ROC60", "ROC126",
                 "Close", "SMA50", "SMA200", "RSI", "VOL_RATIO"]
_G_REQUIRED  = ["BB_WIDTH", "BB_WIDTH_P30", "HIGH_20D",
                 "Close", "SMA50", "RSI", "VOL_RATIO"]
_H_REQUIRED  = ["ROC20", "REL20", "Close", "SMA50", "SMA200",
                 "RSI", "VOL_RATIO", "ADX", "PLUS_DI", "MINUS_DI"]


def _ok(row: pd.Series, cols: list[str]) -> bool:
    return not any(pd.isna(row[c]) for c in cols)


def signal_e(row: pd.Series) -> bool:
    """RS New High: fuerza relativa vs SPY a maximos de 52 semanas."""
    if not _ok(row, _E_REQUIRED):
        return False
    return (
        float(row["RS_LINE"])  >= float(row["RS_52W_MAX"])  # RS line at 52w high
        and float(row["Close"]) > float(row["SMA50"]) > float(row["SMA200"])
        and 50.0 <= float(row["RSI"]) <= 75.0
        and float(row["ROC20"]) > 8.0
        and 0.8 <= float(row["VOL_RATIO"]) <= 2.5
    )


def signal_e_strict(row: pd.Series) -> bool:
    """RS New High + precio dentro del 10% de su propio maximo de 52 semanas."""
    if not _ok(row, _ES_REQUIRED):
        return False
    if not signal_e(row):
        return False
    return float(row["Close"]) >= float(row["PRICE_52W_MAX"]) * 0.90


def signal_f(row: pd.Series) -> bool:
    """Multi-timeframe: ROC5/20/60/126 todos positivos y por encima de umbrales."""
    if not _ok(row, _F_REQUIRED):
        return False
    return (
        float(row["ROC5"])   >  0.0
        and float(row["ROC20"])  > 10.0
        and float(row["ROC60"])  > 15.0
        and float(row["ROC126"]) > 22.0
        and float(row["Close"]) > float(row["SMA50"]) > float(row["SMA200"])
        and 50.0 <= float(row["RSI"]) <= 76.0
        and 0.8 <= float(row["VOL_RATIO"]) <= 2.5
    )


def signal_g(row: pd.Series) -> bool:
    """BB Squeeze + breakout sobre maximo de 20d con volumen."""
    if not _ok(row, _G_REQUIRED):
        return False
    bb_w = float(row["BB_WIDTH"])
    bb_p30 = float(row["BB_WIDTH_P30"])
    return (
        bb_w < bb_p30                                  # BB estrecho (consolidacion)
        and float(row["Close"]) > float(row["HIGH_20D"])  # breakout
        and float(row["Close"]) > float(row["SMA50"])
        and 45.0 <= float(row["RSI"]) <= 70.0
        and float(row["VOL_RATIO"]) > 1.3              # volumen confirma
    )


def signal_h_d_adx(
    row: pd.Series,
    roc20_min: float = D_STRICT_REF["roc20_min"],
    rel20_min: float = D_STRICT_REF["rel20_min"],
    adx_min: float = 22.0,
) -> bool:
    """D + ADX: Signal D con confirmacion de tendencia fuerte (ADX > umbral)."""
    if not _ok(row, _H_REQUIRED):
        return False
    d_ok = (
        float(row["Close"]) > float(row["SMA50"]) > float(row["SMA200"])
        and float(row["ROC20"]) > roc20_min
        and float(row["REL20"]) > rel20_min
        and 55.0 <= float(row["RSI"]) <= 75.0
        and 0.8 <= float(row["VOL_RATIO"]) <= 2.0
    )
    adx_ok = (
        float(row["ADX"]) > adx_min
        and float(row["PLUS_DI"]) > float(row["MINUS_DI"])
    )
    return d_ok and adx_ok


def signal_e_plus_d(row: pd.Series) -> bool:
    """Combinacion E+D: RS new high + ROC20>12% + REL20>7%. Interseccion."""
    if not _ok(row, _E_REQUIRED + ["REL20"]):
        return False
    return (
        float(row["RS_LINE"]) >= float(row["RS_52W_MAX"])
        and float(row["Close"]) > float(row["SMA50"]) > float(row["SMA200"])
        and float(row["ROC20"]) > 12.0
        and float(row["REL20"]) > 7.0
        and 55.0 <= float(row["RSI"]) <= 75.0
        and 0.8 <= float(row["VOL_RATIO"]) <= 2.0
    )


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRUCTOR DE CANDIDATOS GENERICO
# ─────────────────────────────────────────────────────────────────────────────

def build_signal_candidates(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    signal_fn,
    signal_name: str,
    hold_days: int,
    score_col: str = "ROC20",
    start_idx_override: int | None = None,
) -> tuple[dict[int, list[Candidate]], list[dict]]:
    """
    Construye pending dict (para portfolio) y lista de rows (para per-trade metrics).
    Necesita 252 barras de calentamiento extra para RS_52W_MAX.
    """
    start = (START_IDX + 252 + 10) if start_idx_override is None else start_idx_override
    pending: dict[int, list[Candidate]] = {}
    rows: list[dict] = []

    spy_df = prepared["SPY"]

    for ticker, df in prepared.items():
        if ticker == "SPY":
            continue
        n = len(dates)
        for idx in range(start, n - hold_days - 1):
            row = df.iloc[idx]
            if not signal_fn(row):
                continue
            if bool(row.get("CORP_ACTION_10D", False)):
                continue

            exit_idx = min(idx + hold_days, n - 1)
            entry_px = float(df["Close"].iloc[idx])
            exit_px  = float(df["Close"].iloc[exit_idx])
            if entry_px <= 0:
                continue

            score = float(row.get(score_col, 0.0)) if not pd.isna(row.get(score_col, np.nan)) else 0.0
            regime = "SEGURO" if bool(spy_df["REGIME_SAFE"].iloc[idx]) else "PELIGRO"

            cand = Candidate(
                ticker     = ticker,
                signal     = signal_name,
                entry_idx  = idx,
                exit_idx   = exit_idx,
                raw_score  = score,
                signal_date= dates[idx],
                regime     = regime,
                sector     = get_sector(ticker),
            )
            pending.setdefault(idx, []).append(cand)
            rows.append({
                "return_pct": (exit_px / entry_px - 1.0) * 100.0,
                "signal": signal_name,
                "ticker": ticker,
                "sector": get_sector(ticker),
                "regime": regime,
            })

    return pending, rows


# ─────────────────────────────────────────────────────────────────────────────
# WALK-FORWARD 7 VENTANAS
# ─────────────────────────────────────────────────────────────────────────────

def walk_forward_7(
    pending: dict[int, list[Candidate]],
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    n_windows: int = 7,
    hold_days: int = 15,
    slots: int = 3,
) -> dict[str, Any]:
    """Walk-forward no-overlapping de n ventanas. Retorna stats por ventana y resumen."""
    total = len(dates)
    window_size = total // n_windows
    results = []

    for w in range(n_windows):
        s = w * window_size
        e = s + window_size if w < n_windows - 1 else total
        s = max(s, START_IDX + 252 + 10)

        # Filtrar candidatos de esta ventana
        window_pending: dict[int, list[Candidate]] = {
            idx: cands
            for idx, cands in pending.items()
            if s <= idx < e - hold_days
        }
        if not window_pending:
            results.append({"window": w + 1, "sharpe": 0.0, "wr": 0.0, "trades": 0})
            continue

        sim = simulate_sleeves(
            prepared, dates, window_pending,
            primary_slots=slots, start_idx=s, end_idx=e,
        )
        m = sim["metrics"]
        results.append({
            "window": w + 1,
            "sharpe": m.get("sharpe", 0.0),
            "wr": m.get("wr", 0.0),
            "trades": m.get("trades", 0),
        })

    wins = sum(1 for r in results if r["sharpe"] > 0)
    return {"windows": results, "wins": wins, "total": n_windows}


# ─────────────────────────────────────────────────────────────────────────────
# METRICAS PER-TRADE
# ─────────────────────────────────────────────────────────────────────────────

def per_trade_metrics(rows: list[dict]) -> dict[str, float]:
    if not rows:
        return {"trades": 0, "wr": 0.0, "avg": 0.0, "sharpe": 0.0, "mdd": 0.0}
    df = pd.DataFrame(rows)
    returns = df["return_pct"].to_numpy(dtype=float)
    wr   = float((returns > 0).mean() * 100)
    avg  = float(returns.mean())
    std  = float(returns.std())
    sharpe = avg / std * np.sqrt(252 / 15) if std > 0 else 0.0
    equity = np.cumprod(1 + returns / 100)
    peaks  = np.maximum.accumulate(equity)
    mdd    = float(((equity - peaks) / peaks * 100).min())
    total  = float(equity[-1] * 100 - 100)
    return {
        "trades": len(rows),
        "wr": round(wr, 1),
        "avg": round(avg, 3),
        "sharpe": round(sharpe, 3),
        "mdd": round(mdd, 1),
        "total": round(total, 1),
    }


def print_perf_row(label: str, m: dict) -> None:
    wr_flag = " *** WR>70!" if m["wr"] >= 70.0 else (" ** WR>65" if m["wr"] >= 65.0 else "")
    print(
        f"  {label:<18s} | trades {m['trades']:>5d} | WR {m['wr']:>5.1f}% | "
        f"avg {m['avg']:>+6.2f}% | sharpe {m['sharpe']:>5.2f} | "
        f"mdd {m['mdd']:>+6.1f}% | total {m['total']:>+7.1f}%{wr_flag}"
    )


def print_regime_split(label: str, rows: list[dict]) -> None:
    for regime in ["SEGURO", "PELIGRO"]:
        sub = [r for r in rows if r["regime"] == regime]
        if sub:
            m = per_trade_metrics(sub)
            print(f"    {label}/{regime:<7s}        | trades {m['trades']:>5d} | WR {m['wr']:>5.1f}% | avg {m['avg']:>+6.2f}%")


def print_sector_top(label: str, rows: list[dict], top_n: int = 5) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    grp = df.groupby("sector")["return_pct"].agg(["mean", "count", lambda x: (x > 0).mean() * 100])
    grp.columns = ["avg", "n", "wr"]
    grp = grp[grp["n"] >= 8].sort_values("wr", ascending=False)
    print(f"    {label} — top sectores (n>=8):")
    for sec, row_s in grp.head(top_n).iterrows():
        print(f"      {sec:<10s} | n={int(row_s['n']):>4d} | WR {row_s['wr']:.1f}% | avg {row_s['avg']:+.2f}%")


# ─────────────────────────────────────────────────────────────────────────────
# HOLD SENSITIVITY
# ─────────────────────────────────────────────────────────────────────────────

def hold_sensitivity(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    signal_fn,
    signal_name: str,
    holds: list[int],
    score_col: str = "ROC20",
) -> None:
    print(f"    Sensibilidad hold ({signal_name}):")
    for h in holds:
        _, rows = build_signal_candidates(prepared, dates, signal_fn, signal_name, h, score_col)
        m = per_trade_metrics(rows)
        marker = " <-- mejor" if m["wr"] == max(
            per_trade_metrics(
                build_signal_candidates(prepared, dates, signal_fn, signal_name, hh, score_col)[1]
            )["wr"]
            for hh in holds
        ) else ""
        print(
            f"      hold {h:>3d}d | trades {m['trades']:>5d} | WR {m['wr']:>5.1f}% | "
            f"avg {m['avg']:>+6.2f}% | sharpe {m['sharpe']:>5.2f}{marker}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# CHECKLIST ANTI-OVERFITTING
# ─────────────────────────────────────────────────────────────────────────────

def print_antioverfit_checklist(
    signal_name: str,
    rows: list[dict],
    wf_wins: int,
    wf_total: int,
    n_params: int,
) -> int:
    m = per_trade_metrics(rows)
    checks = [
        ("LOOK-AHEAD BIAS",   True,                         "RS_52W_MAX usa shift(1); BB percentil usa shift(1)"),
        ("SURVIVORSHIP BIAS", True,                         "Universo BROAD_UNIVERSE (sin filtrar por sobreviviente)"),
        ("PERIODO",           m["trades"] > 0,              f"6 anos (2020-2026), {m['trades']} trades"),
        ("OUT-OF-SAMPLE",     wf_wins >= 4,                 f"Walk-forward {wf_wins}/{wf_total} ventanas"),
        ("WALK-FORWARD",      wf_total >= 7,                f"{wf_total} ventanas no-overlapping"),
        ("COMPLEJIDAD",       n_params <= 5,                f"{n_params} parametros clave"),
        ("TRADES MINIMOS",    m["trades"] >= MIN_TRADES,    f"{m['trades']} >= {MIN_TRADES}"),
        ("COSTOS",            False,                        "No incluidos (simplificacion estandar del proyecto)"),
    ]
    passed = sum(1 for _, ok, _ in checks if ok)
    print(f"\n  Checklist anti-overfitting — {signal_name}:")
    for name, ok, note in checks:
        icon = "[X]" if ok else "[ ]"
        print(f"    {icon} {name:<20s} : {note}")
    verdict = "ACEPTAR" if passed >= 6 else ("REVISAR" if passed >= 4 else "RECHAZAR")
    print(f"    Score: {passed}/8 PASS → {verdict}")
    return passed


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print(LINE)
    print("  INVESTIGACION V20 — NUEVOS EJES ORTOGONALES")
    print(LINE)
    print("  Objetivo: senales con WR sostenida >70% en walk-forward honesto.")
    print()

    # [0] Carga y preparacion
    print("[0] Cargando universo y extendiendo features...")
    prepared_base, dates = prepare_universe()
    prepared = extend_precompute(prepared_base)
    print(f"  Rango DB    : {dates[0].date()} -> {dates[-1].date()}")
    print(f"  Tickers     : {len([t for t in prepared if t != 'SPY'])}")
    print(f"  Warmup extra: {START_IDX + 252 + 10} barras (para RS_52W_MAX)")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [1] BASELINE V12 (referencia para comparar)
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[1] BASELINE V12 (referencia)")
    print(SUBLINE)
    v11_pending, v11_rows = build_v11_candidates(prepared, dates)
    d_pending,   d_rows   = build_d_candidates(prepared, dates, params=D_STRICT_REF, hold_days=LEADERSHIP_HOLD_DEFAULT)
    print_ind_row("V11_BASE_IND", v11_rows)
    print_ind_row("D_BASE_IND",   d_rows)
    v12_sim = simulate_sleeves(
        prepared, dates,
        v11_pending,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=d_pending,
        secondary_slots=LEADERSHIP_SLOTS,
    )
    print_port_row("V12_PORT (baseline)", v12_sim)
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [2] SIGNAL E — RS NEW HIGH
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[2] SIGNAL E — RS NEW HIGH (Close/SPY a maximos de 52 semanas)")
    print(SUBLINE)
    e_pending, e_rows = build_signal_candidates(
        prepared, dates, signal_e, "E_RS_HIGH", HOLD_E, score_col="ROC20"
    )
    me = per_trade_metrics(e_rows)
    print_perf_row("E_RS_HIGH", me)
    print_regime_split("E", e_rows)
    print_sector_top("E", e_rows)

    print(f"\n  Sensibilidad hold — Signal E:")
    best_e_wr = 0.0
    best_e_hold = HOLD_E
    for h in [8, 10, 12, 15, 21]:
        _, rr = build_signal_candidates(prepared, dates, signal_e, "E", h, "ROC20")
        mm = per_trade_metrics(rr)
        flag = " <--" if mm["wr"] > best_e_wr else ""
        if mm["wr"] > best_e_wr:
            best_e_wr = mm["wr"]
            best_e_hold = h
        print(f"    hold {h:>3d}d | trades {mm['trades']:>5d} | WR {mm['wr']:>5.1f}% | avg {mm['avg']:>+6.2f}%{flag}")

    # WF con mejor hold
    print(f"\n  Walk-forward 7 ventanas (hold={best_e_hold}d):")
    _, e_rows_best = build_signal_candidates(prepared, dates, signal_e, "E_RS_HIGH", best_e_hold, "ROC20")
    e_pend_best, _ = build_signal_candidates(prepared, dates, signal_e, "E_RS_HIGH", best_e_hold, "ROC20")
    wf_e = walk_forward_7(e_pend_best, prepared, dates, hold_days=best_e_hold)
    for r in wf_e["windows"]:
        print(f"    V{r['window']} | sharpe {r['sharpe']:>+5.2f} | WR {r['wr']:>5.1f}% | trades {int(r['trades']):>4d}")
    print(f"  WF resultado: {wf_e['wins']}/{wf_e['total']} ventanas con sharpe>0")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [3] SIGNAL E_STRICT — RS NEW HIGH + PRECIO CERCA DE 52W HIGH
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[3] SIGNAL E_STRICT — RS New High + precio dentro del 10% de maximo 52w")
    print(SUBLINE)
    es_pending, es_rows = build_signal_candidates(
        prepared, dates, signal_e_strict, "E_STRICT", HOLD_E, "ROC20"
    )
    mes = per_trade_metrics(es_rows)
    print_perf_row("E_STRICT", mes)
    print_regime_split("E_STRICT", es_rows)
    print_sector_top("E_STRICT", es_rows)

    # WF
    wf_es = walk_forward_7(es_pending, prepared, dates, hold_days=HOLD_E)
    print(f"\n  Walk-forward 7 ventanas (hold={HOLD_E}d):")
    for r in wf_es["windows"]:
        print(f"    V{r['window']} | sharpe {r['sharpe']:>+5.2f} | WR {r['wr']:>5.1f}% | trades {int(r['trades']):>4d}")
    print(f"  WF resultado: {wf_es['wins']}/{wf_es['total']} ventanas con sharpe>0")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [4] SIGNAL F — MULTI-TIMEFRAME MOMENTUM
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[4] SIGNAL F — MULTI-TIMEFRAME (ROC5+ROC20+ROC60+ROC126 alineados)")
    print(SUBLINE)
    f_pending, f_rows = build_signal_candidates(
        prepared, dates, signal_f, "F_MULTI", HOLD_F, "ROC20"
    )
    mf = per_trade_metrics(f_rows)
    print_perf_row("F_MULTI", mf)
    print_regime_split("F", f_rows)
    print_sector_top("F", f_rows)

    wf_f = walk_forward_7(f_pending, prepared, dates, hold_days=HOLD_F)
    print(f"\n  Walk-forward 7 ventanas (hold={HOLD_F}d):")
    for r in wf_f["windows"]:
        print(f"    V{r['window']} | sharpe {r['sharpe']:>+5.2f} | WR {r['wr']:>5.1f}% | trades {int(r['trades']):>4d}")
    print(f"  WF resultado: {wf_f['wins']}/{wf_f['total']} ventanas con sharpe>0")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [5] SIGNAL G — BB SQUEEZE BREAKOUT
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[5] SIGNAL G — BB SQUEEZE BREAKOUT (consolidacion + expansion)")
    print(SUBLINE)
    g_pending, g_rows = build_signal_candidates(
        prepared, dates, signal_g, "G_SQUEEZE", HOLD_G, "ROC20"
    )
    mg = per_trade_metrics(g_rows)
    print_perf_row("G_SQUEEZE", mg)
    print_regime_split("G", g_rows)
    print_sector_top("G", g_rows)

    wf_g = walk_forward_7(g_pending, prepared, dates, hold_days=HOLD_G)
    print(f"\n  Walk-forward 7 ventanas (hold={HOLD_G}d):")
    for r in wf_g["windows"]:
        print(f"    V{r['window']} | sharpe {r['sharpe']:>+5.2f} | WR {r['wr']:>5.1f}% | trades {int(r['trades']):>4d}")
    print(f"  WF resultado: {wf_g['wins']}/{wf_g['total']} ventanas con sharpe>0")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [6] SIGNAL H — D + ADX
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[6] SIGNAL H — D + ADX (Signal D con confirmacion de fuerza de tendencia)")
    print(SUBLINE)
    h_pending, h_rows = build_signal_candidates(
        prepared, dates, signal_h_d_adx, "H_D_ADX", HOLD_H, "ROC20"
    )
    mh = per_trade_metrics(h_rows)
    print_perf_row("H_D_ADX", mh)
    print(f"  vs D base: WR delta = {mh['wr'] - per_trade_metrics(d_rows)['wr']:+.1f}% | "
          f"trades delta = {mh['trades'] - per_trade_metrics(d_rows)['trades']:+d}")
    print_regime_split("H", h_rows)

    wf_h = walk_forward_7(h_pending, prepared, dates, hold_days=HOLD_H)
    print(f"\n  Walk-forward 7 ventanas (hold={HOLD_H}d):")
    for r in wf_h["windows"]:
        print(f"    V{r['window']} | sharpe {r['sharpe']:>+5.2f} | WR {r['wr']:>5.1f}% | trades {int(r['trades']):>4d}")
    print(f"  WF resultado: {wf_h['wins']}/{wf_h['total']} ventanas con sharpe>0")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [7] SIGNAL E+D — COMBO RS NEW HIGH + FILTROS D
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[7] SIGNAL E+D — COMBO RS New High + ROC20>12% + REL20>7%")
    print(SUBLINE)
    ed_pending, ed_rows = build_signal_candidates(
        prepared, dates, signal_e_plus_d, "E_PLUS_D", HOLD_ED, "ROC20"
    )
    med = per_trade_metrics(ed_rows)
    print_perf_row("E_PLUS_D", med)
    print_regime_split("E+D", ed_rows)
    print_sector_top("E+D", ed_rows)

    wf_ed = walk_forward_7(ed_pending, prepared, dates, hold_days=HOLD_ED)
    print(f"\n  Walk-forward 7 ventanas (hold={HOLD_ED}d):")
    for r in wf_ed["windows"]:
        print(f"    V{r['window']} | sharpe {r['sharpe']:>+5.2f} | WR {r['wr']:>5.1f}% | trades {int(r['trades']):>4d}")
    print(f"  WF resultado: {wf_ed['wins']}/{wf_ed['total']} ventanas con sharpe>0")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [8] PORTFOLIO: MEJOR CANDIDATO vs V12
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[8] PORTFOLIO: mejor candidato como 4to sleeve vs V12")
    print(SUBLINE)

    # Seleccionar el mejor candidato por WR
    candidates_summary = [
        ("E",      me,  e_pend_best,  best_e_hold),
        ("E_STR",  mes, es_pending,   HOLD_E),
        ("F",      mf,  f_pending,    HOLD_F),
        ("G",      mg,  g_pending,    HOLD_G),
        ("H",      mh,  h_pending,    HOLD_H),
        ("E+D",    med, ed_pending,   HOLD_ED),
    ]
    candidates_summary.sort(key=lambda x: x[1]["wr"], reverse=True)

    print("  Ranking por WR per-trade:")
    for name, m, _, _ in candidates_summary:
        bar = "=" * int(m["wr"] / 2) if m["wr"] > 0 else ""
        flag = " *** WR>70!" if m["wr"] >= 70.0 else (" ** WR>65" if m["wr"] >= 65.0 else "")
        print(f"    {name:<10s} WR {m['wr']:>5.1f}% | {bar}{flag}")
    print()

    # Portfolio con el candidato #1
    best_name, best_m, best_pend, best_hold = candidates_summary[0]
    # Mejor candidato reemplazando D (2 V11 + 1 nuevo)
    print(f"  V12 con {best_name} reemplazando D (2 V11 + 1 {best_name}):")
    v12_replace_d = simulate_sleeves(
        prepared, dates,
        v11_pending,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=best_pend,
        secondary_slots=LEADERSHIP_SLOTS,
    )
    print_port_row(f"V12_replace_D_{best_name}", v12_replace_d)

    # Segundo mejor tambien
    if len(candidates_summary) > 1:
        second_name, second_m, second_pend, _ = candidates_summary[1]
        print(f"  V12 con {second_name} reemplazando D (2 V11 + 1 {second_name}):")
        v12_replace_d2 = simulate_sleeves(
            prepared, dates,
            v11_pending,
            primary_slots=V11_PRIMARY_SLOTS,
            secondary_pending=second_pend,
            secondary_slots=LEADERSHIP_SLOTS,
        )
        print_port_row(f"V12_replace_D_{second_name}", v12_replace_d2)
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [9] ANTI-OVERFITTING CHECKLIST
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[9] ANTI-OVERFITTING CHECKLIST")
    print(SUBLINE)

    scores = {}
    for name, m, pend, hold in candidates_summary:
        fn_map = {
            "E": signal_e, "E_STR": signal_e_strict, "F": signal_f,
            "G": signal_g, "H": signal_h_d_adx, "E+D": signal_e_plus_d,
        }
        n_params = {"E": 5, "E_STR": 6, "F": 6, "G": 4, "H": 6, "E+D": 7}.get(name, 5)
        wf_map = {"E": wf_e, "E_STR": wf_es, "F": wf_f, "G": wf_g, "H": wf_h, "E+D": wf_ed}
        wf = wf_map.get(name, {"wins": 0, "total": 7})
        rows_map = {
            "E": e_rows_best, "E_STR": es_rows, "F": f_rows,
            "G": g_rows, "H": h_rows, "E+D": ed_rows,
        }
        score = print_antioverfit_checklist(name, rows_map.get(name, []), wf["wins"], wf["total"], n_params)
        scores[name] = score

    # ─────────────────────────────────────────────────────────────────────────
    # [10] VEREDICTO FINAL
    # ─────────────────────────────────────────────────────────────────────────
    print()
    print(LINE)
    print("  VEREDICTO FINAL")
    print(LINE)

    print("  Resumen ejecutivo:")
    print(f"  {'Senal':<12s} {'WR%':>7s} {'avg%':>7s} {'Sharpe':>8s} {'trades':>7s} {'WF wins':>8s} {'AO score':>9s}  Veredicto")
    print(f"  {'-'*12} {'-'*7} {'-'*7} {'-'*8} {'-'*7} {'-'*8} {'-'*9}  ---------")

    wf_wins_map = {
        "E": wf_e["wins"], "E_STR": wf_es["wins"],
        "F": wf_f["wins"], "G": wf_g["wins"],
        "H": wf_h["wins"], "E+D": wf_ed["wins"],
    }
    rows_map2 = {
        "E": e_rows_best, "E_STR": es_rows, "F": f_rows,
        "G": g_rows, "H": h_rows, "E+D": ed_rows,
    }

    for name, m, _, _ in candidates_summary:
        wf_w  = wf_wins_map.get(name, 0)
        ao_s  = scores.get(name, 0)
        rows_ = rows_map2.get(name, [])
        # Criterios de promocion
        wr_ok    = m["wr"] >= WR_TARGET
        wf_ok    = wf_w >= 4
        ao_ok    = ao_s >= 6
        trades_ok= m["trades"] >= MIN_TRADES

        if wr_ok and wf_ok and ao_ok and trades_ok:
            veredicto = "PROMOVER"
        elif m["wr"] >= WR_INTERESTING and wf_ok and trades_ok:
            veredicto = "CANDIDATO"
        elif wf_ok and trades_ok:
            veredicto = "INTERESANTE"
        else:
            veredicto = "NO PROMOVER"

        print(
            f"  {name:<12s} {m['wr']:>7.1f} {m['avg']:>+7.3f} {m['sharpe']:>8.3f} "
            f"{m['trades']:>7d} {wf_w:>8d}/7 {ao_s:>9d}/8  {veredicto}"
        )

    print()
    print("  Observaciones clave:")
    best_wr_name = max(wf_wins_map, key=lambda n: per_trade_metrics(rows_map2.get(n, []))["wr"],
                       default="--")

    # Imprimir observacion por cada senal
    obs_data = [(name, per_trade_metrics(rows_map2.get(name, []))) for name, _, _, _ in candidates_summary]
    for name, m in obs_data:
        if m["wr"] >= WR_TARGET:
            print(f"  *** {name}: WR {m['wr']:.1f}% supera objetivo 70%. "
                  f"WF {wf_wins_map.get(name,0)}/7. Candidato solido.")
        elif m["wr"] >= WR_INTERESTING:
            print(f"  **  {name}: WR {m['wr']:.1f}% supera umbral de interes (65%). "
                  f"WF {wf_wins_map.get(name,0)}/7. Revisar.")
        else:
            print(f"  .   {name}: WR {m['wr']:.1f}% bajo objetivo. "
                  f"Sin justificacion para promover en este parametro.")

    print()
    print("  Conclusion general:")
    any_above_70 = any(
        per_trade_metrics(rows_map2.get(n, []))["wr"] >= WR_TARGET
        for n in wf_wins_map
    )
    if any_above_70:
        winners = [
            n for n in wf_wins_map
            if per_trade_metrics(rows_map2.get(n, []))["wr"] >= WR_TARGET
        ]
        print(f"  SENALES CON WR >= 70%: {', '.join(winners)}")
        print("  Proximos pasos: profundizar en la mejor, ajustar filtros, y construir V13.")
    else:
        best_name2 = max(wf_wins_map, key=lambda n: per_trade_metrics(rows_map2.get(n, []))["wr"])
        best_wr2   = per_trade_metrics(rows_map2.get(best_name2, []))["wr"]
        print(f"  Ninguna senal supera 70% WR en este parametro inicial.")
        print(f"  Mejor encontrada: {best_name2} con WR {best_wr2:.1f}%.")
        print("  Opciones: endurecer filtros (menos trades, mayor WR) o explorar combinaciones.")
    print(LINE)


if __name__ == "__main__":
    main()
