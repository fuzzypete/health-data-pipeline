# Health Data Pipeline

Poetry + Docker project for ingesting personal health data (HAE CSV) into partitioned Parquet datasets.

## Quick Start
```bash
poetry install
cp .env.example .env
mkdir -p Data/Raw/CSV Data/Archive/CSV
poetry run python -m health_pipeline.ingest.csv_delta
```

## Docs (Markdown is Source of Truth)
- Architecture: `docs/HealthDataPipelineArchitecture.md`
- Design: `docs/HealthDataPipelineDesign.md`


## Pipeline Outputs
- Data/Parquet/minute_facts/
- Data/Parquet/daily_summary/ (wide daily; includes water_fl_oz INT, imperial)
- Data/Parquet/workouts/
