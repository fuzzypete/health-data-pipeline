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

# --- Date Variables ---
# Default API lookback for 'make all' - reasonable window for catching up
API_LOOKBACK_DAYS ?= 7
START_DATE   ?= $(shell date -d '$(API_LOOKBACK_DAYS) days ago' +%Y-%m-%d)
END_DATE     ?= $(shell date +%Y-%m-%d)
REBUILD_START_DATE ?= $(shell date -d '5 years ago' +%Y-%m-%d)

# --- DuckDB Configuration ---
PROJECT_ROOT     := $(shell pwd)
PARQUET_ABS_PATH := $(PROJECT_ROOT)/$(PARQUET_DIR)
SQL_TEMPLATE     := scripts/sql/create-views.sql.template
SQL_RUN_FILE     := scripts/sql/.create_views_run.sql
FETCH_SCRIPT     := scripts/fetch_drive_sources.py

# ============================================================================
# Help
# ============================================================================

.PHONY: help

help:
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "Health Data Pipeline - Makefile Targets"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "📊 Primary Workflows:"
	@echo "  all              - Comprehensive ingestion ($(API_LOOKBACK_DAYS)-day API lookback)"
	@echo "                     Fetches latest HAE, processes all local data, $(API_LOOKBACK_DAYS)-day APIs"
	@echo "  weekly           - Weekly update: Non-quick HAE + Labs + Protocols + 7-day APIs"
	@echo "  reload           - Drop all Parquet data + re-run 'all' (requires CONFIRM=1)"
	@echo "  rebuild-history  - Nuclear option: Fetch ALL history + re-process everything"
	@echo ""
	@echo "🔧 Development:"
	@echo "  install          - Install dependencies with Poetry"
	@echo "  lock             - Update poetry.lock"
	@echo "  lint             - Run ruff + black checks"
	@echo "  fmt              - Format code with black"
	@echo "  test             - Run pytest"
	@echo "  validate         - Validate Parquet data lake integrity"
	@echo "  dev-shell        - Open Poetry shell"
	@echo ""
	@echo "📥 Individual Ingestion (HAE):"
	@echo "  ingest-hae              - Process HAE Automation CSVs (HealthMetrics-...)"
	@echo "  ingest-hae-quick        - Process HAE Quick Export CSVs (HealthAutoExport-...)"
	@echo "  ingest-hae-workouts     - Process HAE Workout JSON"
	@echo ""
	@echo "📥 Individual Ingestion (APIs):"
	@echo "  ingest-concept2         - Ingest Concept2 (default: $(API_LOOKBACK_DAYS)-day lookback)"
	@echo "  ingest-concept2-history - Ingest Concept2 history (5 years, no strokes)"
	@echo "  ingest-oura             - Ingest Oura data (requires fetch-oura first)"
	@echo "  fetch-oura              - Fetch Oura data (default: $(API_LOOKBACK_DAYS)-day lookback)"
	@echo ""
	@echo "📥 Individual Ingestion (Local):"
	@echo "  ingest-jefit            - Ingest latest JEFIT CSV from Data/Raw/JEFIT/"
	@echo "  ingest-jefit-file       - Ingest specific file: FILE=path/to/export.csv"
	@echo "  ingest-labs             - Ingest Labs Excel → Parquet"
	@echo "  ingest-protocols        - Ingest Protocols Excel → Parquet"
	@echo ""
	@echo "☁️  Google Drive Fetching:"
	@echo "  fetch-daily             - Fetch daily HAE automated exports"
	@echo "  fetch-all               - Fetch ALL sources from Google Drive"
	@echo "  fetch-labs              - Fetch Labs Excel from Drive"
	@echo "  fetch-protocols         - Fetch Protocols Excel from Drive"
	@echo "  fetch-hae               - Fetch all HAE sources (daily + quick)"
	@echo "  fetch-hae-daily         - Fetch daily HAE automated exports"
	@echo "  fetch-hae-quick         - Fetch quick HAE manual exports"
	@echo ""
	@echo "🦆 DuckDB (Query Engine):"
	@echo "  duck.init        - Initialize DuckDB database"
	@echo "  duck.views       - Apply/refresh views from SQL"
	@echo "  duck.query       - Run query: SQL=\"SELECT * FROM lake.labs\""
	@echo ""
	@echo "🛠️  Utilities:"
	@echo "  check-parquet    - Check Parquet table status + row counts"
	@echo "  backfill-lactate - Extract lactate from Concept2 comments"
	@echo "  drop-parquet     - Delete $(PARQUET_DIR) (requires CONFIRM=1)"
	@echo "  zipsrc           - Create source-only ZIP in ./tmp/"
	@echo "  image            - Build Docker image (tag: hdp:dev)"
	@echo ""
	@echo "📈 Training Analysis:"
	@echo "  training.weekly  - Generate weekly training report (runs full pipeline)"
	@echo "  training.plan    - Generate recovery-adjusted training plan"
	@echo "  sleep.metrics    - Calculate sleep debt from Oura data"
	@echo "  progression      - Analyze JEFIT strength progression"
	@echo ""
	@echo "💾 Backup (rclone):"
	@echo "  backup           - Backup Data/Raw to Google Drive (alias for backup.raw)"
	@echo "  backup.raw       - Backup Data/Raw to Google Drive"
	@echo "  backup.full      - Backup Raw + Parquet to Drive"
	@echo "  backup.list      - List backup directories in Drive"
	@echo ""
	@echo "🚀 Deployment:"
	@echo "  deploy.refresh   - Copy Data/Parquet → deploy/data for Streamlit"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "Quick Start:"
	@echo "  1. make install"
	@echo "  2. Configure config.yaml and .env"
	@echo "  3. make all                    # Comprehensive ingestion"
	@echo "  4. make all API_LOOKBACK_DAYS=3   # Minimal daily update"
	@echo "  5. make check-parquet          # Verify data loaded"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ============================================================================
