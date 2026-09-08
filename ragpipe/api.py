from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Protocol, cast

import structlog
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ragpipe import __version__
from ragpipe.api_models import (
    HealthResponse,
    OperationalMetricsResponse,
    RunsResponse,
    SearchRequest,
    SearchResponse,
    SearchResultResponse,
    StatusResponse,
    SyncRequest,
    SyncResponse,
    SyncRunResponse,
)
from ragpipe.chunking.chunker import RecursiveCharacterChunker
from ragpipe.config import Settings
from ragpipe.embedding.base import EmbeddingProvider
from ragpipe.embedding.local_provider import LocalSentenceTransformerProvider
from ragpipe.ingest.s3_source import S3DocumentSource, S3SourceError
from ragpipe.ingest.source import DocumentSource, LocalFolderSource
from ragpipe.logging import configure_logging
from ragpipe.metrics import render_prometheus_metrics
from ragpipe.models import (
    OperationalMetricsSnapshot,
    SearchResult,
    StoreStatus,
    SyncResult,
    SyncRunRecord,
)
from ragpipe.pipeline import (
    SyncAlreadyRunningError,
    SyncFailedError,
    SyncPipeline,
    sanitize_error,
)
from ragpipe.store.base import Store
from ragpipe.store.pgvector_store import PgVectorStore, SchemaNotReadyError

log = structlog.get_logger(__name__)
PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class InvalidApiSourceError(ValueError):
    """Raised when an API source is malformed or outside the permitted root."""


class ApiService(Protocol):
    @property
    def embedding_model(self) -> str: ...

    def sync(self, source: str) -> SyncResult: ...

    def search(
        self,
        query: str,
        limit: int,
        metadata_filter: dict[str, object] | None,
    ) -> list[SearchResult]: ...

    def recent_runs(self, limit: int) -> list[SyncRunRecord]: ...

    def status(self) -> StoreStatus: ...

    def operational_metrics(self) -> OperationalMetricsSnapshot: ...

    def close(self) -> None: ...


def make_api_document_source(value: str, allowed_local_root: Path) -> DocumentSource:
    """Create an S3 source or a local source confined to the configured root."""

    if value.startswith("s3://"):
        try:
            return S3DocumentSource(value)
        except S3SourceError as error:
            raise InvalidApiSourceError(str(error)) from error

    root = allowed_local_root.expanduser().resolve()
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate

    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as error:
        raise InvalidApiSourceError(
            "Local source must be an existing directory inside the configured API root."
        ) from error

    if not resolved.is_dir():
        raise InvalidApiSourceError("Local source must be a directory.")

    return LocalFolderSource(resolved)


class DefaultApiService:
    """Long-lived, thread-safe application services used by the HTTP API."""

    def __init__(
        self,
        settings: Settings,
        store: Store,
        embedder: EmbeddingProvider,
    ) -> None:
        self._settings = settings
        self._store = store
        self._embedder = embedder

    @classmethod
    def create(cls, settings: Settings) -> DefaultApiService:
        store = PgVectorStore(settings.database_url)
        try:
            store.initialize(settings.embedding_dimension)
        except Exception:
            store.close()
            raise

        embedder = LocalSentenceTransformerProvider(
            model_name=settings.embedding_model,
            expected_dimension=settings.embedding_dimension,
        )
        return cls(settings, store, embedder)

    @property
    def embedding_model(self) -> str:
        return self._embedder.model_name

    def sync(self, source: str) -> SyncResult:
        document_source = make_api_document_source(
            source,
            self._settings.api_allowed_local_root,
        )
        return SyncPipeline(
            store=self._store,
            chunker=RecursiveCharacterChunker(
                self._settings.chunk_size,
                self._settings.chunk_overlap,
            ),
            embedder=self._embedder,
            batch_size=self._settings.batch_size,
        ).sync(document_source)

    def search(
        self,
        query: str,
        limit: int,
        metadata_filter: dict[str, object] | None,
    ) -> list[SearchResult]:
        embeddings = self._embedder.embed([query])
        if len(embeddings) != 1:
            raise RuntimeError("Embedding provider did not return exactly one query vector")
        return self._store.search(
            query_embedding=embeddings[0],
            model_name=self._embedder.model_name,
            limit=limit,
            metadata_filter=metadata_filter,
        )

    def recent_runs(self, limit: int) -> list[SyncRunRecord]:
        return self._store.recent_runs(limit)

    def status(self) -> StoreStatus:
        return self._store.status()

    def operational_metrics(self) -> OperationalMetricsSnapshot:
        return self._store.operational_metrics()

    def close(self) -> None:
        self._store.close()


