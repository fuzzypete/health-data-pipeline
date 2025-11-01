SHELL := /bin/bash

.PHONY: help install lock lint fmt test run ingest validate image dev-shell
.PHONY: ingest-concept2 ingest-concept2-recent ingest-concept2-all test-concept2

help:
	@echo "Targets:"
	@echo "  install          - poetry install (dev deps included)"
	@echo "  lock             - update poetry.lock"
	@echo "  lint             - ruff lint + black check"
	@echo "  fmt              - black format"
	@echo "  test             - pytest -q"
	@echo ""
	@echo "Ingestion:"
	@echo "  ingest-hae       - run HAE CSV ingestion"
	@echo "  ingest-concept2  - ingest last 50 Concept2 workouts"
	@echo "  ingest-concept2-recent - ingest last 10 workouts (quick)"
	@echo "  ingest-concept2-all    - ingest last 200 workouts (slow!)"
	@echo ""
	@echo "Testing:"
	@echo "  test-concept2    - test Concept2 API connection and processing"
	@echo "  validate         - run data validation checks"
	@echo ""
	@echo "Docker:"
	@echo "  image            - build Docker image (tag: hdp:dev)"
	@echo "  dev-shell        - open poetry shell"

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

# HAE CSV ingestion (existing)
ingest-hae:
	poetry run python -m pipeline.ingest.csv_delta

run: ingest-hae

ingest: ingest-hae

# Concept2 ingestion (NEW)
ingest-concept2:
	@echo "Ingesting last 50 Concept2 workouts..."
	poetry run python -m pipeline.ingest.concept2_api --limit 50

ingest-concept2-recent:
	@echo "Ingesting last 10 Concept2 workouts (quick sync)..."
	poetry run python -m pipeline.ingest.concept2_api --limit 10

ingest-concept2-all:
	@echo "Ingesting last 200 Concept2 workouts (this may take a while)..."
	poetry run python -m pipeline.ingest.concept2_api --limit 200

ingest-concept2-no-strokes:
	@echo "Ingesting workouts without stroke data (faster)..."
	poetry run python -m pipeline.ingest.concept2_api --limit 50 --no-strokes

test-concept2:
	@echo "Testing Concept2 API connection and data processing..."
	poetry run python test_concept2.py

# Validation
validate:
	poetry run python -c "from pipeline.validate.checks import validate_temporal_integrity as v; v()"

# Docker
image:
	docker build -t hdp:dev .

dev-shell:
	poetry shell
