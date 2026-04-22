"""
WALK-FORWARD VALIDATION: V4 baseline vs V5 (V4 + rsi_slope < 0)
================================================================
Metodología idéntica a Round 3:
  - Ventanas rodantes: Train 6 meses → Test 2 meses → Step 2 meses
  - 8 ventanas en total (Sep 2024 → Mar 2026)
  - Sin lookahead: cada ventana test usa SOLO datos anteriores al período

Criterio de éxito para V5:
  - Supera V4 en al menos 5/8 ventanas (consistencia)
  - Sharpe promedio test V5 > Sharpe promedio test V4
  - No más pérdidas en ventanas que V4

Universo: 258 tickers (titan.db completo)
RSI: Wilder ewm(com=13) — VERIFICADO
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os
import pandas as pd
import numpy as np
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from titan_system.core.database import TitanDB
from titan_system.core.data_loader import ACTIVOS, CONTEXT_TICKERS

# ── Config ────────────────────────────────────────────────────────────────────
HOLD_DAYS   = 10
MIN_TRADES  = 2   # mínimo por ventana para calcular métricas

ALL_TICKERS = list(set(ACTIVOS + CONTEXT_TICKERS))

# Ventanas Walk-Forward (idénticas a Round 3)
WINDOWS = [
    ('2024-06-01', '2024-12-01', '2024-12-01', '2025-02-01'),
    ('2024-08-01', '2025-02-01', '2025-02-01', '2025-04-01'),
    ('2024-10-01', '2025-04-01', '2025-04-01', '2025-06-01'),
    ('2024-12-01', '2025-06-01', '2025-06-01', '2025-08-01'),
    ('2025-02-01', '2025-08-01', '2025-08-01', '2025-10-01'),
    ('2025-04-01', '2025-10-01', '2025-10-01', '2025-12-01'),
    ('2025-06-01', '2025-12-01', '2025-12-01', '2026-02-01'),
    ('2025-08-01', '2026-02-01', '2026-02-01', '2026-03-28'),
]

# ── Indicadores ───────────────────────────────────────────────────────────────

def calc_rsi_wilder(close, period=14):
    """Wilder's RSI — ewm(com=period-1). VERIFICADO."""
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

# ── Generador de señales ──────────────────────────────────────────────────────

def get_signals(all_data, spy_df, start_date, end_date, strategy):
    """
    Genera trades para una ventana específica.
    strategy: 'v4' | 'v5'
    """
    trades = []
    recent = {}
    dates  = sorted(d for d in spy_df.index
                    if start_date <= str(d)[:10] <= end_date)

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

            rsi_s   = calc_rsi_wilder(c)
            rsi14   = rsi_s.iloc[-1]
            rsi_sl  = rsi_s.iloc[-1] - rsi_s.iloc[-4] if len(rsi_s) >= 4 else 0.0
            mh      = calc_macd_hist(c)
            mh_c    = mh.iloc[-1]; mh_p = mh.iloc[-2] if len(mh) > 1 else 0.0
            sma50   = c.rolling(50).mean().iloc[-1]
            atr14   = calc_atr(h, l, c).iloc[-1]
            v20     = v.rolling(20).mean().iloc[-1]
            vr      = v.iloc[-1] / (v20 + 1e-10)
            price   = c.iloc[-1]
            dsma    = (price / sma50 - 1) * 100
            acc_n   = (mh_c - mh_p) / (atr14 * 0.01 + 1e-6)
            score   = calc_score(rsi14, dsma, acc_n, vr)

            if any(np.isnan(x) for x in [rsi14, dsma, score, rsi_sl]):
                continue

            # Filtros base V4
            if not (rsi14 < 25 and dsma < -10 and score > 30 and
                    vr < 1.5 and mh_c > mh_p):
                continue

            # Filtro adicional V5
            if strategy == 'v5' and rsi_sl >= 0:
                continue

            # Retorno futuro
            future = df[df.index > date].head(HOLD_DAYS)
            if len(future) < HOLD_DAYS:
                continue

            ret = future['close'].iloc[-1] / price - 1
            trades.append({'date': date, 'ticker': ticker, 'ret': ret,
                           'rsi': rsi14, 'rsi_slope': rsi_sl})
            recent[ticker] = date

    return pd.DataFrame(trades)

