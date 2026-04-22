"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TITAN SYSTEM — Backtester (backtester.py)                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  ¿QUÉ ES UN BACKTEST?                                                       ║
║  ====================                                                        ║
║  Un backtest simula cómo habría funcionado una estrategia de trading        ║
║  en el PASADO, usando datos históricos reales.                               ║
║                                                                              ║
║  Es como decir: "Si yo hubiera corrido TITAN v5 todos los días del         ║
║  último año y operado exactamente lo que me dijo, ¿habría ganado            ║
║  o perdido plata?"                                                           ║
║                                                                              ║
║  ¿POR QUÉ ES TAN IMPORTANTE?                                                ║
║  ============================                                                ║
║  Sin backtest, no sabés si tu modelo funciona. Podrías tener un modelo     ║
║  que "se ve sofisticado" pero pierde plata consistentemente.                ║
║  Con backtest, tenés EVIDENCIA objetiva.                                     ║
║                                                                              ║
║  PELIGROS DEL BACKTEST:                                                      ║
║  ======================                                                      ║
║                                                                              ║
║  1. OVERFITTING (sobreajuste):                                               ║
║     Si optimizás los parámetros del modelo para que el backtest dé           ║
║     buenos resultados, estás "haciendo trampa". El modelo memoriza          ║
║     el pasado pero no puede predecir el futuro.                              ║
║     Ejemplo: "mi modelo gana 90% en los últimos 5 años" → probablemente    ║
║     overfitteado. En el futuro, seguro no funciona.                         ║
║                                                                              ║
║  2. DATA LEAKAGE (fuga de datos):                                            ║
║     Si el modelo accidentalmente usa información del FUTURO para            ║
║     predecir el PRESENTE, los resultados son falsos.                         ║
║     Ejemplo: entrenar con datos de 2024 y testear en 2023 → trampa.        ║
║                                                                              ║
║  3. SURVIVORSHIP BIAS (sesgo de supervivencia):                              ║
║     Si solo testás con activos que existen HOY, ignorás los que             ║
║     quebraron o se deslistaron. Los que sobrevivieron tienden a ser         ║
║     ganadores → tus resultados son optimistas.                              ║
║                                                                              ║
║  NUESTRA SOLUCIÓN: WALK-FORWARD BACKTEST                                    ║
║  ========================================                                    ║
║                                                                              ║
║  Día 1: Entrenar con datos del Mes 1-6  → Predecir Mes 7                   ║
║  Día 2: Entrenar con datos del Mes 1-7  → Predecir Mes 8                   ║
║  Día 3: Entrenar con datos del Mes 1-8  → Predecir Mes 9                   ║
║  ...y así sucesivamente.                                                     ║
║                                                                              ║
║  Esto simula EXACTAMENTE lo que harías en la vida real:                      ║
║  entrenas con lo que sabés, predecís lo que no sabés.                       ║
║  No hay data leakage posible.                                                ║
║                                                                              ║
║  CONCEPTO — "Purged" Walk-Forward:                                           ║
║  Dejamos un GAP entre entrenamiento y test para evitar autocorrelación.     ║
║  Si el modelo usa retornos de 5 días, purgamos los últimos 5 días          ║
║  del set de entrenamiento para que no se filtren al test.                    ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable

from titan_system.core.database import TitanDB
from titan_system.core.data_loader import get_sector


# Colores
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; C = "\033[96m"
W = "\033[97m"; DIM = "\033[2m"; BOLD = "\033[1m"; RST = "\033[0m"


