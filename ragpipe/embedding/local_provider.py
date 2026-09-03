from collections.abc import Sequence
from typing import Any

from ragpipe.embedding.base import EmbeddingProvider


class LocalSentenceTransformerProvider(EmbeddingProvider):
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Install local embeddings with: pip install 'ragpipe[local]'"
            ) from exc
        self._model: Any = SentenceTransformer(model_name)
        self._model_name = model_name

    @property
    def dimension(self) -> int:
        return int(self._model.get_embedding_dimension())

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        values = self._model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
        return [list(map(float, row)) for row in values]