# Development Environment
# ============================================================================

.PHONY: install lock lint fmt test validate image dev-shell

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
# Primary Ingestion Workflows
# ============================================================================

.PHONY: all weekly reload rebuild-history

all:
	@echo "=================================================================="
	@echo "📊 COMPREHENSIVE INGESTION ($(API_LOOKBACK_DAYS)-day API lookback)"
	@echo "=================================================================="
	
	@# Fetch all HAE sources from Drive
	@echo ""
	@echo "--- [1/8] Fetching HAE from Drive ---"
	@$(MAKE) fetch-hae-daily fetch-hae-quick
	
	@# Process all local HAE data
	@echo ""
	@echo "--- [2/8] HAE Daily (Automation) ---"
	@$(MAKE) ingest-hae
	
	@echo ""
	@echo "--- [3/8] HAE Quick (Manual) ---"
	@$(MAKE) ingest-hae-quick
	
	@echo ""
	@echo "--- [4/8] HAE Workouts ---"
	@$(MAKE) ingest-hae-workouts
	
	@# API sources with lookback window
	@echo ""
	@echo "--- [5/8] Concept2 ($(API_LOOKBACK_DAYS)-day lookback) ---"
	@$(MAKE) ingest-concept2 START_DATE=$(START_DATE)
	
	@echo ""
	@echo "--- [6/8] Oura ($(API_LOOKBACK_DAYS)-day lookback) ---"
	@$(MAKE) fetch-oura ingest-oura START_DATE=$(START_DATE)
	
	@# Local sources
	@echo ""
	@echo "--- [7/8] JEFIT ---"
	@$(MAKE) ingest-jefit
	
	@echo ""
	@echo "--- [8/8] Labs & Protocols ---"
	@$(MAKE) fetch-labs ingest-labs fetch-protocols ingest-protocols
	
	@echo ""
	@echo "✅ All ingestion completed ($(API_LOOKBACK_DAYS)-day window)."

weekly:
	@echo "=================================================================="
	@echo "📅 WEEKLY INGESTION"
	@echo "   - Scope: Non-quick HAE, Labs, Protocols (Supps)"
	@echo "   - Lookback: 7 days for Oura & Concept2"
	@echo "=================================================================="
	
	@# Non-Quick HAE (Daily Metrics + Workouts)
	@echo ""
	@echo "--- [1/5] HAE Daily (Non-Quick) ---"
	@$(MAKE) fetch-hae-daily
	@$(MAKE) ingest-hae
	@$(MAKE) ingest-hae-workouts

	@# Labs
	@echo ""
	@echo "--- [2/5] Labs ---"
	@$(MAKE) fetch-labs
	@$(MAKE) ingest-labs

	@# Protocols
	@echo ""
	@echo "--- [3/5] Protocols (Supplements) ---"
	@$(MAKE) fetch-protocols
	@$(MAKE) ingest-protocols

	@# Oura (Last 7 Days)
	@echo ""
	@echo "--- [4/5] Oura (7-day lookback) ---"
	@$(MAKE) fetch-oura ingest-oura START_DATE=$(shell date -d '7 days ago' +%Y-%m-%d)

	@# Concept2 (Last 7 Days)
	@echo ""
	@echo "--- [5/5] Concept2 (7-day lookback) ---"
	@$(MAKE) ingest-concept2 START_DATE=$(shell date -d '7 days ago' +%Y-%m-%d)

	@echo ""
	@echo "✅ Weekly ingest complete."

