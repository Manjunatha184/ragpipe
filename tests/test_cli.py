from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import ragpipe.cli as cli
from ragpipe.config import Settings
from ragpipe.ingest.source import DocumentSource
from ragpipe.models import SearchResult, SyncRunRecord
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

    def sync(self, source: DocumentSource) -> None:
        raise SyncFailedError(
            run_id="test-run-id",
            safe_message="Embedding service unavailable",
        )


class BusyPipeline:
    def __init__(self, **kwargs: Any) -> None:
        pass

    def sync(self, source: DocumentSource) -> None:
        raise SyncAlreadyRunningError()


class SearchStore(ClosingStore):
    def __init__(self) -> None:
        super().__init__()
        self.search_call: tuple[list[float], str, int, Mapping[str, Any] | None] | None = None

    def search(
        self,
        query_embedding: list[float],
        model_name: str,
        limit: int,
        metadata_filter: Mapping[str, Any] | None = None,
    ) -> list[SearchResult]:
        self.search_call = (
            query_embedding,
            model_name,
            limit,
            metadata_filter,
        )

        return [
            SearchResult(
                document_path="guide.md",
                chunk_index=2,
                content="Ragpipe keeps vectors synchronized.",
                metadata={"section": "overview"},
                embedding_model=model_name,
                score=0.95,
            )
        ]


class RunHistoryStore(ClosingStore):
    def __init__(self) -> None:
        super().__init__()
        self.requested_limit: int | None = None

    def recent_runs(self, limit: int) -> list[SyncRunRecord]:
        self.requested_limit = limit

        started = datetime(
            2026,
            9,
            4,
            9,
            30,
            tzinfo=UTC,
        )
        finished = started + timedelta(milliseconds=125)

        return [
            SyncRunRecord(
                run_id="test-run-id",
                source="/data/documents",
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
                embedding_duration_ms=75.5,
                started_at=started,
                finished_at=finished,
                duration_ms=125.0,
                error=None,
            )
        ]


class FailingRunHistoryStore(ClosingStore):
    def recent_runs(self, limit: int) -> list[SyncRunRecord]:
        raise RuntimeError("Could not load run history")


class FakeSearchEmbedder:
    def __init__(
        self,
        model_name: str,
        expected_dimension: int,
    ) -> None:
        self.model_name = model_name
        self.expected_dimension = expected_dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        assert texts == ["What is Ragpipe?"]
        return [[1.0, 0.0, 0.0]]


class FailingSearchEmbedder(FakeSearchEmbedder):
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("Query embedding failed")


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


def test_search_returns_structured_results_and_closes_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SearchStore()

    monkeypatch.setattr(
        cli,
        "make_store",
        lambda settings: store,
    )
    monkeypatch.setattr(
        cli,
        "LocalSentenceTransformerProvider",
        FakeSearchEmbedder,
    )

    result = runner.invoke(
        cli.app,
        [
            "search",
            "--query",
            "What is Ragpipe?",
            "--limit",
            "3",
        ],
    )

    assert result.exit_code == 0

    payload = json.loads(result.stdout)

    assert payload["query"] == "What is Ragpipe?"
    assert payload["count"] == 1
    assert payload["results"] == [
        {
            "document_path": "guide.md",
            "chunk_index": 2,
            "content": "Ragpipe keeps vectors synchronized.",
            "metadata": {"section": "overview"},
            "embedding_model": payload["embedding_model"],
            "score": 0.95,
        }
    ]

    assert store.search_call == (
        [1.0, 0.0, 0.0],
        payload["embedding_model"],
        3,
        None,
    )
    assert store.closed is True


def test_search_failure_returns_structured_error_and_closes_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SearchStore()

    monkeypatch.setattr(
        cli,
        "make_store",
        lambda settings: store,
    )
    monkeypatch.setattr(
        cli,
        "LocalSentenceTransformerProvider",
        FailingSearchEmbedder,
    )

    result = runner.invoke(
        cli.app,
        [
            "search",
            "--query",
            "What is Ragpipe?",
        ],
    )

    assert result.exit_code == 1

    payload = json.loads(result.stderr)

    assert payload == {
        "status": "search_failed",
        "error": "RuntimeError: Query embedding failed",
    }
    assert store.closed is True


