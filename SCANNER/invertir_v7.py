#!/usr/bin/env python3
"""
INVERTIR V7.0 — Dual-Signal Scanner (A + C)
=============================================

Evolucion:
  V1: RSI<30 + MACD up
  V2: + SMA50 + Vol + Scoring
  Final: + SPY regime + anti-knife (Sharpe 4.85)
  V4: + RSI<25 + SMA<-10% + Score>30 (Sharpe 14.15)
  V5: V4 + sin LatAm + hold 7d
  V6: V5 OR Williams+Squeeze (reemplazado — Signal B era debil)
  V7 (esta): Signal A (mean reversion) + Signal C (crash+volume)

Innovacion V7: Arquitectura A+C reemplaza A+B de V6.
  SENAL A (V5): RSI<25 + MACD up + SMA<-10% + Score>30 (CON SPY regime)
  SENAL C (nueva): ROC 10d < -15% + Volume > 2x promedio (SIN regime — contrarian)

  Signal B (Williams+Squeeze) REMOVIDA: WR 47.6%, Sharpe 0.49, MDD -25.7%.
  Signal C la supera en todo: WR 71.7%, Sharpe 3.97, MDD -7.6%.
  0% overlap entre A y C — completamente complementarias.

Resultados backtested A+C (Mar24-Abr26):
  Full Period: 59 trades, WR 71.2%, Sharpe 4.12, MDD -7.9%, Total +641%
  Walk-Forward 5w: 100% (5/5), avg Sharpe 6.77
  Walk-Forward 7w: 100% (7/7), avg Sharpe 11.21
  Monte Carlo: P(Sharpe>0)=100%, Worst 1% Sharpe=+2.39, Worst 1% MDD=-19.7%
  Profit Factor: 5.69

Evidencia (backtests/v7_architecture_decision.py):
  V6 (A+B):  Sharpe 1.17 | WR 54.5% | MDD -21.9% | WF7w 71% FAIL
  V7 (A+C):  Sharpe 4.12 | WR 71.2% | MDD  -7.9% | WF7w 100% PASS
  A+B+C:     Sharpe 2.40 | WR 61.4% | MDD -21.9% | WF7w 86%
  -> A+C gano 5/5 criterios vs A+B+C

Holding: 7 dias habiles
Uso: python SCANNER/invertir_v7.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════════════════════
#  PARAMETROS V7
# ═══════════════════════════════════════════════════════════════════════════════

# Señal A (V5 — mean reversion profunda, CON regime)
V7_RSI_MAX = 25
V7_SMA_DIST_MAX = -10.0
V7_SCORE_MIN = 30
V7_VOL_MAX = 1.5

# Señal C (Crash + Volume — contrarian, SIN regime)
V7_ROC10_MAX = -15.0      # Caida >= 15% en 10 dias
V7_VOL_RATIO_MIN = 2.0    # Volumen >= 2x promedio 20d

# Comunes
V7_HOLDING_DAYS = 7
V7_ANTIKNIFE_DAYS = 5

# ═══════════════════════════════════════════════════════════════════════════════
#  UNIVERSO V7 — Sin LatAm (~197 activos)
# ═══════════════════════════════════════════════════════════════════════════════

TICKERS_STR = """
AAPL, ADBE, ADI, AI, ALAB, AMAT, AMD, ARM, ASML, AVGO, BIDU, COIN, CRM, CRWV,
CSCO, DOCU, ETSY, GOOGL, IBM, INTC, IREN, LRCX, META, MRVL, MSFT, MSTR, MU,
NTES, NVDA, ORCL, PANW, PATH, PLTR, QCOM, RBLX, RGTI, ROKU, SAP, SE, SHOP,
SNAP, SNOW, SONY, SPOT, TEAM, TSM, TWLO, UBER, UPST, ZM, GLW, GRMN, HPQ, MSI,
SWKS, TXN, EA, ASTS, RKLB, ERIC, BB, AXP, BAC, BCS, BK, BKNG,
C, GS, HOOD, HSBC, ING, JPM, LYG, MA, MUFG, PYPL, SCHW, USB, V,
WFC, AIG, HDB, ABBV, ABT, AMGN, AZN, BIIB, BMY, CVS, DHR, GILD, GSK,
ISRG, JNJ, LLY, MDT, MRK, MRNA, NVS, PFE, TMO, UNH, BKR, BP, CVX, E, EQNR, HAL,
OXY, PSX, SHEL, SLB, TTE, XOM, AEM, B, BHP, CDE, FCX, GFI,
HL, HMY, KGC, LAC, MOS, MUX, NEM, NG, NUE, PAAS, RIO,
AAP, ANF, CL, COST, DEO, EBAY, HD, HSY, KMB, KO, MCD, MDLZ, MO, NKE,
ORLY, PEP, PG, PM, ROST, SBUX, SYY, TGT, TJX, UL, WMT, YELP, AVY, BA, CAT, DD, DE,
FDX, GE, HON, HWM, IFF, IP, LMT, MMM, PCAR, PBI, RTX, SNA, UNP,
F, GM, HMC, HOG, NIO, RACE, STLA, TM, TSLA, AAL, ABNB, CAR, CCL, DAL, LVS, SPCE, TCOM, TRIP,
UAL, TMUS, VOD, VZ
"""

tickers = [t.strip() for t in TICKERS_STR.replace('\n', '').split(',') if t.strip()]
if 'SPY' not in tickers:
    tickers.append('SPY')


# ═══════════════════════════════════════════════════════════════════════════════
#  INDICADORES
# ═══════════════════════════════════════════════════════════════════════════════

def calc_rsi(close, period=14):
    """RSI con Wilder's smoothing — OBLIGATORIO. NUNCA rolling."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period-1, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - 100 / (1 + rs)

