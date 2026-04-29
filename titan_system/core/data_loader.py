"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TITAN SYSTEM — Descargador de Datos Históricos (data_loader.py)            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  CONCEPTOS CLAVE:                                                            ║
║                                                                              ║
║  1. DESCARGA INCREMENTAL:                                                    ║
║     En vez de descargar TODO cada vez, chequeamos cuál es la última          ║
║     fecha que ya tenemos y solo descargamos desde ahí.                       ║
║     Primera vez: descarga 2 años completos.                                  ║
║     Siguientes veces: descarga solo los días nuevos.                         ║
║                                                                              ║
║  2. CONCURRENCIA (ThreadPoolExecutor):                                       ║
║     Descargar 260 tickers UNO POR UNO tarda ~10 minutos.                    ║
║     Descargando 10 EN PARALELO tarda ~1 minuto.                             ║
║     ThreadPoolExecutor maneja los hilos automáticamente.                    ║
║                                                                              ║
║     ¿Qué es un hilo (thread)?                                               ║
║     Tu CPU puede hacer varias cosas al mismo tiempo.                         ║
║     Mientras ESPERA la respuesta de Yahoo para AAPL, puede                  ║
║     PEDIR datos de MSFT en otro hilo. Es como tener 10 ventanas            ║
║     del browser abiertas cargando al mismo tiempo.                          ║
║                                                                              ║
║  3. RATE LIMITING:                                                           ║
║     Yahoo Finance tiene límites de requests. Si mandás 260 requests          ║
║     en 1 segundo, te bloquean. Espaciamos las requests con un delay.        ║
║                                                                              ║
║  4. RETRY / ERROR HANDLING:                                                  ║
║     Internet no es perfecto. A veces Yahoo no responde, o manda datos       ║
║     parciales. Tenemos reintentos automáticos y manejo de errores.          ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import time
import sys
import os
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Dict

import pandas as pd
import yfinance as yf
import yfinance.cache as yf_cache

# Importamos nuestra base de datos
from titan_system.core.database import TitanDB


# ── Colores para la consola ──────────────────────────────────────────────────
R = "\033[91m"; G = "\033[92m"; Y = "\033[93m"; C = "\033[96m"
W = "\033[97m"; DIM = "\033[2m"; BOLD = "\033[1m"; RST = "\033[0m"

# Algunos entornos inyectan un proxy dummy local (127.0.0.1:9) que rompe
# curl_cffi/yfinance. Solo neutralizamos ese valor puntual para no pisar
# proxies legitimos del usuario.
PROXY_ENV_VARS = [
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
    "GIT_HTTP_PROXY", "GIT_HTTPS_PROXY",
]
BOGUS_PROXY_MARKERS = ("127.0.0.1:9", "localhost:9")
DOWNLOAD_SYMBOL_ALIASES = {
    "VIX": "^VIX",
}
RECENT_INVALID_LOOKBACK_DAYS = 15


def _neutralize_bogus_proxy_env() -> list[str]:
    cleared = []
    for env_name in PROXY_ENV_VARS:
        value = os.environ.get(env_name, "")
        lower_value = value.lower()
        if value and any(marker in lower_value for marker in BOGUS_PROXY_MARKERS):
            os.environ.pop(env_name, None)
            cleared.append(env_name)
    return cleared


_CLEARED_PROXY_VARS = _neutralize_bogus_proxy_env()

# yfinance usa una cache SQLite propia. En entornos sandboxed de Windows,
# la ubicacion default puede no ser escribible. La movemos al proyecto.
YF_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "yfinance"
YF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
yf.set_tz_cache_location(str(YF_CACHE_DIR))
yf_cache.set_cache_location(str(YF_CACHE_DIR))


