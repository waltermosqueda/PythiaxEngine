#!/usr/bin/env python3
"""
INVERTIR v2.0 — Dashboard diario
Correr después del cierre de mercado para ver señales del día siguiente.

Uso: python dashboard_invertir.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import yfinance as yf
import pandas as pd
import numpy as np
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

# -- COLORES CONSOLA ------------------------------------------------------
G  = "\033[92m"; R  = "\033[91m"; Y  = "\033[93m"
C  = "\033[96m"; W  = "\033[97m"; DIM= "\033[2m"
B  = "\033[1m";  RST= "\033[0m"

# -- TICKERS --------------------------------------------------------------
tickers_str = """
AAPL, ADBE, ADI, AI, ALAB, AMAT, AMD, ARM, ASML, AVGO, BIDU, COIN, CRM,
CRWV, CSCO, DOCU, ETSY, GOOGL, IBM, INTC, IREN, LRCX, META, MRVL, MSFT,
MSTR, MU, NTES, NVDA, ORCL, PANW, PATH, PLTR, QCOM, RBLX, RGTI, ROKU,
SAP, SE, SHOP, SNAP, SNOW, SONY, SPOT, TEAM, TSM, TWLO, UBER, UPST, ZM,
GLW, GRMN, HPQ, MSI, SWKS, TXN, EA, ASTS, RKLB, ERIC, NOKA, BB,
AXP, BAC, BCS, BK, BKNG, BRKB, BSBR, C, GS, HOOD, HSBC, ING, JPM, LYG,
MA, MUFG, NU, PYPL, SAN, SCHW, STNE, USB, V, WFC, XP, PAGS, AIG, HDB,
ABBV, ABT, AMGN, AZN, BIIB, BMY, CVS, DHR, GILD, GSK, ISRG, JNJ, LLY,
MDT, MRK, MRNA, NVS, PFE, TMO, UNH,
BKR, BP, CVX, E, EQNR, HAL, OXY, PBR, PSX, SHEL, SLB, TTE, VIST, XOM,
AEM, B, BHP, CDE, FCX, GFI, GGB, HL, HMY, KGC, LAC, MOS, MUX, NEM, NG,
NUE, PAAS, RIO, SCCO, SID, TXR, VALE,
AAP, ABEV, ANF, ARCO, BABA, CL, COST, DEO, EBAY, HD, HSY, KMB, KO, KOFM,
MCD, MDLZ, MO, NKE, ORLY, PEP, PG, PM, ROST, SBUX, SYY, TGT, TJX, UL,
WMT, YELP,
AVY, BA, CAT, DD, DE, FDX, GE, HON, HWM, IFF, IP, LMT, MMM, PCAR, PBI,
RTX, SNA, UNP,
ADGO, BBD, BIOX, CAAP, ELPC, EMBJ, GLOB, ITUB, LND, MELI, PAC, SATL,
SBS, SUZ, TIMB, UGP, VIV,
F, GM, HMC, HOG, NIO, RACE, STLA, TM, TSLA,
AAL, ABNB, CAR, CCL, DAL, LVS, SPCE, TCOM, TRIP, UAL,
AMX, TMUS, VOD, VZ
"""
tickers = [t.strip() for t in tickers_str.replace('\n', '').split(',') if t.strip()]


def scan():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{B}{'='*72}{RST}")
    print(f"{B}  INVERTIR v2.0 — Dashboard  |  {now}{RST}")
    print(f"{B}{'='*72}{RST}")
    print(f"  {DIM}Escaneando {len(tickers)} activos...{RST}\n")

    signals = []
    watchlist = []  # RSI 30-35 = casi oversold, para vigilar
    scanned = 0
    errors = 0

    for ticker in tickers:
        try:
            data = yf.download(ticker, period="6mo", progress=False)
            if len(data) < 55:
                continue
            scanned += 1

            close  = data['Close'].squeeze()
            volume = data['Volume'].squeeze()
            high   = data['High'].squeeze()
            low    = data['Low'].squeeze()

            # RSI(14)
            delta = close.diff()
            ema_up   = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
            ema_down = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
            rs  = ema_up / ema_down
            rsi = 100 - (100 / (1 + rs))

            # MACD(12,26,9)
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd  = ema12 - ema26
            sig   = macd.ewm(span=9, adjust=False).mean()
            hist  = macd - sig

            # SMA50
            sma50 = close.rolling(50).mean()

            # ATR(14)
            tr = pd.concat([
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs()
            ], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()

            # Volume ratio
            avg_vol = volume.rolling(20).mean()

            # Current values
            cur_rsi   = float(rsi.iloc[-1])
            cur_hist  = float(hist.iloc[-1])
            prev_hist = float(hist.iloc[-2])
            price     = float(close.iloc[-1])
            prev_price = float(close.iloc[-2])
            cur_sma50 = float(sma50.iloc[-1])
            cur_atr   = float(atr.iloc[-1])
            vol_ratio = float(volume.iloc[-1] / avg_vol.iloc[-1]) if avg_vol.iloc[-1] > 0 else 1.0
            change    = (price / prev_price - 1) * 100
            dist_sma  = (price / cur_sma50 - 1) * 100

            # -- SEÑAL PRINCIPAL --------------------------------------
            if (cur_rsi < 30
                    and cur_hist > prev_hist
                    and dist_sma <= -5.0
                    and vol_ratio < 1.5):

                rsi_sc  = max(0, min(40, (30 - cur_rsi) / 30 * 40))
                str_sc  = max(0, min(30, (abs(dist_sma) - 5) / 15 * 30))
                mac_sc  = max(0, min(20, (cur_hist - prev_hist) / (cur_atr * 0.01 + 1e-6) * 5))
                vol_sc  = max(0, min(10, (1.5 - vol_ratio) / 1.5 * 10))
                score   = rsi_sc + str_sc + mac_sc + vol_sc
                stop    = price - 2 * cur_atr
                risk    = (price - stop) / price * 100

                signals.append({
                    'ticker': ticker, 'price': price, 'change': change,
                    'rsi': cur_rsi, 'dist_sma': dist_sma, 'vol_ratio': vol_ratio,
                    'score': score, 'stop': stop, 'risk': risk, 'atr': cur_atr
                })

            # -- WATCHLIST: casi oversold -----------------------------
            elif 30 <= cur_rsi < 35 and dist_sma <= -3.0:
                watchlist.append({
                    'ticker': ticker, 'price': price, 'rsi': cur_rsi,
                    'dist_sma': dist_sma, 'change': change
                })

        except Exception:
            errors += 1

    # ═════════════════════════════════════════════════════════════════════
    #  OUTPUT
    # ═════════════════════════════════════════════════════════════════════

    # SEÑALES ACTIVAS
    if signals:
        signals.sort(key=lambda x: x['score'], reverse=True)
        print(f"  {G}{B}SENALES ACTIVAS — Compra para manana{RST}")
        print(f"  {DIM}{'-'*68}{RST}")
        print(f"  {'Ticker':<8} {'Precio':>8} {'Chg%':>6} {'RSI':>5} {'SMA50':>7} {'Vol':>5} {'Score':>6} {'Stop':>8} {'Risk':>5}")
        print(f"  {DIM}{'-'*68}{RST}")

        for s in signals:
            rsi_color = G if s['rsi'] < 25 else Y
            score_color = G if s['score'] >= 50 else Y if s['score'] >= 30 else W
            chg_color = R if s['change'] < 0 else G

            print(f"  {B}{s['ticker']:<8}{RST}"
                  f" ${s['price']:>7.2f}"
                  f" {chg_color}{s['change']:>+5.1f}%{RST}"
                  f" {rsi_color}{s['rsi']:>5.1f}{RST}"
                  f" {R}{s['dist_sma']:>+6.1f}%{RST}"
                  f" {s['vol_ratio']:>4.1f}x"
                  f" {score_color}{s['score']:>5.0f}{RST}"
                  f" ${s['stop']:>7.2f}"
                  f" {s['risk']:>4.1f}%")

        print(f"\n  {DIM}Reglas de salida:{RST}")
        print(f"  {DIM}  - Mantener 5-10 dias{RST}")
        print(f"  {DIM}  - Take profit si sube >3% en 3 dias{RST}")
        print(f"  {DIM}  - Stop loss al precio indicado{RST}")
    else:
        print(f"  {Y}Sin senales hoy.{RST} Ningun activo cumple los 4 filtros.")
        print(f"  {DIM}(Esto es normal — el modelo es muy selectivo){RST}")

    # WATCHLIST
    if watchlist:
        watchlist.sort(key=lambda x: x['rsi'])
        print(f"\n  {Y}{B}WATCHLIST — Acercandose a sobreventa{RST}")
        print(f"  {DIM}{'-'*50}{RST}")
        print(f"  {'Ticker':<8} {'Precio':>8} {'Chg%':>6} {'RSI':>5} {'SMA50':>7}")
        print(f"  {DIM}{'-'*50}{RST}")

        for w in watchlist[:10]:
            print(f"  {w['ticker']:<8} ${w['price']:>7.2f} {w['change']:>+5.1f}% {Y}{w['rsi']:>5.1f}{RST} {w['dist_sma']:>+6.1f}%")

        print(f"  {DIM}(Si manana RSI baja de 30 con MACD girando, se activa senal){RST}")

    # RESUMEN
    print(f"\n  {DIM}{'-'*68}{RST}")
    print(f"  Escaneados: {scanned} | Senales: {G}{len(signals)}{RST} | "
          f"Watchlist: {Y}{len(watchlist)}{RST} | "
          f"Selectividad: {len(signals)/max(scanned,1)*100:.1f}%")
    print(f"  {DIM}Errores de descarga: {errors}{RST}")
    print(f"{B}{'='*72}{RST}\n")


if __name__ == '__main__':
    scan()
