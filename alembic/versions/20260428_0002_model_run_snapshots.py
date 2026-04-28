"""Add daily model run snapshots table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_0002"
down_revision = "20260422_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_run_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_key", sa.String(length=128), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("analyzed_date", sa.Date(), nullable=False),
        sa.Column("prediction_for", sa.Date(), nullable=True),
        sa.Column("freshness", sa.String(length=32), nullable=True),
        sa.Column("regime_label", sa.String(length=32), nullable=True),
        sa.Column("breadth_pct", sa.Float(), nullable=True),
        sa.Column("signal_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_run_snapshots")),
        sa.UniqueConstraint("model_key", "analyzed_date", name="uq_model_run_snapshots_model_key_date"),
    )
    op.create_index(
        "idx_model_run_snapshots_model_key",
        "model_run_snapshots",
        ["model_key"],
        unique=False,
    )
    op.create_index(
        "idx_model_run_snapshots_analyzed_date",
        "model_run_snapshots",
        ["analyzed_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_model_run_snapshots_analyzed_date", table_name="model_run_snapshots")
    op.drop_index("idx_model_run_snapshots_model_key", table_name="model_run_snapshots")
    op.drop_table("model_run_snapshots")
