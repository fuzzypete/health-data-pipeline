# Storage & Query

**Version:** 2.3  
**Last Updated:** 2025-11-10

## Overview

HDP uses a Parquet + DuckDB architecture for local-first analytics with optional BigQuery export for cloud dashboards. This document covers storage patterns, query optimization, and data export workflows.

---

## Storage Architecture

### Parquet Files (Silver & Gold)

**Why Parquet?**
- Columnar format → efficient for analytics
- Compression reduces storage 10x vs CSV
- Supports partitioning for performance
- Schema enforcement prevents bad data
- Interoperable (Spark, Pandas, DuckDB, BigQuery)

**Storage Layout:**
```
data/
├── bronze/                    # Raw source data
│   ├── hae/
│   ├── concept2/
│   └── ...
├── silver/                    # Normalized tables
│   ├── hae/
│   │   ├── hae_heart_rate_minute/
│   │   │   ├── year=2024/
│   │   │   │   ├── month=10/
│   │   │   │   │   └── data.parquet
│   │   │   │   └── month=11/
│   │   │   │       └── data.parquet
│   │   │   └── year=2023/...
│   │   └── ...
│   ├── concept2/...
│   └── ...
└── gold/                      # Analytics-ready
    ├── hdp.duckdb            # Main query database
    └── exports/              # Parquet exports for BigQuery
```

### Partitioning Strategy

**Monthly Partitioning** (High-Volume Tables)
```
hae_heart_rate_minute/
    year=2024/month=10/data.parquet  (~1M rows)
    year=2024/month=11/data.parquet  (~1M rows)
```

**Yearly Partitioning** (Low-Volume Tables)
```
labs_results/
    year=2024/data.parquet  (~50 rows)
    year=2023/data.parquet  (~50 rows)
```

**Benefits:**
- Query pruning: Only scan relevant partitions
- Avoids PyArrow's 10k partition limit (hit with daily partitioning)
- Efficient for time-range queries

**Example: Only scan November data**
```sql
SELECT * FROM hae_heart_rate_minute
WHERE timestamp_utc >= '2024-11-01'
  AND timestamp_utc < '2024-12-01'
-- DuckDB automatically prunes to year=2024/month=11 partition
```

---

## DuckDB Integration

### Why DuckDB?

- **Embedded:** No server, just a file
- **Fast:** Vectorized query engine
- **Parquet-native:** Direct queries on Parquet files
- **SQL-complete:** Window functions, CTEs, JSON, etc.
- **Portable:** Single file database (~100MB)

### Database Setup

**Initialize:**
```bash
duckdb data/gold/hdp.duckdb
```

**Load Silver Tables:**
```sql
-- Create views over Parquet files
CREATE VIEW hae_heart_rate_minute AS 
SELECT * FROM read_parquet('data/silver/hae/hae_heart_rate_minute/*/*/*/data.parquet');

CREATE VIEW concept2_workouts AS
SELECT * FROM read_parquet('data/silver/concept2/concept2_workouts/*/*/*/data.parquet');

-- Repeat for all silver tables
```

**Materialize Gold Tables:**
```sql
-- Pre-compute integrated daily summary
CREATE TABLE integrated_daily AS
SELECT 
    date_trunc('day', h.timestamp_utc) as date_utc,
    -- HAE metrics
    AVG(h.heart_rate_bpm) as avg_resting_hr,
    SUM(s.steps) as total_steps,
    -- Concept2 metrics
    SUM(c.distance_meters) as c2_total_meters,
    -- Oura metrics
    o.readiness_score,
    o.sleep_score,
    o.average_hrv_ms
FROM hae_heart_rate_minute h
LEFT JOIN hae_steps_minute s ON date_trunc('minute', h.timestamp_utc) = date_trunc('minute', s.timestamp_utc)
LEFT JOIN concept2_workouts c ON h.timestamp_utc::date = c.date_utc::date
LEFT JOIN oura_readiness_daily o ON h.timestamp_utc::date = o.date
GROUP BY date_trunc('day', h.timestamp_utc), o.readiness_score, o.sleep_score, o.average_hrv_ms;
```

