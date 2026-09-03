from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from ragpipe.chunking.chunker import RecursiveCharacterChunker
from ragpipe.config import Settings
from ragpipe.embedding.local_provider import (
    LocalSentenceTransformerProvider,
)
from ragpipe.logging import configure_logging
from ragpipe.pipeline import (
    SyncFailedError,
    SyncPipeline,
)
from ragpipe.store.pgvector_store import (
    PgVectorStore,
    SchemaNotReadyError,
)

app = typer.Typer(
    no_args_is_help=True,
    help="Keep a pgvector store synchronized with documents.",
)


def make_store(settings: Settings) -> PgVectorStore:
    """Create and validate a store without leaking its connection pool."""

    store = PgVectorStore(settings.database_url)

    try:
        store.initialize(settings.embedding_dimension)
    except Exception:
        store.close()
        raise

    return store


def print_schema_error(error: SchemaNotReadyError) -> None:
    typer.echo(
        json.dumps(
            {
                "status": "schema_error",
                "error": str(error),
            },
            indent=2,
        ),
        err=True,
    )


@app.command()
def sync(
    source: Annotated[
        Path,
        typer.Option(
            "--source",
            "-s",
            exists=True,
            file_okay=False,
        ),
    ],
) -> None:
    settings = Settings(source=source)
    configure_logging(settings.log_level)

    store: PgVectorStore | None = None

    try:
        embedder = LocalSentenceTransformerProvider(
            model_name=settings.embedding_model,
            expected_dimension=settings.embedding_dimension,
        )

        store = make_store(settings)

        result = SyncPipeline(
            store=store,
            chunker=RecursiveCharacterChunker(
                settings.chunk_size,
                settings.chunk_overlap,
            ),
            embedder=embedder,
            batch_size=settings.batch_size,
        ).sync(source)

        typer.echo(
            json.dumps(
                asdict(result),
                default=str,
                indent=2,
            )
        )

    except SyncFailedError as error:
        typer.echo(
            json.dumps(
                {
                    "status": "failed",
                    "run_id": error.run_id,
                    "error": error.safe_message,
                },
                indent=2,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from None

    except SchemaNotReadyError as error:
        print_schema_error(error)
        raise typer.Exit(code=2) from None

    finally:
        if store is not None:
            store.close()


@app.command()
def status() -> None:
    settings = Settings()
    store: PgVectorStore | None = None

    try:
        store = make_store(settings)

        typer.echo(
            json.dumps(
                asdict(store.status()),
                default=str,
                indent=2,
            )
        )

    except SchemaNotReadyError as error:
        print_schema_error(error)
        raise typer.Exit(code=2) from None

    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    app()
