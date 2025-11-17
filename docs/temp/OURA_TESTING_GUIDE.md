# Oura Integration - Final Testing Guide

## What We're Fetching

Two complementary endpoints that together give the complete picture:

### ✅ `sleep` - All Measurements
- Sleep durations (total, REM, deep, light, awake) in seconds
- Heart rate (average, lowest = resting baseline) in BPM
- HRV (overnight average) in milliseconds  
- Temperature deviation (embedded in readiness object)
- Readiness score (embedded)
- Timestamps, efficiency, sleep stages

### ✅ `daily_sleep` - Sleep Score
- Sleep score (0-100) - Oura's validated sleep quality algorithm
- Contributor scores showing what drove the overall score:
  - deep_sleep, rem_sleep, efficiency, latency, timing, total_sleep, restfulness

**Result:** Both raw measurements AND Oura's proprietary scoring algorithms.

## Files Updated

1. **src/pipeline/ingest/oura_api.py**
   - Fetches both `sleep` and `daily_sleep` endpoints
   - Saves to `oura_sleep_YYYY-MM-DD.json` and `oura_daily_sleep_YYYY-MM-DD.json`

2. **src/pipeline/ingest/oura_json.py**
   - Loads both file types
   - Merges on `day` field
   - Maps measurements from `sleep` endpoint
   - Maps scores from `daily_sleep` endpoint

## Testing Steps

### 1. Clean Previous Test Data
```bash
# Remove any incorrect test files
rm Data/Raw/Oura/sleep/oura_sleep_time_*.json 2>/dev/null
rm Data/Raw/Oura/readiness/*.json 2>/dev/null

# Or backup everything and start fresh
mkdir -p Data/Raw/Oura/backup
mv Data/Raw/Oura/sleep/*.json Data/Raw/Oura/backup/ 2>/dev/null
```

### 2. Replace Files
```bash
# From your repo root
cp oura_api.py src/pipeline/ingest/oura_api.py
cp oura_json.py src/pipeline/ingest/oura_json.py
```

### 3. Test API Fetch
```bash
# Fetch last 3 days
poetry run python -c "
from src.pipeline.ingest.oura_api import fetch_oura_data
from datetime import date, timedelta
fetch_oura_data(start_date=date.today() - timedelta(days=3))
"
```

**Expected output:**
```
Fetching Oura data from 2025-11-13 to 2025-11-16...
Fetching sleep...
  ✅ Saved 4 items for sleep
Fetching daily_sleep...
  ✅ Saved 4 items for daily_sleep
```

**Expected files:**
```bash
ls -1 Data/Raw/Oura/sleep/
# Should show:
oura_sleep_2025-11-13.json
oura_sleep_2025-11-14.json
oura_sleep_2025-11-15.json
oura_sleep_2025-11-16.json
oura_daily_sleep_2025-11-13.json
oura_daily_sleep_2025-11-14.json
oura_daily_sleep_2025-11-15.json
oura_daily_sleep_2025-11-16.json
```

### 4. Inspect Raw Data

**Check sleep measurements:**
```bash
cat Data/Raw/Oura/sleep/oura_sleep_2025-11-14.json | jq '{
  day, 
  total_sleep_duration, 
  average_hrv, 
  lowest_heart_rate,
  readiness_score: .readiness.score,
  temp_dev: .readiness.temperature_deviation
}'
```

**Expected:**
```json
{
  "day": "2025-11-14",
  "total_sleep_duration": 28800,        // ~8 hours in seconds
  "average_hrv": 45.2,                  // milliseconds
  "lowest_heart_rate": 48,              // BPM (resting baseline!)
  "readiness_score": 77,                // 0-100
  "temp_dev": 0.04                      // celsius
}
```

**Check sleep score:**
```bash
cat Data/Raw/Oura/sleep/oura_daily_sleep_2025-11-14.json | jq '{
  day,
  sleep_score: .score,
  contributors
}'
```

**Expected:**
```json
{
  "day": "2025-11-14",
  "sleep_score": 77,
  "contributors": {
    "deep_sleep": 97,
    "efficiency": 86,
    "latency": 54,
    "rem_sleep": 96,
    "restfulness": 80,
    "timing": 94,
    "total_sleep": 65
  }
}
```

### 5. Test Parquet Ingestion
```bash
poetry run python src/pipeline/ingest/oura_json.py
```

**Expected output:**
```
Starting Oura JSON ingestion (run_id=20251116T200000Z)
Loaded 4 sleep records and 4 daily_sleep records.
Merged into 4 daily records.
Writing 4 processed Oura records to oura_summary
Archived 8 files to Archive/Oura/sleep
✅ Oura JSON ingestion complete.
```

### 6. Query and Validate
```bash
poetry run duckdb Data/duck/health.duckdb
```

```sql
-- Check all the key fields
SELECT 
    day,
    sleep_score,                          -- From daily_sleep
    readiness_score,                      -- From sleep.readiness
    total_sleep_duration_s / 3600.0 as sleep_hours,  -- From sleep
    hrv_ms,                               -- From sleep (average_hrv)
    resting_heart_rate_bpm as resting_hr, -- From sleep (lowest_heart_rate)
    temperature_deviation_c as temp_dev   -- From sleep.readiness
FROM lake.oura_summary
WHERE day >= '2025-11-13'
ORDER BY day DESC;
```

**Validation checklist:**
- ✅ `sleep_score` is 0-100 (not NULL)
- ✅ `readiness_score` is 0-100 (not NULL)
- ✅ `sleep_hours` is 5-10 (realistic range)
- ✅ `hrv_ms` is 20-100 (realistic range, varies by person)
- ✅ `resting_hr` is 40-70 (actual BPM, not a 0-100 score!)
- ✅ `temp_dev` is -1.5 to +1.5 (celsius deviation)

