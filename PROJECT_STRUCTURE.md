# HDP Project Structure

**Last Updated:** 2025-11-12  
**Version:** 2.4 (Added analysis/)

---

## Overview

```
health-data-pipeline/
│
├── Data/                              # Data storage (gitignored)
│   ├── Parquet/                       # Parquet lake (source of truth)
│   │   ├── minute_facts/
│   │   ├── workouts/
│   │   ├── cardio_splits/
│   │   ├── cardio_strokes/
│   │   ├── resistance_sets/
│   │   ├── labs/
│   │   ├── protocol_history/
│   │   └── ...
│   ├── Raw/                           # Raw ingestion files
│   │   ├── HAE/
│   │   ├── Labs/
│   │   └── JEFIT/
│   └── duck/                          # DuckDB persistent views
│       └── health.duckdb
│
├── src/                               # Core pipeline logic
│   └── pipeline/
│       ├── common/
│       ├── hae/
│       ├── concept2/
│       ├── jefit/
│       ├── oura/
│       └── labs/
│
├── scripts/                           # Pipeline operations
│   ├── validate_parquet_tables.py     # Data validation
│   ├── fetch_drive_sources.py         # Data fetching
│   ├── backfill_lactate.py            # Data backfilling
│   └── sql/                           # DuckDB view definitions
│       └── create-views.sql.template
│
├── analysis/                          # Analysis & insights (NEW)
│   ├── queries/                       # Reusable SQL
│   │   └── recovery_baseline_hr.sql
│   ├── scripts/                       # Analysis runners
│   │   ├── run_hr_analysis.py
│   │   └── run_hr_analysis.sh
│   ├── outputs/                       # Generated results (gitignored)
│   │   └── .gitkeep
│   ├── apps/                          # Streamlit dashboards
│   ├── notebooks/                     # Jupyter exploration
│   └── README.md
│
├── docs/                              # Documentation
│   ├── Architecture.md
│   ├── DataSources.md
│   ├── Schema.md
│   ├── TimestampHandling.md
│   ├── StorageAndQuery.md
│   ├── Deployment.md
│   ├── decisions/
│   └── archive/
│
├── tests/                             # Unit/integration tests
│
├── .gitignore
├── Makefile
├── pyproject.toml
├── poetry.lock
└── README.md
```

---

## Directory Purposes

### `/Data` - Data Storage
**Owner:** Pipeline  
**Purpose:** All data artifacts  
**Gitignored:** Yes (too large, machine-specific)

- `Parquet/` - Source of truth, normalized tables
- `Raw/` - Unprocessed ingestion files
- `duck/` - DuckDB view layer (optional, for convenience)

### `/src/pipeline` - Core Logic
**Owner:** Pipeline  
**Purpose:** Reusable ingestion/transformation code  
**When to modify:** Adding data sources, changing schemas

- Installed as package: `from pipeline.hae import HAEIngestion`
- Tested via `/tests`
- Production-grade code

### `/scripts` - Pipeline Operations
**Owner:** Pipeline  
**Purpose:** Scripts that modify or manage the Parquet lake  
**When to use:** Validation, backfilling, fetching, repair

**Examples:**
- Validate Parquet tables
- Fetch latest data from sources
- Backfill historical data
- Repair corrupted partitions
- Generate DuckDB views

**Naming pattern:** `{verb}_{noun}.py`
- `validate_parquet_tables.py`
- `fetch_drive_sources.py`
- `backfill_lactate.py`

### `/analysis` - Data Analysis (NEW)
**Owner:** Analysis  
**Purpose:** Scripts that query and analyze the Parquet lake  
**When to use:** Insights, reports, dashboards, exploration

**Subdirectories:**

#### `/analysis/queries`
Reusable SQL queries for DuckDB.

**Examples:**
- `recovery_baseline_hr.sql` - HR metrics since compound cessation
- `zone2_power_trends.sql` - Zone 2 power progression
- `historical_depletion.sql` - Timeline of iron depletion

**Naming pattern:** `{topic}_{purpose}.sql`

#### `/analysis/scripts`
Python/bash runners that execute analyses.

**Examples:**
- `run_hr_analysis.py` - Execute HR baseline query
- `run_z2_analysis.py` - Zone 2 power analysis
- `generate_weekly_report.py` - Automated weekly summary

**Naming pattern:** `run_{analysis}.py`

#### `/analysis/outputs`
Generated results (CSVs, plots, HTML reports).

**Gitignored:** Yes (regeneratable)  
**Examples:**
- `recovery_weekly_20251112.csv`
- `hr_trend_chart.png`
- `weekly_report_20251112.html`

**Naming pattern:** `{analysis}_{date}.{ext}`

#### `/analysis/apps`
Streamlit dashboards for interactive exploration.

**Created when needed** (not yet)  
**Examples:**
- `app_recovery_dashboard.py` - Real-time recovery tracking
- `app_training_capacity.py` - Training capacity monitoring

