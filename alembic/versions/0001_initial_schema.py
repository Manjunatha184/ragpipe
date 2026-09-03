"""Create the initial ragpipe database schema.

Revision ID: 0001_initial_schema
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create pgvector extension and all ragpipe tables."""

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "path",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.CHAR(length=64),
            nullable=False,
        ),
        sa.Column(
            "media_type",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "size_bytes",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name="documents_size_bytes_check",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="documents_pkey",
        ),
        sa.UniqueConstraint(
            "path",
            name="documents_path_key",
        ),
    )

    op.create_index(
        "documents_hash_idx",
        "documents",
        ["content_hash"],
        unique=False,
    )

    op.create_table(
        "sync_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "new_documents",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "changed_documents",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "deleted_documents",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "unchanged_documents",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "embedded_chunks",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "deleted_chunks",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "error",
            sa.Text(),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="sync_runs_status_check",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="sync_runs_pkey",
        ),
    )

    op.create_table(
        "chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "chunk_index",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.CHAR(length=64),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "embedding_model",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "embedding",
            Vector(dim=384),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="chunks_document_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="chunks_pkey",
        ),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="chunks_document_id_chunk_index_key",
        ),
    )

    op.create_index(
        "chunks_document_id_idx",
        "chunks",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove ragpipe tables in dependency-safe order."""

    op.drop_table("chunks")
    op.drop_table("sync_runs")
    op.drop_table("documents")

    # Do not drop the vector extension because other applications in the
    # same PostgreSQL database may depend on it.
