from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg_pool import ConnectionPool

from ragpipe.models import Chunk, DocumentState, StoreStatus, SyncResult
from ragpipe.store.base import Store

EXPECTED_SCHEMA_REVISION = "0001_initial_schema"


class SchemaNotReadyError(RuntimeError):
    """Raised when required database migrations have not been applied."""


class PgVectorStore(Store):
    def __init__(self, database_url: str) -> None:
        self._pool = ConnectionPool(database_url, min_size=1, max_size=5, open=True)
        self._conn: Connection[Any] | None = None

    def initialize(self, dimension: int) -> None:
        """Verify that Alembic created a compatible database schema."""

        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    to_regclass('public.alembic_version'),
                    to_regclass('public.documents'),
                    to_regclass('public.chunks'),
                    to_regclass('public.sync_runs')
                """
            )
            tables = cur.fetchone()

            if tables is None or any(table is None for table in tables):
                raise SchemaNotReadyError(
                    "Database schema is not initialized. "
                    "Run `alembic upgrade head` before starting ragpipe."
                )

            cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
            revision_row = cur.fetchone()

            if revision_row is None:
                raise SchemaNotReadyError(
                    "Database schema has no Alembic revision. Run `alembic upgrade head`."
                )

            actual_revision = str(revision_row[0])

            if actual_revision != EXPECTED_SCHEMA_REVISION:
                raise SchemaNotReadyError(
                    f"Database schema revision {actual_revision!r} does not match "
                    f"required revision {EXPECTED_SCHEMA_REVISION!r}. "
                    "Run `alembic upgrade head`."
                )

            cur.execute(
                """
                SELECT format_type(
                    attribute.atttypid,
                    attribute.atttypmod
                )
                FROM pg_attribute AS attribute
                JOIN pg_class AS relation
                  ON relation.oid = attribute.attrelid
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relname = 'chunks'
                  AND attribute.attname = 'embedding'
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                """
            )
            vector_row = cur.fetchone()

            expected_vector_type = f"vector({dimension})"

            if vector_row is None or str(vector_row[0]) != expected_vector_type:
                actual_vector_type = None if vector_row is None else str(vector_row[0])
                raise SchemaNotReadyError(
                    f"Database embedding type is {actual_vector_type!r}; "
                    f"expected {expected_vector_type!r}."
                )

            register_vector(conn)

    def _active(self) -> Connection[Any]:
        if self._conn is None:
            raise RuntimeError("Database operation must run inside transaction()")
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[Store]:
        if self._conn is not None:
            raise RuntimeError("Nested transactions are not supported")
        with self._pool.connection() as conn:
            self._conn = conn
            register_vector(conn)
            try:
                with conn.transaction():
                    yield self
            finally:
                self._conn = None

    def document_states(self) -> dict[str, DocumentState]:
        with self._active().cursor() as cur:
            cur.execute("SELECT id::text, path, content_hash FROM documents")
            return {row[1]: DocumentState(*row) for row in cur.fetchall()}

    def delete_document(self, document_id: str) -> int:
        conn = self._active()
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM chunks WHERE document_id = %s", (document_id,))
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("Could not count chunks for document")
            count = int(row[0])
            cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
            return count

    def replace_document(
        self,
        path: str,
        content_hash: str,
        media_type: str,
        size_bytes: int,
        chunks: Sequence[Chunk],
        embeddings: Sequence[Sequence[float]],
        model_name: str,
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("Each chunk must have exactly one embedding")
        conn = self._active()
        document_id = uuid.uuid4()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE path = %s", (path,))
            cur.execute(
                """INSERT INTO documents(id,path,content_hash,media_type,size_bytes)
                   VALUES(%s,%s,%s,%s,%s)""",
                (document_id, path, content_hash, media_type, size_bytes),
            )
            cur.executemany(
                """INSERT INTO chunks(id,document_id,chunk_index,content,content_hash,metadata,
                   embedding_model,embedding) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                [
                    (
                        uuid.uuid4(),
                        document_id,
                        c.index,
                        c.text,
                        c.content_hash,
                        json.dumps(c.metadata),
                        model_name,
                        list(e),
                    )
                    for c, e in zip(chunks, embeddings, strict=True)
                ],
            )
        return len(chunks)

    def record_run(self, result: SyncResult, source: str, error: str | None = None) -> None:
        with self._active().cursor() as cur:
            cur.execute(
                """INSERT INTO sync_runs VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    result.run_id,
                    source,
                    result.status,
                    result.new_documents,
                    result.changed_documents,
                    result.deleted_documents,
                    result.unchanged_documents,
                    result.embedded_chunks,
                    result.deleted_chunks,
                    result.started_at,
                    result.finished_at,
                    error,
                ),
            )

    def status(self) -> StoreStatus:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT (SELECT count(*) FROM documents), (SELECT count(*) FROM chunks)")
            counts = cur.fetchone()
            if counts is None:
                raise RuntimeError("Could not read store status")
            documents, chunks = counts
            cur.execute(
                "SELECT finished_at, status FROM sync_runs ORDER BY finished_at DESC LIMIT 1"
            )
            last = cur.fetchone()
            return StoreStatus(
                int(documents), int(chunks), last[0] if last else None, last[1] if last else None
            )

    def close(self) -> None:
        self._pool.close()
