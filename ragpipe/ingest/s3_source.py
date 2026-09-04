from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

from ragpipe.ingest.loaders import load_bytes
from ragpipe.ingest.metadata import METADATA_FILENAME, metadata_hash, parse_metadata_manifest
from ragpipe.ingest.source_scanner import SUPPORTED_EXTENSIONS, SourceError
from ragpipe.models import ScannedDocument


class S3SourceError(SourceError):
    """Raised when an S3 document source cannot be read safely."""


class _StreamingBody(Protocol):
    def read(self) -> bytes: ...


class _Paginator(Protocol):
    def paginate(self, **kwargs: Any) -> Iterable[Mapping[str, Any]]: ...


class S3Client(Protocol):
    """Small S3 client surface used by the source and its tests."""

    def get_paginator(self, operation_name: str) -> _Paginator: ...

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class _S3Object:
    key: str
    etag: str | None


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """Return the bucket and normalized optional prefix from an S3 URI."""

    parsed = urlsplit(uri)

    if (
        uri != uri.strip()
        or parsed.scheme != "s3"
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise S3SourceError(f"Invalid S3 source URI: {uri!r}")

    prefix = parsed.path.lstrip("/").rstrip("/")
    normalized = PurePosixPath(prefix)

    if prefix and (
        "\\" in prefix
        or "//" in prefix
        or "." in normalized.parts
        or ".." in normalized.parts
        or normalized.as_posix() != prefix
    ):
        raise S3SourceError(f"Invalid S3 source prefix: {prefix!r}")

    return parsed.netloc, prefix


def _make_s3_client() -> S3Client:
    try:
        import boto3
    except ImportError as error:
        raise S3SourceError(
            "S3 support requires the optional dependency: pip install -e '.[s3]'"
        ) from error

    return cast(S3Client, boto3.client("s3"))


class S3DocumentSource:
    """Read supported documents from an S3 bucket and optional prefix."""

    def __init__(
        self,
        uri: str,
        client: S3Client | None = None,
    ) -> None:
        self.bucket, self.prefix = parse_s3_uri(uri)
        self._client = client or _make_s3_client()
        self._objects: dict[str, _S3Object] = {}

    @property
    def label(self) -> str:
        if self.prefix:
            return f"s3://{self.bucket}/{self.prefix}"

        return f"s3://{self.bucket}"

    def _list_prefix(self) -> str:
        if self.prefix:
            return f"{self.prefix}/"

        return ""

    def _relative_path(self, key: str) -> str:
        list_prefix = self._list_prefix()

        if list_prefix and not key.startswith(list_prefix):
            raise S3SourceError(f"S3 returned an object outside the requested prefix: {key!r}")

        relative = key[len(list_prefix) :]
        normalized = PurePosixPath(relative)

        if (
            not relative
            or "\\" in relative
            or "//" in relative
            or normalized.is_absolute()
            or "." in normalized.parts
            or ".." in normalized.parts
            or normalized.as_posix() != relative
        ):
            raise S3SourceError(f"S3 returned an unsafe document path: {relative!r}")

        return relative

    def _read_object(
        self,
        item: _S3Object,
    ) -> bytes:
        arguments: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": item.key,
        }

        if item.etag:
            arguments["IfMatch"] = item.etag

        try:
            response = self._client.get_object(**arguments)
            body = response.get("Body")

            if body is None or not hasattr(body, "read"):
                raise S3SourceError(f"S3 object has no readable body: {item.key!r}")

            content = cast(_StreamingBody, body).read()

            if not isinstance(content, bytes):
                raise S3SourceError(f"S3 object returned a non-bytes body: {item.key!r}")

            return content
        except S3SourceError:
            raise
        except Exception as error:
            raise S3SourceError(f"Could not read s3://{self.bucket}/{item.key}: {error}") from error

    def scan(self) -> Mapping[str, ScannedDocument]:
        """List, hash, and describe supported objects under the prefix."""

        discovered: dict[str, _S3Object] = {}
        manifest: _S3Object | None = None
        manifest_key = f"{self._list_prefix()}{METADATA_FILENAME}"

        try:
            paginator = self._client.get_paginator("list_objects_v2")
            pages = paginator.paginate(
                Bucket=self.bucket,
                Prefix=self._list_prefix(),
            )

            for page in pages:
                contents = page.get("Contents", [])

                if not isinstance(contents, list):
                    raise S3SourceError("S3 listing returned an invalid Contents value.")

                for entry in contents:
                    if not isinstance(entry, Mapping):
                        raise S3SourceError("S3 listing returned an invalid object entry.")

                    key = entry.get("Key")

                    if not isinstance(key, str) or not key or key.endswith("/"):
                        continue

                    etag_value = entry.get("ETag")
                    etag = etag_value if isinstance(etag_value, str) else None
                    item = _S3Object(key=key, etag=etag)

                    if key == manifest_key:
                        manifest = item
                        continue

                    relative = self._relative_path(key)

                    if PurePosixPath(relative).suffix.lower() not in SUPPORTED_EXTENSIONS:
                        continue

                    discovered[relative] = item
        except S3SourceError:
            raise
        except Exception as error:
            raise S3SourceError(f"Could not list {self.label}: {error}") from error

        metadata_by_path = parse_metadata_manifest(self._read_object(manifest)) if manifest else {}
        unknown_paths = sorted(metadata_by_path.keys() - discovered.keys())

        if unknown_paths:
            joined_paths = ", ".join(repr(path) for path in unknown_paths)
            raise S3SourceError(
                f"{METADATA_FILENAME} contains metadata for unknown documents: {joined_paths}"
            )

        scanned: dict[str, ScannedDocument] = {}

        for relative, item in sorted(discovered.items()):
            content = self._read_object(item)
            document_metadata = metadata_by_path.get(relative, {})

            scanned[relative] = ScannedDocument(
                path=relative,
                content_hash=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
                media_type=(mimetypes.guess_type(relative)[0] or "application/octet-stream"),
                metadata=document_metadata,
                metadata_hash=metadata_hash(document_metadata),
            )

        self._objects = discovered

        return scanned

    def load(self, document: ScannedDocument) -> str:
        """Load text from a document returned by the most recent scan."""

        item = self._objects.get(document.path)

        if item is None:
            raise S3SourceError(
                f"Document was not returned by the latest S3 scan: {document.path!r}"
            )

        content = self._read_object(item)
        actual_hash = hashlib.sha256(content).hexdigest()

        if actual_hash != document.content_hash:
            raise S3SourceError(f"S3 object changed after scanning: {document.path!r}")

        return load_bytes(content, document.path)
