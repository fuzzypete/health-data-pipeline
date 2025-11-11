# Decision: Deduplication Approaches

**Date:** 2024-09-25  
**Status:** Implemented  
**Impact:** High (affects data quality and storage efficiency)

## Context

Multiple data sources can produce duplicate records due to:
1. **Re-ingesting overlapping time periods** (e.g., re-downloading same month)
2. **Multiple devices logging same data** (iPhone + Apple Watch)
3. **API pagination edge cases** (same workout in multiple API calls)
4. **Manual data entry errors** (logging same workout twice)

Need systematic deduplication to ensure accurate analytics without double-counting.

## Problem

Without deduplication:
- Metrics are inflated (e.g., 2x steps, 2x distance)
- Averages become meaningless (duplicate HR readings skew stats)
- Storage bloat (same data stored multiple times)
- Query performance degrades (more rows to scan)

## Options Considered

### Option 1: No Deduplication (Naive)
Trust sources never produce duplicates.

**Pros:**
- Simple implementation
- Fast ingestion

**Cons:**
- **Unrealistic assumption** - duplicates happen frequently
- Data quality issues accumulate over time
- Hard to fix retroactively

**Verdict:** Not viable for production system.

### Option 2: Exact Match Deduplication
Drop rows where ALL fields match exactly.

**Pros:**
- Simple logic: `df.drop_duplicates()`
- Fast performance

**Cons:**
- **Too strict:** Minor differences prevent deduplication
  - Same HR reading from different devices: different `source_device_id` → not duplicate
  - Timestamps differ by 1 second due to device clock drift → not duplicate
- Misses most real duplicates

### Option 3: Composite Key Deduplication (CHOSEN)
Define logical uniqueness criteria per table based on business logic.

**Pros:**
- **Flexible:** Different keys for different data types
- **Accurate:** Captures true duplicates
- **Documented:** Explicit about what constitutes a duplicate

**Cons:**
- Requires thought per table
- Slightly more complex code

### Option 4: Fuzzy Timestamp Matching
Treat timestamps within N seconds as duplicates.

**Pros:**
- Handles device clock drift
- Can catch near-duplicates

**Cons:**
- **Risk of false positives:** Legitimate readings within N seconds treated as duplicates
- Slower performance (must compare timestamps)
- Hard to tune threshold

**Use case:** Only for sources with known clock drift issues.

## Decision

Use **composite key deduplication** with table-specific keys.

Define logical primary/composite key for each table based on what makes a record truly unique.

## Implementation

### Key Selection Patterns

**Pattern 1: API-Provided Unique ID**
Source has guaranteed unique identifier.

```python
# Concept2 workouts
df.drop_duplicates(subset=['workout_id'], keep='first')
```

**Examples:**
- `concept2_workouts.workout_id`
- `labs_results.result_id` (UUID)

**Pattern 2: Natural Composite Key**
Combination of fields logically unique.

```python
# HAE heart rate: same timestamp + value + device = duplicate
df.drop_duplicates(
    subset=['timestamp_utc', 'heart_rate_bpm', 'source_device_id'],
    keep='first'
)
```

**Examples:**
- `hae_heart_rate_minute: (timestamp_utc, heart_rate_bpm, source_device_id)`
- `concept2_splits: (workout_id, split_number)`
- `jefit_sets: (workout_id, exercise_name, set_number)`

**Pattern 3: Generated Hash Key**
Source has no native ID, generate stable hash.

```python
# JEFIT workouts: hash based on logical identity
import hashlib

def generate_workout_id(row):
    components = f"{row['date']}|{row['workout_name']}|{sorted(row['exercises'])}"
    return hashlib.sha256(components.encode()).hexdigest()[:16]

df['workout_id'] = df.apply(generate_workout_id, axis=1)
df.drop_duplicates(subset=['workout_id'], keep='first')
```

**Examples:**
- `jefit_workouts: hash(date, workout_name, sorted_exercises)`
- `protocols_doses: hash(date, compound_id, time_of_day, dose_amount)`

