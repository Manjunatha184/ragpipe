.PHONY: install test lint typecheck check build
install:
	python -m pip install -e '.[local,dev]'
test:
	pytest
lint:
	ruff check .
	ruff format --check .
typecheck:
	mypy ragpipe
check: lint typecheck test
build:
	python -m build

