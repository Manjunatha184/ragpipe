from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from contextlib import AbstractContextManager

from ragpipe.models import Chunk, DocumentState, StoreStatus, SyncResult


class Store(ABC):
    @abstractmethod
    def initialize(self, dimension: int) -> None: ...
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
    ) -> int: ...
    @abstractmethod
    def record_run(self, result: SyncResult, source: str, error: str | None = None) -> None: ...
    @abstractmethod
    def status(self) -> StoreStatus: ...
    @abstractmethod
    def close(self) -> None: ...
