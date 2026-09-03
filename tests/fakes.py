from __future__ import annotations

import copy
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from ragpipe.embedding.base import EmbeddingProvider
from ragpipe.models import Chunk, DocumentState, StoreStatus, SyncResult
from ragpipe.store.base import Store, SyncLockUnavailableError


class FakeEmbedder(EmbeddingProvider):
    calls = 0
    texts = 0

    @property
    def dimension(self) -> int:
        return 3

    @property
    def model_name(self) -> str:
        return "fake-v1"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        self.texts += len(texts)
        return [[float(len(t)), 0.0, 1.0] for t in texts]


class MemoryStore(Store):
    def __init__(self) -> None:
        self.documents: dict[str, DocumentState] = {}
        self.chunk_counts: dict[str, int] = {}
        self.runs: list[SyncResult] = []
        self.write_count = 0
        self.sync_lock_available = True

    def initialize(self, dimension: int) -> None:
        pass

    @contextmanager
    def sync_lock(self) -> Iterator[None]:
        if not self.sync_lock_available:
            raise SyncLockUnavailableError("Another synchronization is already running.")

        yield

    @contextmanager
    def transaction(self) -> Iterator[Store]:
        backup = copy.deepcopy((self.documents, self.chunk_counts, self.runs, self.write_count))
        try:
            yield self
        except Exception:
            self.documents, self.chunk_counts, self.runs, self.write_count = backup
            raise

    def document_states(self) -> dict[str, DocumentState]:
        return dict(self.documents)

    def delete_document(self, document_id: str) -> int:
        path = next(path for path, doc in self.documents.items() if doc.id == document_id)
        count = self.chunk_counts.pop(path)
        del self.documents[path]
        self.write_count += 1
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
        assert len(chunks) == len(embeddings)
        self.documents[path] = DocumentState(str(uuid.uuid4()), path, content_hash)
        self.chunk_counts[path] = len(chunks)
        self.write_count += 1
        return len(chunks)

    def record_run(self, result: SyncResult, source: str, error: str | None = None) -> None:
        self.runs.append(result)

    def status(self) -> StoreStatus:
        return StoreStatus(
            len(self.documents),
            sum(self.chunk_counts.values()),
            self.runs[-1].finished_at if self.runs else None,
            self.runs[-1].status if self.runs else None,
        )

    def close(self) -> None:
        pass
