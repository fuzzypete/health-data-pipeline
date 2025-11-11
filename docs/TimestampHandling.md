# Timestamp Handling

**Version:** 2.3  
**Last Updated:** 2025-11-10

## Overview

HDP handles timestamps from multiple sources with varying levels of timezone information. This document explains the two strategies used, when to apply each, and how to handle edge cases.

---

## The Problem

Health data comes from sources with different timestamp fidelity:

**High Fidelity (Rich):**
- Concept2 API: Full timezone offsets (e.g., `2024-11-10T14:23:45-08:00`)
- Oura API: Timezone-aware timestamps

**Low Fidelity (Lossy):**
- Apple Health CSV: No timezone metadata (just `2024-11-10 14:23:45`)
- JEFIT CSV: No timezone metadata
- Labs: Date only (no time component)

**Challenge:** Need consistent UTC timestamps for cross-source joins while preserving local context where available.

---

## Strategy A: Assumed Timezone

### When to Use
Sources with **no timezone information** in the data.

### Sources Using Strategy A
- Apple Health Auto Export (HAE)
- JEFIT resistance training
- Supplement/Medication protocols

### Implementation
```python
# Assume America/Los_Angeles timezone
import pytz
la_tz = pytz.timezone('America/Los_Angeles')

# Parse naive timestamp
naive_timestamp = pd.to_datetime('2024-11-10 14:23:45')

# Localize to LA timezone
local_timestamp = la_tz.localize(naive_timestamp)

# Convert to UTC for storage
utc_timestamp = local_timestamp.astimezone(pytz.UTC)
```

### Trade-offs

**Pros:**
- Simple, consistent approach
- Works for 95%+ of data (user primarily in LA)
- Predictable behavior

**Cons:**
- Travel days will be wrong
- Daylight saving time handled automatically but may not reflect actual recording time

**Decision:** Accept that travel days are **consistently wrong** rather than building complex location tracking. This is better than random corruption from guessing timezones.

### Travel Day Example
```
Actual:    User in NYC at 2024-11-10 14:00 EST → UTC 19:00
Stored:    Assumed LA at 2024-11-10 14:00 PST → UTC 22:00
Error:     3 hours off

Result: Workouts appear later in day than actual, but:
- Pattern is predictable
- Can manually annotate travel periods if needed
- Minute-level accuracy preserved for correlation analysis
```

---

## Strategy B: Rich Timezone

### When to Use
Sources with **full timezone information** in the data.

### Sources Using Strategy B
- Concept2 API
- Oura API

### Implementation
```python
# Parse timezone-aware timestamp
from dateutil import parser

timestamp_with_tz = parser.parse('2024-11-10T14:23:45-08:00')
# Automatically in correct timezone with offset

# Convert to UTC for joins
utc_timestamp = timestamp_with_tz.astimezone(pytz.UTC)

# Also preserve original for display
local_timestamp = timestamp_with_tz  # Keep as-is
```

### Storage Pattern
Store **both** timestamps:

```
concept2_workouts:
    date_utc:    2024-11-10 22:23:45+00  (for joins)
    date_local:  2024-11-10 14:23:45-08  (for display)
```

### Benefits
- Accurate cross-timezone analysis
- Preserves user's actual local time context
- Enables travel correlation studies
- No data loss from timezone conversion

### Use Cases
```sql
-- Join across sources using UTC
SELECT 
    c.date_utc,
    c.distance_meters,
    o.readiness_score
FROM concept2_workouts c
LEFT JOIN oura_readiness o 
    ON c.date_utc::date = o.date

-- Display in user's local timezone
SELECT 
    date_local,  -- Shows "2024-11-10 14:23:45-08"
    distance_meters
FROM concept2_workouts
WHERE date_local::date = '2024-11-10'
```

---

## Strategy Decision Matrix

