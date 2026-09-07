# Release checklist

Use this checklist for version `0.2.0`.

## Repository

- [ ] Working tree contains only intended release changes.
- [ ] Version is `0.2.0` in `pyproject.toml` and `ragpipe/__init__.py`.
- [ ] `CHANGELOG.md`, `README.md`, `OPERATIONS.md`, and `BENCHMARKS.md` are current.
- [ ] No generated benchmark corpus, build artifact, cache, environment file, or credential is staged.
- [ ] `git diff --check` reports no whitespace errors.

## Verification

- [ ] `python -m ruff format --check .`
- [ ] `python -m ruff check .`
- [ ] `python -m mypy ragpipe`
- [ ] Full tests pass with `RAGPIPE_TEST_DATABASE_URL` configured.
- [ ] `python -m alembic heads` reports one head.
- [ ] Upgrade from an empty database reaches the current head.
- [ ] `python -m build` produces the source archive and wheel.
- [ ] The wheel installs in a clean virtual environment.
- [ ] `ragpipe --help`, `ragpipe status`, and `ragpipe metrics` work from that environment.
- [ ] Local first sync and unchanged sync behave correctly.
- [ ] `/metrics` returns `200`; an unknown path returns `404`.

## Security and operations

- [ ] Staged changes contain no database passwords, tokens, AWS keys, or private endpoints.
- [ ] S3 documentation uses placeholders and least-privilege permissions.
- [ ] Metrics bind to loopback by default.
- [ ] Backup and restore instructions have been reviewed.
- [ ] Operational limitations remain explicit.

## GitHub release

- [ ] Pull request CI passes.
- [ ] The pull request is reviewed and merged into `main`.
- [ ] Local `main` is fast-forwarded from `origin/main`.
- [ ] Tag `v0.2.0` points to the merge commit on `main`.
- [ ] The tag is pushed to GitHub.
- [ ] GitHub release notes summarize the `0.2.0` changelog.
- [ ] Merged feature branches are removed locally and remotely.
