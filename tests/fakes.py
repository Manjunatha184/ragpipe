from __future__ import annotations

import copy
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from ragpipe.embedding.base import EmbeddingProvider
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


class FakeEmbedder(EmbeddingProvider):
    calls = 0
    texts = 0

    @property
    def dimension(self) -> int:
        return 3

    @property
    def model_name(self) -> str:
        return "fake-v1"

    def embed(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        self.calls += 1
        self.texts += len(texts)

        return [[float(len(text)), 0.0, 1.0] for text in texts]


class MemoryStore(Store):
    def __init__(self) -> None:
        self.documents: dict[str, DocumentState] = {}
        self.document_metadata: dict[str, dict[str, Any]] = {}
        self.chunk_counts: dict[str, int] = {}
        self.runs: list[SyncResult] = []
        self.run_records: list[SyncRunRecord] = []
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
        backup = copy.deepcopy(
            (
                self.documents,
                self.document_metadata,
                self.chunk_counts,
                self.runs,
                self.write_count,
                self.run_records,
            )
        )

        try:
            yield self
        except Exception:
            (
                self.documents,
                self.document_metadata,
                self.chunk_counts,
                self.runs,
                self.write_count,
                self.run_records,
            ) = backup
            raise

    def document_states(self) -> dict[str, DocumentState]:
        return dict(self.documents)

    def delete_document(self, document_id: str) -> int:
        path = next(path for path, document in self.documents.items() if document.id == document_id)

        count = self.chunk_counts.pop(path)
        self.document_metadata.pop(path, None)
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
        document_metadata: Mapping[str, Any] | None = None,
        metadata_hash: str = EMPTY_METADATA_HASH,
    ) -> int:
        assert len(chunks) == len(embeddings)

        self.documents[path] = DocumentState(
            id=str(uuid.uuid4()),
            path=path,
            content_hash=content_hash,
            metadata_hash=metadata_hash,
        )
        self.document_metadata[path] = dict(document_metadata or {})
        self.chunk_counts[path] = len(chunks)
        self.write_count += 1

        return len(chunks)

    def update_document_metadata(
        self,
        document_id: str,
        document_metadata: Mapping[str, Any],
        metadata_hash: str,
    ) -> None:
        path = next(path for path, document in self.documents.items() if document.id == document_id)
        current = self.documents[path]

        self.documents[path] = DocumentState(
            id=current.id,
            path=current.path,
            content_hash=current.content_hash,
            metadata_hash=metadata_hash,
        )
        self.document_metadata[path] = dict(document_metadata)
        self.write_count += 1

    def record_run(
        self,
        result: SyncResult,
        source: str,
        error: str | None = None,
    ) -> None:
        self.runs.append(result)
        self.run_records.append(
            SyncRunRecord.from_result(
                result=result,
                source=source,
                error=error,
            )
        )

    def recent_runs(self, limit: int) -> list[SyncRunRecord]:
        if limit <= 0:
            raise ValueError("Run-history limit must be greater than zero")

        return list(reversed(self.run_records))[:limit]

    def search(
        self,
        query_embedding: Sequence[float],
        model_name: str,
        limit: int,
        metadata_filter: Mapping[str, Any] | None = None,
    ) -> list[SearchResult]:
        if limit <= 0:
            raise ValueError("Search limit must be greater than zero")

        return []

    def status(self) -> StoreStatus:
        return StoreStatus(
            documents=len(self.documents),
            chunks=sum(self.chunk_counts.values()),
            last_sync_at=(self.runs[-1].finished_at if self.runs else None),
            last_sync_status=(self.runs[-1].status if self.runs else None),
        )

    def close(self) -> None:
        pass