**Check contributor scores:**
```sql
SELECT 
    day,
    sleep_score,
    sleep_contributors
FROM lake.oura_summary
WHERE day = '2025-11-14';
```

Should show a JSON/map object with contributor scores like:
```
{"deep_sleep": 97, "efficiency": 86, "latency": 54, ...}
```

### 7. Test Timeline Analysis
```bash
poetry run python analysis/scripts/create_comprehensive_timeline.py
```

Check the output:
```bash
tail -10 analysis/outputs/comprehensive_historical_timeline.csv | column -t -s,
```

**Verify:**
- `sleep_score` column is populated with 0-100 values
- `sleep_minutes` column has realistic values (360-600 minutes)
- `resting_hr` column has BPM values (40-70 range)
- `hrv` column has millisecond values (20-100 range)

## What You Get

### Raw Measurements (from `sleep` endpoint)
- Precise sleep duration in seconds
- True resting HR baseline (lowest during sleep)
- Overnight HRV average (gold standard)
- Sleep stage durations (REM, deep, light, awake)
- Temperature deviation
- Sleep efficiency percentage

### Validated Scores (from `daily_sleep` endpoint)  
- Overall sleep score (0-100)
- Contributor scores showing:
  - Which sleep stages were optimal
  - Sleep efficiency quality
  - Sleep timing appropriateness
  - Sleep latency (how fast you fell asleep)

### Recovery Metrics (from `sleep.readiness` object)
- Readiness score (0-100)
- Temperature deviation
- Readiness contributors

## Complete Data Set

You now have BOTH:
1. **Raw data** for quantitative analysis and correlation
2. **Validated scores** from Oura's algorithms for qualitative assessment

This gives you the best of both worlds - you can analyze actual HRV trends (e.g., "my HRV dropped 15ms") while also using Oura's holistic scoring ("my sleep score dropped from 85 to 70").

## Troubleshooting

### Issue: sleep_score is NULL but other data is present
**Cause:** `daily_sleep` endpoint didn't return data for that night  
**Solution:** Normal - some nights may not have a sleep score calculated yet. Measurements are still valid.

### Issue: resting_heart_rate_bpm looks like a score (70-100)
**Cause:** Wrong field being used  
**Debug:**
```bash
cat Data/Raw/Oura/sleep/oura_sleep_YYYY-MM-DD.json | jq '.lowest_heart_rate'
```
Should return a number like `48`, not `73`

### Issue: sleep_contributors shows as text, not structured
**Cause:** JSON serialization issue in DuckDB display  
**Solution:** This is display-only. The data is correctly stored as a map structure.

### Issue: Merge created duplicate rows
**Cause:** Multiple sleep records for same day (e.g., nap + main sleep)  
**Debug:**
```bash
cat Data/Raw/Oura/sleep/oura_sleep_*.json | jq -r '.day' | sort | uniq -d
```
**Solution:** Oura API may return multiple sleep periods per day. Current logic takes all records. You may want to filter by `sleep.type` if needed.

## Next Steps

### 1. Backfill Historical Data
```bash
# Fetch last 30 days (or as far back as Oura keeps)
poetry run python -c "
from src.pipeline.ingest.oura_api import fetch_oura_data
from datetime import date, timedelta
fetch_oura_data(start_date=date.today() - timedelta(days=30))
"
poetry run python src/pipeline/ingest/oura_json.py
```

### 2. Add to Daily Workflow
**Makefile:**
```makefile
.PHONY: fetch-oura
fetch-oura:
	poetry run python -c "from src.pipeline.ingest.oura_api import fetch_oura_data; fetch_oura_data()"

.PHONY: ingest-oura
ingest-oura:
	poetry run python src/pipeline/ingest/oura_json.py

.PHONY: update-oura
update-oura: fetch-oura ingest-oura
```

**Daily run:**
```bash
make update-oura
```

### 3. Correlation Analysis
With both measurements and scores, you can analyze:

**Which measurement drives sleep score?**
```sql
SELECT 
    CORR(total_sleep_duration_s, sleep_score) as duration_corr,
    CORR(hrv_ms, sleep_score) as hrv_corr
FROM lake.oura_summary
WHERE sleep_score IS NOT NULL;
```

**Does sleep score predict next-day readiness?**
```sql
SELECT 
    o1.sleep_score,
    o2.readiness_score as next_day_readiness
FROM lake.oura_summary o1
JOIN lake.oura_summary o2 ON o2.day = o1.day + INTERVAL '1 day'
WHERE o1.sleep_score IS NOT NULL;
```

**When measurements look good but score is low?**
```sql
-- Find nights where duration/HRV were good but sleep score was poor
SELECT 
    day,
    total_sleep_duration_s / 3600.0 as hours,
    hrv_ms,
    sleep_score,
    sleep_contributors
FROM lake.oura_summary
WHERE total_sleep_duration_s > 7 * 3600  -- >7 hours
  AND hrv_ms > 40                         -- Decent HRV
  AND sleep_score < 70;                   -- But poor score
```

This helps identify what Oura's algorithm sees that raw measurements don't show (e.g., restlessness, poor timing).

## Summary

You now have the complete Oura dataset:
- ✅ All actual measurements (HRV, RHR, durations, stages)
- ✅ Oura's validated sleep quality score
- ✅ Oura's readiness score  
- ✅ Contributor scores showing scoring drivers
- ✅ Temperature deviation for illness detection

Perfect for your recovery tracking and iron depletion correlation analysis!
