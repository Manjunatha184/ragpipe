from pathlib import Path

import pytest

from ragpipe.ingest.source import LocalFolderSource
from ragpipe.ingest.source_scanner import SourceError
from ragpipe.models import ScannedDocument


def test_local_folder_source_scans_and_loads_document(
    tmp_path: Path,
) -> None:
    document = tmp_path / "nested" / "guide.md"
    document.parent.mkdir()
    document.write_text(
        "# Guide\n\nSource abstraction content.",
        encoding="utf-8",
    )

    source = LocalFolderSource(tmp_path)
    scanned = source.scan()

    assert source.label == str(tmp_path.resolve())
    assert list(scanned) == ["nested/guide.md"]

    item = scanned["nested/guide.md"]

    assert item.path == "nested/guide.md"
    assert source.load(item) == "# Guide\n\nSource abstraction content."


def test_local_folder_source_rejects_missing_directory(
    tmp_path: Path,
) -> None:
    source = LocalFolderSource(tmp_path / "missing")

    with pytest.raises(
        SourceError,
        match="Source directory does not exist",
    ):
        source.scan()


def test_local_folder_source_rejects_path_outside_root(
    tmp_path: Path,
) -> None:
    source = LocalFolderSource(tmp_path)
    document = ScannedDocument(
        path="../outside.txt",
        content_hash="0" * 64,
        size_bytes=0,
        media_type="text/plain",
    )

    with pytest.raises(
        SourceError,
        match="Document path escapes source root",
    ):
        source.load(document)
