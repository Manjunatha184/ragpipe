# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog, and versions follow Semantic Versioning.

## [0.2.0] - 2026-09-07

### Added

- PostgreSQL advisory locking for concurrent synchronization protection.
- Cosine vector search with deterministic ranking and an HNSW index.
- JSONB document metadata, metadata-only synchronization, containment filters, and a GIN index.
- Retrieval evaluation with Hit Rate@K and MRR@K.
- Persisted operational run history, source-volume statistics, and embedding timing.
- Prometheus text rendering, a one-shot `metrics` command, and an HTTP `/metrics` exporter.
- A `DocumentSource` abstraction with local-folder and Amazon S3 implementations.
- Strict S3 URI handling, pagination, exact content hashing, conditional reads, and metadata manifests.
- A safe deterministic benchmark-corpus generator and reproducible benchmark documentation.
- Production operations guidance for scheduling, monitoring, backup, restore, upgrades, and incidents.

### Changed

- Embedding batches now span document boundaries while retaining bounded memory and atomic rollback behavior.
- Embedding-provider output cardinality is validated before a document replacement is written.
- CLI and synchronization errors use bounded credential sanitization.
- Database schema ownership is enforced through versioned Alembic migrations.

### Security

- S3 source URIs reject credentials, queries, fragments, and unsafe traversal paths.
- Local document loading is restricted to the configured source root.
- Prometheus labels avoid unbounded source and run identifiers.
- The metrics exporter binds to loopback by default and hides collection errors from clients.

## [0.1.0] - 2026-09-03

### Added

- Incremental local PDF, Markdown, and text ingestion using SHA-256 content hashes.
- Recursive character chunking and a pluggable embedding-provider interface.
- Local Sentence Transformers embeddings.
- PostgreSQL and pgvector document/chunk storage with cascade deletion.
- Atomic, idempotent new/change/delete synchronization.
- Typer CLI, Docker Compose development database, tests, packaging, and CI.
