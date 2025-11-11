SHELL := /bin/bash

# Load environment variables from .env if present
-include .env
export

# ============================================================================
# Configuration
# ============================================================================

PYTHON       := poetry run python
MODULE_ROOT  := src.pipeline.ingest
PARQUET_DIR  := Data/Parquet
DUCKDB_FILE  ?= Data/duck/health.duckdb

# --- New Date Variables ---
START_DATE   ?= $(shell date -d '3 days ago' +%Y-%m-%d) # Default: 3 days ago
END_DATE     ?= $(shell date +%Y-%m-%d)
REBUILD_START_DATE ?= $(shell date -d '5 years ago' +%Y-%m-%d)

# Default ingestion targets for 'make all'
# UPDATED to use 'fetch-daily' (fast) instead of 'fetch-all' (slow)
INGEST_TARGETS ?= fetch-daily ingest-hae ingest-hae-quick ingest-hae-workouts ingest-concept2 ingest-oura ingest-jefit ingest-labs ingest-protocols

# ============================================================================
# Development Environment
# ============================================================================

.PHONY: help install lock lint fmt test validate image dev-shell

install:
	poetry install --with dev

lock:
	poetry lock --no-update

lint:
	poetry run ruff check .
	poetry run black --check .

fmt:
	poetry run ruff check . --fix
	poetry run black .

test:
	poetry run pytest -q

validate:
	@echo "--- Validating Parquet data lake integrity ---"
	$(PYTHON) scripts/validate_parquet_tables.py

image:
	docker build -t hdp:dev .

dev-shell:
	poetry shell

# ============================================================================
# Data Ingestion
# ============================================================================

.PHONY: ingest-hae ingest-hae-quick ingest-hae-workouts 
.PHONY: ingest-concept2 ingest-concept2-history
.PHONY: fetch-oura ingest-oura ingest-jefit ingest-jefit-file test-jefit backfill-lactate
.PHONY: ingest-labs ingest-protocols
.PHONY: all reload show-ingest check-parquet

# --- HAE (Apple Health Export) ---

ingest-hae:
	@echo "--- Ingesting HAE Automation CSV (HealthMetrics-...) ---"
	$(PYTHON) -m $(MODULE_ROOT).hae_csv

ingest-hae-quick:
	@echo "--- Ingesting HAE Quick Export CSV (HealthAutoExport-...) ---"
	$(PYTHON) -m $(MODULE_ROOT).hae_quick_csv

ingest-hae-workouts:
	@echo "--- Ingesting HAE Workout JSON (Strategy B) ---"
	$(PYTHON) -m $(MODULE_ROOT).hae_workouts

# --- Concept2 (Rowing/Biking) ---

# Default 3-day lookback
ingest-concept2:
	@echo "--- Ingesting Concept2 workouts from $(START_DATE) to $(END_DATE) ---"
	$(PYTHON) -m $(MODULE_ROOT).concept2_api --from-date $(START_DATE) --to-date $(END_DATE)

# 5-year lookback for rebuilds
ingest-concept2-history:
	@echo "--- Ingesting Concept2 HISTORY from $(REBUILD_START_DATE) to $(END_DATE) ---"
	$(PYTHON) -m $(MODULE_ROOT).concept2_api --from-date $(REBUILD_START_DATE) --to-date $(END_DATE) --no-strokes

backfill-lactate:
	@echo "Backfilling lactate measurements from Concept2 comments..."
	poetry run python scripts/backfill_lactate.py

# --- Oura ---

ingest-oura: fetch-oura
	@echo "--- Ingesting Oura JSON into Parquet oura_summary ---"
	$(PYTHON) -m $(MODULE_ROOT).oura_json

fetch-oura:
	@echo "--- Fetching Oura data (from $(START_DATE)) ---"
	@poetry run python scripts/fetch_oura_history.py --start-date $(START_DATE)

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
	$(PYTHON) -m $(MODULE_ROOT).labs_excel

ingest-protocols:
	@echo "Ingesting Protocols from downloaded Excel file..."
	$(PYTHON) -m $(MODULE_ROOT).protocol_excel

# --- Aggregates & Utilities ---

