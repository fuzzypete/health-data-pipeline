SHELL := /bin/bash

# Load environment variables from .env if present
-include .env
export

# ============================================================================
# Configuration
# ============================================================================

PYTHON       := poetry run python
MODULE_ROOT  := pipeline.ingest
PARQUET_DIR  := Data/Parquet
DUCKDB_FILE  ?= Data/duck/health.duckdb

# Default ingestion targets for 'make all'
# This now fetches from Drive first, then runs all ingestions
INGEST_TARGETS ?= fetch-all ingest-hae ingest-concept2-all ingest-jefit ingest-labs ingest-protocols

# NOTE: All HDP_... (Drive config) variables have been removed.
# They are now read by the fetch script from config.yaml and .env

# ============================================================================
# Development Environment
# ============================================================================

.PHONY: help install lock lint fmt test validate image dev-shell

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
	poetry run pytest -q

validate:
	$(PYTHON) -m $(MODULE_ROOT).validate

image:
	docker build -t hdp:dev .

dev-shell:
	poetry shell

# ============================================================================
# Data Ingestion
# ============================================================================

.PHONY: ingest-hae ingest-concept2 ingest-concept2-recent ingest-concept2-all test-concept2
.PHONY: ingest-jefit ingest-jefit-file test-jefit backfill-lactate
.PHONY: ingest-labs ingest-protocols
.PHONY: all reload show-ingest check-parquet

# --- HAE (Apple Health Export) ---

ingest-hae:
	$(PYTHON) -m $(MODULE_ROOT).hae_csv

# --- Concept2 (Rowing/Biking) ---

ingest-concept2:
	$(PYTHON) -m $(MODULE_ROOT).concept2_api --limit 50

ingest-concept2-recent:
	$(PYTHON) -m $(MODULE_ROOT).concept2_api --limit 10

ingest-concept2-all:
	$(PYTHON) -m $(MODULE_ROOT).concept2_api --limit 200

test-concept2:
	$(PYTHON) -m $(MODULE_ROOT).concept2_api --test

backfill-lactate:
	@echo "Backfilling lactate measurements from Concept2 comments..."
	poetry run python scripts/backfill_lactate.py

# --- JEFIT (Resistance Training) ---

