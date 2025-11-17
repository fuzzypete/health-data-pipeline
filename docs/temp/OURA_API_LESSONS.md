# Oura API v2 Endpoint Confusion - Lessons Learned

## The Problem

Oura's API v2 has confusing endpoint naming that led us down the wrong path initially.

## Endpoint Breakdown

### ❌ `daily_sleep` - SCORES ONLY
**What it returns:**
```json
{
  "score": 77,
  "contributors": {
    "deep_sleep": 97,      // Score 0-100, not duration!
    "efficiency": 86,
    "latency": 54,
    "rem_sleep": 96,
    "restfulness": 80,
    "timing": 94,
    "total_sleep": 65      // Score 0-100, not duration!
  },
  "day": "2025-11-14"
}
```
**Why it's useless for us:** No actual measurements, just proprietary scores.

### ❌ `sleep_time` - RECOMMENDATIONS ONLY
**What it returns:**
```json
{
  "optimal_bedtime": null,
  "recommendation": "earlier_bedtime",
  "status": "only_recommended_found",
  "day": "2025-11-14"
}
```
**Why it's useless for us:** Just bedtime suggestions, no measurements.

### ❌ `daily_readiness` - SCORES ONLY (Mostly)
**What it returns:**
```json
{
  "score": 77,
  "contributors": {
    "resting_heart_rate": 73,  // Score 0-100, not BPM!
    "hrv_balance": 85,
    "body_temperature": 100,
    ...
  },
  "temperature_deviation": 0.04,        // This IS useful!
  "temperature_trend_deviation": 0.03,
  "day": "2025-11-14"
}
```
**Why it's mostly useless:** Resting HR is a score, not actual BPM. Only temp deviation is useful, but we get it elsewhere.

### ✅ `sleep` - ALL THE MEASUREMENTS!
**What it returns:**
```json
{
  "day": "2025-11-14",
  
  // Actual durations (seconds)
  "total_sleep_duration": 28800,      // 8 hours in seconds
  "time_in_bed": 30000,
  "deep_sleep_duration": 5400,        // 1.5 hours
  "light_sleep_duration": 14400,      // 4 hours
  "rem_sleep_duration": 5400,         // 1.5 hours
  "awake_time": 900,                  // 15 minutes
  
  // Sleep quality metrics
  "efficiency": 85,                    // Percentage
  "latency": 300,                      // Seconds to fall asleep
  "restless_periods": 12,
  
  // Heart rate (ACTUAL BPM!)
  "average_heart_rate": 52.5,         // BPM during sleep
  "lowest_heart_rate": 48,            // BPM - true resting baseline!
  
  // HRV (milliseconds)
  "average_hrv": 45.2,                // Overnight average
  
  // Breathing
  "average_breath": 14.5,             // Breaths per minute
  
  // Timestamps
  "bedtime_start": "2025-11-13T22:30:00-08:00",
  "bedtime_end": "2025-11-14T06:45:00-08:00",
  
  // Embedded readiness data (bonus!)
  "readiness": {
    "score": 77,
    "temperature_deviation": 0.04,     // Also available here
    "temperature_trend_deviation": 0.03,
    "contributors": { ... }
  }
}
```
**Why this is the ONE:** Every actual measurement we need, plus embedded readiness data.

## The Naming Convention

**Pattern discovered:**
- `daily_*` endpoints = Scores and aggregated metrics (0-100 scales)
- Base endpoints (e.g., `sleep`, `heartrate`) = Raw measurements

## What We Need from Oura

For your recovery tracking and iron depletion analysis:

1. **Sleep HRV** → `sleep.average_hrv` (overnight average in ms)
2. **Resting HR** → `sleep.lowest_heart_rate` (true baseline in BPM)
3. **Sleep duration** → `sleep.total_sleep_duration` (seconds)
4. **Sleep stages** → `sleep.deep_sleep_duration`, `rem_sleep_duration`, etc.
5. **Temperature** → `sleep.readiness.temperature_deviation` (celsius)
6. **Readiness** → `sleep.readiness.score` (0-100)

**ALL from the single `sleep` endpoint.**

## Implementation Strategy

**Single endpoint fetch:**
```python
DATA_ENDPOINTS = {
    "sleep": RAW_OURA_SLEEP_DIR,  # One endpoint, all measurements
}
```

**Simple processing:**
1. Load `oura_sleep_*.json` files
2. Map fields directly (no merging needed)
3. Extract nested readiness object
4. Write to oura_summary table

## Why This Matters

**Old approach (wrong):**
- Fetch 3-4 endpoints
- Complex merging logic
- Still missing the actual measurements we needed
- Got scores instead of durations/BPM/ms

**New approach (correct):**
- Fetch 1 endpoint
- Simple mapping
- All actual measurements present
- Clean, maintainable code

## Key Takeaway

When the Oura API docs say "sleep data," they mean the `sleep` endpoint, not `daily_sleep` or `sleep_time`. The word "daily" is a flag that means "scores and aggregates," not "comprehensive daily data."

## For Future Reference

If you ever need to add more Oura data:

**Activity measurements** → Try `activity` endpoint (not `daily_activity`)  
**Daytime HR** → `heartrate` endpoint (5-minute intervals)  
**Workout details** → `workout` endpoint  

Always prefer the base endpoint name over the `daily_*` version if you want measurements instead of scores.
