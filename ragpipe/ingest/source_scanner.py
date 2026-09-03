from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Mapping
from pathlib import Path

from ragpipe.models import DocumentState, ScannedDocument, SourceDiff

SUPPORTED_EXTENSIONS = frozenset({".txt", ".md", ".markdown", ".pdf"})


class SourceError(ValueError):
    pass


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def scan_source(source: Path) -> dict[str, ScannedDocument]:
    root = source.expanduser().resolve()
    if not root.is_dir():
        raise SourceError(f"Source directory does not exist: {source}")

    result: dict[str, ScannedDocument] = {}
    for path in sorted(root.rglob("*")):
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix.lower() not in SUPPORTED_EXTENSIONS
        ):
            continue
        relative = path.relative_to(root).as_posix()
        result[relative] = ScannedDocument(
            path=relative,
            absolute_path=path,
            content_hash=sha256_file(path),
            size_bytes=path.stat().st_size,
            media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        )
    return result


def diff_source(
    scanned: Mapping[str, ScannedDocument], previous: Mapping[str, DocumentState]
) -> SourceDiff:
    new, changed, unchanged = [], [], []
    for path, item in sorted(scanned.items()):
        old = previous.get(path)
        if old is None:
            new.append(item)
        elif old.content_hash != item.content_hash:
            changed.append(item)
        else:
            unchanged.append(item)
    deleted = [previous[path] for path in sorted(previous.keys() - scanned.keys())]
    return SourceDiff(tuple(new), tuple(changed), tuple(deleted), tuple(unchanged))
