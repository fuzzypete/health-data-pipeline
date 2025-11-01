# Health Data Pipeline — Design (v2.0)
**Date:** 2025-11-01

## Schema Reference
The canonical storage schema is maintained in `docs/HealthDataPipelineSchema.md` v2.0.

The canonical architecture is maintained in `docs/HealthDataPipelineArchitecture.md` v2.0.

---

## Core Design Principles

### 1. Wide Tables for Flexibility
- `minute_facts`: Wide schema with dynamic metric columns
- `daily_summary`: Wide schema for daily aggregates
- Allows easy addition of new metrics without schema changes

### 2. Universal Workout Container
- Single `workouts` table handles all activity types
- Core fields required, type-specific fields nullable
- Child tables (`cardio_splits`, `cardio_strokes`, `resistance_sets`) are optional

### 3. Hybrid Timestamp Strategy
**Problem:** Health data sources have varying timezone quality. HAE CSV/Daily JSON exports lose per-event timezone (corrupted on travel days), while workouts preserve accurate timezones.

**Solution:** Use Strategy A (assumed timezone) for lossy sources and Strategy B (rich timezone) for high-quality sources.

**Result:** Clean circadian analysis from consistent home timezone data + perfect accuracy for workouts including travel days.

**See:** `docs/TimestampHandling.md` for comprehensive specification.

#### Strategy A: Assumed Timezone (HAE CSV, HAE Daily JSON)
```python
from zoneinfo import ZoneInfo
LOCAL_TIMEZONE = ZoneInfo("America/Los_Angeles")

# 1. Parse timestamp as naive (ignore source timezone - it's wrong on travel days)
df['timestamp_local'] = pd.to_datetime(df['Start'], format='%Y-%m-%d %H:%M:%S')

# 2. Localize to assumed home timezone (handles DST correctly)
df['timestamp_local'] = df['timestamp_local'].dt.tz_localize(
    LOCAL_TIMEZONE,
    ambiguous='infer',           # DST fall-back: use context
    nonexistent='shift_forward'  # DST spring-forward: shift to valid time
)

# 3. Convert to UTC for pipeline operations
df['timestamp_utc'] = df['timestamp_local'].dt.tz_convert('UTC')

# 4. Store timezone metadata
df['tz_name'] = 'America/Los_Angeles'
df['tz_source'] = 'assumed'

# 5. Convert local back to naive for Parquet storage
df['timestamp_local'] = df['timestamp_local'].dt.tz_localize(None)
```

**Trade-off accepted:** 95% of data (home days) perfectly correct; 5% of data (travel days) knowingly wrong but consistent. Consistency beats random corruption.

#### Strategy B: Rich Timezone (Workouts, Concept2, JEFIT)
```python
# 1. Extract actual timezone from source
tz_name = workout_json['timezone']  # "America/Los_Angeles"
timestamp_str = workout_json['date']  # "2025-10-30 13:58:00"

# 2. Localize using actual timezone from source
timestamp_local = pd.to_datetime(timestamp_str).tz_localize(
    ZoneInfo(tz_name),
    ambiguous='infer',
    nonexistent='shift_forward'
)

# 3. Convert to UTC
timestamp_utc = timestamp_local.tz_convert('UTC')

# 4. Store metadata
tz_source = 'actual'

# 5. Convert local to naive for Parquet
timestamp_local = timestamp_local.tz_localize(None)
```

**Result:** 100% accurate for all workouts including travel days.

### 4. Idempotent Writes
- Dedupe before write (time-series tables)
- Overwrite partition on re-ingest (daily aggregates)
- Full replacement for sub-workout granular data

---

## Ingestion Algorithms

### HAE Daily CSV → minute_facts, daily_summary

**Column normalization:**
1. Explicit mapping: `RENAME_MAP` dict in code (`Active Energy (kcal)` → `active_energy_kcal`)
2. Fallback: snake_case transformation for unmapped columns
3. Hydration detection: Any header containing "water" → `water_fl_oz` (imperial)

