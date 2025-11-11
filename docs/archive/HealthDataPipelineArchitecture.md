# Health Data Pipeline — Architecture (v2.1)
**Date:** 2025-11-08  
**Last Updated:** Corrected JEFIT timestamp strategy classification

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

**Problem:** Health data sources have varying timezone quality. HAE CSV/Daily JSON exports lose per-event timezone info (travel day corruption), while Workout JSON and Concept2 preserve accurate timezones. JEFIT CSV exports contain no timezone information at all.

**Solution:** Hybrid ingestion with two strategies based on source data quality.

### Strategy A: Assumed Timezone (Lossy Sources)
**Used for:** HAE CSV, HAE Daily JSON, JEFIT CSV → `minute_facts`, `daily_summary`, `workouts`, `resistance_sets`

**Approach:** Ignore source timezone (corrupted or missing), assume home timezone consistently.

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
**Used for:** HAE Workout JSON, Concept2 API → `workouts`, `cardio_splits`, `cardio_strokes`

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
1. **Strategy A timestamp ingestion:** Parse naive timestamps and assume home timezone (see Timestamp Handling Strategy)
2. Parse JEFIT CSV sections (ROUTINES, MYLOGS)
3. Create workout_id per session
4. Extract sets with weight/reps/rest
5. Calculate session aggregates → `workouts`

**Note:** JEFIT exports do not include timezone information, so we assume the user's home timezone (America/Los_Angeles) for all workouts. This means workout times will be incorrect on travel days but consistent at home.

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

# 4. JEFIT resistance training
make ingest-jefit
```

### On-Demand Operations
```bash
# Ingest specific HAE CSV file
make ingest-hae-file FILE=path/to/export.csv

# Ingest specific JEFIT export
make ingest-jefit-file FILE=path/to/jefit_export.csv

# Fetch latest from Google Drive
make fetch-hae
make fetch-labs

# Full reload (drop + re-ingest everything)
make reload
```

---

## Quality Assurance

### Validation Rules

**Temporal Integrity:**
- Monotonicity: Within partition, timestamps increasing
- DST day counts: Spring-forward ~1380 min, fall-back ~1500 min
- Duplicate detection: Flag identical (timestamp_utc, source)

**Value Ranges:**
- `heart_rate_bpm`: 30-220
- `steps`: 0-50,000
- `water_fl_oz`: 0-338 (0-10L)
- `sleep_efficiency_pct`: 0-100

**Workout Validation:**
- `duration_s` > 0
- `start_time_utc` <= `end_time_utc`
- If `has_splits=true`, expect splits present
- If `has_strokes=true`, expect strokes present

**Resistance Training:**
- `actual_reps` >= 0
- `weight_lbs` >= 0
- `set_number` >= 1 and sequential per exercise

### Error Handling

**Strategy:** Fail fast with clear error messages

**Common errors:**
- **Missing file:** Log warning, skip ingestion
- **Malformed CSV/JSON:** Move to `Data/Error/`, log details
- **API timeout:** Retry with exponential backoff (max 3 retries)
- **Validation failure:** Log row details, optionally skip

**Logging pattern:**
```python
logger.info(f"minutes: {file} → rows={n}, window={min_ts}..{max_ts}")
logger.info(f"daily_summary: rows={n}, dates={min}..{max}")
logger.warning(f"validation: {issue_type} in {file} at row {idx}")
logger.error(f"FAILED: {file} → {error_type}: {details}")
```

---

## Configuration Management

### config.yaml Structure

```yaml
# Timezone configuration
timezone:
  default: "America/Los_Angeles"  # For Strategy A sources
  
# API credentials
api:
  concept2:
    token: "YOUR_TOKEN_HERE"
    base_url: "https://log.concept2.com/api/"

# Data directories
data:
  raw_dir: "Data/Raw"
  parquet_dir: "Data/Parquet"
  archive_dir: "Data/Archive"
  error_dir: "Data/Error"

# Ingestion settings
ingestion:
  batch_size: 50
  max_retries: 3
  retry_delay_seconds: 5
  archive_after_ingest: true
