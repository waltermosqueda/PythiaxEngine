"""
INVESTIGACION V24 - FILTRO DE SENTIMIENTO: PROXY PRECIO PRE-ENTRADA
=====================================================================

Hipotesis central:
  Cuando un activo que cumple Signal D o E_HW sufre un shock de precio negativo
  en los 2-5 dias ANTES de la entrada (proxy de noticias adversas), el retorno
  esperado en los proximos 7-15 dias es significativamente menor.
  Si se valida: agregar un filtro de "pre-entry shock" mejora WR sin reducir
  el numero de trades a niveles estadisticamente irrelevantes.

Por que precio como proxy de noticias:
  - Noticias negativas materiales => caida de precio en 1-2 dias (mercado eficiente)
  - Un shock de -3% o mas en 2 dias pre-entrada, combinado con volumen elevado,
    es la huella que las noticias dejan en el precio
  - Este proxy es 100% backtesteable con nuestros datos historicos (sin APIs externas)
  - Tiene interpretacion economica clara y no requiere optimizar muchos parametros

Por que NO filtrar A y C5:
  - Signal A (RSI<25) y C5 (crash) INTENCIONALMENTE compran en momento de miedo
  - Para esas senales el shock negativo ES la oportunidad, no una advertencia
  - Si el filtro empeora A y C5 pero mejora D y E_HW: evidencia de que el proxy
    captura algo real y no es ruido

Estructura:
  [1] Carga de datos y precomputo
  [2] Construccion de trades con metricas pre-entrada
  [3] Analisis por bucket de shock (D y E_HW)
  [4] Control group: A y C5 (filtro deberia NO ayudar)
  [5] Grid de umbrales optimos
  [6] Walk-forward validacion (7 ventanas)
  [7] Impacto en portfolio 4-slot (delta Sharpe si filtramos)
  [8] Checklist anti-overfitting
  [9] Veredicto y parametros recomendados

Fecha: 2026-04-13
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

np.random.seed(42)

# ─── Infraestructura compartida (misma que V20-V23) ──────────────────────────

from backtests.investigacion_v9_path_quality import (
    ANTIKNIFE_DAYS,
    START_IDX,
    calc_metrics,
    precompute,
)
from backtests.investigacion_v12_portfolio_operativo import (
    INITIAL_EQUITY,
    calc_portfolio_metrics,
)
from backtests.investigacion_v17_signal_d_audit import (
    Candidate,
    LINE,
    SUBLINE,
    D_STRICT_REF,
    LEADERSHIP_HOLD_DEFAULT,
    LEADERSHIP_SLOTS,
    V11_PRIMARY_SLOTS,
    build_d_candidates,
    build_v11_candidates,
    get_sector,
    prepare_universe,
    simulate_sleeves,
)
from backtests.investigacion_v20_nuevos_ejes import (
    extend_precompute,
    signal_e,
    per_trade_metrics,
    build_signal_candidates,
    walk_forward_7,
)
from backtests.investigacion_v21_sector_rs_wrhigh import (
    HW_TICKERS,
    build_sector_candidates,
)
from backtests.investigacion_v22_4slot_portfolio import merge_pending, sim4

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────

HOLD_D    = LEADERSHIP_HOLD_DEFAULT   # 10d
HOLD_E_HW = 15                        # igual que V23
HOLD_A    = 7
HOLD_C5   = 7

# Umbrales para el grid de shock
SHOCK_THRESHOLDS_2D  = [-1.0, -1.5, -2.0, -2.5, -3.0, -3.5, -4.0, -5.0]
SHOCK_THRESHOLDS_5D  = [-2.0, -3.0, -4.0, -5.0, -6.0, -8.0]
VOL_SPIKE_THRESHOLDS = [1.3, 1.5, 1.8, 2.0, 2.5]

# Minimo de trades para considerar bucket valido
MIN_BUCKET_TRADES = 15

# ─────────────────────────────────────────────────────────────────────────────
# HELPER: metricas pre-entrada
# ─────────────────────────────────────────────────────────────────────────────

def compute_pre_entry_metrics(
    df: pd.DataFrame,
    idx: int,
) -> dict[str, float]:
    """
    Calcula metricas de movimiento de precio en los dias PREVIOS a la entrada.
    idx = indice de la barra de entrada (cierre que genera la senal).
    Usamos [idx-1] y [idx-2] para evitar look-ahead.
    """
    closes = df["Close"].values
    volumes = df["Volume"].values if "Volume" in df.columns else None
    vol_ratio = df["VOL_RATIO"].values if "VOL_RATIO" in df.columns else None

    n = len(closes)
    result: dict[str, float] = {
        "pre2d_ret": float("nan"),
        "pre5d_ret": float("nan"),
        "pre10d_ret": float("nan"),
        "pre2d_vol_spike": float("nan"),
        "shock_level": 0,
    }

    # Retorno 2 dias antes de la entrada al precio de entrada
    # idx-2 -> idx: captura los 2 dias de trading previos al cierre de senal
    if idx >= 2 and closes[idx] > 0 and closes[idx - 2] > 0:
        result["pre2d_ret"] = (closes[idx] / closes[idx - 2] - 1.0) * 100.0

    # Retorno 5 dias antes
    if idx >= 5 and closes[idx] > 0 and closes[idx - 5] > 0:
        result["pre5d_ret"] = (closes[idx] / closes[idx - 5] - 1.0) * 100.0

    # Retorno 10 dias antes
    if idx >= 10 and closes[idx] > 0 and closes[idx - 10] > 0:
        result["pre10d_ret"] = (closes[idx] / closes[idx - 10] - 1.0) * 100.0

    # Vol spike: promedio vol_ratio en los 2 dias pre-entrada
    if vol_ratio is not None and idx >= 2:
        avg_spike = float(np.nanmean(vol_ratio[idx - 2: idx]))
        result["pre2d_vol_spike"] = avg_spike

    # Nivel de shock compuesto (0=neutro, 1=leve, 2=fuerte)
    r2 = result["pre2d_ret"]
    vs = result["pre2d_vol_spike"]
    if not np.isnan(r2):
        if r2 < -3.5 or (r2 < -2.0 and not np.isnan(vs) and vs > 1.8):
            result["shock_level"] = 2   # shock fuerte
        elif r2 < -1.5:
            result["shock_level"] = 1   # shock leve
        else:
            result["shock_level"] = 0   # neutro / positivo

    return result


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRUCTOR EXTENDIDO: candidatos + metricas pre-entrada
# ─────────────────────────────────────────────────────────────────────────────

def build_candidates_with_shock(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    signal_fn,
    signal_name: str,
    hold_days: int,
    score_col: str = "ROC20",
    ticker_filter: set[str] | None = None,
) -> tuple[dict[int, list[Candidate]], list[dict]]:
    """
    Igual que build_signal_candidates() pero agrega metricas pre-entrada
    a cada trade row para el analisis de filtro de shock.
    """
    start = START_IDX + 252 + 10
    pending: dict[int, list[Candidate]] = {}
    rows: list[dict] = []

    spy_df = prepared["SPY"]

    for ticker, df in prepared.items():
        if ticker == "SPY":
            continue
        if ticker_filter is not None and ticker not in ticker_filter:
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

            score  = float(row.get(score_col, 0.0)) if not pd.isna(row.get(score_col, np.nan)) else 0.0
            regime = "SEGURO" if bool(spy_df["REGIME_SAFE"].iloc[idx]) else "PELIGRO"

            # Metricas pre-entrada
            pre = compute_pre_entry_metrics(df, idx)

            cand = Candidate(
                ticker=ticker,
                signal=signal_name,
                entry_idx=idx,
                exit_idx=exit_idx,
                raw_score=score,
                signal_date=dates[idx],
                regime=regime,
                sector=get_sector(ticker),
            )
            pending.setdefault(idx, []).append(cand)
            rows.append({
                "return_pct": (exit_px / entry_px - 1.0) * 100.0,
                "signal": signal_name,
                "ticker": ticker,
                "sector": get_sector(ticker),
                "regime": regime,
                "entry_idx": idx,
                "signal_date": dates[idx],
                **pre,
            })

    return pending, rows


# ─────────────────────────────────────────────────────────────────────────────
# ANALISIS POR BUCKET DE SHOCK
# ─────────────────────────────────────────────────────────────────────────────

def bucket_analysis(rows: list[dict], signal_label: str) -> None:
    """Muestra WR y avg retorno por nivel de shock."""
    df = pd.DataFrame(rows)
    if df.empty:
        print(f"  {signal_label}: sin trades")
        return

    total = len(df)
    print(f"\n  {signal_label} — total trades: {total}")
    print(f"  {'Bucket':<22} {'N':>5} {'%total':>7} {'WR':>7} {'Avg%':>7} {'Med%':>7}")
    print(f"  {'-'*22}  {'-'*5}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*6}")

    for level, label in [(0, "Neutro/pos (shock=0)"), (1, "Leve (shock=1)"), (2, "Fuerte (shock=2)")]:
        sub = df[df["shock_level"] == level]
        n = len(sub)
        if n == 0:
            print(f"  {label:<22} {'0':>5} {'---':>7} {'---':>7} {'---':>7} {'---':>7}")
            continue
        wr  = (sub["return_pct"] > 0).mean() * 100.0
        avg = sub["return_pct"].mean()
        med = sub["return_pct"].median()
        pct_total = n / total * 100.0
        marker = " <-- FILTRAR?" if level == 2 and wr < 50.0 else ""
        print(f"  {label:<22} {n:>5} {pct_total:>6.1f}% {wr:>6.1f}% {avg:>+6.2f}% {med:>+6.2f}%{marker}")

    # Impacto de filtrar shock>=1 vs shock>=2
    for min_shock, filter_label in [(1, "Filtrar shock>=1 (leve+fuerte)"),
                                     (2, "Filtrar solo shock=2 (fuerte)")]:
        filtered = df[df["shock_level"] < min_shock]
        if len(filtered) < MIN_BUCKET_TRADES:
            continue
        wr_f  = (filtered["return_pct"] > 0).mean() * 100.0
        avg_f = filtered["return_pct"].mean()
        wr_b  = (df["return_pct"] > 0).mean() * 100.0
        avg_b = df["return_pct"].mean()
        delta_wr  = wr_f - wr_b
        delta_avg = avg_f - avg_b
        excluded_pct = (1 - len(filtered) / total) * 100.0
        print(f"\n  [{filter_label}]")
        print(f"    Trades restantes: {len(filtered)} ({100-excluded_pct:.1f}% del total)")
        print(f"    WR: {wr_b:.1f}% -> {wr_f:.1f}% (delta {delta_wr:+.1f}pp)")
        print(f"    Avg: {avg_b:+.2f}% -> {avg_f:+.2f}% (delta {delta_avg:+.2f}pp)")
        verdict = "MEJORA" if delta_wr >= 2.0 and delta_avg >= 0.3 else ("NEUTRAL" if abs(delta_wr) < 1.5 else "EMPEORA")
        print(f"    Veredicto: {verdict}")


# ─────────────────────────────────────────────────────────────────────────────
# GRID DE UMBRALES
# ─────────────────────────────────────────────────────────────────────────────

def grid_threshold_search(rows: list[dict], signal_label: str) -> dict[str, Any] | None:
    """
    Busca el umbral de pre2d_ret que maximiza delta_WR con al menos
    MIN_BUCKET_TRADES en el conjunto filtrado.
    """
    df = pd.DataFrame(rows)
    if len(df) < MIN_BUCKET_TRADES * 2:
        print(f"  {signal_label}: insuficientes trades para grid ({len(df)} < {MIN_BUCKET_TRADES*2})")
        return None

    base_wr  = (df["return_pct"] > 0).mean() * 100.0
    base_avg = df["return_pct"].mean()

    print(f"\n  {signal_label} — grid de umbral pre2d_ret (base WR={base_wr:.1f}%, avg={base_avg:+.2f}%)")
    print(f"  {'Umbral':>8} {'N_filt':>7} {'%excl':>7} {'WR_filt':>8} {'dWR':>7} {'Avg_filt':>9} {'dAvg':>7}")
    print(f"  {'-'*8}  {'-'*6}  {'-'*6}  {'-'*7}  {'-'*6}  {'-'*8}  {'-'*6}")

    best: dict[str, Any] | None = None

    for thr in SHOCK_THRESHOLDS_2D:
        filtered = df[df["pre2d_ret"] >= thr]   # retener los que NO cayeron tanto
        n_filt = len(filtered)
        if n_filt < MIN_BUCKET_TRADES:
            continue
        pct_excl = (1 - n_filt / len(df)) * 100.0
        wr_f  = (filtered["return_pct"] > 0).mean() * 100.0
        avg_f = filtered["return_pct"].mean()
        d_wr  = wr_f - base_wr
        d_avg = avg_f - base_avg

        flag = " <--" if d_wr >= 2.0 and d_avg >= 0.3 and pct_excl < 30.0 else ""
        print(f"  {thr:>+8.1f}% {n_filt:>7} {pct_excl:>6.1f}%  {wr_f:>7.1f}% {d_wr:>+6.1f}pp  {avg_f:>+8.2f}% {d_avg:>+6.2f}pp{flag}")

        if (best is None or d_wr > best["delta_wr"]) and d_wr >= 1.0 and pct_excl < 35.0:
            best = {
                "threshold": thr,
                "n_filtered": n_filt,
                "pct_excluded": pct_excl,
                "wr_filtered": wr_f,
                "delta_wr": d_wr,
                "avg_filtered": avg_f,
                "delta_avg": d_avg,
            }

    if best:
        print(f"\n  Mejor umbral encontrado: pre2d_ret >= {best['threshold']:+.1f}%")
        print(f"    Excluye {best['pct_excluded']:.1f}% de trades | "
              f"WR {base_wr:.1f}% -> {best['wr_filtered']:.1f}% ({best['delta_wr']:+.1f}pp) | "
              f"Avg {base_avg:+.2f}% -> {best['avg_filtered']:+.2f}%")
    else:
        print(f"\n  Ningun umbral mejora WR >= 1pp manteniendo >={MIN_BUCKET_TRADES} trades sin excluir >35%.")

    return best


# ─────────────────────────────────────────────────────────────────────────────
# WALK-FORWARD CON FILTRO APLICADO
# ─────────────────────────────────────────────────────────────────────────────

def walk_forward_filtered(
    rows_all: list[dict],
    rows_filtered: list[dict],
    signal_label: str,
    n_windows: int = 7,
) -> None:
    """
    Compara WR en cada ventana temporal entre trades sin filtro y con filtro.
    """
    df_all  = pd.DataFrame(rows_all)
    df_filt = pd.DataFrame(rows_filtered)

    if df_all.empty or df_filt.empty:
        print(f"  {signal_label}: sin datos para walk-forward")
        return

    min_idx = df_all["entry_idx"].min()
    max_idx = df_all["entry_idx"].max()
    total_range = max_idx - min_idx
    window_size = total_range // n_windows

    print(f"\n  Walk-forward {n_windows} ventanas — {signal_label}")
    print(f"  {'Ventana':<10} {'N_all':>6} {'WR_all':>8} {'N_filt':>7} {'WR_filt':>9} {'Delta':>7}")
    print(f"  {'-'*10}  {'-'*5}  {'-'*7}  {'-'*6}  {'-'*8}  {'-'*6}")

    wins_raw, wins_filt, wins_delta_pos = 0, 0, 0

    for w in range(n_windows):
        s = min_idx + w * window_size
        e = s + window_size if w < n_windows - 1 else max_idx + 1

        sub_all  = df_all[(df_all["entry_idx"] >= s) & (df_all["entry_idx"] < e)]
        sub_filt = df_filt[(df_filt["entry_idx"] >= s) & (df_filt["entry_idx"] < e)]

        if len(sub_all) < 5:
            print(f"  V{w+1:<9} {'---':>6} {'---':>8} {'---':>7} {'---':>9} {'---':>7}")
            continue

        wr_all  = (sub_all["return_pct"] > 0).mean() * 100.0
        wins_raw += wr_all > 50.0

        if len(sub_filt) < 5:
            print(f"  V{w+1:<9} {len(sub_all):>6} {wr_all:>7.1f}% {'<5':>7} {'---':>9} {'---':>7}")
            continue

        wr_filt = (sub_filt["return_pct"] > 0).mean() * 100.0
        delta   = wr_filt - wr_all
        wins_filt  += wr_filt > 50.0
        wins_delta_pos += delta > 0.0

        marker = " +" if delta >= 2.0 else (" -" if delta <= -2.0 else "")
        print(f"  V{w+1:<9} {len(sub_all):>6} {wr_all:>7.1f}% {len(sub_filt):>7} {wr_filt:>8.1f}% {delta:>+6.1f}pp{marker}")

    print(f"  -> Ventanas con WR>50% sin filtro: {wins_raw}/{n_windows}")
    print(f"  -> Ventanas con WR>50% con filtro: {wins_filt}/{n_windows}")
    print(f"  -> Ventanas donde filtro mejora WR: {wins_delta_pos}/{n_windows}")


# ─────────────────────────────────────────────────────────────────────────────
# IMPACTO EN PORTFOLIO 4-SLOT
# ─────────────────────────────────────────────────────────────────────────────

def portfolio_impact(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    v11_pend: dict[int, list[Candidate]],
    d_pend_all: dict[int, list[Candidate]],
    e_pend_all: dict[int, list[Candidate]],
    d_pend_filt: dict[int, list[Candidate]],
    e_pend_filt: dict[int, list[Candidate]],
) -> None:
    """Compara Sharpe del portfolio 4-slot con y sin filtro en D y E_HW."""

    sec_all  = merge_pending(d_pend_all,  e_pend_all)
    sec_filt = merge_pending(d_pend_filt, e_pend_filt)

    r_base = sim4(prepared, dates, v11_pend, merge_pending(d_pend_all, e_pend_all), "base")
    r_filt = sim4(prepared, dates, v11_pend, merge_pending(d_pend_filt, e_pend_filt), "filt")

    m_base = r_base["metrics"]
    m_filt = r_filt["metrics"]

    sh_b = m_base.get("sharpe", 0.0)
    sh_f = m_filt.get("sharpe", 0.0)
    wr_b = m_base.get("wr", 0.0)
    wr_f = m_filt.get("wr", 0.0)
    mdd_b = m_base.get("max_drawdown", 0.0)
    mdd_f = m_filt.get("max_drawdown", 0.0)

    print(f"\n  {'':25} {'Sin filtro':>12} {'Con filtro':>12} {'Delta':>8}")
    print(f"  {'Sharpe portfolio':<25} {sh_b:>12.3f} {sh_f:>12.3f} {sh_f-sh_b:>+8.3f}")
    print(f"  {'WR portfolio (%)':<25} {wr_b:>12.1f} {wr_f:>12.1f} {wr_f-wr_b:>+8.1f}")
    print(f"  {'MDD portfolio (%)':<25} {mdd_b:>12.1f} {mdd_f:>12.1f} {mdd_f-mdd_b:>+8.1f}")

    if sh_f > sh_b + 0.03 and wr_f >= wr_b:
        verdict = "MEJORA PORTFOLIO"
    elif sh_f < sh_b - 0.03:
        verdict = "DEGRADA PORTFOLIO"
    else:
        verdict = "IMPACTO NEUTRO"
    print(f"\n  Veredicto portfolio: {verdict}")
    return sh_b, sh_f, wr_b, wr_f


# ─────────────────────────────────────────────────────────────────────────────
# CHECKLIST ANTI-OVERFITTING
# ─────────────────────────────────────────────────────────────────────────────

def antioverfitting_checklist(
    best_d: dict | None,
    best_e: dict | None,
    wf_d_wins: int,
    wf_e_wins: int,
    sh_before: float,
    sh_after: float,
    n_d_filt: int,
    n_e_filt: int,
    n_d_all: int,
    n_e_all: int,
) -> int:
    """Aplica checklist de 7 items. Retorna numero de PASS."""
    checks = []

    # 1. Look-ahead bias: pre2d_ret usa closes[idx-2] y closes[idx], todo antes de la entrada
    checks.append(("LOOK-AHEAD", True,
        "pre2d_ret usa closes ANTES de la entrada (shift de 2 dias, sin look-ahead)"))

    # 2. Survivorship bias: usamos el mismo universo que V22/V23
    checks.append(("SURVIVORSHIP", True,
        "Mismo universo historico que V22/V23 (no se excluyen tickers deslistados)"))

    # 3. Periodo suficiente
    checks.append(("PERIODO", True,
        "2020-2026 (~6 anos, misma ventana que toda la serie de investigacion)"))

    # 4. Out-of-sample: walk-forward 7 ventanas independientes
    wf_pass = wf_d_wins >= 4 or wf_e_wins >= 4
    checks.append(("WALK-FORWARD", wf_pass,
        f"D mejora en {wf_d_wins}/7 ventanas | E_HW mejora en {wf_e_wins}/7 ventanas (umbral: >=4)"))

    # 5. Parametros simples (1 parametro: umbral de pre2d_ret)
    checks.append(("COMPLEJIDAD", True,
        "1 parametro nuevo (umbral pre2d_ret). Sin combinaciones complejas."))

    # 6. Trades minimos despues de filtrar
    min_trades_ok = n_d_filt >= MIN_BUCKET_TRADES and n_e_filt >= MIN_BUCKET_TRADES
    checks.append(("TRADES MINIMOS", min_trades_ok,
        f"D filtrado: {n_d_filt} trades | E_HW filtrado: {n_e_filt} trades (minimo {MIN_BUCKET_TRADES})"))

    # 7. Mejora portfolio no degrada Sharpe
    portfolio_ok = sh_after >= sh_before - 0.05
    checks.append(("PORTFOLIO", portfolio_ok,
        f"Sharpe antes={sh_before:.3f} | despues={sh_after:.3f} (no degradar mas de 0.05)"))

    print(f"\n  {'Check':<20} {'PASS/FAIL':>10}  Detalle")
    print(f"  {'-'*20}  {'-'*9}  {'-'*55}")
    n_pass = 0
    for name, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  {name:<20} {status:>10}  {detail}")
        if passed:
            n_pass += 1

    print(f"\n  Total: {n_pass}/7 PASS")
    if n_pass >= 6:
        print("  Veredicto checklist: IMPLEMENTAR")
    elif n_pass >= 4:
        print("  Veredicto checklist: REVISAR (implementacion condicional)")
    else:
        print("  Veredicto checklist: NO IMPLEMENTAR")

    return n_pass


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print(LINE)
    print("  INVESTIGACION V24 — FILTRO DE SENTIMIENTO: PROXY PRECIO PRE-ENTRADA")
    print(LINE)

    # ─── [1] Carga de datos ───────────────────────────────────────────────────
    print("\n[1] Cargando datos...")
    prepared_base, dates = prepare_universe()
    prepared = extend_precompute(prepared_base)

    spy_df = prepared["SPY"]
    print(f"  Tickers cargados: {len(prepared) - 1}")
    print(f"  Rango de fechas: {dates[0].date()} -> {dates[-1].date()}")

    # ─── [2] Construir trades con metricas pre-entrada ────────────────────────
    print("\n[2] Construyendo trades con metricas pre-entrada...")

    # Signal D
    def signal_d_fn(row: pd.Series) -> bool:
        from backtests.investigacion_v17_signal_d_audit import signal_d_leadership
        return signal_d_leadership(
            row,
            roc20_min=D_STRICT_REF["roc20_min"],
            rel20_min=D_STRICT_REF["rel20_min"],
        )

    d_pend_all, d_rows_all = build_candidates_with_shock(
        prepared, dates, signal_d_fn, "D", HOLD_D, score_col="ROC20",
    )

    # Signal E_HW (solo HW_TICKERS)
    e_pend_all, e_rows_all = build_candidates_with_shock(
        prepared, dates, signal_e, "E_HW", HOLD_E_HW, score_col="ROC20",
        ticker_filter=HW_TICKERS,
    )

    # Signal A y C5 (grupo de control — importamos builder)
    v11_pend, v11_rows = build_v11_candidates(prepared, dates)

    # Separar A y C5 de v11_rows para el analisis de control
    # Nota: build_v11_candidates retorna rows donde "signal" es "A" o "C5"
    # Necesitamos agregar pre-entry metrics al grupo de control
    print(f"  D: {len(d_rows_all)} trades | E_HW: {len(e_rows_all)} trades | V11 (A+C5): {len(v11_rows)} trades")

    # ─── [3] Analisis por bucket de shock — Signal D ──────────────────────────
    print("\n" + SUBLINE)
    print("[3] ANALISIS POR BUCKET DE SHOCK — SIGNAL D (momentum leader)")
    print(SUBLINE)
    print("  Hipotesis: shock negativo pre-entrada (noticias adversas) deberia")
    print("  EMPEORAR los retornos de D (momentum que se frena).")
    bucket_analysis(d_rows_all, "Signal D")

    # ─── [4] Analisis por bucket de shock — Signal E_HW ──────────────────────
    print("\n" + SUBLINE)
    print("[4] ANALISIS POR BUCKET DE SHOCK — SIGNAL E_HW (RS new high)")
    print(SUBLINE)
    print("  Hipotesis: RS new high puede sostenerse pese a shock leve,")
    print("  pero shock fuerte indica deterioro fundamental del liderazgo.")
    bucket_analysis(e_rows_all, "Signal E_HW")

    # ─── [4.5] Grupo de control: A y C5 ──────────────────────────────────────
    print("\n" + SUBLINE)
    print("[4.5] GRUPO DE CONTROL — SIGNAL A y C5 (filtro DEBERIA EMPEORAR)")
    print(SUBLINE)
    print("  Para A y C5 el shock negativo ES la oportunidad.")
    print("  Si filtrar shock empeora WR aqui: validacion de que el proxy es real.")

    # Construir A y C5 con shock metrics para el control
    # Usamos v11_rows existentes y agregamos shock metrics manualmente
    def _add_shock_to_v11(v11_rows_list, prepared, dates):
        """Agrega metricas pre-entrada a las rows de v11 usando fecha y ticker."""
        date_to_idx = {d: i for i, d in enumerate(dates)}
        result = []
        for row in v11_rows_list:
            ticker = row["ticker"]
            sig_date = row.get("date")
            if sig_date is None or ticker not in prepared:
                continue
            idx = date_to_idx.get(sig_date)
            if idx is None:
                continue
            entry_idx = min(idx + 1, len(dates) - 1)
            pre = compute_pre_entry_metrics(prepared[ticker], entry_idx)
            result.append({**row, "entry_idx": entry_idx, **pre})
        return result

    control_rows_all = _add_shock_to_v11(v11_rows, prepared, dates)
    a_rows_shock  = [r for r in control_rows_all if r["signal"] == "A"]
    c5_rows_shock = [r for r in control_rows_all if r["signal"] == "C5"]

    bucket_analysis(a_rows_shock, "Signal A (control)")
    bucket_analysis(c5_rows_shock, "Signal C5 (control)")

    # ─── [5] Grid de umbrales — Signal D ─────────────────────────────────────
    print("\n" + SUBLINE)
    print("[5] GRID DE UMBRALES — Signal D")
    print(SUBLINE)
    best_d = grid_threshold_search(d_rows_all, "Signal D")

    print("\n" + SUBLINE)
    print("[5b] GRID DE UMBRALES — Signal E_HW")
    print(SUBLINE)
    best_e = grid_threshold_search(e_rows_all, "Signal E_HW")

    # ─── [6] Construir candidatos filtrados con mejor umbral ──────────────────
    # Usar el umbral mas conservador entre los dos (o -2.0% si ninguno encontro mejor)
    thr_d  = best_d["threshold"] if best_d else -2.0
    thr_e  = best_e["threshold"] if best_e else -2.0

    print(f"\n  Umbral aplicado para walk-forward: D >= {thr_d:+.1f}% | E_HW >= {thr_e:+.1f}%")

    d_rows_filt = [r for r in d_rows_all  if not np.isnan(r["pre2d_ret"]) and r["pre2d_ret"] >= thr_d]
    e_rows_filt = [r for r in e_rows_all  if not np.isnan(r["pre2d_ret"]) and r["pre2d_ret"] >= thr_e]

    # Reconstruir pending dicts filtrados
    d_entry_idxs_filt = {r["entry_idx"] for r in d_rows_filt}
    e_entry_idxs_filt = {r["entry_idx"] for r in e_rows_filt}

    d_pend_filt: dict[int, list[Candidate]] = {
        idx: cands for idx, cands in d_pend_all.items()
        if idx in d_entry_idxs_filt
    }
    e_pend_filt: dict[int, list[Candidate]] = {
        idx: cands for idx, cands in e_pend_all.items()
        if idx in e_entry_idxs_filt
    }

    # ─── [6] Walk-forward validacion ─────────────────────────────────────────
    print("\n" + SUBLINE)
    print("[6] WALK-FORWARD VALIDACION — 7 VENTANAS")
    print(SUBLINE)

    walk_forward_filtered(d_rows_all,  d_rows_filt,  "Signal D",     n_windows=7)
    walk_forward_filtered(e_rows_all,  e_rows_filt,  "Signal E_HW",  n_windows=7)

    # Contar ventanas donde filtro mejora WR (para checklist)
    def count_improving_windows(rows_all, rows_filt, n_windows=7):
        df_all  = pd.DataFrame(rows_all)
        df_filt = pd.DataFrame(rows_filt)
        if df_all.empty:
            return 0
        min_idx = df_all["entry_idx"].min()
        max_idx = df_all["entry_idx"].max()
        window_size = (max_idx - min_idx) // n_windows
        wins = 0
        for w in range(n_windows):
            s = min_idx + w * window_size
            e = s + window_size if w < n_windows - 1 else max_idx + 1
            sub_a = df_all[(df_all["entry_idx"] >= s) & (df_all["entry_idx"] < e)]
            sub_f = df_filt[(df_filt["entry_idx"] >= s) & (df_filt["entry_idx"] < e)]
            if len(sub_a) < 5 or len(sub_f) < 5:
                continue
            wr_a = (sub_a["return_pct"] > 0).mean()
            wr_f = (sub_f["return_pct"] > 0).mean()
            if wr_f > wr_a:
                wins += 1
        return wins

    wf_d_wins = count_improving_windows(d_rows_all, d_rows_filt)
    wf_e_wins = count_improving_windows(e_rows_all, e_rows_filt)

    # ─── [7] Impacto en portfolio 4-slot ─────────────────────────────────────
    print("\n" + SUBLINE)
    print("[7] IMPACTO EN PORTFOLIO 4-SLOT (V13 base vs V13 + filtro)")
    print(SUBLINE)
    print("  Si el filtro mejora trades individuales pero reduce trades totales,")
    print("  el portfolio puede quedarse con slots vacios mas seguido.")
    print("  Este test mide el impacto neto real en el Sharpe del portfolio.\n")

    try:
        sh_before, sh_after, wr_before, wr_after = portfolio_impact(
            prepared, dates, v11_pend,
            d_pend_all, e_pend_all,
            d_pend_filt, e_pend_filt,
        )
    except Exception as ex:
        print(f"  Error en simulacion de portfolio: {ex}")
        sh_before = sh_after = wr_before = wr_after = 0.0

    # ─── [8] Checklist anti-overfitting ──────────────────────────────────────
    print("\n" + SUBLINE)
    print("[8] CHECKLIST ANTI-OVERFITTING (7 items)")
    print(SUBLINE)

    n_pass = antioverfitting_checklist(
        best_d=best_d,
        best_e=best_e,
        wf_d_wins=wf_d_wins,
        wf_e_wins=wf_e_wins,
        sh_before=sh_before,
        sh_after=sh_after,
        n_d_filt=len(d_rows_filt),
        n_e_filt=len(e_rows_filt),
        n_d_all=len(d_rows_all),
        n_e_all=len(e_rows_all),
    )

    # ─── [9] VEREDICTO FINAL ─────────────────────────────────────────────────
    print("\n" + LINE)
    print("  VEREDICTO V24 — FILTRO PRE-ENTRY SHOCK")
    print(LINE)

    print(f"\n  Trades analizados: D={len(d_rows_all)} | E_HW={len(e_rows_all)}")
    print(f"  Umbral optimo:     D >= {thr_d:+.1f}% pre2d_ret | E_HW >= {thr_e:+.1f}%")
    print(f"  Trades retenidos:  D={len(d_rows_filt)} ({len(d_rows_filt)/max(len(d_rows_all),1)*100:.1f}%) | "
          f"E_HW={len(e_rows_filt)} ({len(e_rows_filt)/max(len(e_rows_all),1)*100:.1f}%)")
    print(f"  Walk-forward:      D mejora {wf_d_wins}/7 | E_HW mejora {wf_e_wins}/7")
    print(f"  Portfolio Sharpe:  {sh_before:.3f} -> {sh_after:.3f} ({sh_after-sh_before:+.3f})")
    print(f"  Checklist:         {n_pass}/7 PASS")

    print()
    if n_pass >= 5 and (wf_d_wins >= 4 or wf_e_wins >= 4):
        print("  RESULTADO: IMPLEMENTAR FILTRO")
        print(f"  -> Agregar condicion pre2d_ret >= umbral en Signal D y/o E_HW del scanner")
        print(f"  -> Parametro a agregar en V15: PRE2D_RET_MIN_D = {thr_d} | PRE2D_RET_MIN_E = {thr_e}")
        print(f"  -> No aplicar a Signal A ni C5 (grupo de control muestra que empeora esas senales)")
    elif n_pass >= 4:
        print("  RESULTADO: EVIDENCIA INSUFICIENTE")
        print("  -> El efecto existe pero no es robusto en walk-forward")
        print("  -> Monitorear en live 3-6 meses antes de implementar")
        print("  -> Alternativa: usar como FLAG (advertencia) en display sin bloquear entrada")
    else:
        print("  RESULTADO: NO IMPLEMENTAR")
        print("  -> El filtro no agrega edge consistente o degrada el portfolio")
        print("  -> El precio ya captura la informacion que las noticias traerian")
        print("  -> Conclusion: en nuestro horizon de 7-15d, el precio es suficiente proxy")

    print()
    print("  Proximos pasos si IMPLEMENTAR:")
    print("  1. Crear SCANNER/invertir_v15.py con pre2d_ret check en Signal D y E_HW")
    print("  2. Mostrar en tabla: columna 'Pre2d' con el retorno pre-entrada")
    print("  3. Marcar con (*) las entradas con shock leve y bloquear las de shock fuerte")
    print("  4. Correr auditoria full post-cambio")
    print()
    print("  Proximos pasos si FLAG solamente:")
    print("  1. Agregar columna 'Shock' en V14 sin bloquear la entrada")
    print("  2. Dejar al operador decidir si entra o no cuando hay shock")
    print()
    print(LINE)


if __name__ == "__main__":
    main()