def calc_macd(close, fast=12, slow=26, signal=9):
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    macd = ema_f - ema_s
    sig = macd.ewm(span=signal, adjust=False).mean()
    return macd, sig, macd - sig

def calc_atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ═══════════════════════════════════════════════════════════════════════════════
#  CHECK REGIME (SPY health) — solo aplica a Señal A
# ═══════════════════════════════════════════════════════════════════════════════

def check_regime(spy_data):
    """Safe = SPY above SMA50 AND 20d volatility < 1.0%"""
    close = spy_data['Close'].squeeze()
    if len(close) < 55:
        return False, "Datos insuficientes"

    sma50 = close.rolling(50).mean().iloc[-1]
    price = close.iloc[-1]
    vol_20d = close.pct_change().rolling(20).std().iloc[-1] * 100
    dist_sma50 = (price / sma50 - 1) * 100

    above_sma = price > sma50
    low_vol = vol_20d < 1.0

    info = {
        'spy_price': round(price, 2),
        'spy_sma50': round(sma50, 2),
        'spy_dist': f"{dist_sma50:+.1f}%",
        'spy_vol20d': f"{vol_20d:.2f}%",
        'above_sma': above_sma,
        'low_vol': low_vol,
        'safe': above_sma and low_vol,
    }
    return info['safe'], info


# ═══════════════════════════════════════════════════════════════════════════════
#  SEÑAL A: Mean Reversion profunda (V5) — REQUIERE regime safe
# ═══════════════════════════════════════════════════════════════════════════════