**Naming pattern:** `app_{purpose}.py`

#### `/analysis/notebooks`
Jupyter notebooks for exploratory work.

**Created when needed** (not yet)  
**Examples:**
- `exploration_20251112.ipynb` - Ad-hoc investigation
- `correlation_studies.ipynb` - Statistical analysis

### `/docs` - Documentation
**Owner:** Both  
**Purpose:** Living documentation and decision logs

- `Architecture.md`, `Schema.md`, etc. - Core reference docs
- `decisions/` - Why we made specific choices
- `archive/` - Historical versions

### `/tests` - Test Suite
**Owner:** Pipeline  
**Purpose:** Unit and integration tests for core logic

---

## Decision: `scripts/` vs `analysis/`

**Rule of thumb:** If it modifies Parquet → `scripts/`, if it queries Parquet → `analysis/`

| Task | Directory | Rationale |
|------|-----------|-----------|
| Ingest new HAE data | `scripts/` | Modifying Parquet |
| Validate Parquet schemas | `scripts/` | Checking Parquet integrity |
| Query workout trends | `analysis/` | Reading Parquet |
| Generate weekly report | `analysis/` | Reading Parquet |
| Backfill missing data | `scripts/` | Modifying Parquet |
| Build recovery dashboard | `analysis/` | Reading Parquet |
| Repair corrupted partitions | `scripts/` | Modifying Parquet |
| Statistical correlation study | `analysis/` | Reading Parquet |

**Grey area:** Creating DuckDB views (`scripts/sql/`) touches both. We keep it in `scripts/` because it's infrastructure, not analysis.

---

## File Organization Principles

### 1. Single Responsibility
Each script does one thing well:
- ✅ `validate_parquet_tables.py` - validates tables
- ✅ `run_hr_analysis.py` - runs HR analysis
- ❌ `do_everything.py` - does validation, analysis, reporting

### 2. Descriptive Naming
File names should be self-documenting:
- ✅ `recovery_baseline_hr.sql` - clear purpose
- ❌ `query1.sql` - meaningless
- ✅ `run_hr_analysis.py` - obvious what it does
- ❌ `script.py` - too generic

### 3. Consistent Patterns
Follow established conventions:
- Scripts: `{verb}_{noun}.py`
- Queries: `{topic}_{purpose}.sql`
- Apps: `app_{purpose}.py`
- Outputs: `{analysis}_{date}.{ext}`

### 4. Separate Concerns
Don't mix pipeline operations with analysis:
- Pipeline code: deterministic, idempotent, production-grade
- Analysis code: exploratory, iterative, hypothesis-driven

---

## Makefile Integration

### Pipeline Targets
```bash
make ingest-hae         # Ingest HAE data
make ingest-concept2    # Ingest Concept2 data
make validate           # Validate Parquet tables
make duck.init          # Initialize DuckDB
make duck.views         # Refresh DuckDB views
```

### Analysis Targets
```bash
make analysis.hr        # Run recovery HR analysis
make analysis.z2        # Run Zone 2 analysis
make analysis.clean     # Clean output files
```

---

## Adding New Analysis

**Example: Add lactate trend analysis**

1. **Create SQL query:**
   ```bash
   touch analysis/queries/lactate_trends.sql
   # Write query to extract lactate readings over time
   ```

2. **Create runner script:**
   ```bash
   touch analysis/scripts/run_lactate_analysis.py
   # Write Python script that executes query and generates output
   ```

3. **Add Makefile target:**
   ```makefile
   analysis.lactate:
       poetry run python analysis/scripts/run_lactate_analysis.py
   ```

4. **Test it:**
   ```bash
   make analysis.lactate
   ```

5. **Document it:**
   Update `Analysis_Strategy.md` with new analysis entry.

---

## Gitignore Patterns

```gitignore
# Data (too large, machine-specific)
Data/

# Analysis outputs (regeneratable)
analysis/outputs/*
!analysis/outputs/.gitkeep

# Jupyter checkpoints
analysis/notebooks/.ipynb_checkpoints/

# Python cache
__pycache__/
*.pyc
.pytest_cache/

# Environment
.env
```

---

## Evolution History

### v2.4 (2025-11-12)
- Added `analysis/` directory structure
- Separated analysis work from pipeline operations
- Established naming conventions
- Integrated with Makefile

### v2.3 (2025-11-10)
- Finalized documentation structure
- Added decision logs
- Curated living docs

### v2.2 (2025-11-05)
- Completed core pipeline implementation
- All 10 tables validated

---

## See Also

- [Analysis_Strategy.md](docs/Analysis_Strategy.md) - Complete analysis plan
- [QUICK_REFERENCE.md](QUICK_REFERENCE.md) - Command shortcuts
- [README.md](README.md) - Project overview

---

**Maintained By:** Peter Kahaian  
**Review Cycle:** Update when structure changes