.PHONY: rebuild-history
rebuild-history: # This is a placeholder, as your old one was broken
	@echo "--- Running FULL historical rebuild ---"
	@echo "Step 1: Fetching ALL Google Drive history (daily, quick, labs, etc)..."
	$(MAKE) fetch-all
	@echo "Step 2: Fetching ALL Concept2 history..."
	$(MAKE) ingest-concept2-history
	@echo "Step 3: Running all processing scripts..."
	@set -e; \
	for t in $(DAILY_INGEST_TARGETS); do \
		echo ""; \
		echo "=== Running $$t ==="; \
		$(MAKE) $$t; \
	done
	@echo "--- 🚀 Historical rebuild complete! ---"	


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
	@$(PYTHON) scripts/check_parquet_status.py

# ============================================================================
# Google Drive Fetching (NEW UNIFIED SECTION)
# ============================================================================

.PHONY: fetch-daily fetch-all fetch-labs fetch-protocols fetch-hae

FETCH_SCRIPT := scripts/fetch_drive_sources.py

# --- NEW ---
# Default for 'make all'. Fetches only daily automated exports.
fetch-daily:
	@echo "Fetching Daily HAE sources (automated exports)..."
	$(PYTHON) $(FETCH_SCRIPT) hae_daily_metrics hae_daily_workouts

# --- MODIFIED ---
# Manual target for full historical pulls.
fetch-all:
	@echo "Fetching ALL Google Drive sources defined in config.yaml..."
	$(PYTHON) $(FETCH_SCRIPT)

fetch-labs:
	@echo "Fetching 'labs' source from Google Drive..."
	$(PYTHON) $(FETCH_SCRIPT) labs

fetch-protocols:
	@echo "Fetching 'protocols' source from Google Drive..."
	$(PYTHON) $(FETCH_SCRIPT) protocols

fetch-hae-daily:
	@echo "Fetching Daily HAE sources (automated exports)..."
	$(PYTHON) $(FETCH_SCRIPT) hae_daily_metrics hae_daily_workouts

fetch-hae-quick:
	@echo "Fetching Quick HAE sources (manual exports)..."
	$(PYTHON) $(FETCH_SCRIPT) hae_quick_metrics hae_quick_workouts

fetch-hae:
	@echo "Fetching all HAE sources from Google Drive..."
	$(PYTHON) $(FETCH_SCRIPT) hae_daily_metrics hae_daily_workouts hae_quick_metrics hae_quick_workouts

# ============================================================================
# DuckDB (Local query engine)
# ============================================================================

.PHONY: duck.init duck.views duck.query

# --- THIS IS THE ROBUST DuckDB SECTION ---
PROJECT_ROOT     := $(shell pwd)
PARQUET_ABS_PATH := $(PROJECT_ROOT)/$(PARQUET_DIR)

# Source template and the temporary, generated SQL file
SQL_TEMPLATE     := scripts/sql/create-views.sql.template
SQL_RUN_FILE     := scripts/sql/.create_views_run.sql

# This rule generates the SQL script with absolute paths
# It is a prerequisite for duck.init and duck.views
$(SQL_RUN_FILE): $(SQL_TEMPLATE)
	@echo "--- Generating SQL script with absolute paths ---"
	@# Use a delimiter that's not in a file path (like '|')
	@sed 's|__PARQUET_ROOT__|$(PARQUET_ABS_PATH)|g' $(SQL_TEMPLATE) > $(SQL_RUN_FILE)

duck.init: $(SQL_RUN_FILE)
	@mkdir -p $(dir $(DUCKDB_FILE))
	@echo "Creating/initializing $(DUCKDB_FILE)…"
	@# Run duckdb from the project root, so all paths are correct
	poetry run duckdb "$(DUCKDB_FILE)" -init "$(SQL_RUN_FILE)" -c "SELECT 'ok'"
	@rm -f $(SQL_RUN_FILE)

duck.views: $(SQL_RUN_FILE)
	@echo "Applying views from generated SQL script..."
	@# Run duckdb from the project root
	poetry run duckdb "$(DUCKDB_FILE)" -init "$(SQL_RUN_FILE)" -c "SELECT 'ok'"
	@rm -f $(SQL_RUN_FILE)

# Usage: make duck.query SQL="SELECT * FROM lake.labs LIMIT 20"
duck.query:
	@test -n "$(SQL)" || (echo 'Usage: make duck.query SQL="SELECT …"'; exit 1)
	@# Run query from project root
	poetry run duckdb "$(DUCKDB_FILE)" -c "$(SQL)"
# --- END NEW DuckDB SECTION ---

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