# ── Universo de activos (mismo que TITAN v5) ─────────────────────────────────
ACTIVOS = [
    'AAL','AAP','AAPL','ABBV','ABEV','ABT','ACN','ADBE','ADI','ADP',
    'AEG','AEM','AGRO','AIG','AMAT','AMD','AMGN','AMX','AMZN',
    'ANF','ARCO','ARM','ASR','AVGO','AVY','AXP','AZN','BA',
    'BABA','BAC','BAK','BB','BBD','BBVA','BG','BHP','BIDU',
    'BIIB','BK','BKNG','BKR','BMY','BP','BSBR','C',
    'CAAP','CAH','CAR','CAT','CCL','CDE','CL','COIN',
    'COST','CRM','CSCO','CVS','CVX','CX','DAL','DD','DE',
    'DEO','DHR','DIS','DOCU','DOW','E','EA','EBAY',
    'EFX','EQNR','ERIC','ETSY','FCX','FDX','FMX',
    'FSLR','GE','GFI','GGB','GILD','GLOB','GLW','GM','GOLD',
    'GOOGL','GPRK','GRMN','GS','GSK','GT','HAL','HD','HDB','HL',
    'HMC','HMY','HOG','HON','HPQ','HSBC','HSY','HWM','IBM',
    'IBN','IFF','INFY','ING','INTC','IP','ISRG','ITUB','JCI','JD',
    'JNJ','JPM','KB','KEP','KGC','KMB','KO','KOF','LAC','LAR',
    'LLY','LMT','LND','LRCX','LVS','LYG','MA',
    'MCD','MDLZ','MDT','MELI','META','MFG','MMM','MO','MRK',
    'MRNA','MRVL','MSFT','MSI','MUFG','MUX','NEM','NFLX','NG','NGG',
    'NIO','NKE','NMR','NOK','NTES','NU','NUE','NVDA',
    'NVS','NXE','ORCL','ORLY','PAAS','PAC',
    'PAGS','PBI','PBR','PCAR','PEP','PFE','PG','PHG','PINS',
    'PKX','PLTR','PM','PSO','PSX','PYPL','QCOM','RACE','RIO',
    'RIOT','ROKU','ROST','RTX','SAN','SAP','SBS','SBUX','SCCO','SCHW',
    'SE','SHEL','SHOP','SID','SIEGY','SLB','SNA','SNAP',
    'SNOW','SONY','SPGI','SPOT','STLA','STNE','SUZ','SWKS',
    'SYY','T','TCOM','TGT','TIMB','TJX','TMO',
    'TMUS','TRIP','TRV','TS','TSLA','TSM','TTE','TV','TWLO','TX',
    'TXN','UGP','UL','UNH','UNP','URBN','USB','V','VALE','VIST',
    'VIV','VOD','VRSN','VZ','WFC','WMT','XOM',
    'XP','XRX','YELP','ZM',
    # Tickers canonicos usados por los scanners V10/V11 que faltaban
    # en el descargador. El loader puede ser mas amplio que el scanner,
    # pero nunca mas angosto.
    'ABNB','AI','ALAB','ASML','ASTS','B','BCS','CRWV','F','HOOD',
    'IREN','MOS','MSTR','MU','OXY','PANW','PATH','RBLX','RGTI','RKLB',
    'SPCE','TEAM','TM','UAL','UBER','UPST',
]

# Activos de contexto (para detección de régimen macro)
CONTEXT_TICKERS = ['SPY', 'QQQ', 'IWM', 'VIX', 'TLT', 'GLD', 'HYG',
                   'UUP', 'XLE', 'XLF', 'XLK', 'XLV']

