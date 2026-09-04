from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from ragpipe.ingest.loaders import load_text
from ragpipe.ingest.source_scanner import SourceError, scan_source
from ragpipe.models import ScannedDocument


class DocumentSource(Protocol):
    """A collection of documents that can be scanned and loaded."""

    @property
    def label(self) -> str:
        """Return the identifier stored with synchronization runs."""
        ...

    def scan(self) -> Mapping[str, ScannedDocument]:
        """Return documents keyed by their stable source-relative paths."""
        ...

    def load(self, document: ScannedDocument) -> str:
        """Load and extract text from a scanned document."""
        ...


class LocalFolderSource:
    """Read documents recursively from a local directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    @property
    def label(self) -> str:
        return str(self.root)

    def scan(self) -> Mapping[str, ScannedDocument]:
        return scan_source(self.root)

    def load(self, document: ScannedDocument) -> str:
        document_path = (self.root / document.path).resolve()

        try:
            document_path.relative_to(self.root)
        except ValueError as error:
            raise SourceError(f"Document path escapes source root: {document.path}") from error

        return load_text(document_path)
