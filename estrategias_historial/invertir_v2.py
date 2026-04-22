#!/usr/bin/env python3
"""
INVERTIR v2.0 — Mean Reversion Scanner (Evidence-Based Upgrade)

Original: RSI < 30 + MACD histogram rising
Backtest result: +13.77% (101 trades, 10 months)

v2.0 changes (each backed by trade-by-trade analysis on 104 signals):

  1. REMOVED: "RSI turning up" filter
     - Data showed RSI still FALLING = WR 73% avg +1.49%
     - RSI already turning up = WR 47% avg -0.16%
     - Buying when RSI still falls BUT MACD brakes = maximum fear point

  2. ADDED: Distance from SMA50 >= 5%
     - Slightly below SMA50 (0-5%): WR 0%, avg -3.54%
     - Stretched 5%+ below: WR 63%, avg +0.90%
     - Eliminates false oversold in normal downtrends

  3. ADDED: Volume filter <= 1.5x average
     - Low volume reversals: WR 68%, avg +1.85%
     - High volume (>1.2x): WR 61%, avg +0.05%
     - High volume oversold = institutional selling, not opportunity

  4. ADDED: Composite score for ranking
     - RSI depth (deeper = better): 40 pts max
     - Stretch from SMA50 (further = better): 30 pts max
     - MACD acceleration: 20 pts max
     - Volume calm (lower = better): 10 pts max

  5. ADDED: ATR for risk context (stop-loss reference)

Philosophy: SAME simplicity. No ML. No stacking. No 80 features.
Just 2 indicators (RSI + MACD) with smarter filters.
"""

import yfinance as yf
import pandas as pd
import numpy as np
import warnings

warnings.filterwarnings('ignore')

# ── Ticker list ──────────────────────────────────────────────────────────
tickers_str = """
AAPL, ADBE, ADI, AI, ALAB, AMAT, AMD, ARM, ASML, AVGO, BIDU, COIN, CRM, CRWV, CSCO, DOCU, ETSY, GOOGL, IBM, INTC, IREN, LRCX, META, MRVL, MSFT, MSTR, MU, NTES, NVDA, ORCL, PANW, PATH, PLTR, QCOM, RBLX, RGTI, ROKU, SAP, SE, SHOP, SNAP, SNOW, SONY, SPOT, TEAM, TSM, TWLO, UBER, UPST, ZM, GLW, GRMN, HPQ, MSI, SWKS, TXN, EA, ASTS, RKLB, ERIC, NOKA, BB, AXP, BAC, BCS, BK, BKNG, BRKB, BSBR, C, GS, HOOD, HSBC, ING, JPM, LYG, MA, MUFG, NU, PYPL, SAN, SCHW, STNE, USB, V, WFC, XP, PAGS, AIG, HDB, ABBV, ABT, AMGN, AZN, BIIB, BMY, CVS, DHR, GILD, GSK, ISRG, JNJ, LLY, MDT, MRK, MRNA, NVS, PFE, TMO, UNH, BKR, BP, CVX, E, EQNR, HAL, OXY, PBR, PSX, SHEL, SLB, TTE, VIST, XOM, AEM, B, BHP, CDE, FCX, GFI, GGB, HL, HMY, KGC, LAC, MOS, MUX, NEM, NG, NUE, PAAS, RIO, SCCO, SID, TXR, VALE, AAP, ABEV, ANF, ARCO, BABA, CL, COST, DEO, EBAY, HD, HSY, KMB, KO, KOFM, MCD, MDLZ, MO, NKE, ORLY, PEP, PG, PM, ROST, SBUX, SYY, TGT, TJX, UL, WMT, YELP, AVY, BA, CAT, DD, DE, FDX, GE, HON, HWM, IFF, IP, LMT, MMM, PCAR, PBI, RTX, SNA, UNP, ADGO, BBD, BIOX, CAAP, ELPC, EMBJ, GLOB, ITUB, LND, MELI, PAC, SATL, SBS, SUZ, TIMB, UGP, VIV, F, GM, HMC, HOG, NIO, RACE, STLA, TM, TSLA, AAL, ABNB, CAR, CCL, DAL, LVS, SPCE, TCOM, TRIP, UAL, AMX, TMUS, VOD, VZ
"""

tickers = [t.strip() for t in tickers_str.replace('\n', '').split(',') if t.strip()]

print(f"INVERTIR v2.0 - Escaneando {len(tickers)} activos...\n")

oportunidades = []

