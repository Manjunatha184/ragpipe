from __future__ import annotations

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


class SyncPipeline:
    def __init__(
        self, store: Store, chunker: Chunker, embedder: EmbeddingProvider, batch_size: int = 64
    ):
        self.store, self.chunker, self.embedder, self.batch_size = (
            store,
            chunker,
            embedder,
            batch_size,
        )

    def sync(self, source: Path) -> SyncResult:
        started = datetime.now(UTC)
        run_id = str(uuid.uuid4())
        scanned = scan_source(source)
        embedded_chunks = deleted_chunks = 0
        with self.store.transaction():
            previous = self.store.document_states()
            diff = diff_source(scanned, previous)
            for deleted in diff.deleted:
                deleted_chunks += self.store.delete_document(deleted.id)
            for item in (*diff.new, *diff.changed):
                prior = previous.get(item.path)
                if prior:
                    deleted_chunks += self.store.delete_document(prior.id)
                chunks = self.chunker.chunk(load_text(item.absolute_path))
                embeddings: list[list[float]] = []
                for start in range(0, len(chunks), self.batch_size):
                    embeddings.extend(
                        self.embedder.embed(
                            [c.text for c in chunks[start : start + self.batch_size]]
                        )
                    )
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
                run_id,
                "succeeded",
                len(diff.new),
                len(diff.changed),
                len(diff.deleted),
                len(diff.unchanged),
                embedded_chunks,
                deleted_chunks,
                started,
                finished,
            )
            self.store.record_run(result, str(source.resolve()))
        log.info("sync_completed", **result.__dict__)
        return result
