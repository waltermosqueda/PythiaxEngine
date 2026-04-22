"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  TITAN SYSTEM — Tracker de Predicciones (tracker.py)                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  CONCEPTOS CLAVE:                                                            ║
║                                                                              ║
║  1. TRACKING DE PREDICCIONES:                                                ║
║     Cada vez que un modelo ML genera predicciones, este módulo las          ║
║     captura y las guarda en la base de datos con timestamp.                  ║
║     Así podemos responder: "¿cuántas veces acertó TITAN v5?"               ║
║                                                                              ║
║  2. EVALUACIÓN AUTOMÁTICA:                                                   ║
║     Cuando el mercado cierra, comparamos predicciones vs realidad.          ║
║     Esto es el "report card" del modelo.                                     ║
║                                                                              ║
║  3. INTERFAZ ENTRE MODELOS ML Y LA DB:                                       ║
║     Los modelos TITAN existentes generan output en formato propio.          ║
║     Este tracker traduce ese output al formato de la base de datos.         ║
║     Es un "adaptador" — un patrón de diseño muy común.                      ║
║                                                                              ║
║  PATRÓN ADAPTADOR (Adapter Pattern):                                         ║
║  ------------------------------------                                        ║
║  Problema: TITAN v5 genera predicciones en un formato X.                     ║
║            La DB espera datos en formato Y.                                  ║
║  Solución: El Tracker traduce de X a Y.                                      ║
║                                                                              ║
║  ¿Por qué no cambiar TITAN v5 para que escriba directo a la DB?            ║
║  Porque queremos que los modelos sean INDEPENDIENTES de la DB.              ║
║  Si mañana cambiamos de SQLite a PostgreSQL, solo cambiamos                 ║
║  el Tracker — los modelos no se enteran. Esto es "loose coupling"           ║
║  (acoplamiento débil) y es un principio de diseño profesional.              ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from titan_system.core.database import TitanDB
from titan_system.core.data_loader import get_sector


