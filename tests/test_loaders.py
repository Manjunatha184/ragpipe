from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter

from ragpipe.ingest.loaders import (
    DocumentLoadError,
    load_bytes,
    load_text,
)


def test_weird_encoding_is_replaced_not_crashed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.txt"
    path.write_bytes(b"hello\xffworld")

    assert load_text(path) == "hello\ufffdworld"


def test_text_can_be_loaded_directly_from_bytes() -> None:
    assert (
        load_bytes(
            b"hello\xffworld",
            "folder/legacy.txt",
        )
        == "hello\ufffdworld"
    )


def test_pdf_can_be_loaded_directly_from_bytes() -> None:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(
        width=200,
        height=200,
    )
    writer.write(buffer)

    assert (
        load_bytes(
            buffer.getvalue(),
            "folder/blank.pdf",
        )
        == ""
    )


def test_invalid_pdf_is_wrapped_as_document_load_error() -> None:
    with pytest.raises(
        DocumentLoadError,
        match=r"Could not read broken\.pdf",
    ):
        load_bytes(
            b"not a valid PDF",
            "folder/broken.pdf",
        )
