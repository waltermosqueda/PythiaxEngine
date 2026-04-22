#!/usr/bin/env python3
"""
INVERTIR V4.0 — Mean Reversion Scanner (V3-Revisada, validada Round 3)
======================================================================

Evolucion:
  V1 (Original): RSI<30 + MACD up
  V2:            + SMA50 >5% + Vol<1.5x + Scoring
  Final:         V2 + SPY regime + anti-knife (Sharpe 4.85, 90 trades)
  V3:            Final + 7 filtros optimizados -> 0 trades (demasiado restrictivo)
  V4 (esta):     Final + 3 filtros que FUNCIONAN (validados Round 3)

Filtros V4 sobre Final:
  1. RSI < 25 (antes 30)     -> WR sube de 64% a 80%
  2. SMA50 dist < -10% (antes -5%) -> Elimina rebotes debiles
  3. Score > 30              -> Filtra senales de baja calidad

Lo que NO se incluyo (evidencia en contra):
  - Vol<0.8x: WR PEOR que Vol 0.8-1.0x (sweet spot real)
  - Filtro dia: Mie/Jue inconsistente, Lunes resulto mejor en Round 3
  - Score techo: Scores altos (50-60, 60-80) tambien funcionan
  - MACD accel min: Reduce trades sin mejorar calidad

Resultados backtested (Mega Backtest Round 3, 2026-03-28):
  Full Period (Sep24-Mar26):
    V4:    15 trades, WR 80%, Avg 5.56%, Sharpe 14.15, MDD -7.6%
    Final: 90 trades, WR 64%, Avg 1.88%, Sharpe  4.85, MDD -33.6%

  Out-of-Sample (Sep24-Jun25):
    V4:     7 trades, WR 86%, Avg 7.18%, Sharpe 22.60, MDD  0.0%
    Final: 45 trades, WR 58%, Avg 0.79%, Sharpe  2.18, MDD -33.6%

  Walk-Forward: 7/8 ventanas positivas (Sharpe promedio test 10.42)
  Monte Carlo:  99.8% prob profit, 100% prob Sharpe>0, peor 1% MDD -19.8%

Holding: 10 dias habiles (15-20d tiene mayor Sharpe pero mayor MDD).

Uso: python invertir_v4.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════════════════════
#  PARAMETROS V4 (validados en Mega Backtest Round 3)
# ═══════════════════════════════════════════════════════════════════════════════

V4_RSI_MAX = 25           # Final usa 30. RSI<25 -> WR 80% vs 64%
V4_SMA_DIST_MAX = -10.0   # Final usa -5. SMA<-10% -> elimina rebotes debiles
V4_SCORE_MIN = 30         # Score minimo. Score<20 tiene WR 40%, Sharpe -4.4
V4_VOL_MAX = 1.5          # Se mantiene de Final (Vol<0.8x NO funciona)
V4_HOLDING_DAYS = 10      # 10d standard. 15-20d tiene mayor Sharpe pero mas MDD
V4_ANTIKNIFE_DAYS = 5     # No repetir ticker en 5 dias

# ═══════════════════════════════════════════════════════════════════════════════
#  UNIVERSO (260+ activos)
# ═══════════════════════════════════════════════════════════════════════════════

TICKERS_STR = """
AAPL, ADBE, ADI, AI, ALAB, AMAT, AMD, ARM, ASML, AVGO, BIDU, COIN, CRM, CRWV,
CSCO, DOCU, ETSY, GOOGL, IBM, INTC, IREN, LRCX, META, MRVL, MSFT, MSTR, MU,
NTES, NVDA, ORCL, PANW, PATH, PLTR, QCOM, RBLX, RGTI, ROKU, SAP, SE, SHOP,
SNAP, SNOW, SONY, SPOT, TEAM, TSM, TWLO, UBER, UPST, ZM, GLW, GRMN, HPQ, MSI,
SWKS, TXN, EA, ASTS, RKLB, ERIC, BB, AXP, BAC, BCS, BK, BKNG, BSBR,
C, GS, HOOD, HSBC, ING, JPM, LYG, MA, MUFG, NU, PYPL, SAN, SCHW, STNE, USB, V,
WFC, XP, PAGS, AIG, HDB, ABBV, ABT, AMGN, AZN, BIIB, BMY, CVS, DHR, GILD, GSK,
ISRG, JNJ, LLY, MDT, MRK, MRNA, NVS, PFE, TMO, UNH, BKR, BP, CVX, E, EQNR, HAL,
OXY, PBR, PSX, SHEL, SLB, TTE, VIST, XOM, AEM, B, BHP, CDE, FCX, GFI, GGB, HL,
HMY, KGC, LAC, MOS, MUX, NEM, NG, NUE, PAAS, RIO, SCCO, SID, VALE, AAP, ABEV,
ANF, ARCO, BABA, CL, COST, DEO, EBAY, HD, HSY, KMB, KO, MCD, MDLZ, MO, NKE,
ORLY, PEP, PG, PM, ROST, SBUX, SYY, TGT, TJX, UL, WMT, YELP, AVY, BA, CAT, DD, DE,
FDX, GE, HON, HWM, IFF, IP, LMT, MMM, PCAR, PBI, RTX, SNA, UNP, BBD, BIOX,
CAAP, ELPC, EMBJ, GLOB, ITUB, LND, MELI, PAC, SATL, SBS, SUZ, TIMB, UGP, VIV, F, GM,
HMC, HOG, NIO, RACE, STLA, TM, TSLA, AAL, ABNB, CAR, CCL, DAL, LVS, SPCE, TCOM, TRIP,
UAL, AMX, TMUS, VOD, VZ
"""

tickers = [t.strip() for t in TICKERS_STR.replace('\n', '').split(',') if t.strip()]
if 'SPY' not in tickers:
    tickers.append('SPY')


# ═══════════════════════════════════════════════════════════════════════════════
#  INDICADORES
# ═══════════════════════════════════════════════════════════════════════════════

def calc_rsi(close, period=14):
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
#  CHECK REGIME (SPY health) — igual que Final
# ═══════════════════════════════════════════════════════════════════════════════

def check_regime(spy_data):
    """
    Safe = SPY above SMA50 AND 20d volatility < 1.0%
    """
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
#  SCAN INDIVIDUAL TICKER — V4 (3 filtros validados sobre Final)
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_ticker_v4(ticker, data):
    """
    Logica V4:
      Base (igual que Final): RSI<30 + MACD up + >5% bajo SMA50 + Vol<1.5x
      V4 filtros adicionales:
        1. RSI < 25 (mas estricto)
        2. SMA50 dist < -10% (mas estricto)
        3. Score > 30
    Returns signal dict or None.
    """
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

    # Skip if any critical value is NaN
    if np.isnan(curr_rsi) or np.isnan(curr_sma50) or np.isnan(curr_atr) or np.isnan(price):
        return None

    dist_sma50 = (price / curr_sma50 - 1) * 100
    vol_ratio = volume.iloc[-1] / (vol_avg_20.iloc[-1] + 1e-10)
    macd_accel = curr_hist - prev_hist
    macd_accel_norm = macd_accel / (curr_atr * 0.01 + 1e-6)

    # ── Base filters (same as Final) ──
    if curr_rsi >= 30:
        return None
    if curr_hist <= prev_hist:
        return None
    if dist_sma50 > -5:
        return None
    if vol_ratio > V4_VOL_MAX:
        return None

    # ── V4 filter 1: RSI < 25 ──
    if curr_rsi >= V4_RSI_MAX:
        return None

    # ── V4 filter 2: SMA50 dist < -10% ──
    if dist_sma50 > V4_SMA_DIST_MAX:
        return None

    # ── Score (same formula as V2/Final) ──
    rsi_score = max(0, min(40, (30 - curr_rsi) / 30 * 40))
    stretch = abs(dist_sma50)
    stretch_score = max(0, min(30, (stretch - 5) / 15 * 30))
    macd_score = max(0, min(20, macd_accel_norm * 5))
    vol_score = max(0, min(10, (1.5 - vol_ratio) / 1.5 * 10))
    total_score = rsi_score + stretch_score + macd_score + vol_score

    # ── V4 filter 3: Score > 30 ──
    if total_score < V4_SCORE_MIN:
        return None

    stop_loss = price - 2 * curr_atr
    take_profit = price * 1.03
    risk_pct = (1 - stop_loss / price) * 100

    # RSI direction (info only, no filter — RSI falling has higher Sharpe)
    rsi_prev = rsi.iloc[-2] if len(rsi) > 1 else curr_rsi
    rsi_dir = "falling" if curr_rsi < rsi_prev else "rising"

    return {
        'Ticker': ticker,
        'Precio': round(float(price), 2),
        'RSI': round(float(curr_rsi), 1),
        'RSI Dir': rsi_dir,
        'vs SMA50': f"{dist_sma50:.1f}%",
        'Vol': f"{vol_ratio:.2f}x",
        'Score': round(float(total_score)),
        'Stop': f"${stop_loss:.2f}",
        'Target': f"${take_profit:.2f}",
        'Riesgo': f"{risk_pct:.1f}%",
        '_score': total_score,
    }


def analyze_ticker_final(ticker, data):
    """Check if ticker passes FINAL filters (for near-miss comparison)."""
    close = data['Close'].squeeze()
    high = data['High'].squeeze()
    low = data['Low'].squeeze()
    volume = data['Volume'].squeeze()

    if len(close) < 55:
        return None

    rsi = calc_rsi(close)
    _, _, macd_hist = calc_macd(close)
    sma50 = close.rolling(50).mean()
    vol_avg_20 = volume.rolling(20).mean()

    curr_rsi = rsi.iloc[-1]
    curr_hist = macd_hist.iloc[-1]
    prev_hist = macd_hist.iloc[-2] if len(macd_hist) > 1 else 0
    price = close.iloc[-1]
    curr_sma50 = sma50.iloc[-1]
    dist_sma50 = (price / curr_sma50 - 1) * 100
    vol_ratio = volume.iloc[-1] / (vol_avg_20.iloc[-1] + 1e-10)

    if curr_rsi < 30 and curr_hist > prev_hist and dist_sma50 <= -5 and vol_ratio < 1.5:
        return {
            'rsi': curr_rsi, 'dist_sma50': dist_sma50,
            'vol_ratio': vol_ratio, 'price': price,
        }
    return None


def _why_rejected_by_v4(rsi, dist_sma, score):
    """Explica por que una senal Final fue rechazada por V4."""
    reasons = []
    if rsi >= V4_RSI_MAX:
        reasons.append(f"RSI {rsi:.0f} >= {V4_RSI_MAX}")
    if dist_sma > V4_SMA_DIST_MAX:
        reasons.append(f"SMA {dist_sma:.0f}% > {V4_SMA_DIST_MAX}%")
    if score < V4_SCORE_MIN:
        reasons.append(f"Score {score:.0f} < {V4_SCORE_MIN}")
    return ", ".join(reasons) if reasons else "?"


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    hoy = datetime.now()
    hoy_str = hoy.strftime('%Y-%m-%d')
    dia_nombre = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes',
                  'Sabado', 'Domingo'][hoy.weekday()]

    print(f"INVERTIR V4.0 (V3-Revisada validada) - {hoy_str} ({dia_nombre})")
    print(f"Filtros: RSI<{V4_RSI_MAX} + SMA<{V4_SMA_DIST_MAX}% + Score>{V4_SCORE_MIN}")
    print(f"Escaneando {len(tickers)} activos...\n")

    # Download all data at once
    data_all = yf.download(tickers, period="6mo", progress=False, threads=True)

    # ── STEP 1: Check regime ─────────────────────────────────────────────
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
    else:
        print(f"  {regime}")

    if not is_safe:
        reason = 'SPY bajo SMA50' if isinstance(regime, dict) and not regime['above_sma'] else 'Volatilidad alta'
        print(f"""
  {'=' * 68}
  MERCADO NO SEGURO PARA MEAN REVERSION.
  Razon: {reason}
  Backtest mostro que en este regimen la estrategia pierde.
  RECOMENDACION: No operar. Esperar estabilidad.
  {'=' * 68}
  (Mostrando senales como REFERENCIA -- NO operar)
