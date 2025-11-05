# Health Data Pipeline

This pipeline ingests Apple Health Auto Export (HAE) CSVs, Concept2 workouts, and more into Parquet (month-partitioned).

## Quickstart
```bash
poetry install --with dev
make help
```
**Common**
- `make ingest-hae` — ingest HAE CSVs
- `make ingest-concept2` / `make ingest-concept2-all`
- `make all` — bundled ingestions (`INGEST_TARGETS`)
- `make reload CONFIRM=1` — drop Parquet then rebuild
- `make zipsrc` — source-only zip to ./tmp/

See `Deployment.md` for GCS + BigQuery.
