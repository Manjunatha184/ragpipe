from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from fastapi.testclient import TestClient

from ragpipe import __version__
from ragpipe.api import InvalidApiSourceError, create_app, make_api_document_source
from ragpipe.ingest.source import LocalFolderSource
from ragpipe.models import (
    OperationalMetricsSnapshot,
    SearchResult,
    StoreStatus,
    SyncResult,
    SyncRunRecord,
)
from ragpipe.pipeline import SyncAlreadyRunningError, SyncFailedError
from ragpipe.store.pgvector_store import SchemaNotReadyError


class StubApiService:
    embedding_model = "test-model"

    def __init__(self) -> None:
        self.failure: str | None = None
        self.sync_source: str | None = None
        self.search_call: tuple[str, int, dict[str, object] | None] | None = None
        self.requested_run_limit: int | None = None

    def _raise_if_requested(self, operation: str) -> None:
        if self.failure == operation:
            credential = "".join(("password", "=", "secret"))
            raise RuntimeError(f"{operation} unavailable {credential}")

    def sync(self, source: str) -> SyncResult:
        if self.failure == "invalid_source":
            raise InvalidApiSourceError("Source is not permitted.")
        if self.failure == "busy":
            raise SyncAlreadyRunningError()
        if self.failure == "sync_failed":
            raise SyncFailedError("run-failed", "Embedding failed safely.")
        if self.failure == "schema":
            raise SchemaNotReadyError("missing migration")
        self._raise_if_requested("sync")
        self.sync_source = source
        started = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
        return SyncResult(
            run_id="run-1",
            status="succeeded",
            new_documents=1,
            changed_documents=0,
            deleted_documents=0,
            unchanged_documents=2,
            embedded_chunks=3,
            deleted_chunks=0,
            started_at=started,
            finished_at=started + timedelta(milliseconds=125),
            scanned_documents=3,
            scanned_bytes=4096,
            embedding_batches=1,
            embedding_duration_ms=75.0,
        )

    def search(
        self,
        query: str,
        limit: int,
        metadata_filter: dict[str, object] | None,
    ) -> list[SearchResult]:
        self._raise_if_requested("search")
        self.search_call = (query, limit, metadata_filter)
        return [
            SearchResult(
                document_path="guide.md",
                chunk_index=0,
                content="Ragpipe synchronizes documents.",
                metadata={"department": "engineering"},
                embedding_model=self.embedding_model,
                score=0.97,
            )
        ]

    def recent_runs(self, limit: int) -> list[SyncRunRecord]:
        self._raise_if_requested("runs")
        self.requested_run_limit = limit
        started = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
        return [
            SyncRunRecord(
                run_id="run-1",
                source="sample_docs",
                status="succeeded",
                new_documents=1,
                changed_documents=0,
                metadata_changed_documents=0,
                deleted_documents=0,
                unchanged_documents=2,
                embedded_chunks=3,
                deleted_chunks=0,
                scanned_documents=3,
                scanned_bytes=4096,
                embedding_batches=1,
                embedding_duration_ms=75.0,
                started_at=started,
                finished_at=started + timedelta(milliseconds=125),
                duration_ms=125.0,
                error=None,
            )
        ]

    def status(self) -> StoreStatus:
        self._raise_if_requested("status")
        return StoreStatus(
            documents=3,
            chunks=7,
            last_sync_at=datetime(2026, 9, 7, 8, 0, tzinfo=UTC),
            last_sync_status="succeeded",
        )

    def operational_metrics(self) -> OperationalMetricsSnapshot:
        self._raise_if_requested("metrics")
        return OperationalMetricsSnapshot(
            documents=3,
            chunks=7,
            sync_runs_running=0,
            sync_runs_succeeded=4,
            sync_runs_failed=1,
            new_documents_total=3,
            changed_documents_total=1,
            metadata_changed_documents_total=1,
            deleted_documents_total=0,
            unchanged_documents_total=5,
            embedded_chunks_total=7,
            deleted_chunks_total=0,
            scanned_documents_total=10,
            scanned_bytes_total=8192,
            embedding_batches_total=2,
            embedding_duration_ms_total=150.0,
            last_sync_status="succeeded",
            last_sync_at=datetime(2026, 9, 7, 8, 0, tzinfo=UTC),
            last_sync_duration_ms=125.0,
        )

    def close(self) -> None:
        pass