```

### Environment Variables (.env)

```bash
# Required
CONCEPT2_API_TOKEN=your_token_here
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Optional (override config.yaml)
LOCAL_TIMEZONE=America/Los_Angeles
DATA_ROOT=/custom/data/path
```

---

## Deployment

### Local Development

```bash
# 1. Install dependencies
poetry install

# 2. Configure
cp config.yaml.template config.yaml
cp .env.example .env
# Edit both files with your values

# 3. Run ingestion
make ingest-hae-daily
make ingest-concept2
make ingest-jefit

# 4. Query with DuckDB
make duck.init
make duck.query
```

### Docker Deployment

```bash
# Build image
docker build -t health-pipeline:latest .

# Run ingestion
docker run --rm \
  -v $(pwd)/Data:/app/Data \
  -v $(pwd)/config.yaml:/app/config.yaml \
  -v $(pwd)/.env:/app/.env \
  health-pipeline:latest \
  make ingest-all

# Run on schedule (cron in host)
0 2 * * * docker run --rm -v ... health-pipeline:latest make ingest-hae-daily
```

---

## Performance Optimization

### Partitioning Strategy
- Date + source partitioning enables efficient pruning
- Typical query: single month = 30-31 partitions
- Full year query: ~365 partitions (still manageable)

### Compression
- Parquet snappy compression: ~3-5x reduction
- Annual data volume: ~60-80 MB (mostly stroke data)
- 10 years historical: <1 GB total

### Query Optimization
- Use partition filters: `date >= '2025-01-01'`
- Use source filters: `source = 'Concept2'`
- Avoid `SELECT *`: Parquet is columnar
- Use DuckDB for interactive queries (optimized Parquet reader)

### Incremental Processing
- Process only new files (not re-ingesting archives)
- Dedupe on write (not post-processing)
- Partition overwrite for daily summaries (idempotent)

---

## Future Enhancements

### Phase 3: Labs & Protocols
- Manual entry forms (web UI or CLI)
- Lab result ingestion from PDF/Excel
- Protocol history tracking (compounds, dosages, timing)
- Correlation analysis: labs × protocols × workouts

### Phase 4: Real-Time Monitoring
- Glucose/ketone monitor integration
- Lactate meter data capture
- Heart rate variability (HRV) tracking
- Sleep stage analysis (Oura, Whoop, etc.)

### Phase 5: Advanced Analytics
- Automated periodization analysis
- Volume progression tracking
- Recovery metrics (HRV, sleep, strain)
- Supplement efficacy studies (n=1 experiments)
- ML models for injury prevention

### Phase 6: Visualization & Dashboards
- Grafana dashboards for real-time monitoring
- Jupyter notebooks for deep dives
- Automated weekly/monthly reports
- Interactive web UI for data exploration

---

## Troubleshooting

### Common Issues

**Issue:** `No timezone information in JEFIT CSV`  
**Solution:** This is expected. JEFIT uses Strategy A (assumed timezone). Workout times will be correct at home but incorrect on travel days.

**Issue:** `Duplicate timestamps in minute_facts`  
**Solution:** Check for multiple HAE exports covering same date range. Archive old exports and re-ingest.

**Issue:** `API rate limit exceeded (Concept2)`  
**Solution:** Pipeline has exponential backoff retry. Wait 5 minutes and retry. For historical backfills, use smaller date ranges.

**Issue:** `Missing partitions after ingestion`  
**Solution:** Check logs for validation failures. Files with errors are moved to `Data/Error/`.

**Issue:** `Travel day timestamps are wrong`  
**Solution:** Expected for Strategy A sources. Either accept the trade-off or manually correct using travel log.

---

## Maintenance

### Weekly Tasks
- Review error directory for failed ingestions
- Check logs for validation warnings
- Monitor storage usage (stroke data accumulates)

### Monthly Tasks
- Archive old CSV/JSON files
- Validate partition integrity
- Review query performance
- Update API tokens if needed

### Quarterly Tasks
- Full data validation audit
- Review and update documentation
- Optimize slow queries
- Plan new feature development

---

## References

- **Schema Specification:** `docs/HealthDataPipelineSchema.md`
- **Design Patterns:** `docs/HealthDataPipelineDesign.md`
- **Timestamp Handling:** `docs/TimestampHandling.md`
- **API Documentation:** `docs/API_Integration.md`

