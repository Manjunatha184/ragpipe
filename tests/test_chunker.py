import pytest

from ragpipe.chunking.chunker import RecursiveCharacterChunker


def test_empty_and_tiny_documents() -> None:
    chunker = RecursiveCharacterChunker(20, 5)
    assert chunker.chunk("") == []
    chunks = chunker.chunk("tiny")
    assert len(chunks) == 1 and chunks[0].text == "tiny" and len(chunks[0].content_hash) == 64


def test_large_text_is_split_with_stable_indexes() -> None:
    chunks = RecursiveCharacterChunker(30, 5).chunk("paragraph one. " * 12)
    assert len(chunks) > 1
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(len(c.text) <= 35 for c in chunks)


@pytest.mark.parametrize("size,overlap", [(0, 0), (10, -1), (10, 10), (10, 11)])
def test_invalid_configuration(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        RecursiveCharacterChunker(size, overlap)