""")

    # ── STEP 2: Scan tickers ─────────────────────────────────────────────
    results_v4 = []
    near_miss = []

    for ticker in tickers:
        if ticker == 'SPY':
            continue
        try:
            df = data_all.xs(ticker, level=1, axis=1)

            signal_v4 = analyze_ticker_v4(ticker, df)
            if signal_v4:
                results_v4.append(signal_v4)
            else:
                # Check if passes Final but not V4 (near miss)
                signal_final = analyze_ticker_final(ticker, df)
                if signal_final:
                    r = signal_final['rsi']
                    d = signal_final['dist_sma50']
                    # Compute quick score for rejection reason
                    rsi_sc = max(0, min(40, (30 - r) / 30 * 40))
                    sma_sc = max(0, min(30, (abs(d) - 5) / 15 * 30))
                    sc = rsi_sc + sma_sc  # approximate
                    near_miss.append({
                        'Ticker': ticker,
                        'Precio': round(float(signal_final['price']), 2),
                        'RSI': round(float(r), 1),
                        'vs SMA50': f"{d:.1f}%",
                        'Vol': f"{signal_final['vol_ratio']:.2f}x",
                        'Razon V4': _why_rejected_by_v4(r, d, sc),
                    })
        except Exception:
            pass

    # ── STEP 3: Display V4 signals ───────────────────────────────────────
    print("=" * 80)
    print("  PASO 2: SENALES V4 (FILTROS VALIDADOS)")
    print("=" * 80)

    if results_v4:
        results_v4.sort(key=lambda x: x['_score'], reverse=True)
        display_cols = ['Ticker', 'Precio', 'RSI', 'RSI Dir', 'vs SMA50',
                       'Vol', 'Score', 'Stop', 'Target', 'Riesgo']
        df_res = pd.DataFrame(results_v4)[display_cols]

        status = "" if is_safe else " [SOLO REFERENCIA - REGIMEN PELIGROSO]"
        print(f"  {len(results_v4)} senales V4 de {len(tickers)} activos{status}\n")
        print(df_res.to_string(index=False))

        # Extra info
        falling_count = sum(1 for s in results_v4 if s['RSI Dir'] == 'falling')
        if falling_count > 0:
            print(f"\n  * {falling_count} senales con RSI falling (historicamente Sharpe 5.81 vs 4.08 rising)")
    else:
        print(f"  Sin senales V4 hoy.")
        print(f"  V4 es selectiva (~15 trades por periodo de 18 meses).")
        print(f"  Esto es normal -- calidad sobre cantidad.")

    # Show near misses
    if near_miss:
        print(f"\n{'=' * 80}")
        print(f"  NEAR MISS: {len(near_miss)} senales pasan FINAL pero NO V4")
        print("=" * 80)
        df_nm = pd.DataFrame(near_miss)
        print(df_nm.to_string(index=False))
        print("  (Estas senales NO se operan con V4 -- solo referencia)")

    # ── STEP 4: Action plan ──────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("  PASO 3: PLAN DE ACCION V4")
    print("=" * 80)

    if is_safe and results_v4:
        top = results_v4[:3]  # max 3 positions
        print(f"""
  REGIMEN SEGURO + {len(results_v4)} SENALES V4 = OPERAR

  Top {len(top)} oportunidades (max 3 posiciones):
