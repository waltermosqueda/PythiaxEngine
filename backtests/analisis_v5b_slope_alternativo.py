"""
BACKTEST: Filtro slope alternativo — excluir SOLO zona muerta (0 a +3)
=======================================================================
Hipótesis: la zona muerta (rsi_slope entre 0 y +3) es el problema real.
  - slope < 0   → RSI aún cayendo       → WR 68%, Sharpe bueno
  - slope 0-+3  → giro débil / ambiguo  → WR 36%, avg -2.91% ← ZONA MUERTA
  - slope ≥ +3  → giro fuerte confirmado → WR 75%, avg +4.82%

Filtro alternativo: slope < 0 OR slope >= +3
  (conservar giros fuertes, eliminar solo la ambigüedad)

Estrategias comparadas:
  1. V4 baseline
  2. V4 + slope < 0               (V5 original — win 4/7 WF)
  3. V4 + slope < 0 OR slope >= 3 (V5b — excluye solo zona muerta)
  4. V4 + slope < 0 OR slope >= 5 (V5c — umbral más alto para giro fuerte)
  5. V4 + slope != "zona muerta" con distintos umbrales

Luego: walk-forward de la mejor variante.

Universo: 258 tickers (titan.db completo)
Período: Sep 2024 – Mar 2026
Holding: 10 días
RSI: Wilder's smoothing ewm(com=13) — VERIFICADO
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os
import pandas as pd
import numpy as np
import warnings

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from titan_system.core.database import TitanDB
from titan_system.core.data_loader import ACTIVOS, CONTEXT_TICKERS

# ── Config ────────────────────────────────────────────────────────────────────
PERIOD_START = '2024-09-01'
PERIOD_END   = '2026-03-28'
HOLD_DAYS    = 10
MIN_TRADES   = 3
ALL_TICKERS  = list(set(ACTIVOS + CONTEXT_TICKERS))

# ── Indicadores (RSI WILDER VERIFICADO) ──────────────────────────────────────

def calc_rsi_wilder(close, period=14):
    """Wilder's RSI — ewm(com=period-1, adjust=False). VERIFICADO."""
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period-1, adjust=False).mean()
    return 100 - 100 / (1 + gain / (loss + 1e-10))

def calc_macd_hist(close, fast=12, slow=26, signal=9):
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    macd  = ema_f - ema_s
    return macd - macd.ewm(span=signal, adjust=False).mean()

