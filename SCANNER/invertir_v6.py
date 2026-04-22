#!/usr/bin/env python3
"""
INVERTIR V6.0 — Dual-Signal Mean Reversion Scanner
====================================================

Evolucion:
  V1: RSI<30 + MACD up
  V2: + SMA50 + Vol + Scoring
  Final: + SPY regime + anti-knife (Sharpe 4.85)
  V4: + RSI<25 + SMA<-10% + Score>30 (Sharpe 14.15)
  V5: V4 + sin LatAm + hold 7d (Sharpe ~13-17)
  V6 (esta): V5 OR Williams+Squeeze (Sharpe 7.71, 24 trades)

Innovacion V6: DOS señales independientes en UNION (OR)
  SEÑAL A (V5): RSI<25 + MACD up + SMA<-10% + Score>30
  SEÑAL B (nueva): Williams %R < -90 + Bollinger Squeeze + dist SMA < -5%

  0 trades en comun — son completamente complementarias.
  V5 captura oversold profundo. B captura Bollinger squeezes extremos.

Resultados backtested (investigacion_modelo_superador.py + deep_analysis):
  Full Period (Sep24-Abr26):
    V6 (Union): 24 trades, WR 58%, Sharpe 7.71, MDD -4.7%, Total +88.6%
    V5 sola:     7 trades, WR 57%, Sharpe 6.52, MDD -4.7%, Total +12.2%
    D sola:     17 trades, WR 59%, Sharpe 8.10, MDD -5.9%, Total +68.1%

  Walk-Forward: 100% ventanas positivas (5/5), avg Sharpe test 12.10
  Monte Carlo: P(Sharpe>0)=99.9%, P(Total>0)=99.9%, Worst 1% Sharpe=2.19

Holding: 7 dias habiles (validado en analisis_v5_candidates.py)

Uso: python SCANNER/invertir_v6.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════════════════════
#  PARAMETROS V6
# ═══════════════════════════════════════════════════════════════════════════════

# Señal A (V5)
V6_RSI_MAX = 25
V6_SMA_DIST_MAX = -10.0
V6_SCORE_MIN = 30
V6_VOL_MAX = 1.5

# Señal B (Williams + Bollinger Squeeze)
V6_WILLIAMS_MAX = -90       # Williams %R < -90 (extreme oversold)
V6_BB_SQUEEZE_MULT = 1.2    # BB width < 1.2x minimo de 50d (squeeze)
V6_B_SMA_DIST_MAX = -5.0    # Debajo de SMA50

# Comunes
V6_HOLDING_DAYS = 7
V6_ANTIKNIFE_DAYS = 5

# ═══════════════════════════════════════════════════════════════════════════════
#  UNIVERSO V6 — Sin LatAm
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

def calc_williams_r(high, low, close, period=14):
    """Williams %R: -100 a 0. <-80 = oversold, <-90 = extreme."""
    highest = high.rolling(period).max()
    lowest = low.rolling(period).min()
    return -100 * (highest - close) / (highest - lowest + 1e-10)

def calc_bollinger_width(close, period=20, std_dev=2):
    """Ancho de Bollinger Bands como % del precio."""
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    width = (upper - lower) / sma * 100
    return width


# ═══════════════════════════════════════════════════════════════════════════════
#  CHECK REGIME (SPY health) — igual que V4/V5
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
#  SEÑAL A: Mean Reversion profunda (V5)
# ═══════════════════════════════════════════════════════════════════════════════

def signal_a_v5(ticker, data):
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
    if curr_rsi >= 30 or curr_hist <= prev_hist or dist_sma50 > -5 or vol_ratio > V6_VOL_MAX:
        return None
    # Filtros V5
    if curr_rsi >= V6_RSI_MAX or dist_sma50 > V6_SMA_DIST_MAX:
        return None

    # Score
    rsi_score = max(0, min(40, (30 - curr_rsi) / 30 * 40))
    stretch_score = max(0, min(30, (abs(dist_sma50) - 5) / 15 * 30))
    macd_score = max(0, min(20, macd_accel_norm * 5))
    vol_score = max(0, min(10, (1.5 - vol_ratio) / 1.5 * 10))
    total_score = rsi_score + stretch_score + macd_score + vol_score

    if total_score < V6_SCORE_MIN:
        return None

    stop_loss = price - 2 * curr_atr
    take_profit = price * 1.03
    risk_pct = (1 - stop_loss / price) * 100

    rsi_prev = rsi.iloc[-2] if len(rsi) > 1 else curr_rsi
    rsi_dir = "falling" if curr_rsi < rsi_prev else "rising"

    return {
        'Ticker': ticker,
        'Signal': 'A (V5)',
        'Precio': round(float(price), 2),
        'RSI': round(float(curr_rsi), 1),
        'RSI Dir': rsi_dir,
        'vs SMA50': f"{dist_sma50:.1f}%",
        'Vol': f"{vol_ratio:.2f}x",
        'Score': round(float(total_score)),
        'Stop': f"${stop_loss:.2f}",
        'Target': f"${take_profit:.2f}",
        'Riesgo': f"{risk_pct:.1f}%",
        'Williams': '',
        'BB Squeeze': '',
        '_score': total_score,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SEÑAL B: Bollinger Squeeze + Williams %R extremo
# ═══════════════════════════════════════════════════════════════════════════════

def signal_b_williams_squeeze(ticker, data):
    """Williams %R < -90 + Bollinger width en minimo (squeeze) + debajo SMA50"""
    close = data['Close'].squeeze()
    high = data['High'].squeeze()
    low = data['Low'].squeeze()
    volume = data['Volume'].squeeze()
    close = close.dropna()
    if len(close) < 55:
        return None

    williams = calc_williams_r(high, low, close)
    bb_width = calc_bollinger_width(close)
    rsi = calc_rsi(close)
    sma50 = close.rolling(50).mean()
    atr = calc_atr(high, low, close)

    curr_wr = williams.iloc[-1]
    curr_bb_width = bb_width.iloc[-1]
    curr_rsi = rsi.iloc[-1]
    price = close.iloc[-1]
    curr_sma50 = sma50.iloc[-1]
    curr_atr = atr.iloc[-1]

    if np.isnan(curr_wr) or np.isnan(curr_bb_width) or np.isnan(price) or np.isnan(curr_sma50):
        return None

    dist_sma50 = (price / curr_sma50 - 1) * 100

    # BB width minimo de 50 dias
    if len(bb_width) < 50:
        return None
    bb_width_min = bb_width.iloc[-50:].min()
    if np.isnan(bb_width_min):
        return None

    # Filtros Señal B
    if curr_wr >= V6_WILLIAMS_MAX:
        return None
    if curr_bb_width > bb_width_min * V6_BB_SQUEEZE_MULT:
        return None
    if dist_sma50 > V6_B_SMA_DIST_MAX:
        return None

    stop_loss = price - 2 * curr_atr
    take_profit = price * 1.03
    risk_pct = (1 - stop_loss / price) * 100

    squeeze_pct = (curr_bb_width / bb_width_min - 1) * 100

    return {
        'Ticker': ticker,
        'Signal': 'B (W+Sq)',
        'Precio': round(float(price), 2),
        'RSI': round(float(curr_rsi), 1),
        'RSI Dir': '',
        'vs SMA50': f"{dist_sma50:.1f}%",
        'Vol': '',
        'Score': '',
        'Stop': f"${stop_loss:.2f}",
        'Target': f"${take_profit:.2f}",
        'Riesgo': f"{risk_pct:.1f}%",
        'Williams': f"{curr_wr:.1f}",
        'BB Squeeze': f"{squeeze_pct:+.0f}%",
        '_score': abs(curr_wr),  # Para sorting
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
    print(f"INVERTIR V6.0 — Dual-Signal Scanner — {hoy_str} ({dia_nombre})")
    print(f"Señal A (V5): RSI<{V6_RSI_MAX} + SMA<{V6_SMA_DIST_MAX}% + Score>{V6_SCORE_MIN}")
    print(f"Señal B (nueva): Williams<{V6_WILLIAMS_MAX} + BB Squeeze + SMA<{V6_B_SMA_DIST_MAX}%")
    print(f"Universo: {n_tickers} activos (sin LatAm) | Hold: {V6_HOLDING_DAYS}d")
    print(f"Escaneando...\n")

    # Download
    data_all = yf.download(tickers, period="6mo", progress=False, threads=True)

    # ── STEP 1: Regime ──
    print("=" * 80)
    print("  PASO 1: REGIMEN DEL MERCADO (SPY)")
    print("=" * 80)

    try:
        spy_data = data_all.xs('SPY', level=1, axis=1)
    except Exception:
        spy_data = data_all

    is_safe, regime = check_regime(spy_data)

    if isinstance(regime, dict):
        sma_status = "SOBRE SMA50" if regime['above_sma'] else "BAJO SMA50"
        vol_status = "BAJA" if regime['low_vol'] else "ALTA"
        regime_status = "SEGURO -- Operar" if is_safe else "PELIGRO -- No operar"

        print(f"  SPY:         ${regime['spy_price']}  ({regime['spy_dist']} vs SMA50)")
        print(f"  SMA50:       ${regime['spy_sma50']}  -> {sma_status}")
        print(f"  Volatilidad: {regime['spy_vol20d']}  -> {vol_status}")
        print(f"  Regimen:     {regime_status}")

    if not is_safe:
        reason = 'SPY bajo SMA50' if isinstance(regime, dict) and not regime['above_sma'] else 'Volatilidad alta'
        print(f"""
  {'=' * 68}
  MERCADO NO SEGURO PARA MEAN REVERSION.
  Razon: {reason}
  RECOMENDACION: No operar. Esperar estabilidad.
  {'=' * 68}
  (Mostrando senales como REFERENCIA -- NO operar)
