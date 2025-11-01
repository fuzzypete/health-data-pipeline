# Health Data Pipeline — Timestamp Handling (Source of Truth)
**Date:** 2025-11-01  
**Version:** 1.0

## Executive Summary

This document defines the **canonical approach** to timestamp handling across the HDP. All ingestion code must follow these rules.

**The Core Principle:** Use different strategies for different data quality levels. Consistency beats aspirational accuracy when source data is fundamentally flawed.

**The Solution:** Hybrid ingestion with two strategies:
- **Strategy A (Assumed Timezone):** For lossy sources (HAE CSV, HAE Daily JSON)
- **Strategy B (Rich Timezone):** For correct sources (Workouts, Concept2, JEFIT)

**The Schema:** Three timestamps enable everything:
- `timestamp_local` - For analysis (circadian patterns)
- `tz_name` - The context that makes local unambiguous
- `timestamp_utc` - For pipeline operations (joins, dedup, partitioning)

---

## 1. The Problem

### Goal vs. Reality

**What we want:** "Waking day" analysis using correct local timestamps
- Sleep patterns by wall-clock time
- Meal timing relative to circadian rhythm
- Workout performance by time-of-day
- Glucose patterns by hours-since-waking

**What we have:** Sources with varying timezone data quality

| Source | Timezone Quality | Problem |
|--------|-----------------|---------|
| HAE CSV | **Lossy** | Export-time timezone, not per-event timezone |
| HAE Daily JSON | **Lossy** | Same as CSV - timezone at export time only |
| HAE Workout JSON | **Rich** | Per-event timezone stored correctly |
| Concept2 API | **Rich** | Returns `timezone` and `date_utc` per workout |
| JEFIT CSV | **Rich** | Timestamps with user's current timezone |

### The "Travel Day" Problem

**Scenario:** You live in Seattle (UTC-8/-7), travel to St. Louis (UTC-6/-5)

**What happens:**
1. Morning in Seattle: Blood glucose reading at 08:00 PST
2. Evening in St. Louis: Export HAE data at 20:00 CST
3. **Result:** Seattle glucose reading is stamped "08:00 CST" in the export

**The corruption:**
```
Actual:    2025-11-15 08:00:00 PST (UTC-8) → 2025-11-15 16:00:00 UTC
Exported:  2025-11-15 08:00:00 CST (UTC-6) → 2025-11-15 14:00:00 UTC
Error:     2 hours wrong in UTC, wrong timezone in local
```

### The "Consistency" Mandate

**Bad approach:** Trust the source timezone
- Travel day: 5% of data corrupted
- Home days: 95% correct
- **Result:** Chaos in analysis (which rows are trustworthy?)

**Good approach:** Assume home timezone
- Travel days: 5% knowingly wrong
- Home days: 100% correct
- **Result:** Consistent dataset with documented limitations

**Trade-off:** 95% perfect + 5% consistently wrong > 95% perfect + 5% randomly corrupted

---

## 2. The Solution: Hybrid Ingestion

### Strategy A: Assumed Timezone Ingester

**Used for:** HAE CSV, HAE Daily JSON → `minute_facts`, `daily_summary`

**Algorithm:**
```python
# Configuration
LOCAL_TIMEZONE = ZoneInfo("America/Los_Angeles")

def ingest_with_assumed_timezone(df, source_name):
    """
    Strategy A: Ignore source timezone, assume home timezone
    """
    # 1. Read timestamp_local as naive (no timezone)
    df['timestamp_local'] = pd.to_datetime(df['timestamp_local_column'], 
                                           format='%Y-%m-%d %H:%M:%S')
    
    # 2. IGNORE any timezone in source data
    # The source's timezone is wrong, don't use it
    
    # 3. Localize using ASSUMED timezone
    # This correctly handles DST transitions for YOUR home zone
    df['timestamp_local'] = df['timestamp_local'].dt.tz_localize(
        LOCAL_TIMEZONE, 
        ambiguous='infer',    # DST fall-back: use context to infer
        nonexistent='shift_forward'  # DST spring-forward: shift to valid time
    )
    
    # 4. Create UTC from correctly-localized local time
    df['timestamp_utc'] = df['timestamp_local'].dt.tz_convert('UTC')
    
    # 5. Store timezone name as ASSUMED (not from source)
    df['tz_name'] = 'America/Los_Angeles'
    df['tz_source'] = 'assumed'
    
    # 6. Convert to naive for Parquet storage
    df['timestamp_local'] = df['timestamp_local'].dt.tz_localize(None)
    
    return df[['timestamp_utc', 'timestamp_local', 'tz_name', 'tz_source', ...]]
```

