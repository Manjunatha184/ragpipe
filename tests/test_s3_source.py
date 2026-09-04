from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

import pytest

from ragpipe.chunking.chunker import RecursiveCharacterChunker
from ragpipe.ingest.s3_source import (
    S3DocumentSource,
    S3SourceError,
    parse_s3_uri,
)
from ragpipe.models import ScannedDocument
from ragpipe.pipeline import SyncPipeline
from tests.fakes import FakeEmbedder, MemoryStore


class FakeBody:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def read(self) -> bytes:
        return self.content


class FakePaginator:
    def __init__(
        self,
        pages: list[Mapping[str, Any]],
    ) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def paginate(self, **kwargs: Any) -> Iterable[Mapping[str, Any]]:
        self.calls.append(kwargs)
        return iter(self.pages)


class FakeS3Client:
    def __init__(
        self,
        objects: dict[str, bytes],
        pages: list[Mapping[str, Any]],
    ) -> None:
        self.objects = objects
        self.paginator = FakePaginator(pages)
        self.get_calls: list[dict[str, Any]] = []

    def get_paginator(self, operation_name: str) -> FakePaginator:
        assert operation_name == "list_objects_v2"
        return self.paginator

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]:
        self.get_calls.append(kwargs)

        return {"Body": FakeBody(self.objects[str(kwargs["Key"])])}


def object_entry(
    key: str,
    content: bytes,
) -> dict[str, Any]:
    return {
        "Key": key,
        "Size": len(content),
        "ETag": f'"{hashlib.md5(content, usedforsecurity=False).hexdigest()}"',
    }


@pytest.mark.parametrize(
    "uri",
    [
        "",
        "/documents",
        "https://bucket/documents",
        "s3:///documents",
        "s3://bucket/../documents",
        "s3://bucket/documents?version=1",
        "s3://user:password@bucket/documents",
    ],
)
def test_rejects_invalid_s3_uri(uri: str) -> None:
    with pytest.raises(
        S3SourceError,
        match="Invalid S3 source",
    ):
        parse_s3_uri(uri)


def test_s3_source_scans_paginated_objects_and_loads_metadata() -> None:
    guide = b"# Guide\n\nS3 document content."
    policy = b"Leave policy"
    ignored = b"ignored"
    manifest = b"""
    {
      "guide.md": {
        "department": "engineering",
        "tags": ["rag"]
      }
    }
    """
    objects = {
        "knowledge/guide.md": guide,
        "knowledge/nested/policy.txt": policy,
        "knowledge/ignored.csv": ignored,
        "knowledge/.ragpipe-metadata.json": manifest,
    }
    client = FakeS3Client(
        objects=objects,
        pages=[
            {
                "Contents": [
                    object_entry("knowledge/guide.md", guide),
                    object_entry("knowledge/ignored.csv", ignored),
                ]
            },
            {
                "Contents": [
                    object_entry("knowledge/nested/policy.txt", policy),
                    object_entry("knowledge/.ragpipe-metadata.json", manifest),
                    {"Key": "knowledge/folder/", "Size": 0},
                ]
            },
        ],
    )
    source = S3DocumentSource(
        "s3://documents/knowledge/",
        client=client,
    )

    scanned = source.scan()

    assert source.label == "s3://documents/knowledge"
    assert list(scanned) == ["guide.md", "nested/policy.txt"]
    assert scanned["guide.md"].content_hash == hashlib.sha256(guide).hexdigest()
    assert scanned["guide.md"].size_bytes == len(guide)
    assert scanned["guide.md"].media_type == "text/markdown"
    assert scanned["guide.md"].metadata == {
        "department": "engineering",
        "tags": ["rag"],
    }
    assert source.load(scanned["guide.md"]) == "# Guide\n\nS3 document content."
    assert client.paginator.calls == [
        {
            "Bucket": "documents",
            "Prefix": "knowledge/",
        }
    ]
    assert all(call["Bucket"] == "documents" for call in client.get_calls)
    assert all("IfMatch" in call for call in client.get_calls)


def test_s3_source_rejects_metadata_for_unknown_document() -> None:
    manifest = b'{"missing.txt": {"department": "hr"}}'
    key = ".ragpipe-metadata.json"
    client = FakeS3Client(
        objects={key: manifest},
        pages=[{"Contents": [object_entry(key, manifest)]}],
    )
    source = S3DocumentSource(
        "s3://documents",
        client=client,
    )

    with pytest.raises(
        S3SourceError,
        match="unknown documents",
    ):
        source.scan()


def test_s3_source_detects_object_changed_after_scan() -> None:
    key = "guide.txt"
    original = b"Original"
    client = FakeS3Client(
        objects={key: original},
        pages=[{"Contents": [object_entry(key, original)]}],
    )
    source = S3DocumentSource(
        "s3://documents",
        client=client,
    )
    scanned = source.scan()

    client.objects[key] = b"Changed"

    with pytest.raises(
        S3SourceError,
        match="changed after scanning",
    ):
        source.load(scanned["guide.txt"])


def test_s3_source_only_loads_documents_from_latest_scan() -> None:
    client = FakeS3Client(
        objects={},
        pages=[{}],
    )
    source = S3DocumentSource(
        "s3://documents",
        client=client,
    )
    source.scan()

    unknown = ScannedDocument(
        path="unknown.txt",
        content_hash="0" * 64,
        size_bytes=0,
        media_type="text/plain",
    )

    with pytest.raises(
        S3SourceError,
        match="latest S3 scan",
    ):
        source.load(unknown)


def test_s3_source_pipeline_sync_is_idempotent() -> None:
    key = "documents/guide.txt"
    content = b"Ragpipe synchronizes S3 documents."
    client = FakeS3Client(
        objects={key: content},
        pages=[
            {
                "Contents": [
                    object_entry(
                        key,
                        content,
                    )
                ]
            }
        ],
    )
    source = S3DocumentSource(
        "s3://knowledge/documents",
        client=client,
    )
    store = MemoryStore()
    embedder = FakeEmbedder()
    pipeline = SyncPipeline(
        store=store,
        chunker=RecursiveCharacterChunker(
            chunk_size=100,
            overlap=10,
        ),
        embedder=embedder,
    )

    first = pipeline.sync(source)
    embedded_after_first = embedder.texts
    second = pipeline.sync(source)

    assert first.new_documents == 1
    assert first.embedded_chunks == 1
    assert second.unchanged_documents == 1
    assert second.embedded_chunks == 0
    assert embedder.texts == embedded_after_first

    # First sync downloads once for hashing and once for loading.
    # The unchanged second sync only downloads once for hashing.
    assert len(client.get_calls) == 3
