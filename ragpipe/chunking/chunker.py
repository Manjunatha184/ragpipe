from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

from ragpipe.models import Chunk


class Chunker(ABC):
    @abstractmethod
    def chunk(self, text: str) -> list[Chunk]: ...


class RecursiveCharacterChunker(Chunker):
    def __init__(
        self,
        chunk_size: int = 800,
        overlap: int = 120,
        separators: tuple[str, ...] = ("\n\n", "\n", ". ", " ", ""),
    ) -> None:
        if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
            raise ValueError("Require chunk_size > overlap >= 0")
        self.chunk_size, self.overlap, self.separators = chunk_size, overlap, separators

    def chunk(self, text: str) -> list[Chunk]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return []
        pieces = self._split(normalized, self.separators)
        merged: list[str] = []
        current = ""
        for piece in pieces:
            candidate = f"{current} {piece}".strip() if current else piece
            if len(candidate) <= self.chunk_size:
                current = candidate
                continue
            if current:
                merged.append(current)
                prefix = current[-self.overlap :] if self.overlap else ""
                current = f"{prefix} {piece}".strip()
            else:
                merged.append(piece[: self.chunk_size])
                current = piece[self.chunk_size - self.overlap :]
        if current:
            merged.append(current)
        return [
            Chunk(i, value, hashlib.sha256(value.encode()).hexdigest(), {"chunk_index": i})
            for i, value in enumerate(merged)
            if value
        ]

    def _split(self, text: str, separators: tuple[str, ...]) -> list[str]:
        if len(text) <= self.chunk_size:
            return [text]
        separator = next((sep for sep in separators if sep and sep in text), "")
        if not separator:
            step = self.chunk_size - self.overlap
            return [text[i : i + self.chunk_size] for i in range(0, len(text), step)]
        parts = [part.strip() for part in text.split(separator) if part.strip()]
        remaining = separators[separators.index(separator) + 1 :]
        output: list[str] = []
        for part in parts:
            output.extend(self._split(part, remaining) if len(part) > self.chunk_size else [part])
        return output
