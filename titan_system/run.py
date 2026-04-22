#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║   ████████╗██╗████████╗ █████╗ ███╗   ██╗                                   ║
║   ╚══██╔══╝██║╚══██╔══╝██╔══██╗████╗  ██║                                   ║
║      ██║   ██║   ██║   ███████║██╔██╗ ██║                                   ║
║      ██║   ██║   ██║   ██╔══██║██║╚██╗██║                                   ║
║      ██║   ██║   ██║   ██║  ██║██║ ╚████║                                   ║
║      ╚═╝   ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝                                   ║
║                                                                              ║
║   SISTEMA PROFESIONAL DE TRADING ML                                          ║
║   Script Principal — Menú Interactivo                                        ║
║                                                                              ║
║   Uso: python -m titan_system.run                                            ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

CONCEPTO — PUNTO DE ENTRADA (Entry Point):
==========================================
Este es el archivo que el usuario ejecuta para interactuar con todo el sistema.
Es el "control remoto" que da acceso a todas las funcionalidades.

En aplicaciones profesionales, separar la interfaz de usuario (UI) de la
lógica de negocio (core) es FUNDAMENTAL. Esto se llama "separation of concerns":
- core/database.py → lógica de datos (no sabe nada de la consola)
- core/data_loader.py → lógica de descarga (no sabe nada de la consola)
- core/tracker.py → lógica de tracking (mínima salida a consola)
- core/backtester.py → lógica de backtest (mínima salida a consola)
- run.py → SOLO interfaz de usuario (menús, colores, input del usuario)

