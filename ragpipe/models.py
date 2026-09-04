from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

EMPTY_METADATA_HASH = hashlib.sha256(b"{}").hexdigest()


class ChangeType(StrEnum):
    NEW = "new"
    CHANGED = "changed"
    METADATA_CHANGED = "metadata_changed"
    DELETED = "deleted"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class ScannedDocument:
    path: str
    content_hash: str
    size_bytes: int
    media_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    metadata_hash: str = EMPTY_METADATA_HASH


@dataclass(frozen=True)
class DocumentState:
    id: str
    path: str
    content_hash: str
    metadata_hash: str = EMPTY_METADATA_HASH


@dataclass(frozen=True)
class SourceDiff:
    new: tuple[ScannedDocument, ...] = ()
    changed: tuple[ScannedDocument, ...] = ()
    deleted: tuple[DocumentState, ...] = ()
    unchanged: tuple[ScannedDocument, ...] = ()
    metadata_changed: tuple[ScannedDocument, ...] = ()


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    document_path: str
    chunk_index: int
    content: str
    metadata: dict[str, Any]
    embedding_model: str
    score: float


@dataclass(frozen=True)
class SyncResult:
    run_id: str
    status: str
    new_documents: int
    changed_documents: int
    deleted_documents: int
    unchanged_documents: int
    embedded_chunks: int
    deleted_chunks: int
    started_at: datetime
    finished_at: datetime
    metadata_changed_documents: int = 0
    scanned_documents: int = 0
    scanned_bytes: int = 0
    embedding_batches: int = 0
    embedding_duration_ms: float = 0.0


@dataclass(frozen=True)
class SyncRunRecord:
    run_id: str
    source: str
    status: str
    new_documents: int
    changed_documents: int
    metadata_changed_documents: int
    deleted_documents: int
    unchanged_documents: int
    embedded_chunks: int
    deleted_chunks: int
    scanned_documents: int
    scanned_bytes: int
    embedding_batches: int
    embedding_duration_ms: float
    started_at: datetime
    finished_at: datetime
    duration_ms: float
    error: str | None

    @classmethod
    def from_result(
        cls,
        result: SyncResult,
        source: str,
        error: str | None = None,
    ) -> SyncRunRecord:
        duration_ms = max(
            0.0,
            (result.finished_at - result.started_at).total_seconds() * 1000,
        )

        return cls(
            run_id=result.run_id,
            source=source,
            status=result.status,
            new_documents=result.new_documents,
            changed_documents=result.changed_documents,
            metadata_changed_documents=result.metadata_changed_documents,
            deleted_documents=result.deleted_documents,
            unchanged_documents=result.unchanged_documents,
            embedded_chunks=result.embedded_chunks,
            deleted_chunks=result.deleted_chunks,
            scanned_documents=result.scanned_documents,
            scanned_bytes=result.scanned_bytes,
            embedding_batches=result.embedding_batches,
            embedding_duration_ms=result.embedding_duration_ms,
            started_at=result.started_at,
            finished_at=result.finished_at,
            duration_ms=duration_ms,
            error=error,
        )


@dataclass(frozen=True)
class StoreStatus:
    documents: int
    chunks: int
    last_sync_at: datetime | None
    last_sync_status: str | None
