from __future__ import annotations

import os
from collections.abc import Generator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config

from alembic import command
from ragpipe.chunking.chunker import RecursiveCharacterChunker
from ragpipe.ingest.metadata import metadata_hash
from ragpipe.ingest.source import LocalFolderSource
from ragpipe.models import Chunk, SyncResult
from ragpipe.pipeline import SyncFailedError, SyncPipeline
from ragpipe.store.base import SyncLockUnavailableError
from ragpipe.store.pgvector_store import PgVectorStore
from tests.fakes import FakeEmbedder

TEST_DATABASE_URL = os.getenv("RAGPIPE_TEST_DATABASE_URL")

pytestmark = pytest.mark.integration


class PgVectorFakeEmbedder(FakeEmbedder):
    @property
    def dimension(self) -> int:
        return 384

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        self.texts += len(texts)

        return [[float(len(text)), *([0.0] * 383)] for text in texts]


def reset_test_database(database_url: str) -> None:
    """Remove ragpipe tables so every test starts with an empty database."""

    with psycopg.connect(database_url, autocommit=True) as connection:
        row = connection.execute("SELECT current_database()").fetchone()

        if row is None:
            raise RuntimeError("Could not determine the current database")

        database_name = str(row[0])

        # Protect the development/production database from accidental deletion.
        if not database_name.endswith("_test"):
            raise RuntimeError(f"Refusing to reset non-test database: {database_name}")

        connection.execute(
            """
            DROP TABLE IF EXISTS chunks CASCADE;
            DROP TABLE IF EXISTS documents CASCADE;
            DROP TABLE IF EXISTS sync_runs CASCADE;
            DROP TABLE IF EXISTS alembic_version CASCADE;
            """
        )