reload: drop-parquet all

rebuild-history:
	@echo "--- 1/7: Dropping entire Parquet data lake ---"
	@$(MAKE) drop-parquet CONFIRM=1

	@echo "--- 2/7: Unarchiving local raw files from Data/Archive ---"
	@$(MAKE) unarchive

	@echo "--- 3/7: Fetching ALL historical G-Drive sources (Labs, Protocols, HAE) ---"
	@$(MAKE) fetch-all

	@echo "--- 4/7: Fetching ALL historical API data (from 2020-01-01) ---"
	@echo "Fetching Oura history..."
	@$(MAKE) fetch-oura START_DATE=2020-01-01
	@echo "Fetching Concept2 history..."
	@$(MAKE) ingest-concept2-history REBUILD_START_DATE=2020-01-01

	@echo "--- 5/7: Ingesting all fetched data into Parquet ---"
	@$(MAKE) ingest-hae ingest-hae-quick ingest-hae-workouts
	@$(MAKE) ingest-oura ingest-jefit ingest-labs ingest-protocols

	@echo "--- 6/7: Rebuilding DuckDB views ---"
	@$(MAKE) duck.views

	@echo "--- 7/7: Validating rebuilt data lake ---"
	@$(MAKE) validate
	@echo ""
	@echo "✅ --- Historical rebuild complete! ---"

# ============================================================================
# Individual Ingestion Targets
# ============================================================================

.PHONY: ingest-hae ingest-hae-quick ingest-hae-workouts 
.PHONY: ingest-concept2 ingest-concept2-history
.PHONY: fetch-oura ingest-oura ingest-jefit ingest-jefit-file test-jefit backfill-lactate
.PHONY: ingest-labs ingest-protocols

# --- HAE (Apple Health Export) ---

ingest-hae:
	@echo "Ingesting HAE Automation CSV (HealthMetrics-...)..."
	$(PYTHON) -m $(MODULE_ROOT).hae_csv

ingest-hae-quick:
	@echo "Ingesting HAE Quick Export CSV (HealthAutoExport-...)..."
	$(PYTHON) -m $(MODULE_ROOT).hae_quick_csv

ingest-hae-workouts:
	@echo "Ingesting HAE Workout JSON (Strategy B)..."
	$(PYTHON) -m $(MODULE_ROOT).hae_workouts

# --- Concept2 (Rowing/Biking) ---

ingest-concept2:
	@echo "Ingesting Concept2 workouts from $(START_DATE) to $(END_DATE)..."
	$(PYTHON) -m $(MODULE_ROOT).concept2_api --from-date $(START_DATE) --to-date $(END_DATE)

ingest-concept2-history:
	@echo "Ingesting Concept2 HISTORY from $(REBUILD_START_DATE) to $(END_DATE)..."
	$(PYTHON) -m $(MODULE_ROOT).concept2_api --from-date $(REBUILD_START_DATE) --to-date $(END_DATE)

backfill-lactate:
	@echo "Backfilling lactate measurements from Concept2 comments..."
	poetry run python scripts/backfill_lactate.py

# --- Oura ---

ingest-oura: 
	@echo "Ingesting Oura JSON into Parquet oura_summary..."
	$(PYTHON) -m $(MODULE_ROOT).oura_json

fetch-oura:
	@echo "Fetching Oura data from $(START_DATE)..."
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

# ============================================================================
# Google Drive Fetching
# ============================================================================

.PHONY: fetch-daily fetch-all fetch-labs fetch-protocols fetch-hae fetch-hae-daily fetch-hae-quick

# Default for quick updates
fetch-daily:
	@echo "Fetching Daily HAE sources (automated exports)..."
	$(PYTHON) $(FETCH_SCRIPT) hae_daily_metrics hae_daily_workouts

# Manual target for full historical pulls
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

# Generate SQL script with absolute paths
$(SQL_RUN_FILE): $(SQL_TEMPLATE)
	@echo "--- Generating SQL script with absolute paths ---"
	@sed 's|__PARQUET_DIR__|$(PARQUET_ABS_PATH)|g' $(SQL_TEMPLATE) > $(SQL_RUN_FILE)
	@echo "✅ Generated: $(SQL_RUN_FILE)"

