from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from infra.db.base import Base


class Price(Base):
    __tablename__ = "prices"
    __table_args__ = (
        Index("idx_prices_ticker", "ticker"),
        Index("idx_prices_date", "date"),
    )

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int | None] = mapped_column(Integer)
    adj_close: Mapped[float | None] = mapped_column(Float)


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint(
            "model_name",
            "ticker",
            "prediction_date",
            "target_date",
            name="uq_predictions_model_ticker_prediction_target",
        ),
        CheckConstraint("direction IN ('UP', 'DOWN')", name="direction_valid"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_between_0_and_1",
        ),
        Index("idx_pred_model", "model_name"),
        Index("idx_pred_date", "prediction_date"),
        Index("idx_pred_target", "target_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64))
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    prediction_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float | None] = mapped_column(Float)
    regime: Mapped[str | None] = mapped_column(String(32))
    sector: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Outcome(Base):
    __tablename__ = "outcomes"
    __table_args__ = (
        UniqueConstraint("prediction_id", name="uq_outcomes_prediction_id"),
        CheckConstraint("actual_direction IN ('UP', 'DOWN')", name="actual_direction_valid"),
        CheckConstraint("hit IN (0, 1)", name="hit_binary"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int] = mapped_column(
        ForeignKey("predictions.id", ondelete="CASCADE"),
        nullable=False,
    )
    actual_direction: Mapped[str] = mapped_column(String(8), nullable=False)
    actual_return: Mapped[float] = mapped_column(Float, nullable=False)
    hit: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ModelMetric(Base):
    __tablename__ = "model_metrics"
    __table_args__ = (
        UniqueConstraint(
            "model_name",
            "period_start",
            "period_end",
            name="uq_model_metrics_model_period",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    total_predictions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    correct_predictions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    accuracy: Mapped[float | None] = mapped_column(Float, server_default="0")
    avg_confidence: Mapped[float | None] = mapped_column(Float)
    avg_return_when_right: Mapped[float | None] = mapped_column(Float)
    avg_return_when_wrong: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Regime(Base):
    __tablename__ = "regimes"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    trend_regime: Mapped[str | None] = mapped_column(String(32))
    vol_regime: Mapped[str | None] = mapped_column(String(32))
    credit_regime: Mapped[str | None] = mapped_column(String(32))
    composite: Mapped[str | None] = mapped_column(String(32))
    vix_level: Mapped[float | None] = mapped_column(Float)
    spy_return_20d: Mapped[float | None] = mapped_column(Float)
    details: Mapped[str | None] = mapped_column(Text)


class DataStatus(Base):
    __tablename__ = "data_status"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_pipeline_runs_run_id"),
        Index("idx_pipeline_runs_run_date", "run_date"),
        Index("idx_pipeline_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_name: Mapped[str] = mapped_column(String(64), nullable=False)
    run_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    run_source: Mapped[str | None] = mapped_column(String(32))
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    active_scanner_version: Mapped[str | None] = mapped_column(String(16))
    db_backend: Mapped[str | None] = mapped_column(String(16))
    expected_market_date: Mapped[date | None] = mapped_column(Date)
    latest_prices_date: Mapped[date | None] = mapped_column(Date)
    rows_inserted: Mapped[int | None] = mapped_column(Integer)
    warnings_count: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    artifact_manifest: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ModelRunSnapshot(Base):
    __tablename__ = "model_run_snapshots"
    __table_args__ = (
        UniqueConstraint("model_key", "analyzed_date", name="uq_model_run_snapshots_model_key_date"),
        Index("idx_model_run_snapshots_model_key", "model_key"),
        Index("idx_model_run_snapshots_analyzed_date", "analyzed_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_key: Mapped[str] = mapped_column(String(128), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str | None] = mapped_column(String(32))
    analyzed_date: Mapped[date] = mapped_column(Date, nullable=False)
    prediction_for: Mapped[date | None] = mapped_column(Date)
    freshness: Mapped[str | None] = mapped_column(String(32))
    regime_label: Mapped[str | None] = mapped_column(String(32))
    breadth_pct: Mapped[float | None] = mapped_column(Float)
    signal_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