ingest-jefit:
	@test -d "Data/Raw/JEFIT" || mkdir -p "Data/Raw/JEFIT"
	@latest=$$(ls -t Data/Raw/JEFIT/*.csv 2>/dev/null | head -1); \
	if [ -z "$$latest" ]; then \
		echo "❌ No JEFIT CSV found in Data/Raw/JEFIT/"; \
		echo "   Export from JEFIT app and place here."; \
		exit 1; \
	fi; \
	echo "Using latest: $$latest"; \
	$(PYTHON) -m $(MODULE_ROOT).jefit_csv "$$latest"

ingest-jefit-file:
	@test -n "$(FILE)" || (echo "Usage: make ingest-jefit-file FILE=path/to/export.csv" && exit 1)
	$(PYTHON) -m $(MODULE_ROOT).jefit_csv "$(FILE)"

test-jefit:
	$(PYTHON) scratch/test_jefit_ingestion.py

# --- Labs & Protocols (from downloaded Excel) ---

ingest-labs:
	@echo "Ingesting Labs from downloaded Excel file..."
	$(PYTHON) -m pipeline.ingest.labs_excel

ingest-protocols:
	@echo "Ingesting Protocols from downloaded Excel file..."
	$(PYTHON) -m pipeline.ingest.protocol_excel

# --- Aggregates & Utilities ---

show-ingest:
	@echo "INGEST_TARGETS => $(INGEST_TARGETS)"

all: show-ingest
	@set -e; \
	for t in $(INGEST_TARGETS); do \
		echo ""; \
		echo "=== Running $$t ==="; \
		$(MAKE) $$t; \
	done
	@echo ""; \
	echo "✅ All ingestion completed."

reload: drop-parquet all

check-parquet:
	@echo "Checking Parquet table status..."
	@$(PYTHON) check_parquet_status.py

# ============================================================================
# Google Drive Fetching (NEW UNIFIED SECTION)
# ============================================================================

.PHONY: fetch-all fetch-labs fetch-protocols fetch-hae

FETCH_SCRIPT := scripts/fetch_drive_sources.py

fetch-all:
	@echo "Fetching all Google Drive sources defined in config.yaml..."
	$(PYTHON) $(FETCH_SCRIPT)

fetch-labs:
	@echo "Fetching 'labs' source from Google Drive..."
	$(PYTHON) $(FETCH_SCRIPT) labs

fetch-protocols:
	@echo "Fetching 'protocols' source from Google Drive..."
	$(PYTHON) $(FETCH_SCRIPT) protocols

fetch-hae:
	@echo "Fetching all HAE sources (hae_csv, hae_json, hae_quick) from Google Drive..."
	$(PYTHON) $(FETCH_SCRIPT) hae_csv hae_json hae_quick

# ============================================================================
# Labs (Google Drive sync + ingestion)  <-- THIS SECTION IS NOW REMOVED
# ============================================================================
# (All old labs.* targets are gone)

# ============================================================================
# DuckDB (Local query engine)
# ============================================================================

.PHONY: duck.init duck.views duck.query

CREATE_VIEWS_SQL ?= scripts/sql/create-views.sql

duck.init:
	@mkdir -p $(dir $(DUCKDB_FILE))
	@mkdir -p scripts/sql
	@test -f "$(CREATE_VIEWS_SQL)" || (echo "❌ Missing $(CREATE_VIEWS_SQL). Create it first."; exit 1)
	@echo "Creating/initializing $(DUCKDB_FILE)…"
	poetry run duckdb "$(DUCKDB_FILE)" -init "$(CREATE_VIEWS_SQL)" -c "SELECT 'ok'"

duck.views:
	@test -f "$(CREATE_VIEWS_SQL)" || (echo "❌ Missing $(CREATE_VIEWS_SQL)"; exit 1)
	@echo "Applying views from $(CREATE_VIEWS_SQL)…"
	poetry run duckdb "$(DUCKDB_FILE)" -init "$(CREATE_VIEWS_SQL)" -c "SELECT 'ok'"

# Usage: make duck.query SQL="SELECT * FROM lake.labs LIMIT 20"
duck.query:
	@test -n "$(SQL)" || (echo 'Usage: make duck.query SQL="SELECT …"'; exit 1)
	poetry run duckdb "$(DUCKDB_FILE)" -c "$(SQL)"

# ============================================================================
# Maintenance & Utilities
# ============================================================================

.PHONY: drop-parquet zipsrc

drop-parquet:
	@{ [ "$(CONFIRM)" = "1" ] || { \
		echo "❌ Refusing to remove $(PARQUET_DIR)."; \
		echo "   Re-run with: make drop-parquet CONFIRM=1"; \
		exit 1; }; }
	@echo "Removing $(PARQUET_DIR)..."
	@rm -rf -- "$(PARQUET_DIR)"
	@echo "✅ Done."

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
	@echo "✅ Source-only archive created: $$out"

# ============================================================================
# Help
# ============================================================================

help:
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "Health Data Pipeline - Makefile Targets"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "Development:"
	@echo "  install          - Install dependencies with Poetry"
	@echo "  lock             - Update poetry.lock"
	@echo "  lint             - Run ruff + black checks"
	@echo "  fmt              - Format code with black"
	@echo "  test             - Run pytest"
	@echo "  validate         - Run data validation checks"
	@echo "  dev-shell        - Open Poetry shell"
	@echo ""
	@echo "Ingestion - Primary:"
	@echo "  ingest-hae              - Ingest HAE (Apple Health) CSV data from Data/Raw/HAE/CSV/"
	@echo "  ingest-concept2         - Ingest last 50 Concept2 workouts via API"
	@echo "  ingest-concept2-recent  - Ingest last 10 workouts (quick test)"
	@echo "  ingest-concept2-all     - Ingest last 200 workouts (full sync)"
	@echo "  ingest-jefit            - Ingest latest JEFIT CSV from Data/Raw/JEFIT/"
	@echo "  ingest-jefit-file       - Ingest specific file: FILE=path/to/export.csv"
	@echo "  ingest-labs             - Ingest downloaded Labs Excel file -> Parquet"
	@echo "  ingest-protocols        - Ingest downloaded Protocols Excel file -> Parquet"
	@echo ""
	@echo "Ingestion - Google Drive (Fetch):"
	@echo "  fetch-all               - Fetch all sources from Google Drive defined in config.yaml"
	@echo "  fetch-labs              - Fetch 'labs' source from Google Drive"
	@echo "  fetch-protocols         - Fetch 'protocols' source from Google Drive"
	@echo "  fetch-hae               - Fetch all HAE sources (hae_csv, hae_json, hae_quick) from Drive"
	@echo ""
	@echo "Ingestion - Utilities:"
	@echo "  all              - Run all default targets: $(INGEST_TARGETS)"
	@echo "  show-ingest      - Show which targets will run in 'make all'"
	@echo "  check-parquet    - Check which Parquet tables exist + row counts"
	@echo "  backfill-lactate - Extract lactate from Concept2 comments"
	@echo "  reload           - Drop all Parquet data + re-ingest (CONFIRM=1)"
	@echo ""
	@echo "Testing:"
	@echo "  test-concept2    - Test Concept2 API connection"
	@echo "  test-jefit       - Test JEFIT CSV parsing"
	@echo ""
	@echo "DuckDB (Query Engine):"
	@echo "  duck.init        - Initialize DuckDB database"
	@echo "  duck.views       - Apply/refresh views from SQL"
	@echo "  duck.query       - Run query: SQL=\"SELECT * FROM lake.labs\""
	@echo ""
	@echo "Utilities:"
	@echo "  drop-parquet     - Delete $(PARQUET_DIR) (requires CONFIRM=1)"
	@echo "  zipsrc           - Create source-only ZIP in ./tmp/"
	@echo "  image            - Build Docker image (tag: hdp:dev)"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "Quick Start:"
	@echo "  1. make install"
	@echo "  2. Configure .env with GOOGLE_APPLICATION_CREDENTIALS and HDP_... folder IDs"
	@echo "  3. make all          # Fetch all data from Drive AND run all ingestions"
	@echo "  4. make check-parquet # Verify data loaded"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"