""")

    # ── STEP 2: Scan (ambas señales) ──
    results = []

    for ticker in tickers:
        if ticker == 'SPY':
            continue
        try:
            df = data_all.xs(ticker, level=1, axis=1)

            # Señal A (V5)
            sig_a = signal_a_v5(ticker, df)
            if sig_a:
                results.append(sig_a)
                continue  # Si pasa A, no necesita B (evitar duplicados)

            # Señal B (Williams + Squeeze)
            sig_b = signal_b_williams_squeeze(ticker, df)
            if sig_b:
                results.append(sig_b)
        except Exception:
            pass

    # ── STEP 3: Display ──
    print("=" * 80)
    print("  PASO 2: SENALES V6 (DUAL-SIGNAL)")
    print("=" * 80)

    if results:
        results.sort(key=lambda x: x['_score'], reverse=True)
        display_cols = ['Ticker', 'Signal', 'Precio', 'RSI', 'vs SMA50',
                       'Williams', 'BB Squeeze', 'Stop', 'Target', 'Riesgo']
        df_res = pd.DataFrame(results)[display_cols]

        status = "" if is_safe else " [SOLO REFERENCIA - REGIMEN PELIGROSO]"
        count_a = sum(1 for r in results if 'A' in r['Signal'])
        count_b = sum(1 for r in results if 'B' in r['Signal'])
        print(f"  {len(results)} senales V6: {count_a} tipo A (V5) + {count_b} tipo B (W+Sq){status}\n")
        print(df_res.to_string(index=False))
    else:
        print(f"  Sin senales V6 hoy.")
        print(f"  V6 genera ~24 trades en 18 meses (~1 cada 3 semanas).")
        print(f"  Esto es normal -- calidad sobre cantidad.")

    # ── STEP 4: Action plan ──
    print(f"\n{'=' * 80}")
    print("  PASO 3: PLAN DE ACCION V6")
    print("=" * 80)

    if is_safe and results:
        top = results[:3]
        print(f"""
  REGIMEN SEGURO + {len(results)} SENALES V6 = OPERAR

  Top {len(top)} oportunidades (max 3 posiciones):