def calc_atr(high, low, close, period=14):
    tr = pd.concat([
        (high - low),
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_score(rsi, dist_sma50, macd_acc_n, vol_ratio):
    return (max(0, min(40, (30 - rsi) / 30 * 40)) +
            max(0, min(30, (abs(dist_sma50) - 5) / 15 * 30)) +
            max(0, min(20, macd_acc_n * 5)) +
            max(0, min(10, (1.5 - vol_ratio) / 1.5 * 10)))

# ── Recopilar todos los trades V4 con slope ───────────────────────────────────

def collect_all_trades(all_data, spy_df):
    """
    Genera TODOS los trades V4 con su rsi_slope.
    El filtrado por slope se aplica después para comparar variantes.
    """
    trades = []
    recent = {}

    dates = sorted(d for d in spy_df.index
                   if PERIOD_START <= str(d)[:10] <= PERIOD_END)

    for date in dates:
        spy_sl = spy_df[spy_df.index <= date]
        if len(spy_sl) < 55:
            continue
        spy_c = spy_sl['close']
        if not (spy_c.iloc[-1] > spy_c.rolling(50).mean().iloc[-1] and
                spy_c.pct_change().rolling(20).std().iloc[-1] * 100 < 1.0):
            continue

        for ticker, df in all_data.items():
            if ticker in CONTEXT_TICKERS:
                continue
            df_sl = df[df.index <= date]
            if len(df_sl) < 80:
                continue
            if ticker in recent and (date - recent[ticker]).days < 7:
                continue

            c = df_sl['close']; h = df_sl['high']
            l = df_sl['low'];   v = df_sl['volume']

            rsi_s  = calc_rsi_wilder(c)
            rsi14  = rsi_s.iloc[-1]
            rsi_sl = rsi_s.iloc[-1] - rsi_s.iloc[-4] if len(rsi_s) >= 4 else 0.0
            mh     = calc_macd_hist(c)
            mh_c   = mh.iloc[-1]; mh_p = mh.iloc[-2] if len(mh) > 1 else 0.0
            sma50  = c.rolling(50).mean().iloc[-1]
            atr14  = calc_atr(h, l, c).iloc[-1]
            v20    = v.rolling(20).mean().iloc[-1]
            vr     = v.iloc[-1] / (v20 + 1e-10)
            price  = c.iloc[-1]
            dsma   = (price / sma50 - 1) * 100
            acc_n  = (mh_c - mh_p) / (atr14 * 0.01 + 1e-6)
            score  = calc_score(rsi14, dsma, acc_n, vr)

            if any(np.isnan(x) for x in [rsi14, dsma, score, rsi_sl]):
                continue

            # Filtros base V4 (sin ningún filtro de slope)
            if not (rsi14 < 25 and dsma < -10 and score > 30 and
                    vr < 1.5 and mh_c > mh_p):
                continue

            future = df[df.index > date].head(HOLD_DAYS)
            if len(future) < HOLD_DAYS:
                continue

            ret = future['close'].iloc[-1] / price - 1
            trades.append({
                'date': date, 'ticker': ticker,
                'ret': ret, 'rsi': rsi14,
                'rsi_slope': rsi_sl, 'score': score,
                'dsma': dsma, 'vr': vr
            })
            recent[ticker] = date

    return pd.DataFrame(trades)


def metrics(df, label):
    if df is None or len(df) < MIN_TRADES:
        print(f"  {label:<45}  <{MIN_TRADES} trades")
        return None
    r    = df['ret'].values
    wins = (r > 0).sum()
    wr   = wins / len(r) * 100
    avg  = r.mean() * 100
    daily = r / HOLD_DAYS
    sh   = (daily.mean() / (daily.std() + 1e-10)) * np.sqrt(252)
    tot  = ((1 + r).prod() - 1) * 100
    mdd  = min(0, min((np.cumprod(1 + r) / np.maximum.accumulate(np.cumprod(1 + r)) - 1))) * 100
    print(f"  {label:<45}  TR:{len(r):>3}  WR:{wr:>5.1f}%  "
          f"Avg:{avg:>+5.2f}%  Sh:{sh:>6.2f}  MDD:{mdd:>+6.1f}%  Tot:{tot:>+6.1f}%")
    return {'trades': len(r), 'wr': wr, 'avg': avg, 'sharpe': sh, 'mdd': mdd, 'total': tot}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 90)
    print("  BACKTEST: Filtro slope alternativo — excluir SOLO zona muerta (slope 0 a +3)")
    print("  Universo: 258 tickers  |  Sep 2024 – Mar 2026  |  Hold 10d")
    print("  RSI: Wilder ewm(com=13) — VERIFICADO")
    print("=" * 90)

    print("\n  Cargando datos...")
    with TitanDB() as db:
        all_data = {}
        for t in ALL_TICKERS:
            df = db.get_prices(t, '2024-06-01', '2026-03-28')
            if df is not None and len(df) > 80:
                all_data[t] = df.sort_index()
    spy_df = all_data.get('SPY')
    print(f"  {len(all_data)} tickers cargados\n")

    print("  Generando trades V4 completos (sin filtro slope)...")
    all_trades = collect_all_trades(all_data, spy_df)
    print(f"  {len(all_trades)} trades V4 base recopilados\n")

    if len(all_trades) == 0:
        print("  ERROR: Sin trades. Verificar datos.")
        return

    sl = all_trades['rsi_slope']

    # ── Definir variantes ─────────────────────────────────────────────────────
    print("=" * 90)
    print("  DISTRIBUCIÓN DE TRADES POR BUCKET DE SLOPE")
    print("=" * 90)

    buckets = [
        ("slope < -5   (caída fuerte)",       sl < -5),
        ("slope -5 a -2 (caída moderada)",    (sl >= -5) & (sl < -2)),
        ("slope -2 a 0 (caída leve)",         (sl >= -2) & (sl < 0)),
        ("slope 0 a +2 (zona muerta leve)",   (sl >= 0)  & (sl < 2)),
        ("slope +2 a +3 (zona muerta med)",   (sl >= 2)  & (sl < 3)),
        ("slope +3 a +5 (giro moderado)",     (sl >= 3)  & (sl < 5)),
        ("slope +5 a +8 (giro fuerte)",       (sl >= 5)  & (sl < 8)),
        ("slope >= +8  (giro muy fuerte)",    sl >= 8),
    ]

    print(f"\n  {'Bucket':<40}  {'N':>4}  {'WR':>6}  {'Avg':>7}  {'Sharpe':>7}")
    print(f"  {'-'*72}")
    for label, mask in buckets:
        sub = all_trades[mask]
        if len(sub) < 2:
            print(f"  {label:<40}  {len(sub):>4}  {'—':>6}  {'—':>7}  {'—':>7}")
            continue
        r    = sub['ret'].values
        wr   = (r > 0).mean() * 100
        avg  = r.mean() * 100
        daily = r / HOLD_DAYS
        sh   = (daily.mean() / (daily.std() + 1e-10)) * np.sqrt(252)
        print(f"  {label:<40}  {len(sub):>4}  {wr:>5.1f}%  {avg:>+6.2f}%  {sh:>7.2f}")

    # ── Comparativa de variantes ──────────────────────────────────────────────
    print()
    print("=" * 90)
    print("  COMPARATIVA DE ESTRATEGIAS")
    print("=" * 90)
    print()

    variants = [
        ("V4 baseline (sin filtro slope)",        all_trades),
        ("V4 + slope < 0",                        all_trades[sl < 0]),
        ("V4 + slope < 0 OR slope >= +3",         all_trades[(sl < 0) | (sl >= 3)]),
        ("V4 + slope < 0 OR slope >= +5",         all_trades[(sl < 0) | (sl >= 5)]),
        ("V4 + slope < 0 OR slope >= +8",         all_trades[(sl < 0) | (sl >= 8)]),
        ("V4 + slope < -2 OR slope >= +3",        all_trades[(sl < -2) | (sl >= 3)]),
        ("V4 + slope != zona muerta (0 a +2)",    all_trades[(sl < 0) | (sl >= 2)]),
        ("V4 excluye SOLO zona muerta (0-+3)",    all_trades[(sl < 0) | (sl >= 3)]),
        ("V4 + slope < 0 OR slope > +3",          all_trades[(sl < 0) | (sl > 3)]),
        ("V4 giro fuerte solo (slope >= +3)",     all_trades[sl >= 3]),
        ("V4 + slope < -2",                       all_trades[sl < -2]),
    ]

    results = {}
    print(f"  {'Estrategia':<45}  {'TR':>4}  {'WR':>6}  {'Avg':>7}  {'Sharpe':>7}  {'MDD':>7}  {'Total':>7}")
    print(f"  {'-'*90}")
    for label, sub in variants:
        m = metrics(sub, label)
        results[label] = m

    # ── Ranking por Sharpe ────────────────────────────────────────────────────
    print()
    print("=" * 90)
    print("  RANKING POR SHARPE (solo variantes con datos)")
    print("=" * 90)
    ranked = [(lbl, m) for lbl, m in results.items() if m and m['trades'] >= MIN_TRADES]
    ranked.sort(key=lambda x: x[1]['sharpe'], reverse=True)
    print()
    for i, (lbl, m) in enumerate(ranked, 1):
        print(f"  #{i:<2} {lbl:<45}  Sharpe:{m['sharpe']:>6.2f}  WR:{m['wr']:>5.1f}%  "
              f"TR:{m['trades']:>3}  MDD:{m['mdd']:>+6.1f}%")

    # ── Candidato para walk-forward ────────────────────────────────────────────
    print()
    print("=" * 90)
    print("  CANDIDATO PARA WALK-FORWARD")
    print("=" * 90)
    if ranked:
        best_lbl, best_m = ranked[0]
        v4_m = results.get("V4 baseline (sin filtro slope)")
        print(f"""
  Mejor variante: {best_lbl}
    Sharpe: {best_m['sharpe']:.2f}  vs  V4: {(f"{v4_m['sharpe']:.2f}") if v4_m else '?'}
    WR:     {best_m['wr']:.1f}%  vs  V4: {(f"{v4_m['wr']:.1f}%") if v4_m else '?'}
    Trades: {best_m['trades']}  vs  V4: {v4_m['trades'] if v4_m else '?'}

  Siguiente paso: walk-forward de esta variante para confirmar out-of-sample.
  Si supera 60% de ventanas → candidato oficial V5b.
        """)
    else:
        print("  Sin datos suficientes para ranking.")

    # ── Trades individuales por variante top ───────────────────────────────────
    # Mostrar los trades de la variante alternativa vs los eliminados
    v5_orig = all_trades[sl < 0]
    v5b_alt = all_trades[(sl < 0) | (sl >= 3)]
    trades_nuevos = v5b_alt[~v5b_alt.index.isin(v5_orig.index)] if len(v5_orig) > 0 else v5b_alt

    # Los trades con slope >= 3 que se RE-incluyen
    reincluidos = all_trades[sl >= 3]
    if len(reincluidos) > 0:
        print()
        print("=" * 90)
        print("  TRADES RE-INCLUIDOS por slope >= +3 (vs V5 original)")
        print("  (estos son los trades que V5 excluía pero V5b conserva)")
        print("=" * 90)
        print(f"\n  {'Fecha':<12}  {'Ticker':<8}  {'RSI':>6}  {'Slope':>7}  {'Ret':>8}  {'Score':>6}")
        print(f"  {'-'*55}")
        for _, row in reincluidos.sort_values('date').iterrows():
            win = "✓" if row['ret'] > 0 else "✗"
            print(f"  {str(row['date'])[:10]:<12}  {row['ticker']:<8}  "
                  f"{row['rsi']:>6.1f}  {row['rsi_slope']:>+7.2f}  "
                  f"{row['ret']*100:>+7.2f}% {win}  score:{row['score']:>4.0f}")

        r_new = reincluidos['ret'].values
        if len(r_new) > 0:
            print(f"\n  Resumen re-incluidos: N={len(r_new)}, "
                  f"WR={( r_new>0).mean()*100:.1f}%, "
                  f"Avg={r_new.mean()*100:+.2f}%")


if __name__ == '__main__':
    main()
