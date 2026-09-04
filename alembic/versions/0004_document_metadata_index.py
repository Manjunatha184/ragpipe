"""Add a GIN index for document metadata filtering.

Revision ID: 0004_document_metadata_index
Revises: 0003_document_metadata
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_document_metadata_index"
down_revision: str | None = "0003_document_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX documents_metadata_gin_idx
        ON documents
        USING gin (metadata jsonb_path_ops)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS documents_metadata_gin_idx
        """
    )