def window_metrics(df):
    if df is None or len(df) < MIN_TRADES:
        return None
    r     = df['ret'].values
    wins  = (r > 0).sum()
    wr    = wins / len(r) * 100
    avg   = r.mean() * 100
    daily = r / HOLD_DAYS
    sh    = (daily.mean() / (daily.std() + 1e-10)) * np.sqrt(252)
    tot   = ((1 + r).prod() - 1) * 100
    return {'trades': len(r), 'wins': int(wins), 'wr': wr,
            'avg': avg, 'sharpe': sh, 'total': tot}

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 80)
    print("  WALK-FORWARD: V4 baseline vs V5 (V4 + rsi_slope < 0)")
    print("  8 ventanas | Train 6m → Test 2m | 258 tickers")
    print("  RSI: Wilder ewm(com=13) — VERIFICADO")
    print("=" * 80)

    print("\n  Cargando datos...")
    with TitanDB() as db:
        all_data = {}
        for t in ALL_TICKERS:
            df = db.get_prices(t, '2024-06-01', '2026-03-28')
            if df is not None and len(df) > 80:
                all_data[t] = df.sort_index()
    spy_df = all_data.get('SPY')
    print(f"  {len(all_data)} tickers cargados\n")

    wf_v4, wf_v5 = [], []

    for wi, (tr_s, tr_e, te_s, te_e) in enumerate(WINDOWS):
        print(f"  WF{wi+1}  Train: {tr_s} → {tr_e}  |  Test: {te_s} → {te_e}")

        t_v4 = get_signals(all_data, spy_df, te_s, te_e, 'v4')
        t_v5 = get_signals(all_data, spy_df, te_s, te_e, 'v5')

        m4 = window_metrics(t_v4)
        m5 = window_metrics(t_v5)

        v4_str = (f"TR:{m4['trades']:>2}  WR:{m4['wr']:>5.1f}%  "
                  f"Avg:{m4['avg']:>+5.2f}%  Sh:{m4['sharpe']:>5.2f}"
                  if m4 else "  <2 trades")
        v5_str = (f"TR:{m5['trades']:>2}  WR:{m5['wr']:>5.1f}%  "
                  f"Avg:{m5['avg']:>+5.2f}%  Sh:{m5['sharpe']:>5.2f}"
                  if m5 else "  <2 trades")

        winner = ""
        if m4 and m5:
            if m5['sharpe'] > m4['sharpe']:
                winner = "  ★ V5 gana"
            elif m4['sharpe'] > m5['sharpe']:
                winner = "  ✓ V4 gana"
            else:
                winner = "  = empate"

        print(f"    V4: {v4_str}")
        print(f"    V5: {v5_str}{winner}")
        print()

        wf_v4.append(m4)
        wf_v5.append(m5)

    # ── Resumen global ────────────────────────────────────────────────────────
    valid_v4 = [m for m in wf_v4 if m]
    valid_v5 = [m for m in wf_v5 if m]

    sh_v4 = [m['sharpe'] for m in valid_v4]
    sh_v5 = [m['sharpe'] for m in valid_v5]
    wr_v4 = [m['wr']     for m in valid_v4]
    wr_v5 = [m['wr']     for m in valid_v5]

    # Ventanas positivas (Sharpe > 0)
    pos_v4 = sum(1 for s in sh_v4 if s > 0)
    pos_v5 = sum(1 for s in sh_v5 if s > 0)

    # Ventanas donde V5 > V4 (solo en ventanas con datos para ambos)
    paired = [(m4, m5) for m4, m5 in zip(wf_v4, wf_v5) if m4 and m5]
    v5_wins = sum(1 for m4, m5 in paired if m5['sharpe'] > m4['sharpe'])
    v4_wins = sum(1 for m4, m5 in paired if m4['sharpe'] > m5['sharpe'])

    print("=" * 80)
    print("  RESUMEN WALK-FORWARD")
    print("=" * 80)
    print(f"\n  {'Métrica':<35} {'V4 baseline':>14}  {'V5 rsi<0':>14}")
    print(f"  {'-'*65}")
    print(f"  {'Ventanas con datos':<35} {len(valid_v4):>14}  {len(valid_v5):>14}")
    print(f"  {'Ventanas Sharpe > 0':<35} {pos_v4:>14}  {pos_v5:>14}")
    print(f"  {'Sharpe promedio':<35} {np.mean(sh_v4):>14.2f}  {np.mean(sh_v5):>14.2f}")
    print(f"  {'Sharpe mediana':<35} {np.median(sh_v4):>14.2f}  {np.median(sh_v5):>14.2f}")
    print(f"  {'WR promedio':<35} {np.mean(wr_v4):>13.1f}%  {np.mean(wr_v5):>13.1f}%")
    print(f"  {'Trades promedio / ventana':<35} {np.mean([m['trades'] for m in valid_v4]):>14.1f}  "
          f"{np.mean([m['trades'] for m in valid_v5]):>14.1f}")
    print(f"  {'-'*65}")
    print(f"  {'V5 gana en N ventanas (de {len(paired)} comunes)':<35} {v5_wins:>14}  ")
    print(f"  {'V4 gana en N ventanas':<35} {v4_wins:>14}  ")

    # ── Veredicto ─────────────────────────────────────────────────────────────
    print()
    print("=" * 80)
    print("  VEREDICTO WALK-FORWARD")
    print("=" * 80)

    sh_mejora   = np.mean(sh_v5) > np.mean(sh_v4)
    wr_mejora   = np.mean(wr_v5) > np.mean(wr_v4)
    consistente = v5_wins >= len(paired) * 0.6  # gana ≥ 60% de ventanas
    positivo    = pos_v5 >= pos_v4

    if sh_mejora and consistente and positivo:
        print(f"""
  RESULTADO: V5 = V4 + rsi_slope < 0 está VALIDADO.

  Criterios cumplidos:
  ✓ Sharpe promedio superior  (V5: {np.mean(sh_v5):.2f} vs V4: {np.mean(sh_v4):.2f})
  ✓ Consistente: V5 gana en {v5_wins}/{len(paired)} ventanas (objetivo ≥ {int(len(paired)*0.6)})
  ✓ Ventanas positivas: V5 {pos_v5}/{len(valid_v5)} vs V4 {pos_v4}/{len(valid_v4)}

  Recomendación: crear SCANNER/invertir_v5.py con filtro rsi_slope < 0.
  Walk-forward confirma que el filtro generaliza fuera de muestra.
        """)
    elif sh_mejora and not consistente:
        print(f"""
  RESULTADO: V5 muestra MEJORA PARCIAL pero no consistente.

  Sharpe promedio sube (V5: {np.mean(sh_v5):.2f} vs V4: {np.mean(sh_v4):.2f})
  pero V5 solo gana en {v5_wins}/{len(paired)} ventanas (objetivo ≥ {int(len(paired)*0.6)}).
  La mejora no es suficientemente robusta entre regímenes de mercado.

  Recomendación: mantener V4. El filtro rsi_slope puede ser sobre-ajuste parcial.
        """)
    else:
        print(f"""
  RESULTADO: V5 NO mejora V4 en walk-forward.

  V4 gana en más ventanas ({v4_wins} vs {v5_wins}).
  El filtro rsi_slope < 0 funciona in-sample pero no generaliza.

  Recomendación: mantener V4 sin cambios. El filtro rsi_slope es sobre-ajuste.
        """)

    # Comparativa final lado a lado
    print("  Detalle por ventana:")
    print(f"  {'WF':>3}  {'Test period':<25}  {'V4 Sh':>7}  {'V5 Sh':>7}  {'Ganador':>10}")
    print(f"  {'-'*60}")
    for i, ((_, _, te_s, te_e), m4, m5) in enumerate(zip(WINDOWS, wf_v4, wf_v5)):
        sh4 = f"{m4['sharpe']:>7.2f}" if m4 else "    ---"
        sh5 = f"{m5['sharpe']:>7.2f}" if m5 else "    ---"
        if m4 and m5:
            gan = "V5 ★" if m5['sharpe'] > m4['sharpe'] else "V4" if m4['sharpe'] > m5['sharpe'] else "="
        else:
            gan = "sin datos"
        print(f"  WF{i+1:>1}  {te_s} → {te_e}  {sh4}  {sh5}  {gan:>10}")
    print()

if __name__ == '__main__':
    main()
