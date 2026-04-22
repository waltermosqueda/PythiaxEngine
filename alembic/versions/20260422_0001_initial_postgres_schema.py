"""Initial Postgres schema for Claude Titan."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260422_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prices",
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("adj_close", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("ticker", "date", name=op.f("pk_prices")),
    )
    op.create_index("idx_prices_ticker", "prices", ["ticker"], unique=False)
    op.create_index("idx_prices_date", "prices", ["date"], unique=False)

    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("prediction_date", sa.Date(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("regime", sa.String(length=32), nullable=True),
        sa.Column("sector", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("direction IN ('UP', 'DOWN')", name=op.f("ck_predictions_direction_valid")),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_predictions_confidence_between_0_and_1"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_predictions")),
        sa.UniqueConstraint(
            "model_name",
            "ticker",
            "prediction_date",
            "target_date",
            name="uq_predictions_model_ticker_prediction_target",
        ),
    )
    op.create_index("idx_pred_model", "predictions", ["model_name"], unique=False)
    op.create_index("idx_pred_date", "predictions", ["prediction_date"], unique=False)
    op.create_index("idx_pred_target", "predictions", ["target_date"], unique=False)

    op.create_table(
        "outcomes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prediction_id", sa.Integer(), nullable=False),
        sa.Column("actual_direction", sa.String(length=8), nullable=False),
        sa.Column("actual_return", sa.Float(), nullable=False),
        sa.Column("hit", sa.Integer(), nullable=False),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actual_direction IN ('UP', 'DOWN')",
            name=op.f("ck_outcomes_actual_direction_valid"),
        ),
        sa.CheckConstraint("hit IN (0, 1)", name=op.f("ck_outcomes_hit_binary")),
        sa.ForeignKeyConstraint(
            ["prediction_id"],
            ["predictions.id"],
            name=op.f("fk_outcomes_prediction_id_predictions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outcomes")),
        sa.UniqueConstraint("prediction_id", name="uq_outcomes_prediction_id"),
    )

    op.create_table(
        "model_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("total_predictions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("correct_predictions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("accuracy", sa.Float(), server_default="0", nullable=True),
        sa.Column("avg_confidence", sa.Float(), nullable=True),
        sa.Column("avg_return_when_right", sa.Float(), nullable=True),
        sa.Column("avg_return_when_wrong", sa.Float(), nullable=True),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("sharpe_ratio", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_metrics")),
        sa.UniqueConstraint(
            "model_name",
            "period_start",
            "period_end",
            name="uq_model_metrics_model_period",
        ),
    )

    op.create_table(
        "regimes",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("trend_regime", sa.String(length=32), nullable=True),
        sa.Column("vol_regime", sa.String(length=32), nullable=True),
        sa.Column("credit_regime", sa.String(length=32), nullable=True),
        sa.Column("composite", sa.String(length=32), nullable=True),
        sa.Column("vix_level", sa.Float(), nullable=True),
        sa.Column("spy_return_20d", sa.Float(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("date", name=op.f("pk_regimes")),
    )

    op.create_table(
        "data_status",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_data_status")),
    )

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("pipeline_name", sa.String(length=64), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("run_source", sa.String(length=32), nullable=True),
        sa.Column("commit_sha", sa.String(length=40), nullable=True),
        sa.Column("active_scanner_version", sa.String(length=16), nullable=True),
        sa.Column("db_backend", sa.String(length=16), nullable=True),
        sa.Column("expected_market_date", sa.Date(), nullable=True),
        sa.Column("latest_prices_date", sa.Date(), nullable=True),
        sa.Column("rows_inserted", sa.Integer(), nullable=True),
        sa.Column("warnings_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("artifact_manifest", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_runs")),
        sa.UniqueConstraint("run_id", name="uq_pipeline_runs_run_id"),
    )
    op.create_index("idx_pipeline_runs_run_date", "pipeline_runs", ["run_date"], unique=False)
    op.create_index("idx_pipeline_runs_status", "pipeline_runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_pipeline_runs_status", table_name="pipeline_runs")
    op.drop_index("idx_pipeline_runs_run_date", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
    op.drop_table("data_status")
    op.drop_table("regimes")
    op.drop_table("model_metrics")
    op.drop_table("outcomes")
    op.drop_index("idx_pred_target", table_name="predictions")
    op.drop_index("idx_pred_date", table_name="predictions")
    op.drop_index("idx_pred_model", table_name="predictions")
    op.drop_table("predictions")
    op.drop_index("idx_prices_date", table_name="prices")
    op.drop_index("idx_prices_ticker", table_name="prices")
    op.drop_table("prices")

