# Ragpipe benchmarks

This document records reproducible performance checks for Ragpipe. The numbers are observations from one development machine, not universal performance guarantees.

## Environment

- Date: 2026-09-07
- Machine: Lenovo ThinkPad T470
- Python: 3.13.7
- Database: PostgreSQL 16 with pgvector in Docker
- Embedding model: `sentence-transformers/all-MiniLM-L6-v2`, running locally
- Corpus: 100 deterministic text documents
- Document size: 4,096 bytes each (409,600 bytes total)
- Chunk configuration: 800 characters with 120-character overlap
- Generated chunks: 700
- Configured embedding batch size: 64

The first model use in each CLI process includes model initialization. Hugging Face authentication was not configured during these runs.

## Results

| Scenario | Documents scanned | Changed state | Chunks embedded/deleted | Provider calls | Pipeline duration | CLI wall time |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| Initial load before cross-document batching | 100 | 100 new | 700 embedded | 100 | 45.918 s | 47.34 s |
| Initial load after cross-document batching | 100 | 100 new | 700 embedded | 11 | 48.881 s | 50.56 s |
| Unchanged corpus after batching | 100 | 100 unchanged | 0 | 0 | 18.146 ms | 0.57 s |
| One content change | 99 | 1 changed, 98 unchanged | 7 embedded and 7 deleted | 1 | 12.085 s | 13.53 s |
| One deletion | 99 | 1 deleted, 99 unchanged | 7 deleted | 0 | 18.047 ms | 0.55 s |

Cross-document batching reduced embedding-provider calls from 100 to 11, an 89% reduction. It did not improve local CPU runtime in this single comparison because the same 700 vectors still had to be calculated and Sentence Transformers also performs internal batching. The small runtime difference is normal run-to-run variation; no throughput improvement is claimed from these two samples.

Fewer provider calls still matter operationally. They reduce per-request overhead for remote providers, make configured batching apply across document boundaries, and provide better control over rate limits. The implementation streams completed document batches into the existing database transaction instead of retaining embeddings for the entire corpus in memory.

The unchanged and deletion cases demonstrate the main incremental property: scanning and database reconciliation complete without loading the embedding model or generating vectors.

## Reproducing the benchmark

Use a dedicated database. Never point a benchmark at a development or production corpus because every selected source is treated as the complete corpus for that database.

Create and migrate a benchmark database:

```bash
docker compose exec -T postgres \
  createdb -U <user> ragpipe_benchmark

export RAGPIPE_DATABASE_URL="postgresql://<user>:<password>@localhost:5432/ragpipe_benchmark"
python -m alembic upgrade head
```

Generate a new corpus. The generator refuses to overwrite an existing output path:

```bash
python scripts/generate_benchmark_corpus.py \
  --output ./benchmark_docs_100 \
  --documents 100 \
  --size-bytes 4096 \
  --extension txt
```

Measure an initial and unchanged synchronization:

```bash
/usr/bin/time -f "INITIAL_SYNC_WALL_SECONDS=%e" \
  ragpipe sync --source ./benchmark_docs_100

/usr/bin/time -f "UNCHANGED_SYNC_WALL_SECONDS=%e" \
  ragpipe sync --source ./benchmark_docs_100

ragpipe runs --limit 2
```

Record the machine, Python version, model, corpus parameters, chunk configuration, result counters, internal duration, and wall time when publishing new results. Use several runs before making throughput comparisons.

## Generator safety limits

`scripts/generate_benchmark_corpus.py`:

- Creates deterministic `.txt` or `.md` documents.
- Writes an exact byte size for each document.
- Accepts between 1 and 10,000 documents.
- Limits each document to 10 MiB.
- Refuses any output path that already exists, including a symlink.
- Never deletes benchmark files or databases.

Cleanup is deliberately manual so that benchmark evidence is not destroyed accidentally. Confirm exact paths and database names before removing them.
