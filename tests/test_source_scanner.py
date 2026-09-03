import hashlib
from pathlib import Path

import pytest

from ragpipe.ingest.source_scanner import SourceError, diff_source, scan_source
from ragpipe.models import DocumentState


def test_scan_and_all_diff_categories(tmp_path: Path) -> None:
    (tmp_path / "new.md").write_text("new")
    (tmp_path / "changed.txt").write_text("changed now")
    (tmp_path / "same.txt").write_text("same")
    (tmp_path / "ignored.csv").write_text("ignore")
    scanned = scan_source(tmp_path)
    previous = {
        "changed.txt": DocumentState("1", "changed.txt", "old-hash"),
        "same.txt": DocumentState("2", "same.txt", hashlib.sha256(b"same").hexdigest()),
        "deleted.pdf": DocumentState("3", "deleted.pdf", "gone"),
    }
    diff = diff_source(scanned, previous)
    assert [x.path for x in diff.new] == ["new.md"]
    assert [x.path for x in diff.changed] == ["changed.txt"]
    assert [x.path for x in diff.deleted] == ["deleted.pdf"]
    assert [x.path for x in diff.unchanged] == ["same.txt"]
    assert "ignored.csv" not in scanned


def test_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(SourceError):
        scan_source(tmp_path / "missing")


def test_skips_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("ok")
    (tmp_path / "link.txt").symlink_to(target)
    assert set(scan_source(tmp_path)) == {"target.txt"}