duck.init: $(SQL_RUN_FILE)
	@echo "--- Initializing DuckDB at $(DUCKDB_FILE) ---"
	@mkdir -p $(dir $(DUCKDB_FILE))
	@$(PYTHON) -c "import duckdb; duckdb.connect('$(DUCKDB_FILE)').execute('SELECT 1').fetchall(); print('✅ DuckDB initialized')"
	@$(MAKE) duck.views

duck.views: $(SQL_RUN_FILE)
	@echo "--- Applying views from $(SQL_RUN_FILE) ---"
	@duckdb $(DUCKDB_FILE) < $(SQL_RUN_FILE)
	@echo "✅ Views applied"

duck.query:
	@test -n "$(SQL)" || (echo "Usage: make duck.query SQL=\"SELECT * FROM lake.labs LIMIT 5\"" && exit 1)
	@duckdb $(DUCKDB_FILE) "$(SQL)"

# ============================================================================
# Backup (via rclone)
# ============================================================================

BACKUP_REMOTE := gdrive:Personal/Health/Data/HDP/Backups

.PHONY: backup backup.raw backup.full backup.list

backup: backup.raw

backup.raw:
	@echo "--- Backing up Data/Raw to Google Drive ---"
	rclone copy Data/Raw "$(BACKUP_REMOTE)/Raw" --progress

backup.full:
	@echo "--- Backing up Data/Raw + Parquet to Google Drive ---"
	rclone copy Data/Raw "$(BACKUP_REMOTE)/Raw" --progress
	rclone copy Data/Parquet "$(BACKUP_REMOTE)/Parquet" --progress

backup.list:
	@echo "--- Listing backups in Google Drive ---"
	rclone lsd "$(BACKUP_REMOTE)"

# ============================================================================
# Analysis Scripts
# ============================================================================

.PHONY: sleep.metrics progression training.plan training.weekly

sleep.metrics:
	@echo "--- Calculating sleep metrics ---"
	$(PYTHON) analysis/scripts/calculate_sleep_metrics.py

progression:
	@echo "--- Analyzing strength progression ---"
	$(PYTHON) analysis/scripts/calculate_progression.py

training.plan:
	@echo "--- Generating recovery-adjusted training plan ---"
	@$(MAKE) sleep.metrics
	@$(MAKE) progression
	$(PYTHON) analysis/scripts/calculate_training_mode.py

training.weekly:
	@echo "--- Generating weekly training report ---"
	@$(MAKE) training.plan
	$(PYTHON) analysis/scripts/generate_weekly_report.py

# ============================================================================
# Dashboard
# ============================================================================

.PHONY: dashboard

dashboard:
	@echo "--- Launching HDP Dashboard ---"
	cd analysis/apps && poetry run streamlit run hdp_dashboard.py

# ============================================================================
# Deployment
# ============================================================================

.PHONY: deploy.refresh

deploy.refresh:
	@echo "--- Refreshing deploy/data from Data/Parquet ---"
	@rm -rf deploy/data/workouts deploy/data/cardio_splits deploy/data/resistance_sets \
		deploy/data/oura_summary deploy/data/labs deploy/data/lactate deploy/data/protocol_history \
		deploy/data/cardio_strokes
	@mkdir -p deploy/data
	@cp -r Data/Parquet/workouts deploy/data/
	@cp -r Data/Parquet/cardio_splits deploy/data/
	@cp -r Data/Parquet/resistance_sets deploy/data/
	@cp -r Data/Parquet/oura_summary deploy/data/
	@cp -r Data/Parquet/labs deploy/data/
	@cp -r Data/Parquet/lactate deploy/data/
	@cp -r Data/Parquet/protocol_history deploy/data/
	@cp -r Data/Parquet/cardio_strokes deploy/data/
	@echo "✅ deploy/data refreshed"

# ============================================================================
# Utilities
# ============================================================================

.PHONY: check-parquet drop-parquet zipsrc unarchive

check-parquet:
	@echo "Checking Parquet table status..."
	@$(PYTHON) scripts/check_parquet_status.py

drop-parquet:
	@if [ "$(CONFIRM)" != "1" ]; then \
		echo "⚠️  This will delete ALL Parquet data!"; \
		echo "   Run: make drop-parquet CONFIRM=1"; \
		exit 1; \
	fi
	@echo "🗑️  Dropping $(PARQUET_DIR)..."
	@rm -rf $(PARQUET_DIR)
	@echo "✅ Parquet directory cleared"

unarchive:
	@echo "Unarchiving Data/Archive → Data/Raw..."
	@if [ -d "Data/Archive" ]; then \
		rsync -av Data/Archive/ Data/Raw/; \
		echo "✅ Unarchive complete"; \
	else \
		echo "ℹ️  No Data/Archive directory found"; \
	fi

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