unarchive:
	@echo "--- ♻️  Moving all archived files back to Data/Raw/ ---"
	@# Create directories just in case they were deleted
	@mkdir -p Data/Raw/HAE/CSV Data/Raw/HAE/JSON Data/Raw/HAE/Quick
	@mkdir -p Data/Raw/JEFIT Data/Raw/Concept2 Data/Raw/labs
	@mkdir -p Data/Raw/Oura/sleep Data/Raw/Oura/activity Data/Raw/Oura/readiness
	
	@# Move files, suppressing errors if source directory is empty
	@echo "Unarchiving HAE CSV..."
	@mv Data/Archive/HAE/CSV/* Data/Raw/HAE/CSV/ 2>/dev/null || true
	@echo "Unarchiving HAE JSON..."
	@mv Data/Archive/HAE/JSON/* Data/Raw/HAE/JSON/ 2>/dev/null || true
	@echo "Unarchiving HAE Quick..."
	@mv Data/Archive/HAE/Quick/* Data/Raw/HAE/Quick/ 2>/dev/null || true
	@echo "Unarchiving JEFIT..."
	@mv Data/Archive/JEFIT/* Data/Raw/JEFIT/ 2>/dev/null || true
	@echo "Unarchiving Concept2..."
	@mv Data/Archive/Concept2/* Data/Raw/Concept2/ 2>/dev/null || true
	@echo "Unarchiving Labs..."
	@mv Data/Archive/labs/* Data/Raw/labs/ 2>/dev/null || true
	@echo "Unarchiving Oura..."
	@mv DataData/Archive/Oura/sleep/* Data/Raw/Oura/sleep/ 2>/dev/null || true
	@mv Data/Archive/Oura/activity/* Data/Raw/Oura/activity/ 2>/dev/null || true
	@mv Data/Archive/Oura/readiness/* Data/Raw/Oura/readiness/ 2>/dev/null || true
	@echo "✅ Unarchive complete."

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
	@echo "  ingest-hae              - Ingest HAE Automation CSVs (HealthMetrics-...) from Data/Raw/HAE/CSV/"
	@echo "  ingest-hae-quick        - Ingest HAE Quick Export CSVs (HealthAutoExport-...) from Data/Raw/HAE/Quick/"
	@echo "  ingest-hae-workouts     - Ingest HAE Workout JSON from Data/Raw/HAE/JSON/"
	@echo "  ingest-concept2         - Ingest Concept2 workouts from last 3 days"
	@echo "  ingest-concept2-history - Ingest Concept2 workouts from last 5 years (no strokes)"
	@echo "  ingest-oura             - Fetch & Ingest Oura data (from $$START_DATE)"
	@echo "  fetch-oura              - Fetch Oura data without ingesting"
	@echo "  ingest-jefit            - Ingest latest JEFIT CSV from Data/Raw/JEFIT/"
	@echo "  ingest-jefit-file       - Ingest specific file: FILE=path/to/export.csv"
	@echo "  ingest-labs             - Ingest downloaded Labs Excel file -> Parquet"
	@echo "  ingest-protocols        - Ingest downloaded Protocols Excel file -> Parquet"
	@echo ""
	@echo "Ingestion - Google Drive (Fetch):"
	@echo "  fetch-daily             - (DEFAULT FOR 'all') Fetch daily HAE sources from Google Drive"
	@echo "  fetch-all               - (MANUAL) Fetch ALL sources from Google Drive defined in config.yaml"
	@echo "  fetch-labs              - Fetch 'labs' source from Google Drive"
	@echo "  fetch-protocols         - Fetch 'protocols' source from GoogleDrive"
	@echo "  fetch-hae               - Fetch all HAE sources from Google Drive"
	@echo "  fetch-hae-daily         - Fetch Daily HAE sources (CSV + JSON)"
	@echo "  fetch-hae-quick         - Fetch Quick HAE sources (CSV + JSON)"
	@echo ""
	@echo "Ingestion - Utilities:"
	@echo "  all              - Run all default targets: $(INGEST_TARGETS)"
	@echo "  show-ingest      - Show which targets will run in 'make all'"
	@echo "  check-parquet    - Check which Parquet tables exist + row counts"
	@echo "  backfill-lactate - Extract lactate from Concept2 comments"
	@echo "  reload           - Drop all Parquet data + re-ingest (CONFIRM=1)"
	@echo "  rebuild-history  - Fetch ALL history and re-process all data"
	@echo ""
	@echo "Testing:"
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
	@echo "  2. Configure config.yaml and .env with your settings and IDs"
	@echo "  3. make all          # Fetch daily data from Drive AND run all ingestions"
	@echo "  4. make check-parquet # Verify data loaded"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"