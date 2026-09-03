from __future__ import annotations

import os
from collections.abc import Generator, Sequence
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config

from alembic import command
from ragpipe.chunking.chunker import RecursiveCharacterChunker
from ragpipe.pipeline import SyncPipeline
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
    first = pipeline.sync(tmp_path)

    assert first.new_documents == 1
    assert first.embedded_chunks == 1
    assert first.deleted_chunks == 0

    first_status = pgvector_store.status()

    assert first_status.documents == 1
    assert first_status.chunks == 1

    # Second run: unchanged document must not be embedded again.
    second = pipeline.sync(tmp_path)

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

    changed = pipeline.sync(tmp_path)

    assert changed.changed_documents == 1
    assert changed.embedded_chunks == 1
    assert changed.deleted_chunks == 1

    changed_status = pgvector_store.status()

    assert changed_status.documents == 1
    assert changed_status.chunks == 1

    # Fourth run: deleting the source must remove its vector.
    document.unlink()

    deleted = pipeline.sync(tmp_path)

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
    working_pipeline.sync(tmp_path)

    original_status = pgvector_store.status()

    with pgvector_store.transaction():
        original_state = pgvector_store.document_states()["policy.txt"]

    document.write_text("Updated policy", encoding="utf-8")

    failing_pipeline = create_pipeline(
        pgvector_store,
        embedder=FailingEmbedder(),
    )

    with pytest.raises(RuntimeError, match="Simulated embedding failure"):
        failing_pipeline.sync(tmp_path)

    # The original document and vector must still exist after rollback.
    rolled_back_status = pgvector_store.status()

    assert rolled_back_status.documents == original_status.documents
    assert rolled_back_status.chunks == original_status.chunks

    with pgvector_store.transaction():
        rolled_back_state = pgvector_store.document_states()["policy.txt"]

    assert rolled_back_state.content_hash == original_state.content_hash
