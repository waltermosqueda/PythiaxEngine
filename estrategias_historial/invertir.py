import yfinance as yf
import pandas as pd
import warnings
import logging

# Suprimimos warnings de la API para mantener la consola limpia
warnings.filterwarnings('ignore')

# Suprimimos los mensajes de log de yfinance que no son errores críticos
logging.getLogger('yfinance').setLevel(logging.ERROR)

# 1. Definimos la lista completa de activos a monitorear
tickers_str = """
AAPL, ADBE, ADI, AI, ALAB, AMAT, AMD, ARM, ASML, AVGO, BIDU, COIN, CRM, CRWV, CSCO, DOCU, ETSY, GOOGL, IBM, INTC, IREN, LRCX, META, MRVL, MSFT, MSTR, MU, NTES, NVDA, ORCL, PANW, PATH, PLTR, QCOM, RBLX, RGTI, ROKU, SAP, SE, SHOP, SNAP, SNOW, SONY, SPOT, TEAM, TSM, TWLO, UBER, UPST, ZM, GLW, GRMN, HPQ, MSI, SWKS, TXN, EA, ASTS, RKLB, ERIC, NOK, BB, AXP, BAC, BCS, BK, BKNG, BRK-B, BSBR, C, GS, HOOD, HSBC, ING, JPM, LYG, MA, MUFG, NU, PYPL, SAN, SCHW, STNE, USB, V, WFC, XP, PAGS, AIG, HDB, ABBV, ABT, AMGN, AZN, BIIB, BMY, CVS, DHR, GILD, GSK, ISRG, JNJ, LLY, MDT, MRK, MRNA, NVS, PFE, TMO, UNH, BKR, BP, CVX, E, EQNR, HAL, OXY, PBR, PSX, SHEL, SLB, TTE, VIST, XOM, AEM, B, BHP, CDE, FCX, GFI, GGB, HL, HMY, KGC, LAC, MOS, MUX, NEM, NG, NUE, PAAS, RIO, SCCO, SID, VALE, AAP, ABEV, ANF, ARCO, BABA, CL, COST, DEO, EBAY, HD, HSY, KMB, KO, MCD, MDLZ, MO, NKE, ORLY, PEP, PG, PM, ROST, SBUX, SYY, TGT, TJX, UL, WMT, YELP, AVY, BA, CAT, DD, DE, FDX, GE, HON, HWM, IFF, IP, LMT, MMM, PCAR, PBI, RTX, SNA, UNP, BBD, BIOX, CAAP, ELPC, EMBJ, GLOB, ITUB, LND, MELI, PAC, SATL, SBS, SUZ, TIMB, UGP, VIV, F, GM, HMC, HOG, NIO, RACE, STLA, TM, TSLA, AAL, ABNB, CAR, CCL, DAL, LVS, SPCE, TCOM, TRIP, UAL, AMX, TMUS, VOD, VZ
"""

# Limpiamos la lista y la convertimos en un array (se omitieron los tickers con sufijos complejos locales para compatibilidad directa con Yahoo Finance US)
tickers = [t.strip() for t in tickers_str.replace('\n', '').split(',') if t.strip()]

print(f"Iniciando escaneo de {len(tickers)} activos. Buscando señales críticas...\n")

# 2. Descargamos todos los datos en un solo lote para mayor eficiencia
all_data = yf.download(tickers, period="6mo", progress=False)

oportunidades = []

# 3. Iteramos sobre cada activo para procesar sus datos
for ticker in all_data['Close'].columns:
    try:
        # Extraemos solo la columna de precios de cierre para el cálculo
        close = all_data['Close'][ticker]
        
        # Filtramos activos sin suficiente historial o con errores de descarga (columna con NaNs)
        if close.count() < 35:
            continue
            
        # 4. Cálculo matemático del RSI (14 períodos)
        delta = close.diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        
        ema_up = up.ewm(com=13, adjust=False).mean()
        ema_down = down.ewm(com=13, adjust=False).mean()
        rs = ema_up / ema_down.replace(0, 1e-10) # Evitar división por cero
        rsi = 100 - (100 / (1 + rs))
        
        # 5. Cálculo del MACD (12, 26, 9)
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal_line = macd.ewm(span=9, adjust=False).mean()
        macd_hist = macd - signal_line
        
        # 6. Obtenemos los valores de la última sesión
        current_rsi = rsi.iloc[-1]
        current_macd_hist = macd_hist.iloc[-1]
        prev_macd_hist = macd_hist.iloc[-2]
        current_price = close.iloc[-1]
        
        # 7. LÓGICA DE ALERTA: RSI < 30 y el Histograma MACD empieza a curvarse hacia arriba
        if not pd.isna(current_rsi) and current_rsi < 30 and (current_macd_hist > prev_macd_hist):
            oportunidades.append({
                'Ticker': ticker,
                'Precio Actual (USD)': round(current_price, 2),
                'RSI': round(current_rsi, 2),
                'MACD Hist': round(current_macd_hist, 3)
            })
            
    except Exception as e:
        # Este bloque captura errores de cálculo para un ticker específico, no de descarga.
        # print(f"Error procesando {ticker}: {e}") # Descomentar para depuración
        pass

# 8. Procesamiento final y visualización
df_resultados = pd.DataFrame(oportunidades)

if not df_resultados.empty:
    # Ordenamos de menor a mayor RSI (los más sobrevendidos primero) y tomamos el Top 10
    top_10 = df_resultados.sort_values(by='RSI', ascending=True).head(10)
    
    print("🎯 TOP 10 OPORTUNIDADES POR SOBREVENTA EXTREMA (RSI < 30 + MACD Reversal)")
    print("-" * 65)
    print(top_10.to_string(index=False))
    print("-" * 65)
    print("\n⚠️ AVISO: El script identifica anomalías estadísticas, no garantiza un rebote. Ejecutar análisis fundamental antes de operar.")
else:
    print("No se encontraron activos en condición de sobreventa extrema estricta el día de hoy.")