# Decision: Timezone Handling Strategy

**Date:** 2024-09-20  
**Status:** Implemented  
**Impact:** Critical (affects timestamp integrity across all sources)

## Context

Health data comes from multiple sources with varying levels of timezone information:
- **Rich:** Concept2 API, Oura API provide full timezone offsets
- **Lossy:** Apple Health CSV, JEFIT CSV have no timezone metadata
- **Hybrid:** User primarily in Los Angeles but occasionally travels

Need consistent UTC timestamps for cross-source joins while preserving local context where available.

## Problem

Inconsistent timezone handling causes:
1. **Join errors:** Data from same moment appears at different times
2. **Correlation issues:** Training affects *next-day* recovery, but timestamps off by hours
3. **Travel ambiguity:** Same workout time shows different UTC depending on location
4. **Data quality:** Hard to detect anomalies when timestamps are inconsistent

## Options Considered

### Option 1: Always UTC (Naive)
Convert everything to UTC assuming system timezone.

**Pros:**
- Simple implementation
- Consistent storage format

**Cons:**
- **Loses local context** (workout at "2pm" becomes meaningless)
- Travel days get random timezone conversions
- No way to reconstruct actual local time

### Option 2: Always Preserve Original
Store timestamps as-is from source.

**Pros:**
- No information loss

**Cons:**
- **Cannot join across sources** (some UTC, some local, some unknown)
- Analysis becomes nightmare of timezone conversion
- No consistency guarantees

### Option 3: Hybrid Strategy (CHOSEN)

**Strategy A (Assumed Timezone):**
- For sources with NO timezone: Assume America/Los_Angeles → UTC
- Accept that travel days are wrong but consistently wrong

**Strategy B (Rich Timezone):**
- For sources WITH timezone: Store both UTC and local
- Preserves accurate local context

**Pros:**
- **Enables joins** (all have UTC)
- **Preserves context** where available
- **Simple assumptions** for lossy sources
- Errors are predictable and documentable

**Cons:**
- Travel days using Strategy A will be ~3 hours off (acceptable)
- Dual storage for Strategy B adds slight complexity

## Decision

Implement **hybrid approach** with two strategies:

### Strategy A: Assumed Timezone (Lossy Sources)
**Applied to:** HAE, JEFIT, Protocols

```python
import pytz

la_tz = pytz.timezone('America/Los_Angeles')
naive_timestamp = pd.to_datetime('2024-11-10 14:23:45')
local_timestamp = la_tz.localize(naive_timestamp)
utc_timestamp = local_timestamp.astimezone(pytz.UTC)
# Store: utc_timestamp only
```

### Strategy B: Rich Timezone (Complete Sources)
**Applied to:** Concept2, Oura

```python
from dateutil import parser

timestamp_with_tz = parser.parse('2024-11-10T14:23:45-08:00')
utc_timestamp = timestamp_with_tz.astimezone(pytz.UTC)
local_timestamp = timestamp_with_tz  # Keep original

# Store: BOTH utc_timestamp AND local_timestamp
```

## Rationale

1. **Cross-source joins require UTC:**
   ```sql
   SELECT h.timestamp_utc, c.date_utc, o.readiness_score
   FROM hae_heart_rate h
   JOIN concept2_workouts c ON h.timestamp_utc = c.date_utc
   JOIN oura_readiness o ON h.timestamp_utc::date = o.date
   ```

2. **Lossy sources can't be perfect anyway:**
   - Apple Health CSV has no timezone → must assume something
   - Better to assume consistently (LA) than try to guess travel

3. **Rich sources provide full context:**
   - Concept2: `"date": "2024-11-10T14:23:45-08:00"` → store both UTC and local
   - Enables travel analysis: "How did NYC training affect sleep?"

4. **Local context matters for display:**
   - User wants to see "workout at 2pm" not "workout at 22:00 UTC"
   - Strategy B preserves this for capable sources

## Implementation

### Schema Pattern
```sql
-- Strategy A tables (HAE, JEFIT, Protocols)
CREATE TABLE hae_heart_rate_minute (
    timestamp_utc TIMESTAMP,  -- Assumed LA → UTC
    ...
);

-- Strategy B tables (Concept2, Oura)
CREATE TABLE concept2_workouts (
    date_utc TIMESTAMP,    -- Converted to UTC
    date_local TIMESTAMP,  -- Original timezone preserved
    ...
);
```

### Source Classification
| Source | Strategy | Rationale |
|--------|----------|-----------|
| HAE | A | CSV has no timezone |
| Concept2 | B | API provides full offset |
| JEFIT | A | CSV has no timezone |
| Oura | B | API provides full offset |
| Labs | N/A | Date-only, no time component |
| Protocols | A | Manual logging in single timezone |

