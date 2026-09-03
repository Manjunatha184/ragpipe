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


class PgVectorStore(Store):
    def __init__(self, database_url: str) -> None:
        self._pool = ConnectionPool(database_url, min_size=1, max_size=5, open=True)
        self._conn: Connection[Any] | None = None

    def initialize(self, dimension: int) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                  id uuid PRIMARY KEY, path text UNIQUE NOT NULL, content_hash char(64) NOT NULL,
                  media_type text NOT NULL, size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
                  last_synced_at timestamptz NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS sync_runs (
                  id uuid PRIMARY KEY, source text NOT NULL, status text NOT NULL,
                  new_documents int NOT NULL, changed_documents int NOT NULL,
                  deleted_documents int NOT NULL, unchanged_documents int NOT NULL,
                  embedded_chunks int NOT NULL, deleted_chunks int NOT NULL,
                  started_at timestamptz NOT NULL, finished_at timestamptz NOT NULL,
                  error text
                );
            """)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS chunks (
                  id uuid PRIMARY KEY,
                  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                  chunk_index int NOT NULL, content text NOT NULL, content_hash char(64) NOT NULL,
                  metadata jsonb NOT NULL DEFAULT '{{}}', embedding_model text NOT NULL,
                  embedding vector({dimension}) NOT NULL,
                  UNIQUE(document_id, chunk_index)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS chunks_document_id_idx ON chunks(document_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS documents_hash_idx ON documents(content_hash)")
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