""")
        for i, s in enumerate(top, 1):
            print(f"  {i}. {s['Ticker']:<6} @ ${s['Precio']}")
            print(f"     RSI: {s['RSI']} ({s['RSI Dir']}) | {s['vs SMA50']} bajo SMA50 | Score: {s['Score']}")
            print(f"     Vol: {s['Vol']} | Stop: {s['Stop']} ({s['Riesgo']} riesgo)")
            print(f"     Target: {s['Target']} (+3%)")
            print()

        print(f"""  REGLAS V4:
  - Comprar al OPEN del dia siguiente
  - Posicion: max 10% del portfolio por trade
  - Stop loss: precio de 'Stop' -- vender SIN pensar si lo toca
  - Take profit: vender 50% si sube 3% en primeros 3 dias
  - Holding: {V4_HOLDING_DAYS} dias habiles, despues cerrar
  - ANTI-KNIFE: no comprar mismo ticker en {V4_ANTIKNIFE_DAYS} dias
  - NUNCA promediar para abajo

  ESTADISTICAS V4 (backtest Sep24-Mar26):
  - 15 trades, 80% win rate, Sharpe 14.15
  - Avg win: +8.16%, Avg loss: -4.85%
  - Max drawdown: -7.6% (vs -33.6% de Final)
  - 86% de trades tocan +3% en algun momento