**Result:**
- ✅ Clean, consistent minute_facts
- ✅ Correct DST handling for home timezone
- ✅ 95% of data perfectly correct
- ⚠️ 5% of data (travel days) knowingly wrong but consistent
- ✅ Can be corrected later with manual travel log

---

### Strategy B: Rich Timezone Ingester

**Used for:** HAE Workout JSON, Concept2 API, JEFIT CSV → `workouts`, `cardio_splits`, `cardio_strokes`, `resistance_sets`

**Algorithm:**
```python
def ingest_with_rich_timezone(record):
    """
    Strategy B: Trust source timezone (it's correct for these sources)
    """
    # 1. Read timestamp_local and timezone from source
    timestamp_local_str = record['date']  # "2025-10-30 13:58:00"
    tz_name = record['timezone']          # "America/Los_Angeles"
    
    # 2. Localize using ACTUAL timezone from source
    timestamp_local = pd.to_datetime(timestamp_local_str)
    timestamp_local = timestamp_local.tz_localize(
        ZoneInfo(tz_name),
        ambiguous='infer',
        nonexistent='shift_forward'
    )
    
    # 3. Create UTC from correctly-localized local time
    timestamp_utc = timestamp_local.tz_convert('UTC')
    
    # 4. Store timezone name as ACTUAL (from source)
    tz_source = 'actual'
    
    # 5. Convert to naive for Parquet storage
    timestamp_local = timestamp_local.tz_localize(None)
    
    return {
        'timestamp_utc': timestamp_utc,
        'timestamp_local': timestamp_local,
        'tz_name': tz_name,
        'tz_source': tz_source,
        ...
    }
```

**Result:**
- ✅ Perfect accuracy for all workouts
- ✅ Correct timezone on travel days
- ✅ No assumptions, no corrections needed

---

## 3. The Schema: Three Timestamps

### Field Definitions

| Field | Type | Nullable | Purpose | Source |
|-------|------|----------|---------|--------|
| `timestamp_local` | timestamp (no TZ) | NO | **For analysis.** The "wall clock" time. Use for circadian patterns, grouping by hour-of-day, time-since-waking. | Read directly from source |
| `tz_name` | string | YES | **The context.** Makes `timestamp_local` unambiguous. IANA timezone (e.g., "America/Los_Angeles"). | Strategy A: Assumed constant. Strategy B: From source. |
| `timestamp_utc` | timestamp (UTC) | NO | **For pipeline.** Absolute, normalized time. Use for partitioning, deduplication, joins, sorting. | **Always calculated,** never read from source |

### Additional Metadata (Optional)

| Field | Type | Purpose |
|-------|------|---------|
| `tz_source` | enum("assumed", "actual") | Documents whether `tz_name` was assumed or came from source |
| `is_travel_day` | boolean | Manual flag for known travel days (for filtering in analysis) |

---

## 4. Implementation Details

### DST Handling

**Ambiguous times (fall-back):**
```python
# November 3, 2024, 01:30 AM happened twice in America/Los_Angeles
# - First time: 01:30 PDT (UTC-7)
# - Second time: 01:30 PST (UTC-8)

dt.tz_localize(tz, ambiguous='infer')
# Uses surrounding context to pick the right one
```

**Nonexistent times (spring-forward):**
```python
# March 10, 2024, 02:30 AM never existed in America/Los_Angeles
# Clocks jumped from 02:00 → 03:00

dt.tz_localize(tz, nonexistent='shift_forward')
# Shifts 02:30 → 03:00 (the actual time on the clock)
```

### Parquet Storage

**Why naive timestamps for local:**
```python
# Parquet doesn't support "timestamp with timezone name"
# Only supports: naive timestamp OR timestamp with UTC offset

# Bad: Would lose timezone name
df['timestamp_local'].dt.tz_localize('America/Los_Angeles')  # Has offset, loses name

# Good: Store naive + store tz_name separately
df['timestamp_local'] = df['timestamp_local'].dt.tz_localize(None)
df['tz_name'] = 'America/Los_Angeles'
```

