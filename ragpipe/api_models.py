from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"
    version: str


class SyncRequest(ApiModel):
    source: str = Field(min_length=1, max_length=2048)

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Source must not be blank")
        return normalized


class SyncResponse(ApiModel):
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
    metadata_changed_documents: int
    scanned_documents: int
    scanned_bytes: int
    embedding_batches: int
    embedding_duration_ms: float


class SearchRequest(ApiModel):
    query: str = Field(min_length=1, max_length=10_000)
    limit: int = Field(default=5, ge=1, le=100)
    metadata_filter: dict[str, Any] | None = None

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Query must not be blank")
        return normalized


class SearchResultResponse(ApiModel):
    document_path: str
    chunk_index: int
    content: str
    metadata: dict[str, Any]
    embedding_model: str
    score: float


class SearchResponse(ApiModel):
    query: str
    metadata_filter: dict[str, Any] | None
    embedding_model: str
    count: int
    results: list[SearchResultResponse]


class SyncRunResponse(ApiModel):
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


class RunsResponse(ApiModel):
    limit: int
    count: int
    runs: list[SyncRunResponse]


class StatusResponse(ApiModel):
    documents: int
    chunks: int
    last_sync_at: datetime | None
    last_sync_status: str | None


class OperationalMetricsResponse(ApiModel):
    documents: int
    chunks: int
    sync_runs_running: int
    sync_runs_succeeded: int
    sync_runs_failed: int
    new_documents_total: int
    changed_documents_total: int
    metadata_changed_documents_total: int
    deleted_documents_total: int
    unchanged_documents_total: int
    embedded_chunks_total: int
    deleted_chunks_total: int
    scanned_documents_total: int
    scanned_bytes_total: int
    embedding_batches_total: int
    embedding_duration_ms_total: float
    last_sync_status: str | None
    last_sync_at: datetime | None
    last_sync_duration_ms: float | None
