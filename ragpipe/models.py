from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class ChangeType(StrEnum):
    NEW = "new"
    CHANGED = "changed"
    DELETED = "deleted"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class ScannedDocument:
    path: str
    absolute_path: Path
    content_hash: str
    size_bytes: int
    media_type: str


@dataclass(frozen=True)
class DocumentState:
    id: str
    path: str
    content_hash: str


@dataclass(frozen=True)
class SourceDiff:
    new: tuple[ScannedDocument, ...] = ()
    changed: tuple[ScannedDocument, ...] = ()
    deleted: tuple[DocumentState, ...] = ()
    unchanged: tuple[ScannedDocument, ...] = ()


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


@dataclass(frozen=True)
class StoreStatus:
    documents: int
    chunks: int
    last_sync_at: datetime | None
    last_sync_status: str | None
