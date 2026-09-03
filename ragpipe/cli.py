from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from ragpipe.chunking.chunker import RecursiveCharacterChunker
from ragpipe.config import Settings
from ragpipe.embedding.local_provider import LocalSentenceTransformerProvider
from ragpipe.logging import configure_logging
from ragpipe.pipeline import SyncPipeline
from ragpipe.store.pgvector_store import PgVectorStore

app = typer.Typer(no_args_is_help=True, help="Keep a pgvector store synchronized with documents.")


def make_store(settings: Settings) -> PgVectorStore:
    store = PgVectorStore(settings.database_url)
    store.initialize(settings.embedding_dimension)
    return store


@app.command()
def sync(
    source: Annotated[Path, typer.Option("--source", "-s", exists=True, file_okay=False)],
) -> None:
    settings = Settings(source=source)
    configure_logging(settings.log_level)
    embedder = LocalSentenceTransformerProvider(settings.embedding_model)
    if embedder.dimension != settings.embedding_dimension:
        raise typer.BadParameter(
            f"Model dimension {embedder.dimension} does not match configured "
            f"dimension {settings.embedding_dimension}"
        )
    store = make_store(settings)
    try:
        result = SyncPipeline(
            store,
            RecursiveCharacterChunker(settings.chunk_size, settings.chunk_overlap),
            embedder,
            settings.batch_size,
        ).sync(source)
        typer.echo(json.dumps(asdict(result), default=str, indent=2))
    finally:
        store.close()


@app.command()
def status() -> None:
    settings = Settings()
    store = make_store(settings)
    try:
        typer.echo(json.dumps(asdict(store.status()), default=str, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    app()
