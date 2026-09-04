from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Never, cast

import typer

from ragpipe.chunking.chunker import RecursiveCharacterChunker
from ragpipe.config import Settings
from ragpipe.embedding.local_provider import (
    LocalSentenceTransformerProvider,
)
from ragpipe.evaluation import (
    EvaluationDatasetError,
    RetrievalEvaluator,
    load_evaluation_cases,
)
from ragpipe.ingest.s3_source import (
    S3DocumentSource,
    S3SourceError,
)
from ragpipe.ingest.source import (
    DocumentSource,
    LocalFolderSource,
)
from ragpipe.logging import configure_logging
from ragpipe.pipeline import (
    SyncAlreadyRunningError,
    SyncFailedError,
    SyncPipeline,
    sanitize_error,
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


def reject_non_finite_json(value: str) -> Never:
    """Reject JSON extensions such as NaN and Infinity."""

    raise ValueError(f"Non-finite JSON number is not allowed: {value}")


def parse_metadata_filter(value: str | None) -> dict[str, Any] | None:
    """Parse a CLI metadata filter as a strict JSON object."""

    if value is None:
        return None

    try:
        parsed = json.loads(
            value,
            parse_constant=reject_non_finite_json,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise typer.BadParameter(
            "Metadata filter must be valid JSON.",
            param_hint="--metadata",
        ) from error

    if not isinstance(parsed, dict):
        raise typer.BadParameter(
            "Metadata filter must be a JSON object.",
            param_hint="--metadata",
        )

    return cast(dict[str, Any], parsed)


def make_document_source(value: str) -> DocumentSource:
    """Create a document source from a local path or S3 URI."""

    if value.startswith("s3://"):
        try:
            return S3DocumentSource(value)
        except S3SourceError as error:
            raise typer.BadParameter(
                str(error),
                param_hint="--source",
            ) from error

    path = Path(value).expanduser()

    if not path.is_dir():
        raise typer.BadParameter(
            f"Local source directory does not exist: {value}",
            param_hint="--source",
        )

    return LocalFolderSource(path)


@app.command()
def sync(
    source: Annotated[
        str,
        typer.Option(
            "--source",
            "-s",
            help="Local directory or s3://bucket/prefix URI.",
        ),
    ],
) -> None:
    document_source = make_document_source(source)
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
        ).sync(document_source)

        typer.echo(
            json.dumps(
                asdict(result),
                default=str,
                indent=2,
            )
        )

    except SyncAlreadyRunningError as error:
        typer.echo(
            json.dumps(
                {
                    "status": "busy",
                    "error": error.safe_message,
                },
                indent=2,
            ),
            err=True,
        )
        raise typer.Exit(code=3) from None

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
def search(
    query: Annotated[
        str,
        typer.Option(
            "--query",
            "-q",
            help="Natural-language query to search for.",
        ),
    ],
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-n",
            min=1,
            max=100,
            help="Maximum number of matching chunks.",
        ),
    ] = 5,
    metadata: Annotated[
        str | None,
        typer.Option(
            "--metadata",
            "-m",
            help='JSON document-metadata filter, for example: {"department":"hr"}',
        ),
    ] = None,
) -> None:
    query_text = query.strip()

    if not query_text:
        raise typer.BadParameter(
            "Query must not be empty.",
            param_hint="--query",
        )

    metadata_filter = parse_metadata_filter(metadata)
    settings = Settings()
    configure_logging(settings.log_level)

    store: PgVectorStore | None = None

    try:
        embedder = LocalSentenceTransformerProvider(
            model_name=settings.embedding_model,
            expected_dimension=settings.embedding_dimension,
        )

        store = make_store(settings)

        query_embeddings = embedder.embed([query_text])

        if len(query_embeddings) != 1:
            raise RuntimeError("Embedding provider did not return exactly one query vector")

        results = store.search(
            query_embedding=query_embeddings[0],
            model_name=embedder.model_name,
            limit=limit,
            metadata_filter=metadata_filter,
        )

        typer.echo(
            json.dumps(
                {
                    "query": query_text,
                    "metadata_filter": metadata_filter,
                    "embedding_model": embedder.model_name,
                    "count": len(results),
                    "results": [asdict(result) for result in results],
                },
                default=str,
                indent=2,
            )
        )

    except SchemaNotReadyError as error:
        print_schema_error(error)
        raise typer.Exit(code=2) from None

    except Exception as error:
        typer.echo(
            json.dumps(
                {
                    "status": "search_failed",
                    "error": sanitize_error(error),
                },
                indent=2,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from None

    finally:
        if store is not None:
            store.close()


@app.command()
def evaluate(
    dataset: Annotated[
        Path,
        typer.Option(
            "--dataset",
            "-d",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="JSONL file containing retrieval evaluation cases.",
        ),
    ],
    k: Annotated[
        int,
        typer.Option(
            "--k",
            min=1,
            max=100,
            help="Number of retrieved chunks evaluated per query.",
        ),
    ] = 5,
) -> None:
    settings = Settings()
    configure_logging(settings.log_level)

    store: PgVectorStore | None = None

    try:
        cases = load_evaluation_cases(dataset)

        embedder = LocalSentenceTransformerProvider(
            model_name=settings.embedding_model,
            expected_dimension=settings.embedding_dimension,
        )

        store = make_store(settings)

        report = RetrievalEvaluator(
            store=store,
            embedder=embedder,
            batch_size=settings.batch_size,
        ).evaluate(
            cases=cases,
            k=k,
        )

        typer.echo(
            json.dumps(
                {
                    "dataset": str(dataset.expanduser().resolve()),
                    "embedding_model": embedder.model_name,
                    **asdict(report),
                },
                default=str,
                indent=2,
            )
        )

    except EvaluationDatasetError as error:
        typer.echo(
            json.dumps(
                {
                    "status": "invalid_dataset",
                    "error": str(error),
                },
                indent=2,
            ),
            err=True,
        )
        raise typer.Exit(code=4) from None

    except SchemaNotReadyError as error:
        print_schema_error(error)
        raise typer.Exit(code=2) from None

    except Exception as error:
        typer.echo(
            json.dumps(
                {
                    "status": "evaluation_failed",
                    "error": sanitize_error(error),
                },
                indent=2,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from None

    finally:
        if store is not None:
            store.close()


@app.command()
def runs(
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-n",
            min=1,
            max=100,
            help="Maximum number of recent synchronization runs.",
        ),
    ] = 10,
) -> None:
    settings = Settings()
    configure_logging(settings.log_level)

    store: PgVectorStore | None = None

    try:
        store = make_store(settings)
        records = store.recent_runs(limit=limit)

        typer.echo(
            json.dumps(
                {
                    "limit": limit,
                    "count": len(records),
                    "runs": [asdict(record) for record in records],
                },
                default=str,
                indent=2,
            )
        )

    except SchemaNotReadyError as error:
        print_schema_error(error)
        raise typer.Exit(code=2) from None

    except Exception as error:
        typer.echo(
            json.dumps(
                {
                    "status": "run_history_failed",
                    "error": sanitize_error(error),
                },
                indent=2,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from None

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