def test_search_rejects_blank_query() -> None:
    result = runner.invoke(
        cli.app,
        [
            "search",
            "--query",
            "   ",
        ],
    )

    assert result.exit_code == 2
    assert "Query must not be empty" in result.output


def test_evaluate_returns_metrics_and_closes_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "evaluation.jsonl"
    dataset.write_text(
        '{"query": "What is Ragpipe?", "expected_document": "guide.md"}\n',
        encoding="utf-8",
    )

    store = SearchStore()

    monkeypatch.setattr(
        cli,
        "make_store",
        lambda settings: store,
    )
    monkeypatch.setattr(
        cli,
        "LocalSentenceTransformerProvider",
        FakeSearchEmbedder,
    )

    result = runner.invoke(
        cli.app,
        [
            "evaluate",
            "--dataset",
            str(dataset),
            "--k",
            "3",
        ],
    )

    assert result.exit_code == 0

    payload = json.loads(result.stdout)

    assert payload["dataset"] == str(dataset.resolve())
    assert payload["k"] == 3
    assert payload["total_cases"] == 1
    assert payload["hits"] == 1
    assert payload["hit_rate_at_k"] == 1.0
    assert payload["mean_reciprocal_rank_at_k"] == 1.0
    assert payload["cases"] == [
        {
            "query": "What is Ragpipe?",
            "expected_document": "guide.md",
            "retrieved_documents": ["guide.md"],
            "rank": 1,
            "reciprocal_rank": 1.0,
            "hit": True,
        }
    ]
    assert store.closed is True


def test_evaluate_rejects_invalid_dataset_before_opening_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "invalid.jsonl"
    dataset.write_text(
        "not-json\n",
        encoding="utf-8",
    )

    def unexpected_store_creation(settings: Settings) -> ClosingStore:
        raise AssertionError("Store must not be created for invalid data")

    monkeypatch.setattr(
        cli,
        "make_store",
        unexpected_store_creation,
    )

    result = runner.invoke(
        cli.app,
        [
            "evaluate",
            "--dataset",
            str(dataset),
        ],
    )

    assert result.exit_code == 4

    payload = json.loads(result.stderr)

    assert payload["status"] == "invalid_dataset"
    assert "line 1 is not valid JSON" in payload["error"]


def test_evaluate_failure_returns_structured_error_and_closes_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "evaluation.jsonl"
    dataset.write_text(
        '{"query": "What is Ragpipe?", "expected_document": "guide.md"}\n',
        encoding="utf-8",
    )

    store = SearchStore()

    monkeypatch.setattr(
        cli,
        "make_store",
        lambda settings: store,
    )
    monkeypatch.setattr(
        cli,
        "LocalSentenceTransformerProvider",
        FailingSearchEmbedder,
    )

    result = runner.invoke(
        cli.app,
        [
            "evaluate",
            "--dataset",
            str(dataset),
        ],
    )

    assert result.exit_code == 1

    payload = json.loads(result.stderr)

    assert payload == {
        "status": "evaluation_failed",
        "error": "RuntimeError: Query embedding failed",
    }
    assert store.closed is True


def test_search_forwards_metadata_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SearchStore()

    monkeypatch.setattr(
        cli,
        "make_store",
        lambda settings: store,
    )
    monkeypatch.setattr(
        cli,
        "LocalSentenceTransformerProvider",
        FakeSearchEmbedder,
    )

    result = runner.invoke(
        cli.app,
        [
            "search",
            "--query",
            "What is Ragpipe?",
            "--limit",
            "3",
            "--metadata",
            '{"department":"hr","tags":["policy"]}',
        ],
    )

    assert result.exit_code == 0

    payload = json.loads(result.stdout)

    expected_filter = {
        "department": "hr",
        "tags": ["policy"],
    }

    assert payload["metadata_filter"] == expected_filter
    assert store.search_call == (
        [1.0, 0.0, 0.0],
        payload["embedding_model"],
        3,
        expected_filter,
    )
    assert store.closed is True


