SHELL := /bin/bash

.PHONY: help install lock lint fmt test run ingest validate image dev-shell
.PHONY: ingest-hae ingest-concept2 ingest-concept2-recent ingest-concept2-all test-concept2
.PHONY: all reload drop-parquet zipsrc show-ingest
.PHONY: backfill-lactate

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


# Backward-compatible shim; prefer `make ingest-hae`
#ingest-hae:
#	@echo "Deprecated: use make ingest-hae";
#	$(MAKE) ingest-hae

backfill-lactate:
	@echo "Backfilling lactate measurements from Concept2 comments..."
	poetry run python scripts/backfill_lactate.py

# Loads .env if present (keep your existing -include .env above)
export

# ---- Config (override in .env or on CLI) ----
GOOGLE_APPLICATION_CREDENTIALS ?= ~/.config/healthdatapipeline/hdpfetcher-key.json

HDP_LABS_FILE_NAME ?= AllLabsHistory.xlsx   # exact Drive filename (no folders)
HDP_LABS_FILE_ID   ?=                       # optional: if set, bypasses name search
HDP_LABS_FOLDER_ID ?=                       # optional: restrict search to a folder

HDP_OUT_LABS ?= Data/Raw/labs/labs-master-latest.xlsx

HDP_LABS_FILE_NAME := $(strip $(HDP_LABS_FILE_NAME))
HDP_LABS_FOLDER_ID := $(strip $(HDP_LABS_FOLDER_ID))
HDP_OUT_LABS       := $(strip $(HDP_OUT_LABS))

HDP_FOLDER_ARG := $(if $(HDP_LABS_FOLDER_ID),--folder-id $(HDP_LABS_FOLDER_ID),)

# Your project’s ingest command; override in .env if different
# Example:
#   HDP_LABS_INGEST_CMD=poetry run python -m pipeline.ingest.labs_excel --input "$(HDP_OUT_LABS)"
HDP_LABS_INGEST_CMD ?= poetry run python -m pipeline.ingest.labs_excel --input "$(HDP_OUT_LABS)"

.PHONY: labs.env labs.check labs.adc labs.fetch labs.fetch.id labs.fetch.any labs.ingest labs.all labs.clean

labs.env:
	@echo "GOOGLE_APPLICATION_CREDENTIALS=$(GOOGLE_APPLICATION_CREDENTIALS)"
	@echo "HDP_LABS_FILE_NAME=$(HDP_LABS_FILE_NAME)"
	@echo "HDP_LABS_FILE_ID=$(HDP_LABS_FILE_ID)"
	@echo "HDP_LABS_FOLDER_ID=$(HDP_LABS_FOLDER_ID)"
	@echo "HDP_OUT_LABS=$(HDP_OUT_LABS)"
	@echo "HDP_LABS_INGEST_CMD=$(HDP_LABS_INGEST_CMD)"

labs.check:
	@test -n "$(GOOGLE_APPLICATION_CREDENTIALS)" && test -f "$(GOOGLE_APPLICATION_CREDENTIALS)" || ( \
		echo "Missing SA key. Set GOOGLE_APPLICATION_CREDENTIALS to a valid file."; \
		exit 1 )

labs.adc: labs.check
	@poetry run gcloud auth application-default print-access-token >/dev/null && echo "ADC OK"

# Fetch by exact file name (recommended)
labs.fetch: labs.check
	@mkdir -p $(dir $(HDP_OUT_LABS))
	poetry run python scripts/hdp_drive_fetcher.py \
		--file-name "$(HDP_LABS_FILE_NAME)" \
		$(HDP_FOLDER_ARG) \
		--out "$(HDP_OUT_LABS)"
	@echo "Saved -> $(HDP_OUT_LABS)"

# Fetch by file ID (fastest; bypasses search)
labs.fetch.id: labs.check
	@test -n "$(HDP_LABS_FILE_ID)" || (echo "Set HDP_LABS_FILE_ID to a Drive file ID"; exit 1)
	@mkdir -p $(dir $(HDP_OUT_LABS))
	poetry run python scripts/hdp_drive_fetcher.py \
		--file-id "$(HDP_LABS_FILE_ID)" \
		--out "$(HDP_OUT_LABS)"
	@echo "Saved -> $(HDP_OUT_LABS)"

# Use whichever signal is provided (ID > name)
labs.fetch.any:
	@if [ -n "$(HDP_LABS_FILE_ID)" ]; then \
		$(MAKE) labs.fetch.id; \
	else \
		$(MAKE) labs.fetch; \
	fi

# Ingest
labs.ingest:
	@test -f "$(HDP_OUT_LABS)" || (echo "Missing input file: $(HDP_OUT_LABS). Run 'make labs.fetch' first." && exit 1)
	@echo "Ingesting $(HDP_OUT_LABS)…"
	@$(HDP_LABS_INGEST_CMD)

# End-to-end
labs.all: labs.fetch.any labs.ingest

# Clean local artifact
labs.clean:
	@rm -f "$(HDP_OUT_LABS)" && echo "Removed $(HDP_OUT_LABS)" || true

.PHONY: labs.debug
labs.debug:
	@echo "HDP_LABS_FILE_NAME=[[$(HDP_LABS_FILE_NAME)]]"
	@echo "HDP_LABS_FOLDER_ID=[[$(HDP_LABS_FOLDER_ID)]]"
	@echo "HDP_OUT_LABS=[[$(HDP_OUT_LABS)]]"

# --- DuckDB views setup ---
DUCKDB_FILE ?= Data/duck/health.duckdb
CREATE_VIEWS_SQL ?= scripts/sql/create-views.sql

.PHONY: duck.init duck.views duck.query

duck.init:
	@mkdir -p $(dir $(DUCKDB_FILE))
	@mkdir -p scripts/sql
	@test -f "$(CREATE_VIEWS_SQL)" || (echo "Missing $(CREATE_VIEWS_SQL). Create it first."; exit 1)
	@echo "Creating/initializing $(DUCKDB_FILE)…"
	poetry run duckdb "$(DUCKDB_FILE)" -init "$(CREATE_VIEWS_SQL)" -c "SELECT 'ok'"

duck.views:
	@test -f "$(CREATE_VIEWS_SQL)" || (echo "Missing $(CREATE_VIEWS_SQL)"; exit 1)
	@echo "Applying views from $(CREATE_VIEWS_SQL)…"
	poetry run duckdb "$(DUCKDB_FILE)" -init "$(CREATE_VIEWS_SQL)" -c "SELECT 'ok'"

# Ad-hoc query helper:
# Usage: make duck.query SQL="SELECT * FROM lake.labs LIMIT 20"
duck.query:
	@test -n "$(SQL)" || (echo 'Provide SQL="SELECT …"'; exit 1)
	poetry run duckdb "$(DUCKDB_FILE)" -c "$(SQL)"