def _error(status_code: int, status: str, message: str, **extra: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": status, "error": message, **extra},
    )


def create_app(service: ApiService | None = None) -> FastAPI:
    owns_service = service is None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        resolved_service = service
        if resolved_service is None:
            settings = Settings()
            configure_logging(settings.log_level)
            resolved_service = DefaultApiService.create(settings)

        application.state.ragpipe_service = resolved_service
        try:
            yield
        finally:
            if owns_service:
                resolved_service.close()

    application = FastAPI(
        title="ragpipe API",
        description="Operate and inspect the ragpipe ingestion and retrieval pipeline.",
        version=__version__,
        lifespan=lifespan,
    )

    settings = Settings()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    def get_service(request: Request) -> ApiService:
        return cast(ApiService, request.app.state.ragpipe_service)

    @application.get("/api/v1/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(version=__version__)

    @application.get("/api/v1/status", response_model=StatusResponse)
    async def status(request: Request) -> StatusResponse | JSONResponse:
        try:
            value = await run_in_threadpool(get_service(request).status)
            return StatusResponse.model_validate(asdict(value))
        except Exception as error:
            log.error("api_status_failed", error=sanitize_error(error))
            return _error(503, "unavailable", "Could not read ragpipe status.")

    @application.get("/api/v1/runs", response_model=RunsResponse)
    async def runs(
        request: Request,
        limit: int = Query(default=10, ge=1, le=100),
    ) -> RunsResponse | JSONResponse:
        try:
            records = await run_in_threadpool(get_service(request).recent_runs, limit)
            return RunsResponse(
                limit=limit,
                count=len(records),
                runs=[SyncRunResponse.model_validate(asdict(record)) for record in records],
            )
        except Exception as error:
            log.error("api_runs_failed", error=sanitize_error(error))
            return _error(503, "unavailable", "Could not read synchronization history.")

    @application.get("/api/v1/metrics", response_model=OperationalMetricsResponse)
    async def metrics_json(request: Request) -> OperationalMetricsResponse | JSONResponse:
        try:
            snapshot = await run_in_threadpool(get_service(request).operational_metrics)
            return OperationalMetricsResponse.model_validate(asdict(snapshot))
        except Exception as error:
            log.error("api_metrics_failed", error=sanitize_error(error))
            return _error(503, "unavailable", "Could not read operational metrics.")

    @application.get("/metrics")
    async def metrics_prometheus(request: Request) -> Response:
        try:
            snapshot = await run_in_threadpool(get_service(request).operational_metrics)
            return Response(
                render_prometheus_metrics(snapshot),
                media_type=PROMETHEUS_CONTENT_TYPE,
            )
        except Exception as error:
            log.error("api_prometheus_metrics_failed", error=sanitize_error(error))
            return Response(
                "metrics unavailable\n",
                status_code=503,
                media_type="text/plain",
            )

    @application.post("/api/v1/search", response_model=SearchResponse)
    async def search(
        payload: SearchRequest,
        request: Request,
    ) -> SearchResponse | JSONResponse:
        current_service = get_service(request)
        metadata_filter = (
            None
            if payload.metadata_filter is None
            else cast(dict[str, object], payload.metadata_filter)
        )
        try:
            results = await run_in_threadpool(
                current_service.search,
                payload.query,
                payload.limit,
                metadata_filter,
            )
            return SearchResponse(
                query=payload.query,
                metadata_filter=payload.metadata_filter,
                embedding_model=current_service.embedding_model,
                count=len(results),
                results=[SearchResultResponse.model_validate(asdict(result)) for result in results],
            )
        except Exception as error:
            log.error("api_search_failed", error=sanitize_error(error))
            return _error(500, "search_failed", "Search failed.")

    @application.post("/api/v1/sync", response_model=SyncResponse)
    async def sync(
        payload: SyncRequest,
        request: Request,
    ) -> SyncResponse | JSONResponse:
        try:
            result = await run_in_threadpool(get_service(request).sync, payload.source)
            return SyncResponse.model_validate(asdict(result))
        except InvalidApiSourceError as error:
            return _error(400, "invalid_source", str(error))
        except SyncAlreadyRunningError as error:
            return _error(409, "busy", error.safe_message)
        except SyncFailedError as error:
            return _error(
                500,
                "failed",
                error.safe_message,
                run_id=error.run_id,
            )
        except SchemaNotReadyError:
            return _error(503, "schema_error", "Database schema is not ready.")
        except Exception as error:
            log.error("api_sync_failed", error=sanitize_error(error))
            return _error(500, "failed", "Synchronization failed.")

    return application


app = create_app()
