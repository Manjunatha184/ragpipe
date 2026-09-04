from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ragpipe.embedding.base import EmbeddingProvider
from ragpipe.store.base import Store


class EvaluationDatasetError(ValueError):
    """Raised when an evaluation dataset is invalid."""


@dataclass(frozen=True)
class EvaluationCase:
    query: str
    expected_document: str


@dataclass(frozen=True)
class EvaluationCaseResult:
    query: str
    expected_document: str
    retrieved_documents: tuple[str, ...]
    rank: int | None
    reciprocal_rank: float
    hit: bool


@dataclass(frozen=True)
class EvaluationReport:
    k: int
    total_cases: int
    hits: int
    hit_rate_at_k: float
    mean_reciprocal_rank_at_k: float
    cases: tuple[EvaluationCaseResult, ...]


def load_evaluation_cases(path: Path) -> tuple[EvaluationCase, ...]:
    """Load and validate query/document expectations from JSONL."""

    cases: list[EvaluationCase] = []

    try:
        with path.open(encoding="utf-8") as dataset:
            for line_number, raw_line in enumerate(dataset, start=1):
                line = raw_line.strip()

                if not line:
                    continue

                try:
                    payload: Any = json.loads(line)
                except json.JSONDecodeError as error:
                    raise EvaluationDatasetError(
                        f"Evaluation dataset line {line_number} is not valid JSON."
                    ) from error

                if not isinstance(payload, dict):
                    raise EvaluationDatasetError(
                        f"Evaluation dataset line {line_number} must be a JSON object."
                    )

                query = payload.get("query")
                expected_document = payload.get("expected_document")

                if not isinstance(query, str) or not query.strip():
                    raise EvaluationDatasetError(
                        f"Evaluation dataset line {line_number} has an invalid query."
                    )

                if not isinstance(expected_document, str) or not expected_document.strip():
                    raise EvaluationDatasetError(
                        f"Evaluation dataset line {line_number} has an invalid expected_document."
                    )

                cases.append(
                    EvaluationCase(
                        query=query.strip(),
                        expected_document=expected_document.strip(),
                    )
                )

    except OSError as error:
        raise EvaluationDatasetError(f"Could not read evaluation dataset: {error}") from error
    except UnicodeError as error:
        raise EvaluationDatasetError("Evaluation dataset must be valid UTF-8.") from error

    if not cases:
        raise EvaluationDatasetError("Evaluation dataset must contain at least one case.")

    return tuple(cases)


class RetrievalEvaluator:
    def __init__(
        self,
        store: Store,
        embedder: EmbeddingProvider,
        batch_size: int = 64,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("Evaluation batch size must be greater than zero")

        self.store = store
        self.embedder = embedder
        self.batch_size = batch_size

    def evaluate(
        self,
        cases: Sequence[EvaluationCase],
        k: int,
    ) -> EvaluationReport:
        if not cases:
            raise ValueError("At least one evaluation case is required")

        if k <= 0 or k > 100:
            raise ValueError("Evaluation k must be between 1 and 100")

        embeddings: list[list[float]] = []

        for start in range(0, len(cases), self.batch_size):
            batch = cases[start : start + self.batch_size]
            batch_embeddings = self.embedder.embed([case.query for case in batch])

            if len(batch_embeddings) != len(batch):
                raise RuntimeError("Embedding provider returned an unexpected number of vectors")

            embeddings.extend(batch_embeddings)

        case_results: list[EvaluationCaseResult] = []
        hits = 0
        reciprocal_rank_sum = 0.0

        for case, embedding in zip(cases, embeddings, strict=True):
            search_results = self.store.search(
                query_embedding=embedding,
                model_name=self.embedder.model_name,
                limit=k,
            )

            retrieved_documents = tuple(result.document_path for result in search_results)

            try:
                rank: int | None = retrieved_documents.index(case.expected_document) + 1
            except ValueError:
                rank = None

            hit = rank is not None
            reciprocal_rank = 0.0 if rank is None else 1.0 / rank

            if hit:
                hits += 1

            reciprocal_rank_sum += reciprocal_rank

            case_results.append(
                EvaluationCaseResult(
                    query=case.query,
                    expected_document=case.expected_document,
                    retrieved_documents=retrieved_documents,
                    rank=rank,
                    reciprocal_rank=reciprocal_rank,
                    hit=hit,
                )
            )

        total_cases = len(cases)

        return EvaluationReport(
            k=k,
            total_cases=total_cases,
            hits=hits,
            hit_rate_at_k=hits / total_cases,
            mean_reciprocal_rank_at_k=(reciprocal_rank_sum / total_cases),
            cases=tuple(case_results),
        )
