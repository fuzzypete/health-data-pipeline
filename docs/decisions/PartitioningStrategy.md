# Decision: Partitioning Strategy

**Date:** 2024-10-15  
**Status:** Implemented  
**Impact:** High (affects all silver tables)

## Context

Parquet tables need partitioning for query performance and maintainability. We evaluated daily vs monthly partitioning for high-volume tables like HAE minute-level data and Concept2 stroke data.

## Problem

High-volume tables generate massive numbers of files:
- **HAE heart rate:** ~1.4M rows/month, ~17M rows/year
- **Concept2 strokes:** ~20k rows/workout, hundreds of workouts/year
- **Daily partitioning:** 365 partitions/year/table × multiple years = thousands of files
- **PyArrow limit:** Max 10,000 partitions in a dataset

With daily partitioning across multiple years and tables, we quickly hit PyArrow's partition limit.

## Options Considered

### Option 1: Daily Partitioning
```
hae_heart_rate_minute/
    year=2024/month=10/day=01/data.parquet
    year=2024/month=10/day=02/data.parquet
    ...
```

**Pros:**
- Finest granularity
- Very fast for single-day queries
- Easy to delete specific days

**Cons:**
- **Hits PyArrow 10k partition limit** with 5+ years of data
- Thousands of small files (poor I/O performance)
- High filesystem metadata overhead
- Slower for month/year range queries (must scan many files)

### Option 2: Monthly Partitioning
```
hae_heart_rate_minute/
    year=2024/month=10/data.parquet
    year=2024/month=11/data.parquet
    ...
```

**Pros:**
- **Avoids partition limit** (12 partitions/year)
- Fewer, larger files (better I/O)
- Still fast for date-range queries
- Simpler directory structure

**Cons:**
- Single-day queries must scan entire month (~1M rows)
- Still reasonable with columnar format + filters

### Option 3: Yearly Partitioning
```
hae_heart_rate_minute/
    year=2024/data.parquet
    year=2023/data.parquet
```

**Pros:**
- Minimal partitions
- Very simple

**Cons:**
- **Too coarse** - scans entire year for monthly analysis
- Multi-GB files become unwieldy
- Reprocessing a single month requires rewriting entire year

## Decision

**Use monthly partitioning** (`year/month`) for high-volume tables.

**Rationale:**
1. Avoids PyArrow partition limit
2. Balances query performance with file count
3. DuckDB's partition pruning still works effectively
4. Each monthly file is manageable (~5-50MB compressed)

## Implementation

### High-Volume Tables (Monthly)
- HAE minute-level tables
- Concept2 strokes
- JEFIT sets
- Oura 5-min HR
- Protocols doses

### Low-Volume Tables (Yearly)
- Labs results (~50 rows/year)
- JEFIT workouts summary
- Concept2 workout summary
- Protocols phases

### Code Pattern
```python
import pyarrow.parquet as pq

pq.write_to_dataset(
    table=df,
    root_path='data/silver/hae/hae_heart_rate_minute',
    partition_cols=['year', 'month'],  # Monthly partitioning
    existing_data_behavior='overwrite_or_ignore'
)
```

## Results

**Before (Daily Partitioning):**
- Error after ingesting 3 years: "Cannot write more than 10000 partitions"
- Had to delete and restart with coarser partitioning

**After (Monthly Partitioning):**
- 10+ years of data: ~120 partitions/table (well under limit)
- Query performance: Month-range queries ~200-800ms (acceptable)
- File sizes: 10-100MB per partition (optimal for SSD I/O)

## Trade-offs Accepted

1. **Single-day queries slightly slower:** Must scan full month instead of single day
   - Mitigated by: Columnar format + DuckDB's predicate pushdown
   - Impact: ~100ms overhead (negligible)

2. **Cannot delete single days easily:** Must reprocess entire month
   - Acceptable: Day-level deletion rarely needed
   - Workaround: Filter in queries if needed

## Lessons Learned

- Start with coarser partitioning, refine if needed
- PyArrow limits are real constraints, not suggestions
- File count matters more than individual file size for performance
- Monthly granularity is the sweet spot for health data longitudinal analysis

## Future Considerations

If we hit performance issues with monthly partitioning:
- Consider weekly partitioning (52 partitions/year)
- Evaluate materialized daily summaries in gold layer
- Explore Iceberg/Delta Lake for advanced partitioning

---

**Related:**
- [StorageAndQuery.md](../StorageAndQuery.md) - Implementation details
- [Architecture.md](../Architecture.md) - Overall system design
