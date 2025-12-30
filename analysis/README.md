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

## Script Index

See **[scripts/SCRIPT_INDEX.md](scripts/SCRIPT_INDEX.md)** for a complete list of all analysis scripts with usage examples.

**Common scripts:**
| Script | Purpose |
|--------|---------|
| `analyze_interval_session.py` | 30/30 interval analysis with trending |
| `generate_weekly_report.py` | Weekly training report |
| `calculate_sleep_metrics.py` | Sleep debt calculator |
| `run_hr_analysis.py` | HR baseline analysis |

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
