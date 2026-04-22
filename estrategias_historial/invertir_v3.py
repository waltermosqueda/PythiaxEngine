#!/usr/bin/env python3
"""
INVERTIR V3.0 — Mean Reversion Scanner (Filtros Optimizados por Backtests)
==========================================================================

Basada en INVERTIR Final (Sharpe 6.26, la unica estrategia positiva IS+OOS).
Agrega filtros descubiertos en Mega Backtest Round 2 (analisis de 82+ trades):

Filtros V3 vs Final:
  1. RSI < 25 (antes < 30)     -> WR sube dramaticamente, RSI<22 = 100% WR
  2. SMA50 dist -15% a -10%    -> Sweet spot de rebote maximo
  3. Volume < 0.8x avg (antes 1.5x) -> Elimina presion institucional
  4. MACD accel media-alta      -> 88% WR en ese rango
  5. Solo Miercoles/Jueves      -> Mejor rendimiento estadistico
  6. Score entre 30-50          -> Rango optimo descubierto
  7. SPY regime + anti-knife    -> Se mantienen de Final

Holding: 10 dias habiles (optimo confirmado en backtests).

ADVERTENCIA: Filtros mas estrictos = menos trades (~15-25 por periodo).
Esto es intencional: preferimos CALIDAD sobre CANTIDAD.

Uso: python invertir_v3.py
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
if 'SPY' not in tickers:
    tickers.append('SPY')


# ═══════════════════════════════════════════════════════════════════════════════
#  PARAMETROS V3 (descubiertos en backtests)
# ═══════════════════════════════════════════════════════════════════════════════

V3_RSI_MAX = 25           # antes 30 - WR sube dramaticamente
V3_SMA_DIST_MIN = -15.0   # -15% minimo (mas estirado no rebota bien)
V3_SMA_DIST_MAX = -10.0   # -10% maximo (poca elasticidad si esta cerca)
V3_VOL_MAX = 0.8          # antes 1.5x - sin presion institucional
V3_SCORE_MIN = 30         # score minimo
V3_SCORE_MAX = 50         # score maximo (>50 = demasiado extremo)
V3_DIAS_OK = [2, 3]       # 0=Lun, 1=Mar, 2=Mie, 3=Jue, 4=Vie
V3_HOLDING_DAYS = 10      # dias habiles de holding
V3_MACD_ACCEL_MIN = 0.3   # aceleracion MACD minima (normalizada por ATR)


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
#  SCAN INDIVIDUAL TICKER — V3 con filtros optimizados
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_ticker_v3(ticker, data, today_weekday):
    """Returns signal dict or None. Aplica todos los filtros V3."""
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
    macd_accel = curr_hist - prev_hist
    macd_accel_norm = macd_accel / (curr_atr * 0.01 + 1e-6)

    # ── F1: RSI < 25 (V3: mas estricto que Final) ──
    if curr_rsi >= V3_RSI_MAX:
        return None

    # ── F2: MACD hist rising ──
    if curr_hist <= prev_hist:
        return None

    # ── F3: SMA50 distance en sweet spot -15% a -10% ──
    if dist_sma50 < V3_SMA_DIST_MIN or dist_sma50 > V3_SMA_DIST_MAX:
        return None

    # ── F4: Volume < 0.8x avg (V3: mas estricto) ──
    if vol_ratio > V3_VOL_MAX:
        return None

    # ── F5: Solo Miercoles/Jueves ──
    if today_weekday not in V3_DIAS_OK:
        return None

    # ── F6: MACD aceleracion media-alta ──
    if macd_accel_norm < V3_MACD_ACCEL_MIN:
        return None

    # ── Score (misma formula que V2/Final) ──
    rsi_score = max(0, min(40, (30 - curr_rsi) / 30 * 40))
    stretch = abs(dist_sma50)
    stretch_score = max(0, min(30, (stretch - 5) / 15 * 30))
    macd_score = max(0, min(20, macd_accel_norm * 5))
    vol_score = max(0, min(10, (1.5 - vol_ratio) / 1.5 * 10))
    total_score = rsi_score + stretch_score + macd_score + vol_score

    # ── F7: Score en rango optimo 30-50 ──
    if total_score < V3_SCORE_MIN or total_score > V3_SCORE_MAX:
        return None

    stop_loss = price - 2 * curr_atr
    take_profit = price * 1.03
    risk_pct = (1 - stop_loss / price) * 100

    return {
        'Ticker': ticker,
        'Precio': round(float(price), 2),
        'RSI': round(float(curr_rsi), 1),
        'vs SMA50': f"{dist_sma50:.1f}%",
        'Vol': f"{vol_ratio:.2f}x",
        'MACD Acc': f"{macd_accel_norm:.1f}",
        'Score': round(float(total_score)),
        'Stop': f"${stop_loss:.2f}",
        'Target': f"${take_profit:.2f}",
        'Riesgo': f"{risk_pct:.1f}%",
        '_score': total_score,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def _why_rejected(rsi, dist_sma, vol_ratio, weekday):
    """Explica por que una senal Final fue rechazada por V3."""
    reasons = []
    if rsi >= V3_RSI_MAX:
        reasons.append(f"RSI {rsi:.0f}>={V3_RSI_MAX}")
    if dist_sma < V3_SMA_DIST_MIN:
        reasons.append(f"SMA {dist_sma:.0f}%<{V3_SMA_DIST_MIN}%")
    if dist_sma > V3_SMA_DIST_MAX:
        reasons.append(f"SMA {dist_sma:.0f}%>{V3_SMA_DIST_MAX}%")
    if vol_ratio > V3_VOL_MAX:
        reasons.append(f"Vol {vol_ratio:.1f}>{V3_VOL_MAX}")
    if weekday not in V3_DIAS_OK:
        reasons.append("dia no valido")
    return ", ".join(reasons) if reasons else "score fuera de rango"


def main():
    hoy = datetime.now()
    hoy_str = hoy.strftime('%Y-%m-%d')
    weekday = hoy.weekday()  # 0=Lun ... 4=Vie
    dia_nombre = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado', 'Domingo'][weekday]

    print(f"INVERTIR V3.0 (Filtros Optimizados) - {hoy_str} ({dia_nombre})")
    print(f"Escaneando {len(tickers)} activos...\n")

    # Download all data at once (much faster)
    data_all = yf.download(tickers, period="6mo", progress=False, threads=True)

    # ── STEP 1: Check day of week ─────────────────────────────────────────
    print("=" * 80)
    print("  PASO 0: DIA DE LA SEMANA")
    print("=" * 80)

    if weekday not in V3_DIAS_OK:
        dias_ok_nombres = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes']
        print(f"  Hoy es {dia_nombre}.")
        print(f"  V3 solo opera los: {', '.join(dias_ok_nombres[d] for d in V3_DIAS_OK)}")
        print(f"  Backtests mostraron que {dia_nombre} tiene peor performance.")
        print(f"\n  DECISION: NO OPERAR HOY (filtro de dia)")
        print(f"  Proximo escaneo valido: ", end="")
        for offset in range(1, 8):
            next_day = (weekday + offset) % 7
            if next_day in V3_DIAS_OK:
                next_nombre = dias_ok_nombres[next_day]
                print(f"{next_nombre}")
                break
        print(f"\n  (Mostrando senales como REFERENCIA para que veas el mercado)\n")
    else:
        print(f"  Hoy es {dia_nombre} - DIA VALIDO para operar")
        print()

    # ── STEP 2: Check regime ─────────────────────────────────────────────
    print("=" * 80)
    print("  PASO 1: REGIMEN DEL MERCADO")
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
    else:
        print(f"  {regime}")

    if not is_safe:
        print(f"""
  {'=' * 68}
  MERCADO NO SEGURO PARA MEAN REVERSION.
  Razon: {'SPY bajo SMA50' if isinstance(regime, dict) and not regime['above_sma'] else 'Volatilidad alta'}
  RECOMENDACION: No operar. Esperar estabilidad.
  {'=' * 68}
