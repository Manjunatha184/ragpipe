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
from ragpipe.store.base import Store, SyncLockUnavailableError

log = structlog.get_logger()

_URL_PASSWORD_PATTERN = re.compile(
    r"(://[^:/\s]+:)[^@\s]+(@)",
)

_DSN_PASSWORD_PATTERN = re.compile(
    r"(?i)(password\s*=\s*)\S+",
)


class SyncAlreadyRunningError(RuntimeError):
    """Raised when another synchronization owns the store lock."""

    safe_message = "Another synchronization is already running for this store."

    def __init__(self) -> None:
        super().__init__(self.safe_message)


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
        metadata_changed_documents = 0
        deleted_documents = 0
        unchanged_documents = 0
        embedded_chunks = 0
        deleted_chunks = 0

        try:
            with self.store.sync_lock():
                try:
                    scanned = scan_source(source)

                    with self.store.transaction():
                        previous = self.store.document_states()
                        diff = diff_source(scanned, previous)

                        new_documents = len(diff.new)
                        changed_documents = len(diff.changed)
                        metadata_changed_documents = len(diff.metadata_changed)
                        deleted_documents = len(diff.deleted)
                        unchanged_documents = len(diff.unchanged)

                        # Metadata-only changes update the document row without
                        # deleting chunks or generating embeddings again.
                        for item in diff.metadata_changed:
                            metadata_state = previous[item.path]

                            self.store.update_document_metadata(
                                document_id=metadata_state.id,
                                document_metadata=item.metadata,
                                metadata_hash=item.metadata_hash,
                            )

                        for deleted in diff.deleted:
                            deleted_chunks += self.store.delete_document(deleted.id)

                        for item in (*diff.new, *diff.changed):
                            prior = previous.get(item.path)

                            if prior:
                                deleted_chunks += self.store.delete_document(prior.id)

                            chunks = self.chunker.chunk(load_text(item.absolute_path))
                            embeddings: list[list[float]] = []

                            for batch_start in range(
                                0,
                                len(chunks),
                                self.batch_size,
                            ):
                                batch = chunks[batch_start : batch_start + self.batch_size]
                                embeddings.extend(
                                    self.embedder.embed([chunk.text for chunk in batch])
                                )

                            self.store.replace_document(
                                path=item.path,
                                content_hash=item.content_hash,
                                media_type=item.media_type,
                                size_bytes=item.size_bytes,
                                chunks=chunks,
                                embeddings=embeddings,
                                model_name=self.embedder.model_name,
                                document_metadata=item.metadata,
                                metadata_hash=item.metadata_hash,
                            )
                            embedded_chunks += len(chunks)

                        finished = datetime.now(UTC)

                        result = SyncResult(
                            run_id=run_id,
                            status="succeeded",
                            new_documents=new_documents,
                            changed_documents=changed_documents,
                            metadata_changed_documents=metadata_changed_documents,
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

                    # The document transaction rolled back. Keep the sync
                    # lock while recording the failure so another sync
                    # cannot begin between rollback and observability.
                    failed_result = SyncResult(
                        run_id=run_id,
                        status="failed",
                        new_documents=new_documents,
                        changed_documents=changed_documents,
                        metadata_changed_documents=metadata_changed_documents,
                        deleted_documents=deleted_documents,
                        unchanged_documents=unchanged_documents,
                        embedded_chunks=0,
                        deleted_chunks=0,
                        started_at=started,
                        finished_at=finished,
                    )

                    try:
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

        except SyncLockUnavailableError as error:
            log.warning(
                "sync_skipped",
                source=source_label,
                reason="lock_unavailable",
            )

            # Lock contention is not a failed pipeline run because this
            # process never began reading or changing the corpus.
            raise SyncAlreadyRunningError() from error

        log.info(
            "sync_completed",
            **result.__dict__,
        )

        return result