@pytest.fixture
def pgvector_store(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[PgVectorStore, None, None]:
    if TEST_DATABASE_URL is None:
        pytest.skip("RAGPIPE_TEST_DATABASE_URL is not configured")

    monkeypatch.setenv(
        "RAGPIPE_DATABASE_URL",
        TEST_DATABASE_URL,
    )

    reset_test_database(TEST_DATABASE_URL)

    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")

    store = PgVectorStore(TEST_DATABASE_URL)
    store.initialize(dimension=384)

    try:
        yield store
    finally:
        store.close()
        command.downgrade(alembic_config, "base")
        reset_test_database(TEST_DATABASE_URL)


def create_pipeline(
    store: PgVectorStore,
    embedder: PgVectorFakeEmbedder | None = None,
) -> SyncPipeline:
    return SyncPipeline(
        store=store,
        chunker=RecursiveCharacterChunker(
            chunk_size=100,
            overlap=10,
        ),
        embedder=embedder or PgVectorFakeEmbedder(),
        batch_size=16,
    )


def make_search_vector(
    first: float,
    second: float,
) -> list[float]:
    return [
        first,
        second,
        *([0.0] * 382),
    ]


def insert_search_document(
    store: PgVectorStore,
    path: str,
    content: str,
    embedding: Sequence[float],
    model_name: str = "search-test-model",
    metadata: dict[str, str] | None = None,
) -> None:
    chunk = Chunk(
        index=0,
        text=content,
        content_hash="c" * 64,
        metadata=metadata or {},
    )

    store.replace_document(
        path=path,
        content_hash="d" * 64,
        media_type="text/plain",
        size_bytes=len(content.encode("utf-8")),
        chunks=[chunk],
        embeddings=[embedding],
        model_name=model_name,
    )


def test_complete_document_lifecycle(
    tmp_path: Path,
    pgvector_store: PgVectorStore,
) -> None:
    document = tmp_path / "policy.md"
    document.write_text(
        "Employees receive 12 casual leaves every year.",
        encoding="utf-8",
    )

    pipeline = create_pipeline(pgvector_store)

    # First run: document and vector must be inserted.
    first = pipeline.sync(LocalFolderSource(tmp_path))

    assert first.new_documents == 1
    assert first.embedded_chunks == 1
    assert first.deleted_chunks == 0

    first_status = pgvector_store.status()

    assert first_status.documents == 1
    assert first_status.chunks == 1

    # Second run: unchanged document must not be embedded again.
    second = pipeline.sync(LocalFolderSource(tmp_path))

    assert second.new_documents == 0
    assert second.changed_documents == 0
    assert second.unchanged_documents == 1
    assert second.embedded_chunks == 0
    assert second.deleted_chunks == 0

    second_status = pgvector_store.status()

    assert second_status.documents == 1
    assert second_status.chunks == 1

    # Third run: changing the file must replace its old vector.
    document.write_text(
        "Employees receive 15 casual leaves every year.",
        encoding="utf-8",
    )

    changed = pipeline.sync(LocalFolderSource(tmp_path))

    assert changed.changed_documents == 1
    assert changed.embedded_chunks == 1
    assert changed.deleted_chunks == 1

    changed_status = pgvector_store.status()

    assert changed_status.documents == 1
    assert changed_status.chunks == 1

    # Fourth run: deleting the source must remove its vector.
    document.unlink()

    deleted = pipeline.sync(LocalFolderSource(tmp_path))

    assert deleted.deleted_documents == 1
    assert deleted.deleted_chunks == 1
    assert deleted.embedded_chunks == 0

    deleted_status = pgvector_store.status()

    assert deleted_status.documents == 0
    assert deleted_status.chunks == 0


class FailingEmbedder(PgVectorFakeEmbedder):
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("Simulated embedding failure")


def test_failed_changed_document_sync_rolls_back(
    tmp_path: Path,
    pgvector_store: PgVectorStore,
) -> None:
    document = tmp_path / "policy.txt"
    document.write_text("Original policy", encoding="utf-8")

    working_pipeline = create_pipeline(pgvector_store)
    working_pipeline.sync(LocalFolderSource(tmp_path))

    original_status = pgvector_store.status()

    with pgvector_store.transaction():
        original_state = pgvector_store.document_states()["policy.txt"]

    document.write_text("Updated policy", encoding="utf-8")

    failing_pipeline = create_pipeline(
        pgvector_store,
        embedder=FailingEmbedder(),
    )

    with pytest.raises(
        SyncFailedError,
        match="Simulated embedding failure",
    ):
        failing_pipeline.sync(LocalFolderSource(tmp_path))

    # The original document and vector must still exist after rollback.
    rolled_back_status = pgvector_store.status()

    assert rolled_back_status.documents == original_status.documents
    assert rolled_back_status.chunks == original_status.chunks

    assert rolled_back_status.last_sync_status == "failed"

    failed_run = pgvector_store.recent_runs(limit=1)[0]

    assert failed_run.status == "failed"
    assert failed_run.changed_documents == 1
    assert failed_run.scanned_documents == 1
    assert failed_run.scanned_bytes == len(b"Updated policy")
    assert failed_run.embedding_batches == 1
    assert failed_run.embedding_duration_ms >= 0
    assert failed_run.duration_ms >= 0

    # These represent committed changes, so they remain zero after rollback.
    assert failed_run.embedded_chunks == 0
    assert failed_run.deleted_chunks == 0

    assert failed_run.error is not None
    assert "Simulated embedding failure" in failed_run.error

    with pgvector_store.transaction():
        rolled_back_state = pgvector_store.document_states()["policy.txt"]

    assert rolled_back_state.content_hash == original_state.content_hash


def test_sync_lock_rejects_concurrent_holder(
    pgvector_store: PgVectorStore,
) -> None:
    if TEST_DATABASE_URL is None:
        pytest.skip("RAGPIPE_TEST_DATABASE_URL is not configured")

    contender = PgVectorStore(TEST_DATABASE_URL)

    try:
        with (
            pgvector_store.sync_lock(),
            pytest.raises(
                SyncLockUnavailableError,
                match="already running",
            ),
            contender.sync_lock(),
        ):
            pytest.fail("Contender unexpectedly acquired the sync lock")

        # The lock must become reusable after the first holder releases it.
        with contender.sync_lock():
            pass
    finally:
        contender.close()


def test_vector_search_ranks_nearest_chunk_and_returns_metadata(
    pgvector_store: PgVectorStore,
) -> None:
    with pgvector_store.transaction():
        insert_search_document(
            pgvector_store,
            path="nearest.txt",
            content="Nearest content",
            embedding=make_search_vector(1.0, 0.0),
            metadata={"topic": "nearest"},
        )
        insert_search_document(
            pgvector_store,
            path="distant.txt",
            content="Distant content",
            embedding=make_search_vector(0.0, 1.0),
            metadata={"topic": "distant"},
        )

    results = pgvector_store.search(
        query_embedding=make_search_vector(1.0, 0.0),
        model_name="search-test-model",
        limit=5,
    )

    assert [result.document_path for result in results] == [
        "nearest.txt",
        "distant.txt",
    ]
    assert results[0].chunk_index == 0
    assert results[0].content == "Nearest content"
    assert results[0].metadata == {"topic": "nearest"}
    assert results[0].embedding_model == "search-test-model"
    assert results[0].score == pytest.approx(1.0)
    assert results[1].score == pytest.approx(0.0)


def test_vector_search_filters_embedding_model_and_applies_limit(
    pgvector_store: PgVectorStore,
) -> None:
    with pgvector_store.transaction():
        insert_search_document(
            pgvector_store,
            path="first.txt",
            content="First compatible result",
            embedding=make_search_vector(1.0, 0.0),
        )
        insert_search_document(
            pgvector_store,
            path="second.txt",
            content="Second compatible result",
            embedding=make_search_vector(0.8, 0.2),
        )
        insert_search_document(
            pgvector_store,
            path="incompatible.txt",
            content="Different embedding model",
            embedding=make_search_vector(1.0, 0.0),
            model_name="different-model",
        )

    results = pgvector_store.search(
        query_embedding=make_search_vector(1.0, 0.0),
        model_name="search-test-model",
        limit=1,
    )

    assert len(results) == 1
    assert results[0].document_path == "first.txt"
    assert results[0].embedding_model == "search-test-model"


def test_vector_search_returns_empty_list_for_empty_store(
    pgvector_store: PgVectorStore,
) -> None:
    results = pgvector_store.search(
        query_embedding=make_search_vector(1.0, 0.0),
        model_name="search-test-model",
        limit=5,
    )

    assert results == []


def test_vector_search_rejects_invalid_inputs(
    pgvector_store: PgVectorStore,
) -> None:
    with pytest.raises(
        ValueError,
        match="limit must be greater than zero",
    ):
        pgvector_store.search(
            query_embedding=make_search_vector(1.0, 0.0),
            model_name="search-test-model",
            limit=0,
        )

    with pytest.raises(
        ValueError,
        match="must not be empty",
    ):
        pgvector_store.search(
            query_embedding=[],
            model_name="search-test-model",
            limit=5,
        )


def test_vector_search_hnsw_index_exists(
    pgvector_store: PgVectorStore,
) -> None:
    if TEST_DATABASE_URL is None:
        pytest.skip("RAGPIPE_TEST_DATABASE_URL is not configured")

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        row = connection.execute(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'chunks'
              AND indexname = 'chunks_embedding_hnsw_idx'
            """
        ).fetchone()

    assert row is not None

    index_definition = str(row[0]).lower()

    assert "using hnsw" in index_definition
    assert "vector_cosine_ops" in index_definition


def test_document_metadata_is_stored_updated_and_filtered(
    pgvector_store: PgVectorStore,
) -> None:
    original_metadata = {
        "department": "hr",
        "tags": ["leave", "policy"],
    }

    with pgvector_store.transaction():
        pgvector_store.replace_document(
            path="policy.md",
            content_hash="d" * 64,
            media_type="text/markdown",
            size_bytes=12,
            chunks=[
                Chunk(
                    index=0,
                    text="Leave policy",
                    content_hash="c" * 64,
                    metadata={"chunk_index": 0},
                )
            ],
            embeddings=[make_search_vector(1.0, 0.0)],
            model_name="search-test-model",
            document_metadata=original_metadata,
            metadata_hash=metadata_hash(original_metadata),
        )

    matching = pgvector_store.search(
        query_embedding=make_search_vector(1.0, 0.0),
        model_name="search-test-model",
        limit=5,
        metadata_filter={"department": "hr"},
    )

    assert len(matching) == 1
    assert matching[0].metadata == {
        "department": "hr",
        "tags": ["leave", "policy"],
        "chunk_index": 0,
    }

    not_matching = pgvector_store.search(
        query_embedding=make_search_vector(1.0, 0.0),
        model_name="search-test-model",
        limit=5,
        metadata_filter={"department": "finance"},
    )

    assert not_matching == []

    with pgvector_store.transaction():
        document = pgvector_store.document_states()["policy.md"]

        updated_metadata = {
            "department": "finance",
            "tags": ["policy"],
        }

        pgvector_store.update_document_metadata(
            document_id=document.id,
            document_metadata=updated_metadata,
            metadata_hash=metadata_hash(updated_metadata),
        )

    updated = pgvector_store.search(
        query_embedding=make_search_vector(1.0, 0.0),
        model_name="search-test-model",
        limit=5,
        metadata_filter={"department": "finance"},
    )

    assert len(updated) == 1
    assert updated[0].metadata["department"] == "finance"


def test_pipeline_metadata_only_change_preserves_existing_chunks(
    tmp_path: Path,
    pgvector_store: PgVectorStore,
) -> None:
    document = tmp_path / "policy.md"
    document.write_text(
        "Employees receive annual leave.",
        encoding="utf-8",
    )

    embedder = PgVectorFakeEmbedder()
    pipeline = create_pipeline(
        pgvector_store,
        embedder=embedder,
    )

    first = pipeline.sync(LocalFolderSource(tmp_path))

    assert first.new_documents == 1
    assert first.embedded_chunks == 1

    embedding_calls_before = embedder.calls

    if TEST_DATABASE_URL is None:
        pytest.fail("RAGPIPE_TEST_DATABASE_URL unexpectedly missing")

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        chunk_before = connection.execute(
            """
            SELECT chunks.id::text
            FROM chunks
            JOIN documents
              ON documents.id = chunks.document_id
            WHERE documents.path = %s
            """,
            ("policy.md",),
        ).fetchone()

    assert chunk_before is not None

    (tmp_path / ".ragpipe-metadata.json").write_text(
        """
        {
          "policy.md": {
            "department": "hr",
            "tags": ["leave", "policy"]
          }
        }
        """,
        encoding="utf-8",
    )

    changed = pipeline.sync(LocalFolderSource(tmp_path))

    assert changed.new_documents == 0
    assert changed.changed_documents == 0
    assert changed.metadata_changed_documents == 1
    assert changed.deleted_documents == 0
    assert changed.unchanged_documents == 0
    assert changed.embedded_chunks == 0
    assert changed.deleted_chunks == 0
    assert embedder.calls == embedding_calls_before

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        chunk_after = connection.execute(
            """
            SELECT chunks.id::text
            FROM chunks
            JOIN documents
              ON documents.id = chunks.document_id
            WHERE documents.path = %s
            """,
            ("policy.md",),
        ).fetchone()

    # The same chunk remains—the pipeline did not delete and recreate it.
    assert chunk_after == chunk_before

    matching = pgvector_store.search(
        query_embedding=make_search_vector(1.0, 0.0),
        model_name=embedder.model_name,
        limit=5,
        metadata_filter={"department": "hr"},
    )

    assert len(matching) == 1
    assert matching[0].document_path == "policy.md"
    assert matching[0].metadata["department"] == "hr"
    assert matching[0].metadata["tags"] == ["leave", "policy"]

    nonmatching = pgvector_store.search(
        query_embedding=make_search_vector(1.0, 0.0),
        model_name=embedder.model_name,
        limit=5,
        metadata_filter={"department": "finance"},
    )

    assert nonmatching == []


def test_document_metadata_gin_index_exists(
    pgvector_store: PgVectorStore,
) -> None:
    if TEST_DATABASE_URL is None:
        pytest.fail("RAGPIPE_TEST_DATABASE_URL unexpectedly missing")

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        row = connection.execute(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'documents'
              AND indexname = 'documents_metadata_gin_idx'
            """
        ).fetchone()

    assert row is not None

    index_definition = str(row[0]).lower()

    assert "using gin" in index_definition
    assert "jsonb_path_ops" in index_definition


def test_sync_operational_metrics_are_persisted(
    tmp_path: Path,
    pgvector_store: PgVectorStore,
) -> None:
    content = "Operational metrics test document."

    (tmp_path / "metrics.txt").write_text(
        content,
        encoding="utf-8",
    )

    embedder = PgVectorFakeEmbedder()
    result = create_pipeline(
        pgvector_store,
        embedder=embedder,
    ).sync(LocalFolderSource(tmp_path))

    if TEST_DATABASE_URL is None:
        pytest.fail("RAGPIPE_TEST_DATABASE_URL unexpectedly missing")

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        row = connection.execute(
            """
            SELECT
                scanned_documents,
                scanned_bytes,
                embedding_batches,
                embedding_duration_ms,
                EXTRACT(
                    EPOCH FROM finished_at - started_at
                ) * 1000 AS total_duration_ms
            FROM sync_runs
            WHERE id = %s
            """,
            (result.run_id,),
        ).fetchone()

    with pytest.raises(
        ValueError,
        match="greater than zero",
    ):
        pgvector_store.recent_runs(limit=0)
    assert row is not None
    assert int(row[0]) == 1
    assert int(row[1]) == len(content.encode("utf-8"))
    assert int(row[2]) == 1
    assert float(row[3]) >= 0
    assert float(row[4]) >= 0

    assert result.scanned_documents == 1
    assert result.scanned_bytes == len(content.encode("utf-8"))
    assert result.embedding_batches == 1
    assert result.embedding_duration_ms >= 0

    recent = pgvector_store.recent_runs(limit=1)

    assert len(recent) == 1
    assert recent[0].run_id == result.run_id
    assert recent[0].status == "succeeded"
    assert recent[0].scanned_documents == 1
    assert recent[0].scanned_bytes == len(content.encode("utf-8"))
    assert recent[0].embedding_batches == 1
    assert recent[0].embedding_duration_ms >= 0
    assert recent[0].duration_ms >= 0
    assert recent[0].error is None


def test_operational_metrics_snapshot_aggregates_all_runs(
    pgvector_store: PgVectorStore,
) -> None:
    started = datetime(
        2026,
        9,
        4,
        13,
        0,
        tzinfo=UTC,
    )
    succeeded = SyncResult(
        run_id="00000000-0000-0000-0000-000000000001",
        status="succeeded",
        new_documents=1,
        changed_documents=2,
        metadata_changed_documents=3,
        deleted_documents=4,
        unchanged_documents=5,
        embedded_chunks=6,
        deleted_chunks=7,
        scanned_documents=8,
        scanned_bytes=900,
        embedding_batches=10,
        embedding_duration_ms=11.5,
        started_at=started,
        finished_at=started + timedelta(milliseconds=100),
    )
    failed_started = started + timedelta(seconds=1)
    failed = SyncResult(
        run_id="00000000-0000-0000-0000-000000000002",
        status="failed",
        new_documents=0,
        changed_documents=1,
        metadata_changed_documents=0,
        deleted_documents=0,
        unchanged_documents=0,
        embedded_chunks=0,
        deleted_chunks=0,
        scanned_documents=2,
        scanned_bytes=100,
        embedding_batches=1,
        embedding_duration_ms=2.5,
        started_at=failed_started,
        finished_at=failed_started + timedelta(milliseconds=250),
    )

    with pgvector_store.transaction():
        pgvector_store.record_run(
            succeeded,
            source="/documents",
        )
        pgvector_store.record_run(
            failed,
            source="s3://documents/knowledge",
            error="RuntimeError: test failure",
        )

    snapshot = pgvector_store.operational_metrics()

    assert snapshot.documents == 0
    assert snapshot.chunks == 0

    assert snapshot.sync_runs_running == 0
    assert snapshot.sync_runs_succeeded == 1
    assert snapshot.sync_runs_failed == 1

    assert snapshot.new_documents_total == 1
    assert snapshot.changed_documents_total == 3
    assert snapshot.metadata_changed_documents_total == 3
    assert snapshot.deleted_documents_total == 4
    assert snapshot.unchanged_documents_total == 5

    assert snapshot.embedded_chunks_total == 6
    assert snapshot.deleted_chunks_total == 7
    assert snapshot.scanned_documents_total == 10
    assert snapshot.scanned_bytes_total == 1000
    assert snapshot.embedding_batches_total == 11
    assert snapshot.embedding_duration_ms_total == pytest.approx(14.0)

    assert snapshot.last_sync_status == "failed"
    assert snapshot.last_sync_at == failed.finished_at
    assert snapshot.last_sync_duration_ms == pytest.approx(250.0)