""")

    # ── STEP 3: Scan tickers ─────────────────────────────────────────────
    results = []
    near_miss = []

    for ticker in tickers:
        if ticker == 'SPY':
            continue
        try:
            df = data_all.xs(ticker, level=1, axis=1)

            signal = analyze_ticker_v3(ticker, df, weekday)
            if signal:
                results.append(signal)
            else:
                # Check if it would pass FINAL filters (for reference)
                close = df['Close'].squeeze()
                if len(close) >= 55:
                    rsi = calc_rsi(close)
                    _, _, macd_hist = calc_macd(close)
                    sma50 = close.rolling(50).mean()
                    vol_avg = df['Volume'].squeeze().rolling(20).mean()

                    r = rsi.iloc[-1]
                    h = macd_hist.iloc[-1]
                    hp = macd_hist.iloc[-2] if len(macd_hist) > 1 else 0
                    p = close.iloc[-1]
                    s = sma50.iloc[-1]
                    d = (p / s - 1) * 100
                    vr = df['Volume'].squeeze().iloc[-1] / (vol_avg.iloc[-1] + 1e-10)

                    if r < 30 and h > hp and d <= -5 and vr < 1.5:
                        near_miss.append({
                            'Ticker': ticker,
                            'RSI': round(float(r), 1),
                            'vs SMA50': f"{d:.1f}%",
                            'Vol': f"{vr:.2f}x",
                            'Razon': _why_rejected(r, d, vr, weekday),
                        })
        except Exception:
            pass

    # ── STEP 4: Display results ──────────────────────────────────────────
    print("=" * 80)
    print("  PASO 2: SENALES V3 (FILTROS OPTIMIZADOS)")
    print("=" * 80)

    can_trade = is_safe and weekday in V3_DIAS_OK

    if results:
        results.sort(key=lambda x: x['_score'], reverse=True)
        display_cols = ['Ticker', 'Precio', 'RSI', 'vs SMA50', 'Vol', 'MACD Acc', 'Score', 'Stop', 'Target', 'Riesgo']
        df_res = pd.DataFrame(results)[display_cols]

        status = "" if can_trade else " [SOLO REFERENCIA]"
        print(f"  {len(results)} senales V3 de {len(tickers)} activos{status}\n")
        print(df_res.to_string(index=False))
    else:
        print(f"  Sin senales V3 hoy.")
        print(f"  (V3 es MUY selectiva — esto es normal y esperado)")

    # Show near misses for context
    if near_miss:
        print(f"\n{'=' * 80}")
        print(f"  NEAR MISS: {len(near_miss)} senales pasan FINAL pero NO V3")
        print("=" * 80)
        df_nm = pd.DataFrame(near_miss)
        print(df_nm.to_string(index=False))
        print("  (Estas senales NO se operan con V3 — solo referencia)")

    # ── STEP 5: Action plan ──────────────────────────────────────────────
    print(f"\n{'=' * 80}")
    print("  PASO 3: PLAN DE ACCION V3")
    print("=" * 80)

    if can_trade and results:
        top = results[:3]
        print(f"""
  REGIMEN SEGURO + DIA VALIDO + {len(results)} SENALES = OPERAR

  Top {len(top)} oportunidades (max 3 posiciones):
