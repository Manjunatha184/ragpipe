from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from wsgiref.simple_server import make_server

from ragpipe.models import OperationalMetricsSnapshot

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

SnapshotProvider = Callable[[], OperationalMetricsSnapshot]
StartResponse = Callable[..., Any]


def _metric(
    lines: list[str],
    name: str,
    help_text: str,
    metric_type: str,
    samples: list[tuple[str, int | float]],
) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} {metric_type}")

    for suffix, value in samples:
        lines.append(f"{name}{suffix} {value}")


def render_prometheus_metrics(
    snapshot: OperationalMetricsSnapshot,
) -> str:
    """Render a snapshot in Prometheus text exposition format."""

    lines: list[str] = []

    _metric(
        lines,
        "ragpipe_documents",
        "Current number of synchronized documents.",
        "gauge",
        [("", snapshot.documents)],
    )
    _metric(
        lines,
        "ragpipe_chunks",
        "Current number of stored chunks.",
        "gauge",
        [("", snapshot.chunks)],
    )
    _metric(
        lines,
        "ragpipe_sync_runs_total",
        "Persisted synchronization runs by final status.",
        "counter",
        [
            ('{status="running"}', snapshot.sync_runs_running),
            ('{status="succeeded"}', snapshot.sync_runs_succeeded),
            ('{status="failed"}', snapshot.sync_runs_failed),
        ],
    )
    _metric(
        lines,
        "ragpipe_document_changes_total",
        "Documents observed by synchronization change category.",
        "counter",
        [
            ('{change="new"}', snapshot.new_documents_total),
            ('{change="content"}', snapshot.changed_documents_total),
            (
                '{change="metadata"}',
                snapshot.metadata_changed_documents_total,
            ),
            ('{change="deleted"}', snapshot.deleted_documents_total),
            ('{change="unchanged"}', snapshot.unchanged_documents_total),
        ],
    )
    _metric(
        lines,
        "ragpipe_embedded_chunks_total",
        "Chunks successfully committed with embeddings.",
        "counter",
        [("", snapshot.embedded_chunks_total)],
    )
    _metric(
        lines,
        "ragpipe_deleted_chunks_total",
        "Chunks deleted by successful synchronizations.",
        "counter",
        [("", snapshot.deleted_chunks_total)],
    )
    _metric(
        lines,
        "ragpipe_scanned_documents_total",
        "Documents scanned across persisted synchronization runs.",
        "counter",
        [("", snapshot.scanned_documents_total)],
    )
    _metric(
        lines,
        "ragpipe_scanned_bytes_total",
        "Document bytes scanned across persisted synchronization runs.",
        "counter",
        [("", snapshot.scanned_bytes_total)],
    )
    _metric(
        lines,
        "ragpipe_embedding_batches_total",
        "Embedding batches attempted across synchronization runs.",
        "counter",
        [("", snapshot.embedding_batches_total)],
    )
    _metric(
        lines,
        "ragpipe_embedding_duration_seconds_total",
        "Cumulative time spent in attempted embedding calls.",
        "counter",
        [("", snapshot.embedding_duration_ms_total / 1000)],
    )
    _metric(
        lines,
        "ragpipe_last_sync_status",
        "Whether the latest synchronization has each status.",
        "gauge",
        [
            (
                '{status="running"}',
                int(snapshot.last_sync_status == "running"),
            ),
            (
                '{status="succeeded"}',
                int(snapshot.last_sync_status == "succeeded"),
            ),
            (
                '{status="failed"}',
                int(snapshot.last_sync_status == "failed"),
            ),
        ],
    )

    if snapshot.last_sync_at is not None:
        _metric(
            lines,
            "ragpipe_last_sync_timestamp_seconds",
            "Unix timestamp when the latest synchronization finished.",
            "gauge",
            [("", snapshot.last_sync_at.timestamp())],
        )

    if snapshot.last_sync_duration_ms is not None:
        _metric(
            lines,
            "ragpipe_last_sync_duration_seconds",
            "Duration of the latest synchronization.",
            "gauge",
            [("", snapshot.last_sync_duration_ms / 1000)],
        )

    return "\n".join(lines) + "\n"


class PrometheusMetricsApplication:
    """Minimal WSGI application exposing a live `/metrics` endpoint."""

    def __init__(
        self,
        snapshot_provider: SnapshotProvider,
    ) -> None:
        self.snapshot_provider = snapshot_provider

    def __call__(
        self,
        environ: Mapping[str, Any],
        start_response: StartResponse,
    ) -> list[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET"))
        path = str(environ.get("PATH_INFO", ""))

        if method != "GET" or path != "/metrics":
            payload = b"not found\n"
            start_response(
                "404 Not Found",
                [
                    ("Content-Type", "text/plain; charset=utf-8"),
                    ("Content-Length", str(len(payload))),
                ],
            )

            return [payload]

        try:
            payload = render_prometheus_metrics(self.snapshot_provider()).encode("utf-8")
        except Exception:
            # Do not expose database errors or credentials to HTTP clients.
            payload = b"metrics collection failed\n"
            start_response(
                "500 Internal Server Error",
                [
                    ("Content-Type", "text/plain; charset=utf-8"),
                    ("Content-Length", str(len(payload))),
                ],
            )

            return [payload]

        start_response(
            "200 OK",
            [
                ("Content-Type", PROMETHEUS_CONTENT_TYPE),
                ("Content-Length", str(len(payload))),
            ],
        )

        return [payload]


def serve_prometheus_metrics(
    snapshot_provider: SnapshotProvider,
    host: str,
    port: int,
) -> None:
    """Serve live Prometheus metrics until the process is interrupted."""

    application = PrometheusMetricsApplication(snapshot_provider)

    with make_server(
        host,
        port,
        application,
    ) as server:
        server.serve_forever()
