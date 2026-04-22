#!/usr/bin/env python3
"""
Base generica para scanners observados historicos.

Idea:
  - el champion y su cadena operativa siguen aparte
  - los modelos viejos corren como competidores observados
  - guardan picks, outcomes y metricas con la misma disciplina
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import importlib
import json
from pathlib import Path
import platform
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import herramientas.aprendizaje_operativo_v11 as base
from titan_system.core.database import TitanDB


@dataclass(frozen=True)
class ObservedScannerConfig:
    version: int
    scanner_module: str
    scanner_file: str
    learning_file: str
    crash_signal_attr: str
    crash_signal_code: str
    crash_display_label: str
    crash_horizons: tuple[int, ...]
    a_horizons: tuple[int, ...] = (1, 7)


@dataclass
class ObservedSnapshot:
    run_started: datetime
    run_finished: datetime
    analyzed_date: str
    db_last_write: datetime | None
    freshness: str
    regime_label: str
    breadth_pct: float
    results_a: list[Any]
    results_c: list[Any]
    quality_alerts: list[dict[str, object]]
    memory_context: list[str]


def _build_runtime_context(scanner_path: Path, learning_path: Path, latest_db_date: str | None) -> dict[str, object]:
    critical_files = {
        "scanner": scanner_path.resolve(),
        "learning": learning_path.resolve(),
        "validate_market_data": ROOT / "herramientas" / "validate_market_data.py",
        "auto_actualizar": ROOT / "herramientas" / "auto_actualizar.py",
    }
    file_hashes = {
        name: base.file_sha256(path)
        for name, path in critical_files.items()
        if path.exists()
    }
    fingerprint = hashlib.sha256(
        "|".join(f"{name}:{value}" for name, value in sorted(file_hashes.items())).encode("utf-8")
    ).hexdigest()
    return {
        "scanner_path": str(scanner_path.resolve().relative_to(ROOT)),
        "learning_path": str(learning_path.resolve().relative_to(ROOT)),
        "latest_db_date": latest_db_date,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "critical_file_hashes": file_hashes,
        "runtime_fingerprint": fingerprint,
    }


class OperationalLearningObservedAC(base.OperationalLearningV11):
    def __init__(self, db: TitanDB, config: ObservedScannerConfig):
        self.db = db
        self.config = config
        self.model_prefix = f"INVERTIR_V{config.version}"
        self.model_version = f"v{config.version}"
        self.source_tag = f"aprendizaje_operativo_v{config.version}"
        self.run_dir = ROOT / "aprendizaje_operativo" / f"v{config.version}_runs"
        self.report_dir = ROOT / "aprendizaje_operativo" / f"v{config.version}_reports"
        self.learning_path = ROOT / config.learning_file
        self.scanner_path = ROOT / config.scanner_file
        self.scanner = importlib.import_module(config.scanner_module)
        self.crash_signal = getattr(self.scanner, config.crash_signal_attr)

        # La base V11 filtra por estos globals; cada script observado corre en proceso propio.
        base.MODEL_PREFIX = self.model_prefix
        base.MODEL_VERSION = self.model_version
        base.RUNS_DIR = self.run_dir
        base.REPORTS_DIR = self.report_dir
        base.A_HORIZONS = config.a_horizons
        base.C5_HORIZONS = config.crash_horizons

        self.universe_data, self.missing = self.scanner.load_universe_data(db, self.scanner.UNIVERSE)
        self.prepared = self.scanner.precompute_indicators(self.universe_data)
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

    def _historical_freshness(self, analyzed_date: str) -> str:
        if analyzed_date != self.latest_db_date:
            return "HISTORICA"

        today = datetime.now().date()
        latest_dt = datetime.strptime(analyzed_date, "%Y-%m-%d").date()
        staleness = self.scanner.business_days_between(latest_dt, today)
        if staleness <= 1:
            return "AL DIA"
        return f"STALE ({staleness} dias habiles)"

    def prediction_for(self, analyzed_date: str) -> str:
        return self.resolve_target_date(analyzed_date, 1)

    def build_snapshot(self, requested_date: str | None = None) -> tuple[ObservedSnapshot, dict[str, object]]:
        run_started = datetime.now()
        as_of_ts = self.resolve_as_of(requested_date)
        analyzed_date = as_of_ts.date().isoformat()

        regime_safe, regime_info = self.scanner.check_regime(self.prepared["SPY"].loc[:as_of_ts])
        breadth_pct = self._compute_breadth_asof(as_of_ts)
        quality_alerts = self._recent_quality_alerts_asof(as_of_ts)

        results_a: list[Any] = []
        results_c: list[Any] = []

        for ticker in sorted(t for t in self.prepared.keys() if t != "SPY"):
            work = self.prepared[ticker].loc[:as_of_ts]
            if len(work) < 2:
                continue

            if regime_safe:
                sig_a = self.scanner.signal_a_mean_reversion(ticker, work)
                if sig_a is not None:
                    results_a.append(sig_a)

            sig_c = self.crash_signal(ticker, work)
            if sig_c is not None and not any(existing.ticker == ticker for existing in results_a):
                results_c.append(sig_c)

        results_a.sort(key=lambda item: float(item.score), reverse=True)
        results_c.sort(key=lambda item: float(item.score), reverse=True)
        regime_label = "SEGURO" if regime_info.get("safe") else "PELIGRO"
        memory_context = [
            f"{row['label']} en {row['regime']}: hit {row['accuracy_pct']:.1f}% | avg {row['avg_return_pct']:+.3f}% | n={row['total']}"
            for row in self.context_memory_rows(regime_label)
        ]
        snapshot = ObservedSnapshot(
            run_started=run_started,
            run_finished=datetime.now(),
            analyzed_date=analyzed_date,
            db_last_write=self.db_last_write,
            freshness=self._historical_freshness(analyzed_date),
            regime_label=regime_label,
            breadth_pct=float(breadth_pct),
            results_a=results_a,
            results_c=results_c,
            quality_alerts=quality_alerts,
            memory_context=memory_context,
        )
        return snapshot, regime_info

    def _confidence_for(self, result: Any) -> float:
        a_score_min = getattr(self.scanner, "A_SCORE_MIN", getattr(self.scanner, "V7_SCORE_MIN", 30.0))
        if str(result.signal).startswith("A"):
            raw = (float(result.score) - float(a_score_min)) / 50.0
        else:
            raw = float(result.score) / 100.0
        bounded = max(0.05, min(0.99, raw))
        return round(float(bounded), 4)

    def _prediction_rows_from_result(self, result: Any, prediction_date: str) -> list[dict[str, Any]]:
        if str(result.signal).startswith("A"):
            signal_code = "A"
            horizons = self.config.a_horizons
        else:
            signal_code = self.config.crash_signal_code
            horizons = self.config.crash_horizons

        rows: list[dict[str, Any]] = []
        for horizon in horizons:
            rows.append(
                {
                    "model_name": f"{self.model_prefix}_{signal_code}_D{horizon}",
                    "model_version": self.model_version,
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

    def record_snapshot(self, snapshot: ObservedSnapshot, regime_info: dict[str, object]) -> dict[str, int]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._save_snapshot_artifact(snapshot, regime_info)
        self._save_regime(snapshot, regime_info)

        existing_keys = self._existing_prediction_keys(snapshot.analyzed_date)
        rows: list[dict[str, Any]] = []
        for result in snapshot.results_a + snapshot.results_c:
            for row in self._prediction_rows_from_result(result, snapshot.analyzed_date):
                row["regime"] = snapshot.regime_label
                key = (str(row["model_name"]), str(row["ticker"]), str(row["target_date"]))
                if key in existing_keys:
                    continue
                rows.append(row)

        saved = self.db.save_predictions_bulk(rows) if rows else 0
        return {
            "saved_predictions": saved,
            "signals": len(snapshot.results_a) + len(snapshot.results_c),
        }

    def _save_snapshot_artifact(self, snapshot: ObservedSnapshot, regime_info: dict[str, object]) -> None:
        artifact = {
            "model_name": self.model_prefix,
            "model_version": self.model_version,
            "analyzed_date": snapshot.analyzed_date,
            "prediction_for": self.prediction_for(snapshot.analyzed_date),
            "run_started": snapshot.run_started.isoformat(timespec="seconds"),
            "run_finished": snapshot.run_finished.isoformat(timespec="seconds"),
            "db_last_write": snapshot.db_last_write.isoformat(timespec="seconds") if snapshot.db_last_write else None,
            "freshness": snapshot.freshness,
            "regime_label": snapshot.regime_label,
            "regime_info": regime_info,
            "breadth_pct": snapshot.breadth_pct,
            "quality_alerts": snapshot.quality_alerts,
            "memory_context": snapshot.memory_context,
            "results_a": [asdict(result) for result in snapshot.results_a],
            "results_c": [asdict(result) for result in snapshot.results_c],
            "config": {
                "crash_signal_code": self.config.crash_signal_code,
                "crash_display_label": self.config.crash_display_label,
                "a_horizons": list(self.config.a_horizons),
                "crash_horizons": list(self.config.crash_horizons),
            },
            "runtime_context": _build_runtime_context(self.scanner_path, self.learning_path, self.latest_db_date),
        }
        path = self.run_dir / f"{snapshot.analyzed_date}.json"
        path.write_text(json.dumps(artifact, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    def _save_regime(self, snapshot: ObservedSnapshot, regime_info: dict[str, object]) -> None:
        spy_df = self.prepared["SPY"].loc[: pd.Timestamp(snapshot.analyzed_date)]
        spy_ret_20d = None
        if len(spy_df) >= 21:
            before = float(spy_df["Close"].iloc[-21])
            after = float(spy_df["Close"].iloc[-1])
            if before != 0:
                spy_ret_20d = round((after / before - 1.0) * 100.0, 3)

        details = {
            "source": self.source_tag,
            "breadth_pct": snapshot.breadth_pct,
            "signals_a": len(snapshot.results_a),
            "signals_c": len(snapshot.results_c),
            "quality_alerts": len(snapshot.quality_alerts),
            "freshness": snapshot.freshness,
        }
        self.db.save_regime(
            date_str=snapshot.analyzed_date,
            trend="ABOVE_SMA50" if bool(regime_info.get("above_sma")) else "BELOW_SMA50",
            vol="LOW" if bool(regime_info.get("low_vol")) else "HIGH",
            credit="N/A",
            composite=snapshot.regime_label,
            vix=None,
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
            (f"{self.model_prefix}_%",),
        ).fetchone()
        regimes_count = self.db.conn.execute(
            "SELECT COUNT(*) FROM regimes WHERE details LIKE ?",
            (f"%{self.source_tag}%",),
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
        if regime_label == "SEGURO" and self.config.a_horizons:
            final_a = max(self.config.a_horizons)
            specs.append((f"{self.model_prefix}_A_D{final_a}", f"A / D{final_a}"))
        if self.config.crash_horizons:
            final_c = max(self.config.crash_horizons)
            specs.append(
                (
                    f"{self.model_prefix}_{self.config.crash_signal_code}_D{final_c}",
                    f"{self.config.crash_display_label} / D{final_c}",
                )
            )

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
        return rows

    def daily_summary_text(self, snapshot: ObservedSnapshot) -> str:
        status = self.report_status()
        overall = self.report()
        memory_rows = self.context_memory_rows(snapshot.regime_label)
        signals_total = len(snapshot.results_a) + len(snapshot.results_c)

        lines = [
            "=" * 110,
            f"  RESUMEN DIARIO V{self.config.version} | {snapshot.analyzed_date}",
            "=" * 110,
            f"  Prediccion para      : {self.prediction_for(snapshot.analyzed_date)}",
            f"  Regimen actual       : {snapshot.regime_label}",
            f"  Breadth actual       : {snapshot.breadth_pct:.1f}%",
            (
                f"  Oportunidades hoy    : {signals_total} "
                f"({len(snapshot.results_a)} A + {len(snapshot.results_c)} {self.config.crash_display_label})"
            ),
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


def print_run_summary(config: ObservedScannerConfig, snapshot: ObservedSnapshot, recorded: dict[str, int], evaluated: dict[str, Any]) -> None:
    print("=" * 90)
    print(f"  APRENDIZAJE OBSERVADO V{config.version} | {snapshot.analyzed_date}")
    print("=" * 90)
    print(f"  Regimen          : {snapshot.regime_label}")
    print(f"  Breadth          : {snapshot.breadth_pct:.1f}%")
    print(f"  Senales A        : {len(snapshot.results_a)}")
    print(f"  Senales {config.crash_display_label:<7}: {len(snapshot.results_c)}")
    print(f"  Predicciones nuevas guardadas : {recorded['saved_predictions']}")
    print(
        f"  Evaluacion pendiente resuelta : {evaluated['evaluated']} "
        f"(hits {evaluated['hits']} | misses {evaluated['misses']} | errores {evaluated['errors']})"
    )
    print("=" * 90)


def print_report(config: ObservedScannerConfig, df: pd.DataFrame, status: dict[str, Any]) -> None:
    print("=" * 110)
    print(f"  MEMORIA OBSERVADA V{config.version}")
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


def parse_args(version: int) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Bucle de aprendizaje observado para INVERTIR V{version}")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Registrar un dia y evaluar lo que ya vencio")
    run_parser.add_argument("--date", help="Fecha analizada (YYYY-MM-DD). Si no se pasa, usa la ultima de la DB.")

    backfill_parser = sub.add_parser("backfill", help="Backfill historico del loop observado")
    backfill_parser.add_argument("--from-date", required=True, help="Fecha inicial (YYYY-MM-DD)")
    backfill_parser.add_argument("--to-date", help="Fecha final (YYYY-MM-DD). Default: ultima de la DB")

    sub.add_parser("report", help=f"Resumen de memoria y metricas acumuladas V{version}")
    summary_parser = sub.add_parser("daily-summary", help="Resumen final diario del loop observado")
    summary_parser.add_argument("--date", help="Fecha base (YYYY-MM-DD). Si no se pasa, usa la ultima de la DB.")
    recompute_parser = sub.add_parser(
        "recompute-outcomes",
        help=f"Recalcular outcomes V{version} con retorno operable (open siguiente -> close target)",
    )
    recompute_parser.add_argument("--to-date", help="Fecha final (YYYY-MM-DD). Default: ultima de la DB.")
    return parser.parse_args()


def run_single(engine: OperationalLearningObservedAC) -> None:
    snapshot, regime_info = engine.build_snapshot(engine.requested_date)
    recorded = engine.record_snapshot(snapshot, regime_info)
    evaluated = engine.evaluate_due_predictions()
    engine.refresh_model_metrics()
    print_run_summary(engine.config, snapshot, recorded, evaluated)


def run_backfill(engine: OperationalLearningObservedAC, from_date: str, to_date: str | None) -> None:
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
    print(f"  BACKFILL OBSERVADO V{engine.config.version} | {dates[0]} -> {dates[-1]}")
    print("=" * 90)
    print(f"  Dias procesados      : {total_days}")
    print(f"  Predicciones guardadas: {total_saved}")
    print(
        f"  Evaluadas            : {evaluated['evaluated']} "
        f"(hits {evaluated['hits']} | misses {evaluated['misses']} | errores {evaluated['errors']})"
    )
    print("=" * 90)


def run_report(engine: OperationalLearningObservedAC) -> None:
    engine.refresh_model_metrics()
    print_report(engine.config, engine.report(), engine.report_status())


def run_daily_summary(engine: OperationalLearningObservedAC) -> None:
    engine.refresh_model_metrics()
    snapshot, _ = engine.build_snapshot(engine.requested_date)
    path = engine.write_daily_summary(snapshot)
    print(engine.daily_summary_text(snapshot))
    print("-" * 110)
    print(f"  Resumen guardado en: {path}")


def run_recompute_outcomes(engine: OperationalLearningObservedAC, to_date: str | None) -> None:
    evaluated = engine.evaluate_due_predictions(
        max_target_date=to_date or engine.latest_db_date,
        recompute_existing=True,
    )
    engine.refresh_model_metrics()
    print("=" * 90)
    print(f"  RECOMPUTE OUTCOMES OBSERVADO V{engine.config.version}")
    print("=" * 90)
    print(f"  Hasta fecha        : {to_date or engine.latest_db_date}")
    print(f"  Evaluadas          : {evaluated['evaluated']}")
    print(f"  Hits               : {evaluated['hits']}")
    print(f"  Misses             : {evaluated['misses']}")
    print(f"  Errores            : {evaluated['errors']}")
    print("=" * 90)


def main_for_config(config: ObservedScannerConfig) -> int:
    args = parse_args(config.version)
    requested_date = getattr(args, "date", None)

    with TitanDB() as db:
        engine = OperationalLearningObservedAC(db, config)
        engine.requested_date = requested_date
        if args.command == "run":
            run_single(engine)
            return 0
        if args.command == "backfill":
            run_backfill(engine, args.from_date, args.to_date)
            return 0
        if args.command == "report":
            run_report(engine)
            return 0
        if args.command == "daily-summary":
            run_daily_summary(engine)
            return 0
        if args.command == "recompute-outcomes":
            run_recompute_outcomes(engine, args.to_date)
            return 0
    return 1
