# Health Data Pipeline — Design (Source of Truth)

## Schemas
- `minute_facts` partitioned by `date_utc` with PK `timestamp_utc`
- `daily_summary` partitioned by `date` (lenient emission)
- Future: workout tables (header/splits/samples)

## Algorithms
- Column normalization: explicit HAE→canonical mappings + snake_case fallback
- DST-safe UTC conversion using previous-UTC disambiguation
- Idempotent partitioned writes with overwrite_or_ignore
- Lenient daily aggregation (only when inputs exist)

## Validation
- Temporal monotonicity, duplicate detection, DST day counts (fixtures later)

## Paths
- Inputs: Data/Raw/CSV/HealthAutoExport-*.csv
- Outputs: Data/Parquet/{minute_facts,daily_summary}/...
- Archive/Error routing
