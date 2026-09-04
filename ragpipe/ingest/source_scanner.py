from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Mapping
from pathlib import Path

from ragpipe.ingest.metadata import (
    METADATA_FILENAME,
    load_metadata_manifest,
    metadata_hash,
)
from ragpipe.models import DocumentState, ScannedDocument, SourceDiff

SUPPORTED_EXTENSIONS = frozenset({".txt", ".md", ".markdown", ".pdf"})


class SourceError(ValueError):
    pass


def sha256_file(
    path: Path,
    block_size: int = 1024 * 1024,
) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)

    return digest.hexdigest()


def scan_source(source: Path) -> dict[str, ScannedDocument]:
    root = source.expanduser().resolve()

    if not root.is_dir():
        raise SourceError(f"Source directory does not exist: {source}")

    candidates: list[tuple[str, Path]] = []

    for path in sorted(root.rglob("*")):
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix.lower() not in SUPPORTED_EXTENSIONS
        ):
            continue

        candidates.append(
            (
                path.relative_to(root).as_posix(),
                path,
            )
        )

    metadata_by_path = load_metadata_manifest(root)
    candidate_paths = {relative for relative, _ in candidates}
    unknown_paths = sorted(metadata_by_path.keys() - candidate_paths)

    if unknown_paths:
        joined_paths = ", ".join(repr(path) for path in unknown_paths)

        raise SourceError(
            f"{METADATA_FILENAME} contains metadata for unknown documents: {joined_paths}"
        )

    result: dict[str, ScannedDocument] = {}

    for relative, path in candidates:
        document_metadata = metadata_by_path.get(relative, {})

        result[relative] = ScannedDocument(
            path=relative,
            content_hash=sha256_file(path),
            size_bytes=path.stat().st_size,
            media_type=(mimetypes.guess_type(path.name)[0] or "application/octet-stream"),
            metadata=document_metadata,
            metadata_hash=metadata_hash(document_metadata),
        )

    return result


def diff_source(
    scanned: Mapping[str, ScannedDocument],
    previous: Mapping[str, DocumentState],
) -> SourceDiff:
    new: list[ScannedDocument] = []
    changed: list[ScannedDocument] = []
    metadata_changed: list[ScannedDocument] = []
    unchanged: list[ScannedDocument] = []

    for path, item in sorted(scanned.items()):
        old = previous.get(path)

        if old is None:
            new.append(item)
        elif old.content_hash != item.content_hash:
            changed.append(item)
        elif old.metadata_hash != item.metadata_hash:
            metadata_changed.append(item)
        else:
            unchanged.append(item)

    deleted = [previous[path] for path in sorted(previous.keys() - scanned.keys())]

    return SourceDiff(
        new=tuple(new),
        changed=tuple(changed),
        deleted=tuple(deleted),
        unchanged=tuple(unchanged),
        metadata_changed=tuple(metadata_changed),
    )