class BacktestResult:
    """
    Contenedor para los resultados de un backtest.

    CONCEPTO — Dataclass / Contenedor:
    ----------------------------------
    En vez de devolver un diccionario genérico, creamos una clase
    específica para los resultados. Ventajas:
    1. Autocompletado en el IDE
    2. Documentación clara de qué contiene
    3. Métodos para calcular métricas derivadas
    4. Se puede imprimir de forma bonita

    En Python moderno usarías @dataclass, pero lo hacemos explícito
    para que veas cada campo.
    """

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.trades: List[Dict] = []        # lista de cada trade simulado
        self.daily_returns: List[float] = [] # retorno diario del portfolio
        self.equity_curve: List[float] = []  # valor acumulado del portfolio
        self.dates: List[str] = []           # fechas de cada día
        self.metadata: Dict = {}             # info adicional

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> int:
        return sum(1 for t in self.trades if t.get('hit', False))

    @property
    def losing_trades(self) -> int:
        return self.total_trades - self.winning_trades

    @property
    def win_rate(self) -> float:
        """
        Win Rate (Accuracy): % de trades que acertaron la dirección.

        CONCEPTO — @property:
        ---------------------
        El decorador @property hace que un método funcione como un
        atributo. En vez de: result.win_rate()  (con paréntesis)
        Podés hacer: result.win_rate             (sin paréntesis)

        Es azúcar sintáctica, pero hace el código más limpio.
        """
        if self.total_trades == 0:
            return 0
        return self.winning_trades / self.total_trades * 100

    @property
    def total_return(self) -> float:
        """Retorno total acumulado (%)."""
        if not self.equity_curve:
            return 0
        return (self.equity_curve[-1] / self.equity_curve[0] - 1) * 100

    @property
    def sharpe_ratio(self) -> float:
        """
        Sharpe Ratio: retorno ajustado por riesgo.

        CONCEPTO — Sharpe Ratio:
        ------------------------
        Es LA métrica más usada en finanzas para evaluar estrategias.
        Fórmula: (retorno_promedio - tasa_libre_riesgo) / volatilidad

        Interpretación:
          < 0.5: malo
          0.5-1.0: mediocre
          1.0-1.5: bueno
          1.5-2.0: muy bueno
          > 2.0: excelente (sospechoso si es mucho mayor)

        Usamos retornos diarios anualizados (×√252 días de trading).
        La tasa libre de riesgo la asumimos 0 por simplicidad.
        """
        if len(self.daily_returns) < 10:
            return 0
        returns = np.array(self.daily_returns)
        if returns.std() == 0:
            return 0
        # Anualizar: √252 porque hay ~252 días de trading al año
        return float(returns.mean() / returns.std() * np.sqrt(252))

    @property
    def sortino_ratio(self) -> float:
        """
        Sortino Ratio: como Sharpe pero solo penaliza volatilidad NEGATIVA.

        CONCEPTO — ¿Por qué Sortino es mejor que Sharpe?
        Sharpe penaliza TODA la volatilidad, incluyendo la positiva.
        Si tu modelo tiene días de +5% seguidos de +3%, Sharpe dice
        "mucha volatilidad" aunque toda sea ganancia.
        Sortino solo penaliza los días negativos (downside deviation).
        """
        if len(self.daily_returns) < 10:
            return 0
        returns = np.array(self.daily_returns)
        negative_returns = returns[returns < 0]
        if len(negative_returns) == 0 or negative_returns.std() == 0:
            return float('inf') if returns.mean() > 0 else 0
        return float(returns.mean() / negative_returns.std() * np.sqrt(252))

    @property
    def max_drawdown(self) -> float:
        """
        Maximum Drawdown: la peor caída desde un máximo hasta un mínimo.

        CONCEPTO — Max Drawdown:
        -----------------------
        Si tu portfolio llegó a $1000 y después cayó a $800,
        el drawdown es -20%. Es la métrica de RIESGO más importante.

        Un drawdown de -50% necesita +100% para recuperarse.
        Un drawdown de -30% necesita +43% para recuperarse.

        Los fondos profesionales se preocupan MUCHO por esto.
        Un Sharpe de 2.0 con max drawdown de -50% no sirve
        porque la mayoría de inversores venden en pánico antes
        de que el modelo se recupere.
        """
        if not self.equity_curve:
            return 0
        curve = np.array(self.equity_curve)
        peak = np.maximum.accumulate(curve)
        drawdown = (curve - peak) / peak
        return float(drawdown.min() * 100)

    @property
    def profit_factor(self) -> float:
        """
        Profit Factor: ganancias brutas / pérdidas brutas.

        > 1.0 = gana más de lo que pierde (rentable)
        > 1.5 = bueno
        > 2.0 = muy bueno
        """
        gains = sum(t['return'] for t in self.trades if t.get('return', 0) > 0)
        losses = abs(sum(t['return'] for t in self.trades if t.get('return', 0) < 0))
        if losses == 0:
            return float('inf') if gains > 0 else 0
        return gains / losses

    @property
    def expectancy(self) -> float:
        """
        Expectancy: ganancia promedio esperada por trade (%).

        Si expectancy > 0, el sistema es rentable a largo plazo.
        Es la métrica más honesta: resume win_rate + avg_win + avg_loss
        en un solo número.
        """
        if self.total_trades == 0:
            return 0
        return sum(t.get('return', 0) for t in self.trades) / self.total_trades

    def summary(self) -> Dict[str, Any]:
        """Resumen completo como diccionario."""
        return {
            'model': self.model_name,
            'total_trades': self.total_trades,
            'win_rate': round(self.win_rate, 2),
            'total_return': round(self.total_return, 2),
            'sharpe_ratio': round(self.sharpe_ratio, 2),
            'sortino_ratio': round(self.sortino_ratio, 2),
            'max_drawdown': round(self.max_drawdown, 2),
            'profit_factor': round(self.profit_factor, 2),
            'expectancy': round(self.expectancy, 4),
        }

    def print_report(self):
        """Imprime el reporte de backtest en consola."""
        s = self.summary()
        print(f"\n  {'═' * 60}")
        print(f"  {BOLD}BACKTEST REPORT — {self.model_name}{RST}")
        print(f"  {'═' * 60}")
        print(f"  Período:         {self.dates[0] if self.dates else '?'} → "
              f"{self.dates[-1] if self.dates else '?'}")
        print(f"  Total trades:    {s['total_trades']}")
        print(f"  Win Rate:        {_fmt_acc(s['win_rate'])}")
        print(f"  Total Return:    {_fmt_ret(s['total_return'])}")
        print(f"  Sharpe Ratio:    {_fmt_sharpe(s['sharpe_ratio'])}")
        print(f"  Sortino Ratio:   {_fmt_sharpe(s['sortino_ratio'])}")
        print(f"  Max Drawdown:    {R}{s['max_drawdown']:.2f}%{RST}")
        print(f"  Profit Factor:   {_fmt_pf(s['profit_factor'])}")
        print(f"  Expectancy:      {_fmt_ret(s['expectancy'])}% per trade")
        print(f"  {'═' * 60}\n")