""")
        for i, s in enumerate(top, 1):
            print(f"  {i}. {s['Ticker']:<6} @ ${s['Precio']}  [{s['Signal']}]")
            if 'A' in s['Signal']:
                print(f"     RSI: {s['RSI']} | {s['vs SMA50']} bajo SMA50 | Score: {s['Score']}")
            else:
                print(f"     Williams: {s['Williams']} | BB Squeeze: {s['BB Squeeze']} | {s['vs SMA50']} bajo SMA50")
            print(f"     Stop: {s['Stop']} ({s['Riesgo']} riesgo) | Target: {s['Target']}")
            print()

        print(f"""  REGLAS V6:
  - Comprar al OPEN del dia siguiente
  - Posicion: max 10% del portfolio por trade
  - Stop loss: precio de 'Stop' -- vender SIN pensar si lo toca
  - Take profit: vender 50% si sube 3% en primeros 3 dias
  - Holding: {V6_HOLDING_DAYS} dias habiles, despues cerrar
  - ANTI-KNIFE: no comprar mismo ticker en {V6_ANTIKNIFE_DAYS} dias
  - NUNCA promediar para abajo

  BACKTESTED (deep_analysis_williams_squeeze.py):
  Union (V6): 24 trades, WR 58%, Sharpe 7.71, MDD -4.7%
  Walk-Forward: 100% positivas (5/5), Avg Sharpe 12.10
  Monte Carlo: P(Sharpe>0)=99.9%, Worst 1% Sharpe=2.19
""")
    elif is_safe and not results:
        print(f"""
  REGIMEN SEGURO pero SIN SENALES V6.
  V6 genera ~24 trades en 18 meses (~1 cada 3 semanas).
  No forzar trades. Revisar manana.
""")
    else:
        print(f"""
  REGIMEN PELIGROSO -- NO OPERAR.
  Mantener efectivo. Esperar estabilidad.
""")

    # Summary
    if is_safe and results:
        decision = "OPERAR"
    elif is_safe:
        decision = "ESPERAR (sin senales V6)"
    else:
        decision = "NO OPERAR (regimen peligroso)"

    print(f"  >>> DECISION: {decision} <<<")
    print(f"  Proximo escaneo: manana al cierre del mercado")
    print(f"  Ejecutar: python SCANNER/invertir_v6.py")
    print(f"  (V5 como fallback: python SCANNER/invertir_v5.py)")


if __name__ == '__main__':
    main()