**Reading back:**
```python
# When reading from Parquet for analysis
df = pd.read_parquet('minute_facts')

# Reconstruct timezone-aware local timestamp
df['timestamp_local_aware'] = pd.to_datetime(df['timestamp_local']).dt.tz_localize(
    df['tz_name'].iloc[0]  # Assuming single timezone per partition
)
```

---

## 5. Query Patterns

### Circadian Analysis (Use timestamp_local)

**Example: Glucose patterns by hour of day**
```sql
SELECT 
  EXTRACT(HOUR FROM timestamp_local) as hour_of_day,
  AVG(glucose_mg_dl) as avg_glucose
FROM minute_facts
WHERE tz_source = 'assumed'  -- Only use consistent home timezone data
  AND NOT is_travel_day      -- Exclude known travel days
GROUP BY hour_of_day
ORDER BY hour_of_day
```

**Example: Sleep quality by bedtime**
```sql
SELECT 
  EXTRACT(HOUR FROM start_time_local) as bedtime_hour,
  AVG(sleep_score) as avg_sleep_quality
FROM workouts
WHERE workout_type = 'Sleep'
  AND tz_source = 'actual'   -- Workouts have correct timezone
GROUP BY bedtime_hour
```

### Pipeline Operations (Use timestamp_utc)

**Example: Join workout with surrounding glucose**
```sql
SELECT 
  w.workout_id,
  w.workout_type,
  AVG(mf.glucose_mg_dl) as avg_glucose_during_workout
FROM workouts w
JOIN minute_facts mf 
  ON mf.timestamp_utc BETWEEN w.start_time_utc AND w.end_time_utc
WHERE w.date = '2025-10-30'
GROUP BY w.workout_id, w.workout_type
```

**Example: Deduplicate on UTC**
```python
# Remove duplicates based on absolute time
df_deduped = df.drop_duplicates(subset=['timestamp_utc', 'source'])
```

### Time-of-Day Analysis (Use both)

**Example: Workout performance by time of day (home timezone)**
```sql
SELECT 
  EXTRACT(HOUR FROM start_time_local) as hour,
  AVG(avg_hr_bpm) as avg_hr,
  AVG(calories_kcal) as avg_calories
FROM workouts
WHERE tz_name = 'America/Los_Angeles'  -- Only home timezone workouts
  OR tz_source = 'actual'              -- Or use actual timezone data
GROUP BY hour
ORDER BY hour
```

---

## 6. Known Limitations & Mitigation

### Limitation 1: Travel Days in minute_facts

**Problem:** HAE CSV data from travel days has wrong timezone assumption

**Impact:**
- ~5% of data (if you travel 2-3 weeks per year)
- Affects: minute_facts, daily_summary
- Does NOT affect: workouts (Strategy B)

**Mitigation:**
```sql
-- Option 1: Manual travel log table
CREATE TABLE travel_periods (
  start_date DATE,
  end_date DATE,
  actual_timezone STRING
);

-- Option 2: Flag and filter
SELECT * FROM minute_facts
WHERE date NOT IN (SELECT date FROM travel_periods);

-- Option 3: Accept the limitation
-- For most analyses, 5% noise is acceptable
```

### Limitation 2: Timezone Changes (Moving)

**Problem:** If you move to a new timezone, old assumption is wrong

**Solution:** 
1. Update `LOCAL_TIMEZONE` config
2. **Do NOT re-ingest old data** (would corrupt UTC)
3. Document timezone change date
4. Filter analyses: "Data from Seattle era vs. Austin era"

```python
# config.yaml
timezone:
  default: "America/Los_Angeles"
  changes:
    - before: "2025-06-01"
      timezone: "America/Los_Angeles"
    - after: "2025-06-01"
      timezone: "America/Chicago"
```

### Limitation 3: DST Transitions

**Problem:** Ambiguous or nonexistent times during DST changes

**Solution:** Already handled by `ambiguous='infer'` and `nonexistent='shift_forward'`