# Mapa de sectores (para análisis de performance por sector)
SECTOR_MAP = {
    'tech': ['AAPL','MSFT','GOOGL','META','AMZN','ADBE','CRM','ORCL','ACN','IBM',
             'CSCO','INFY','SAP','DOCU','EA','EBAY','GLOB','SNAP','SPOT','TWLO',
             'VRSN','ZM','SNOW','PLTR','ERIC','NOK'],
    'semis': ['NVDA','AMD','AVGO','QCOM','INTC','AMAT','LRCX','ADI','MRVL','ARM',
              'TXN','TSM','SWKS','FSLR'],
    'finance': ['JPM','BAC','GS','C','V','MA','AXP','PYPL','SCHW','BK','HSBC',
                'ING','BBVA','SAN','ITUB','BBD','NU','WFC','USB','BSBR','LYG',
                'MUFG','NMR','KB','KEP','IBN','HDB','MFG','PKX','BKR','AIG',
                'COIN','XP','PAGS','STNE'],
    'energy': ['XOM','CVX','BP','SHEL','SLB','HAL','EQNR','TTE','PSX','PBR'],
    'mining': ['GOLD','NEM','VALE','FCX','BHP','RIO','AEM','GFI','HMY','KGC',
               'PAAS','HL','CDE','SCCO','MUX','NXE','LAC','GGB','SID'],
    'health': ['JNJ','PFE','MRK','ABBV','LLY','UNH','ABT','AMGN','GILD','BIIB',
               'BMY','MDT','DHR','TMO','ISRG','MRNA','CVS','AZN','NVS','GSK'],
    'consumer': ['KO','PEP','WMT','COST','MCD','SBUX','NKE','HD','DIS','PG','CL',
                 'KMB','MDLZ','PM','MO','TGT','TJX','ROST','ORLY','HSY','ANF',
                 'URBN','BKNG','TRIP','LVS','CCL','HOG','RACE','SHOP','MELI',
                 'BABA','JD','NTES','SE','ROKU','ETSY'],
    'industrial': ['CAT','DE','BA','HON','GE','RTX','LMT','FDX','GM','DAL','AAL',
                   'MMM','DD','AVY','GRMN','SNA','PCAR','HWM','JCI','UNP','SYY',
                   'IP','GLW','GT','CAR','STLA','HMC','TSLA','NIO'],
    'telecom': ['T','VZ','TMUS','VOD'],
    'latam': ['ABEV','AGRO','AMX','ARCO','ASR','CAAP','CX','FMX','GGB','GPRK',
              'KOF','LAR','LND','PAC','SBS','SID','SUZ','TIMB','TV','TX','UGP',
              'VIV','VIST'],
}

# Invertir: de ticker → sector
TICKER_SECTOR = {}
for sector, tickers in SECTOR_MAP.items():
    for t in tickers:
        TICKER_SECTOR[t] = sector


def get_sector(ticker: str) -> str:
    """Devuelve el sector de un ticker, o 'other' si no está mapeado."""
    return TICKER_SECTOR.get(ticker, 'other')


