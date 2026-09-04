"""Add document metadata and metadata-change statistics.

Revision ID: 0003_document_metadata
Revises: 0002_vector_search_index
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from ragpipe.models import EMPTY_METADATA_HASH

revision: str = "0003_document_metadata"
down_revision: str | Sequence[str] | None = "0002_vector_search_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add document metadata without rebuilding stored embeddings."""

    op.add_column(
        "documents",
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    op.add_column(
        "documents",
        sa.Column(
            "metadata_hash",
            sa.CHAR(length=64),
            server_default=sa.text(f"'{EMPTY_METADATA_HASH}'"),
            nullable=False,
        ),
    )

    op.add_column(
        "sync_runs",
        sa.Column(
            "metadata_changed_documents",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Remove document metadata fields."""

    op.drop_column(
        "sync_runs",
        "metadata_changed_documents",
    )
    op.drop_column(
        "documents",
        "metadata_hash",
    )
    op.drop_column(
        "documents",
        "metadata",
    )
