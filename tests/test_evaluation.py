from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from ragpipe.embedding.base import EmbeddingProvider
from ragpipe.evaluation import (
    EvaluationCase,
    EvaluationDatasetError,
    RetrievalEvaluator,
    load_evaluation_cases,
)
from ragpipe.models import SearchResult
from tests.fakes import MemoryStore


class EvaluationEmbedder(EmbeddingProvider):
    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    @property
    def dimension(self) -> int:
        return 1

    @property
    def model_name(self) -> str:
        return "evaluation-model"

    def embed(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        self.batches.append(list(texts))

        markers = {
            "query one": 1.0,
            "query two": 2.0,
            "query three": 3.0,
        }

        return [[markers[text]] for text in texts]


class EvaluationStore(MemoryStore):
    def search(
        self,
        query_embedding: Sequence[float],
        model_name: str,
        limit: int,
    ) -> list[SearchResult]:
        marker = int(query_embedding[0])

        paths = {
            1: ["document-a.md", "other.md"],
            2: ["other.md", "document-b.md"],
            3: ["other.md"],
        }[marker]

        return [
            SearchResult(
                document_path=path,
                chunk_index=index,
                content=f"Content from {path}",
                metadata={},
                embedding_model=model_name,
                score=1.0 / (index + 1),
            )
            for index, path in enumerate(paths[:limit])
        ]


def test_load_evaluation_cases_accepts_valid_jsonl(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "evaluation.jsonl"
    dataset.write_text(
        "\n".join(
            [
                '{"query": " First query ", "expected_document": " first.md "}',
                "",
                '{"query": "Second query", "expected_document": "second.md", "extra": "allowed"}',
            ]
        ),
        encoding="utf-8",
    )

    cases = load_evaluation_cases(dataset)

    assert cases == (
        EvaluationCase(
            query="First query",
            expected_document="first.md",
        ),
        EvaluationCase(
            query="Second query",
            expected_document="second.md",
        ),
    )


def test_load_evaluation_cases_reports_invalid_json_line(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "evaluation.jsonl"
    dataset.write_text(
        '{"query": "valid", "expected_document": "valid.md"}\nnot-json\n',
        encoding="utf-8",
    )

    with pytest.raises(
        EvaluationDatasetError,
        match="line 2 is not valid JSON",
    ):
        load_evaluation_cases(dataset)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"expected_document": "document.md"},
        {"query": "query", "expected_document": "   "},
    ],
)
def test_load_evaluation_cases_rejects_invalid_fields(
    tmp_path: Path,
    payload: object,
) -> None:
    dataset = tmp_path / "evaluation.jsonl"
    dataset.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(
        EvaluationDatasetError,
        match="line 1",
    ):
        load_evaluation_cases(dataset)


def test_load_evaluation_cases_rejects_empty_dataset(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "evaluation.jsonl"
    dataset.write_text("\n", encoding="utf-8")

    with pytest.raises(
        EvaluationDatasetError,
        match="at least one case",
    ):
        load_evaluation_cases(dataset)


def test_retrieval_evaluator_calculates_metrics_and_batches() -> None:
    store = EvaluationStore()
    embedder = EvaluationEmbedder()
    evaluator = RetrievalEvaluator(
        store=store,
        embedder=embedder,
        batch_size=2,
    )

    report = evaluator.evaluate(
        cases=[
            EvaluationCase("query one", "document-a.md"),
            EvaluationCase("query two", "document-b.md"),
            EvaluationCase("query three", "missing.md"),
        ],
        k=2,
    )

    assert report.k == 2
    assert report.total_cases == 3
    assert report.hits == 2
    assert report.hit_rate_at_k == pytest.approx(2 / 3)
    assert report.mean_reciprocal_rank_at_k == pytest.approx(0.5)

    assert [case.rank for case in report.cases] == [
        1,
        2,
        None,
    ]
    assert [case.reciprocal_rank for case in report.cases] == [
        1.0,
        0.5,
        0.0,
    ]
    assert embedder.batches == [
        ["query one", "query two"],
        ["query three"],
    ]