| Source | Strategy | Has TZ Info? | Primary User Location | Rationale |
|--------|----------|--------------|---------------------|-----------|
| HAE | A (Assumed LA) | ❌ No | Los Angeles | Lossy source, prioritize consistency |
| Concept2 | B (Rich) | ✅ Yes | Variable | Full timezone available, preserve it |
| JEFIT | A (Assumed LA) | ❌ No | Los Angeles | Lossy source, user primarily in LA |
| Oura | B (Rich) | ✅ Yes | Variable | Full timezone available, preserve it |
| Labs | N/A | N/A (date only) | Los Angeles | No time component in lab reports |
| Protocols | A (Assumed LA) | ❌ No | Los Angeles | Manual logging, single timezone |

---

## Cross-Source Joins

### Joining Strategy A + Strategy B
Both strategies convert to UTC, so joins work seamlessly:

```sql
-- HAE (Strategy A) + Concept2 (Strategy B)
SELECT 
    h.timestamp_utc,
    h.heart_rate_bpm,
    c.average_watts
FROM hae_heart_rate_minute h
LEFT JOIN concept2_strokes c 
    ON h.timestamp_utc = c.workout_id::date + c.timestamp_offset_seconds
WHERE h.timestamp_utc BETWEEN '2024-11-10 00:00' AND '2024-11-10 23:59'
```

Both `h.timestamp_utc` and `c.workout_id::date` are in UTC, so join is accurate.

### Daily Aggregation Pattern
```sql
-- Gold layer: Aggregate all sources to daily summaries
CREATE TABLE integrated_daily AS
SELECT 
    date_trunc('day', timestamp_utc) as date_utc,
    -- HAE metrics (Strategy A)
    AVG(hae_hr.heart_rate_bpm) as avg_hr,
    SUM(hae_steps.steps) as total_steps,
    -- Concept2 metrics (Strategy B)
    SUM(c2.distance_meters) as c2_total_meters,
    -- Oura metrics (Strategy B)
    o.readiness_score
FROM ...
GROUP BY date_trunc('day', timestamp_utc)
```

---

## Edge Cases & Solutions

### Case 1: Daylight Saving Time Transitions

**Problem:** 
- Spring forward: 2024-03-10 02:00 → 03:00 (1 hour lost)
- Fall back: 2024-11-03 02:00 → 01:00 (1 hour repeated)

**Strategy A Solution:**
```python
# pytz handles DST automatically
la_tz.localize(naive_timestamp, is_dst=None)
# Raises exception if ambiguous (fall back hour)
# → Disambiguate manually or use is_dst=True/False
```

**Strategy B Solution:**
Timezone offset in data handles DST:
```
Before spring: 2024-03-10 01:59:00-08:00
After spring:  2024-03-10 03:00:00-07:00
(No ambiguity)
```

### Case 2: Missing Timezone Data Mid-Stream

**Problem:** Source that usually has timezone suddenly doesn't.

**Solution:**
```python
def parse_with_fallback(timestamp_str):
    try:
        # Try parsing with timezone
        return parser.parse(timestamp_str)
    except ValueError:
        # Fall back to Strategy A
        naive = pd.to_datetime(timestamp_str)
        return la_tz.localize(naive)
```

### Case 3: Future Timestamps

**Problem:** Device clock set incorrectly, creates future timestamps.

**Solution:**
```python
# Quality check: Reject timestamps > now + 1 day
now = datetime.now(pytz.UTC)
if timestamp_utc > now + timedelta(days=1):
    raise ValueError(f"Future timestamp: {timestamp_utc}")
```

### Case 4: Ancient Timestamps

**Problem:** Device glitch creates timestamps in 1970 or before birth year.

**Solution:**
```python
# Quality check: Reject timestamps before reasonable date
MIN_VALID_DATE = datetime(2010, 1, 1, tzinfo=pytz.UTC)
if timestamp_utc < MIN_VALID_DATE:
    raise ValueError(f"Invalid old timestamp: {timestamp_utc}")
```

---

## Query Patterns

### Pattern 1: Local Time Display
```sql
-- Show workouts in user's local time
SELECT 
    date_local AT TIME ZONE 'America/Los_Angeles' as display_time,
    distance_meters
FROM concept2_workouts
WHERE date_local::date = '2024-11-10'
```

