#!/usr/bin/env python3
"""
INVERTIR TITAN v1.0
===================
Evolucion de INVERTIR_V2 + insights de V37_SQUEEZE.

Basado en analisis de 104 trades historicos que revelaron:

1. RSI(14) < 27 es mejor que < 30 (elimina senales debiles)
2. MACD hist girando UP es la confirmacion clave (no el RSI)
3. Volumen BAJO (< 1.2x promedio) = mejor rebote que vol alto
4. >5% debajo SMA50 obligatorio (< 5% tiene 0% WR historico)
5. Holding 10 dias >>> 5 dias (69% WR vs 62%)
6. De V37: close_strength alta + vol_zscore = timing de entrada

MEJORAS vs INVERTIR_V2:
- RSI threshold mas estricto (27 vs 30)
- Filtro de volumen maximo (elimina ventas institucionales)
- Filtro SMA50 obligatorio (> 5% debajo)
- Score incorpora close_strength de V37 (microestructura)
- Horizonte optimo: 10 dias (no 5)
- ATR stop loss dinamico
"""

import yfinance as yf
import pandas as pd
import numpy as np
import warnings

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════════════════════
#  UNIVERSO DE ACTIVOS
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


# ═══════════════════════════════════════════════════════════════════════════════
#  INDICADORES TECNICOS
# ═══════════════════════════════════════════════════════════════════════════════

