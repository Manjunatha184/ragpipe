from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg_pool import ConnectionPool

from ragpipe.models import (
    EMPTY_METADATA_HASH,
    Chunk,
    DocumentState,
    SearchResult,
    StoreStatus,
    SyncResult,
    SyncRunRecord,
)
from ragpipe.store.base import Store, SyncLockUnavailableError

EXPECTED_SCHEMA_REVISION = "0005_operational_metrics"
SYNC_LOCK_NAME = "ragpipe:global-sync"


def _serialize_metadata(
    metadata: Mapping[str, Any],
) -> str:
    try:
        return json.dumps(
            dict(metadata),
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Metadata must contain valid JSON values") from error


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

    @contextmanager
    def sync_lock(self) -> Iterator[None]:
        """Allow only one synchronization per database at a time."""

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pg_try_advisory_lock(
                        hashtextextended(%s, 0)
                    )
                    """,
                    (SYNC_LOCK_NAME,),
                )
                row = cur.fetchone()

            conn.commit()
            acquired = row is not None and bool(row[0])

            if not acquired:
                raise SyncLockUnavailableError("Another synchronization is already running.")

            try:
                yield
            finally:
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT pg_advisory_unlock(
                                hashtextextended(%s, 0)
                            )
                            """,
                            (SYNC_LOCK_NAME,),
                        )

                    conn.commit()
                except Exception:
                    # Closing the session guarantees PostgreSQL releases
                    # any remaining session-level advisory lock.
                    conn.close()
                    raise

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
            cur.execute(
                """
                SELECT
                    id::text,
                    path,
                    content_hash,
                    metadata_hash
                FROM documents
                """
            )

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
        document_metadata: Mapping[str, Any] | None = None,
        metadata_hash: str = EMPTY_METADATA_HASH,
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("Each chunk must have exactly one embedding")

        serialized_metadata = _serialize_metadata(document_metadata or {})
        conn = self._active()
        document_id = uuid.uuid4()

        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM documents WHERE path = %s",
                (path,),
            )
            cur.execute(
                """
                INSERT INTO documents(
                    id,
                    path,
                    content_hash,
                    media_type,
                    size_bytes,
                    metadata,
                    metadata_hash
                )
                VALUES(%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    document_id,
                    path,
                    content_hash,
                    media_type,
                    size_bytes,
                    serialized_metadata,
                    metadata_hash,
                ),
            )
            cur.executemany(
                """
                INSERT INTO chunks(
                    id,
                    document_id,
                    chunk_index,
                    content,
                    content_hash,
                    metadata,
                    embedding_model,
                    embedding
                )
                VALUES(%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        uuid.uuid4(),
                        document_id,
                        chunk.index,
                        chunk.text,
                        chunk.content_hash,
                        _serialize_metadata(chunk.metadata),
                        model_name,
                        list(embedding),
                    )
                    for chunk, embedding in zip(
                        chunks,
                        embeddings,
                        strict=True,
                    )
                ],
            )

        return len(chunks)

    def update_document_metadata(
        self,
        document_id: str,
        document_metadata: Mapping[str, Any],
        metadata_hash: str,
    ) -> None:
        with self._active().cursor() as cur:
            cur.execute(
                """
                UPDATE documents
                SET
                    metadata = %s,
                    metadata_hash = %s,
                    last_synced_at = now()
                WHERE id = %s
                """,
                (
                    _serialize_metadata(document_metadata),
                    metadata_hash,
                    document_id,
                ),
            )

            if cur.rowcount != 1:
                raise RuntimeError(f"Document does not exist: {document_id}")

    def record_run(
        self,
        result: SyncResult,
        source: str,
        error: str | None = None,
    ) -> None:
        with self._active().cursor() as cur:
            cur.execute(
                """
                INSERT INTO sync_runs(
                    id,
                    source,
                    status,
                    new_documents,
                    changed_documents,
                    metadata_changed_documents,
                    deleted_documents,
                    unchanged_documents,
                    embedded_chunks,
                    deleted_chunks,
                    scanned_documents,
                    scanned_bytes,
                    embedding_batches,
                    embedding_duration_ms,
                    started_at,
                    finished_at,
                    error
                )
                VALUES(
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    result.run_id,
                    source,
                    result.status,
                    result.new_documents,
                    result.changed_documents,
                    result.metadata_changed_documents,
                    result.deleted_documents,
                    result.unchanged_documents,
                    result.embedded_chunks,
                    result.deleted_chunks,
                    result.scanned_documents,
                    result.scanned_bytes,
                    result.embedding_batches,
                    result.embedding_duration_ms,
                    result.started_at,
                    result.finished_at,
                    error,
                ),
            )

    def recent_runs(self, limit: int) -> list[SyncRunRecord]:
        if limit <= 0:
            raise ValueError("Run-history limit must be greater than zero")

        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id::text,
                    source,
                    status,
                    new_documents,
                    changed_documents,
                    metadata_changed_documents,
                    deleted_documents,
                    unchanged_documents,
                    embedded_chunks,
                    deleted_chunks,
                    scanned_documents,
                    scanned_bytes,
                    embedding_batches,
                    embedding_duration_ms,
                    started_at,
                    finished_at,
                    GREATEST(
                        0,
                        EXTRACT(
                            EPOCH FROM finished_at - started_at
                        ) * 1000
                    ) AS duration_ms,
                    error
                FROM sync_runs
                ORDER BY finished_at DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            )

            rows = cur.fetchall()

        return [
            SyncRunRecord(
                run_id=str(row[0]),
                source=str(row[1]),
                status=str(row[2]),
                new_documents=int(row[3]),
                changed_documents=int(row[4]),
                metadata_changed_documents=int(row[5]),
                deleted_documents=int(row[6]),
                unchanged_documents=int(row[7]),
                embedded_chunks=int(row[8]),
                deleted_chunks=int(row[9]),
                scanned_documents=int(row[10]),
                scanned_bytes=int(row[11]),
                embedding_batches=int(row[12]),
                embedding_duration_ms=float(row[13]),
                started_at=row[14],
                finished_at=row[15],
                duration_ms=float(row[16]),
                error=None if row[17] is None else str(row[17]),
            )
            for row in rows
        ]

    def search(
        self,
        query_embedding: Sequence[float],
        model_name: str,
        limit: int,
        metadata_filter: Mapping[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Return compatible chunks using cosine similarity."""

        if limit <= 0:
            raise ValueError("Search limit must be greater than zero")

        if not query_embedding:
            raise ValueError("Query embedding must not be empty")

        serialized_filter = (
            None if metadata_filter is None else _serialize_metadata(metadata_filter)
        )

        with self._pool.connection() as conn:
            register_vector(conn)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH query_input AS (
                        SELECT
                            %s::vector AS embedding,
                            %s::jsonb AS metadata_filter
                    )
                    SELECT
                        documents.path,
                        chunks.chunk_index,
                        chunks.content,
                        documents.metadata || chunks.metadata,
                        chunks.embedding_model,
                        1 - (
                            chunks.embedding
                            <=> query_input.embedding
                        ) AS score
                    FROM chunks
                    JOIN documents
                      ON documents.id = chunks.document_id
                    CROSS JOIN query_input
                    WHERE chunks.embedding_model = %s
                      AND (
                          query_input.metadata_filter IS NULL
                          OR documents.metadata
                             @> query_input.metadata_filter
                      )
                    ORDER BY
                        chunks.embedding <=> query_input.embedding,
                        documents.path,
                        chunks.chunk_index
                    LIMIT %s
                    """,
                    (
                        list(query_embedding),
                        serialized_filter,
                        model_name,
                        limit,
                    ),
                )

                rows = cur.fetchall()

        return [
            SearchResult(
                document_path=str(row[0]),
                chunk_index=int(row[1]),
                content=str(row[2]),
                metadata=dict(row[3]),
                embedding_model=str(row[4]),
                score=float(row[5]),
            )
            for row in rows
        ]

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