**Verification:**
```python
# Test DST transitions
test_dates = [
    '2024-03-10 02:30:00',  # Spring forward (nonexistent)
    '2024-11-03 01:30:00',  # Fall back (ambiguous)
]
for date_str in test_dates:
    dt = pd.to_datetime(date_str)
    local = dt.tz_localize('America/Los_Angeles', 
                          ambiguous='infer', 
                          nonexistent='shift_forward')
    print(f"{date_str} → {local} → {local.tz_convert('UTC')}")
```

---

## 7. Configuration

### config.yaml
```yaml
timezone:
  # Primary timezone for Strategy A (assumed timezone)
  default: "America/Los_Angeles"
  
  # Strategy assignments
  strategy_a_sources:
    - HAE_CSV
    - HAE_Daily_JSON
  
  strategy_b_sources:
    - HAE_Workout_JSON
    - Concept2
    - JEFIT
  
  # Historical timezone changes (if you moved)
  changes:
    - before: "2025-06-01"
      timezone: "America/Los_Angeles"
      notes: "Seattle era"
    # - after: "2025-06-01"
    #   timezone: "America/Chicago"
    #   notes: "Moved to Austin"
  
  # Known travel periods (optional, for filtering)
  travel_periods:
    - start: "2025-03-15"
      end: "2025-03-22"
      timezone: "Europe/London"
      notes: "London vacation"
```

---

## 8. Testing Requirements

### Unit Tests

**Test DST transitions:**
```python
def test_dst_spring_forward():
    # 2024-03-10 02:30 doesn't exist in America/Los_Angeles
    dt = pd.to_datetime('2024-03-10 02:30:00')
    local = dt.tz_localize('America/Los_Angeles', nonexistent='shift_forward')
    assert local.hour == 3  # Should shift to 03:00
    
def test_dst_fall_back():
    # 2024-11-03 01:30 is ambiguous
    dt = pd.to_datetime('2024-11-03 01:30:00')
    local = dt.tz_localize('America/Los_Angeles', ambiguous='infer')
    assert local is not None  # Should resolve to one of the two
```

**Test Strategy A:**
```python
def test_assumed_timezone_ingestion():
    df = pd.DataFrame({
        'timestamp': ['2025-10-30 08:00:00', '2025-10-30 09:00:00']
    })
    result = ingest_with_assumed_timezone(df, 'HAE_CSV')
    
    assert result['tz_name'].iloc[0] == 'America/Los_Angeles'
    assert result['tz_source'].iloc[0] == 'assumed'
    assert result['timestamp_utc'] is not None
```

**Test Strategy B:**
```python
def test_rich_timezone_ingestion():
    record = {
        'date': '2025-10-30 13:58:00',
        'timezone': 'America/Los_Angeles'
    }
    result = ingest_with_rich_timezone(record)
    
    assert result['tz_name'] == 'America/Los_Angeles'
    assert result['tz_source'] == 'actual'
    assert result['timestamp_utc'] is not None
```

### Integration Tests

**Test travel day scenario:**
```python
def test_travel_day_consistency():
    # Simulate export in St. Louis with Seattle data
    seattle_data = "2025-10-30 08:00:00"  # Morning in Seattle
    
    # Strategy A should use America/Los_Angeles regardless
    result = ingest_with_assumed_timezone(seattle_data, 'HAE_CSV')
    
    # Verify it used Seattle timezone, not St. Louis
    assert result['tz_name'] == 'America/Los_Angeles'
    # The UTC time should be Seattle's UTC offset
```

---

## 9. Migration Guide

### Existing Data

If you have already ingested data with a different strategy:

**Option 1: Accept and document**
- Old data used different logic → document cutoff date
- New data uses this logic → all new ingestions consistent

**Option 2: Re-ingest** (only if critical)
```bash
# 1. Back up current data
cp -r Data/Parquet Data/Parquet.backup

# 2. Delete existing partitions
rm -rf Data/Parquet/minute_facts/*
rm -rf Data/Parquet/daily_summary/*

# 3. Re-run ingestion with new logic
make ingest-all

# 4. Verify consistency
make test-timestamp-integrity
```

---

## 10. Decision Record

