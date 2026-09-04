"""Add operational metrics to synchronization runs.

Revision ID: 0005_operational_metrics
Revises: 0004_document_metadata_index
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_operational_metrics"
down_revision: str | None = "0004_document_metadata_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sync_runs",
        sa.Column(
            "scanned_documents",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "sync_runs",
        sa.Column(
            "scanned_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "sync_runs",
        sa.Column(
            "embedding_batches",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "sync_runs",
        sa.Column(
            "embedding_duration_ms",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    op.create_check_constraint(
        "sync_runs_scanned_documents_check",
        "sync_runs",
        "scanned_documents >= 0",
    )
    op.create_check_constraint(
        "sync_runs_scanned_bytes_check",
        "sync_runs",
        "scanned_bytes >= 0",
    )
    op.create_check_constraint(
        "sync_runs_embedding_batches_check",
        "sync_runs",
        "embedding_batches >= 0",
    )
    op.create_check_constraint(
        "sync_runs_embedding_duration_ms_check",
        "sync_runs",
        "embedding_duration_ms >= 0",
    )

    op.execute(
        """
        CREATE INDEX sync_runs_finished_at_idx
        ON sync_runs (finished_at DESC, id DESC)
        """
    )


def downgrade() -> None:
    op.drop_index(
        "sync_runs_finished_at_idx",
        table_name="sync_runs",
    )

    op.drop_constraint(
        "sync_runs_embedding_duration_ms_check",
        "sync_runs",
        type_="check",
    )
    op.drop_constraint(
        "sync_runs_embedding_batches_check",
        "sync_runs",
        type_="check",
    )
    op.drop_constraint(
        "sync_runs_scanned_bytes_check",
        "sync_runs",
        type_="check",
    )
    op.drop_constraint(
        "sync_runs_scanned_documents_check",
        "sync_runs",
        type_="check",
    )

    op.drop_column("sync_runs", "embedding_duration_ms")
    op.drop_column("sync_runs", "embedding_batches")
    op.drop_column("sync_runs", "scanned_bytes")
    op.drop_column("sync_runs", "scanned_documents")
