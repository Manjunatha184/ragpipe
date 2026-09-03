from collections.abc import Sequence
from typing import Any

from ragpipe.embedding.base import EmbeddingProvider


class LocalSentenceTransformerProvider(EmbeddingProvider):
    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        expected_dimension: int = 384,
    ) -> None:
        self._model_name = model_name
        self._expected_dimension = expected_dimension
        self._model: Any | None = None

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "Install local embeddings with: pip install 'ragpipe[local]'"
                ) from exc

            self._model = SentenceTransformer(self._model_name)

            actual_dimension = int(self._model.get_embedding_dimension())
            if actual_dimension != self._expected_dimension:
                raise ValueError(
                    f"Model dimension {actual_dimension} does not match "
                    f"configured dimension {self._expected_dimension}"
                )

        return self._model

    @property
    def dimension(self) -> int:
        return self._expected_dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        model = self._load_model()
        values = model.encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [list(map(float, row)) for row in values]