**Timestamp handling:**
- Uses **Strategy A** (assumed timezone) - see Core Design Principles section above
- Assumes home timezone (America/Los_Angeles) for all rows
- Ignores export-time timezone from source (corrupted on travel days)
- Handles DST transitions correctly for home timezone
- Stores: timestamp_utc (pipeline), timestamp_local (analysis), tz_name, tz_source='assumed'

**Minute facts write:**
- Dedupe on (`timestamp_utc`, `source`)
- Write to partitioned dataset: `date=YYYY-MM-DD/source=HAE_CSV/`

**Daily summary derivation:**
- Aggregate from minute_facts OR directly from HAE daily totals
- **Write rule:** Write row if ≥1 metric exists; skip only if all missing
- **Guarded derivations:**
  - `energy_total_kcal = active_energy_kcal + basal_energy_kcal` (if both present)
  - `sleep_efficiency_pct = 100 * sleep_minutes_asleep / sleep_minutes_in_bed` (if both present, denom > 0)
  - `net_energy_kcal = calories_kcal - energy_total_kcal` (if both present)
- **Hydration:** `water_fl_oz` as INT (imperial); conversions from ml/L; values outside ~0-338 fl oz → NULL

---

### HAE Workouts JSON → workouts

**Processing:**
1. Parse JSON exports from Apple Health
2. **Strategy B timestamp handling:** Use actual per-workout timezone from JSON
3. Extract workout metadata: type, duration, distance, HR, calories
4. Synthesize `workout_id` from (source, start_time, workout_type) hash
5. Insert into `workouts` with `source=HAE_JSON`, `tz_source='actual'`

**No granular data:** Apple Health workouts are session-level only.

---

### Concept2 API → workouts, cardio_splits, cardio_strokes

**Three-tier ingestion:**

**Tier 1: Session summary**
```python
# Fetch /users/me/results?limit=N
for workout in results:
    # Strategy B: Use actual timezone from API
    tz_name = workout['timezone']  # "America/Los_Angeles"
    start_time_local = pd.to_datetime(workout['date']).tz_localize(ZoneInfo(tz_name))
    start_time_utc = start_time_local.tz_convert('UTC')
    
    workout_record = {
        'workout_id': workout['id'],
        'source': 'Concept2',
        'workout_type': 'Rowing' | 'Cycling' | 'Skiing',
        'erg_type': workout['type'],  # 'rower', 'bikeerg', 'skierg'
        'start_time_utc': start_time_utc,
        'start_time_local': start_time_local.tz_localize(None),  # Naive for Parquet
        'timezone': tz_name,
        'tz_source': 'actual',
        'duration_s': workout['time'],
        'distance_m': workout['distance'],
        'avg_hr_bpm': workout['heart_rate']['average'],
        'stroke_rate': workout['stroke_rate'],
        'has_splits': workout.get('workout', {}).get('splits') is not None,
        'has_strokes': workout['stroke_data'],
        # ... more fields
    }
    insert_workout(workout_record)
```

**Tier 2: Splits (if available)**
```python
if workout['has_splits']:
    for i, split in enumerate(workout['workout']['splits']):
        split_record = {
            'workout_id': workout['id'],
            'split_number': i + 1,
            'split_time_s': split['time'],
            'split_distance_m': split['distance'],
            'avg_hr_bpm': split['heart_rate']['average'],
            # ... more fields
        }
        insert_split(split_record)
```

**Tier 3: Strokes (if available)**
```python
if workout['stroke_data']:
    # Fetch /users/me/results/{workout_id}/strokes
    strokes = fetch_strokes(workout['id'])
    for i, stroke in enumerate(strokes['data']):
        stroke_record = {
            'workout_id': workout['id'],
            'stroke_number': i + 1,
            'time_cumulative_s': stroke['t'],
            'distance_cumulative_m': stroke['d'],
            'pace_500m_cs': stroke['p'],
            'heart_rate_bpm': stroke['hr'],
            'stroke_rate_spm': stroke['spm'],
        }
        insert_stroke(stroke_record)
```

