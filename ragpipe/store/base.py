from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Any

from ragpipe.models import (
    EMPTY_METADATA_HASH,
    Chunk,
    DocumentState,
    OperationalMetricsSnapshot,
    SearchResult,
    StoreStatus,
    SyncResult,
    SyncRunRecord,
)


class SyncLockUnavailableError(RuntimeError):
    """Raised when another synchronization already owns the store lock."""


class Store(ABC):
    @abstractmethod
    def initialize(self, dimension: int) -> None: ...

    @abstractmethod
    def sync_lock(self) -> AbstractContextManager[None]: ...

    @abstractmethod
    def transaction(self) -> AbstractContextManager[Store]: ...

    @abstractmethod
    def document_states(self) -> dict[str, DocumentState]: ...

    @abstractmethod
    def delete_document(self, document_id: str) -> int: ...

    @abstractmethod
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
    ) -> int: ...

    @abstractmethod
    def update_document_metadata(
        self,
        document_id: str,
        document_metadata: Mapping[str, Any],
        metadata_hash: str,
    ) -> None: ...

    @abstractmethod
    def record_run(
        self,
        result: SyncResult,
        source: str,
        error: str | None = None,
    ) -> None: ...

    @abstractmethod
    def search(
        self,
        query_embedding: Sequence[float],
        model_name: str,
        limit: int,
        metadata_filter: Mapping[str, Any] | None = None,
    ) -> list[SearchResult]: ...

    @abstractmethod
    def recent_runs(self, limit: int) -> list[SyncRunRecord]: ...

    @abstractmethod
    def operational_metrics(
        self,
    ) -> OperationalMetricsSnapshot: ...

    @abstractmethod
    def status(self) -> StoreStatus: ...

    @abstractmethod
    def close(self) -> None: ...
