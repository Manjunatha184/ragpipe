from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import ragpipe.cli as cli
from ragpipe.config import Settings
from ragpipe.pipeline import (
    SyncAlreadyRunningError,
    SyncFailedError,
)
from ragpipe.store.pgvector_store import SchemaNotReadyError

runner = CliRunner()


class ClosingStore:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FailingPipeline:
    def __init__(self, **kwargs: Any) -> None:
        pass

    def sync(self, source: Path) -> None:
        raise SyncFailedError(
            run_id="test-run-id",
            safe_message="Embedding service unavailable",
        )


class BusyPipeline:
    def __init__(self, **kwargs: Any) -> None:
        pass

    def sync(self, source: Path) -> None:
        raise SyncAlreadyRunningError()


def test_sync_failure_returns_structured_error_and_exit_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ClosingStore()

    monkeypatch.setattr(
        cli,
        "make_store",
        lambda settings: store,
    )
    monkeypatch.setattr(
        cli,
        "SyncPipeline",
        FailingPipeline,
    )

    result = runner.invoke(
        cli.app,
        [
            "sync",
            "--source",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1

    payload = json.loads(result.stderr)

    assert payload == {
        "status": "failed",
        "run_id": "test-run-id",
        "error": "Embedding service unavailable",
    }
    assert store.closed is True


def test_sync_contention_returns_structured_error_and_exit_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ClosingStore()

    monkeypatch.setattr(
        cli,
        "make_store",
        lambda settings: store,
    )
    monkeypatch.setattr(
        cli,
        "SyncPipeline",
        BusyPipeline,
    )

    result = runner.invoke(
        cli.app,
        [
            "sync",
            "--source",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 3

    payload = json.loads(result.stderr)

    assert payload == {
        "status": "busy",
        "error": "Another synchronization is already running for this store.",
    }
    assert store.closed is True


def test_status_schema_error_returns_exit_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_schema_error(settings: Settings) -> ClosingStore:
        raise SchemaNotReadyError("Run `alembic upgrade head`.")

    monkeypatch.setattr(
        cli,
        "make_store",
        raise_schema_error,
    )

    result = runner.invoke(
        cli.app,
        ["status"],
    )

    assert result.exit_code == 2

    payload = json.loads(result.stderr)

    assert payload == {
        "status": "schema_error",
        "error": "Run `alembic upgrade head`.",
    }


def test_make_store_closes_pool_when_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_stores: list[Any] = []

    class BrokenPgVectorStore:
        def __init__(self, database_url: str) -> None:
            self.database_url = database_url
            self.closed = False
            created_stores.append(self)

        def initialize(self, dimension: int) -> None:
            raise SchemaNotReadyError("Schema is missing")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(
        cli,
        "PgVectorStore",
        BrokenPgVectorStore,
    )

    settings = Settings(database_url=("postgresql://ragpipe@localhost:5432/ragpipe_test"))

    with pytest.raises(
        SchemaNotReadyError,
        match="Schema is missing",
    ):
        cli.make_store(settings)

    assert len(created_stores) == 1
    assert created_stores[0].closed is True