**Deduplication:**
- Upsert workout by (`workout_id`, `source`)
- Overwrite all splits/strokes for `workout_id` on re-ingest (atomic replacement)

---

### JEFIT CSV → workouts, resistance_sets

**CSV structure (example):**
```
### ROUTINES
_id,name,day,...
100000,"Upper Body",1,...

### MYLOGS
row_id,exercise_id,belongplan,exercisename,set_number,weight,reps,timestamp,...
123,31,100000,"Dumbbell Bench Press",1,60,10,"2025-10-30 13:00:00",...
124,31,100000,"Dumbbell Bench Press",2,60,8,"2025-10-30 13:05:00",...
```

**Processing:**
1. Parse ROUTINES section → identify workout sessions by `belongplan` ID
2. Parse MYLOGS section → group sets by (`belongplan`, `timestamp_date`)
3. **Strategy B timestamp handling:** Use timestamps with user's current timezone from CSV
4. Create `workout_id` = hash(JEFIT, belongplan, date)
5. Insert workout summary (aggregate totals: sets, reps, volume, with tz_source='actual')
6. Insert individual sets with weight/reps/rest

**Workout-level aggregates:**
```python
total_sets = len(sets)
total_reps = sum(s['actual_reps'] for s in sets)
total_volume_lbs = sum(s['actual_reps'] * s['weight_lbs'] for s in sets)
exercises_count = len(set(s['exercise_id'] for s in sets))
```

---

## Validation Rules

### Temporal Integrity
- **Monotonicity:** Within a partition, timestamps should be monotonically increasing (or equal)
- **DST day counts:** Spring-forward days should have ~1380 minutes; fall-back days ~1500 minutes
- **Duplicate detection:** Flag rows with identical (`timestamp_utc`, `source`)

### Value Ranges (guarded)
- `heart_rate_bpm`: 30-220 (typical human range)
- `steps`: 0-50,000 (daily max sanity check)
- `water_fl_oz`: 0-338 (0-10L in imperial)
- `weight_lbs`: 100-400 (user-specific, configure in env)
- `sleep_efficiency_pct`: 0-100

### Workout Validation
- `duration_s` > 0
- `start_time_utc` <= `end_time_utc`
- If `distance_m` present, must be > 0
- If `has_splits=true`, expect splits present
- If `has_strokes=true`, expect strokes present

### Resistance Training Validation
- `actual_reps` >= 0
- `weight_lbs` >= 0
- `set_number` >= 1
- Sets within workout should have sequential set_numbers per exercise

---

## Error Handling

### Ingestion Errors
**Strategy:** Fail fast with clear error messages

**Common errors:**
- **Missing file:** Log warning, skip ingestion
- **Malformed CSV/JSON:** Move to `Data/Error/`, log details
- **API timeout:** Retry with exponential backoff (max 3 retries)
- **Validation failure:** Log row details, optionally skip (depending on severity)

**Logging pattern:**
```python
logger.info(f"minutes: {file} → rows={n}, window={min_ts}..{max_ts}")
logger.info(f"daily_summary: rows={n}, dates={min}..{max}")
logger.warning(f"validation: {issue_type} in {file} at row {idx}")
logger.error(f"FAILED: {file} → {error_type}: {details}")
```

---

## Archive & Cleanup

### Archive Strategy
**After successful ingestion:**
1. Move processed files from `Data/Raw/` to `Data/Archive/`
2. Organize by date: `Data/Archive/{CSV,JSON}/YYYY/MM/`
3. Compress old archives (>6 months) with gzip

**Error files:**
- Move to `Data/Error/` with timestamp suffix
- Review manually, fix issues, re-ingest
- Delete after successful re-processing