**Date:** 2025-11-01  
**Decision:** Adopt hybrid timestamp strategy (Strategy A + Strategy B)  
**Rationale:** 
- HAE CSV/JSON sources are fundamentally lossy
- Travel day problem is unfixable at source level
- Consistency (99% correct, 1% knowingly wrong) beats chaos (99% correct, 1% randomly corrupted)
- Workouts/Concept2/JEFIT have rich timezone data - use it
- Three-timestamp schema enables both strategies

**Alternatives Considered:**
1. **Trust all source timezones** - Rejected: Creates corrupt data on travel days
2. **Parse and correct travel days** - Rejected: Impossible without external travel log
3. **Use UTC only** - Rejected: Breaks circadian analysis
4. **Store only local time** - Rejected: Breaks joins and deduplication

**Trade-offs Accepted:**
- Travel day data in minute_facts will be wrong (~5% of data)
- Acceptable because: consistent, documentable, filterable, correctable later

**Review Date:** 2026-01-01 (after 2 months of usage)

---

## 11. References

**Python timezone handling:**
- `zoneinfo.ZoneInfo` - IANA timezone database
- `pandas.Series.dt.tz_localize()` - Add timezone to naive timestamps
- `pandas.Series.dt.tz_convert()` - Convert between timezones

**DST rules:**
- Spring forward: Second Sunday in March, 2:00 AM → 3:00 AM
- Fall back: First Sunday in November, 2:00 AM → 1:00 AM (repeated)

**IANA timezone database:**
- Canonical names: "America/Los_Angeles", "Europe/London", "Asia/Tokyo"
- Includes all historical DST rule changes

---

## Appendix A: Example Implementations

### Full Strategy A Implementation
```python
# src/pipeline/ingest/csv_delta.py

from zoneinfo import ZoneInfo
import pandas as pd

LOCAL_TIMEZONE = ZoneInfo("America/Los_Angeles")

def process_hae_csv(file_path):
    """Strategy A: Assumed timezone ingestion"""
    
    # 1. Read CSV
    df = pd.read_csv(file_path)
    
    # 2. Parse timestamp as naive
    df['timestamp_local'] = pd.to_datetime(
        df['Start'],  # Or whatever the column name is
        format='%Y-%m-%d %H:%M:%S'
    )
    
    # 3. Localize to assumed timezone (handles DST)
    df['timestamp_local'] = df['timestamp_local'].dt.tz_localize(
        LOCAL_TIMEZONE,
        ambiguous='infer',
        nonexistent='shift_forward'
    )
    
    # 4. Convert to UTC
    df['timestamp_utc'] = df['timestamp_local'].dt.tz_convert('UTC')
    
    # 5. Add metadata
    df['tz_name'] = str(LOCAL_TIMEZONE)
    df['tz_source'] = 'assumed'
    df['source'] = 'HAE_CSV'
    
    # 6. Convert local back to naive for Parquet
    df['timestamp_local'] = df['timestamp_local'].dt.tz_localize(None)
    
    return df
```

### Full Strategy B Implementation
```python
# src/pipeline/ingest/concept2_api.py

from zoneinfo import ZoneInfo
import pandas as pd

def process_concept2_workout(workout_json):
    """Strategy B: Rich timezone ingestion"""
    
    # 1. Extract timezone and timestamp from API response
    tz_name = workout_json['timezone']
    timestamp_local_str = workout_json['date']
    
    # 2. Parse as naive
    timestamp_local = pd.to_datetime(timestamp_local_str)
    
    # 3. Localize to actual timezone from source
    timestamp_local = timestamp_local.tz_localize(
        ZoneInfo(tz_name),
        ambiguous='infer',
        nonexistent='shift_forward'
    )
    
    # 4. Convert to UTC
    timestamp_utc = timestamp_local.tz_convert('UTC')
    
    # 5. Build workout record
    workout_record = {
        'workout_id': workout_json['id'],
        'start_time_local': timestamp_local.tz_localize(None),  # Naive for Parquet
        'start_time_utc': timestamp_utc,
        'timezone': tz_name,
        'tz_source': 'actual',
        'source': 'Concept2',
        # ... other fields
    }
    
    return workout_record
```

---

**END OF DOCUMENT**

This is the canonical source of truth for timestamp handling in the Health Data Pipeline.  
All implementation code must follow these specifications.
