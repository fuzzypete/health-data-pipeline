# Health Data Pipeline — Architecture (v2.0)
**Date:** 2025-11-01

## System Overview

Health data ETL pipeline ingesting from multiple sources into normalized Parquet datasets for longitudinal analysis.

**Core principles:**
- Hybrid timestamp strategy: Three timestamps (UTC, local, timezone) enable both pipeline operations and circadian analysis
- Strategy A (assumed timezone) for lossy sources; Strategy B (rich timezone) for high-quality sources
- Parquet with Hive-style partitioning (date + source)
- Idempotent writes with overwrite_or_ignore
- Single Docker image; Poetry environment
- Archive processed inputs; move failures to Error/

---

## Timestamp Handling Strategy

**Problem:** Health data sources have varying timezone quality. HAE CSV/Daily JSON exports lose per-event timezone info (travel day corruption), while Workout JSON, Concept2, and JEFIT preserve accurate timezones.

**Solution:** Hybrid ingestion with two strategies based on source data quality.

### Strategy A: Assumed Timezone (Lossy Sources)
**Used for:** HAE CSV, HAE Daily JSON → `minute_facts`, `daily_summary`

**Approach:** Ignore source timezone (corrupted on travel days), assume home timezone consistently.

**Result:** 
- 95% of data (home days) perfectly correct
- 5% of data (travel days) knowingly wrong but consistent
- Enables clean circadian analysis without random corruption
- Can be corrected later with manual travel log

**Implementation:**
```python
# Read timestamp as naive, localize to assumed home timezone
LOCAL_TIMEZONE = ZoneInfo("America/Los_Angeles")
df['timestamp_local'] = pd.to_datetime(df['timestamp']).dt.tz_localize(
    LOCAL_TIMEZONE, ambiguous='infer', nonexistent='shift_forward'
)
df['timestamp_utc'] = df['timestamp_local'].dt.tz_convert('UTC')
df['tz_name'] = 'America/Los_Angeles'
df['tz_source'] = 'assumed'
```

### Strategy B: Rich Timezone (High-Quality Sources)
**Used for:** HAE Workout JSON, Concept2 API, JEFIT CSV → `workouts`, `cardio_splits`, `cardio_strokes`, `resistance_sets`

