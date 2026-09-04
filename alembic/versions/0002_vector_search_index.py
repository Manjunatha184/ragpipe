"""Add an HNSW cosine index for vector search.

Revision ID: 0002_vector_search_index
Revises: 0001_initial_schema
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_vector_search_index"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create an approximate nearest-neighbor cosine index."""

    op.execute(
        """
        CREATE INDEX chunks_embedding_hnsw_idx
        ON chunks
        USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    """Remove the vector-search index."""

    op.execute(
        """
        DROP INDEX IF EXISTS chunks_embedding_hnsw_idx
        """
    )
