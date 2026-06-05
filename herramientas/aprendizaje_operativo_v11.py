#!/usr/bin/env python3
"""
APRENDIZAJE OPERATIVO V11
=========================

Bucle operativo para que Claude:
  - recuerde que predijo V11 cada dia
  - guarde el regimen/contexto del mercado
  - mida resultados cuando las fechas objetivo ya existen en la DB
  - deje artefactos diarios auditables fuera de SCANNER/

Uso rapido:
  python herramientas/aprendizaje_operativo_v11.py run
  python herramientas/aprendizaje_operativo_v11.py run --date 2026-03-20
  python herramientas/aprendizaje_operativo_v11.py backfill --from-date 2026-03-01
  python herramientas/aprendizaje_operativo_v11.py report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import re
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from SCANNER import invertir_v11 as v11
from titan_system.core.database import TitanDB


MODEL_PREFIX = "INVERTIR_V11"
MODEL_VERSION = "v11"
RUNS_DIR = ROOT / "aprendizaje_operativo" / "v11_runs"
REPORTS_DIR = ROOT / "aprendizaje_operativo" / "v11_reports"
A_HORIZONS = (1, 7)
C5_HORIZONS = (1, 4, 7)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_runtime_context(scanner_path: Path, latest_db_date: str | None) -> dict[str, object]:
    critical_files = {
        "scanner": scanner_path.resolve(),
        "learning": Path(__file__).resolve(),
        "validate_market_data": ROOT / "herramientas" / "validate_market_data.py",
        "auto_actualizar": ROOT / "herramientas" / "auto_actualizar.py",
    }
    file_hashes = {
        name: file_sha256(path)
        for name, path in critical_files.items()
        if path.exists()
    }
    fingerprint = hashlib.sha256(
        "|".join(f"{name}:{value}" for name, value in sorted(file_hashes.items())).encode("utf-8")
    ).hexdigest()
    return {
        "scanner_path": str(scanner_path.resolve().relative_to(ROOT)),
        "latest_db_date": latest_db_date,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "critical_file_hashes": file_hashes,
        "runtime_fingerprint": fingerprint,
    }
HORIZON_RE = re.compile(r"_D(\d+)$")


class OperationalLearningV11:
    def __init__(self, db: TitanDB):
        self.db = db
        self.universe_data, self.missing = v11.load_universe_data(db, v11.UNIVERSE)
        # Commit la transaccion de lectura antes de precompute_indicators.
        # precompute_indicators puede tardar 30-90s de CPU puro; con la
        # transaccion abierta Supabase mata la sesion por
        # idle_in_transaction_session_timeout. El commit evita ese idle.
        if db.using_sqlalchemy_compat:
            db.conn.commit()
        self.prepared = v11.precompute_indicators(self.universe_data)
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

    def resolve_as_of(self, requested_date: str | None) -> pd.Timestamp:
        if requested_date is None:
            return self.spy_dates[-1]

        ts = pd.Timestamp(requested_date)
        candidates = self.spy_dates[self.spy_dates <= ts]
        if len(candidates) == 0:
            raise ValueError(f"No hay fechas en DB <= {requested_date}")
        return candidates[-1]

    def trading_day_offset(self, date_text: str, days_forward: int) -> str | None:
        idx = self.date_to_idx.get(date_text)
        if idx is None:
            return None
        target_idx = idx + days_forward
        if target_idx >= len(self.spy_dates):
            return None
        return self.spy_dates[target_idx].date().isoformat()

    def projected_business_day_offset(self, date_text: str, days_forward: int) -> str:
        cursor = pd.Timestamp(date_text).date()
        remaining = days_forward
        while remaining > 0:
            cursor += pd.Timedelta(days=1)
            if cursor.weekday() < 5:
                remaining -= 1
        return cursor.isoformat()

    def resolve_target_date(self, prediction_date: str, days_forward: int) -> str:
        actual = self.trading_day_offset(prediction_date, days_forward)
        if actual is not None:
            return actual
        return self.projected_business_day_offset(prediction_date, days_forward)

    def extract_horizon(self, model_name: str) -> int | None:
        match = HORIZON_RE.search(model_name)
        if not match:
            return None
        return int(match.group(1))

    def _historical_freshness(self, analyzed_date: str) -> str:
        if analyzed_date != self.latest_db_date:
            return "HISTORICA"

        today = datetime.now().date()
        latest_dt = datetime.strptime(analyzed_date, "%Y-%m-%d").date()
        staleness = v11.business_days_between(latest_dt, today)
        if staleness <= 1:
            return "AL DIA"
        return f"STALE ({staleness} dias habiles)"

    def _compute_breadth_asof(self, as_of_ts: pd.Timestamp) -> float:
        eligible = []
        for ticker, df in self.prepared.items():
            if ticker == "SPY":
                continue
            work = df.loc[:as_of_ts]
            if len(work) < 55:
                continue
            price = work["Close"].iloc[-1]
            sma50 = work["SMA50"].iloc[-1]
            if pd.isna(price) or pd.isna(sma50):
                continue
            eligible.append(bool(price > sma50))
        if not eligible:
            return 0.0
        return round(sum(eligible) / len(eligible) * 100, 1)

    def _recent_quality_alerts_asof(self, as_of_ts: pd.Timestamp) -> list[dict[str, object]]:
        alerts: list[dict[str, object]] = []
        for ticker, df in self.prepared.items():
            if ticker == "SPY":
                continue
            work = df.loc[:as_of_ts]
            if work.empty or "CORP_ACTION_DAY" not in work.columns:
                continue
            flagged = work[work["CORP_ACTION_DAY"]]
            if flagged.empty:
                continue
            last_idx = flagged.index[-1]
            if (work.index[-1] - last_idx).days > 10:
                continue
            last = flagged.iloc[-1]
            alerts.append(
                {
                    "ticker": ticker,
                    "date": last_idx.date().isoformat(),
                    "ret1": round(float(last["RET1"] * 100), 1),
                    "intraday": round(float(last["INTRADAY"] * 100), 1),
                    "range_pct": round(float(last["RANGE_PCT"] * 100), 1),
                }
            )
        alerts.sort(key=lambda item: item["date"], reverse=True)
        return alerts

    def build_snapshot(self, requested_date: str | None = None) -> tuple[v11.Snapshot, dict[str, object]]:
        run_started = datetime.now()
        as_of_ts = self.resolve_as_of(requested_date)
        analyzed_date = as_of_ts.date().isoformat()

        regime_safe, regime_info = v11.check_regime(self.prepared["SPY"].loc[:as_of_ts])
        breadth_pct = self._compute_breadth_asof(as_of_ts)
        quality_alerts = self._recent_quality_alerts_asof(as_of_ts)

        results_a: list[v11.ScanResult] = []
        results_c5: list[v11.ScanResult] = []
        blocked_extreme: list[v11.ScanResult] = []

        for ticker in sorted(t for t in self.prepared.keys() if t != "SPY"):
            work = self.prepared[ticker].loc[:as_of_ts]
            if len(work) < 2:
                continue

            if regime_safe:
                sig_a = v11.signal_a_mean_reversion(ticker, work)
                if sig_a is not None:
                    results_a.append(sig_a)

            c_candidate = v11.build_c5_candidate(ticker, work)
            if c_candidate is None:
                continue
            if any(existing.ticker == ticker for existing in results_a):
                continue
            if v11.c5_is_preferred(c_candidate):
                results_c5.append(c_candidate)
            else:
                blocked_extreme.append(c_candidate)

        regime_label = "SEGURO" if regime_info.get("safe") else "PELIGRO"
        all_results = v11.apply_priority_layer(self.db, results_a + results_c5, regime_label, analyzed_date)
        results_a = [result for result in all_results if result.signal.startswith("A")]
        results_c5 = [result for result in all_results if result.signal.startswith("C5")]
        blocked_extreme.sort(key=lambda item: item.score, reverse=True)

        memory_context = [
            f"{row['label']} en {row['regime']}: hit {row['accuracy_pct']:.1f}% | avg {row['avg_return_pct']:+.3f}% | n={row['total']}"
            for row in self.context_memory_rows(regime_label)
        ]
        snapshot = v11.Snapshot(
            run_started=run_started,
            run_finished=datetime.now(),
            analyzed_date=analyzed_date,
            db_last_write=self.db_last_write,
            freshness=self._historical_freshness(analyzed_date),
            regime_label=regime_label,
            breadth_pct=float(breadth_pct),
            results_a=results_a,
            results_c5=results_c5,
            blocked_extreme=blocked_extreme,
            quality_alerts=quality_alerts,
            memory_context=memory_context,
        )
        return snapshot, regime_info

    def _confidence_for(self, result: v11.ScanResult) -> float:
        if result.signal.startswith("A"):
            raw = (result.score - v11.A_SCORE_MIN) / 50.0
        else:
            raw = result.score / max(v11.C_SCORE_MAX, 1.0)
        bounded = max(0.05, min(0.99, raw))
        return round(float(bounded), 4)

    def _prediction_rows_from_result(self, result: v11.ScanResult, prediction_date: str) -> list[dict[str, Any]]:
        signal_code = "A" if result.signal.startswith("A") else "C5"
        horizons = A_HORIZONS if signal_code == "A" else C5_HORIZONS
        rows: list[dict[str, Any]] = []
        for horizon in horizons:
            target_date = self.resolve_target_date(prediction_date, horizon)
            rows.append(
                {
                    "model_name": f"{MODEL_PREFIX}_{signal_code}_D{horizon}",
                    "model_version": MODEL_VERSION,
                    "ticker": result.ticker,
                    "prediction_date": prediction_date,
                    "target_date": target_date,
                    "direction": "UP",
                    "confidence": self._confidence_for(result),
                    "score": round(float(result.score), 4),
                    "regime": None,  # completado al guardar
                    "sector": result.sector,
                }
            )
        return rows

    def _existing_prediction_keys(self, prediction_date: str) -> set[tuple[str, str, str]]:
        rows = self.db.conn.execute(
            """
            SELECT model_name, ticker, target_date
            FROM predictions
            WHERE prediction_date = ? AND model_name LIKE ?
            """,
            (prediction_date, f"{MODEL_PREFIX}_%"),
        ).fetchall()
        return {(str(row[0]), str(row[1]), str(row[2])) for row in rows}

    def record_snapshot(self, snapshot: v11.Snapshot, regime_info: dict[str, object]) -> dict[str, int]:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self._save_snapshot_artifact(snapshot, regime_info)
        self._save_regime(snapshot, regime_info)

        existing_keys = self._existing_prediction_keys(snapshot.analyzed_date)
        rows: list[dict[str, Any]] = []
        for result in snapshot.results_a + snapshot.results_c5:
            for row in self._prediction_rows_from_result(result, snapshot.analyzed_date):
                row["regime"] = snapshot.regime_label
                key = (str(row["model_name"]), str(row["ticker"]), str(row["target_date"]))
                if key in existing_keys:
                    continue
                rows.append(row)

        saved = self.db.save_predictions_bulk(rows) if rows else 0
        return {
            "saved_predictions": saved,
            "signals": len(snapshot.results_a) + len(snapshot.results_c5),
            "blocked": len(snapshot.blocked_extreme),
        }

    def _save_snapshot_artifact(self, snapshot: v11.Snapshot, regime_info: dict[str, object]) -> None:
        artifact = {
            "model_name": MODEL_PREFIX,
            "model_version": MODEL_VERSION,
            "analyzed_date": snapshot.analyzed_date,
            "prediction_for": v11.next_business_day(snapshot.analyzed_date),
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
            "blocked_extreme": [asdict(result) for result in snapshot.blocked_extreme],
            "runtime_context": build_runtime_context(ROOT / "SCANNER" / "invertir_v11.py", self.latest_db_date),
        }
        path = RUNS_DIR / f"{snapshot.analyzed_date}.json"
        path.write_text(json.dumps(artifact, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        self.db.save_model_run_snapshot(
            model_key="V11",
            model_name=MODEL_PREFIX,
            model_version=MODEL_VERSION,
            role="base",
            analyzed_date=snapshot.analyzed_date,
            prediction_for=str(artifact["prediction_for"]),
            freshness=snapshot.freshness,
            regime_label=snapshot.regime_label,
            breadth_pct=snapshot.breadth_pct,
            signal_count=len(snapshot.results_a) + len(snapshot.results_c5),
            snapshot_payload=artifact,
        )

    def _save_regime(self, snapshot: v11.Snapshot, regime_info: dict[str, object]) -> None:
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
            "source": "aprendizaje_operativo_v11",
            "breadth_pct": snapshot.breadth_pct,
            "signals_a": len(snapshot.results_a),
            "signals_c5": len(snapshot.results_c5),
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

    def evaluate_due_predictions(
        self,
        max_target_date: str | None = None,
        recompute_existing: bool = False,
    ) -> dict[str, Any]:
        if max_target_date is None:
            max_target_date = self.latest_db_date

        if recompute_existing:
            due_dates = [
                row[0]
                for row in self.db.conn.execute(
                    """
                    SELECT DISTINCT p.target_date
                    FROM predictions p
                    WHERE p.model_name LIKE ? AND p.target_date <= ?
                    ORDER BY p.target_date
                    """,
                    (f"{MODEL_PREFIX}_%", max_target_date),
                ).fetchall()
            ]
        else:
            due_dates = [
                row[0]
                for row in self.db.conn.execute(
                    """
                    SELECT DISTINCT p.target_date
                    FROM predictions p
                    LEFT JOIN outcomes o ON p.id = o.prediction_id
                    WHERE p.model_name LIKE ? AND o.id IS NULL AND p.target_date <= ?
                    ORDER BY p.target_date
                    """,
                    (f"{MODEL_PREFIX}_%", max_target_date),
                ).fetchall()
            ]

        summary = {"evaluated": 0, "hits": 0, "misses": 0, "errors": 0, "dates": len(due_dates)}
        
        # === BATCH OPTIMIZATION (2026-06-05): Fetch ALL due predictions + needed prices in 2-3 queries instead of N+1 ===
        # Fetch ALL pending predictions in ONE query (using IN with all target_dates)
        if recompute_existing:
            all_pending = self.db.conn.execute(
                f"""
                SELECT p.id, p.model_name, p.ticker, p.direction, p.prediction_date, p.target_date
                FROM predictions p
                WHERE p.model_name LIKE ? AND p.target_date IN ({','.join('?' * len(due_dates))})
                ORDER BY p.target_date, p.ticker, p.prediction_date
                """,
                (f"{MODEL_PREFIX}_%", *due_dates),
            ).fetchall()
        else:
            all_pending = self.db.conn.execute(
                f"""
                SELECT p.id, p.model_name, p.ticker, p.direction, p.prediction_date, p.target_date
                FROM predictions p
                LEFT JOIN outcomes o ON p.id = o.prediction_id
                WHERE p.model_name LIKE ? AND p.target_date IN ({','.join('?' * len(due_dates))}) AND o.id IS NULL
                ORDER BY p.target_date, p.ticker, p.prediction_date
                """,
                (f"{MODEL_PREFIX}_%", *due_dates),
            ).fetchall()

        # Pre-compute needed dates + metadata for all predictions
        needed_dates_set = set()
        pred_meta = {}  # Map pred_id -> (model_name, ticker, pred_date, stored_target, dir, entry_date, actual_target, horizon)
        
        for pred_id, model_name, ticker, predicted_dir, pred_date, stored_target_date in all_pending:
            pred_date_str = str(pred_date)
            stored_target_date_str = str(stored_target_date)
            horizon = self.extract_horizon(str(model_name))
            
            if horizon is None:
                summary["errors"] += 1
                continue
            
            entry_date = self.trading_day_offset(pred_date_str, 1)
            actual_target_date = self.trading_day_offset(pred_date_str, horizon)
            
            if entry_date is None or actual_target_date is None:
                summary["errors"] += 1
                continue
            if actual_target_date > max_target_date:
                continue
            
            # Register needed price dates
            needed_dates_set.add((ticker, entry_date))
            needed_dates_set.add((ticker, actual_target_date))
            pred_meta[pred_id] = (model_name, ticker, pred_date_str, stored_target_date_str, predicted_dir, entry_date, actual_target_date, horizon)

        # Batch fetch ALL needed prices in ONE query
        prices_map = {}  # Map (ticker, date) -> (open, close)
        if needed_dates_set:
            needed_list = list(needed_dates_set)
            placeholders = ",".join(f"(?,?)" for _ in needed_list)
            flat_params = [item for pair in needed_list for item in pair]
            
            query = f"""
                SELECT ticker, date, open, close
                FROM prices
                WHERE (ticker, date) IN ({placeholders})
            """
            for ticker, date, open_price, close_price in self.db.conn.execute(query, flat_params).fetchall():
                prices_map[(ticker, date)] = (open_price, close_price)

        # Process all predictions with pre-fetched data (NO DB QUERIES IN LOOP)
        outcomes_to_insert = []
        for pred_id in list(pred_meta.keys()):
            model_name, ticker, pred_date_str, stored_target_date_str, predicted_dir, entry_date, actual_target_date, horizon = pred_meta[pred_id]
            
            # Check if stored target_date needs update
            if stored_target_date_str != actual_target_date:
                existing_row = self.db.conn.execute(
                    """
                    SELECT id
                    FROM predictions
                    WHERE model_name = ? AND ticker = ? AND prediction_date = ? AND target_date = ?
                    """,
                    (model_name, ticker, pred_date_str, actual_target_date),
                ).fetchone()
                if existing_row and int(existing_row[0]) != int(pred_id):
                    self.db.conn.execute("DELETE FROM predictions WHERE id = ?", (pred_id,))
                    pred_id = int(existing_row[0])
                else:
                    self.db.conn.execute(
                        "UPDATE predictions SET target_date = ? WHERE id = ?",
                        (actual_target_date, pred_id),
                    )

            # Lookup pre-fetched prices (NO QUERY)
            entry_row = prices_map.get((ticker, entry_date))
            target_row = prices_map.get((ticker, actual_target_date))

            if entry_row is None or target_row is None:
                summary["errors"] += 1
                continue

            price_before = entry_row[0]
            entry_close_chk = entry_row[1]
            price_after = target_row[0]
            
            if price_before in (None, 0) or price_after is None:
                summary["errors"] += 1
                continue
            # Guard: open == close sugiere barra incompleta (datos pre-cierre o intraday).
            if entry_close_chk is not None and abs(float(price_before) - float(entry_close_chk)) < 1e-6:
                summary["errors"] += 1
                continue

            actual_return = (price_after - price_before) / price_before
            actual_direction = "UP" if actual_return >= 0 else "DOWN"
            hit = 1 if str(predicted_dir).upper() == actual_direction else 0

            outcomes_to_insert.append((pred_id, actual_direction, actual_return, hit))
            summary["evaluated"] += 1
            if hit:
                summary["hits"] += 1
            else:
                summary["misses"] += 1

        # Batch insert ALL outcomes in ONE operation
        if outcomes_to_insert:
            self.db.conn.executemany(
                """
                INSERT OR REPLACE INTO outcomes
                    (prediction_id, actual_direction, actual_return, hit)
                VALUES (?, ?, ?, ?)
                """,
                outcomes_to_insert,
            )
        
        self.db.conn.commit()
        return summary

    def report(self) -> pd.DataFrame:
        df = self.db.execute_raw(
            """
            SELECT
                p.model_name,
                COUNT(*) AS total_predictions,
                SUM(CASE WHEN o.id IS NOT NULL THEN 1 ELSE 0 END) AS evaluated,
                AVG(o.hit) * 100 AS accuracy_pct,
                AVG(o.actual_return) * 100 AS avg_return_pct,
                AVG(p.confidence) * 100 AS avg_confidence_pct
            FROM predictions p
            LEFT JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name LIKE ?
            GROUP BY p.model_name
            ORDER BY p.model_name
            """,
            (f"{MODEL_PREFIX}_%",),
        )
        for column, digits in {
            "accuracy_pct": 2,
            "avg_return_pct": 3,
            "avg_confidence_pct": 2,
        }.items():
            if column in df.columns:
                df[column] = df[column].apply(
                    lambda value, d=digits: round(float(value), d) if pd.notna(value) else None
                )
        return df

    def refresh_model_metrics(self) -> int:
        metrics_df = self.db.execute_raw(
            """
            SELECT
                p.model_name,
                p.prediction_date,
                p.target_date,
                p.confidence,
                o.hit,
                o.actual_return
            FROM predictions p
            LEFT JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name LIKE ?
            ORDER BY p.model_name, p.prediction_date, p.target_date
            """,
            (f"{MODEL_PREFIX}_%",),
        )
        if metrics_df.empty:
            return 0

        rows: list[dict[str, Any]] = []
        for model_name, group in metrics_df.groupby("model_name"):
            evaluated = group[group["actual_return"].notna()].copy()
            returns = evaluated["actual_return"].astype(float) if not evaluated.empty else pd.Series(dtype=float)
            total_predictions = int(len(group))
            correct_predictions = int(evaluated["hit"].fillna(0).astype(int).sum()) if not evaluated.empty else 0
            accuracy = float(evaluated["hit"].mean()) if not evaluated.empty else None
            avg_confidence = float(group["confidence"].dropna().mean()) if group["confidence"].notna().any() else None
            avg_right = (
                float(evaluated.loc[evaluated["hit"] == 1, "actual_return"].mean())
                if not evaluated.loc[evaluated["hit"] == 1].empty
                else None
            )
            avg_wrong = (
                float(evaluated.loc[evaluated["hit"] == 0, "actual_return"].mean())
                if not evaluated.loc[evaluated["hit"] == 0].empty
                else None
            )

            profit_factor = None
            if not returns.empty:
                gains = float(returns[returns > 0].sum())
                losses = float(returns[returns < 0].sum())
                if losses < 0:
                    profit_factor = gains / abs(losses)

            sharpe_ratio = None
            if len(returns) >= 2:
                std = float(returns.std(ddof=1))
                if std > 0:
                    sharpe_ratio = float(returns.mean() / std * (len(returns) ** 0.5))

            max_drawdown = None
            if not returns.empty:
                curve = (1.0 + returns).cumprod()
                peaks = curve.cummax()
                drawdown = curve / peaks - 1.0
                max_drawdown = float(drawdown.min())

            rows.append(
                {
                    "model_name": str(model_name),
                    "period_start": str(group["prediction_date"].min()),
                    "period_end": str(group["target_date"].max()),
                    "total_predictions": total_predictions,
                    "correct_predictions": correct_predictions,
                    "accuracy": accuracy,
                    "avg_confidence": avg_confidence,
                    "avg_return_when_right": avg_right,
                    "avg_return_when_wrong": avg_wrong,
                    "profit_factor": profit_factor,
                    "sharpe_ratio": sharpe_ratio,
                    "max_drawdown": max_drawdown,
                }
            )

        return self.db.save_model_metrics_bulk(rows)

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
            ("%aprendizaje_operativo_v11%",),
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
        return rows

    def daily_summary_text(self, snapshot: v11.Snapshot) -> str:
        status = self.report_status()
        overall = self.report()
        memory_rows = self.context_memory_rows(snapshot.regime_label)
        signals_total = len(snapshot.results_a) + len(snapshot.results_c5)

        lines = [
            "=" * 110,
            f"  RESUMEN DIARIO V11 | {snapshot.analyzed_date}",
            "=" * 110,
            f"  Prediccion para      : {v11.next_business_day(snapshot.analyzed_date)}",
            f"  Regimen actual       : {snapshot.regime_label}",
            f"  Breadth actual       : {snapshot.breadth_pct:.1f}%",
            f"  Oportunidades hoy    : {signals_total} ({len(snapshot.results_a)} A + {len(snapshot.results_c5)} C5)",
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
            lines.append("  - Sin muestra suficiente para el regimen actual.")

        lines.append("-" * 110)
        lines.append("  METRICAS POR HORIZONTE")
        if overall.empty:
            lines.append("  Sin datos suficientes.")
        else:
            lines.append(overall.to_string(index=False))

        return "\n".join(lines)

    def write_daily_summary(self, snapshot: v11.Snapshot) -> Path:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        text = self.daily_summary_text(snapshot).strip() + "\n"
        path = REPORTS_DIR / f"{snapshot.analyzed_date}_resumen.txt"
        path.write_text(text, encoding="utf-8")
        return path


def print_run_summary(snapshot: v11.Snapshot, recorded: dict[str, int], evaluated: dict[str, Any]) -> None:
    print("=" * 90)
    print(f"  APRENDIZAJE OPERATIVO V11 | {snapshot.analyzed_date}")
    print("=" * 90)
    print(f"  Regimen          : {snapshot.regime_label}")
    print(f"  Breadth          : {snapshot.breadth_pct:.1f}%")
    print(f"  Senales A        : {len(snapshot.results_a)}")
    print(f"  Senales C5       : {len(snapshot.results_c5)}")
    print(f"  Bloqueadas       : {len(snapshot.blocked_extreme)}")
    print(f"  Predicciones nuevas guardadas : {recorded['saved_predictions']}")
    print(
        f"  Evaluacion pendiente resuelta : {evaluated['evaluated']} "
        f"(hits {evaluated['hits']} | misses {evaluated['misses']} | errores {evaluated['errors']})"
    )
    print("=" * 90)


def print_report(df: pd.DataFrame, status: dict[str, Any]) -> None:
    print("=" * 110)
    print("  MEMORIA OPERATIVA V11")
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
    parser = argparse.ArgumentParser(description="Bucle de aprendizaje operativo para INVERTIR V11")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Registrar un dia y evaluar lo que ya vencio")
    run_parser.add_argument("--date", help="Fecha analizada (YYYY-MM-DD). Si no se pasa, usa la ultima de la DB.")

    backfill_parser = sub.add_parser("backfill", help="Backfill historico del loop operativo")
    backfill_parser.add_argument("--from-date", required=True, help="Fecha inicial (YYYY-MM-DD)")
    backfill_parser.add_argument("--to-date", help="Fecha final (YYYY-MM-DD). Default: ultima de la DB")

    sub.add_parser("report", help="Resumen de memoria y metricas acumuladas V11")
    summary_parser = sub.add_parser("daily-summary", help="Resumen final diario del loop operativo")
    summary_parser.add_argument("--date", help="Fecha base (YYYY-MM-DD). Si no se pasa, usa la ultima de la DB.")
    recompute_parser = sub.add_parser(
        "recompute-outcomes",
        help="Recalcular outcomes V11 con retorno operable (open siguiente -> close target)",
    )
    recompute_parser.add_argument("--to-date", help="Fecha final (YYYY-MM-DD). Default: ultima de la DB.")
    return parser.parse_args()


def run_single(db: TitanDB, requested_date: str | None) -> None:
    engine = OperationalLearningV11(db)
    snapshot, regime_info = engine.build_snapshot(requested_date)
    recorded = engine.record_snapshot(snapshot, regime_info)
    evaluated = engine.evaluate_due_predictions()
    engine.refresh_model_metrics()
    print_run_summary(snapshot, recorded, evaluated)


def run_backfill(db: TitanDB, from_date: str, to_date: str | None) -> None:
    engine = OperationalLearningV11(db)
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
    print(f"  BACKFILL V11 | {dates[0]} -> {dates[-1]}")
    print("=" * 90)
    print(f"  Dias procesados      : {total_days}")
    print(f"  Predicciones guardadas: {total_saved}")
    print(
        f"  Evaluadas            : {evaluated['evaluated']} "
        f"(hits {evaluated['hits']} | misses {evaluated['misses']} | errores {evaluated['errors']})"
    )
    print("=" * 90)


def run_report(db: TitanDB) -> None:
    engine = OperationalLearningV11(db)
    engine.refresh_model_metrics()
    print_report(engine.report(), engine.report_status())


def run_daily_summary(db: TitanDB, requested_date: str | None) -> None:
    engine = OperationalLearningV11(db)
    engine.refresh_model_metrics()
    snapshot, _ = engine.build_snapshot(requested_date)
    path = engine.write_daily_summary(snapshot)
    print(engine.daily_summary_text(snapshot))
    print("-" * 110)
    print(f"  Resumen guardado en: {path}")


def run_recompute_outcomes(db: TitanDB, to_date: str | None) -> None:
    engine = OperationalLearningV11(db)
    evaluated = engine.evaluate_due_predictions(
        max_target_date=to_date or engine.latest_db_date,
        recompute_existing=True,
    )
    engine.refresh_model_metrics()
    print("=" * 90)
    print("  RECOMPUTE OUTCOMES V11")
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