class PredictionTracker:
    """
    Captura predicciones de modelos ML y las registra en la DB.

    Flujo:
    1. Modelo corre → genera lista de picks con scores
    2. Tracker.record() → guarda en DB con timestamp y metadata
    3. Tracker.evaluate() → compara vs realidad cuando el mercado cierra
    4. Tracker.report() → genera estadísticas de accuracy
    """

    def __init__(self, db: TitanDB):
        self.db = db

    def record_predictions(self, model_name: str,
                           picks: List[Dict[str, Any]],
                           prediction_date: str = None,
                           target_date: str = None,
                           regime: str = None,
                           model_version: str = None) -> int:
        """
        Registra las predicciones de un modelo.

        Parámetros:
        -----------
        model_name : str
            Nombre del modelo (ej: 'TITAN_v5', 'TITAN_v4')
        picks : list of dicts
            Cada dict debe tener al menos:
            {
                'ticker': 'AAPL',
                'direction': 'UP',       # 'UP' o 'DOWN'
                'confidence': 0.73,       # 0.0 a 1.0
                'score': 82.5,            # puntaje crudo del modelo
            }
        prediction_date : str
            Fecha en que se hizo la predicción (default: hoy)
        target_date : str
            Fecha para la que predice (default: siguiente día hábil)
        regime : str
            Régimen de mercado actual (ej: 'BULL', 'BEAR')
        model_version : str
            Versión del modelo (ej: 'v5.0')

        Returns:
        --------
        int: cantidad de predicciones guardadas

        CONCEPTO — Valores por defecto inteligentes:
        -------------------------------------------
        Si no pasás prediction_date, usa la fecha de hoy.
        Si no pasás target_date, calcula el siguiente día hábil.
        Esto hace que el uso más común sea muy simple:
            tracker.record_predictions('TITAN_v5', picks)
        Sin tener que calcular fechas cada vez.
        """
        if not picks:
            return 0

        if prediction_date is None:
            prediction_date = datetime.now().strftime('%Y-%m-%d')

        if target_date is None:
            target_date = self._next_business_day(prediction_date)

        # Convertir los picks al formato de la DB
        predictions = []
        for pick in picks:
            predictions.append({
                'model_name': model_name,
                'model_version': model_version,
                'ticker': pick['ticker'],
                'prediction_date': prediction_date,
                'target_date': target_date,
                'direction': pick.get('direction', 'UP'),
                'confidence': pick.get('confidence'),
                'score': pick.get('score'),
                'regime': regime or pick.get('regime'),
                'sector': get_sector(pick['ticker']),
            })

        saved = self.db.save_predictions_bulk(predictions)

        print(f"  {self._G}✓{self._RST} {saved} predicciones guardadas "
              f"({model_name} → {target_date})")

        return saved

    def evaluate(self, target_date: str = None) -> Dict[str, Any]:
        """
        Evalúa todas las predicciones pendientes para una fecha.

        Este método se corre DESPUÉS de que el mercado cierra.
        Compara lo que los modelos predijeron vs lo que realmente pasó.

        CONCEPTO — Separación de responsabilidades:
        -------------------------------------------
        record_predictions() → se corre ANTES del mercado (pre-market)
        evaluate()           → se corre DESPUÉS del cierre (post-market)

        Esta separación es crucial para evitar "look-ahead bias":
        NUNCA podemos evaluar una predicción usando datos que no
        estaban disponibles cuando se hizo la predicción.
        """
        if target_date is None:
            target_date = datetime.now().strftime('%Y-%m-%d')

        results = self.db.evaluate_pending_predictions(target_date)

        if results['evaluated'] > 0:
            accuracy = results['hits'] / results['evaluated'] * 100
            print(f"\n  {'═' * 50}")
            print(f"  EVALUACIÓN para {target_date}")
            print(f"  {'─' * 50}")
            print(f"  Evaluadas:  {results['evaluated']}")
            print(f"  Aciertos:   {self._G}{results['hits']}{self._RST}")
            print(f"  Fallos:     {self._R}{results['misses']}{self._RST}")
            print(f"  Accuracy:   {self._fmt_acc(accuracy)}")
            if results['errors'] > 0:
                print(f"  Errores:    {self._Y}{results['errors']}{self._RST} "
                      f"(sin datos de precio)")
            print(f"  {'═' * 50}\n")
        else:
            print(f"  {self._DIM}Sin predicciones pendientes para {target_date}{self._RST}")

        return results

    def report(self, model_name: str = None) -> pd.DataFrame:
        """
        Genera un reporte de accuracy para uno o todos los modelos.

        CONCEPTO — Métricas de evaluación de un modelo de trading:
        ----------------------------------------------------------
        No alcanza con saber el % de aciertos. Un modelo que acierta
        60% pero pierde más cuando falla que lo que gana cuando acierta
        es PERDEDOR. Necesitamos:

        1. Accuracy (Win Rate): % de veces que acertó la dirección
        2. Avg Return Right: retorno promedio cuando acierta
        3. Avg Return Wrong: retorno promedio cuando falla
        4. Profit Factor: |ganancias| / |pérdidas|
           > 1.0 = rentable, > 1.5 = bueno, > 2.0 = excelente
        5. Expectancy: ganancia esperada por operación
           = (win_rate × avg_win) - (loss_rate × avg_loss)
           > 0 = sistema rentable a largo plazo
        """
        if model_name:
            models = [model_name]
        else:
            models_rows = self.db.conn.execute(
                "SELECT DISTINCT model_name FROM predictions ORDER BY model_name"
            ).fetchall()
            models = [r[0] for r in models_rows]

        if not models:
            print(f"  {self._DIM}No hay modelos registrados{self._RST}")
            return pd.DataFrame()

        print(f"\n  {'═' * 70}")
        print(f"  {self._BOLD}REPORT CARD — Performance de Modelos{self._RST}")
        print(f"  {'═' * 70}")

        all_stats = []

        for model in models:
            stats = self.db.get_model_accuracy(model)

            if stats['total'] == 0:
                print(f"\n  {model}: sin predicciones evaluadas")
                continue

            # Calcular métricas adicionales
            acc = stats['accuracy_pct']
            avg_right = stats.get('avg_return_when_right') or 0
            avg_wrong = abs(stats.get('avg_return_when_wrong') or 0)

            # Profit factor: ganancias brutas / pérdidas brutas
            if avg_wrong > 0:
                profit_factor = (acc/100 * avg_right) / ((1-acc/100) * avg_wrong)
            else:
                profit_factor = float('inf') if acc > 0 else 0

            # Expectancy: ganancia esperada por operación
            expectancy = (acc/100 * avg_right) - ((1-acc/100) * avg_wrong)

            # Racha actual
            streak = self.db.get_streak(model)

            print(f"\n  {'─' * 70}")
            print(f"  {self._BOLD}{model}{self._RST}")
            print(f"  {'─' * 70}")
            print(f"  Total predicciones: {stats['total']}")
            print(f"  Accuracy:           {self._fmt_acc(acc)}")
            print(f"  Avg Return (hit):   {self._G}+{avg_right:.3f}%{self._RST}")
            print(f"  Avg Return (miss):  {self._R}-{avg_wrong:.3f}%{self._RST}")
            print(f"  Profit Factor:      {self._fmt_pf(profit_factor)}")
            print(f"  Expectancy:         {self._fmt_exp(expectancy)}")
            print(f"  Avg Confidence:     {stats.get('avg_confidence', 0):.1f}%")
            print(f"  Racha actual:       {streak['current_streak']} {streak['streak_type']}")

            all_stats.append({
                'model': model,
                'total': stats['total'],
                'accuracy': acc,
                'avg_return_right': avg_right,
                'avg_return_wrong': -avg_wrong,
                'profit_factor': profit_factor,
                'expectancy': expectancy,
                'confidence': stats.get('avg_confidence', 0),
            })

        print(f"\n  {'═' * 70}\n")

        return pd.DataFrame(all_stats)

    def report_by_sector(self, model_name: str):
        """Muestra accuracy desglosada por sector."""
        df = self.db.get_accuracy_by_sector(model_name)
        if df.empty:
            print(f"  Sin datos por sector para {model_name}")
            return df

        print(f"\n  {self._BOLD}ACCURACY POR SECTOR — {model_name}{self._RST}")
        print(f"  {'─' * 55}")
        print(f"  {'Sector':<12} {'Total':>6} {'Aciertos':>9} {'Accuracy':>9} {'Avg Ret':>8}")
        print(f"  {'─' * 55}")
        for _, row in df.iterrows():
            acc_str = self._fmt_acc(row['accuracy_pct'])
            print(f"  {row['sector']:<12} {row['total']:>6} "
                  f"{row['aciertos']:>9} {acc_str:>20} "
                  f"{row['avg_return_pct']:>7.3f}%")
        print(f"  {'─' * 55}\n")
        return df

    def report_by_regime(self, model_name: str):
        """Muestra accuracy desglosada por régimen de mercado."""
        df = self.db.get_accuracy_by_regime(model_name)
        if df.empty:
            print(f"  Sin datos por régimen para {model_name}")
            return df

        print(f"\n  {self._BOLD}ACCURACY POR RÉGIMEN — {model_name}{self._RST}")
        print(f"  {'─' * 55}")
        print(f"  {'Régimen':<15} {'Total':>6} {'Aciertos':>9} {'Accuracy':>9} {'Avg Ret':>8}")
        print(f"  {'─' * 55}")
        for _, row in df.iterrows():
            acc_str = self._fmt_acc(row['accuracy_pct'])
            print(f"  {str(row['regime']):<15} {row['total']:>6} "
                  f"{row['aciertos']:>9} {acc_str:>20} "
                  f"{row['avg_return_pct']:>7.3f}%")
        print(f"  {'─' * 55}\n")
        return df

    # ── Helpers internos ─────────────────────────────────────────────────────

    def _next_business_day(self, date_str: str) -> str:
        """
        Calcula el siguiente día hábil (lun-vie).

        CONCEPTO — Días hábiles:
        El mercado no opera sáb/dom. Si hoy es viernes, el target
        es el lunes. Si es jueves, el target es viernes.
        (No consideramos feriados bursátiles por simplicidad.)
        """
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        dt += timedelta(days=1)
        # weekday(): 0=lun, 4=vie, 5=sáb, 6=dom
        while dt.weekday() >= 5:
            dt += timedelta(days=1)
        return dt.strftime('%Y-%m-%d')

    # Colores
    _G = "\033[92m"; _R = "\033[91m"; _Y = "\033[93m"
    _DIM = "\033[2m"; _BOLD = "\033[1m"; _RST = "\033[0m"

    def _fmt_acc(self, acc):
        if acc >= 55: return f"{self._G}{acc:.1f}%{self._RST}"
        if acc >= 50: return f"{self._Y}{acc:.1f}%{self._RST}"
        return f"{self._R}{acc:.1f}%{self._RST}"

    def _fmt_pf(self, pf):
        if pf >= 1.5: return f"{self._G}{pf:.2f}{self._RST}"
        if pf >= 1.0: return f"{self._Y}{pf:.2f}{self._RST}"
        return f"{self._R}{pf:.2f}{self._RST}"

    def _fmt_exp(self, exp):
        if exp > 0: return f"{self._G}+{exp:.4f}%{self._RST}"
        return f"{self._R}{exp:.4f}%{self._RST}"


if __name__ == '__main__':
    print("=" * 60)
    print("  TEST DE TRACKER")
    print("=" * 60)

    with TitanDB() as db:
        tracker = PredictionTracker(db)

        # Test: registrar predicciones de ejemplo
        test_picks = [
            {'ticker': 'AAPL', 'direction': 'UP', 'confidence': 0.75, 'score': 82},
            {'ticker': 'MSFT', 'direction': 'UP', 'confidence': 0.68, 'score': 74},
            {'ticker': 'NVDA', 'direction': 'DOWN', 'confidence': 0.62, 'score': 65},
        ]

        tracker.record_predictions(
            model_name='TEST_MODEL',
            picks=test_picks,
            prediction_date='2024-01-15',
            target_date='2024-01-16',
            regime='BULL',
            model_version='test',
        )

        # Verificar que se guardaron
        preds = db.get_predictions(model_name='TEST_MODEL')
        print(f"\n  Predicciones guardadas: {len(preds)}")
        print(preds[['model_name', 'ticker', 'direction', 'confidence']].to_string())

        # Generar reporte (estará vacío porque no hay outcomes aún)
        tracker.report('TEST_MODEL')

    print("=" * 60)
