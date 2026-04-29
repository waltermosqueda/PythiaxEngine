from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import analisis.generar_tablero_maquina_pensante as dashboard
import herramientas.competencia_topn_estandar as competition_topn
import herramientas.refrescar_datos_dashboard as refresher
import infra.cloud.audit_dashboard_integrity as integrity_audit
from herramientas.dashboard_paths import C1_PRO_BUNDLE_HTML, C1_PRO_TEMPLATE_HTML, EXECUTIVE_HTML, INDEX_HTML, LAB_HTML, MANIFEST_PATH, SNAPSHOT_PATH
from herramientas.scanner_operativo_context import OperationalScannerContext
from infra.db.migrate_sqlite_to_postgres import sqlite_path_to_url
from infra.publish.dashboard_site import stage_dashboard_site
from titan_system.core.database import TitanDB


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-cloud-dashboard-integrity" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def business_days(start: date, count: int) -> list[str]:
    out: list[str] = []
    cursor = start
    while len(out) < count:
        if cursor.weekday() < 5:
            out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


def seed_dashboard_db(db_path: Path, market_dates: list[str]) -> None:
    prediction_pairs = list(zip(market_dates[-5:-2], market_dates[-4:-1], strict=False))
    with TitanDB(db_path=str(db_path)) as db:
        con = db.conn
        for idx, market_date in enumerate(market_dates, start=1):
            con.execute(
                """
                INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("SPY", market_date, 500.0 + idx, 502.0 + idx, 498.0 + idx, 501.0 + idx, 1000000 + idx, 501.0 + idx),
            )
            con.execute(
                """
                INSERT INTO regimes (date, trend_regime, vol_regime, credit_regime, composite, vix_level, spy_return_20d, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (market_date, "BULL", "LOW", "OK", "SEGURO", 18.0, 0.03, "{}"),
            )

        prediction_id = 1
        for offset, (prediction_date, target_date) in enumerate(prediction_pairs, start=1):
            rows = [
                ("INVERTIR_V13_D_D10", "AAPL", 0.91 - offset * 0.01, 2.5 - offset * 0.1, "Tech"),
                ("INVERTIR_V13_D_D10", "MSFT", 0.87 - offset * 0.01, 2.2 - offset * 0.1, "Tech"),
                ("INVERTIR_V13_E_D15", "NVDA", 0.78 - offset * 0.01, 1.9 - offset * 0.1, "Tech"),
                ("INVERTIR_V12_D_D10", "GOOG", 0.72 - offset * 0.01, 1.7 - offset * 0.1, "Tech"),
            ]
            for model_name, ticker, confidence, score, sector in rows:
                con.execute(
                    """
                    INSERT INTO predictions
                        (id, model_name, model_version, ticker, prediction_date, target_date, direction, confidence, score, regime, sector)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prediction_id,
                        model_name,
                        model_name.split("_")[1].lower(),
                        ticker,
                        prediction_date,
                        target_date,
                        "UP",
                        confidence,
                        score,
                        "SEGURO",
                        sector,
                    ),
                )
                con.execute(
                    """
                    INSERT INTO outcomes
                        (id, prediction_id, actual_direction, actual_return, hit)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        prediction_id,
                        prediction_id,
                        "UP" if prediction_id % 2 else "DOWN",
                        0.02 if prediction_id % 2 else -0.01,
                        1 if prediction_id % 2 else 0,
                    ),
                )
                prediction_id += 1

        con.execute(
            """
            INSERT INTO data_status (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            ("latest_prices_date", market_dates[-1], f"{market_dates[-1]} 20:00:00"),
        )
        con.execute(
            """
            INSERT INTO data_status (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            ("market_data_updated_at", f"{market_dates[-1]} 20:00:00", f"{market_dates[-1]} 20:00:00"),
        )
        con.commit()


def seed_model_run_snapshots(db_path: Path, monitored: list[dict[str, str]], analyzed_date: str) -> None:
    with TitanDB(db_path=str(db_path)) as db:
        for entry in monitored:
            payload = {
                "analyzed_date": analyzed_date,
                "prediction_for": analyzed_date,
                "freshness": "AL DIA",
                "regime_label": "SEGURO",
                "breadth_pct": 0.0,
                "results_d": [],
                "results_e": [],
            }
            db.save_model_run_snapshot(
                model_key=str(entry["label"]),
                model_name=str(entry["prefix"]),
                model_version=str(entry["label"]).lower(),
                role=str(entry["role"]),
                analyzed_date=analyzed_date,
                prediction_for=analyzed_date,
                freshness="AL DIA",
                regime_label="SEGURO",
                breadth_pct=0.0,
                signal_count=0,
                snapshot_payload=payload,
            )


def write_human_dashboard_artifacts(payload: dict[str, object], dashboard_dir: Path, template_path: Path) -> None:
    template_html = C1_PRO_TEMPLATE_HTML.read_text(encoding="utf-8")
    rendered_html = refresher.render_dashboard_html(template_html, payload, verbose=False)
    template_path.write_text(rendered_html, encoding="utf-8")
    published_html = dashboard.rewrite_dashboard_variant_hrefs(rendered_html, dashboard_dir / C1_PRO_BUNDLE_HTML.name)
    (dashboard_dir / C1_PRO_BUNDLE_HTML.name).write_text(published_html, encoding="utf-8")


def test_audit_dashboard_integrity_passes_for_db_snapshot_and_site(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "dashboard.db"
    dashboard_dir = tmp_dir / "dashboard"
    site_dir = tmp_dir / "site"
    template_path = tmp_dir / C1_PRO_TEMPLATE_HTML.name
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    try:
        market_dates = business_days(date(2026, 3, 2), 35)
        seed_dashboard_db(db_path, market_dates)
        database_url = sqlite_path_to_url(db_path)

        context = OperationalScannerContext(
            active_entry_id="v13",
            active_version=13,
            active_scanner=Path("SCANNER/invertir_v13.py"),
            reference_version=12,
            reference_scanner=Path("SCANNER/invertir_v12.py"),
            base_learning=Path("herramientas/aprendizaje_operativo_v11.py"),
            reference_learning=Path("herramientas/aprendizaje_operativo_v12.py"),
            active_learning=Path("herramientas/aprendizaje_operativo_v13.py"),
            learning_chain=(
                Path("herramientas/aprendizaje_operativo_v11.py"),
                Path("herramientas/aprendizaje_operativo_v12.py"),
                Path("herramientas/aprendizaje_operativo_v13.py"),
            ),
            observed_versions=(),
            observed_scanners=(),
            observed_learning_chain=(),
        )
        monitored = [
            {"key": "V13", "label": "V13", "role": "activo", "prefix": "INVERTIR_V13"},
            {"key": "V12", "label": "V12", "role": "referencia", "prefix": "INVERTIR_V12"},
        ]
        seed_model_run_snapshots(db_path, monitored, market_dates[-1])
        monkeypatch.setattr(dashboard, "resolve_operational_scanner_context", lambda: context)
        monkeypatch.setattr(competition_topn, "monitored_entries", lambda: monitored)
        monkeypatch.setattr(integrity_audit, "resolve_operational_scanner_context", lambda: context)
        monkeypatch.setattr(integrity_audit, "C1_PRO_TEMPLATE_HTML", template_path)

        payload = dashboard.build_dashboard_payload(database_url=database_url)
        snapshot_path = dashboard_dir / SNAPSHOT_PATH.name
        snapshot_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        (dashboard_dir / INDEX_HTML.name).write_text(dashboard.render_index(payload), encoding="utf-8")
        (dashboard_dir / EXECUTIVE_HTML.name).write_text(dashboard.render_executive(payload), encoding="utf-8")
        (dashboard_dir / LAB_HTML.name).write_text(dashboard.render_lab(payload), encoding="utf-8")
        write_human_dashboard_artifacts(payload, dashboard_dir, template_path)
        (dashboard_dir / MANIFEST_PATH.name).write_text(
            json.dumps(
                {
                    "generated_at": payload["generated_at"],
                    "artifact_count": 5,
                    "build": payload["build"],
                    "artifacts": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        stage_dashboard_site(dashboard_dir, site_dir)

        report_path = tmp_dir / "dashboard_integrity_audit.json"
        report = integrity_audit.audit_dashboard_integrity(
            database_url=database_url,
            snapshot_path=snapshot_path,
            dashboard_dir=dashboard_dir,
            site_dir=site_dir,
            sample_size=2,
            seed=7,
            report_path=report_path,
        )

        assert report["checks_failed"] == 0
        assert sorted(report["sampled_versions"]) == ["V12", "V13"]
        assert report_path.exists()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_audit_dashboard_integrity_flags_stale_live_target_dates(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "dashboard.db"
    dashboard_dir = tmp_dir / "dashboard"
    site_dir = tmp_dir / "site"
    template_path = tmp_dir / C1_PRO_TEMPLATE_HTML.name
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    try:
        market_dates = business_days(date(2026, 3, 2), 35)
        seed_dashboard_db(db_path, market_dates)
        database_url = sqlite_path_to_url(db_path)

        context = OperationalScannerContext(
            active_entry_id="v13",
            active_version=13,
            active_scanner=Path("SCANNER/invertir_v13.py"),
            reference_version=12,
            reference_scanner=Path("SCANNER/invertir_v12.py"),
            base_learning=Path("herramientas/aprendizaje_operativo_v11.py"),
            reference_learning=Path("herramientas/aprendizaje_operativo_v12.py"),
            active_learning=Path("herramientas/aprendizaje_operativo_v13.py"),
            learning_chain=(
                Path("herramientas/aprendizaje_operativo_v11.py"),
                Path("herramientas/aprendizaje_operativo_v12.py"),
                Path("herramientas/aprendizaje_operativo_v13.py"),
            ),
            observed_versions=(),
            observed_scanners=(),
            observed_learning_chain=(),
        )
        monitored = [
            {"key": "V13", "label": "V13", "role": "activo", "prefix": "INVERTIR_V13"},
            {"key": "V12", "label": "V12", "role": "referencia", "prefix": "INVERTIR_V12"},
        ]
        seed_model_run_snapshots(db_path, monitored, market_dates[-1])
        monkeypatch.setattr(dashboard, "resolve_operational_scanner_context", lambda: context)
        monkeypatch.setattr(competition_topn, "monitored_entries", lambda: monitored)
        monkeypatch.setattr(integrity_audit, "resolve_operational_scanner_context", lambda: context)
        monkeypatch.setattr(integrity_audit, "C1_PRO_TEMPLATE_HTML", template_path)

        payload = dashboard.build_dashboard_payload(database_url=database_url)
        active_run = (payload.get("active") or {}).get("active_run") or {}
        active_run["results_e"] = [
            {
                "ticker": "NVDA",
                "signal": "UP",
                "sector": "Tech",
                "confidence": 0.88,
                "score": 81.0,
                "target_date": "2026-03-20",
            }
        ]
        snapshot_path = dashboard_dir / SNAPSHOT_PATH.name
        snapshot_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        (dashboard_dir / INDEX_HTML.name).write_text(dashboard.render_index(payload), encoding="utf-8")
        (dashboard_dir / EXECUTIVE_HTML.name).write_text(dashboard.render_executive(payload), encoding="utf-8")
        (dashboard_dir / LAB_HTML.name).write_text(dashboard.render_lab(payload), encoding="utf-8")
        write_human_dashboard_artifacts(payload, dashboard_dir, template_path)
        (dashboard_dir / MANIFEST_PATH.name).write_text(
            json.dumps(
                {
                    "generated_at": payload["generated_at"],
                    "artifact_count": 5,
                    "build": payload["build"],
                    "artifacts": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        stage_dashboard_site(dashboard_dir, site_dir)

        report = integrity_audit.audit_dashboard_integrity(
            database_url=database_url,
            snapshot_path=snapshot_path,
            dashboard_dir=dashboard_dir,
            site_dir=site_dir,
            sample_size=2,
            seed=7,
            report_path=tmp_dir / "dashboard_integrity_audit.json",
        )

        assert report["checks_failed"] >= 1
        assert any(
            failure["label"] == "active.active_run.target_dates_not_before_analyzed_date"
            for failure in report["failures"]
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_audit_dashboard_integrity_flags_site_entrypoint_drift(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "dashboard.db"
    dashboard_dir = tmp_dir / "dashboard"
    site_dir = tmp_dir / "site"
    template_path = tmp_dir / C1_PRO_TEMPLATE_HTML.name
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    try:
        market_dates = business_days(date(2026, 3, 2), 35)
        seed_dashboard_db(db_path, market_dates)
        database_url = sqlite_path_to_url(db_path)

        context = OperationalScannerContext(
            active_entry_id="v13",
            active_version=13,
            active_scanner=Path("SCANNER/invertir_v13.py"),
            reference_version=12,
            reference_scanner=Path("SCANNER/invertir_v12.py"),
            base_learning=Path("herramientas/aprendizaje_operativo_v11.py"),
            reference_learning=Path("herramientas/aprendizaje_operativo_v12.py"),
            active_learning=Path("herramientas/aprendizaje_operativo_v13.py"),
            learning_chain=(
                Path("herramientas/aprendizaje_operativo_v11.py"),
                Path("herramientas/aprendizaje_operativo_v12.py"),
                Path("herramientas/aprendizaje_operativo_v13.py"),
            ),
            observed_versions=(),
            observed_scanners=(),
            observed_learning_chain=(),
        )
        monitored = [
            {"key": "V13", "label": "V13", "role": "activo", "prefix": "INVERTIR_V13"},
            {"key": "V12", "label": "V12", "role": "referencia", "prefix": "INVERTIR_V12"},
        ]
        seed_model_run_snapshots(db_path, monitored, market_dates[-1])
        monkeypatch.setattr(dashboard, "resolve_operational_scanner_context", lambda: context)
        monkeypatch.setattr(competition_topn, "monitored_entries", lambda: monitored)
        monkeypatch.setattr(integrity_audit, "resolve_operational_scanner_context", lambda: context)
        monkeypatch.setattr(integrity_audit, "C1_PRO_TEMPLATE_HTML", template_path)

        payload = dashboard.build_dashboard_payload(database_url=database_url)
        snapshot_path = dashboard_dir / SNAPSHOT_PATH.name
        snapshot_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        (dashboard_dir / INDEX_HTML.name).write_text(dashboard.render_index(payload), encoding="utf-8")
        (dashboard_dir / EXECUTIVE_HTML.name).write_text(dashboard.render_executive(payload), encoding="utf-8")
        (dashboard_dir / LAB_HTML.name).write_text(dashboard.render_lab(payload), encoding="utf-8")
        write_human_dashboard_artifacts(payload, dashboard_dir, template_path)
        (dashboard_dir / MANIFEST_PATH.name).write_text(
            json.dumps(
                {
                    "generated_at": payload["generated_at"],
                    "artifact_count": 5,
                    "build": payload["build"],
                    "artifacts": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        stage_dashboard_site(dashboard_dir, site_dir)
        (site_dir / "index.html").write_text("<html><body>stale site</body></html>\n", encoding="utf-8")

        report = integrity_audit.audit_dashboard_integrity(
            database_url=database_url,
            snapshot_path=snapshot_path,
            dashboard_dir=dashboard_dir,
            site_dir=site_dir,
            sample_size=2,
            seed=7,
            report_path=tmp_dir / "dashboard_integrity_audit.json",
        )

        assert report["checks_failed"] >= 1
        assert any(
            failure["label"] == "site_file[index.html]"
            for failure in report["failures"]
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_audit_dashboard_integrity_flags_stale_competition_snapshots(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "dashboard.db"
    dashboard_dir = tmp_dir / "dashboard"
    site_dir = tmp_dir / "site"
    template_path = tmp_dir / C1_PRO_TEMPLATE_HTML.name
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    try:
        market_dates = business_days(date(2026, 3, 2), 35)
        seed_dashboard_db(db_path, market_dates)
        database_url = sqlite_path_to_url(db_path)

        context = OperationalScannerContext(
            active_entry_id="v13",
            active_version=13,
            active_scanner=Path("SCANNER/invertir_v13.py"),
            reference_version=12,
            reference_scanner=Path("SCANNER/invertir_v12.py"),
            base_learning=Path("herramientas/aprendizaje_operativo_v11.py"),
            reference_learning=Path("herramientas/aprendizaje_operativo_v12.py"),
            active_learning=Path("herramientas/aprendizaje_operativo_v13.py"),
            learning_chain=(
                Path("herramientas/aprendizaje_operativo_v11.py"),
                Path("herramientas/aprendizaje_operativo_v12.py"),
                Path("herramientas/aprendizaje_operativo_v13.py"),
            ),
            observed_versions=(),
            observed_scanners=(),
            observed_learning_chain=(),
        )
        monitored = [
            {"key": "V13", "label": "V13", "role": "activo", "prefix": "INVERTIR_V13"},
            {"key": "V12", "label": "V12", "role": "referencia", "prefix": "INVERTIR_V12"},
        ]
        seed_model_run_snapshots(db_path, monitored, market_dates[-2])
        monkeypatch.setattr(dashboard, "resolve_operational_scanner_context", lambda: context)
        monkeypatch.setattr(competition_topn, "monitored_entries", lambda: monitored)
        monkeypatch.setattr(integrity_audit, "resolve_operational_scanner_context", lambda: context)
        monkeypatch.setattr(integrity_audit, "C1_PRO_TEMPLATE_HTML", template_path)

        payload = dashboard.build_dashboard_payload(database_url=database_url)
        snapshot_path = dashboard_dir / SNAPSHOT_PATH.name
        snapshot_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        (dashboard_dir / INDEX_HTML.name).write_text(dashboard.render_index(payload), encoding="utf-8")
        (dashboard_dir / EXECUTIVE_HTML.name).write_text(dashboard.render_executive(payload), encoding="utf-8")
        (dashboard_dir / LAB_HTML.name).write_text(dashboard.render_lab(payload), encoding="utf-8")
        write_human_dashboard_artifacts(payload, dashboard_dir, template_path)
        (dashboard_dir / MANIFEST_PATH.name).write_text(
            json.dumps(
                {
                    "generated_at": payload["generated_at"],
                    "artifact_count": 5,
                    "build": payload["build"],
                    "artifacts": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        stage_dashboard_site(dashboard_dir, site_dir)

        report = integrity_audit.audit_dashboard_integrity(
            database_url=database_url,
            snapshot_path=snapshot_path,
            dashboard_dir=dashboard_dir,
            site_dir=site_dir,
            sample_size=2,
            seed=7,
            report_path=tmp_dir / "dashboard_integrity_audit.json",
        )

        assert report["checks_failed"] >= 1
        assert any(
            failure["label"] in {"active.active_run.latest_market_date", "competition[V12].latest_snapshot_date", "competition[V13].latest_snapshot_date"}
            for failure in report["failures"]
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
