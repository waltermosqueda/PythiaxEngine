#!/usr/bin/env python3
"""
INVERTIR V5.0 — Mean Reversion Scanner
=======================================

Evolucion:
  V1 (Original): RSI<30 + MACD up
  V2:            + SMA50 >5% + Vol<1.5x + Scoring
  Final:         V2 + SPY regime + anti-knife (Sharpe 4.85, 90 trades)
  V3:            Final + 7 filtros optimizados -> 0 trades (demasiado restrictivo)
  V4:            Final + 3 filtros que FUNCIONAN (Sharpe 14.15, 15 trades)
  V5 (esta):     V4 + 2 mejoras validadas por walk-forward

Cambios V5 vs V4 (validados en analisis_v5_candidates.py, 2026-04-05):
  1. Universo: Excluir LatAm (Sharpe -1.22 en Round 3, WR 47%)
     - Walk-forward: 100% ventanas positivas (2/2)
     - No agrega filtros, solo limpia universo
  2. Holding: 7 dias (antes 10d)
     - V4 a 7d: Sharpe 16.57 vs 14.15 a 10d, MDD -4.7% vs -7.6%
     - Convergencia 3 angulos: Tecnico OK, Riesgo OK, Simplicidad OK

Lo que se INVESTIGO y DESCARTO (con evidencia):
  - Vol<1.0x:        WF FAIL 33% — sobreajuste a 8 trades
  - Stoch 10-25:     WF PASS pero solo 1 ventana con trades — insuficiente
  - RelPerf<-20%:    WF FAIL 50% — no consistente out-of-sample
  - RSI slope:       WF FAIL 33% — confirmado sesion 13

Filtros (identicos a V4 — NO se agregaron filtros nuevos):
  1. RSI(14) < 25 — Wilder's smoothing
  2. SMA50 distancia < -10%
  3. Score compuesto > 30
  4. SPY regime: SPY > SMA50 y volatilidad 20d < 1%
  5. Anti-knife: no repetir ticker en 5 dias

Resultados esperados (basado en backtest C1 NoLatAm):
  Full Period (Sep24-Abr26): ~13 trades, WR ~77%, Sharpe ~13-17, MDD ~-5%

Uso: python SCANNER/invertir_v5.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════════════════════
#  PARAMETROS V5
# ═══════════════════════════════════════════════════════════════════════════════

V5_RSI_MAX = 25           # Igual que V4
V5_SMA_DIST_MAX = -10.0   # Igual que V4
V5_SCORE_MIN = 30         # Igual que V4
V5_VOL_MAX = 1.5          # Igual que V4
V5_HOLDING_DAYS = 7       # CAMBIO: 7d (antes 10d). Sharpe 16.57 vs 14.15, MDD -4.7% vs -7.6%
V5_ANTIKNIFE_DAYS = 5     # Igual que V4

# ═══════════════════════════════════════════════════════════════════════════════
#  UNIVERSO V5 — Sin LatAm (Sharpe -1.22 en Round 3)
# ═══════════════════════════════════════════════════════════════════════════════
#
#  LatAm excluidos: MELI, NU, BABA, VALE, PBR, GLOB, STNE, XP, SBS, ITUB,
#  BBD, BIOX, CAAP, ELPC, EMBJ, LND, PAC, SATL, SUZ, TIMB, UGP, VIV,
#  ARCO, ABEV, AMX, BSBR, SAN (LatAm-linked), SID, GGB, SCCO
#
#  Tambien se excluyen ADRs LatAm que estaban en el universo V4.

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
#  INDICADORES (RSI = Wilder's smoothing — OBLIGATORIO)
# ═══════════════════════════════════════════════════════════════════════════════

def calc_rsi(close, period=14):
    """RSI con Wilder's smoothing: ewm(com=13, adjust=False). NUNCA rolling."""
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
#  CHECK REGIME (SPY health) — igual que V4
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
#  SCAN INDIVIDUAL TICKER — V5 (mismos filtros que V4)
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_ticker_v5(ticker, data):
    """
    Logica V5 = logica V4 exacta.
    Los cambios son universo (sin LatAm) y holding (7d), no filtros.
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
    if vol_ratio > V5_VOL_MAX:
        return None

    # ── V4/V5 filters (identical) ──
    if curr_rsi >= V5_RSI_MAX:
        return None
    if dist_sma50 > V5_SMA_DIST_MAX:
        return None

    # ── Score ──
    rsi_score = max(0, min(40, (30 - curr_rsi) / 30 * 40))
    stretch = abs(dist_sma50)
    stretch_score = max(0, min(30, (stretch - 5) / 15 * 30))
    macd_score = max(0, min(20, macd_accel_norm * 5))
    vol_score = max(0, min(10, (1.5 - vol_ratio) / 1.5 * 10))
    total_score = rsi_score + stretch_score + macd_score + vol_score

    if total_score < V5_SCORE_MIN:
        return None

    stop_loss = price - 2 * curr_atr
    take_profit = price * 1.03
    risk_pct = (1 - stop_loss / price) * 100

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


def analyze_ticker_v4(ticker, data):
    """Check if ticker passes V4 filters (for near-miss / comparison)."""
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
        if curr_rsi < 25 and dist_sma50 <= -10:
            return {
                'rsi': curr_rsi, 'dist_sma50': dist_sma50,
                'vol_ratio': vol_ratio, 'price': price,
            }
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    hoy = datetime.now()
    hoy_str = hoy.strftime('%Y-%m-%d')
    dia_nombre = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes',
                  'Sabado', 'Domingo'][hoy.weekday()]

    n_tickers = len([t for t in tickers if t != 'SPY'])
    print(f"INVERTIR V5.0 — {hoy_str} ({dia_nombre})")
    print(f"Cambios vs V4: Sin LatAm ({n_tickers} activos) + Holding {V5_HOLDING_DAYS}d")
    print(f"Filtros: RSI<{V5_RSI_MAX} + SMA<{V5_SMA_DIST_MAX}% + Score>{V5_SCORE_MIN}")
    print(f"Escaneando...\n")

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
    results_v5 = []
    near_miss = []

    for ticker in tickers:
        if ticker == 'SPY':
            continue
        try:
            df = data_all.xs(ticker, level=1, axis=1)

            signal_v5 = analyze_ticker_v5(ticker, df)
            if signal_v5:
                results_v5.append(signal_v5)
            else:
                # Check if passes V4 filters but excluded from V5 universe
                signal_v4 = analyze_ticker_v4(ticker, df)
                if signal_v4:
                    near_miss.append({
                        'Ticker': ticker,
                        'Precio': round(float(signal_v4['price']), 2),
                        'RSI': round(float(signal_v4['rsi']), 1),
                        'vs SMA50': f"{signal_v4['dist_sma50']:.1f}%",
                        'Vol': f"{signal_v4['vol_ratio']:.2f}x",
                        'Nota': 'Pasa V4 filtros',
                    })
        except Exception:
            pass

    # ── STEP 3: Display V5 signals ───────────────────────────────────────
    print("=" * 80)
    print("  PASO 2: SENALES V5")
    print("=" * 80)

    if results_v5:
        results_v5.sort(key=lambda x: x['_score'], reverse=True)
        display_cols = ['Ticker', 'Precio', 'RSI', 'RSI Dir', 'vs SMA50',
                       'Vol', 'Score', 'Stop', 'Target', 'Riesgo']
        df_res = pd.DataFrame(results_v5)[display_cols]

        status = "" if is_safe else " [SOLO REFERENCIA - REGIMEN PELIGROSO]"
        print(f"  {len(results_v5)} senales V5 de {n_tickers} activos{status}\n")
        print(df_res.to_string(index=False))

        falling_count = sum(1 for s in results_v5 if s['RSI Dir'] == 'falling')
        if falling_count > 0:
            print(f"\n  * {falling_count} senales con RSI falling (historicamente mayor Sharpe)")
    else:
        print(f"  Sin senales V5 hoy.")
        print(f"  V5 es selectiva (~13 trades por periodo de 18 meses).")
        print(f"  Esto es normal -- calidad sobre cantidad.")

    # Show near misses
    if near_miss:
        print(f"\n{'=' * 80}")
        print(f"  NEAR MISS: {len(near_miss)} senales pasan filtros V4 pero no estan en universo V5")
        print("=" * 80)
        df_nm = pd.DataFrame(near_miss)
        print(df_nm.to_string(index=False))
        print("  (Estas senales NO se operan con V5 -- solo referencia)")

    # ── STEP 4: Action plan ──────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("  PASO 3: PLAN DE ACCION V5")
    print("=" * 80)

    if is_safe and results_v5:
        top = results_v5[:3]
        print(f"""
  REGIMEN SEGURO + {len(results_v5)} SENALES V5 = OPERAR

  Top {len(top)} oportunidades (max 3 posiciones):