---

## Performance Optimizations

### Partitioning Benefits
- **Query pruning:** Date filters skip irrelevant partitions
- **Incremental processing:** Only process new date ranges
- **Parallel writes:** Can write multiple partitions concurrently

### Compression
- **Parquet snappy:** ~70% compression typical
- **Columnar storage:** Efficient for analytical queries
- **Predicate pushdown:** Filter at read time, not in memory

### API Rate Limiting (Concept2)
- **Rate limit:** Unknown (be conservative)
- **Strategy:** Batch fetch workouts (limit=50), then fetch strokes individually
- **Caching:** Cache workout IDs already ingested, skip on re-run

---

## Daily Summary Implementation Policy

### Write Rule
- Write row if **any** metric exists for that `date × source`
- **Skip** only if *all* metrics are missing

### Units
- **Imperial for hydration:** `water_fl_oz` (INT)
- Conversions handled from ml/L
- Values outside ~0-338 fl oz → NULL

### Derived Metrics (Guarded)
Only compute if inputs are present:
- `energy_total_kcal` (if active + basal present)
- `sleep_efficiency_pct` (if asleep + in_bed present, denom > 0)
- `net_energy_kcal` (if calories + energy_total present)

---

## Header Crosswalk (HAE CSV)

### Canonical Mapping Intent
Maintain explicit dict in code: `RENAME_MAP`

**Examples (non-exhaustive):**
- `Active Energy (kcal)` → `active_energy_kcal`
- `Resting Energy (kcal)` → `basal_energy_kcal`
- `Walking + Running Distance (mi)` → `distance_mi`
- `Steps (count)` → `steps`
- Sleep: `Sleep Analysis Asleep (min)` → `sleep_minutes_asleep`
- Body: `Weight (lb)` → `weight_lb`, `Body Fat Percentage (%)` → `body_fat_pct`

**Hydration detection:** Any header containing "water" → `water_fl_oz` (imperial)

**Fallback:** Unmapped columns → snake_case transformation

---

## Operational Logging

### Minute Facts (per file)
```
minutes: HealthAutoExport-2025-10-30.csv → rows=1440, window=2025-10-30T00:00:00..2025-10-30T23:59:00, non_null_top=[steps:1200, heart_rate_avg:1000, active_energy_kcal:800]
```

### Daily Summary
**Written:**
```
daily_summary: rows=5, dates=2025-10-26..2025-10-30, sample={steps=8500, energy_total_kcal=2200, water_fl_oz=80}
```

**Skipped:**
```
OK: HealthAutoExport-2025-10-30.csv → Data/Parquet/daily_summary (daily_summary skipped: no metrics)
```

### Header Crosswalk Audit (Optional)
```
header-xwalk: unmapped=3 [Environmental Audio Exposure (dB), Outdoor Temperature (°F), ...]
```

---

## Future Enhancements

### Phase 3: Manual Entry Tables
- **labs:** Lab results with protocol context
- **protocol_history:** Supplement/medication tracking
- **glucose_ketone:** CGM data
- **lactate:** Lactate meter readings

### Phase 4: Enrichment Pipeline
- **enriched_workouts:** Join workout data with minute_facts HR
- **daily_metrics_enriched:** Trending, percentiles, anomaly detection
- **body_metrics_calculated:** Body comp trends, strength ratios

### Phase 5: Analysis Outputs
- **Auto-generate compound tracker:** Replace manual spreadsheet
- **Power curve visualizations:** Concept2 performance analysis
- **Volume periodization:** Resistance training load management
- **Recovery metrics:** HRV trends, sleep quality correlation

---

## Version History

| Version | Date       | Changes |
|---------|------------|---------|
| v2.0    | 2025-11-01 | Added Concept2 and JEFIT ingestion algorithms; validation rules for new tables |
| v1.0    | 2025-10-25 | Initial design: HAE CSV algorithms, DST handling, daily summary rules |