### Common Query Patterns

**Pattern 1: Time-Range Filtering**
```sql
-- Last 30 days of readiness scores
SELECT date, score
FROM oura_readiness_daily
WHERE date >= current_date - interval '30 days'
ORDER BY date DESC;
```

**Pattern 2: Aggregation with Window Functions**
```sql
-- 7-day rolling average heart rate
SELECT 
    date_utc,
    avg_resting_hr,
    AVG(avg_resting_hr) OVER (
        ORDER BY date_utc 
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) as hr_7day_avg
FROM integrated_daily
WHERE date_utc >= '2024-01-01'
ORDER BY date_utc;
```

**Pattern 3: Cross-Source Correlation**
```sql
-- Training volume vs next-day readiness
SELECT 
    d.date_utc as training_date,
    d.c2_total_meters + COALESCE(j.total_volume_kg * 10, 0) as total_load,
    o.score as next_day_readiness
FROM integrated_daily d
LEFT JOIN jefit_daily j ON d.date_utc = j.date_utc
LEFT JOIN oura_readiness_daily o ON d.date_utc + interval '1 day' = o.date
WHERE d.date_utc >= '2024-01-01'
  AND (d.c2_total_meters > 0 OR j.total_volume_kg > 0)
ORDER BY d.date_utc;
```

**Pattern 4: Protocol Effectiveness**
```sql
-- Ferritin levels during iron protocol
WITH protocol AS (
    SELECT start_date, end_date
    FROM protocols_phases
    WHERE phase_name = 'Iron Repletion Protocol'
),
labs AS (
    SELECT test_date, result_value
    FROM labs_results
    WHERE biomarker_name = 'ferritin'
      AND test_date BETWEEN (SELECT start_date FROM protocol) 
                        AND (SELECT end_date FROM protocol)
)
SELECT 
    test_date,
    result_value,
    result_value - LAG(result_value) OVER (ORDER BY test_date) as delta,
    test_date - LAG(test_date) OVER (ORDER BY test_date) as days_between
FROM labs
ORDER BY test_date;
```

**Pattern 5: Minute-Level Workout Analysis**
```sql
-- Heart rate during specific Concept2 workout
WITH workout AS (
    SELECT workout_id, date_utc, duration_seconds
    FROM concept2_workouts
    WHERE workout_id = '12345'
)
SELECT 
    h.timestamp_utc,
    h.heart_rate_bpm,
    s.stroke_rate,
    s.watts
FROM hae_heart_rate_minute h
JOIN workout w ON h.timestamp_utc >= w.date_utc 
              AND h.timestamp_utc <= w.date_utc + (w.duration_seconds || ' seconds')::interval
LEFT JOIN concept2_strokes s ON s.workout_id = w.workout_id 
                             AND h.timestamp_utc = w.date_utc + (s.timestamp_offset_seconds || ' seconds')::interval
ORDER BY h.timestamp_utc;
```

---

## Query Optimization

### 1. Partition Pruning
```sql
-- Good: Uses partition pruning
SELECT * FROM hae_heart_rate_minute
WHERE timestamp_utc >= '2024-11-01'  
-- Only scans year=2024/month=11

-- Bad: Full table scan
SELECT * FROM hae_heart_rate_minute
WHERE EXTRACT(month FROM timestamp_utc) = 11
-- Function on column prevents partition pruning
```

### 2. Predicate Pushdown
```sql
-- Good: Filter pushed to Parquet read
SELECT * FROM concept2_workouts
WHERE workout_type = 'RowErg'
  AND date_utc >= '2024-01-01'

-- Bad: Filter after full read
SELECT * FROM (
    SELECT * FROM concept2_workouts
) WHERE workout_type = 'RowErg'
```