### Pattern 2: Cross-Source Minute Matching
```sql
-- Find HAE heart rate during Concept2 workout
WITH workout AS (
    SELECT 
        workout_id,
        date_utc as start_utc,
        date_utc + (duration_seconds || ' seconds')::interval as end_utc
    FROM concept2_workouts
    WHERE workout_id = 'abc123'
)
SELECT 
    h.timestamp_utc,
    h.heart_rate_bpm
FROM hae_heart_rate_minute h
JOIN workout w ON h.timestamp_utc BETWEEN w.start_utc AND w.end_utc
ORDER BY h.timestamp_utc
```

### Pattern 3: Daily Summary Joins
```sql
-- Join daily summaries across sources
SELECT 
    d.date_utc,
    c.total_distance_meters,
    o.readiness_score,
    h.avg_resting_hr
FROM date_series d
LEFT JOIN concept2_daily c ON d.date_utc = c.date_local::date
LEFT JOIN oura_readiness o ON d.date_utc = o.date
LEFT JOIN hae_daily_hr h ON d.date_utc = h.date_utc::date
WHERE d.date_utc >= '2024-01-01'
```

---

## Best Practices

### 1. Always Store UTC
- Silver layer timestamps always in UTC
- Enables consistent joins across sources
- No ambiguity in storage

### 2. Preserve Original When Available
- Strategy B: Store both `date_utc` and `date_local`
- Enables accurate display and timezone analysis
- Minimal storage cost

### 3. Document Assumptions
- Clearly mark Strategy A data sources
- Flag travel periods if critical for analysis
- Note DST transitions in metadata

### 4. Validate on Ingestion
```python
def validate_timestamp(ts):
    now = datetime.now(pytz.UTC)
    min_date = datetime(2010, 1, 1, tzinfo=pytz.UTC)
    
    if ts < min_date:
        raise ValueError("Timestamp too old")
    if ts > now + timedelta(days=1):
        raise ValueError("Future timestamp")
    return ts
```

### 5. Use Timezone-Aware Libraries
```python
# Good: timezone-aware
import pytz
from dateutil import parser

# Avoid: timezone-naive
# datetime.now()  # Missing timezone!
# Use: datetime.now(pytz.UTC)
```

---

## Travel Handling (Future)

Currently, travel days are accepted as wrong. Future enhancements:

### Option 1: Manual Travel Log
```
travel_periods:
    start_date, end_date, timezone
    
# Apply during ingestion
if date in travel_periods:
    tz = travel_periods[date].timezone
else:
    tz = 'America/Los_Angeles'
```

### Option 2: Location Inference
```
# Use Concept2/Oura timezone as proxy
# If Concept2 workout in EST, assume all HAE data that day in EST
# Risk: Multi-timezone days (red-eye flights)
```

### Option 3: Accept Limitation
Current approach: Keep it simple, annotate travel manually if needed for specific analysis.

---

## Testing Strategy

### Unit Tests
```python
def test_strategy_a_conversion():
    # Given naive timestamp
    naive = pd.to_datetime('2024-11-10 14:23:45')
    
    # When localized to LA
    local = la_tz.localize(naive)
    
    # Then converts to UTC correctly
    utc = local.astimezone(pytz.UTC)
    assert utc.hour == 22  # 14:00 PST = 22:00 UTC
    
def test_strategy_b_preservation():
    # Given timezone-aware timestamp
    ts = parser.parse('2024-11-10T14:23:45-05:00')
    
    # When stored
    utc = ts.astimezone(pytz.UTC)
    local = ts
    
    # Then both preserved
    assert utc.hour == 19  # 14:00 EST = 19:00 UTC
    assert local.hour == 14
    assert str(local).endswith('-05:00')
```

### Integration Tests
```python
def test_cross_source_join():
    # Given HAE data (Strategy A) and Concept2 data (Strategy B)
    # When joined by UTC timestamp
    # Then matches correctly despite different strategies
    ...
```

---

**See Also:**
- [Architecture.md](Architecture.md) - System design
- [DataSources.md](DataSources.md) - Source-specific details
- [decisions/TimezoneStrategy.md](decisions/TimezoneStrategy.md) - Why we chose this approach