Si mañana querés reemplazar la consola por una web app, solo cambiás run.py.
Todo lo demás sigue igual.
"""

import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# Agregar el directorio padre al path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from titan_system.core.database import TitanDB
from titan_system.core.data_loader import DataLoader, ACTIVOS, CONTEXT_TICKERS, get_sector
from titan_system.core.tracker import PredictionTracker
from titan_system.core.backtester import Backtester, BacktestResult

# ── Colores ──────────────────────────────────────────────────────────────────
R = "\033[91m"; G = "\033[92m"; Y = "\033[93m"; M = "\033[95m"
C = "\033[96m"; W = "\033[97m"; DIM = "\033[2m"; BOLD = "\033[1m"; RST = "\033[0m"


def clr():
    os.system("cls" if os.name == "nt" else "clear")


def banner():
    clr()
    print(f"""
{C}{'═' * 65}
{BOLD}  ████████╗██╗████████╗ █████╗ ███╗   ██╗  SYSTEM
  ╚══██╔══╝██║╚══██╔══╝██╔══██╗████╗  ██║
     ██║   ██║   ██║   ███████║██╔██╗ ██║  ML Trading
     ██║   ██║   ██║   ██╔══██║██║╚██╗██║  Infrastructure
     ██║   ██║   ██║   ██║  ██║██║ ╚████║  v1.0
     ╚═╝   ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝{RST}
{C}{'═' * 65}{RST}
""")


def show_status(db):
    """Muestra el estado actual de la base de datos."""
    stats = db.db_stats()

    print(f"  {BOLD}ESTADO DEL SISTEMA{RST}")
    print(f"  {'─' * 50}")
    print(f"  Precios:      {G}{stats['prices_count']:,}{RST} registros")
    print(f"  Predicciones: {C}{stats['predictions_count']:,}{RST} registros")
    print(f"  Evaluadas:    {Y}{stats['outcomes_count']:,}{RST} resultados")
    print(f"  Regímenes:    {M}{stats['regimes_count']:,}{RST} días")
    print(f"  Rango datos:  {stats['price_date_range']}")
    print(f"  DB tamaño:    {stats.get('db_size_mb', 0):.1f} MB")

    if stats['models']:
        print(f"  Modelos:      {', '.join(stats['models'])}")

    # Mostrar conteo de tickers
    counts = db.count_prices()
    if counts:
        tickers_con_datos = len(counts)
        avg_days = sum(counts.values()) / len(counts) if counts else 0
        print(f"  Tickers:      {tickers_con_datos} activos, ~{avg_days:.0f} días promedio")

    print(f"  {'─' * 50}\n")


def menu_principal():
    """Menú principal del sistema."""
    print(f"  {BOLD}¿QUÉ QUERÉS HACER?{RST}\n")
    print(f"  {C}[1]{RST} Descargar/actualizar datos históricos")
    print(f"  {C}[2]{RST} Ver estado de la base de datos")
    print(f"  {C}[3]{RST} Backtest rápido (estrategia momentum simple)")
    print(f"  {C}[4]{RST} Ver performance de modelos")
    print(f"  {C}[5]{RST} Explorar datos (consultas SQL)")
    print(f"  {C}[6]{RST} Backtest de estrategia personalizada")
    print(f"  {C}[0]{RST} Salir\n")

    return input(f"  {BOLD}Opción: {RST}").strip()


# ═══════════════════════════════════════════════════════════════════════════════
#  ESTRATEGIAS DE EJEMPLO PARA BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════
#
# Estas son estrategias SIMPLES para probar el backtester.
# Después integraremos los modelos TITAN reales.
#
# Cada strategy_fn recibe:
#   - prices_dict: {ticker: DataFrame_OHLCV} con datos hasta HOY
#   - tickers: lista de tickers disponibles
#   - date_str: fecha actual del backtest
#
# Y devuelve:
#   - Lista de picks: [{ticker, direction, confidence, score}]

def strategy_momentum(prices_dict, tickers, date_str):
    """
    ESTRATEGIA: Momentum simple.

    CONCEPTO — Momentum:
    --------------------
    "Lo que subió tiende a seguir subiendo" (al menos a corto plazo).
    Es uno de los factores más documentados en finanzas académicas.
    Jegadeesh & Titman (1993) demostraron que comprar ganadores
    de los últimos 3-12 meses genera alpha.

    Esta estrategia:
    1. Calcula el retorno de cada activo en los últimos 20 días
    2. Rankea de mayor a menor
    3. Los top 10 → dirección UP (comprar)
    4. Los bottom 10 → dirección DOWN (vender/shortear)
    """
    picks = []

    for ticker in tickers:
        if ticker not in prices_dict:
            continue

        df = prices_dict[ticker]
        if len(df) < 25:
            continue

        close = df['Close']

        # Retorno de 20 días
        ret_20d = (close.iloc[-1] / close.iloc[-20] - 1) if close.iloc[-20] != 0 else 0

        # Retorno de 5 días (momentum corto)
        ret_5d = (close.iloc[-1] / close.iloc[-5] - 1) if close.iloc[-5] != 0 else 0

        # Score compuesto
        score = ret_20d * 0.6 + ret_5d * 0.4

        if not np.isfinite(score):
            continue

        picks.append({
            'ticker': ticker,
            'direction': 'UP' if score > 0 else 'DOWN',
            'confidence': min(abs(score) * 10, 1.0),  # normalizar a 0-1
            'score': abs(score) * 100,
        })

    # Ordenar por score descendente
    picks.sort(key=lambda x: x['score'], reverse=True)
    return picks


def strategy_mean_reversion(prices_dict, tickers, date_str):
    """
    ESTRATEGIA: Mean Reversion (reversión a la media).

    CONCEPTO — Mean Reversion:
    --------------------------
    "Lo que bajó mucho tiende a rebotar" (y viceversa).
    Es el opuesto de momentum. Funciona mejor en plazos cortos (1-5 días).

    Esta estrategia:
    1. Calcula cuánto se desvió el precio de su media de 20 días (Z-Score)
    2. Si está MUY por debajo de la media (Z < -2) → comprar (esperando rebote)
    3. Si está MUY por arriba de la media (Z > +2) → vender
    """
    picks = []

    for ticker in tickers:
        if ticker not in prices_dict:
            continue

        df = prices_dict[ticker]
        if len(df) < 25:
            continue

        close = df['Close']

        # Z-Score: cuántas desviaciones estándar del promedio de 20 días
        mean_20 = close.iloc[-20:].mean()
        std_20 = close.iloc[-20:].std()

        if std_20 == 0 or not np.isfinite(std_20):
            continue

        z_score = (close.iloc[-1] - mean_20) / std_20

        if not np.isfinite(z_score):
            continue

        # Mean reversion: comprar si cayó mucho, vender si subió mucho
        picks.append({
            'ticker': ticker,
            'direction': 'UP' if z_score < 0 else 'DOWN',
            'confidence': min(abs(z_score) / 3, 1.0),
            'score': abs(z_score) * 30,
        })

    picks.sort(key=lambda x: x['score'], reverse=True)
    return picks


def strategy_rsi_crossover(prices_dict, tickers, date_str):
    """
    ESTRATEGIA: RSI Oversold/Overbought.

    CONCEPTO — RSI (Relative Strength Index):
    -----------------------------------------
    Indicador de 0 a 100 que mide la velocidad de los movimientos.
    RSI < 30 → "oversold" (sobrevendido) → señal de compra
    RSI > 70 → "overbought" (sobrecomprado) → señal de venta

    Es uno de los indicadores más usados en análisis técnico.
    Creado por J. Welles Wilder en 1978.
    """
    picks = []

    for ticker in tickers:
        if ticker not in prices_dict:
            continue

        df = prices_dict[ticker]
        if len(df) < 20:
            continue

        close = df['Close']
        delta = close.diff()

        # RSI de 14 períodos
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()

        last_gain = gain.iloc[-1]
        last_loss = loss.iloc[-1]

        if last_loss == 0 or not np.isfinite(last_gain) or not np.isfinite(last_loss):
            continue

        rs = last_gain / last_loss
        rsi = 100 - (100 / (1 + rs))

        if not np.isfinite(rsi):
            continue

        # Score basado en qué tan extremo es el RSI
        if rsi < 35:
            score = (35 - rsi) * 2  # más oversold → más score
            direction = 'UP'
        elif rsi > 65:
            score = (rsi - 65) * 2  # más overbought → más score
            direction = 'DOWN'
        else:
            continue  # RSI neutral → no operar

        picks.append({
            'ticker': ticker,
            'direction': direction,
            'confidence': min(score / 50, 1.0),
            'score': score,
        })

    picks.sort(key=lambda x: x['score'], reverse=True)
    return picks


# ═══════════════════════════════════════════════════════════════════════════════
#  EJECUCIÓN DE OPCIONES DEL MENÚ
# ═══════════════════════════════════════════════════════════════════════════════

def opcion_descargar(db):
    """Opción 1: Descargar datos."""
    loader = DataLoader(db, years_history=2, max_workers=10)

    print(f"\n  {BOLD}DESCARGAR DATOS{RST}\n")
    print(f"  [1] Actualización incremental (solo datos nuevos) {G}← recomendado{RST}")
    print(f"  [2] Descarga completa (2 años, forzar todo)")
    print(f"  [3] Descargar solo algunos tickers\n")

    sub = input(f"  Opción: ").strip()

    if sub == '1':
        loader.download_all(force_full=False)
    elif sub == '2':
        print(f"\n  {Y}⚠ Esto descargará ~260 tickers × 2 años. Puede tardar 5-10 min.{RST}")
        confirm = input(f"  ¿Continuar? (s/n): ").strip().lower()
        if confirm == 's':
            loader.download_all(force_full=True)
    elif sub == '3':
        tickers_input = input(f"  Tickers (separados por coma): ").strip().upper()
        custom_tickers = [t.strip() for t in tickers_input.split(',')]
        loader.download_all(tickers=custom_tickers, include_context=True)


def opcion_backtest_rapido(db):
    """Opción 3: Backtest rápido con estrategias simples."""
    bt = Backtester(db)

    # Verificar que hay datos
    counts = db.count_prices()
    if not counts:
        print(f"\n  {R}ERROR: No hay datos en la DB. Primero descargá datos (opción 1).{RST}\n")
        return

    # Determinar rango disponible
    row = db.conn.execute("SELECT MIN(date), MAX(date) FROM prices").fetchone()
    min_date, max_date = row[0], row[1]

    print(f"\n  {BOLD}BACKTEST RÁPIDO{RST}")
    print(f"  {'─' * 50}")
    print(f"  Datos disponibles: {min_date} → {max_date}")
    print(f"  Tickers con datos: {len(counts)}\n")

    # Selección de estrategia
    print(f"  {BOLD}Elegí una estrategia:{RST}\n")
    print(f"  {C}[1]{RST} Momentum (comprar ganadores recientes)")
    print(f"  {C}[2]{RST} Mean Reversion (comprar los que cayeron)")
    print(f"  {C}[3]{RST} RSI Crossover (sobrevendido/sobrecomprado)")
    print(f"  {C}[4]{RST} TODAS (comparar las 3 lado a lado)\n")

    strat = input(f"  Estrategia: ").strip()

    # Parámetros del backtest
    print(f"\n  {DIM}(Enter para valores por defecto){RST}")

    start_input = input(f"  Fecha inicio [{min_date}]: ").strip()
    start_date = start_input if start_input else min_date

    end_input = input(f"  Fecha fin [{max_date}]: ").strip()
    end_date = end_input if end_input else max_date

    top_n_input = input(f"  Top N picks por día [10]: ").strip()
    top_n = int(top_n_input) if top_n_input else 10

    # Tickers a usar (los que tienen suficientes datos)
    tickers = [t for t, cnt in counts.items() if cnt > 100]

    strategies = {
        '1': ('MOMENTUM', strategy_momentum),
        '2': ('MEAN_REVERSION', strategy_mean_reversion),
        '3': ('RSI_CROSSOVER', strategy_rsi_crossover),
    }

    results = []

    if strat in strategies:
        name, fn = strategies[strat]
        result = bt.run(fn, name, tickers, start_date, end_date, top_n=top_n)
        result.print_report()
        results.append(result)
    elif strat == '4':
        for name, fn in strategies.values():
            print(f"\n  {BOLD}═══ {name} ═══{RST}")
            result = bt.run(fn, name, tickers, start_date, end_date, top_n=top_n)
            results.append(result)

        if len(results) > 1:
            bt.compare_models(results)
    else:
        print(f"  {R}Opción no válida{RST}")
        return

    # Preguntar si guardar resultados
    save = input(f"\n  ¿Guardar predicciones del backtest en la DB? (s/n): ").strip().lower()
    if save == 's':
        tracker = PredictionTracker(db)
        for result in results:
            for trade in result.trades:
                db.save_prediction(
                    model_name=result.model_name + '_BT',
                    ticker=trade['ticker'],
                    prediction_date=trade['date'],
                    target_date=trade['target_date'],
                    direction=trade['direction'],
                    confidence=trade.get('confidence'),
                    score=trade.get('score'),
                    sector=trade.get('sector'),
                )
                # Guardar outcome también
                pred_id = db.conn.execute(
                    "SELECT id FROM predictions WHERE model_name=? AND ticker=? AND target_date=? ORDER BY id DESC LIMIT 1",
                    (result.model_name + '_BT', trade['ticker'], trade['target_date'])
                ).fetchone()
                if pred_id:
                    db.save_outcome(pred_id[0], trade['actual_direction'], trade['actual_return'])

        print(f"\n  {G}✓ Resultados guardados en la DB{RST}")


def opcion_performance(db):
    """Opción 4: Ver performance de modelos."""
    tracker = PredictionTracker(db)

    models = db.conn.execute(
        "SELECT DISTINCT model_name FROM predictions ORDER BY model_name"
    ).fetchall()

    if not models:
        print(f"\n  {Y}No hay modelos registrados. Corré un backtest primero (opción 3).{RST}\n")
        return

    print(f"\n  {BOLD}MODELOS DISPONIBLES:{RST}\n")
    for i, m in enumerate(models, 1):
        print(f"  {C}[{i}]{RST} {m[0]}")
    print(f"  {C}[0]{RST} Todos\n")

    sel = input(f"  Modelo: ").strip()

    if sel == '0':
        tracker.report()
    elif sel.isdigit() and 1 <= int(sel) <= len(models):
        model_name = models[int(sel)-1][0]
        tracker.report(model_name)

        print(f"\n  {DIM}¿Ver desglose?{RST}")
        print(f"  [1] Por sector")
        print(f"  [2] Por régimen")
        print(f"  [3] Por nivel de confianza")
        print(f"  [0] Volver\n")
        sub = input(f"  Opción: ").strip()

        if sub == '1':
            tracker.report_by_sector(model_name)
        elif sub == '2':
            tracker.report_by_regime(model_name)
        elif sub == '3':
            df = db.get_accuracy_by_confidence(model_name)
            if not df.empty:
                print(f"\n  {BOLD}ACCURACY POR CONFIANZA — {model_name}{RST}")
                print(df.to_string(index=False))


def opcion_explorar(db):
    """
    Opción 5: Explorar datos con SQL.

    CONCEPTO — SQL Interactivo:
    ---------------------------
    Esto es como tener una terminal SQL donde podés escribir
    consultas directas. Es LA MEJOR forma de aprender SQL:
    escribir queries y ver resultados en tiempo real.

    Queries de ejemplo para probar:
    - SELECT * FROM prices WHERE ticker='AAPL' LIMIT 5
    - SELECT COUNT(*) FROM predictions GROUP BY model_name
    - SELECT ticker, close FROM prices WHERE date='2024-03-20' ORDER BY close DESC LIMIT 10
    """
    print(f"\n  {BOLD}EXPLORADOR SQL{RST}")
    print(f"  {'─' * 50}")
    print(f"  Escribí consultas SQL directas.")
    print(f"  Tablas: prices, predictions, outcomes, regimes")
    print(f"  Escribí 'salir' para volver.\n")

    print(f"  {DIM}Queries de ejemplo:{RST}")
    print(f"  {DIM}  SELECT * FROM prices WHERE ticker='AAPL' ORDER BY date DESC LIMIT 5{RST}")
    print(f"  {DIM}  SELECT ticker, COUNT(*) as dias FROM prices GROUP BY ticker ORDER BY dias DESC LIMIT 10{RST}")
    print(f"  {DIM}  SELECT model_name, COUNT(*) FROM predictions GROUP BY model_name{RST}\n")

    while True:
        query = input(f"  {C}SQL>{RST} ").strip()

        if query.lower() in ('salir', 'exit', 'quit', ''):
            break

        try:
            df = db.execute_raw(query)
            if df.empty:
                print(f"  {DIM}(Sin resultados){RST}\n")
            else:
                print(f"\n{df.to_string(index=False)}\n")
                print(f"  {DIM}({len(df)} filas){RST}\n")
        except Exception as e:
            print(f"  {R}Error: {e}{RST}\n")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """
    Función principal del sistema.

    CONCEPTO — Main function pattern:
    ---------------------------------
    Separar el main() en su propia función permite:
    1. Importar este archivo sin ejecutar el programa
    2. Testear funciones individuales
    3. Llamar a main() desde otros scripts
    """
    with TitanDB() as db:
        while True:
            banner()
            show_status(db)

            opcion = menu_principal()

            if opcion == '1':
                opcion_descargar(db)
            elif opcion == '2':
                show_status(db)
            elif opcion == '3':
                opcion_backtest_rapido(db)
            elif opcion == '4':
                opcion_performance(db)
            elif opcion == '5':
                opcion_explorar(db)
            elif opcion == '6':
                print(f"\n  {Y}Próximamente: integración con modelos TITAN v4/v5{RST}\n")
            elif opcion == '0':
                print(f"\n  {G}¡Hasta luego!{RST}\n")
                break
            else:
                print(f"\n  {R}Opción no válida{RST}")

            input(f"\n  {DIM}Enter para continuar...{RST}")


if __name__ == '__main__':
    main()
