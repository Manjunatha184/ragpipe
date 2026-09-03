from collections.abc import Sequence
from pathlib import Path

import pytest

from ragpipe.chunking.chunker import RecursiveCharacterChunker
from ragpipe.pipeline import (
    SyncAlreadyRunningError,
    SyncFailedError,
    SyncPipeline,
    sanitize_error,
)
from tests.fakes import FakeEmbedder, MemoryStore


def make_pipeline() -> tuple[SyncPipeline, MemoryStore, FakeEmbedder]:
    store, embedder = MemoryStore(), FakeEmbedder()
    return SyncPipeline(store, RecursiveCharacterChunker(40, 5), embedder), store, embedder


def test_full_sync_is_idempotent(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("one document")
    pipeline, store, embedder = make_pipeline()
    first = pipeline.sync(tmp_path)
    writes_after_first, texts_after_first = store.write_count, embedder.texts
    second = pipeline.sync(tmp_path)
    assert first.new_documents == 1 and first.embedded_chunks == 1
    assert second.unchanged_documents == 1 and second.embedded_chunks == 0
    assert store.write_count == writes_after_first
    assert embedder.texts == texts_after_first
    assert store.status().documents == 1 and store.status().chunks == 1


def test_change_only_reembeds_changed_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("A")
    (tmp_path / "b.txt").write_text("B")
    pipeline, store, embedder = make_pipeline()
    pipeline.sync(tmp_path)
    before = embedder.texts
    (tmp_path / "b.txt").write_text("B changed")
    result = pipeline.sync(tmp_path)
    assert result.changed_documents == 1 and result.unchanged_documents == 1
    assert embedder.texts == before + 1
    assert store.status().documents == 2


def test_delete_removes_all_chunks_without_embedding(tmp_path: Path) -> None:
    path = tmp_path / "large.md"
    path.write_text("content " * 30)
    pipeline, store, embedder = make_pipeline()
    pipeline.sync(tmp_path)
    original_chunks, before = store.status().chunks, embedder.texts
    path.unlink()
    result = pipeline.sync(tmp_path)
    assert result.deleted_documents == 1 and result.deleted_chunks == original_chunks
    assert embedder.texts == before
    assert store.status().documents == 0 and store.status().chunks == 0


def test_empty_document_is_tracked_without_embedding(tmp_path: Path) -> None:
    (tmp_path / "empty.txt").write_text("")
    pipeline, store, embedder = make_pipeline()
    result = pipeline.sync(tmp_path)
    assert result.new_documents == 1 and result.embedded_chunks == 0
    assert embedder.calls == 0 and store.status().documents == 1


class FailingEmbedder(FakeEmbedder):
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("Embedding service unavailable")


def test_failed_sync_is_recorded_after_rollback(
    tmp_path: Path,
) -> None:
    document = tmp_path / "policy.txt"
    document.write_text(
        "Original policy",
        encoding="utf-8",
    )

    pipeline, store, _ = make_pipeline()
    pipeline.sync(tmp_path)

    original_state = store.documents["policy.txt"]
    original_chunk_count = store.status().chunks

    document.write_text(
        "Updated policy",
        encoding="utf-8",
    )

    failing_pipeline = SyncPipeline(
        store=store,
        chunker=RecursiveCharacterChunker(40, 5),
        embedder=FailingEmbedder(),
    )

    with pytest.raises(
        SyncFailedError,
        match="Embedding service unavailable",
    ) as captured:
        failing_pipeline.sync(tmp_path)

    assert captured.value.run_id == store.runs[-1].run_id
    assert store.runs[-1].status == "failed"
    assert store.status().last_sync_status == "failed"

    # The original document remains because the changed-document
    # transaction was rolled back.
    assert store.documents["policy.txt"] == original_state
    assert store.status().chunks == original_chunk_count


def test_error_sanitization_removes_credentials() -> None:
    error = RuntimeError(
        "Could not connect to "
        "postgresql://ragpipe:super-secret@localhost/ragpipe "
        "password=another-secret"
    )

    sanitized = sanitize_error(error)

    assert "super-secret" not in sanitized
    assert "another-secret" not in sanitized
    assert "postgresql://ragpipe:***@localhost/ragpipe" in sanitized
    assert "password=***" in sanitized


def test_lock_contention_does_not_start_or_record_sync(
    tmp_path: Path,
) -> None:
    (tmp_path / "document.txt").write_text(
        "Document content",
        encoding="utf-8",
    )

    pipeline, store, embedder = make_pipeline()
    store.sync_lock_available = False

    with pytest.raises(
        SyncAlreadyRunningError,
        match="already running",
    ):
        pipeline.sync(tmp_path)

    assert store.documents == {}
    assert store.runs == []
    assert store.write_count == 0
    assert embedder.calls == 0
