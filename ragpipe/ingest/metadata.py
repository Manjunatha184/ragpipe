from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

METADATA_FILENAME = ".ragpipe-metadata.json"
MAX_METADATA_FILE_SIZE_BYTES = 1024 * 1024


class MetadataManifestError(ValueError):
    """Raised when source metadata configuration is invalid."""


def metadata_hash(metadata: Mapping[str, Any]) -> str:
    """Return a deterministic hash for JSON-compatible metadata."""

    try:
        canonical = json.dumps(
            dict(metadata),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise MetadataManifestError("Document metadata must contain valid JSON values.") from error

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_document_path(path: str) -> None:
    normalized = PurePosixPath(path)

    if (
        not path
        or "\\" in path
        or normalized.is_absolute()
        or "." in normalized.parts
        or ".." in normalized.parts
        or normalized.as_posix() != path
    ):
        raise MetadataManifestError(f"Metadata manifest contains unsafe document path: {path!r}")


def parse_metadata_manifest(
    content: bytes,
) -> dict[str, dict[str, Any]]:
    """Parse and validate metadata-manifest bytes."""

    if len(content) > MAX_METADATA_FILE_SIZE_BYTES:
        raise MetadataManifestError(
            f"{METADATA_FILENAME} must not exceed {MAX_METADATA_FILE_SIZE_BYTES} bytes."
        )

    try:
        decoded = content.decode("utf-8")
    except UnicodeError as error:
        raise MetadataManifestError(f"{METADATA_FILENAME} must be valid UTF-8.") from error

    try:
        payload: Any = json.loads(decoded)
    except json.JSONDecodeError as error:
        raise MetadataManifestError(f"{METADATA_FILENAME} is not valid JSON.") from error

    if not isinstance(payload, dict):
        raise MetadataManifestError(f"{METADATA_FILENAME} must contain a JSON object.")

    result: dict[str, dict[str, Any]] = {}

    for document_path, document_metadata in payload.items():
        _validate_document_path(document_path)

        if not isinstance(document_metadata, dict):
            raise MetadataManifestError(f"Metadata for {document_path!r} must be a JSON object.")

        normalized_metadata = dict(document_metadata)

        # Validate nested values and reject NaN/Infinity.
        metadata_hash(normalized_metadata)
        result[document_path] = normalized_metadata

    return result


def load_metadata_manifest(
    source_root: Path,
) -> dict[str, dict[str, Any]]:
    """Load document metadata keyed by relative source path."""

    manifest = source_root / METADATA_FILENAME

    if manifest.is_symlink():
        raise MetadataManifestError(f"{METADATA_FILENAME} must not be a symbolic link.")

    if not manifest.exists():
        return {}

    if not manifest.is_file():
        raise MetadataManifestError(f"{METADATA_FILENAME} must be a regular file.")

    try:
        if manifest.stat().st_size > MAX_METADATA_FILE_SIZE_BYTES:
            raise MetadataManifestError(
                f"{METADATA_FILENAME} must not exceed {MAX_METADATA_FILE_SIZE_BYTES} bytes."
            )

        content = manifest.read_bytes()
    except OSError as error:
        raise MetadataManifestError(f"Could not read {METADATA_FILENAME}: {error}") from error

    return parse_metadata_manifest(content)