### 3. Columnar Projection
```sql
-- Good: Only reads needed columns
SELECT date_utc, distance_meters, average_watts
FROM concept2_workouts

-- Bad: Reads all columns
SELECT * FROM concept2_workouts
-- Then filter in application
```

### 4. Materialized Aggregations
```sql
-- Good: Pre-compute daily summaries
CREATE TABLE hae_daily_summary AS
SELECT 
    date_trunc('day', timestamp_utc) as date,
    AVG(heart_rate_bpm) as avg_hr,
    MIN(heart_rate_bpm) as min_hr,
    MAX(heart_rate_bpm) as max_hr
FROM hae_heart_rate_minute
GROUP BY date_trunc('day', timestamp_utc);

-- Query the summary (fast)
SELECT * FROM hae_daily_summary WHERE date >= '2024-01-01';

-- Bad: Aggregate on every query (slow)
SELECT date_trunc('day', timestamp_utc), AVG(heart_rate_bpm)
FROM hae_heart_rate_minute  -- Scans millions of rows
WHERE timestamp_utc >= '2024-01-01'
GROUP BY date_trunc('day', timestamp_utc);
```

---

## Write Strategies

### Append vs Overwrite

**Append (Default):**
```python
import pyarrow.parquet as pq

# Append new data to existing partition
pq.write_to_dataset(
    table=df,
    root_path='data/silver/hae/hae_heart_rate_minute',
    partition_cols=['year', 'month'],
    existing_data_behavior='overwrite_or_ignore'  # Overwrite same partition
)
```

**Full Overwrite (Rare):**
```python
# Replace entire table
pq.write_to_dataset(
    table=df,
    root_path='data/silver/hae/hae_heart_rate_minute',
    partition_cols=['year', 'month'],
    existing_data_behavior='delete_matching'  # Delete all partitions first
)
```

### Deduplication on Write
```python
# Deduplicate before writing
df_deduped = df.drop_duplicates(
    subset=['timestamp_utc', 'heart_rate_bpm', 'source_device_id'],
    keep='first'  # Keep earliest ingestion
)

# Write deduplicated data
pq.write_to_dataset(df_deduped, ...)
```

### Schema Evolution
```python
# Adding new column to existing table
df_new = df.assign(new_column=default_value)

# PyArrow will merge schemas automatically
pq.write_to_dataset(df_new, ...)
# Old partitions: missing new_column (null in queries)
# New partitions: have new_column
```

---

## BigQuery Export (Optional)

### Why Export to BigQuery?

- **Dashboards:** Use Looker/Tableau for visualization
- **Sharing:** Query from web without local database
- **Scale:** Larger-than-memory datasets
- **Collaboration:** Team access to data

### Export Workflow

**1. Export Gold Parquet:**
```python
# Export integrated_daily to Parquet
duckdb_con.execute("""
    COPY (SELECT * FROM integrated_daily)
    TO 'data/gold/exports/integrated_daily.parquet'
    (FORMAT PARQUET, COMPRESSION SNAPPY)
""")
```

**2. Upload to GCS:**
```bash
gsutil cp data/gold/exports/integrated_daily.parquet \
    gs://hdp-data/gold/integrated_daily/
```

**3. Load into BigQuery:**
```bash
bq load \
    --source_format=PARQUET \
    --replace \
    hdp_dataset.integrated_daily \
    gs://hdp-data/gold/integrated_daily/integrated_daily.parquet
```

**4. Query in BigQuery:**
```sql
SELECT 
    date_utc,
    avg_resting_hr,
    readiness_score
FROM `project.hdp_dataset.integrated_daily`
WHERE date_utc >= '2024-01-01'
ORDER BY date_utc DESC
LIMIT 100;
```

### Scheduling Exports

**Cron job (daily at 2am):**
```bash
0 2 * * * /path/to/scripts/export_to_bigquery.sh
```

