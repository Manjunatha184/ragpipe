from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog

from ragpipe.chunking.chunker import Chunker
from ragpipe.embedding.base import EmbeddingProvider
from ragpipe.ingest.loaders import load_text
from ragpipe.ingest.source_scanner import diff_source, scan_source
from ragpipe.models import SyncResult
from ragpipe.store.base import Store

log = structlog.get_logger()

_URL_PASSWORD_PATTERN = re.compile(
    r"(://[^:/\s]+:)[^@\s]+(@)",
)

_DSN_PASSWORD_PATTERN = re.compile(
    r"(?i)(password\s*=\s*)\S+",
)


class SyncFailedError(RuntimeError):
    """Raised after a failed synchronization attempt is recorded."""

    def __init__(self, run_id: str, safe_message: str) -> None:
        self.run_id = run_id
        self.safe_message = safe_message

        super().__init__(f"Synchronization {run_id} failed: {safe_message}")


def sanitize_error(error: Exception) -> str:
    """Return a bounded error message with common credentials removed."""

    message = f"{type(error).__name__}: {error}"
    message = _URL_PASSWORD_PATTERN.sub(r"\1***\2", message)
    message = _DSN_PASSWORD_PATTERN.sub(r"\1***", message)

    # Store one bounded line instead of an uncontrolled traceback.
    return " ".join(message.split())[:1000]


class SyncPipeline:
    def __init__(
        self,
        store: Store,
        chunker: Chunker,
        embedder: EmbeddingProvider,
        batch_size: int = 64,
    ) -> None:
        self.store = store
        self.chunker = chunker
        self.embedder = embedder
        self.batch_size = batch_size

    def sync(self, source: Path) -> SyncResult:
        started = datetime.now(UTC)
        run_id = str(uuid.uuid4())
        source_label = str(source.expanduser().resolve())

        new_documents = 0
        changed_documents = 0
        deleted_documents = 0
        unchanged_documents = 0
        embedded_chunks = 0
        deleted_chunks = 0

        try:
            scanned = scan_source(source)

            with self.store.transaction():
                previous = self.store.document_states()
                diff = diff_source(scanned, previous)

                new_documents = len(diff.new)
                changed_documents = len(diff.changed)
                deleted_documents = len(diff.deleted)
                unchanged_documents = len(diff.unchanged)

                for deleted in diff.deleted:
                    deleted_chunks += self.store.delete_document(deleted.id)

                for item in (*diff.new, *diff.changed):
                    prior = previous.get(item.path)

                    if prior:
                        deleted_chunks += self.store.delete_document(prior.id)

                    chunks = self.chunker.chunk(load_text(item.absolute_path))
                    embeddings: list[list[float]] = []

                    for start in range(
                        0,
                        len(chunks),
                        self.batch_size,
                    ):
                        batch = chunks[start : start + self.batch_size]
                        embeddings.extend(self.embedder.embed([chunk.text for chunk in batch]))

                    self.store.replace_document(
                        item.path,
                        item.content_hash,
                        item.media_type,
                        item.size_bytes,
                        chunks,
                        embeddings,
                        self.embedder.model_name,
                    )
                    embedded_chunks += len(chunks)

                finished = datetime.now(UTC)

                result = SyncResult(
                    run_id=run_id,
                    status="succeeded",
                    new_documents=new_documents,
                    changed_documents=changed_documents,
                    deleted_documents=deleted_documents,
                    unchanged_documents=unchanged_documents,
                    embedded_chunks=embedded_chunks,
                    deleted_chunks=deleted_chunks,
                    started_at=started,
                    finished_at=finished,
                )

                self.store.record_run(
                    result,
                    source_label,
                )

        except Exception as error:
            finished = datetime.now(UTC)
            safe_message = sanitize_error(error)

            # The main transaction rolled back, so zero chunks were
            # committed or deleted even if some work was attempted.
            failed_result = SyncResult(
                run_id=run_id,
                status="failed",
                new_documents=new_documents,
                changed_documents=changed_documents,
                deleted_documents=deleted_documents,
                unchanged_documents=unchanged_documents,
                embedded_chunks=0,
                deleted_chunks=0,
                started_at=started,
                finished_at=finished,
            )

            try:
                # Use a separate transaction so the failed-run record
                # survives the rollback of document and vector changes.
                with self.store.transaction():
                    self.store.record_run(
                        failed_result,
                        source_label,
                        error=safe_message,
                    )
            except Exception as recording_error:
                log.error(
                    "failed_run_recording_failed",
                    run_id=run_id,
                    error=sanitize_error(recording_error),
                )

            log.error(
                "sync_failed",
                run_id=run_id,
                error=safe_message,
            )

            raise SyncFailedError(
                run_id,
                safe_message,
            ) from error

        log.info(
            "sync_completed",
            **result.__dict__,
        )

        return result