@pytest.mark.parametrize(
    ("metadata", "expected_message"),
    [
        ('{"department":', "Metadata filter must be valid JSON"),
        ('["hr"]', "Metadata filter must be a JSON object"),
        ('"hr"', "Metadata filter must be a JSON object"),
        ("NaN", "Metadata filter must be valid JSON"),
    ],
)
def test_search_rejects_invalid_metadata_before_opening_store(
    metadata: str,
    expected_message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_store_creation(settings: Settings) -> ClosingStore:
        raise AssertionError("Store must not be opened for invalid metadata")

    class UnexpectedEmbedder:
        def __init__(self, **kwargs: Any) -> None:
            raise AssertionError("Embedder must not be loaded for invalid metadata")

    monkeypatch.setattr(
        cli,
        "make_store",
        unexpected_store_creation,
    )
    monkeypatch.setattr(
        cli,
        "LocalSentenceTransformerProvider",
        UnexpectedEmbedder,
    )

    result = runner.invoke(
        cli.app,
        [
            "search",
            "--query",
            "What is Ragpipe?",
            "--metadata",
            metadata,
        ],
    )

    assert result.exit_code == 2
    assert expected_message in result.output


def test_runs_returns_recent_operational_metrics_and_closes_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = RunHistoryStore()

    monkeypatch.setattr(
        cli,
        "make_store",
        lambda settings: store,
    )

    result = runner.invoke(
        cli.app,
        [
            "runs",
            "--limit",
            "5",
        ],
    )

    assert result.exit_code == 0

    payload = json.loads(result.stdout)

    assert payload["limit"] == 5
    assert payload["count"] == 1
    assert payload["runs"][0]["run_id"] == "test-run-id"
    assert payload["runs"][0]["status"] == "succeeded"
    assert payload["runs"][0]["scanned_documents"] == 3
    assert payload["runs"][0]["scanned_bytes"] == 4096
    assert payload["runs"][0]["embedding_batches"] == 1
    assert payload["runs"][0]["embedding_duration_ms"] == 75.5
    assert payload["runs"][0]["duration_ms"] == 125.0
    assert payload["runs"][0]["error"] is None

    assert store.requested_limit == 5
    assert store.closed is True


def test_runs_failure_returns_structured_error_and_closes_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FailingRunHistoryStore()

    monkeypatch.setattr(
        cli,
        "make_store",
        lambda settings: store,
    )

    result = runner.invoke(
        cli.app,
        [
            "runs",
            "--limit",
            "5",
        ],
    )

    assert result.exit_code == 1

    payload = json.loads(result.stderr)

    assert payload == {
        "status": "run_history_failed",
        "error": "RuntimeError: Could not load run history",
    }
    assert store.closed is True


def test_make_document_source_accepts_local_directory(
    tmp_path: Path,
) -> None:
    source = cli.make_document_source(str(tmp_path))

    assert isinstance(
        source,
        cli.LocalFolderSource,
    )
    assert source.label == str(tmp_path.resolve())


def test_make_document_source_accepts_s3_uri(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_source = cli.LocalFolderSource(tmp_path)
    received: list[str] = []

    def fake_s3_source(uri: str) -> cli.LocalFolderSource:
        received.append(uri)
        return local_source

    monkeypatch.setattr(
        cli,
        "S3DocumentSource",
        fake_s3_source,
    )

    source = cli.make_document_source("s3://documents/knowledge")

    assert source is local_source
    assert received == ["s3://documents/knowledge"]


def test_sync_rejects_missing_local_source_before_opening_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_store_creation(
        settings: Settings,
    ) -> ClosingStore:
        raise AssertionError("Store must not be created for an invalid source")

    monkeypatch.setattr(
        cli,
        "make_store",
        unexpected_store_creation,
    )

    result = runner.invoke(
        cli.app,
        [
            "sync",
            "--source",
            str(tmp_path / "missing"),
        ],
    )

    assert result.exit_code == 2
    assert "Local source directory does not exist" in result.output


def test_sync_rejects_invalid_s3_uri_before_opening_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_store_creation(
        settings: Settings,
    ) -> ClosingStore:
        raise AssertionError("Store must not be created for an invalid source")

    monkeypatch.setattr(
        cli,
        "make_store",
        unexpected_store_creation,
    )

    result = runner.invoke(
        cli.app,
        [
            "sync",
            "--source",
            "s3:///missing-bucket",
        ],
    )

    assert result.exit_code == 2
    assert "Invalid S3 source URI" in result.output