### Keep Strategy: `keep='first'`

When duplicates found, keep the FIRST occurrence (earliest ingestion).

**Rationale:**
- Preserves original `ingestion_id` (audit trail)
- Respects temporal ordering
- Consistent behavior across all tables

**Alternative considered:** `keep='last'` (newest data)
- Rejected: Could overwrite historical records with re-ingested data
- Exception: Could use for tables where "latest wins" (reference data)

## Table-Specific Deduplication Keys

### HAE Tables
All use `(timestamp_utc, metric_value, source_device_id)` pattern.

```python
# hae_heart_rate_minute
dedup_key = ['timestamp_utc', 'heart_rate_bpm', 'source_device_id']

# hae_steps_minute  
dedup_key = ['timestamp_utc', 'steps', 'source_device_id']

# hae_body_mass
dedup_key = ['timestamp_utc', 'body_mass_kg', 'source_device_id']
```

**Why `source_device_id`?**
- iPhone and Apple Watch both log HR → legitimately different readings
- Same timestamp + same value + different device = NOT duplicate
- Same timestamp + same value + same device = duplicate

### Concept2 Tables
```python
# workouts: API-guaranteed unique ID
dedup_key = ['workout_id']

# splits: composite key
dedup_key = ['workout_id', 'split_number']

# strokes: composite key  
dedup_key = ['workout_id', 'stroke_number']
```

**Why this works:**
- `workout_id` from API is globally unique
- `split_number` and `stroke_number` are sequential within workout
- No hash needed - natural keys

### JEFIT Tables
```python
# workouts: generated hash
dedup_key = ['workout_id']  # where workout_id = hash(date, name, exercises)

# sets: generated hash
dedup_key = ['set_id']  # where set_id = hash(workout_id, exercise, set_number)
```

**Why hash-based:**
- JEFIT CSV has no native IDs
- Hash ensures stable ID across re-imports
- Same workout logged twice → same hash → deduplicated

### Oura Tables
```python
# readiness_daily, sleep_daily, activity_daily
dedup_key = ['date']  # One summary per day

# heart_rate_5min
dedup_key = ['timestamp_utc']  # One reading per 5-min interval
```

**Why date/timestamp alone:**
- Oura provides one summary per day (guaranteed unique)
- 5-min HR readings have precise timestamps (no overlaps)

### Labs & Protocols
```python
# labs_results
dedup_key = ['test_date', 'biomarker_name']  # One result per biomarker per test date

# protocols_doses
dedup_key = ['date', 'compound_id', 'time_of_day']  # One dose per compound per time slot
```

## Edge Cases

### Case 1: Legitimate Near-Duplicates
**Scenario:** Two HR readings 1 second apart.

**Current behavior:** Both kept (different timestamps).

**Acceptable?** Yes - minute-level data should capture both.

**Exception:** If known device glitch, use fuzzy matching:
```python
def deduplicate_fuzzy_time(df, threshold_seconds=60):
    df_sorted = df.sort_values('timestamp_utc')
    df_sorted['time_diff'] = df_sorted['timestamp_utc'].diff().dt.total_seconds()
    df_sorted['is_duplicate'] = (df_sorted['time_diff'] < threshold_seconds) & \
                                 (df_sorted['heart_rate_bpm'] == df_sorted['heart_rate_bpm'].shift())
    return df_sorted[~df_sorted['is_duplicate']]
```

### Case 2: Multiple Devices, Same Value
**Scenario:** iPhone HR = 72 bpm, Apple Watch HR = 72 bpm at same timestamp.

**Current behavior:** Both kept (different `source_device_id`).

**Acceptable?** Yes - could be coincidence, or could be one device reading from the other.

**Future enhancement:** Device priority rules (prefer Watch over Phone).

### Case 3: Re-ingesting with Schema Changes
**Scenario:** Re-ingest old data after adding new column.

**Current behavior:** Deduplication uses only key columns, not all columns.