""")
        for i, s in enumerate(top, 1):
            print(f"  {i}. {s['Ticker']:<6} @ ${s['Precio']}")
            print(f"     RSI: {s['RSI']} ({s['RSI Dir']}) | {s['vs SMA50']} bajo SMA50 | Score: {s['Score']}")
            print(f"     Vol: {s['Vol']} | Stop: {s['Stop']} ({s['Riesgo']} riesgo)")
            print(f"     Target: {s['Target']} (+3%)")
            print()

        print(f"""  REGLAS V5:
  - Comprar al OPEN del dia siguiente
  - Posicion: max 10% del portfolio por trade
  - Stop loss: precio de 'Stop' -- vender SIN pensar si lo toca
  - Take profit: vender 50% si sube 3% en primeros 3 dias
  - Holding: {V5_HOLDING_DAYS} dias habiles, despues cerrar
  - ANTI-KNIFE: no comprar mismo ticker en {V5_ANTIKNIFE_DAYS} dias
  - NUNCA promediar para abajo

  CAMBIOS V5 vs V4:
  - Universo: {n_tickers} activos (sin LatAm, antes ~230+)
  - Holding: {V5_HOLDING_DAYS} dias (antes 10d)
  - Filtros: IDENTICOS a V4 (RSI<25, SMA<-10%, Score>30)

  BACKTESTED (C1 NoLatAm, analisis_v5_candidates.py):
  - WR ~77% | Sharpe ~13-17 | MDD ~-5%
  - Walk-forward: 100% ventanas positivas
""")
    elif is_safe and not results_v5:
        nm_count = len(near_miss)
        print(f"""
  REGIMEN SEGURO pero SIN SENALES V5.
  V5 necesita RSI<{V5_RSI_MAX} + SMA<{V5_SMA_DIST_MAX}% + Score>{V5_SCORE_MIN}.
  Esto genera ~13 trades en 18 meses (~1 cada 5-6 semanas).
  {"Hay " + str(nm_count) + " senales V4 fuera del universo V5 (ver arriba)." if nm_count > 0 else ""}
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
    if is_safe and results_v5:
        decision = "OPERAR"
    elif is_safe:
        decision = "ESPERAR (sin senales V5)"
    else:
        decision = "NO OPERAR (regimen peligroso)"

    print(f"  >>> DECISION: {decision} <<<")
    print(f"  Proximo escaneo: manana al cierre del mercado")
    print(f"  Ejecutar: python SCANNER/invertir_v5.py")
    print(f"  (V4 disponible como fallback: python SCANNER/invertir_v4.py)")


if __name__ == '__main__':
    main()