def signal_a_mean_reversion(ticker, data):
    """RSI<25 + MACD up + SMA<-10% + Score>30 + Vol<1.5x"""
    close = data['Close'].squeeze()
    high = data['High'].squeeze()
    low = data['Low'].squeeze()
    volume = data['Volume'].squeeze()
    close = close.dropna()
    if len(close) < 55:
        return None

    rsi = calc_rsi(close)
    _, _, macd_hist = calc_macd(close)
    sma50 = close.rolling(50).mean()
    atr = calc_atr(high, low, close)
    vol_avg_20 = volume.rolling(20).mean()

    curr_rsi = rsi.iloc[-1]
    curr_hist = macd_hist.iloc[-1]
    prev_hist = macd_hist.iloc[-2] if len(macd_hist) > 1 else 0
    price = close.iloc[-1]
    curr_sma50 = sma50.iloc[-1]
    curr_atr = atr.iloc[-1]

    if np.isnan(curr_rsi) or np.isnan(curr_sma50) or np.isnan(curr_atr) or np.isnan(price):
        return None

    dist_sma50 = (price / curr_sma50 - 1) * 100
    vol_ratio = volume.iloc[-1] / (vol_avg_20.iloc[-1] + 1e-10)
    macd_accel = curr_hist - prev_hist
    macd_accel_norm = macd_accel / (curr_atr * 0.01 + 1e-6)

    # Filtros base
    if curr_rsi >= 30 or curr_hist <= prev_hist or dist_sma50 > -5 or vol_ratio > V7_VOL_MAX:
        return None
    # Filtros V5 estrictos
    if curr_rsi >= V7_RSI_MAX or dist_sma50 > V7_SMA_DIST_MAX:
        return None

    # Score compuesto
    rsi_score = max(0, min(40, (30 - curr_rsi) / 30 * 40))
    stretch_score = max(0, min(30, (abs(dist_sma50) - 5) / 15 * 30))
    macd_score = max(0, min(20, macd_accel_norm * 5))
    vol_score = max(0, min(10, (1.5 - vol_ratio) / 1.5 * 10))
    total_score = rsi_score + stretch_score + macd_score + vol_score

    if total_score < V7_SCORE_MIN:
        return None

    stop_loss = price - 2 * curr_atr
    take_profit = price * 1.03
    risk_pct = (1 - stop_loss / price) * 100

    rsi_prev = rsi.iloc[-2] if len(rsi) > 1 else curr_rsi
    rsi_dir = "falling" if curr_rsi < rsi_prev else "rising"

    return {
        'Ticker': ticker,
        'Signal': 'A (MeanRev)',
        'Precio': round(float(price), 2),
        'RSI': round(float(curr_rsi), 1),
        'RSI Dir': rsi_dir,
        'vs SMA50': f"{dist_sma50:.1f}%",
        'Vol': f"{vol_ratio:.2f}x",
        'Score': round(float(total_score)),
        'ROC 10d': '',
        'VolSpike': '',
        'Stop': f"${stop_loss:.2f}",
        'Target': f"${take_profit:.2f}",
        'Riesgo': f"{risk_pct:.1f}%",
        '_score': total_score,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SEÑAL C: Crash + Volume — NO REQUIERE regime (contrarian)
# ═══════════════════════════════════════════════════════════════════════════════

def signal_c_crash_volume(ticker, data):
    """ROC 10d < -15% + Volume > 2x promedio 20d.
    Captura liquidaciones forzadas institucionales.
    NO usa regime filter — es inherentemente contrarian:
    funciona MEJOR en mercados bajistas cuando institucionales liquidan."""
    close = data['Close'].squeeze()
    volume = data['Volume'].squeeze()
    high = data['High'].squeeze()
    low = data['Low'].squeeze()
    close = close.dropna()
    if len(close) < 25:
        return None

    # ROC 10d
    if len(close) < 11:
        return None
    roc10 = (close.iloc[-1] / close.iloc[-11] - 1) * 100

    # Volume ratio
    vol_avg_20 = volume.rolling(20).mean()
    curr_vol = volume.iloc[-1]
    curr_vol_avg = vol_avg_20.iloc[-1]

    if np.isnan(roc10) or np.isnan(curr_vol) or np.isnan(curr_vol_avg) or curr_vol_avg == 0:
        return None

    vol_ratio = curr_vol / curr_vol_avg
    price = close.iloc[-1]

    # Filtros C
    if roc10 >= V7_ROC10_MAX:
        return None
    if vol_ratio < V7_VOL_RATIO_MIN:
        return None

    # RSI para referencia (no como filtro)
    rsi = calc_rsi(close)
    curr_rsi = rsi.iloc[-1]

    # ATR para stop
    atr = calc_atr(high, low, close)
    curr_atr = atr.iloc[-1]
    if np.isnan(curr_atr):
        curr_atr = price * 0.03  # fallback 3%

    stop_loss = price - 2 * curr_atr
    take_profit = price * 1.05  # target mas amplio para crashes
    risk_pct = (1 - stop_loss / price) * 100

    # SMA50 para referencia
    sma50 = close.rolling(50).mean()
    dist_sma = (price / sma50.iloc[-1] - 1) * 100 if len(sma50) >= 50 and not np.isnan(sma50.iloc[-1]) else 0

    return {
        'Ticker': ticker,
        'Signal': 'C (Crash)',
        'Precio': round(float(price), 2),
        'RSI': round(float(curr_rsi), 1) if not np.isnan(curr_rsi) else '',
        'RSI Dir': '',
        'vs SMA50': f"{dist_sma:.1f}%",
        'Vol': '',
        'Score': '',
        'ROC 10d': f"{roc10:.1f}%",
        'VolSpike': f"{vol_ratio:.1f}x",
        'Stop': f"${stop_loss:.2f}",
        'Target': f"${take_profit:.2f}",
        'Riesgo': f"{risk_pct:.1f}%",
        '_score': abs(roc10) * vol_ratio,  # Sorting: mas extremo = mejor
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    hoy = datetime.now()
    hoy_str = hoy.strftime('%Y-%m-%d')
    dia_nombre = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes',
                  'Sabado', 'Domingo'][hoy.weekday()]

    n_tickers = len([t for t in tickers if t != 'SPY'])
    print(f"INVERTIR V7.0 — Dual-Signal Scanner (A+C) — {hoy_str} ({dia_nombre})")
    print(f"Senal A (MeanRev): RSI<{V7_RSI_MAX} + SMA<{V7_SMA_DIST_MAX}% + Score>{V7_SCORE_MIN} [CON regime]")
    print(f"Senal C (Crash):   ROC10d<{V7_ROC10_MAX}% + Vol>{V7_VOL_RATIO_MIN}x [SIN regime — contrarian]")
    print(f"Universo: {n_tickers} activos (sin LatAm) | Hold: {V7_HOLDING_DAYS}d")
    print(f"Escaneando...\n")

    # Download
    data_all = yf.download(tickers, period="3mo", progress=False, threads=True)

    # ── STEP 1: Regime (solo afecta Señal A) ──
    print("=" * 80)
    print("  PASO 1: REGIMEN DEL MERCADO (SPY) — aplica solo a Senal A")
    print("=" * 80)

    try:
        spy_data = data_all.xs('SPY', level=1, axis=1)
    except Exception:
        spy_data = data_all

    is_safe, regime = check_regime(spy_data)

    if isinstance(regime, dict):
        sma_status = "SOBRE SMA50" if regime['above_sma'] else "BAJO SMA50"
        vol_status = "BAJA" if regime['low_vol'] else "ALTA"
        regime_status = "SEGURO" if is_safe else "PELIGRO"

        print(f"  SPY:         ${regime['spy_price']}  ({regime['spy_dist']} vs SMA50)")
        print(f"  SMA50:       ${regime['spy_sma50']}  -> {sma_status}")
        print(f"  Volatilidad: {regime['spy_vol20d']}  -> {vol_status}")
        print(f"  Regimen:     {regime_status}")

    if not is_safe:
        reason = 'SPY bajo SMA50' if isinstance(regime, dict) and not regime['above_sma'] else 'Volatilidad alta'
        print(f"""
  {'=' * 68}
  REGIMEN PELIGRO — Senal A (MeanRev) BLOQUEADA.
  Razon: {reason}
  PERO: Senal C (Crash) sigue ACTIVA — es contrarian por diseno.
  (Las mejores oportunidades C ocurren en mercados bajistas)
  {'=' * 68}
""")
    else:
        print(f"\n  Regimen SEGURO — Ambas senales activas (A + C)\n")

    # ── STEP 2: Scan ──
    results_a = []
    results_c = []

    for ticker in tickers:
        if ticker == 'SPY':
            continue
        try:
            df = data_all.xs(ticker, level=1, axis=1)

            # Señal A (solo si regime es safe)
            if is_safe:
                sig_a = signal_a_mean_reversion(ticker, df)
                if sig_a:
                    results_a.append(sig_a)

            # Señal C (SIEMPRE activa — contrarian)
            sig_c = signal_c_crash_volume(ticker, df)
            if sig_c:
                # Evitar duplicados: si ya esta en A, no agregar en C
                if not any(r['Ticker'] == ticker for r in results_a):
                    results_c.append(sig_c)

        except Exception:
            pass

    # ── STEP 3: Display ──
    all_results = results_a + results_c
    all_results.sort(key=lambda x: x['_score'], reverse=True)

    print("=" * 80)
    print("  PASO 2: SENALES V7 (DUAL-SIGNAL A+C)")
    print("=" * 80)

    if all_results:
        count_a = len(results_a)
        count_c = len(results_c)
        a_status = "" if is_safe else " (bloqueada por regime)"
        print(f"  {len(all_results)} senales V7: {count_a} tipo A (MeanRev){a_status} + {count_c} tipo C (Crash)\n")

        display_cols = ['Ticker', 'Signal', 'Precio', 'RSI', 'vs SMA50',
                       'ROC 10d', 'VolSpike', 'Stop', 'Target', 'Riesgo']
        df_res = pd.DataFrame(all_results)[display_cols]
        print(df_res.to_string(index=False))
    else:
        print(f"  Sin senales V7 hoy.")
        print(f"  V7 genera ~59 trades en 24 meses (~1 cada 12 dias).")
        print(f"  Esto es normal — calidad sobre cantidad.")

    # ── STEP 4: Action plan ──
    print(f"\n{'=' * 80}")
    print("  PASO 3: PLAN DE ACCION V7")
    print("=" * 80)

    if all_results:
        top = all_results[:3]
        has_crash_signals = len(results_c) > 0

        if has_crash_signals and not is_safe:
            print(f"""
  REGIMEN PELIGRO pero SENALES C (CRASH) DETECTADAS.
  Las senales C son contrarian — funcionan EN mercados bajistas.
  Backtested: C sola tiene WR 71.7%, Sharpe 3.97, MDD -7.6%.
""")

        print(f"  Top {len(top)} oportunidades (max 3 posiciones):\n")

        for i, s in enumerate(top, 1):
            print(f"  {i}. {s['Ticker']:<6} @ ${s['Precio']}  [{s['Signal']}]")
            if 'MeanRev' in s['Signal']:
                print(f"     RSI: {s['RSI']} | {s['vs SMA50']} bajo SMA50 | Score: {s['Score']}")
            else:
                print(f"     Crash: {s['ROC 10d']} en 10d | Volumen: {s['VolSpike']} promedio | RSI: {s['RSI']}")
            print(f"     Stop: {s['Stop']} ({s['Riesgo']} riesgo) | Target: {s['Target']}")
            print()

        print(f"""  REGLAS V7:
  - Comprar al OPEN del dia siguiente
  - Posicion: max 10% del portfolio por trade
  - Stop loss: precio de 'Stop' -- vender SIN pensar si lo toca
  - Take profit: vender 50% si sube 3% (A) o 5% (C) en primeros 3 dias
  - Holding: {V7_HOLDING_DAYS} dias habiles, despues cerrar
  - ANTI-KNIFE: no comprar mismo ticker en {V7_ANTIKNIFE_DAYS} dias
  - NUNCA promediar para abajo

  BACKTESTED (v7_architecture_decision.py):
  V7 (A+C): 59 trades, WR 71.2%, Sharpe 4.12, MDD -7.9%
  Walk-Forward: 100% positivas (5/5 y 7/7)
  Monte Carlo: P(Sharpe>0)=100%, Worst 1% Sharpe=+2.39
  Profit Factor: 5.69
""")
    elif is_safe:
        print(f"""
  REGIMEN SEGURO pero SIN SENALES V7.
  V7 genera ~59 trades en 24 meses (~1 cada 12 dias).
  No forzar trades. Revisar manana.
""")
    else:
        print(f"""
  REGIMEN PELIGRO + SIN SENALES C (no hay crashes extremos hoy).
  Senal A bloqueada por regime. Senal C no detecta crashes.
  Mantener efectivo. Revisar manana.
  (Recordar: C se activa en crashes -15% con volumen 2x+)
""")

    # Summary
    if all_results:
        if results_c and not is_safe:
            decision = f"OPERAR SENALES C ({len(results_c)} crash signals)"
        elif is_safe:
            decision = f"OPERAR ({len(all_results)} senales)"
        else:
            decision = "ESPERAR"
    elif is_safe:
        decision = "ESPERAR (sin senales V7)"
    else:
        decision = "NO OPERAR (regime peligroso, sin crashes)"

    print(f"  >>> DECISION: {decision} <<<")
    print(f"  Proximo escaneo: manana al cierre del mercado")
    print(f"  Ejecutar: python SCANNER/invertir_v7.py")
    print(f"  (V6 como referencia: python SCANNER/invertir_v6.py)")


if __name__ == '__main__':
    main()