""")
        for i, s in enumerate(top, 1):
            print(f"  {i}. {s['Ticker']:<6} @ ${s['Precio']}")
            print(f"     RSI: {s['RSI']} | {s['vs SMA50']} bajo SMA50 | Score: {s['Score']}")
            print(f"     MACD Accel: {s['MACD Acc']} | Vol: {s['Vol']}")
            print(f"     Stop: {s['Stop']} ({s['Riesgo']} riesgo) | Target: {s['Target']} (+3%)")
            print()

        print(f"""  REGLAS V3:
  - Comprar al OPEN del dia siguiente
  - Posicion: max 10% del portfolio por trade
  - Stop loss: precio de 'Stop' — vender SIN pensar si lo toca
  - Take profit: vender 50% si sube 3% en primeros 3 dias
  - Holding: {V3_HOLDING_DAYS} dias habiles, despues cerrar
  - ANTI-KNIFE: no comprar mismo ticker en 5 dias
  - NUNCA promediar para abajo
""")
    elif can_trade and not results:
        print("""
  REGIMEN SEGURO + DIA VALIDO pero SIN SENALES V3.
  V3 es muy selectiva (RSI<25, Vol<0.8x, SMA -15%/-10%).
  Esto genera ~15-25 trades por periodo vs 82 de Final.
  No forzar trades. Revisar manana.
""")
    elif not is_safe:
        print("""
  REGIMEN PELIGROSO — NO OPERAR.
  Mantener efectivo. Esperar estabilidad del mercado.
""")
    else:
        print(f"""
  Hoy es {dia_nombre} — V3 no opera este dia.
  Solo opera Miercoles y Jueves (mejores dias segun backtests).
  Revisar el proximo dia valido.
""")

    # ── Summary ──────────────────────────────────────────────────────────
    if can_trade and results:
        decision = "OPERAR"
    else:
        reasons = []
        if not is_safe:
            reasons.append("regimen peligroso")
        if weekday not in V3_DIAS_OK:
            reasons.append(f"dia no valido ({dia_nombre})")
        if not results:
            reasons.append("sin senales V3")
        decision = f"ESPERAR ({', '.join(reasons)})"

    print(f"  >>> DECISION: {decision} <<<")
    print(f"  Ejecutar: python invertir_v3.py")


if __name__ == '__main__':
    main()
