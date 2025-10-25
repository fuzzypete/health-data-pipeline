# Health Data Pipeline — Design (Source of Truth)

**Schema Reference**
The canonical storage schema is maintained in `HealthDataPipelineSchema.md`.

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


### Daily Summary (wide)
- Write row if at least one metric exists; skip only if all missing.
- Units: imperial for hydration (`water_fl_oz` INT).
