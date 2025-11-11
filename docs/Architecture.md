# Architecture

**Version:** 2.3  
**Last Updated:** 2025-11-10

## System Overview

HDP is a data pipeline that consolidates health and fitness data from multiple sources into a unified analytics platform. The primary goal is enabling correlation analysis between training protocols, supplement regimens, and biomarker changes over time.

```
Data Sources → Bronze (Raw) → Silver (Normalized) → Gold (Analytics)
     ↓              ↓                ↓                     ↓
  APIs/CSV      Parquet          Parquet            DuckDB/BigQuery
```

## Medallion Architecture

### Bronze Layer (Raw Ingestion)
- **Purpose:** Immutable record of source data
- **Format:** JSON, CSV, Parquet (source-dependent)
- **Location:** `data/bronze/{source}/{date}/`
- **Retention:** Permanent (enables re-processing)

**Sources:**
- Apple Health Auto Export (CSV)
- Concept2 API (JSON)
- JEFIT exports (CSV)
- Oura API (JSON)
- Labs (manual JSON from PDFs)
- Protocols (manual CSV/JSON)

### Silver Layer (Normalized)
- **Purpose:** Cleaned, deduplicated, timezone-normalized tables
- **Format:** Parquet with partitioning
- **Location:** `data/silver/{source}/{table}/{year}/{month}/`
- **Schema:** Normalized relational tables per source

**Characteristics:**
- UTC timestamps (with Strategy A or B)
- Deduplication by composite keys
- Type enforcement
- Monthly or yearly partitioning

### Gold Layer (Analytics)
- **Purpose:** Aggregated, joined, analysis-ready datasets
- **Format:** DuckDB database + Parquet exports
- **Location:** `data/gold/hdp.duckdb`
- **Views:** Cross-source integrated daily summaries

**Key Tables:**
- `integrated_daily` - All sources joined by date
- `protocol_outcomes` - Supplement effectiveness analysis
- `training_load_recovery` - Correlation of volume to readiness

## Data Flow Patterns

### Move-Process-Move (MPM)
Each source follows a three-phase ingestion:

```
1. MOVE: Source → Bronze
   - Download/fetch raw data
   - Preserve original format
   - Log in metadata.ingestion_log

2. PROCESS: Bronze → Silver
   - Parse to normalized tables
   - Apply timezone strategy
   - Deduplicate
   - Validate ranges
   - Partition by date

3. MOVE: Silver → Gold
   - Aggregate to summaries
   - Join across sources
   - Calculate derived metrics
   - Load into DuckDB
```

### Timestamp Strategies

**Strategy A: Assumed Timezone**
- Used for: HAE, JEFIT, Protocols
- Approach: Assume America/Los_Angeles, convert to UTC
- Trade-off: Travel days will be wrong but *consistently* wrong
- Priority: Consistency over perfect accuracy

**Strategy B: Rich Timezone**
- Used for: Concept2, Oura
- Approach: Store both UTC and local timestamps
- Benefit: Accurate local time context preserved
- Use case: Cross-timezone analysis, travel correlations

## Technology Stack

### Storage
- **Parquet:** Columnar storage for silver/gold layers
- **DuckDB:** Embedded analytics database for queries
- **PyArrow:** Parquet read/write with partitioning
- **Optional:** Google Cloud Storage + BigQuery

### Processing
- **Python 3.11+** with Poetry dependency management
- **Pandas:** DataFrame manipulation
- **PyArrow:** Efficient Parquet operations
- **Requests:** API authentication and data fetching

### Automation
- **Make:** Task orchestration (`make ingest-all`)
- **Docker:** Containerized deployment (future)
- **Cron:** Scheduled ingestion (future)

## Design Principles

### 1. Immutability
Bronze layer never changes. All transformations preserve raw source data for re-processing if needed.

### 2. Single Source of Truth
Each data type has one authoritative table:
- Minute-level heart rate → `hae_heart_rate_minute`
- Workout summaries → `concept2_workouts`
- Biomarkers → `labs_results`

### 3. Idempotency
Re-running ingestion produces the same result. Deduplication ensures no double-counting.

### 4. Queryability First
Schema optimized for common queries:
- "What supplements was I taking when ferritin dropped?"
- "How did training volume affect sleep quality?"
- "Did protocol X improve biomarker Y?"

### 5. Practical > Perfect
Accept known limitations (e.g., travel day timestamps) rather than build overcomplicated solutions.

## Deployment Modes

### Local Development (Current)
```
~/health-data-pipeline/
├── data/
│   ├── bronze/
│   ├── silver/
│   └── gold/hdp.duckdb
├── scripts/
└── pyproject.toml
```

Run: `make ingest-all`

### Multi-Machine (Planned)
- **Bulk ingestion:** Linux server with Docker
- **Analysis:** MacBook syncing gold layer
- **Automation:** VPS cron jobs

### Cloud Export (Optional)
- Upload gold Parquet to GCS
- Import to BigQuery for Looker dashboards
- Maintains local-first workflow

## Metadata & Observability

### Ingestion Tracking
`metadata.ingestion_log` records:
- Source, table, timestamp
- Records processed/inserted/deduplicated
- Processing duration
- Status (success/partial/failed)

### Data Quality Checks
- Timestamp validation (no future dates)
- Value range checks (e.g., HR 30-220 bpm)
- Foreign key integrity
- Completeness checks (required fields)

### Monitoring (Future)
- Ingestion lag alerts
- Processing error notifications
- Storage growth tracking
- Query performance metrics

## Cross-Source Integration

Gold layer enables queries spanning multiple sources:

```sql
-- Example: Training load vs readiness
SELECT 
    d.date_utc,
    c.total_distance_meters AS cardio_volume,
    j.total_volume_kg AS strength_volume,
    o.readiness_score,
    o.average_hrv_ms,
    p.active_compounds
FROM integrated_daily d
LEFT JOIN concept2_daily c ON d.date_utc = c.date_local
LEFT JOIN jefit_daily j ON d.date_utc = j.date_utc
LEFT JOIN oura_readiness o ON d.date_utc = o.date
LEFT JOIN protocols_daily p ON d.date_utc = p.date
WHERE d.date_utc >= '2024-01-01'
ORDER BY d.date_utc;
```

## Extension Points

New sources follow the same pattern:
1. Define bronze storage format
2. Create silver schema
3. Implement MPM ingestion
4. Add to gold integrated views
5. Document in `DataSources.md`

Current extension work:
- CGM (continuous glucose) → 5-minute intervals
- Blood pressure → daily readings
- DEXA scans → quarterly body composition

---

**See Also:**
- [DataSources.md](DataSources.md) - Source-specific ingestion details
- [Schema.md](Schema.md) - Complete table definitions
- [TimestampHandling.md](TimestampHandling.md) - Deep dive on timezone strategies