class DataLoader:
    """
    Descargador inteligente de datos históricos.

    Maneja:
    - Descarga inicial (2 años de historia)
    - Actualizaciones incrementales (solo días nuevos)
    - Concurrencia (múltiples descargas en paralelo)
    - Reintentos automáticos en caso de error
    - Barra de progreso en consola
    """

    def __init__(self, db: TitanDB, years_history: int = 2,
                 max_workers: int = 10, max_retries: int = 3,
                 retry_sleep: float = 0.75):
        """
        Parámetros:
        -----------
        db : TitanDB
            Instancia de la base de datos
        years_history : int
            Cuántos años de historia descargar la primera vez
        max_workers : int
            Cuántas descargas en paralelo (cuidado: >15 puede triggerear
            rate limits de Yahoo Finance)

        CONCEPTO — Dependency Injection:
        --------------------------------
        En vez de crear la DB dentro de DataLoader, la RECIBIMOS como
        parámetro. Esto se llama "dependency injection" y es un patrón
        fundamental de diseño de software:

        Ventajas:
        1. DataLoader no necesita saber CÓMO crear la DB
        2. Podemos pasar una DB de test, una DB en memoria, etc.
        3. Múltiples componentes comparten la MISMA conexión a la DB
        4. Es más fácil de testear (se puede mockear la DB)

        En entrevistas, si mencionás dependency injection,
        demuestras que pensás en diseño de software profesional.
        """
        self.db = db
        self.years_history = years_history
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep

    def download_all(self, tickers: Optional[List[str]] = None,
                     include_context: bool = True,
                     force_full: bool = False,
                     end_date: Optional[str] = None) -> Dict[str, int]:
        """
        Descarga datos para todos los tickers.

        Parámetros:
        -----------
        tickers : list, opcional
            Lista de tickers a descargar. Si es None, usa ACTIVOS completo.
        include_context : bool
            Si True, también descarga SPY, VIX, etc para régimen
        force_full : bool
            Si True, descarga todo desde cero (ignora datos existentes)

        Returns:
        --------
        dict con estadísticas: {'success': N, 'failed': N, 'total_rows': N}

        CONCEPTO — as_completed():
        --------------------------
        ThreadPoolExecutor.submit() lanza tareas en hilos paralelos.
        as_completed() devuelve las tareas A MEDIDA QUE TERMINAN
        (no en el orden en que se lanzaron).

        Esto es ideal para barras de progreso: mostrás el avance
        real sin esperar a que todas terminen en orden.
        """
        all_tickers = list(tickers or ACTIVOS)
        if include_context:
            for ctx in CONTEXT_TICKERS:
                if ctx not in all_tickers:
                    all_tickers.append(ctx)

        total = len(all_tickers)
        print(f"\n  {BOLD}{C}DESCARGA DE DATOS HISTORICOS{RST}")
        print(f"  {'-' * 50}")
        print(f"  Tickers: {total} | Workers: {self.max_workers} | "
              f"Historia: {self.years_history} años")
        print(f"  Modo: {'COMPLETO (forzado)' if force_full else 'INCREMENTAL (solo datos nuevos)'}")
        if end_date:
            print(f"  Hasta fecha: {end_date}")
        print(f"  {'-' * 50}\n")

        results = {'success': 0, 'failed': 0, 'skipped': 0, 'empty': 0,
                   'total_rows': 0, 'errors': [], 'empty_details': []}
        completed = 0

        # Pre-cargar todas las fechas en el hilo principal antes de lanzar workers.
        # Los workers NO deben acceder a la DB (SQLite no es thread-safe para
        # objetos creados en otro hilo). Esta query trae todo en un solo round-trip.
        if not force_full:
            latest_dates = self.db.get_all_latest_dates()
        else:
            latest_dates = {}

        # ThreadPoolExecutor: crea un "pool" de workers (hilos)
        # Le damos tareas y el las distribuye entre los hilos disponibles
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:

            # Lanzar todas las tareas en paralelo
            # future_to_ticker: mapea cada "futuro" al ticker que descarga
            future_to_ticker = {}
            for ticker in all_tickers:
                future = executor.submit(
                    self._download_one, ticker, force_full,
                    latest_dates.get(ticker), end_date
                )
                future_to_ticker[future] = ticker

            # Procesar resultados a medida que terminan
            for future in as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                completed += 1

                try:
                    # .result() obtiene el resultado del hilo
                    ticker_result, df, status_code, detail = future.result()

                    if status_code == 'ok' and df is not None:
                        # Escritura a DB en el hilo principal (thread-safe)
                        rows_saved = self.db.save_prices(df, ticker_result)
                        results['success'] += 1
                        results['total_rows'] += rows_saved
                        status = f"{G}+ {rows_saved} filas{RST}"
                    elif status_code == 'skip':
                        results['skipped'] += 1
                        status = f"{DIM}= al dia{RST}"
                    elif status_code == 'empty':
                        results['empty'] += 1
                        if detail:
                            results['empty_details'].append(f"{ticker}: {detail}")
                        status = f"{Y}! sin datos{RST}"
                    else:
                        results['failed'] += 1
                        detail_text = detail or status_code
                        results['errors'].append(f"{ticker}: {detail_text}")
                        status = f"{R}x {detail_text[:25]}{RST}"

                except Exception as e:
                    results['failed'] += 1
                    results['errors'].append(f"{ticker}: {str(e)[:50]}")
                    status = f"{R}x {str(e)[:25]}{RST}"

                # Barra de progreso
                pct = completed / total * 100
                bar_len = 30
                filled = int(bar_len * completed / total)
                bar = f"{G}{'#' * filled}{DIM}{'.' * (bar_len - filled)}{RST}"
                print(f"\r  {bar} {pct:5.1f}% | {completed}/{total} | "
                      f"{ticker:6s} {status}          ", end='', flush=True)

        # Resumen final
        print(f"\n\n  {'-' * 50}")
        print(f"  {G}[OK] Exitosos: {results['success']}{RST}")
        print(f"  {DIM}[==] Al dia:   {results['skipped']}{RST}")
        if results['empty'] > 0:
            print(f"  {Y}[??] Sin datos: {results['empty']}{RST}")
            for detail in results['empty_details'][:5]:
                print(f"    {DIM}{detail}{RST}")
        if results['failed'] > 0:
            print(f"  {R}[!!] Fallidos: {results['failed']}{RST}")
            for err in results['errors'][:5]:
                print(f"    {DIM}{err}{RST}")
        print(f"  {BOLD}Total filas guardadas: {results['total_rows']}{RST}")
        print(f"  {'-' * 50}\n")

        return results

    def _download_one(self, ticker: str, force_full: bool = False,
                      latest_date: Optional[str] = None,
                      end_date: Optional[str] = None):
        """
        Descarga datos de UN ticker (llamado por los hilos del pool).

        CONCEPTO — Descarga incremental:
        ---------------------------------
        1. Recibe la ultima fecha pre-cargada desde el hilo principal.
        2. Si no tiene nada -> descargamos 2 anios completos
        3. Si tiene hasta 2024-03-20 -> descargamos desde 2024-03-21

        Returns: (ticker, DataFrame) tuple — la escritura a DB se hace
        en el hilo principal para evitar problemas de concurrencia con SQLite.

        CONCEPTO — Thread Safety:
        -------------------------
        SQLite no permite usar objetos de conexion creados en otro hilo.
        Solucion: el hilo principal pre-carga todas las fechas con
        get_all_latest_dates() ANTES de lanzar workers, y las pasa como
        parametro. Los workers solo DESCARGAN (I/O de red), nunca tocan la DB.
        El hilo principal ESCRIBE a la DB al recibir cada resultado.
        Este patron se llama "producer-consumer".
        """
        try:
            today_str = datetime.now().strftime('%Y-%m-%d')

            # Determinar desde cuando descargar
            if force_full:
                start_date = (datetime.now() - timedelta(
                    days=365 * self.years_history)).strftime('%Y-%m-%d')
            else:
                # latest_date fue pre-cargado en el hilo principal (thread-safe)
                if latest_date:
                    start_date = (datetime.strptime(latest_date, '%Y-%m-%d')
                                  + timedelta(days=1)).strftime('%Y-%m-%d')
                    # Si no se fijo una fecha objetivo explicita, evitamos pedir
                    # la rueda de HOY para no consumir una barra parcial.
                    # Pero si end_date la pide de forma explicita (pipeline post-cierre),
                    # debemos permitir start_date == hoy para descargar la rueda recien cerrada.
                    if end_date is None and start_date >= today_str:
                        return (ticker, None, 'skip', None)
                else:
                    start_date = (datetime.now() - timedelta(
                        days=365 * self.years_history)).strftime('%Y-%m-%d')

            if end_date and start_date > end_date:
                return (ticker, None, 'skip', None)

            # Descargar de Yahoo Finance
            request_symbol = DOWNLOAD_SYMBOL_ALIASES.get(ticker, ticker)
            history_kwargs = {
                'start': start_date,
                'auto_adjust': False,
                'timeout': 30,
            }
            if end_date:
                end_exclusive = (
                    datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                ).strftime('%Y-%m-%d')
                history_kwargs['end'] = end_exclusive

            last_error = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    tk = yf.Ticker(request_symbol)
                    df = tk.history(**history_kwargs)
                    time.sleep(0.15)

                    if df is None or df.empty:
                        detail = (
                            f"sin datos desde {start_date}"
                            + (f" hasta {end_date}" if end_date else "")
                        )
                        if request_symbol != ticker:
                            detail += f" (alias {request_symbol})"
                        return (ticker, None, 'empty', detail)

                    return (ticker, df, 'ok', None)
                except Exception as exc:
                    last_error = str(exc)[:120]
                    if attempt < self.max_retries:
                        time.sleep(self.retry_sleep * attempt)
                    else:
                        break

            return (ticker, None, 'error', f"retry agotado: {last_error}")

        except Exception as e:
            return (ticker, None, 'error', str(e)[:80])

    def find_recent_invalid_rows(
        self,
        end_date: str,
        lookback_days: int = RECENT_INVALID_LOOKBACK_DAYS,
    ) -> pd.DataFrame:
        """Devuelve filas recientes con OHLCV severamente invalido."""
        end_day = datetime.strptime(end_date, '%Y-%m-%d').date()
        start_date = (end_day - timedelta(days=lookback_days)).isoformat()
        invalid_rows = self.db.execute_raw(
            """
            SELECT ticker, date, open, high, low, close, volume
            FROM prices
            WHERE date >= ?
              AND date <= ?
              AND (
                    open <= 0
                 OR high <= 0
                 OR low <= 0
                 OR close <= 0
                 OR volume < 0
                 OR high < low
              )
            ORDER BY ticker ASC, date ASC
            """,
            (start_date, end_date),
        )
        if not invalid_rows.empty:
            invalid_rows['date'] = pd.to_datetime(invalid_rows['date']).dt.date
        return invalid_rows

    def update_daily(self, end_date: Optional[str] = None) -> Dict[str, int]:
        """
        Actualización diaria rápida.
        Solo descarga los datos de hoy/ayer para todos los tickers.

        CONCEPTO — Patrón de actualización:
        -----------------------------------
        Este método está diseñado para correr TODOS LOS DÍAS.
        Es "idempotente": si lo corrés 3 veces en el mismo día,
        no pasa nada malo (INSERT OR REPLACE evita duplicados).
        """
        print(f"\n  {BOLD}{C}ACTUALIZACION DIARIA{RST}")
        return self.download_all(force_full=False, end_date=end_date)

    def refresh_recent_invalid_rows(self, end_date: str, lookback_days: int = 15) -> Dict[str, object]:
        """
        Reconsulta tickers con OHLCV severamente invalido en una ventana reciente.

        El update incremental no vuelve a pedir una rueda ya presente en la DB.
        Si un proveedor devolvio una barra corrupta para el ultimo cierre, ese
        dato puede quedar pegado indefinidamente hasta que se fuerce un refetch
        puntual desde la fecha afectada.
        """
        invalid = self.find_recent_invalid_rows(end_date=end_date, lookback_days=lookback_days)
        if invalid.empty:
            return {
                'invalid_rows': 0,
                'affected_tickers': [],
                'refetched_rows': 0,
                'refreshed_tickers': [],
                'remaining_rows': 0,
                'remaining_tickers': [],
                'remaining_details': [],
                'errors': [],
            }

        affected_tickers = sorted({str(ticker) for ticker in invalid['ticker'].tolist()})
        refetched_rows = 0
        refreshed_tickers: list[str] = []
        errors: list[str] = []

        for ticker in affected_tickers:
            ticker_rows = invalid.loc[invalid['ticker'] == ticker]
            earliest_bad_date = ticker_rows['date'].min()
            latest_before = (earliest_bad_date - timedelta(days=1)).isoformat()
            ticker_result, df, status_code, detail = self._download_one(
                ticker,
                force_full=False,
                latest_date=latest_before,
                end_date=end_date,
            )
            if status_code == 'ok' and df is not None and not df.empty:
                saved_rows = int(self.db.save_prices(df, ticker_result) or 0)
                refetched_rows += saved_rows
                refreshed_tickers.append(ticker)
            else:
                errors.append(f"{ticker}: {detail or status_code}")

        remaining = self.find_recent_invalid_rows(end_date=end_date, lookback_days=lookback_days)
        remaining_tickers = (
            sorted({str(ticker) for ticker in remaining['ticker'].tolist()})
            if not remaining.empty
            else []
        )
        remaining_details = [
            (
                f"{row.ticker} {row.date.isoformat()} | "
                f"O={row.open:.4f} H={row.high:.4f} L={row.low:.4f} "
                f"C={row.close:.4f} V={int(row.volume)}"
            )
            for row in remaining.head(12).itertuples(index=False)
        ]
        return {
            'invalid_rows': int(len(invalid)),
            'affected_tickers': affected_tickers,
            'refetched_rows': refetched_rows,
            'refreshed_tickers': refreshed_tickers,
            'remaining_rows': int(len(remaining)),
            'remaining_tickers': remaining_tickers,
            'remaining_details': remaining_details,
            'errors': errors,
        }

    def get_prices_df(self, tickers: Optional[List[str]] = None,
                      start_date: Optional[str] = None,
                      end_date: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        """
        Obtiene precios de la DB como diccionario de DataFrames.

        Este método REEMPLAZA la descarga directa de Yahoo Finance
        en los modelos TITAN. En vez de:
            df = yf.download('AAPL', ...)  # lento, red
        Ahora hacemos:
            df = loader.get_prices_df(['AAPL'])  # instantáneo, local

        Returns:
        --------
        dict: {ticker: DataFrame_con_OHLCV}
        """
        tickers = tickers or ACTIVOS
        result = {}

        for ticker in tickers:
            df = self.db.get_prices(ticker, start_date, end_date)
            if not df.empty:
                # Renombrar columnas para compatibilidad con código existente
                df.columns = [c.title() if c != 'adj_close' else 'Adj Close'
                              for c in df.columns]
                # Eliminar columna 'ticker' del DataFrame (ya sabemos cuál es)
                if 'Ticker' in df.columns:
                    df = df.drop(columns=['Ticker'])
                result[ticker] = df

        return result


# ═══════════════════════════════════════════════════════════════════════════════
#  EJECUCIÓN DIRECTA: descarga todos los datos
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print(f"\n{'=' * 60}")
    print("  TITAN SYSTEM - DESCARGA DE DATOS HISTORICOS")
    print(f"{'=' * 60}")

    with TitanDB() as db:
        loader = DataLoader(db, years_history=2, max_workers=10)

        # Verificar estado actual
        stats = db.db_stats()
        print(f"\n  Estado actual de la DB:")
        print(f"  Precios: {stats['prices_count']} registros")
        print(f"  Rango:   {stats['price_date_range']}")

        # Descargar
        results = loader.download_all()

        # Verificar estado final
        stats = db.db_stats()
        print(f"\n  Estado final de la DB:")
        print(f"  Precios: {stats['prices_count']} registros")
        print(f"  Rango:   {stats['price_date_range']}")
        print(f"  Tamano:  {stats.get('db_size_mb', 0)} MB")

        # Mostrar cuántos registros por ticker (sample)
        counts = db.count_prices()
        if counts:
            sample = list(counts.items())[:10]
            print(f"\n  Muestra de datos por ticker:")
            for ticker, cnt in sample:
                print(f"    {ticker:6s} -> {cnt} dias")

    print(f"\n{'=' * 60}")
    print(f"  DESCARGA COMPLETA")
    print(f"{'=' * 60}\n")
