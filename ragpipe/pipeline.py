from __future__ import annotations

import re
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter

import structlog

from ragpipe.chunking.chunker import Chunker
from ragpipe.embedding.base import EmbeddingProvider
from ragpipe.ingest.source import DocumentSource
from ragpipe.ingest.source_scanner import diff_source
from ragpipe.models import Chunk, ScannedDocument, SyncResult
from ragpipe.store.base import Store, SyncLockUnavailableError

log = structlog.get_logger()

_URL_PASSWORD_PATTERN = re.compile(
    r"(://[^:/\s]+:)[^@\s]+(@)",
)

_DSN_PASSWORD_PATTERN = re.compile(
    r"(?i)(password\s*=\s*)\S+",
)


@dataclass
class _PreparedDocument:
    document: ScannedDocument
    chunks: list[Chunk]
    embeddings: list[list[float]] = field(default_factory=list)


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
        if batch_size <= 0:
            raise ValueError("Batch size must be greater than zero")

        self.store = store
        self.chunker = chunker
        self.embedder = embedder
        self.batch_size = batch_size

    def sync(self, source: DocumentSource) -> SyncResult:
        started = datetime.now(UTC)
        run_id = str(uuid.uuid4())
        source_label = source.label

        new_documents = 0
        changed_documents = 0
        metadata_changed_documents = 0
        deleted_documents = 0
        unchanged_documents = 0
        embedded_chunks = 0
        deleted_chunks = 0
        scanned_documents = 0
        scanned_bytes = 0
        embedding_batches = 0
        embedding_duration_ms = 0.0

        try:
            with self.store.sync_lock():
                try:
                    scanned = source.scan()
                    scanned_documents = len(scanned)
                    scanned_bytes = sum(document.size_bytes for document in scanned.values())

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

                        pending_documents: deque[_PreparedDocument] = deque()
                        pending_chunks: list[tuple[_PreparedDocument, Chunk]] = []

                        def flush_embedding_batch() -> None:
                            nonlocal embedding_batches
                            nonlocal embedding_duration_ms

                            if not pending_chunks:
                                return

                            batch_texts = [chunk.text for _, chunk in pending_chunks]
                            embedding_started = perf_counter()
                            embedding_batches += 1

                            try:
                                batch_embeddings = self.embedder.embed(batch_texts)
                            finally:
                                embedding_duration_ms += (perf_counter() - embedding_started) * 1000

                            if len(batch_embeddings) != len(pending_chunks):
                                raise RuntimeError(
                                    "Embedding provider returned an unexpected number of vectors"
                                )

                            for (prepared, _), embedding in zip(
                                pending_chunks,
                                batch_embeddings,
                                strict=True,
                            ):
                                prepared.embeddings.append(embedding)

                            pending_chunks.clear()

                        def store_completed_documents() -> None:
                            nonlocal deleted_chunks
                            nonlocal embedded_chunks

                            while pending_documents:
                                prepared = pending_documents[0]

                                if len(prepared.embeddings) != len(prepared.chunks):
                                    break

                                pending_documents.popleft()
                                item = prepared.document
                                prior = previous.get(item.path)

                                if prior:
                                    deleted_chunks += self.store.delete_document(prior.id)

                                self.store.replace_document(
                                    path=item.path,
                                    content_hash=item.content_hash,
                                    media_type=item.media_type,
                                    size_bytes=item.size_bytes,
                                    chunks=prepared.chunks,
                                    embeddings=prepared.embeddings,
                                    model_name=self.embedder.model_name,
                                    document_metadata=item.metadata,
                                    metadata_hash=item.metadata_hash,
                                )
                                embedded_chunks += len(prepared.chunks)

                        for item in (*diff.new, *diff.changed):
                            prepared = _PreparedDocument(
                                document=item,
                                chunks=self.chunker.chunk(source.load(item)),
                            )
                            pending_documents.append(prepared)

                            for chunk in prepared.chunks:
                                pending_chunks.append((prepared, chunk))

                                if len(pending_chunks) == self.batch_size:
                                    flush_embedding_batch()
                                    store_completed_documents()

                            # Empty documents are complete without embeddings.
                            store_completed_documents()

                        flush_embedding_batch()
                        store_completed_documents()

                        if pending_documents:
                            raise RuntimeError("Could not map all embeddings to their documents")

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
                            scanned_documents=scanned_documents,
                            scanned_bytes=scanned_bytes,
                            embedding_batches=embedding_batches,
                            embedding_duration_ms=embedding_duration_ms,
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
                        scanned_documents=scanned_documents,
                        scanned_bytes=scanned_bytes,
                        embedding_batches=embedding_batches,
                        embedding_duration_ms=embedding_duration_ms,
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
