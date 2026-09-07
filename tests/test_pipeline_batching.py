from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from ragpipe.chunking.chunker import RecursiveCharacterChunker
from ragpipe.ingest.source import LocalFolderSource
from ragpipe.pipeline import SyncFailedError, SyncPipeline
from tests.fakes import FakeEmbedder, MemoryStore


class RecordingEmbedder(FakeEmbedder):
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def embed(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        self.batch_sizes.append(len(texts))
        return super().embed(texts)


class ShortResultEmbedder(FakeEmbedder):
    def embed(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        return super().embed(texts)[:-1]


def test_rejects_non_positive_batch_size() -> None:
    with pytest.raises(
        ValueError,
        match="Batch size must be greater than zero",
    ):
        SyncPipeline(
            store=MemoryStore(),
            chunker=RecursiveCharacterChunker(100, 0),
            embedder=FakeEmbedder(),
            batch_size=0,
        )


def test_batches_chunks_across_document_boundaries(
    tmp_path: Path,
) -> None:
    for index in range(5):
        (tmp_path / f"document-{index}.txt").write_text(
            f"Document {index}",
            encoding="utf-8",
        )

    store = MemoryStore()
    embedder = RecordingEmbedder()
    pipeline = SyncPipeline(
        store=store,
        chunker=RecursiveCharacterChunker(100, 0),
        embedder=embedder,
        batch_size=2,
    )

    result = pipeline.sync(LocalFolderSource(tmp_path))

    assert result.new_documents == 5
    assert result.embedded_chunks == 5
    assert result.embedding_batches == 3
    assert embedder.batch_sizes == [2, 2, 1]
    assert embedder.texts == 5
    assert store.status().documents == 5
    assert store.status().chunks == 5


def test_rejects_wrong_embedding_count_before_writing_documents(
    tmp_path: Path,
) -> None:
    (tmp_path / "document.txt").write_text(
        "Document content",
        encoding="utf-8",
    )

    store = MemoryStore()
    pipeline = SyncPipeline(
        store=store,
        chunker=RecursiveCharacterChunker(100, 0),
        embedder=ShortResultEmbedder(),
        batch_size=2,
    )

    with pytest.raises(
        SyncFailedError,
        match="unexpected number of vectors",
    ):
        pipeline.sync(LocalFolderSource(tmp_path))

    assert store.documents == {}
    assert store.status().chunks == 0
    assert store.runs[-1].status == "failed"
    assert store.runs[-1].embedding_batches == 1
    assert store.runs[-1].embedded_chunks == 0