**Export script:**
```bash
#!/bin/bash
# export_to_bigquery.sh

# Run DuckDB export
duckdb data/gold/hdp.duckdb < scripts/export_gold.sql

# Upload to GCS
gsutil -m cp -r data/gold/exports/* gs://hdp-data/gold/

# Load into BigQuery
bq load --replace --source_format=PARQUET \
    hdp_dataset.integrated_daily \
    gs://hdp-data/gold/integrated_daily/*.parquet
```

---

## Performance Benchmarks

### Query Performance (Local)

**Hardware:** M1 MacBook, 16GB RAM, NVMe SSD

| Query Type | Dataset Size | DuckDB Time | Notes |
|------------|-------------|-------------|-------|
| Partition scan | 1M rows (1 month HAE) | ~50ms | Single partition |
| Full table scan | 12M rows (1 year HAE) | ~800ms | All partitions |
| Aggregation | 12M rows → daily | ~1.2s | GROUP BY day |
| Join (2 tables) | 1M + 500 rows | ~200ms | HAE + Concept2 |
| Complex (3 joins + window) | Multi-million rows | ~3s | Gold layer query |

**Key Takeaway:** DuckDB handles millions of rows efficiently on laptop hardware.

### Storage Efficiency

| Source | Format | Size | Compression Ratio |
|--------|--------|------|------------------|
| HAE CSV | CSV | 2.4 GB | 1x (baseline) |
| HAE Parquet | Parquet (Snappy) | 240 MB | 10x compression |
| Concept2 JSON | JSON | 150 MB | 1x |
| Concept2 Parquet | Parquet (Snappy) | 25 MB | 6x compression |

**Key Takeaway:** Parquet reduces storage 6-10x vs text formats.

---

## Maintenance Tasks

### Compact Small Partitions
```python
# If many small files in partition, consolidate
import pyarrow.parquet as pq

# Read entire partition
table = pq.read_table('data/silver/hae/hae_heart_rate_minute/year=2024/month=11')

# Write back as single file
pq.write_table(table, 'data/silver/hae/hae_heart_rate_minute/year=2024/month=11/data.parquet')
```

### Vacuum Old Partitions
```python
# Remove partitions older than retention period
import shutil
from pathlib import Path

retention_years = 10
current_year = datetime.now().year
cutoff_year = current_year - retention_years

for year_dir in Path('data/silver').rglob('year=*'):
    year = int(year_dir.name.split('=')[1])
    if year < cutoff_year:
        shutil.rmtree(year_dir)
        print(f"Deleted: {year_dir}")
```

### Rebuild DuckDB Database
```bash
# If database corruption or schema changes
rm data/gold/hdp.duckdb
duckdb data/gold/hdp.duckdb < scripts/init_gold.sql
```

---

## Troubleshooting

### Issue: "PyArrow partition limit exceeded"
```
Error: Cannot write more than 10000 partitions
```

**Solution:** Use monthly partitioning instead of daily
```python
# Bad: Daily partitioning (365 partitions/year)
partition_cols=['year', 'month', 'day']

# Good: Monthly partitioning (12 partitions/year)
partition_cols=['year', 'month']
```

### Issue: "DuckDB out of memory"
```
Error: Out of memory allocating for query
```

**Solution:** Process in smaller time chunks
```sql
-- Instead of entire table
SELECT * FROM hae_heart_rate_minute

-- Process monthly
SELECT * FROM hae_heart_rate_minute
WHERE timestamp_utc >= '2024-11-01' 
  AND timestamp_utc < '2024-12-01'
```

### Issue: "Parquet schema mismatch"
```
Error: Schema mismatch when reading partition
```

**Solution:** Unify schemas before merging
```python
# Read with schema inference disabled
table = pq.read_table('path', schema=expected_schema)
```

---

**See Also:**
- [Architecture.md](Architecture.md) - System design
- [Schema.md](Schema.md) - Table definitions
- [Deployment.md](Deployment.md) - Production setup