class Backtester:
    """
    Walk-Forward Backtester para estrategias de trading ML.

    CÓMO FUNCIONA:
    ==============

    1. Recibe una STRATEGY FUNCTION — una función que, dados precios
       históricos, genera predicciones (lista de picks).

    2. Simula día por día:
       - Le da a la strategy los datos HASTA ayer (no incluye hoy)
       - La strategy genera picks
       - Al "día siguiente", verifica si acertó
       - Registra el resultado

    3. Al final, calcula todas las métricas.

    CONCEPTO — Strategy como función (Higher-Order Functions):
    ---------------------------------------------------------
    En vez de hardcodear TITAN v5 adentro del backtester, recibimos
    una FUNCIÓN como parámetro. Esto se llama "higher-order function"
    y es un concepto fundamental de programación funcional.

    Ventaja: el mismo backtester sirve para CUALQUIER modelo.
    Solo cambiás la función strategy.

    Ejemplo:
        def mi_estrategia(prices_dict, date):
            # ... lógica de ML ...
            return [{'ticker': 'AAPL', 'direction': 'UP', 'confidence': 0.7}]

        bt = Backtester(db)
        result = bt.run(mi_estrategia, 'MI_MODELO', ...)
    """

    def __init__(self, db: TitanDB):
        self.db = db

    def run(self, strategy_fn: Callable,
            model_name: str,
            tickers: List[str],
            start_date: str,
            end_date: str,
            top_n: int = 10,
            purge_days: int = 5,
            commission_pct: float = 0.001) -> BacktestResult:
        """
        Ejecuta el backtest walk-forward.

        Parámetros:
        -----------
        strategy_fn : callable
            Función que recibe (prices_dict, tickers, date) y devuelve
            lista de picks [{ticker, direction, confidence, score}]
        model_name : str
            Nombre identificador del modelo
        tickers : list
            Universo de tickers para operar
        start_date : str
            Fecha de inicio del backtest (YYYY-MM-DD)
        end_date : str
            Fecha de fin del backtest (YYYY-MM-DD)
        top_n : int
            Cuántos picks tomar por día (top N por score)
        purge_days : int
            Días de gap entre entrenamiento y predicción
            para evitar data leakage por autocorrelación
        commission_pct : float
            Comisión por trade (0.001 = 0.1% = $1 por cada $1000)
            Broker típico en EEUU: 0.0% (gratis en Robinhood/IBKR)
            Broker típico en Argentina: 0.5-1.5%

        Returns:
        --------
        BacktestResult con todas las métricas
        """
        result = BacktestResult(model_name)
        result.metadata = {
            'start_date': start_date,
            'end_date': end_date,
            'top_n': top_n,
            'purge_days': purge_days,
            'commission_pct': commission_pct,
            'n_tickers': len(tickers),
        }

        # Cargar TODOS los precios necesarios de la DB de una vez
        # (mucho más eficiente que cargar día por día)
        print(f"\n  {C}Cargando datos de {len(tickers)} tickers...{RST}")
        all_prices = {}
        for ticker in tickers:
            df = self.db.get_prices(ticker, start_date=None, end_date=end_date)
            if not df.empty and len(df) > 60:  # mínimo 60 días de historia
                # Renombrar columnas para compatibilidad
                df.columns = [c.title() if c != 'adj_close' else 'Adj Close'
                              for c in df.columns]
                if 'Ticker' in df.columns:
                    df = df.drop(columns=['Ticker'])
                all_prices[ticker] = df

        if not all_prices:
            print(f"  {R}ERROR: No hay suficientes datos para backtest{RST}")
            return result

        valid_tickers = list(all_prices.keys())
        print(f"  {G}[OK]{RST} {len(valid_tickers)} tickers con datos suficientes")

        # Generar lista de fechas de trading en el rango
        # Usamos las fechas de SPY (o el primer ticker) como referencia
        ref_ticker = 'SPY' if 'SPY' in all_prices else valid_tickers[0]
        ref_prices = all_prices[ref_ticker]
        trading_dates = ref_prices.loc[start_date:end_date].index

        if len(trading_dates) < 2:
            print(f"  {R}ERROR: No hay suficientes fechas en el rango{RST}")
            return result

        print(f"  Período: {trading_dates[0].strftime('%Y-%m-%d')} → "
              f"{trading_dates[-1].strftime('%Y-%m-%d')} "
              f"({len(trading_dates)} días)")
        print(f"  Simulando...\n")

        # ── SIMULACIÓN DÍA POR DÍA ──────────────────────────────────────────
        equity = 100000  # capital inicial $100,000
        result.equity_curve.append(equity)

        for i in range(len(trading_dates) - 1):
            current_date = trading_dates[i]
            next_date = trading_dates[i + 1]
            date_str = current_date.strftime('%Y-%m-%d')
            next_str = next_date.strftime('%Y-%m-%d')

            # Preparar datos HASTA hoy (sin incluir mañana → sin data leakage)
            prices_until_today = {}
            for ticker in valid_tickers:
                df = all_prices[ticker]
                # Solo datos hasta current_date (inclusive)
                mask = df.index <= current_date
                if mask.sum() > 60:
                    prices_until_today[ticker] = df[mask].copy()

            if len(prices_until_today) < 20:
                continue

            # Ejecutar la strategy function
            try:
                picks = strategy_fn(prices_until_today, valid_tickers, date_str)
            except Exception as e:
                continue

            if not picks:
                result.daily_returns.append(0)
                result.dates.append(date_str)
                result.equity_curve.append(equity)
                continue

            # Tomar solo los top_n picks
            picks = sorted(picks, key=lambda x: x.get('score', 0), reverse=True)
            picks = picks[:top_n]

            # Evaluar cada pick
            day_return = 0
            n_valid = 0

            for pick in picks:
                ticker = pick['ticker']
                direction = pick.get('direction', 'UP')

                if ticker not in all_prices:
                    continue

                df = all_prices[ticker]

                # Verificar que tenemos precio para ambas fechas
                if current_date not in df.index or next_date not in df.index:
                    continue

                price_today = df.loc[current_date, 'Close']
                price_tomorrow = df.loc[next_date, 'Close']

                if pd.isna(price_today) or pd.isna(price_tomorrow) or price_today == 0:
                    continue

                # Calcular retorno real
                actual_return = (price_tomorrow - price_today) / price_today

                # Si predijimos DOWN, el retorno es inverso (vendemos en corto)
                trade_return = actual_return if direction == 'UP' else -actual_return

                # Restar comisiones (entrada + salida)
                trade_return -= commission_pct * 2

                # ¿Acertó la dirección?
                actual_dir = 'UP' if actual_return >= 0 else 'DOWN'
                hit = direction == actual_dir

                result.trades.append({
                    'date': date_str,
                    'target_date': next_str,
                    'ticker': ticker,
                    'direction': direction,
                    'actual_direction': actual_dir,
                    'return': trade_return,
                    'actual_return': actual_return,
                    'hit': hit,
                    'confidence': pick.get('confidence', 0),
                    'score': pick.get('score', 0),
                    'sector': get_sector(ticker),
                })

                day_return += trade_return
                n_valid += 1

            # Retorno promedio del portfolio (equal weight)
            if n_valid > 0:
                portfolio_return = day_return / n_valid
            else:
                portfolio_return = 0

            equity *= (1 + portfolio_return)
            result.daily_returns.append(portfolio_return)
            result.equity_curve.append(equity)
            result.dates.append(date_str)

            # Progreso cada 20 días
            if i % 20 == 0:
                pct = (i + 1) / (len(trading_dates) - 1) * 100
                wr = result.win_rate
                print(f"\r  Día {i+1}/{len(trading_dates)-1} ({pct:.0f}%) │ "
                      f"Trades: {result.total_trades} │ "
                      f"WR: {_fmt_acc(wr)} │ "
                      f"Equity: ${equity:,.0f}    ", end='', flush=True)

        print(f"\r  {'─' * 60}")
        return result

    def compare_models(self, results: List[BacktestResult]):
        """
        Compara resultados de múltiples modelos lado a lado.

        CONCEPTO — Tabla comparativa:
        Permite evaluar objetivamente cuál modelo es mejor
        en cada métrica, sin sesgos personales.
        """
        print(f"\n  {'═' * 80}")
        print(f"  {BOLD}COMPARACIÓN DE MODELOS{RST}")
        print(f"  {'═' * 80}")

        header = (f"  {'Modelo':<18} {'Trades':>7} {'WinRate':>8} {'Return':>8} "
                  f"{'Sharpe':>7} {'MaxDD':>7} {'PF':>6} {'Expect':>8}")
        print(header)
        print(f"  {'─' * 80}")

        for r in sorted(results, key=lambda x: x.sharpe_ratio, reverse=True):
            s = r.summary()
            print(f"  {s['model']:<18} "
                  f"{s['total_trades']:>7} "
                  f"{_fmt_acc(s['win_rate']):>18} "
                  f"{_fmt_ret(s['total_return']):>18} "
                  f"{_fmt_sharpe(s['sharpe_ratio']):>17} "
                  f"{s['max_drawdown']:>6.1f}% "
                  f"{_fmt_pf(s['profit_factor']):>15} "
                  f"{_fmt_ret(s['expectancy']):>18}")

        print(f"  {'═' * 80}\n")


# ── Funciones de formato (fuera de la clase para reutilizar) ─────────────────

def _fmt_acc(v):
    if v >= 55: return f"{G}{v:.1f}%{RST}"
    if v >= 50: return f"{Y}{v:.1f}%{RST}"
    return f"{R}{v:.1f}%{RST}"

def _fmt_ret(v):
    if v > 0: return f"{G}+{v:.2f}%{RST}"
    if v < 0: return f"{R}{v:.2f}%{RST}"
    return f"{DIM}0.00%{RST}"

def _fmt_sharpe(v):
    if v >= 1.0: return f"{G}{v:.2f}{RST}"
    if v >= 0.5: return f"{Y}{v:.2f}{RST}"
    return f"{R}{v:.2f}{RST}"

def _fmt_pf(v):
    if v >= 1.5: return f"{G}{v:.2f}{RST}"
    if v >= 1.0: return f"{Y}{v:.2f}{RST}"
    return f"{R}{v:.2f}{RST}"
