# Health Data Pipeline — Timestamp Handling (v1.1)
**Date:** 2025-11-08  
**Last Updated:** Corrected JEFIT classification

## 1. The Problem

Health data sources have varying levels of timezone quality:

| Source | Timezone Quality | Problem |
|--------|------------------|---------|
| **Rich Timezone Sources** |
| HAE Workout JSON | **Rich** | Per-workout timezone preserved correctly |
| Concept2 API | **Rich** | Per-workout timezone from API |
| **Lossy Timezone Sources** |
| HAE CSV/JSON (Daily) | **Lossy** | Export-time timezone only; corrupted on travel days |
| JEFIT CSV | **Lossy** | No timezone provided; naive timestamps only |

**Key insight:** Not all sources are equally trustworthy for timezone data.

---

## 2. Solution: Hybrid Ingestion Strategy

### Strategy A: Assumed Timezone (Lossy Sources)

**Used for:** HAE CSV, HAE Daily JSON, JEFIT CSV → `minute_facts`, `daily_summary`, `workouts`, `resistance_sets`

**Approach:** Ignore any source timezone (corrupted or missing), assume home timezone consistently.

**Implementation:**
```python
from zoneinfo import ZoneInfo
LOCAL_TIMEZONE = ZoneInfo("America/Los_Angeles")

# 1. Parse timestamp as naive (ignore source timezone)
df['timestamp_local'] = pd.to_datetime(df['timestamp'])

# 2. Localize to assumed home timezone
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

**Result:**
- ✅ 95% of data (home days) perfectly correct
- ⚠️ 5% of data (travel days) knowingly wrong but **consistent**
- ✅ Enables clean circadian analysis without random corruption
- ✅ Can be corrected later with manual travel log

**Trade-off:** Consistency beats random corruption.

---

### Strategy B: Rich Timezone (High-Quality Sources)

**Used for:** HAE Workout JSON, Concept2 API → `workouts`, `cardio_splits`, `cardio_strokes`

**Approach:** Trust per-event timezone from source (it's correct).

**Implementation:**
```python
from zoneinfo import ZoneInfo

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

**Result:**
- ✅ 100% accurate for all workouts including travel days
- ✅ No assumptions, no corrections needed

---

## 3. Three-Timestamp Schema

All tables store three timestamps to support both pipeline operations and circadian analysis:

| Field | Type | Purpose | Example |
|-------|------|---------|---------|
| `timestamp_utc` | timestamp (UTC) | **Pipeline canonical time.** Absolute, normalized timestamp for joins, dedup, partitioning, sorting. | 2025-10-30 20:58:00+00:00 |
| `timestamp_local` | timestamp (naive) | **Analysis time.** Wall clock time for circadian patterns, hour-of-day analysis. Stored naive in Parquet. | 2025-10-30 13:58:00 |
| `tz_name` | string | **Context for local time.** IANA timezone name that makes local unambiguous. | "America/Los_Angeles" |
| `tz_source` | string | **Provenance.** Either "assumed" (Strategy A) or "actual" (Strategy B). Documents reliability. | "assumed" or "actual" |

**Why three timestamps?**
- **UTC:** Universal reference for pipeline operations (joins, deduplication)
- **Local:** Human-readable time for analysis (circadian patterns, hour-of-day)
- **Timezone name:** Makes local time unambiguous (especially during DST)
- **Source:** Documents which strategy was used (for data quality assessment)

---

## 4. DST Handling

Both strategies handle Daylight Saving Time transitions correctly:

### Spring Forward (March)
**Problem:** 2:00 AM → 3:00 AM (2:30 AM doesn't exist)

**Solution:** `nonexistent='shift_forward'`
```python
# 2025-03-09 02:30:00 → shifted to 03:30:00
```

### Fall Back (November)
**Problem:** 2:00 AM → 1:00 AM (1:30 AM happens twice)

**Solution:** `ambiguous='infer'`
```python
# Uses context from surrounding timestamps to pick correct occurrence
# For isolated timestamps, defaults to standard time (second occurrence)
```

---

## 5. Parquet Storage

**Why naive timestamps in Parquet?**
- PyArrow has limitations with timezone-aware timestamps in partitioned datasets
- Storing naive + separate tz_name string avoids serialization issues
- Reconstruction is trivial: `pd.to_datetime(df['timestamp_local']).dt.tz_localize(df['tz_name'])`

**Schema:**
```python
pa.field("timestamp_utc", pa.timestamp("us", tz="UTC"), nullable=False),
pa.field("timestamp_local", pa.timestamp("us"), nullable=False),  # Naive
pa.field("tz_name", pa.string(), nullable=True),
pa.field("tz_source", pa.string(), nullable=True),
```

---

## 6. Query Patterns

### UTC-based Queries (Pipeline Operations)

```python
# Time-series joins
df = df_workouts.merge(df_minute_facts, on='timestamp_utc')

# Date range filtering
df = df[
    (df['timestamp_utc'] >= '2025-01-01') &
    (df['timestamp_utc'] < '2025-02-01')
]

# Deduplication
df = df.drop_duplicates(subset=['timestamp_utc', 'source'])
```

### Local Time Queries (Circadian Analysis)

```python
# Hour-of-day patterns
df['hour_local'] = pd.to_datetime(df['timestamp_local']).dt.hour
hourly_avg = df.groupby('hour_local')['metric'].mean()

# Bedtime analysis (after 10 PM)
df['time_local'] = pd.to_datetime(df['timestamp_local']).dt.time
late_night = df[df['time_local'] >= datetime.time(22, 0)]

# Day-of-week patterns
df['dow_local'] = pd.to_datetime(df['timestamp_local']).dt.day_name()
weekly = df.groupby('dow_local')['metric'].mean()
```

---

## 7. Configuration (config.yaml)

```yaml
timezone:
  # Your home timezone for Strategy A ingestion
  default: "America/Los_Angeles"
  
  # Optional: Historical timezone changes (if you moved)
  changes:
    - before: "2025-06-01"
      timezone: "America/Los_Angeles"
      notes: "Seattle era"
    - after: "2025-06-01"
      timezone: "America/Chicago"
      notes: "Moved to Austin"
  
  # Optional: Known travel periods (for filtering in analysis)
  travel_periods:
    - start: "2025-03-15"
      end: "2025-03-22"
      timezone: "Europe/London"
      notes: "London vacation"

# Strategy assignment (for reference only)
strategy_a_sources:
  - HAE_CSV
  - HAE_JSON  # Daily aggregates
  - JEFIT

strategy_b_sources:
  - HAE_JSON  # Workouts only
  - Concept2
```

---

## 8. Travel Day Handling

### Problem
**Strategy A sources** (HAE CSV, JEFIT) will have **incorrect local times** on travel days.

### Solution Options

**Option 1: Accept Inconsistency (Recommended)**
- Travel days are ~5% of data
- Most analyses are home-based anyway
- Document travel periods in config.yaml for filtering

**Option 2: Manual Correction**
```python
# After ingestion, update specific date ranges with correct timezone
travel_mask = (
    (df['date'] >= '2025-03-15') &
    (df['date'] <= '2025-03-22')
)
df.loc[travel_mask, 'tz_name'] = 'Europe/London'

# Recompute local and UTC times
df.loc[travel_mask, 'timestamp_local'] = ...
df.loc[travel_mask, 'timestamp_utc'] = ...
```

**Option 3: Travel Log Integration (Future)**
```python
# Load travel log
travel_log = pd.read_csv('travel_periods.csv')

# Join on date and apply correct timezone
df = df.merge(travel_log, on='date', how='left')
df['tz_name'] = df['travel_timezone'].fillna(df['tz_name'])
```

---

## 9. Validation

### Timezone Consistency Checks

```python
# Check for missing timezone metadata
assert df['tz_name'].notna().all(), "Missing tz_name values"
assert df['tz_source'].isin(['assumed', 'actual']).all(), "Invalid tz_source"

# Verify UTC/local alignment
df_check = df.copy()
df_check['timestamp_local_tz'] = pd.to_datetime(
    df_check['timestamp_local']
).dt.tz_localize(df_check['tz_name'])
df_check['timestamp_utc_derived'] = df_check['timestamp_local_tz'].dt.tz_convert('UTC')

# Allow small differences due to rounding
time_diff = (df_check['timestamp_utc'] - df_check['timestamp_utc_derived']).abs()
assert (time_diff < pd.Timedelta(seconds=1)).all(), "UTC/local mismatch detected"
```

### DST Transition Checks

```python
# Count records per day (should be ~1440 for most days)
daily_counts = df.groupby(df['timestamp_local'].dt.date).size()

# Spring forward: ~1380 minutes (23 hours)
spring_forward_days = daily_counts[daily_counts < 1400]

# Fall back: ~1500 minutes (25 hours)
fall_back_days = daily_counts[daily_counts > 1460]

# Verify these align with actual DST dates
```

---

## 10. Decision Record

### Rationale

**Why hybrid strategy?**
- HAE exports lose per-event timezone (corrupted on travel days)
- Workouts/Concept2 have rich timezone data - use it
- JEFIT exports lack timezone information entirely
- Different sources require different handling

**Why not parse HAE timezone?**
- Export-time timezone ≠ event-time timezone
- Leads to random corruption on travel days
- Consistent wrong data > randomly corrupted data

**Why store three timestamps?**
- UTC: Pipeline operations (joins, dedup, sorting)
- Local: Circadian analysis (hour-of-day, bedtime)
- Timezone: Makes local unambiguous + documents quality

**Why assume home timezone?**
- 95% of data is at home (empirically observed)
- Travel day errors are acceptable trade-off
- Enables clean circadian analysis without noise
- Can be corrected later with manual travel log

**Why JEFIT uses Strategy A:**
- JEFIT CSV exports contain only naive timestamps
- No per-workout timezone information available
- Must assume user's home timezone for consistency
- Same trade-off as HAE CSV: correct at home, wrong when traveling

---

## 11. Implementation Checklist

When adding a new data source, determine:

- [ ] Does source provide per-event timezone? (Yes → Strategy B, No → Strategy A)
- [ ] If Strategy A: Which home timezone to assume?
- [ ] If Strategy B: Where is timezone stored in source data?
- [ ] Are timestamps already in UTC or local time?
- [ ] How to handle DST transitions?
- [ ] Which tables will use these timestamps?
- [ ] Update config.yaml with strategy assignment
- [ ] Add validation checks for this source
- [ ] Document any known limitations

---

## 12. Future Enhancements

- **Travel log integration:** Automatically correct travel day timezones
- **Timezone history tracking:** Handle users who move between timezones
- **Multi-timezone support:** For users who travel frequently
- **Automatic DST detection:** Validate DST transitions against timezone database
- **Query helpers:** Functions for common timezone operations

---

## References

- **IANA Timezone Database:** https://www.iana.org/time-zones
- **Python zoneinfo:** https://docs.python.org/3/library/zoneinfo.html
- **pandas timezone handling:** https://pandas.pydata.org/docs/user_guide/timeseries.html
- **PyArrow timestamp limitations:** https://arrow.apache.org/docs/python/timestamps.html