for ticker in tickers:
    try:
        data = yf.download(ticker, period="6mo", progress=False)

        if len(data) < 55:  # Need 50 for SMA50 + buffer
            continue

        close = data['Close'].squeeze()
        volume = data['Volume'].squeeze()

        # ── RSI (14) ────────────────────────────────────────────────────
        delta = close.diff()
        ema_up = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        ema_down = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
        rs = ema_up / ema_down
        rsi = 100 - (100 / (1 + rs))

        # ── MACD (12, 26, 9) ───────────────────────────────────────────
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal_line = macd.ewm(span=9, adjust=False).mean()
        macd_hist = macd - signal_line

        # ── SMA50 ──────────────────────────────────────────────────────
        sma50 = close.rolling(50).mean()

        # ── ATR (14) for risk context ──────────────────────────────────
        high = data['High'].squeeze()
        low = data['Low'].squeeze()
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()

        # ── Volume ratio ───────────────────────────────────────────────
        avg_vol_20 = volume.rolling(20).mean()

        # ── Current values ─────────────────────────────────────────────
        current_rsi = rsi.iloc[-1]
        current_hist = macd_hist.iloc[-1]
        prev_hist = macd_hist.iloc[-2]
        current_price = close.iloc[-1]
        current_sma50 = sma50.iloc[-1]
        current_atr = atr.iloc[-1]
        vol_ratio = volume.iloc[-1] / avg_vol_20.iloc[-1] if avg_vol_20.iloc[-1] > 0 else 1.0

        # Distance from SMA50 (negative = below)
        dist_sma50_pct = (current_price / current_sma50 - 1) * 100

        # MACD acceleration
        macd_accel = current_hist - prev_hist

        # ═════════════════════════════════════════════════════════════════
        #  SIGNAL LOGIC v2.0
        #
        #  Core (unchanged):  RSI < 30 AND MACD histogram rising
        #  New filter 1:      At least 5% below SMA50 (real oversold)
        #  New filter 2:      Volume not extreme (< 1.5x avg)
        # ═════════════════════════════════════════════════════════════════

        if (current_rsi < 30
                and current_hist > prev_hist
                and dist_sma50_pct <= -5.0
                and vol_ratio < 1.5):

            # ── Composite Score (0-100) ────────────────────────────────
            # RSI depth: RSI 30→0 maps to 0→40 pts
            rsi_score = max(0, min(40, (30 - current_rsi) / 30 * 40))

            # Stretch from SMA50: 5%→20% maps to 0→30 pts
            stretch = abs(dist_sma50_pct)
            stretch_score = max(0, min(30, (stretch - 5) / 15 * 30))

            # MACD momentum: acceleration mapped to 0→20 pts
            macd_score = max(0, min(20, macd_accel / (current_atr * 0.01 + 1e-6) * 5))

            # Volume calm: lower is better. 1.5→0 maps to 0→10 pts
            vol_score = max(0, min(10, (1.5 - vol_ratio) / 1.5 * 10))

            total_score = rsi_score + stretch_score + macd_score + vol_score

            # Suggested stop-loss: 2x ATR below entry
            stop_loss = current_price - 2 * current_atr
            risk_pct = (current_price - stop_loss) / current_price * 100

            oportunidades.append({
                'Ticker': ticker,
                'Precio': round(float(current_price), 2),
                'RSI': round(float(current_rsi), 1),
                'Dist SMA50': f"{dist_sma50_pct:.1f}%",
                'Vol Ratio': f"{vol_ratio:.1f}x",
                'MACD Hist': round(float(current_hist), 4),
                'Score': round(float(total_score), 0),
                'Stop Loss': round(float(stop_loss), 2),
                'Riesgo': f"{risk_pct:.1f}%",
            })

    except Exception:
        pass

# ═════════════════════════════════════════════════════════════════════════
#  OUTPUT
# ═════════════════════════════════════════════════════════════════════════

df_res = pd.DataFrame(oportunidades)

if not df_res.empty:
    top = df_res.sort_values(by='Score', ascending=False).head(10)

    print("=" * 90)
    print("  TOP OPORTUNIDADES — Sobreventa Extrema Confirmada")
    print("  Filtros: RSI<30 + MACD reversal + >5% bajo SMA50 + volumen calmo")
    print("=" * 90)
    print(top.to_string(index=False))
    print("=" * 90)

    print(f"\n  Senales encontradas: {len(df_res)} de {len(tickers)} activos")
    print(f"  Selectividad: {len(df_res)/len(tickers)*100:.1f}% pasan el filtro\n")

    print("  COMO LEER CADA COLUMNA:")
    print("  - RSI:        < 25 = sobreventa fuerte, < 20 = extrema")
    print("  - Dist SMA50: Mas negativo = mas estirado (mayor potencial de rebote)")
    print("  - Vol Ratio:  < 1.0x = volumen bajo (panico sin conviccion, ideal)")
    print("  - Score:      Ranking compuesto (mayor = mejor oportunidad)")
    print("  - Stop Loss:  Precio sugerido de salida si la tesis falla (2x ATR)")
    print("  - Riesgo:     Distancia al stop loss en % del precio")

    print("\n  ESTRATEGIA DE SALIDA SUGERIDA:")
    print("  - Mantener 5-10 dias (horizonte optimo segun backtests)")
    print("  - Take profit parcial si sube >3% en los primeros 3 dias")
    print("  - Stop loss si cae al nivel sugerido")
    print("  - No promediar para abajo — si toca stop, salir")
else:
    print("  No hay activos en sobreventa extrema confirmada hoy.")
    print("  (Esto es BUENO — significa que el filtro es selectivo)")
    print(f"  Se escanearon {len(tickers)} activos sin encontrar oportunidad clara.")
