SHELL := /bin/bash

.PHONY: help install lock lint fmt test run ingest validate image dev-shell

help:
	@echo "Targets:"
	@echo "  install   - poetry install (dev deps included)"
	@echo "  lock      - update poetry.lock"
	@echo "  lint      - ruff lint + black check"
	@echo "  fmt       - black format"
	@echo "  test      - pytest -q"
	@echo "  run       - run CSV ingestion (no-op if no files)"
	@echo "  ingest    - run CSV ingestion"
	@echo "  validate  - run basic validations (warnings only)"
	@echo "  image     - build Docker image (tag: hdp:dev)"
	@echo "  dev-shell - open poetry shell"

install:
	poetry install

lock:
	poetry lock

lint:
	poetry run ruff check .
	poetry run black --check .

fmt:
	poetry run black .

test:
	poetry run pytest -q

run:
	poetry run python -m health_pipeline.ingest.csv_delta

ingest:
	poetry run python -m health_pipeline.ingest.csv_delta

validate:
	poetry run python -c "from health_pipeline.validate.checks import validate_temporal_integrity as v; v()"

image:
	docker build -t hdp:dev .

dev-shell:
	poetry shell
