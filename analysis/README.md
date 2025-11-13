# Analysis Directory

This directory contains all data analysis work - queries, scripts, dashboards, and notebooks.

## Structure

```
analysis/
├── queries/          # Reusable SQL queries
├── scripts/          # Python/bash analysis runners
├── outputs/          # Generated results (gitignored)
├── apps/             # Streamlit dashboards (when needed)
└── notebooks/        # Jupyter exploration (when needed)
```

## Quick Start

**Run recovery HR analysis:**
```bash
poetry run python analysis/scripts/run_hr_analysis.py
```

**With CSV export:**
```bash
poetry run python analysis/scripts/run_hr_analysis.py \
    --output analysis/outputs/recovery_weekly.csv
```

**Via Makefile:**
```bash
make analysis.hr
```

## Guidelines

**SQL Queries (`queries/`):**
- Reusable DuckDB queries
- Name: `{topic}_{purpose}.sql`
- Example: `recovery_baseline_hr.sql`

**Scripts (`scripts/`):**
- Analysis runners and report generators
- Name: `run_{analysis}.py`
- Example: `run_hr_analysis.py`

**Outputs (`outputs/`):**
- Generated CSVs, plots, reports
- Gitignored by default
- Name: `{analysis}_{date}.csv`
- Example: `recovery_weekly_20251112.csv`

**Apps (`apps/`):**
- Streamlit dashboards
- Name: `app_{purpose}.py`
- Example: `app_recovery_dashboard.py`

**Notebooks (`notebooks/`):**
- Exploratory Jupyter work
- Ad-hoc investigations
- Experimental analyses

## See Also

- [Analysis_Strategy.md](../docs/Analysis_Strategy.md) - Complete analysis plan
- [QUICK_REFERENCE.md](../QUICK_REFERENCE.md) - Command shortcuts