**Approach:** Trust per-event timezone from source (it's correct).

**Result:**
- 100% accurate for all workouts including travel days
- No assumptions, no corrections needed

**Implementation:**
```python
# Use actual timezone from source data
tz_name = record['timezone']  # "America/Los_Angeles"
timestamp_local = pd.to_datetime(record['date']).dt.tz_localize(
    ZoneInfo(tz_name), ambiguous='infer', nonexistent='shift_forward'
)
timestamp_utc = timestamp_local.tz_convert('UTC')
tz_source = 'actual'
```

### Three-Timestamp Schema
All tables store:
1. **timestamp_utc** - Pipeline operations (joins, dedup, partitioning)
2. **timestamp_local** - Analysis (circadian patterns, hour-of-day)
3. **tz_name** - Context that makes local unambiguous

**See:** `docs/TimestampHandling.md` for comprehensive specification, DST handling, query patterns, and implementation examples.

---

## Data Sources

### Phase 1 (Implemented)
- **Apple Health Daily CSV** → `minute_facts`, `daily_summary`
- **Apple Health Workouts JSON** → `workouts`

### Phase 2 (v2.0 - Current)
- **Concept2 Logbook API** → `workouts`, `cardio_splits`, `cardio_strokes`
- **JEFIT CSV Export** → `workouts`, `resistance_sets`

### Future Phases
- Labs (manual entry) → `labs`
- Protocol history (manual entry) → `protocol_history`
- Glucose/ketone monitors → `glucose_ketone`
- Lactate meters → `lactate`

---

## Data Flows

### Minute-Level Health Metrics (HAE CSV)
```
HAE Daily CSV
  ↓ ingest/csv_delta.py
  ├→ minute_facts (parquet, wide)
  └→ daily_summary (parquet, wide, derived)
```

**Processing:**
- Column normalization (HAE headers → canonical names)
- **Strategy A timestamp ingestion:** Assume home timezone (see Timestamp Handling Strategy)
- Dedupe on (timestamp_utc, source)
- Daily aggregation with guarded derivations

---

### Workouts - Universal Session Container

#### Apple Health Workouts (HAE JSON)
```
HAE Workouts JSON
  ↓ ingest/hae_workouts.py
  └→ workouts (session-level only)
```

**Processing:**
- Parse JSON workout exports
- **Strategy B timestamp ingestion:** Use actual per-workout timezone from source
- Extract: walking, hiking, strength, flexibility, etc.
- Session-level metadata only (no granular data)

#### Concept2 Cardio (API)
```
Concept2 Logbook API
  ↓ ingest/concept2_api.py
  ├→ workouts (session summary)
  ├→ cardio_splits (interval-level)
  └→ cardio_strokes (stroke-by-stroke)
```

**Processing:**
1. **Strategy B timestamp ingestion:** Use actual per-workout timezone from API
2. Fetch workout summary → `workouts`
3. If `has_splits=true` → fetch splits → `cardio_splits`
4. If `has_strokes=true` → fetch `/strokes` endpoint → `cardio_strokes`

**Granularity:**
- Splits: ~5-10 per workout (2-min or 500m intervals)
- Strokes: ~1,200 per 60-min workout (~1 per 3 seconds)

#### Resistance Training (JEFIT CSV)
```
JEFIT CSV Export
  ↓ ingest/jefit_csv.py
  ├→ workouts (session aggregates)
  └→ resistance_sets (set-level)
```

**Processing:**
1. **Strategy B timestamp ingestion:** Use timestamps with user's actual timezone from CSV
2. Parse JEFIT CSV sections (ROUTINES, MYLOGS)
3. Create workout_id per session
4. Extract sets with weight/reps/rest
5. Calculate session aggregates → `workouts`

---

## Storage Architecture

### Directory Structure
```
Data/
  ├── Raw/
  │   ├── CSV/              # HAE daily exports (staging)
  │   └── JSON/             # HAE workout exports (staging)
  │
  ├── Parquet/              # Normalized datasets
  │   ├── minute_facts/     # date=YYYY-MM-DD/source=HAE_CSV/
  │   ├── daily_summary/    # date=YYYY-MM-DD/source=HAE_CSV/
  │   ├── workouts/         # date=YYYY-MM-DD/source={HAE_JSON,Concept2,JEFIT}/
  │   ├── cardio_splits/    # date=YYYY-MM-DD/source=Concept2/
  │   ├── cardio_strokes/   # date=YYYY-MM-DD/source=Concept2/
  │   └── resistance_sets/  # date=YYYY-MM-DD/source=JEFIT/
  │
  ├── Archive/
  │   ├── CSV/              # Processed HAE daily exports
  │   └── JSON/             # Processed HAE workout exports
  │
  └── Error/                # Failed ingestions for review
```

### Partitioning Strategy

All tables use **Hive-style partitioning:**
```
date=YYYY-MM-DD/source={HAE_CSV,HAE_JSON,Concept2,JEFIT}/
```

**Benefits:**
- Efficient date-range queries
- Source isolation
- Incremental processing
- Partition pruning in queries

---

## Ingestion Orchestration

### Daily Automation (Cron/Scheduler)
```bash
# 1. HAE minute-level data
make ingest-hae-daily

# 2. HAE workouts
make ingest-hae-workouts

# 3. Concept2 sync (weekly or on-demand)
make ingest-concept2

# 4. JEFIT export (manual trigger)
make ingest-jefit
```

### Ingestion Modules

**Core modules:**
- `src/pipeline/ingest/csv_delta.py` - HAE CSV → minute_facts, daily_summary
- `src/pipeline/ingest/hae_workouts.py` - HAE JSON → workouts
- `src/pipeline/ingest/concept2_api.py` - Concept2 API → workouts + splits + strokes
- `src/pipeline/ingest/jefit_csv.py` - JEFIT CSV → workouts + resistance_sets

**Shared utilities:**
- `src/pipeline/common/schema.py` - PyArrow schemas
- `src/pipeline/common/normalization.py` - Column mapping
- `src/pipeline/validate/checks.py` - Data validation

---

## Technology Stack

**Runtime:**
- Python 3.11
- Poetry for dependency management
- Docker for containerization

**Data Processing:**
- pandas - DataFrame operations
- pyarrow - Parquet I/O, schemas
- dask - Future: distributed processing for large datasets

**APIs:**
- requests - HTTP client for Concept2 API

**Development:**
- pytest - Testing
- black - Code formatting
- ruff - Linting
- Makefile - Task automation

---

## Deduplication Strategy

### Write Modes by Table

**Minute-level (time-series):**
- `minute_facts`: Dedupe on (`timestamp_utc`, `source`) before write
- `daily_summary`: Overwrite partition on re-ingest

**Session-level (workouts):**
- `workouts`: Upsert by (`workout_id`, `source`)

**Granular data (sub-workout):**
- `cardio_splits`: Overwrite all splits for `workout_id` on re-ingest
- `cardio_strokes`: Overwrite all strokes for `workout_id` on re-ingest
- `resistance_sets`: Overwrite all sets for `workout_id` on re-ingest

**Rationale:** Granular data is always fetched atomically per workout, so full replacement is safe and simpler than row-level merge.

---

## Query Patterns

### Time-series analysis
```sql
SELECT timestamp_utc, heart_rate_avg, steps
FROM minute_facts
WHERE date BETWEEN '2025-10-01' AND '2025-10-31'
  AND source = 'HAE_CSV'
```

### Workout summaries
```sql
SELECT workout_type, AVG(duration_s), AVG(calories_kcal)
FROM workouts
WHERE date >= '2025-01-01'
GROUP BY workout_type
```

### Power curve analysis (Concept2)
```sql
SELECT 
  cs.time_cumulative_s,
  cs.pace_500m_cs,
  cs.heart_rate_bpm
FROM workouts w
JOIN cardio_strokes cs ON w.workout_id = cs.workout_id
WHERE w.erg_type = 'rower'
  AND w.date = '2025-10-30'
ORDER BY cs.time_cumulative_s
```

### Volume tracking (resistance training)
```sql
SELECT 
  DATE_TRUNC('week', workout_start_utc) as week,
  exercise_name,
  SUM(actual_reps * weight_lbs) as weekly_volume
FROM resistance_sets
WHERE exercise_name = 'Dumbbell Bench Press'
GROUP BY week, exercise_name
```

---

## Enrichment Pipeline (Future)

### Planned enrichments:
1. **Workout context** - Join minute_facts HR data with workouts
2. **Recovery metrics** - Calculate HRV trends, sleep quality correlation
3. **Volume periodization** - Track resistance training load over time
4. **Power zones** - Classify Concept2 efforts by HR/power zones
5. **Protocol correlation** - Link labs/performance to supplement protocols

### Enriched tables:
- `enriched_workouts` - Workouts + surrounding context
- `daily_metrics_enriched` - Daily summary + derived insights
- `body_metrics_calculated` - Trending, percentiles, changes

---

## Version History

| Version | Date       | Changes |
|---------|------------|---------|
| v2.0    | 2025-11-01 | Added Concept2 API and JEFIT ingestion; cardio splits/strokes; resistance sets |
| v1.0    | 2025-10-24 | Initial architecture: HAE CSV → minute_facts, daily_summary |
