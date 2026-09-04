from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import CliRunner

import ragpipe.cli as cli
from ragpipe.config import Settings
from ragpipe.store.pgvector_store import SchemaNotReadyError

runner = CliRunner()


class MetricsStore:
    def __init__(self) -> None:
        self.snapshot = object()
        self.closed = False

    def operational_metrics(self) -> Any:
        return self.snapshot

    def close(self) -> None:
        self.closed = True


class FailingMetricsStore(MetricsStore):
    def operational_metrics(self) -> Any:
        raise RuntimeError("Could not collect metrics")


def test_metrics_prints_snapshot_and_closes_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MetricsStore()

    monkeypatch.setattr(cli, "make_store", lambda settings: store)

    def render(snapshot: Any) -> str:
        assert snapshot is store.snapshot
        return "# TYPE ragpipe_documents gauge\nragpipe_documents 2\n"

    monkeypatch.setattr(cli, "render_prometheus_metrics", render)

    result = runner.invoke(cli.app, ["metrics"])

    assert result.exit_code == 0
    assert result.stdout == ("# TYPE ragpipe_documents gauge\nragpipe_documents 2\n")
    assert store.closed is True


def test_metrics_failure_returns_structured_error_and_closes_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FailingMetricsStore()
    monkeypatch.setattr(cli, "make_store", lambda settings: store)

    result = runner.invoke(cli.app, ["metrics"])

    assert result.exit_code == 1
    assert json.loads(result.stderr) == {
        "status": "metrics_failed",
        "error": "RuntimeError: Could not collect metrics",
    }
    assert store.closed is True


def test_metrics_schema_error_returns_exit_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_schema_error(settings: Settings) -> MetricsStore:
        raise SchemaNotReadyError("Run `alembic upgrade head`.")

    monkeypatch.setattr(cli, "make_store", raise_schema_error)

    result = runner.invoke(cli.app, ["metrics"])

    assert result.exit_code == 2
    assert json.loads(result.stderr) == {
        "status": "schema_error",
        "error": "Run `alembic upgrade head`.",
    }


def test_serve_metrics_forwards_host_port_and_closes_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MetricsStore()
    calls: list[tuple[str, int]] = []

    monkeypatch.setattr(cli, "make_store", lambda settings: store)

    def serve(
        snapshot_provider: Callable[[], Any],
        host: str,
        port: int,
    ) -> None:
        assert snapshot_provider() is store.snapshot
        calls.append((host, port))

    monkeypatch.setattr(cli, "serve_prometheus_metrics", serve)

    result = runner.invoke(
        cli.app,
        [
            "serve-metrics",
            "--host",
            "0.0.0.0",
            "--port",
            "9500",
        ],
    )

    assert result.exit_code == 0
    assert calls == [("0.0.0.0", 9500)]
    assert "http://0.0.0.0:9500/metrics" in result.stdout
    assert store.closed is True


def test_serve_metrics_failure_is_structured_and_closes_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MetricsStore()
    monkeypatch.setattr(cli, "make_store", lambda settings: store)

    def fail_to_serve(
        snapshot_provider: Callable[[], Any],
        host: str,
        port: int,
    ) -> None:
        raise OSError("Address already in use")

    monkeypatch.setattr(cli, "serve_prometheus_metrics", fail_to_serve)

    result = runner.invoke(cli.app, ["serve-metrics"])

    assert result.exit_code == 1
    assert json.loads(result.stderr) == {
        "status": "metrics_server_failed",
        "error": "OSError: Address already in use",
    }
    assert store.closed is True


def test_serve_metrics_rejects_invalid_port_before_opening_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_store_creation(settings: Settings) -> MetricsStore:
        raise AssertionError("Store must not be opened for an invalid port")

    monkeypatch.setattr(cli, "make_store", unexpected_store_creation)

    result = runner.invoke(
        cli.app,
        ["serve-metrics", "--port", "70000"],
    )

    assert result.exit_code == 2
    assert "70000" in result.output
    assert "65535" in result.output
