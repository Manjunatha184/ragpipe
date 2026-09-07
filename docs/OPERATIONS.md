# Ragpipe operations runbook

This runbook covers deployment, scheduled synchronization, Prometheus serving, upgrades, backup, recovery, and incident checks. Adapt users, paths, source locations, and secret management to the target environment.

## Deployment assumptions

- Python 3.12 or newer
- PostgreSQL 16 with the pgvector extension
- Alembic migrations applied before application startup
- One PostgreSQL corpus per selected source
- A local folder or an `s3://bucket/prefix` source
- Database and cloud credentials supplied through a protected environment or workload identity

Ragpipe does not provide authentication, TLS termination, process supervision, PostgreSQL backup scheduling, or Prometheus itself.

## Required environment

Store production values in a secret manager or root-readable environment file. Do not commit them.

```dotenv
RAGPIPE_DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<database>
RAGPIPE_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RAGPIPE_EMBEDDING_DIMENSION=384
RAGPIPE_CHUNK_SIZE=800
RAGPIPE_CHUNK_OVERLAP=120
RAGPIPE_BATCH_SIZE=64
RAGPIPE_LOG_LEVEL=INFO
```

For S3, prefer an instance, task, pod, or workload role. The principal needs `s3:ListBucket` on the selected bucket and `s3:GetObject` under the selected prefix.

## Initial deployment

```bash
cd /opt/ragpipe
python3 -m venv .venv
./.venv/bin/pip install '.[local,s3]'
set -a
source /etc/ragpipe/ragpipe.env
set +a
./.venv/bin/alembic upgrade head
./.venv/bin/ragpipe status
```

For an immutable deployment, build the wheel in CI, copy the verified artifact to `/opt/ragpipe`, and install that wheel with its required extras instead of using an editable installation.

## Scheduled synchronization with systemd

Example `/etc/systemd/system/ragpipe-sync.service`:

```ini
[Unit]
Description=Synchronize Ragpipe document corpus
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ragpipe
Group=ragpipe
WorkingDirectory=/opt/ragpipe
EnvironmentFile=/etc/ragpipe/ragpipe.env
ExecStart=/opt/ragpipe/.venv/bin/ragpipe sync --source /srv/ragpipe/documents
```

For S3, replace the source with the intended `s3://bucket/prefix` URI.

Example `/etc/systemd/system/ragpipe-sync.timer`:

```ini
[Unit]
Description=Run Ragpipe synchronization every 15 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
Persistent=true
Unit=ragpipe-sync.service

[Install]
WantedBy=timers.target
```

Enable and inspect it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ragpipe-sync.timer
systemctl list-timers ragpipe-sync.timer
journalctl -u ragpipe-sync.service -n 100 --no-pager
```

The PostgreSQL advisory lock rejects overlapping synchronization attempts with exit code `3`. A scheduler may retry later; a rejected attempt does not modify the corpus.

## Prometheus exporter with systemd

Example `/etc/systemd/system/ragpipe-metrics.service`:

```ini
[Unit]
Description=Ragpipe Prometheus metrics exporter
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ragpipe
Group=ragpipe
WorkingDirectory=/opt/ragpipe
EnvironmentFile=/etc/ragpipe/ragpipe.env
ExecStart=/opt/ragpipe/.venv/bin/ragpipe serve-metrics --host 127.0.0.1 --port 9464
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

Enable and verify it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ragpipe-metrics.service
systemctl status ragpipe-metrics.service
curl --fail --silent --show-error http://127.0.0.1:9464/metrics >/dev/null
```

The exporter has no built-in authentication. It binds to loopback by default. For remote scraping, expose it only through controlled networking or a trusted reverse proxy that provides TLS and authentication.

Example Prometheus job on the same host:

```yaml
scrape_configs:
  - job_name: ragpipe
    scrape_interval: 15s
    static_configs:
      - targets: ["127.0.0.1:9464"]
```

## Upgrade procedure

1. Review `CHANGELOG.md` and new Alembic revisions.
2. Take and verify a PostgreSQL backup.
3. Stop scheduled synchronization and the metrics service.
4. Install the new package or checked-out commit.
5. Apply `alembic upgrade head`.
6. Run `ragpipe status`, `ragpipe metrics`, and one synchronization.
7. Restart and verify the services.

```bash
sudo systemctl stop ragpipe-sync.timer ragpipe-metrics.service
python -m alembic current
python -m alembic upgrade head
ragpipe status
ragpipe metrics >/dev/null
sudo systemctl start ragpipe-metrics.service ragpipe-sync.timer
```

Do not automatically downgrade a production schema during application rollback. Restore the previous application only after confirming schema compatibility. If a database rollback is required, use a tested backup and an explicit recovery plan.

## Backup and restore

Create a custom-format backup:

```bash
pg_dump \
  --format=custom \
  --file=/var/backups/ragpipe/ragpipe-$(date +%Y%m%d-%H%M%S).dump \
  "$RAGPIPE_DATABASE_URL"
```

Test restoration into a separate database rather than overwriting the active corpus:

```bash
createdb ragpipe_restore_test
pg_restore \
  --clean \
  --if-exists \
  --no-owner \
  --dbname=ragpipe_restore_test \
  /var/backups/ragpipe/<backup-file>.dump
```

After restoration, verify the Alembic revision, document/chunk counts, latest run, search, and metadata filtering before directing traffic to the restored database.

## Routine checks

```bash
ragpipe status
ragpipe runs --limit 10
ragpipe metrics
python -m alembic current
```

Monitor at least:

- Latest synchronization status and timestamp
- Failed synchronization count
- Time since the last successful run
- Sync duration and embedding duration
- Scanned document/byte changes
- Document and chunk gauges
- Unexpected increases in deletions or metadata changes

## Incident guide

| Symptom | Checks | Response |
| --- | --- | --- |
| Exit code `2` or schema error | `alembic current`, `alembic heads` | Back up the database and apply the required migration |
| Exit code `3` | Active scheduler/process and PostgreSQL sessions | Allow the current sync to finish, then retry |
| Failed sync | `ragpipe runs --limit 10`, service journal | Correct the source, credentials, model, or database problem; committed corpus remains unchanged |
| S3 access failure | Workload identity, bucket policy, prefix, region | Restore least-privilege `ListBucket` and `GetObject` access |
| S3 object changed during sync | Writer activity and object ETag | Retry after the upstream write completes |
| Search returns no results | Corpus status, model name/dimension, metadata filter | Synchronize the expected source and verify compatible embeddings/filters |
| Metrics returns `500` | Database connectivity and schema revision | Restore read access and verify `0005_operational_metrics` |
| Port already in use | `ss -ltnp`, service configuration | Select an unused port or stop the conflicting process |

## Security checklist

- Keep database passwords, `HF_TOKEN`, and cloud credentials out of Git.
- Prefer workload identities instead of static AWS keys.
- Restrict PostgreSQL and exporter network access.
- Use TLS for remote database and metrics connections.
- Protect environment files with operating-system permissions.
- Treat metadata filters as retrieval filters, not authorization.
- Put authentication and fail-closed authorization in any application exposing stored chunks.
- Pin and regularly update production container and Python dependency versions.
- Test backup restoration, not only backup creation.
- Review failed-run messages and logs before sharing them externally.

## Benchmarking

Use `scripts/generate_benchmark_corpus.py` only with a dedicated benchmark database. See `BENCHMARKS.md` for the measured development results, reproduction commands, limitations, and generator safety rules.
