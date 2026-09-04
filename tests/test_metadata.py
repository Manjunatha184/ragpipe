import pytest

from ragpipe.ingest.metadata import (
    MAX_METADATA_FILE_SIZE_BYTES,
    MetadataManifestError,
    parse_metadata_manifest,
)


def test_metadata_manifest_can_be_parsed_from_bytes() -> None:
    result = parse_metadata_manifest(
        b"""
        {
          "guide.md": {
            "department": "engineering",
            "tags": ["rag", "demo"]
          }
        }
        """
    )

    assert result == {
        "guide.md": {
            "department": "engineering",
            "tags": ["rag", "demo"],
        }
    }


def test_metadata_manifest_bytes_must_be_utf8() -> None:
    with pytest.raises(
        MetadataManifestError,
        match="must be valid UTF-8",
    ):
        parse_metadata_manifest(b'{"guide.md": "\xff"}')


def test_metadata_manifest_bytes_have_size_limit() -> None:
    oversized = b" " * (MAX_METADATA_FILE_SIZE_BYTES + 1)

    with pytest.raises(
        MetadataManifestError,
        match="must not exceed",
    ):
        parse_metadata_manifest(oversized)