## Trade-offs Accepted

### 1. Travel Days (Strategy A)
**Problem:** User in NYC logs workout at 2pm EST, stored as 2pm PST → 5pm UTC (wrong, should be 7pm UTC)

**Impact:**
- Timestamps off by ~3 hours
- Affects ~5% of data (travel days)

**Mitigation:**
- **Accepted:** Consistently wrong is better than randomly wrong
- Can manually annotate travel periods if needed for specific analysis
- Focus on patterns over precise timestamps

**Why acceptable:**
- Correlation analysis (training → recovery) uses daily granularity
- 3-hour error within same day doesn't break patterns
- Travel typically involves lighter training anyway

### 2. Dual Storage (Strategy B)
**Problem:** Storing both UTC and local adds ~30% column overhead

**Impact:**
- ~10MB extra per year of Concept2 data

**Mitigation:**
- Parquet compression reduces impact
- Storage is cheap, data loss is expensive

**Why acceptable:**
- Can always drop local timestamp later if needed
- Cannot reconstruct local from UTC alone

### 3. Complexity (Two Strategies)
**Problem:** Developers must remember which sources use which strategy

**Impact:**
- Potential confusion in query writing
- Need documentation

**Mitigation:**
- Clear naming: `timestamp_utc` vs `date_utc` + `date_local`
- Document in [TimestampHandling.md](../TimestampHandling.md)
- Schema enforces correct usage

## Results

**Before (Inconsistent Approach):**
- Some data stored as LA time, some as UTC, some unknown
- Cross-source joins produced garbage
- Couldn't tell if workout at "22:00" was 10pm local or 2pm local converted to UTC

**After (Hybrid Strategy):**
- All sources have UTC for joins ✓
- Rich sources preserve local context ✓
- Predictable behavior even on travel days ✓
- Query patterns are consistent ✓

### Example Success: Workout HR Analysis
```sql
-- Find HAE heart rate during Concept2 workout
-- WORKS because both have timestamp_utc
WITH workout AS (
    SELECT workout_id, date_utc, duration_seconds
    FROM concept2_workouts WHERE workout_id = 'abc123'
)
SELECT h.timestamp_utc, h.heart_rate_bpm, s.watts
FROM hae_heart_rate_minute h
JOIN workout w ON h.timestamp_utc BETWEEN w.date_utc AND w.date_utc + (w.duration_seconds || ' seconds')::interval
LEFT JOIN concept2_strokes s ON ...
```

## Future Enhancements

### Option 1: Travel Log
```sql
CREATE TABLE travel_periods (
    start_date DATE,
    end_date DATE,
    timezone STRING
);

-- Apply during ingestion for Strategy A sources
```

### Option 2: Timezone Inference
Use Strategy B sources (Concept2/Oura) as proxy:
- If Concept2 workout logged in EST, assume HAE data that day also EST
- Risk: Red-eye flights, multi-timezone days

### Option 3: Accept Limitation
Current approach: Simple, predictable, good enough for 95% of use cases.

## Lessons Learned

1. **Perfect is the enemy of done:**
   - Could spend months building location tracking system
   - Better to accept known limitation and move forward

2. **Consistency > accuracy for travel edge cases:**
   - Better to be off by 3 hours predictably than randomly corrupted

3. **Preserve rich data when available:**
   - Future-proof: Can always downsample
   - Cannot reconstruct lost timezone info

4. **Document assumptions explicitly:**
   - "Travel days will be wrong" in docs prevents confusion
   - Users know what to expect

## Testing Strategy

```python
def test_strategy_a_conversion():
    """LA time → UTC conversion"""
    naive = pd.to_datetime('2024-11-10 14:00:00')
    la_tz = pytz.timezone('America/Los_Angeles')
    local = la_tz.localize(naive)
    utc = local.astimezone(pytz.UTC)
    assert utc.hour == 22  # 14:00 PST = 22:00 UTC

def test_strategy_b_preservation():
    """Preserve both UTC and local"""
    ts = parser.parse('2024-11-10T14:00:00-05:00')  # EST
    utc = ts.astimezone(pytz.UTC)
    assert utc.hour == 19  # 14:00 EST = 19:00 UTC
    assert str(ts).endswith('-05:00')  # Local preserved

def test_cross_source_join():
    """HAE (Strategy A) + Concept2 (Strategy B) join works"""
    # Both have timestamp_utc, join succeeds
    ...
```

---

**Related:**
- [TimestampHandling.md](../TimestampHandling.md) - Implementation details
- [Architecture.md](../Architecture.md) - System design
- [DataSources.md](../DataSources.md) - Source-specific strategies