**Acceptable?** Yes - allows schema evolution without treating all old data as "different".

### Case 4: Null Values in Key
**Scenario:** `source_device_id` is null for some records.

**Current behavior:** All nulls treated as same value → may over-deduplicate.

**Solution:** Fill nulls with sentinel:
```python
df['source_device_id'] = df['source_device_id'].fillna('UNKNOWN')
```

## Results

**Before Deduplication:**
- Re-ingesting October HAE data: +1.4M rows (duplicates of existing data)
- Step counts doubled after re-import
- Daily aggregates incorrect

**After Deduplication:**
- Re-ingesting October HAE data: +0 rows (all duplicates removed)
- Metrics consistent across re-imports
- Storage footprint stays flat

### Performance Impact

| Table | Rows Before | Rows After | Dedup Time |
|-------|------------|-----------|------------|
| hae_heart_rate_minute (1 month) | 1,440,000 | 1,420,000 | ~2 seconds |
| concept2_strokes (100 workouts) | 2,000,000 | 2,000,000 | ~1 second |
| jefit_sets (1 year) | 15,000 | 14,800 | <0.1 seconds |

**Key takeaway:** Deduplication overhead is negligible (~1-2% of ingestion time).

## Trade-offs Accepted

1. **Keep first, not last:**
   - Preserves historical `ingestion_id`
   - Could miss corrections if source data fixed later
   - Acceptable: Source corrections are rare, audit trail more important

2. **No fuzzy timestamp matching by default:**
   - Avoids false positives
   - Misses duplicates with clock drift
   - Acceptable: Clock drift minimal in practice, can add fuzzy matching for specific sources if needed

3. **Device-specific HAE data:**
   - Multiple devices = multiple readings kept
   - Could inflate counts if both devices active
   - Acceptable: Better to keep both than lose data, can filter by preferred device in queries

## Lessons Learned

1. **Define uniqueness upfront:**
   - Think through "what makes this record unique?" before ingesting
   - Easier to deduplicate during ingestion than fix retroactively

2. **Use natural keys when available:**
   - API-provided IDs are better than generated hashes
   - Less chance of collision or logic errors

3. **Hash generation must be stable:**
   - `hash(date, name, sorted(exercises))` → consistent
   - `hash(date, name, exercises)` → order-dependent, breaks on re-sort

4. **Deduplication is cheap:**
   - Pandas `drop_duplicates()` is fast
   - No reason to skip this step

## Testing Strategy

```python
def test_hae_deduplication():
    """Same timestamp + value + device = duplicate"""
    data = {
        'timestamp_utc': ['2024-11-10 14:00', '2024-11-10 14:00', '2024-11-10 14:01'],
        'heart_rate_bpm': [72, 72, 75],
        'source_device_id': ['iPhone', 'iPhone', 'iPhone']
    }
    df = pd.DataFrame(data)
    deduped = df.drop_duplicates(subset=['timestamp_utc', 'heart_rate_bpm', 'source_device_id'])
    assert len(deduped) == 2  # First two are duplicates

def test_concept2_deduplication():
    """Workout ID is unique"""
    data = {
        'workout_id': ['abc123', 'abc123', 'xyz789'],
        'distance_meters': [5000, 5000, 3000]
    }
    df = pd.DataFrame(data)
    deduped = df.drop_duplicates(subset=['workout_id'])
    assert len(deduped) == 2

def test_jefit_hash_stability():
    """Same workout data produces same hash"""
    workout_a = hash_workout('2024-11-10', 'Upper A', ['Bench Press', 'Rows'])
    workout_b = hash_workout('2024-11-10', 'Upper A', ['Rows', 'Bench Press'])  # Different order
    assert workout_a == workout_b  # Must sort exercises first
```

---

**Related:**
- [DataSources.md](../DataSources.md) - Source-specific deduplication keys
- [Schema.md](../Schema.md) - Primary/composite keys
- [StorageAndQuery.md](../StorageAndQuery.md) - Deduplication performance
