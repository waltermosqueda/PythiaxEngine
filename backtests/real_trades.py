"""
BACKTEST INVERTIR FINAL - EXTRACCION DE TRADES REALES
Todos los datos provienen de Yahoo Finance via yfinance
Ningún valor es inventado o estimado
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.environ['PYTHONIOENCODING'] = 'utf-8'
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

TICKERS_INVERTIR = [
    'AAPL','ABBV','ABNB','ABT','ACHR','ACN','ADBE','ADI','ADP','ADSK',
    'AEM','AFRM','AIG','AMAT','AMD','AMGN','AMZN','ANET','APA','APP',
    'ARKK','ARM','ASML','AVGO','AXP','BA','BABA','BAC','BHP','BIDU',
    'BILL','BK','BKNG','BLK','BMY','BRK-B','BSX','C','CAT','CCJ',
    'CELH','CEG','CHWY','CL','CLSK','CMCSA','CME','CMG','COIN','COP',
    'COST','CRM','CRSP','CRWD','CSCO','CTAS','CVS','CVX','CYBR','DASH',
    'DAL','DG','DHR','DIS','DKNG','DLTR','DOCU','DDOG','DOW','DUOL',
    'DVN','DXCM','EA','EBAY','EL','EMR','ENPH','EQIX','EQNR','EW',
    'F','FANG','FCX','FDX','FSLR','FTNT','GD','GE','GILD','GIS',
    'GLW','GM','GOLD','GOOG','GPN','GS','HAL','HCA','HD','HIMS',
    'HOOD','HUBS','HUM','IBM','ICE','INTC','INTU','IONQ','ISRG','JCI',
    'JD','JNJ','JPM','KHC','KMI','KO','LBRD','LEN','LLY','LMT',
    'LOW','LRCX','LULU','LUV','LVS','MA','MARA','MAT','MCD','MCK',
    'MDLZ','MDT','MELI','MET','META','MMM','MO','MOH','MOS','MPWR',
    'MRK','MRVL','MS','MSFT','MSI','MU','NEE','NEM','NET','NFLX',
    'NKE','NOC','NOW','NSC','NVDA','NVO','NXPI','OKE','ON','ORCL',
    'OXY','PANW','PATH','PDD','PEP','PFE','PG','PGR','PINS','PLTR',
    'PM','PNC','PSX','PYPL','QCOM','QQQ','REGN','RIOT','RIVN','RKLB',
    'RBLX','ROKU','ROP','ROST','RTX','SAVE','SCHW','SE','SHOP','SNAP',
    'SNOW','SO','SOFI','SPY','SQ','SYK','SYY','T','TEM','TFC',
    'TGT','TJX','TMUS','TSLA','TSM','TTE','TTD','TTWO','TWLO','TXN',
    'U','UAL','UBER','UNH','UNP','UPS','URI','USB','V','VALE',
    'VFC','VKTX','VLO','VMC','VRTX','VZ','WBA','WBD','WDAY','WFC',
    'WM','WMT','XLE','XLF','XOM','ZM','ZS'
]

print("=" * 120)
print("BACKTEST INVERTIR FINAL - TRADES REALES CON DATOS VERIFICADOS DE YAHOO FINANCE")
print("=" * 120)
print(f"Fecha de ejecucion: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"Tickers en universo: {len(TICKERS_INVERTIR)}")
print()

# === DESCARGAR DATOS ===
print("Descargando datos de yfinance (Jun 2024 - Mar 2026)...")
start_date = "2024-06-01"
end_date = "2026-03-28"

data = {}
errors = []
for ticker in TICKERS_INVERTIR:
    try:
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)
        if len(df) > 60:
            data[ticker] = df
    except Exception as e:
        errors.append(ticker)

print(f"Descargados: {len(data)} tickers OK, {len(errors)} errores")
if errors:
    print(f"Errores: {errors}")

# === SPY DATA ===
spy = data.get("SPY")
if spy is None:
    print("ERROR: No se pudo descargar SPY")
    sys.exit(1)

spy_close = spy["Close"].squeeze()
spy_sma50 = spy_close.rolling(50).mean()
spy_returns = spy_close.pct_change()
spy_vol = spy_returns.rolling(20).std()

# === BUSCAR SENALES ===
print("Calculando indicadores y buscando senales...")

all_trades = []
backtest_start = pd.Timestamp("2024-09-01")
backtest_end = pd.Timestamp("2026-03-15")

for ticker in data:
    if ticker == "SPY":
        continue

    df = data[ticker]
    close = df["Close"].squeeze().dropna()
    volume = df["Volume"].squeeze().dropna()

    if len(close) < 60:
        continue

    # RSI(14) - Wilder's smoothing (como en invertir_final.py)
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss_s = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rs = gain / (loss_s + 1e-10)
    rsi = 100 - 100 / (1 + rs)

    # MACD(12,26,9)
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9).mean()
    macd_hist = macd_line - signal_line

    # SMA50
    sma50 = close.rolling(50).mean()
    sma_dist = ((close - sma50) / sma50) * 100

    # Volume ratio
    vol_avg = volume.rolling(20).mean()
    vol_ratio = volume / vol_avg

    # ATR(14)
    high = df["High"].squeeze().dropna()
    low = df["Low"].squeeze().dropna()
    common_idx = close.index.intersection(high.index).intersection(low.index)
    close_c = close.reindex(common_idx)
    high_c = high.reindex(common_idx)
    low_c = low.reindex(common_idx)
    tr1 = high_c - low_c
    tr2 = (high_c - close_c.shift(1)).abs()
    tr3 = (low_c - close_c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    # Anti-knife tracking
    last_signal_date = None

    dates = close.index
    for i_day in range(1, len(dates)):
        date = dates[i_day]
        if date < backtest_start or date > backtest_end:
            continue

        prev_date = dates[i_day - 1]

        try:
            curr_rsi = float(rsi.get(date, np.nan))
            curr_sma_d = float(sma_dist.get(date, np.nan))
            curr_vol_r = float(vol_ratio.get(date, np.nan))
            curr_price = float(close.get(date, np.nan))
            curr_macd = float(macd_hist.get(date, np.nan))
            prev_macd = float(macd_hist.get(prev_date, np.nan))
            curr_atr = float(atr.get(date, np.nan))
        except (TypeError, ValueError):
            continue

        if any(np.isnan(x) for x in [curr_rsi, curr_sma_d, curr_vol_r, curr_price, curr_macd, prev_macd, curr_atr]):
            continue

        # === FILTROS INVERTIR FINAL ===
        if curr_rsi >= 30:
            continue
        if curr_macd <= prev_macd:
            continue
        if curr_sma_d > -5:
            continue
        if curr_vol_r >= 1.5:
            continue

        # SPY Regime
        if date not in spy_close.index:
            continue
        try:
            sp = float(spy_close.get(date, np.nan))
            ss = float(spy_sma50.get(date, np.nan))
            sv = float(spy_vol.get(date, np.nan))
        except (TypeError, ValueError):
            continue

        if any(np.isnan(x) for x in [sp, ss, sv]):
            continue
        if sp <= ss or sv > 0.01:
            continue

        # Anti-knife
        if last_signal_date is not None:
            if (date - last_signal_date).days < 5:
                continue

        last_signal_date = date

        # === RESULTADO ===
        future_idx = dates[dates > date]

        ret_5d = None
        ret_10d = None
        price_5d = None
        price_10d = None

        if len(future_idx) >= 5:
            p5 = float(close[future_idx[4]])
            price_5d = round(p5, 2)
            ret_5d = round((p5 / curr_price - 1) * 100, 2)
        if len(future_idx) >= 10:
            p10 = float(close[future_idx[9]])
            price_10d = round(p10, 2)
            ret_10d = round((p10 / curr_price - 1) * 100, 2)

        # Score exacto como invertir_final.py: (30-RSI)*2 + |SMA dist|
        score = round((30 - curr_rsi) * 2 + abs(curr_sma_d), 1)

        all_trades.append({
            "date": date.strftime("%Y-%m-%d"),
            "ticker": ticker,
            "price": round(curr_price, 2),
            "rsi": round(curr_rsi, 2),
            "macd_hist": round(curr_macd, 4),
            "macd_prev": round(prev_macd, 4),
            "sma_dist": round(curr_sma_d, 2),
            "vol_ratio": round(curr_vol_r, 2),
            "atr": round(curr_atr, 2),
            "score": score,
            "ret_5d": ret_5d,
            "ret_10d": ret_10d,
            "price_5d": price_5d,
            "price_10d": price_10d,
            "spy_price": round(sp, 2),
            "spy_sma50": round(ss, 2),
            "spy_vol_pct": round(sv * 100, 3),
        })

# Ordenar
all_trades.sort(key=lambda x: x["date"])

print(f"Total senales encontradas: {len(all_trades)}")
print()

# === TABLA COMPLETA ===
print("=" * 140)
print("LISTA COMPLETA DE TRADES REALES - INVERTIR FINAL (Sep 2024 - Mar 2026)")
print("=" * 140)
header = f"{'#':<4} {'FECHA':<12} {'TICKER':<8} {'PRECIO':>9} {'RSI':>7} {'MACD_H':>10} {'MACD_P':>10} {'SMA%':>8} {'VOLR':>6} {'SCORE':>6} {'RET5D':>8} {'RET10D':>8} {'P_5D':>9} {'P_10D':>9}"
print(header)
print("-" * 140)

wins_5 = losses_5 = wins_10 = losses_10 = 0
rets5 = []
rets10 = []

for i, t in enumerate(all_trades, 1):
    r5 = f"{t['ret_5d']:+.2f}%" if t["ret_5d"] is not None else "N/A"
    r10 = f"{t['ret_10d']:+.2f}%" if t["ret_10d"] is not None else "N/A"
    p5 = f"${t['price_5d']:.2f}" if t["price_5d"] is not None else "N/A"
    p10 = f"${t['price_10d']:.2f}" if t["price_10d"] is not None else "N/A"

    print(f"{i:<4} {t['date']:<12} {t['ticker']:<8} ${t['price']:>8.2f} {t['rsi']:>7.2f} {t['macd_hist']:>+10.4f} {t['macd_prev']:>+10.4f} {t['sma_dist']:>+7.2f}% {t['vol_ratio']:>5.2f}x {t['score']:>5.1f} {r5:>8} {r10:>8} {p5:>9} {p10:>9}")

    if t["ret_5d"] is not None:
        rets5.append(t["ret_5d"])
        if t["ret_5d"] > 0: wins_5 += 1
        else: losses_5 += 1
    if t["ret_10d"] is not None:
        rets10.append(t["ret_10d"])
        if t["ret_10d"] > 0: wins_10 += 1
        else: losses_10 += 1

# === RESUMEN ===
print()
print("=" * 80)
print("RESUMEN ESTADISTICO (DATOS 100% REALES DE YAHOO FINANCE)")
print("=" * 80)

for name, rets, w, l in [("HOLD 5 DIAS", rets5, wins_5, losses_5), ("HOLD 10 DIAS", rets10, wins_10, losses_10)]:
    if not rets:
        continue
    arr = np.array(rets)
    hold_days = 5 if "5" in name else 10
    sharpe = (arr.mean() / arr.std()) * np.sqrt(252 / hold_days) if arr.std() > 0 else 0
    wins_arr = arr[arr > 0]
    loss_arr = arr[arr <= 0]

    print(f"\n{name}:")
    print(f"  Trades totales: {len(arr)}")
    print(f"  Wins: {w} | Losses: {l} | Win Rate: {w/len(arr)*100:.1f}%")
    print(f"  Retorno promedio: {arr.mean():.2f}%")
    if len(wins_arr) > 0:
        print(f"  Avg Win: +{wins_arr.mean():.2f}%")
    if len(loss_arr) > 0:
        print(f"  Avg Loss: {loss_arr.mean():.2f}%")
    print(f"  Retorno total acumulado: {arr.sum():.2f}%")
    print(f"  Desviacion estandar: {arr.std():.2f}%")
    print(f"  Sharpe ratio (anualizado): {sharpe:.2f}")
    print(f"  Mejor trade: {arr.max():+.2f}%")
    print(f"  Peor trade: {arr.min():+.2f}%")
    print(f"  Mediana: {np.median(arr):+.2f}%")
    if len(wins_arr) > 0 and len(loss_arr) > 0:
        rr = wins_arr.mean() / abs(loss_arr.mean())
        print(f"  Risk:Reward: 1:{rr:.2f}")
        pf = wins_arr.sum() / abs(loss_arr.sum())
        print(f"  Profit Factor: {pf:.2f}")

# === 3 EJEMPLOS DETALLADOS ===
print()
print("=" * 80)
print("3 EJEMPLOS DETALLADOS PASO A PASO (DATOS 100% REALES)")
print("=" * 80)

examples = []
# Buscar un win grande, un win normal, un loss
for t in all_trades:
    if t["ret_10d"] is not None:
        if t["ret_10d"] > 8 and len(examples) == 0:
            examples.append(("EJEMPLO 1: WIN GRANDE", t))
        elif 1 < t["ret_10d"] < 5 and len(examples) == 1:
            examples.append(("EJEMPLO 2: WIN MODERADO", t))
        elif t["ret_10d"] < -2 and len(examples) == 2:
            examples.append(("EJEMPLO 3: LOSS", t))

# Fallback si no encontramos los 3 tipos
if len(examples) < 3:
    for t in all_trades:
        if t["ret_10d"] is not None and len(examples) < 3:
            label = f"EJEMPLO {len(examples)+1}: {'WIN' if t['ret_10d'] > 0 else 'LOSS'}"
            examples.append((label, t))

for label, t in examples:
    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"{'='*60}")
    print(f"Fecha de senal: {t['date']}")
    print(f"Ticker: {t['ticker']}")
    print(f"Precio de entrada: ${t['price']}")
    print()

    print("PASO 1 - RSI(14) < 30:")
    pasa1 = "PASA" if t["rsi"] < 30 else "RECHAZADO"
    print(f"  RSI(14) = {t['rsi']}")
    print(f"  Umbral: < 30 --> {pasa1}")
    print(f"  Interpretacion: RSI {t['rsi']:.0f} indica sobreventa {'extrema' if t['rsi'] < 25 else 'moderada'}")
    print()

    print("PASO 2 - MACD histograma subiendo:")
    diff_macd = t["macd_hist"] - t["macd_prev"]
    pasa2 = "PASA" if diff_macd > 0 else "RECHAZADO"
    print(f"  MACD hist HOY  = {t['macd_hist']:+.4f}")
    print(f"  MACD hist AYER = {t['macd_prev']:+.4f}")
    print(f"  Cambio = {diff_macd:+.4f} --> {pasa2}")
    print(f"  Interpretacion: El momentum bajista se esta {'desacelerando' if t['macd_hist'] < 0 else 'acelerando al alza'}")
    print()

    print("PASO 3 - Precio > 5% debajo de SMA50:")
    pasa3 = "PASA" if t["sma_dist"] < -5 else "RECHAZADO"
    print(f"  Distancia a SMA50 = {t['sma_dist']:+.2f}%")
    print(f"  Umbral: < -5% --> {pasa3}")
    print(f"  Interpretacion: El precio esta {abs(t['sma_dist']):.1f}% por debajo de su media de 50 dias")
    print()

    print("PASO 4 - Volumen calmado (< 1.5x promedio):")
    pasa4 = "PASA" if t["vol_ratio"] < 1.5 else "RECHAZADO"
    print(f"  Volumen ratio = {t['vol_ratio']:.2f}x promedio 20d")
    print(f"  Umbral: < 1.5x --> {pasa4}")
    print(f"  Interpretacion: {'No hay panico vendedor, caida ordenada' if t['vol_ratio'] < 1.5 else 'Volumen alto, posible panico'}")
    print()

    print("PASO 5 - SPY Regime Filter:")
    pasa5a = "ENCIMA" if t["spy_price"] > t["spy_sma50"] else "DEBAJO"
    pasa5b = "PASA" if t["spy_vol_pct"] < 1.0 else "RECHAZADO"
    print(f"  SPY = ${t['spy_price']} vs SMA50 = ${t['spy_sma50']} --> SPY {pasa5a} de SMA50")
    print(f"  SPY volatilidad 20d = {t['spy_vol_pct']:.3f}% --> {pasa5b} (umbral < 1%)")
    print(f"  Interpretacion: Mercado en tendencia alcista con baja volatilidad = entorno favorable")
    print()

    print("PASO 6 - Score de conviccion:")
    rsi_comp = round((30 - t["rsi"]) * 2, 1)
    sma_comp = round(abs(t["sma_dist"]), 1)
    print(f"  Score = {t['score']}")
    print(f"  Calculo: (30 - {t['rsi']}) * 2 + |{t['sma_dist']}| = {rsi_comp} + {sma_comp} = {t['score']}")
    print()

    print("RESULTADO REAL:")
    print(f"  Compra: ${t['price']} el {t['date']}")
    if t["price_5d"] is not None:
        emoji5 = "GANANCIA" if t["ret_5d"] > 0 else "PERDIDA"
        print(f"  A 5 dias: ${t['price_5d']} --> {t['ret_5d']:+.2f}% ({emoji5})")
    if t["price_10d"] is not None:
        emoji10 = "GANANCIA" if t["ret_10d"] > 0 else "PERDIDA"
        print(f"  A 10 dias: ${t['price_10d']} --> {t['ret_10d']:+.2f}% ({emoji10})")
    if t["ret_10d"] is not None:
        dollar = t["ret_10d"] * 100  # por cada $10,000
        print(f"  Si invertias $10,000: {'ganabas' if dollar > 0 else 'perdias'} ${abs(dollar):.0f}")

print()
print("=" * 80)
print("VERIFICACION: TODOS LOS PRECIOS SON DE YAHOO FINANCE (yfinance)")
print("PUEDES VERIFICAR CUALQUIER PRECIO EN https://finance.yahoo.com/")
print("=" * 80)
