from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from ragpipe.metrics import (
    PROMETHEUS_CONTENT_TYPE,
    PrometheusMetricsApplication,
    render_prometheus_metrics,
)
from ragpipe.models import OperationalMetricsSnapshot


def make_snapshot(
    *,
    last_sync_status: str | None = "succeeded",
    last_sync_at: datetime | None = None,
    last_sync_duration_ms: float | None = 250.0,
) -> OperationalMetricsSnapshot:
    return OperationalMetricsSnapshot(
        documents=3,
        chunks=12,
        sync_runs_running=0,
        sync_runs_succeeded=4,
        sync_runs_failed=1,
        new_documents_total=5,
        changed_documents_total=6,
        metadata_changed_documents_total=7,
        deleted_documents_total=8,
        unchanged_documents_total=9,
        embedded_chunks_total=10,
        deleted_chunks_total=11,
        scanned_documents_total=20,
        scanned_bytes_total=4096,
        embedding_batches_total=2,
        embedding_duration_ms_total=1500.0,
        last_sync_status=last_sync_status,
        last_sync_at=(
            last_sync_at if last_sync_at is not None else datetime(2026, 9, 4, 13, 30, tzinfo=UTC)
        ),
        last_sync_duration_ms=last_sync_duration_ms,
    )


def call_application(
    application: PrometheusMetricsApplication,
    path: str,
    method: str = "GET",
) -> tuple[str, dict[str, str], bytes]:
    captured_status = ""
    captured_headers: dict[str, str] = {}

    def start_response(
        status: str,
        headers: list[tuple[str, str]],
        exc_info: Any = None,
    ) -> None:
        nonlocal captured_status, captured_headers
        captured_status = status
        captured_headers = dict(headers)

    payload = b"".join(
        application(
            {
                "PATH_INFO": path,
                "REQUEST_METHOD": method,
            },
            start_response,
        )
    )

    return captured_status, captured_headers, payload


def test_renders_prometheus_metrics_without_high_cardinality_labels() -> None:
    rendered = render_prometheus_metrics(make_snapshot())

    assert "# TYPE ragpipe_documents gauge" in rendered
    assert "ragpipe_documents 3" in rendered
    assert 'ragpipe_sync_runs_total{status="succeeded"} 4' in rendered
    assert 'ragpipe_sync_runs_total{status="failed"} 1' in rendered
    assert 'ragpipe_document_changes_total{change="metadata"} 7' in rendered
    assert "ragpipe_scanned_bytes_total 4096" in rendered
    assert "ragpipe_embedding_duration_seconds_total 1.5" in rendered
    assert "ragpipe_last_sync_duration_seconds 0.25" in rendered
    assert "ragpipe_last_sync_timestamp_seconds 1788528600.0" in rendered
    assert "run_id" not in rendered
    assert "source=" not in rendered


def test_metrics_without_run_omit_latest_time_samples() -> None:
    snapshot = make_snapshot(
        last_sync_status=None,
        last_sync_duration_ms=None,
    )
    snapshot = replace(snapshot, last_sync_at=None)

    rendered = render_prometheus_metrics(snapshot)

    assert "ragpipe_last_sync_timestamp_seconds" not in rendered
    assert "ragpipe_last_sync_duration_seconds" not in rendered
    assert 'ragpipe_last_sync_status{status="succeeded"} 0' in rendered
    assert 'ragpipe_last_sync_status{status="failed"} 0' in rendered


def test_metrics_application_returns_prometheus_response() -> None:
    application = PrometheusMetricsApplication(make_snapshot)

    status, headers, payload = call_application(
        application,
        "/metrics",
    )

    assert status == "200 OK"
    assert headers["Content-Type"] == PROMETHEUS_CONTENT_TYPE
    assert headers["Content-Length"] == str(len(payload))
    assert b"ragpipe_documents 3" in payload


def test_metrics_application_returns_not_found_without_querying_store() -> None:
    queried = False

    def unexpected_provider() -> OperationalMetricsSnapshot:
        nonlocal queried
        queried = True
        raise AssertionError("Provider must not be called")

    application = PrometheusMetricsApplication(unexpected_provider)

    status, _, payload = call_application(
        application,
        "/",
    )

    assert status == "404 Not Found"
    assert payload == b"not found\n"
    assert queried is False


def test_metrics_application_hides_collection_errors() -> None:
    def failing_provider() -> OperationalMetricsSnapshot:
        raise RuntimeError("postgresql://user:secret@database/ragpipe")

    application = PrometheusMetricsApplication(failing_provider)

    status, _, payload = call_application(
        application,
        "/metrics",
    )

    assert status == "500 Internal Server Error"
    assert payload == b"metrics collection failed\n"
    assert b"secret" not in payload
