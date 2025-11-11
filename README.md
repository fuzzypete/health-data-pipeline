# Health Data Pipeline Documentation

**Last Updated:** 2025-11-10  
**Version:** 2.3 (Curated Structure)

## Overview

The Health Data Pipeline (HDP) ingests multi-source health and fitness data into minute-level Parquet tables for longitudinal analysis. Primary sources include Apple Health, Concept2, JEFIT, Oura, Labs, and Supplement/Medication protocols.

**Default Operation:** Local Parquet + DuckDB  
**Optional:** GCS + BigQuery export for cloud analytics

## Documentation Structure

### Living Documentation (`/docs/`)
These are the actively maintained reference docs you'll use day-to-day:

- **[Architecture.md](docs/Architecture.md)** - System design, medallion architecture, data flow
- **[DataSources.md](docs/DataSources.md)** - Ingestion details for each source (HAE, Concept2, JEFIT, Oura, Labs, Protocols)
- **[Schema.md](docs/Schema.md)** - Complete table definitions, fields, partitioning, keys
- **[TimestampHandling.md](docs/TimestampHandling.md)** - Strategy A vs B, timezone complexity, edge cases
- **[StorageAndQuery.md](docs/StorageAndQuery.md)** - DuckDB patterns, Parquet optimization, BigQuery export
- **[Deployment.md](docs/Deployment.md)** - Docker setup, automation, multi-machine deployment

### Archive (`/docs/archive/`)
Comprehensive reference material that captures the full evolution and detailed design:

- **HealthDataPipelineArchitecture_v2.3.md** - Complete system architecture deep-dive
- **HealthDataPipelineSchema_v2.3.md** - Exhaustive schema documentation with all 35+ tables
- **HealthDataPipelineDesign_v2.3.md** - Detailed ingestion algorithms, deduplication, quality checks

**When to use archive:** When you need exhaustive detail, implementation algorithms, or complete table specifications.

### Decision Logs (`/docs/decisions/`)
Documents that explain *why* we made specific technical choices:

- **PartitioningStrategy.md** - Why monthly > daily for large datasets
- **TimezoneStrategy.md** - Trade-offs between Strategy A (assumed) vs B (rich)
- **DeduplicationApproaches.md** - Hash-based vs exact-match vs fuzzy-time
- **LabsStandardization.md** - Biomarker canonical naming and reference range handling

**When to use decisions:** Before changing core architecture, to understand historical context and avoid repeating mistakes.

## Quick Start

```bash
# Setup
poetry install --with dev
make help

# Ingest data
make ingest-hae
make ingest-concept2
make ingest-oura
make ingest-labs

# Query
duckdb data/gold/hdp.duckdb
```

## Current Implementation Status

✅ **Implemented:**
- Apple Health Auto Export (HAE) - 10+ tables, minute-level
- Concept2 API - Workouts, splits, strokes
- JEFIT - Resistance training workouts and sets
- Oura Ring - Daily summaries + 5-min HR
- Labs - Biomarker results with standardization
- Protocols - Supplement/medication tracking

🚧 **In Progress:**
- Automated scheduling for Oura/Concept2
- Dashboard generation
- CGM integration prep

📋 **Planned:**
- Blood pressure monitoring
- DEXA scan results
- Lactate test parsing from Concept2 comments

## Key Concepts

**Medallion Architecture:**
- **Bronze:** Raw ingested data (immutable)
- **Silver:** Cleaned, normalized, deduplicated
- **Gold:** Aggregated, joined, analysis-ready

**Timestamp Strategies:**
- **Strategy A (Assumed):** HAE, JEFIT, Protocols - assume America/Los_Angeles
- **Strategy B (Rich):** Concept2, Oura - preserve full timezone info

**Partitioning:**
- Monthly for high-volume (Concept2 strokes, HAE minute data)
- Yearly for low-volume (Labs, JEFIT)

## Need Help?

1. **Implementation details?** → Check `/docs/DataSources.md` for your source
2. **Schema questions?** → Check `/docs/Schema.md`
3. **Why does it work this way?** → Check `/docs/decisions/`
4. **Deep technical dive?** → Check `/docs/archive/`

## Maintenance

- Update living docs (`/docs/`) when behavior changes
- Add decision logs when making architectural choices
- Archive old versions of living docs with date suffix (e.g., `Architecture_v2.2_20251101.md`)

---

**Maintained By:** Peter Kahaian  
**Tech Stack:** Python 3.11+, PyArrow, DuckDB, Poetry
