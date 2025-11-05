SHELL := /bin/bash

.PHONY: help install lock lint fmt test run ingest validate image dev-shell
.PHONY: ingest-hae ingest-concept2 ingest-concept2-recent ingest-concept2-all test-concept2
.PHONY: all reload drop-parquet zipsrc show-ingest

PYTHON       := poetry run python
MODULE_ROOT  := pipeline.ingest
PARQUET_DIR  := Data/Parquet
INGEST_TARGETS ?= ingest-hae ingest-concept2-all

install:
	poetry install --with dev

lock:
	poetry lock --no-update

lint:
	ruff check .
	black --check .

fmt:
	black .

test:
	pytest -q

run:
	$(PYTHON) -m $(MODULE_ROOT)

validate:
	$(PYTHON) -m $(MODULE_ROOT).validate

image:
	docker build -t hdp:dev .

dev-shell:
	poetry shell

### ------------------------------------------------------------
### Ingestion Targets
### ------------------------------------------------------------

ingest-hae:
	$(PYTHON) -m $(MODULE_ROOT).hae_csv

ingest-concept2:
	$(PYTHON) -m $(MODULE_ROOT).concept2_api --limit 50

ingest-concept2-recent:
	$(PYTHON) -m $(MODULE_ROOT).concept2_api --limit 10

ingest-concept2-all:
	$(PYTHON) -m $(MODULE_ROOT).concept2_api --limit 200

test-concept2:
	$(PYTHON) -m $(MODULE_ROOT).concept2_api --test

### ------------------------------------------------------------
### Aggregates + Maintenance
### ------------------------------------------------------------

# Show which ingestion targets will run
show-ingest:
	@echo "INGEST_TARGETS => $(INGEST_TARGETS)"

# Run every ingestion target listed in INGEST_TARGETS
all: show-ingest
	@set -e; \
	for t in $(INGEST_TARGETS); do \
		echo ""; \
		echo "=== Running $$t ==="; \
		$(MAKE) $$t; \
	done
	@echo ""; echo "✅ All ingestion completed."

# Safety: require CONFIRM=1 before deleting Parquet directory
drop-parquet:
	@{ [ "$(CONFIRM)" = "1" ] || { \
		echo "Refusing to remove $(PARQUET_DIR). Re-run with: make drop-parquet CONFIRM=1"; \
		exit 1; }; }
	@echo "Removing $(PARQUET_DIR)..."
	@rm -rf -- "$(PARQUET_DIR)"
	@echo "OK."

# Drop Parquet directory, then rerun all ingestion targets
reload: drop-parquet all

# Create a zipped snapshot of the source (code + config only)
zipsrc:
	@mkdir -p tmp
	@ts=$$(date +"%Y%m%d-%H%M"); \
	out="tmp/health-data-pipeline-src-$$ts.zip"; \
	echo "Creating $$out..."; \
	zip -r "$$out" . \
		-x "*.git*" \
		-x "tmp/*" \
		-x "__pycache__/*" \
		-x "*.pyc" \
		-x "Data/*" \
		-x "out/*" \
		-x "Raw/*" \
		-x "*.parquet" \
		-x "*.csv" \
		-x "*.json" \
		-x "*.log"
	@echo "✅ Source-only archive created in tmp/"

### ------------------------------------------------------------
### Help
### ------------------------------------------------------------

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
	@echo "  ingest-concept2-all    - ingest last 200 workouts (slow)"
	@echo ""
	@echo "Aggregates:"
	@echo "  all              - run bundled ingestion targets ($(INGEST_TARGETS))"
	@echo "  reload           - drop parquet and then run all (requires CONFIRM=1)"
	@echo ""
	@echo "Testing:"
	@echo "  test-concept2    - test Concept2 API connection"
	@echo "  validate         - run validation checks"
	@echo ""
	@echo "Docker:"
	@echo "  image            - build Docker image (tag: hdp:dev)"
	@echo "  dev-shell        - poetry shell"
	@echo ""
	@echo "Utilities:"
	@echo "  zipsrc           - zip source into ./tmp/"
	@echo "  drop-parquet     - remove $(PARQUET_DIR) (requires CONFIRM=1)"
