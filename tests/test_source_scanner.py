import hashlib
from pathlib import Path

import pytest

from ragpipe.ingest.metadata import metadata_hash
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


def test_manifest_metadata_is_loaded_and_detected_separately(
    tmp_path: Path,
) -> None:
    document = tmp_path / "policy.md"
    document.write_text(
        "Leave policy",
        encoding="utf-8",
    )

    (tmp_path / ".ragpipe-metadata.json").write_text(
        """
        {
          "policy.md": {
            "department": "hr",
            "tags": ["leave", "policy"]
          }
        }
        """,
        encoding="utf-8",
    )

    scanned = scan_source(tmp_path)
    item = scanned["policy.md"]

    assert item.metadata == {
        "department": "hr",
        "tags": ["leave", "policy"],
    }

    previous = {
        "policy.md": DocumentState(
            id="document-id",
            path="policy.md",
            content_hash=item.content_hash,
            metadata_hash=metadata_hash(
                {
                    "department": "finance",
                    "tags": ["policy"],
                }
            ),
        )
    }

    diff = diff_source(
        scanned,
        previous,
    )

    assert diff.new == ()
    assert diff.changed == ()
    assert diff.deleted == ()
    assert diff.unchanged == ()
    assert [document.path for document in diff.metadata_changed] == ["policy.md"]


def test_metadata_hash_is_independent_of_key_order() -> None:
    first = metadata_hash(
        {
            "department": "hr",
            "classification": "internal",
        }
    )
    second = metadata_hash(
        {
            "classification": "internal",
            "department": "hr",
        }
    )

    assert first == second


@pytest.mark.parametrize(
    ("manifest", "expected_message"),
    [
        (
            "[]",
            "must contain a JSON object",
        ),
        (
            '{"../outside.txt": {}}',
            "unsafe document path",
        ),
        (
            '{"missing.txt": {"department": "hr"}}',
            "unknown documents",
        ),
    ],
)
def test_rejects_invalid_metadata_manifest(
    tmp_path: Path,
    manifest: str,
    expected_message: str,
) -> None:
    (tmp_path / "document.txt").write_text(
        "Document",
        encoding="utf-8",
    )
    (tmp_path / ".ragpipe-metadata.json").write_text(
        manifest,
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        scan_source(tmp_path)