""")
    elif is_safe and not results_v4:
        nm_count = len(near_miss)
        print(f"""
  REGIMEN SEGURO pero SIN SENALES V4.
  V4 necesita RSI<{V4_RSI_MAX} + SMA<{V4_SMA_DIST_MAX}% + Score>{V4_SCORE_MIN}.
  Esto genera ~15 trades en 18 meses (1 cada ~5 semanas).
  {"Hay " + str(nm_count) + " senales de Final que NO pasan V4 (ver arriba)." if nm_count > 0 else ""}
  No forzar trades. Revisar manana.
""")
    else:
        print(f"""
  REGIMEN PELIGROSO -- NO OPERAR.
  Mantener efectivo. Esperar a que el mercado se estabilice.
  Verificar diariamente hasta que SPY vuelva sobre SMA50
  y la volatilidad baje de 1.0%.
""")

    # ── Summary ──────────────────────────────────────────────────────────
    if is_safe and results_v4:
        decision = "OPERAR"
    elif is_safe:
        decision = "ESPERAR (sin senales V4)"
    else:
        decision = "NO OPERAR (regimen peligroso)"

    print(f"  >>> DECISION: {decision} <<<")
    print(f"  Proximo escaneo: manana al cierre del mercado")
    print(f"  Ejecutar: python invertir_v4.py")
    print(f"  (Final disponible como fallback: python invertir_final.py)")


if __name__ == '__main__':
    main()
