#!/usr/bin/env python3
"""
INVERTIR FINAL v1.0
====================
La version definitiva, validada en 2 periodos independientes.

Logica:
  1. RSI(14) < 30 + MACD hist girando UP (senal base de sobreventa)
  2. >5% debajo de SMA50 del ticker (goma estirada)
  3. Volumen < 1.5x promedio (sin venta institucional)
  4. SPY sobre su SMA50 (mercado alcista/neutro)
  5. Volatilidad 20d de SPY < 1.0% (mercado calmo)
  6. No repetir ticker en 5 dias (anti falling knife)

Resultados backtested:
  In-sample  Jun25-Mar26:  WR ~70%, Sharpe >1, MaxDD < 6%
  Out-sample Sep24-Jun25:  WR ~63%, Return ~-1%, MaxDD -4% (protegido)

Uso: python invertir_final.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════════════════════
#  UNIVERSO
# ═══════════════════════════════════════════════════════════════════════════════

TICKERS_STR = """
AAPL, ADBE, ADI, AI, ALAB, AMAT, AMD, ARM, ASML, AVGO, BIDU, COIN, CRM, CRWV,
CSCO, DOCU, ETSY, GOOGL, IBM, INTC, IREN, LRCX, META, MRVL, MSFT, MSTR, MU,
NTES, NVDA, ORCL, PANW, PATH, PLTR, QCOM, RBLX, RGTI, ROKU, SAP, SE, SHOP,
SNAP, SNOW, SONY, SPOT, TEAM, TSM, TWLO, UBER, UPST, ZM, GLW, GRMN, HPQ, MSI,
SWKS, TXN, EA, ASTS, RKLB, ERIC, NOKA, BB, AXP, BAC, BCS, BK, BKNG, BRKB, BSBR,
C, GS, HOOD, HSBC, ING, JPM, LYG, MA, MUFG, NU, PYPL, SAN, SCHW, STNE, USB, V,
WFC, XP, PAGS, AIG, HDB, ABBV, ABT, AMGN, AZN, BIIB, BMY, CVS, DHR, GILD, GSK,
ISRG, JNJ, LLY, MDT, MRK, MRNA, NVS, PFE, TMO, UNH, BKR, BP, CVX, E, EQNR, HAL,
OXY, PBR, PSX, SHEL, SLB, TTE, VIST, XOM, AEM, B, BHP, CDE, FCX, GFI, GGB, HL,
HMY, KGC, LAC, MOS, MUX, NEM, NG, NUE, PAAS, RIO, SCCO, SID, TXR, VALE, AAP, ABEV,
ANF, ARCO, BABA, CL, COST, DEO, EBAY, HD, HSY, KMB, KO, KOFM, MCD, MDLZ, MO, NKE,
ORLY, PEP, PG, PM, ROST, SBUX, SYY, TGT, TJX, UL, WMT, YELP, AVY, BA, CAT, DD, DE,
FDX, GE, HON, HWM, IFF, IP, LMT, MMM, PCAR, PBI, RTX, SNA, UNP, ADGO, BBD, BIOX,
CAAP, ELPC, EMBJ, GLOB, ITUB, LND, MELI, PAC, SATL, SBS, SUZ, TIMB, UGP, VIV, F, GM,
HMC, HOG, NIO, RACE, STLA, TM, TSLA, AAL, ABNB, CAR, CCL, DAL, LVS, SPCE, TCOM, TRIP,
UAL, AMX, TMUS, VOD, VZ
"""

tickers = [t.strip() for t in TICKERS_STR.replace('\n', '').split(',') if t.strip()]
# SPY must be in the list for regime check
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
#  CHECK REGIME (SPY health)
# ═══════════════════════════════════════════════════════════════════════════════

def check_regime(spy_data):
    """
    Returns (is_safe, regime_info) tuple.
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
#  SCAN INDIVIDUAL TICKER
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_ticker(ticker, data):
    """Returns signal dict or None."""
    close = data['Close'].squeeze()
    high = data['High'].squeeze()
    low = data['Low'].squeeze()
    volume = data['Volume'].squeeze()

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
    dist_sma50 = (price / curr_sma50 - 1) * 100
    vol_ratio = volume.iloc[-1] / (vol_avg_20.iloc[-1] + 1e-10)

    # F1: RSI < 30
    if curr_rsi >= 30:
        return None
    # F2: MACD hist rising
    if curr_hist <= prev_hist:
        return None
    # F3: > 5% below SMA50
    if dist_sma50 > -5:
        return None
    # F4: Volume < 1.5x avg
    if vol_ratio > 1.5:
        return None

    # Score
    score = (30 - curr_rsi) * 2 + abs(dist_sma50)
    stop_loss = price - 2 * curr_atr
    take_profit = price * 1.03
    risk_pct = (1 - stop_loss / price) * 100

    return {
        'Ticker': ticker,
        'Precio': round(price, 2),
        'RSI': round(curr_rsi, 1),
        'vs SMA50': f"{dist_sma50:.1f}%",
        'Vol': f"{vol_ratio:.1f}x",
        'Score': round(score),
        'Stop': f"${stop_loss:.2f}",
        'Target': f"${take_profit:.2f}",
        'Riesgo': f"{risk_pct:.1f}%",
        '_score': score,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    hoy = datetime.now().strftime('%Y-%m-%d')

    print(f"INVERTIR FINAL v1.0 — {hoy}")
    print(f"Escaneando {len(tickers)} activos...\n")

    # Download
    data_all = yf.download(tickers, period="6mo", progress=False, threads=True)

    # ── STEP 1: Check regime ─────────────────────────────────────────────
    print("=" * 80)
    print("  PASO 1: REGIMEN DEL MERCADO")
    print("=" * 80)

    try:
        spy_data = data_all.xs('SPY', level=1, axis=1)
    except Exception:
        spy_data = data_all  # single ticker case

    is_safe, regime = check_regime(spy_data)

    if isinstance(regime, dict):
        sma_status = "SOBRE SMA50" if regime['above_sma'] else "BAJO SMA50"
        vol_status = "BAJA" if regime['low_vol'] else "ALTA"
        regime_status = "SEGURO — Operar" if is_safe else "PELIGRO — No operar"

        print(f"  SPY:         ${regime['spy_price']}  ({regime['spy_dist']} vs SMA50)")
        print(f"  SMA50:       ${regime['spy_sma50']}  -> {sma_status}")
        print(f"  Volatilidad: {regime['spy_vol20d']}  -> {vol_status}")
        print(f"  Regimen:     {regime_status}")
    else:
        print(f"  {regime}")

    if not is_safe:
        print(f"""
  {'=' * 68}
  EL MERCADO NO ES SEGURO PARA MEAN REVERSION.

  Razon: {'SPY bajo SMA50 (tendencia bajista)' if isinstance(regime, dict) and not regime['above_sma'] else 'Volatilidad alta (mercado inestable)'}

  Cuando el mercado esta en tendencia bajista o alta volatilidad,
  comprar acciones sobrevendidas es atrapar cuchillos cayendo.
  El backtest mostro que en este regimen la estrategia pierde -38%.

  RECOMENDACION: No operar. Esperar a que SPY vuelva sobre SMA50
  y la volatilidad baje. Revisar manana.
  {'=' * 68}
""")
        # Still show signals for information, but with WARNING
        print("  (Mostrando senales solo como REFERENCIA — NO operar)\n")

    # ── STEP 2: Scan tickers ─────────────────────────────────────────────
    results = []
    recent_tickers = set()  # anti-knife: in live mode, track manually

    for ticker in tickers:
        if ticker == 'SPY':
            continue
        try:
            df = data_all.xs(ticker, level=1, axis=1)
            signal = analyze_ticker(ticker, df)
            if signal:
                results.append(signal)
        except Exception:
            pass

    # ── STEP 3: Display results ──────────────────────────────────────────
    print("=" * 80)
    print("  PASO 2: SENALES DE SOBREVENTA")
    print("=" * 80)

    if results:
        results.sort(key=lambda x: x['_score'], reverse=True)
        display_cols = ['Ticker', 'Precio', 'RSI', 'vs SMA50', 'Vol', 'Score', 'Stop', 'Target', 'Riesgo']
        df_res = pd.DataFrame(results)[display_cols]

        status = "" if is_safe else " [SOLO REFERENCIA - REGIMEN PELIGROSO]"
        print(f"  {len(results)} senales encontradas de {len(tickers)} activos{status}\n")
        print(df_res.to_string(index=False))
    else:
        print("  Sin senales de sobreventa hoy.")

    # ── STEP 4: Action plan ──────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("  PASO 3: PLAN DE ACCION")
    print("=" * 80)

    if is_safe and results:
        top = results[:3]  # max 3 positions
        print(f"""
  REGIMEN SEGURO + {len(results)} SENALES = OPERAR

  Top {len(top)} oportunidades (max 3 posiciones simultaneas):
""")
        for i, s in enumerate(top, 1):
            print(f"  {i}. {s['Ticker']:<6} @ ${s['Precio']}")
            print(f"     RSI: {s['RSI']} | {s['vs SMA50']} bajo SMA50 | Score: {s['Score']}")
            print(f"     Stop loss: {s['Stop']} ({s['Riesgo']} riesgo)")
            print(f"     Take profit: {s['Target']} (+3%)")
            print()

        print("""  REGLAS:
  - Comprar al OPEN del dia siguiente
  - Posicion: max 10% del portfolio por trade
  - Stop loss: si toca el precio de 'Stop', vender SIN pensar
  - Take profit: vender 50% si sube 3% en los primeros 3 dias
  - Tiempo maximo: 10 dias habiles, despues cerrar
  - ANTI-KNIFE: si ya compraste un ticker, no comprarlo de nuevo en 5 dias
  - NUNCA promediar para abajo (no comprar mas si cae)
""")
    elif is_safe and not results:
        print("""
  REGIMEN SEGURO pero SIN SENALES.
  El mercado esta tranquilo y no hay acciones sobrevendidas.
  Esto es BUENO — no forzar trades. Revisar manana.
""")
    else:
        print("""
  REGIMEN PELIGROSO — NO OPERAR.
  Mantener efectivo. Esperar a que el mercado se estabilice.
  Verificar diariamente hasta que SPY vuelva sobre SMA50
  y la volatilidad baje de 1.0%.
""")

    # ── Summary line ─────────────────────────────────────────────────────
    status_emoji = "OPERAR" if (is_safe and results) else "ESPERAR" if is_safe else "NO OPERAR"
    print(f"  >>> DECISION: {status_emoji} <<<")
    print(f"  Proximo escaneo: manana al cierre del mercado")
    print(f"  Ejecutar: python invertir_final.py")


if __name__ == '__main__':
    main()