def test_api_successful_dashboard_flow() -> None:
    service = StubApiService()

    with TestClient(create_app(service)) as client:
        health = client.get("/api/v1/health")
        status = client.get("/api/v1/status")
        runs = client.get("/api/v1/runs", params={"limit": 5})
        metrics = client.get("/api/v1/metrics")
        prometheus = client.get("/metrics")
        search = client.post(
            "/api/v1/search",
            json={
                "query": "  What is Ragpipe?  ",
                "limit": 3,
                "metadata_filter": {"department": "engineering"},
            },
        )
        sync = client.post("/api/v1/sync", json={"source": "  sample_docs  "})

    assert health.status_code == 200
    assert health.json()["version"] == __version__
    assert status.json()["documents"] == 3
    assert runs.json()["count"] == 1
    assert service.requested_run_limit == 5
    assert metrics.json()["sync_runs_succeeded"] == 4
    assert "ragpipe_documents 3" in prometheus.text
    assert search.status_code == 200
    assert search.json()["results"][0]["document_path"] == "guide.md"
    assert service.search_call == (
        "What is Ragpipe?",
        3,
        {"department": "engineering"},
    )
    assert sync.status_code == 200
    assert sync.json()["run_id"] == "run-1"
    assert service.sync_source == "sample_docs"


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code"),
    [
        ("invalid_source", "invalid_source", 400),
        ("busy", "busy", 409),
        ("sync_failed", "failed", 500),
        ("schema", "schema_error", 503),
        ("sync", "failed", 500),
    ],
)
def test_sync_returns_controlled_errors(
    failure: str,
    expected_status: str,
    expected_code: int,
) -> None:
    service = StubApiService()
    service.failure = failure

    with TestClient(create_app(service)) as client:
        response = client.post("/api/v1/sync", json={"source": "sample_docs"})

    assert response.status_code == expected_code
    assert response.json()["status"] == expected_status
    assert "secret" not in response.text


@pytest.mark.parametrize(
    ("operation", "method", "path", "expected_code"),
    [
        ("status", "get", "/api/v1/status", 503),
        ("runs", "get", "/api/v1/runs", 503),
        ("metrics", "get", "/api/v1/metrics", 503),
        ("metrics", "get", "/metrics", 503),
        ("search", "post", "/api/v1/search", 500),
    ],
)
def test_api_hides_internal_collection_errors(
    operation: str,
    method: Literal["get", "post"],
    path: str,
    expected_code: int,
) -> None:
    service = StubApiService()
    service.failure = operation
    payload = {"query": "Ragpipe"} if method == "post" else None

    with TestClient(create_app(service)) as client:
        response = client.request(method, path, json=payload)

    assert response.status_code == expected_code
    assert "secret" not in response.text


def test_api_rejects_invalid_request_values() -> None:
    with TestClient(create_app(StubApiService())) as client:
        blank_query = client.post("/api/v1/search", json={"query": "   "})
        large_limit = client.get("/api/v1/runs", params={"limit": 101})
        extra_field = client.post(
            "/api/v1/sync",
            json={"source": "sample_docs", "unexpected": True},
        )

    assert blank_query.status_code == 422
    assert large_limit.status_code == 422
    assert extra_field.status_code == 422


def test_local_api_source_is_confined_to_allowed_root(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    source_path = root / "documents"
    source_path.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()

    source = make_api_document_source("documents", root)

    assert isinstance(source, LocalFolderSource)

    with pytest.raises(InvalidApiSourceError, match="configured API root"):
        make_api_document_source("../outside", root)


def test_local_api_source_must_be_a_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "document.txt"
    file_path.write_text("document", encoding="utf-8")

    with pytest.raises(InvalidApiSourceError, match="must be a directory"):
        make_api_document_source(str(file_path), tmp_path)
