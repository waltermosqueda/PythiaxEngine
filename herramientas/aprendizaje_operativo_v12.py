#!/usr/bin/env python3
"""
APRENDIZAJE OPERATIVO V12
=========================

Bucle operativo para que Claude:
  - recuerde que predijo V12 cada dia
  - guarde el regimen/contexto del mercado
  - mida resultados cuando las fechas objetivo ya existen en la DB
  - deje artefactos diarios auditables fuera de SCANNER/

Uso rapido:
  python herramientas/aprendizaje_operativo_v12.py run
  python herramientas/aprendizaje_operativo_v12.py run --date 2026-04-09
  python herramientas/aprendizaje_operativo_v12.py backfill --from-date 2026-04-01
  python herramientas/aprendizaje_operativo_v12.py report
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import herramientas.aprendizaje_operativo_v11 as base
from SCANNER import invertir_v12 as v12
from titan_system.core.database import TitanDB


MODEL_PREFIX = "INVERTIR_V12"
MODEL_VERSION = "v12"
RUNS_DIR = ROOT / "aprendizaje_operativo" / "v12_runs"
REPORTS_DIR = ROOT / "aprendizaje_operativo" / "v12_reports"
A_HORIZONS = (1, 7)
C5_HORIZONS = (1, 4, 7)
D_HORIZONS = (10,)

# Reutilizamos la base robusta de V11, pero apuntando al namespace V12.
base.MODEL_PREFIX = MODEL_PREFIX
base.MODEL_VERSION = MODEL_VERSION
base.RUNS_DIR = RUNS_DIR
base.REPORTS_DIR = REPORTS_DIR
base.A_HORIZONS = A_HORIZONS
base.C5_HORIZONS = C5_HORIZONS


class OperationalLearningV12(base.OperationalLearningV11):
    def __init__(self, db: TitanDB):
        self.db = db
        self.universe_data, self.missing = v12.load_universe_data(db, v12.UNIVERSE)
        self.prepared = v12.precompute_indicators(self.universe_data)
        if "SPY" not in self.prepared:
            raise RuntimeError("SPY no esta disponible en titan.db")

        self.spy_dates = self.prepared["SPY"].index
        self.date_to_idx = {ts.date().isoformat(): idx for idx, ts in enumerate(self.spy_dates)}
        self.latest_db_date = self.spy_dates[-1].date().isoformat()
        market_status = db.get_market_data_status()
        self.db_last_write = None
        updated_at_text = market_status.get("market_data_updated_at")
        latest_prices_date = market_status.get("latest_prices_date")
        if updated_at_text and latest_prices_date == self.latest_db_date:
            self.db_last_write = datetime.strptime(updated_at_text, "%Y-%m-%d %H:%M:%S")

    def evaluate_due_predictions(
        self,
        max_target_date: str | None = None,
        recompute_existing: bool = False,
    ) -> dict[str, Any]:
        """Versión optimizada V12: precios desde self.prepared (in-memory) + bulk SELECT.

        La implementación base (V11) hace 2 queries de precios por predicción
        (entry_date open + target_date close), resultando en ~3500 round-trips a
        Supabase para 1000+ predicciones históricas → timeout de 600s.

        Esta versión usa:
        1. Un único SELECT bulk para todas las predicciones (vs. uno por target_date).
        2. Lookups O(1) en self.prepared[ticker] DataFrame para los precios (0 queries).
        3. Un único executemany para los outcomes (vs. uno por predicción).
        Reduce de ~3500 queries a ~3 queries totales.
        """
        if max_target_date is None:
            max_target_date = self.latest_db_date

        # 1. Bulk SELECT: todas las predicciones relevantes en UNA sola query.
        if recompute_existing:
            all_pending = self.db.conn.execute(
                """
                SELECT p.id, p.model_name, p.ticker, p.direction, p.prediction_date, p.target_date
                FROM predictions p
                WHERE p.model_name LIKE ? AND p.target_date <= ?
                ORDER BY p.target_date
                """,
                (f"{MODEL_PREFIX}_%", max_target_date),
            ).fetchall()
            if all_pending:
                pred_ids = [int(row[0]) for row in all_pending]
                for i in range(0, len(pred_ids), 500):
                    batch = pred_ids[i : i + 500]
                    placeholders = ",".join("?" * len(batch))
                    self.db.conn.execute(
                        f"DELETE FROM outcomes WHERE prediction_id IN ({placeholders})",
                        batch,
                    )
        else:
            all_pending = self.db.conn.execute(
                """
                SELECT p.id, p.model_name, p.ticker, p.direction, p.prediction_date, p.target_date
                FROM predictions p
                LEFT JOIN outcomes o ON p.id = o.prediction_id
                WHERE p.model_name LIKE ? AND p.target_date <= ? AND o.id IS NULL
                ORDER BY p.target_date
                """,
                (f"{MODEL_PREFIX}_%", max_target_date),
            ).fetchall()

        distinct_dates = len({str(row[5]) for row in all_pending})
        summary: dict[str, Any] = {
            "evaluated": 0,
            "hits": 0,
            "misses": 0,
            "errors": 0,
            "dates": distinct_dates,
        }

        outcomes_batch: list[tuple[int, str, float, int]] = []
        for pred_id, model_name, ticker, predicted_dir, pred_date, stored_target_date in all_pending:
            pred_date = str(pred_date)
            stored_target_date = str(stored_target_date)
            horizon = self.extract_horizon(str(model_name))
            if horizon is None:
                summary["errors"] += 1
                continue

            entry_date = self.trading_day_offset(str(pred_date), 1)
            actual_target_date = self.trading_day_offset(str(pred_date), horizon)
            if entry_date is None or actual_target_date is None:
                continue
            if actual_target_date > max_target_date:
                continue

            # Corrección de target_date: si cambió (raro), actualiza en DB.
            if stored_target_date != actual_target_date:
                existing_row = self.db.conn.execute(
                    """
                    SELECT id
                    FROM predictions
                    WHERE model_name = ? AND ticker = ? AND prediction_date = ? AND target_date = ?
                    """,
                    (model_name, ticker, pred_date, actual_target_date),
                ).fetchone()
                if existing_row and int(existing_row[0]) != int(pred_id):
                    self.db.conn.execute("DELETE FROM predictions WHERE id = ?", (pred_id,))
                    pred_id = int(existing_row[0])
                else:
                    self.db.conn.execute(
                        "UPDATE predictions SET target_date = ? WHERE id = ?",
                        (actual_target_date, pred_id),
                    )

            # 2. Price lookup en memoria (0 queries a DB).
            if ticker not in self.prepared:
                summary["errors"] += 1
                continue
            df = self.prepared[ticker]
            try:
                price_before = df.at[pd.Timestamp(entry_date), "Open"]
                price_after = df.at[pd.Timestamp(actual_target_date), "Close"]
            except (KeyError, TypeError):
                summary["errors"] += 1
                continue
            if pd.isna(price_before) or pd.isna(price_after):
                summary["errors"] += 1
                continue
            if price_before == 0:
                summary["errors"] += 1
                continue
            # Guard: open == close en la barra de entrada sugiere barra incompleta
            # (descarga pre-cierre de mercado). Dejar pendiente en vez de registrar 0.0 falso.
            try:
                entry_close_chk = df.at[pd.Timestamp(entry_date), "Close"]
            except (KeyError, TypeError):
                entry_close_chk = float("nan")
            if not pd.isna(entry_close_chk) and abs(float(price_before) - float(entry_close_chk)) < 1e-6:
                summary["errors"] += 1
                continue

            actual_return = (price_after - price_before) / price_before
            if abs(actual_return) > 1.00:
                summary["errors"] += 1
                continue
            if abs(actual_return) > 0.50:
                try:
                    window = df.loc[entry_date:actual_target_date]
                    if not window.empty and "Close" in window.columns:
                        close_rets = window["Close"].pct_change().abs()
                        if (close_rets > 0.50).any():
                            summary["errors"] += 1
                            continue
                except Exception:
                    pass
            actual_direction = "UP" if actual_return >= 0 else "DOWN"
            hit = 1 if str(predicted_dir).upper() == actual_direction else 0
            outcomes_batch.append((int(pred_id), actual_direction, float(actual_return), hit))
            summary["evaluated"] += 1
            if hit:
                summary["hits"] += 1
            else:
                summary["misses"] += 1

        # 3. Batch upsert de outcomes (1 executemany en lugar de N INSERTs).
        if outcomes_batch:
            self.db.conn.executemany(
                """
                INSERT OR REPLACE INTO outcomes
                    (prediction_id, actual_direction, actual_return, hit)
                VALUES (?, ?, ?, ?)
                """,
                outcomes_batch,
            )
        self.db.conn.commit()
        return summary

    def _historical_freshness(self, analyzed_date: str) -> str:
        if analyzed_date != self.latest_db_date:
            return "HISTORICA"

        today = datetime.now().date()
        latest_dt = datetime.strptime(analyzed_date, "%Y-%m-%d").date()
        staleness = v12.business_days_between(latest_dt, today)
        if staleness <= 1:
            return "AL DIA"
        return f"STALE ({staleness} dias habiles)"

    def build_snapshot(self, requested_date: str | None = None) -> tuple[v12.Snapshot, dict[str, object]]:
        run_started = datetime.now()
        as_of_ts = self.resolve_as_of(requested_date)
        analyzed_date = as_of_ts.date().isoformat()

        regime_safe, regime_info = v12.check_regime(self.prepared["SPY"].loc[:as_of_ts])
        breadth_pct = self._compute_breadth_asof(as_of_ts)
        quality_alerts = self._recent_quality_alerts_asof(as_of_ts)

        results_a: list[v12.ScanResult] = []
        results_c5: list[v12.ScanResult] = []
        results_d: list[v12.ScanResult] = []
        blocked_extreme: list[v12.ScanResult] = []

        for ticker in sorted(t for t in self.prepared.keys() if t != "SPY"):
            work = self.prepared[ticker].loc[:as_of_ts]
            if len(work) < 2:
                continue

            if regime_safe:
                sig_a = v12.signal_a_mean_reversion(ticker, work)
                if sig_a is not None:
                    results_a.append(sig_a)

            d_candidate = v12.signal_d_leadership(ticker, work)
            if d_candidate is not None and not any(existing.ticker == ticker for existing in results_a):
                results_d.append(d_candidate)

            c_candidate = v12.build_c5_candidate(ticker, work)
            if c_candidate is None:
                continue
            if any(existing.ticker == ticker for existing in results_a):
                continue
            if v12.c5_is_preferred(c_candidate):
                results_c5.append(c_candidate)
            else:
                blocked_extreme.append(c_candidate)

        regime_label = "SEGURO" if regime_info.get("safe") else "PELIGRO"
        all_results = v12.apply_priority_layer(self.db, results_a + results_c5 + results_d, regime_label, analyzed_date)
        results_a = [result for result in all_results if result.signal.startswith("A")]
        results_c5 = [result for result in all_results if result.signal.startswith("C5")]
        results_d = [result for result in all_results if result.signal.startswith("D")]
        blocked_extreme.sort(key=lambda item: item.score, reverse=True)

        memory_context = [
            f"{row['label']} en {row['regime']}: hit {row['accuracy_pct']:.1f}% | avg {row['avg_return_pct']:+.3f}% | n={row['total']}"
            for row in self.context_memory_rows(regime_label)
        ]
        snapshot = v12.Snapshot(
            run_started=run_started,
            run_finished=datetime.now(),
            analyzed_date=analyzed_date,
            db_last_write=self.db_last_write,
            freshness=self._historical_freshness(analyzed_date),
            regime_label=regime_label,
            breadth_pct=float(breadth_pct),
            results_a=results_a,
            results_c5=results_c5,
            results_d=results_d,
            blocked_extreme=blocked_extreme,
            quality_alerts=quality_alerts,
            memory_context=memory_context,
        )
        return snapshot, regime_info

    def _confidence_for(self, result: v12.ScanResult) -> float:
        if result.signal.startswith("A"):
            raw = (result.score - v12.A_SCORE_MIN) / 50.0
        elif result.signal.startswith("C5"):
            raw = result.score / max(v12.C_SCORE_MAX, 1.0)
        else:
            raw = result.score / 50.0
        bounded = max(0.05, min(0.99, raw))
        return round(float(bounded), 4)

    def _prediction_rows_from_result(self, result: v12.ScanResult, prediction_date: str) -> list[dict[str, Any]]:
        if result.signal.startswith("A"):
            signal_code = "A"
            horizons = A_HORIZONS
        elif result.signal.startswith("C5"):
            signal_code = "C5"
            horizons = C5_HORIZONS
        else:
            signal_code = "D"
            horizons = D_HORIZONS

        rows: list[dict[str, Any]] = []
        for horizon in horizons:
            rows.append(
                {
                    "model_name": f"{MODEL_PREFIX}_{signal_code}_D{horizon}",
                    "model_version": MODEL_VERSION,
                    "ticker": result.ticker,
                    "prediction_date": prediction_date,
                    "target_date": self.resolve_target_date(prediction_date, horizon),
                    "direction": "UP",
                    "confidence": self._confidence_for(result),
                    "score": round(float(result.score), 4),
                    "regime": None,
                    "sector": result.sector,
                }
            )
        return rows

    def record_snapshot(self, snapshot: v12.Snapshot, regime_info: dict[str, object]) -> dict[str, int]:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self._save_snapshot_artifact(snapshot, regime_info)
        self._save_regime(snapshot, regime_info)

        existing_keys = self._existing_prediction_keys(snapshot.analyzed_date)
        rows: list[dict[str, Any]] = []
        for result in snapshot.results_a + snapshot.results_c5 + snapshot.results_d:
            for row in self._prediction_rows_from_result(result, snapshot.analyzed_date):
                row["regime"] = snapshot.regime_label
                key = (str(row["model_name"]), str(row["ticker"]), str(row["target_date"]))
                if key in existing_keys:
                    continue
                rows.append(row)

        saved = self.db.save_predictions_bulk(rows) if rows else 0
        return {
            "saved_predictions": saved,
            "signals": len(snapshot.results_a) + len(snapshot.results_c5) + len(snapshot.results_d),
            "blocked": len(snapshot.blocked_extreme),
        }

    def _save_snapshot_artifact(self, snapshot: v12.Snapshot, regime_info: dict[str, object]) -> None:
        artifact = {
            "model_name": MODEL_PREFIX,
            "model_version": MODEL_VERSION,
            "analyzed_date": snapshot.analyzed_date,
            "prediction_for": v12.next_business_day(snapshot.analyzed_date),
            "run_started": snapshot.run_started.isoformat(timespec="seconds"),
            "run_finished": snapshot.run_finished.isoformat(timespec="seconds"),
            "db_last_write": snapshot.db_last_write.isoformat(timespec="seconds") if snapshot.db_last_write else None,
            "freshness": snapshot.freshness,
            "regime_label": snapshot.regime_label,
            "regime_info": regime_info,
            "breadth_pct": snapshot.breadth_pct,
            "quality_alerts": snapshot.quality_alerts,
            "results_a": [asdict(result) for result in snapshot.results_a],
            "results_c5": [asdict(result) for result in snapshot.results_c5],
            "results_d": [asdict(result) for result in snapshot.results_d],
            "blocked_extreme": [asdict(result) for result in snapshot.blocked_extreme],
            "runtime_context": base.build_runtime_context(ROOT / "SCANNER" / "invertir_v12.py", self.latest_db_date),
        }
        path = RUNS_DIR / f"{snapshot.analyzed_date}.json"
        path.write_text(json.dumps(artifact, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        self.db.save_model_run_snapshot(
            model_key="V12",
            model_name=MODEL_PREFIX,
            model_version=MODEL_VERSION,
            role="scanner",
            analyzed_date=snapshot.analyzed_date,
            prediction_for=str(artifact["prediction_for"]),
            freshness=snapshot.freshness,
            regime_label=snapshot.regime_label,
            breadth_pct=snapshot.breadth_pct,
            signal_count=len(snapshot.results_a) + len(snapshot.results_c5) + len(snapshot.results_d),
            snapshot_payload=artifact,
        )

    def _save_regime(self, snapshot: v12.Snapshot, regime_info: dict[str, object]) -> None:
        spy_df = self.prepared["SPY"].loc[: pd.Timestamp(snapshot.analyzed_date)]
        spy_ret_20d = None
        if len(spy_df) >= 21:
            before = float(spy_df["Close"].iloc[-21])
            after = float(spy_df["Close"].iloc[-1])
            if before != 0:
                spy_ret_20d = round((after / before - 1.0) * 100.0, 3)

        vix_level = None
        if "VIX" in self.prepared:
            vix_df = self.prepared["VIX"].loc[: pd.Timestamp(snapshot.analyzed_date)]
            if not vix_df.empty:
                vix_level = round(float(vix_df["Close"].iloc[-1]), 3)

        details = {
            "source": "aprendizaje_operativo_v12",
            "breadth_pct": snapshot.breadth_pct,
            "signals_a": len(snapshot.results_a),
            "signals_c5": len(snapshot.results_c5),
            "signals_d": len(snapshot.results_d),
            "blocked_extreme": len(snapshot.blocked_extreme),
            "quality_alerts": len(snapshot.quality_alerts),
            "freshness": snapshot.freshness,
        }
        self.db.save_regime(
            date_str=snapshot.analyzed_date,
            trend="ABOVE_SMA50" if bool(regime_info.get("above_sma")) else "BELOW_SMA50",
            vol="LOW" if bool(regime_info.get("low_vol")) else "HIGH",
            credit="N/A",
            composite=snapshot.regime_label,
            vix=vix_level,
            spy_ret=spy_ret_20d,
            details=json.dumps(details, ensure_ascii=True),
        )

    def report_status(self) -> dict[str, Any]:
        row = self.db.conn.execute(
            """
            SELECT
                COUNT(*) AS predictions_count,
                COUNT(DISTINCT prediction_date) AS prediction_days,
                MIN(prediction_date) AS first_prediction_date,
                MAX(prediction_date) AS last_prediction_date
            FROM predictions
            WHERE model_name LIKE ?
            """,
            (f"{MODEL_PREFIX}_%",),
        ).fetchone()
        regimes_count = self.db.conn.execute(
            "SELECT COUNT(*) FROM regimes WHERE details LIKE ?",
            ("%aprendizaje_operativo_v12%",),
        ).fetchone()[0]
        return {
            "predictions_count": int(row[0] or 0),
            "prediction_days": int(row[1] or 0),
            "first_prediction_date": row[2],
            "last_prediction_date": row[3],
            "regimes_count": int(regimes_count),
        }

    def context_memory_rows(self, regime_label: str) -> list[dict[str, Any]]:
        specs: list[tuple[str, str]] = []
        if regime_label == "SEGURO":
            specs.append((f"{MODEL_PREFIX}_A_D7", "A / D7"))
            specs.append((f"{MODEL_PREFIX}_C5_D7", "C5 / D7"))
        else:
            specs.append((f"{MODEL_PREFIX}_C5_D4", "C5 / D4"))
            specs.append((f"{MODEL_PREFIX}_C5_D7", "C5 / D7"))

        rows: list[dict[str, Any]] = []
        for model_name, label in specs:
            row = self.db.conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    AVG(o.hit) * 100.0 AS accuracy_pct,
                    AVG(o.actual_return) * 100.0 AS avg_return_pct
                FROM predictions p
                JOIN outcomes o ON p.id = o.prediction_id
                WHERE p.model_name = ? AND p.regime = ?
                """,
                (model_name, regime_label),
            ).fetchone()
            total = int(row[0] or 0)
            if total == 0:
                continue
            rows.append(
                {
                    "label": label,
                    "regime": regime_label,
                    "total": total,
                    "accuracy_pct": round(float(row[1]), 2),
                    "avg_return_pct": round(float(row[2]), 3),
                }
            )

        d_row = self.db.conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                AVG(o.hit) * 100.0 AS accuracy_pct,
                AVG(o.actual_return) * 100.0 AS avg_return_pct
            FROM predictions p
            JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name = ?
            """,
            (f"{MODEL_PREFIX}_D_D10",),
        ).fetchone()
        d_total = int(d_row[0] or 0)
        if d_total > 0:
            rows.append(
                {
                    "label": "D / D10",
                    "regime": "GLOBAL",
                    "total": d_total,
                    "accuracy_pct": round(float(d_row[1]), 2),
                    "avg_return_pct": round(float(d_row[2]), 3),
                }
            )
        return rows

    def daily_summary_text(self, snapshot: v12.Snapshot) -> str:
        status = self.report_status()
        overall = self.report()
        memory_rows = self.context_memory_rows(snapshot.regime_label)
        signals_total = len(snapshot.results_a) + len(snapshot.results_c5) + len(snapshot.results_d)

        lines = [
            "=" * 110,
            f"  RESUMEN DIARIO V12 | {snapshot.analyzed_date}",
            "=" * 110,
            f"  Prediccion para      : {v12.next_business_day(snapshot.analyzed_date)}",
            f"  Regimen actual       : {snapshot.regime_label}",
            f"  Breadth actual       : {snapshot.breadth_pct:.1f}%",
            f"  Oportunidades hoy    : {signals_total} ({len(snapshot.results_a)} A + {len(snapshot.results_c5)} C5 + {len(snapshot.results_d)} D)",
            f"  Bloqueadas hoy       : {len(snapshot.blocked_extreme)}",
            "-" * 110,
            "  MEMORIA ACUMULADA",
            f"  Predicciones totales : {status['predictions_count']}",
            f"  Dias con senales     : {status['prediction_days']}",
            f"  Regimenes guardados  : {status['regimes_count']}",
            f"  Rango memoria        : {status['first_prediction_date'] or '-'} -> {status['last_prediction_date'] or '-'}",
            "-" * 110,
            "  CONTEXTO HISTORICO RELEVANTE",
        ]

        if memory_rows:
            for row in memory_rows:
                lines.append(
                    f"  - {row['label']} en {row['regime']}: "
                    f"hit {row['accuracy_pct']:.1f}% | avg {row['avg_return_pct']:+.3f}% | n={row['total']}"
                )
        else:
            lines.append("  - Sin muestra suficiente todavia.")

        lines.append("-" * 110)
        lines.append("  METRICAS POR HORIZONTE")
        if overall.empty:
            lines.append("  Sin datos suficientes.")
        else:
            lines.append(overall.to_string(index=False))

        return "\n".join(lines)


def print_run_summary(snapshot: v12.Snapshot, recorded: dict[str, int], evaluated: dict[str, Any]) -> None:
    print("=" * 90)
    print(f"  APRENDIZAJE OPERATIVO V12 | {snapshot.analyzed_date}")
    print("=" * 90)
    print(f"  Regimen          : {snapshot.regime_label}")
    print(f"  Breadth          : {snapshot.breadth_pct:.1f}%")
    print(f"  Senales A        : {len(snapshot.results_a)}")
    print(f"  Senales C5       : {len(snapshot.results_c5)}")
    print(f"  Senales D        : {len(snapshot.results_d)}")
    print(f"  Bloqueadas       : {len(snapshot.blocked_extreme)}")
    print(f"  Predicciones nuevas guardadas : {recorded['saved_predictions']}")
    print(
        f"  Evaluacion pendiente resuelta : {evaluated['evaluated']} "
        f"(hits {evaluated['hits']} | misses {evaluated['misses']} | errores {evaluated['errors']})"
    )
    print("=" * 90)


def print_report(df: pd.DataFrame, status: dict[str, Any]) -> None:
    print("=" * 110)
    print("  MEMORIA OPERATIVA V12")
    print("=" * 110)
    print(f"  Predicciones totales : {status['predictions_count']}")
    print(f"  Dias con memoria     : {status['prediction_days']}")
    print(f"  Regimenes guardados  : {status['regimes_count']}")
    print(f"  Primer dia           : {status['first_prediction_date'] or '-'}")
    print(f"  Ultimo dia           : {status['last_prediction_date'] or '-'}")
    print("-" * 110)
    if df.empty:
        print("  Sin predicciones registradas aun.")
        return
    print(df.to_string(index=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bucle de aprendizaje operativo para INVERTIR V12")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Registrar un dia y evaluar lo que ya vencio")
    run_parser.add_argument("--date", help="Fecha analizada (YYYY-MM-DD). Si no se pasa, usa la ultima de la DB.")

    backfill_parser = sub.add_parser("backfill", help="Backfill historico del loop operativo")
    backfill_parser.add_argument("--from-date", required=True, help="Fecha inicial (YYYY-MM-DD)")
    backfill_parser.add_argument("--to-date", help="Fecha final (YYYY-MM-DD). Default: ultima de la DB")

    sub.add_parser("report", help="Resumen de memoria y metricas acumuladas V12")
    summary_parser = sub.add_parser("daily-summary", help="Resumen final diario del loop operativo")
    summary_parser.add_argument("--date", help="Fecha base (YYYY-MM-DD). Si no se pasa, usa la ultima de la DB.")
    recompute_parser = sub.add_parser(
        "recompute-outcomes",
        help="Recalcular outcomes V12 con retorno operable (open siguiente -> close target)",
    )
    recompute_parser.add_argument("--to-date", help="Fecha final (YYYY-MM-DD). Default: ultima de la DB.")
    return parser.parse_args()


def run_single(db: TitanDB, requested_date: str | None) -> None:
    engine = OperationalLearningV12(db)
    snapshot, regime_info = engine.build_snapshot(requested_date)
    recorded = engine.record_snapshot(snapshot, regime_info)
    evaluated = engine.evaluate_due_predictions()
    engine.refresh_model_metrics()
    print_run_summary(snapshot, recorded, evaluated)


def run_backfill(db: TitanDB, from_date: str, to_date: str | None) -> None:
    engine = OperationalLearningV12(db)
    start_ts = engine.resolve_as_of(from_date)
    end_ts = engine.resolve_as_of(to_date) if to_date else engine.spy_dates[-1]
    dates = [ts.date().isoformat() for ts in engine.spy_dates if start_ts <= ts <= end_ts]

    total_saved = 0
    total_days = 0
    for date_text in dates:
        snapshot, regime_info = engine.build_snapshot(date_text)
        recorded = engine.record_snapshot(snapshot, regime_info)
        total_saved += recorded["saved_predictions"]
        total_days += 1

    evaluated = engine.evaluate_due_predictions(max_target_date=end_ts.date().isoformat())
    engine.refresh_model_metrics()
    print("=" * 90)
    print(f"  BACKFILL V12 | {dates[0]} -> {dates[-1]}")
    print("=" * 90)
    print(f"  Dias procesados      : {total_days}")
    print(f"  Predicciones guardadas: {total_saved}")
    print(
        f"  Evaluadas            : {evaluated['evaluated']} "
        f"(hits {evaluated['hits']} | misses {evaluated['misses']} | errores {evaluated['errors']})"
    )
    print("=" * 90)


def run_report(db: TitanDB) -> None:
    engine = OperationalLearningV12(db)
    engine.refresh_model_metrics()
    print_report(engine.report(), engine.report_status())


def run_daily_summary(db: TitanDB, requested_date: str | None) -> None:
    engine = OperationalLearningV12(db)
    engine.refresh_model_metrics()
    snapshot, _ = engine.build_snapshot(requested_date)
    path = engine.write_daily_summary(snapshot)
    print(engine.daily_summary_text(snapshot))
    print("-" * 110)
    print(f"  Resumen guardado en: {path}")


def run_recompute_outcomes(db: TitanDB, to_date: str | None) -> None:
    engine = OperationalLearningV12(db)
    evaluated = engine.evaluate_due_predictions(
        max_target_date=to_date or engine.latest_db_date,
        recompute_existing=True,
    )
    engine.refresh_model_metrics()
    print("=" * 90)
    print("  RECOMPUTE OUTCOMES V12")
    print("=" * 90)
    print(f"  Hasta fecha        : {to_date or engine.latest_db_date}")
    print(f"  Evaluadas          : {evaluated['evaluated']}")
    print(f"  Hits               : {evaluated['hits']}")
    print(f"  Misses             : {evaluated['misses']}")
    print(f"  Errores            : {evaluated['errors']}")
    print(f"  Fechas objetivo    : {evaluated['dates']}")
    print("=" * 90)


def main() -> None:
    args = parse_args()
    with TitanDB() as db:
        if args.command == "run":
            run_single(db, args.date)
        elif args.command == "backfill":
            run_backfill(db, args.from_date, args.to_date)
        elif args.command == "report":
            run_report(db)
        elif args.command == "daily-summary":
            run_daily_summary(db, args.date)
        elif args.command == "recompute-outcomes":
            run_recompute_outcomes(db, args.to_date)
        else:
            raise ValueError(f"Comando no soportado: {args.command}")


if __name__ == "__main__":
    main()