def calc_rsi(close, period=14):
    """RSI clasico con EMA."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period-1, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - 100 / (1 + rs)


def calc_macd(close, fast=12, slow=26, signal=9):
    """MACD clasico."""
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    macd = ema_f - ema_s
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return macd, sig, hist


def calc_atr(high, low, close, period=14):
    """Average True Range."""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ═══════════════════════════════════════════════════════════════════════════════
#  LOGICA DE DETECCION — INVERTIR TITAN
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_ticker(ticker, data):
    """
    Analiza un activo y devuelve senal si pasa TODOS los filtros.

    Filtros (cada uno respaldado por datos de 104 trades historicos):

    F1: RSI(14) < 27         — Solo sobreventa significativa (WR 60-62%)
    F2: MACD hist > prev     — Momentum frenando (confirmacion clave)
    F3: > 5% debajo SMA50    — Goma estirada (0% WR si < 5%)
    F4: Volumen < 1.2x avg   — Sin presion institucional (68% WR vs 0%)
    F5: close_strength > 0.3  — De V37: cierre no en minimo del dia
    """
    close = data['Close'].squeeze()
    high = data['High'].squeeze()
    low = data['Low'].squeeze()
    open_ = data['Open'].squeeze()
    volume = data['Volume'].squeeze()

    if len(close) < 55:
        return None

    # --- Indicadores ---
    rsi = calc_rsi(close)
    _, _, macd_hist = calc_macd(close)
    sma50 = close.rolling(50).mean()
    atr = calc_atr(high, low, close)
    vol_avg_20 = volume.rolling(20).mean()

    # Valores actuales
    curr_rsi = rsi.iloc[-1]
    curr_hist = macd_hist.iloc[-1]
    prev_hist = macd_hist.iloc[-2]
    curr_price = close.iloc[-1]
    curr_sma50 = sma50.iloc[-1]
    curr_atr = atr.iloc[-1]
    curr_vol = volume.iloc[-1]
    avg_vol = vol_avg_20.iloc[-1]

    # Close strength (de V37): donde cerro dentro del rango del dia
    day_range = high.iloc[-1] - low.iloc[-1]
    close_strength = (close.iloc[-1] - low.iloc[-1]) / (day_range + 1e-10)

    # Distancia a SMA50
    dist_sma50 = (curr_price / curr_sma50 - 1) * 100

    # Volume ratio
    vol_ratio = curr_vol / (avg_vol + 1e-10)

    # MACD acceleration
    macd_accel = curr_hist - prev_hist

    # --- FILTROS ---

    # F1: RSI < 27 (estricto — elimina senales RSI 27-30 que tienen solo +0.06% avg)
    if curr_rsi >= 27:
        return None

    # F2: MACD histograma girando hacia arriba
    if curr_hist <= prev_hist:
        return None

    # F3: > 5% debajo de SMA50 (bucket "slightly below" tiene 0% WR)
    if dist_sma50 > -5:
        return None

    # F4: Volumen no excesivo (< 1.2x promedio)
    # Vol > 2x tuvo 0% WR, vol > 1.2x apenas breakeven
    if vol_ratio > 1.2:
        return None

    # F5: Close strength > 0.3 (insight de V37 — no cerro en el minimo)
    # Esto filtra dias donde la caida fue sin ningun rebote intradiario
    if close_strength < 0.3:
        return None

    # --- SCORING ---
    # Componentes (cada uno contribuye segun su poder predictivo demostrado)

    # RSI depth: mas bajo = mas estirado = mejor rebote
    # RSI 15-22 tuvo +1.20% avg, RSI 22-27 tuvo +1.36% avg
    rsi_score = max(0, min(40, (27 - curr_rsi) / 27 * 40))

    # SMA50 distance: mas estirado = mas potencial
    # 5-10% below: 69% WR, >10% below: 61% WR (diminishing returns)
    stretch = abs(dist_sma50)
    stretch_score = min(30, stretch * 2)  # max 30 pts at 15%+ below

    # MACD acceleration: giro mas fuerte = confirmacion mas solida
    macd_score = min(15, macd_accel * 500)  # normalized

    # Close strength (from V37): cerro alto en el rango = presion compradora
    cs_score = close_strength * 15  # max 15 pts

    total_score = rsi_score + stretch_score + macd_score + cs_score
    total_score = max(0, min(100, total_score))

    # --- STOP LOSS (2x ATR) ---
    stop_loss = curr_price - 2 * curr_atr
    stop_pct = (1 - stop_loss / curr_price) * 100

    # --- TAKE PROFIT (3% — optimo segun backtests) ---
    take_profit = curr_price * 1.03

    return {
        'Ticker': ticker,
        'Precio': round(curr_price, 2),
        'RSI': round(curr_rsi, 1),
        'vs SMA50': f"{dist_sma50:.1f}%",
        'Vol': f"{vol_ratio:.1f}x",
        'CloseStr': f"{close_strength:.0%}",
        'MACD': 'GIRANDO' if macd_accel > 0 else '-',
        'Score': round(total_score),
        'Stop': f"${stop_loss:.2f}",
        'Target': f"${take_profit:.2f}",
        'Riesgo': f"{stop_pct:.1f}%",
        # Raw values for sorting
        '_score': total_score,
        '_rsi': curr_rsi,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"INVERTIR TITAN v1.0 — Escaneando {len(tickers)} activos...\n")

    # Download all data
    data_all = yf.download(tickers, period="6mo", progress=False, threads=True)

    results = []
    for ticker in tickers:
        try:
            if len(tickers) > 1:
                df = data_all.xs(ticker, level=1, axis=1)
            else:
                df = data_all
            if len(df) < 55:
                continue
            signal = analyze_ticker(ticker, df)
            if signal:
                results.append(signal)
        except Exception:
            pass

    if results:
        # Sort by score descending
        results.sort(key=lambda x: x['_score'], reverse=True)

        # Display columns (remove internal ones)
        display_cols = ['Ticker', 'Precio', 'RSI', 'vs SMA50', 'Vol',
                       'CloseStr', 'MACD', 'Score', 'Stop', 'Target', 'Riesgo']

        df_res = pd.DataFrame(results)[display_cols]

        print("=" * 95)
        print("  SENALES INVERTIR TITAN — Sobreventa + Microestructura Confirmada")
        print("  Filtros: RSI<27 + MACD giro + >5% bajo SMA50 + vol<1.2x + close_strength>30%")
        print("=" * 95)
        print(df_res.to_string(index=False))
        print("=" * 95)
        print(f"\n  Senales: {len(results)} de {len(tickers)} activos ({len(results)/len(tickers)*100:.1f}% selectividad)")

        print(f"""
  COMO OPERAR:
  1. Comprar al open del dia siguiente
  2. Stop loss en columna 'Stop' (si toca, salir sin pensar)
  3. Target: +3% parcial si llega rapido (1-3 dias)
  4. Horizonte: mantener hasta 10 dias habiles max
  5. Si no toca stop ni target en 10 dias, cerrar posicion

  FUNDAMENTO:
  - RSI < 27 = sobreventa severa (historico: 61% WR a 5d, 69% WR a 10d)
  - MACD girando = el momentum bajista frena
  - >5% bajo SMA50 = goma estirada (mean reversion)
  - Volumen bajo = caida sin conviccion institucional
  - Close strength = el precio no cerro en el minimo (compradores entrando)
""")
    else:
        print("  Sin senales hoy. El mercado no presenta oportunidades claras de sobreventa.")
        print("  Esto es BUENO — mejor no operar que forzar trades malos.")

    print(f"  Activos escaneados: {len(tickers)}")


if __name__ == '__main__':
    main()
