# Data Sources

> **NOTE: This document may be stale. Always defer to `schema.py` and ingest code as the source of truth.**



**Version:** 2.3  
**Last Updated:** 2025-11-10

## Overview

This document covers ingestion specifics for each data source: authentication, data format, update frequency, and key processing steps.

---

## Apple Health Auto Export (HAE)

### Source Details
- **Format:** CSV files from Health Auto Export iOS app
- **Location:** Google Drive automated sync
- **Frequency:** Daily exports
- **Granularity:** Minute-level for most metrics
- **Timezone:** None (lossy) → Strategy A

### Tables Created
- `hae_heart_rate_minute` - Continuous HR tracking
- `hae_steps_minute` - Step counts
- `hae_exercise_minutes` - Exercise time
- `hae_active_energy_minute` - Active calories
- `hae_resting_energy_minute` - BMR calories
- `hae_distance_walking_running` - Movement distance
- `hae_flights_climbed` - Stair climbing
- `hae_vo2max` - Cardio fitness estimates
- `hae_hrv_sdnn` - Heart rate variability
- `hae_body_mass` - Weight logs
- `hae_body_fat_percentage` - BF% logs
- `hae_lean_body_mass` - LBM logs

### Ingestion Process
```bash
make ingest-hae
```

**Steps:**
1. Download new CSVs from Google Drive
2. Parse with pandas
3. Assume America/Los_Angeles timezone → convert to UTC
4. Deduplicate by (timestamp_utc, value, device_id)
5. Write to `silver/hae/{table}/{year}/{month}.parquet`

### Known Issues
- Travel days will have incorrect timestamps (consistently wrong)
- Duplicate minute readings from multiple devices - kept first occurrence
- CSV format changes occasionally with iOS updates

### Data Quality
- HR range: 30-220 bpm
- Steps: >= 0
- Timestamps: No future dates, no dates before 2010

---

## Concept2 (Rowing/Skiing/Biking)

### Source Details
- **Format:** JSON from Concept2 Logbook API
- **Authentication:** OAuth 2.0 (web flow)
- **Frequency:** Manual pulls after workouts
- **Granularity:** Stroke-by-stroke for rowing/skiing
- **Timezone:** Full offsets → Strategy B

### Tables Created
- `concept2_workouts` - Workout summaries
- `concept2_splits` - Split data (500m or timed intervals)
- `concept2_strokes` - Individual stroke data (for rowing/skiing)

### Ingestion Process
```bash
make ingest-concept2
```

**Steps:**
1. Authenticate via OAuth (browser flow if needed)
2. Fetch workout list: `GET /api/users/{user_id}/results`
3. For each workout with splits/strokes, fetch details
4. Parse metadata, splits, strokes into separate tables
5. Preserve both UTC and local timestamps
6. Write to `silver/concept2/{table}/{year}/{month}.parquet`

### Authentication Setup
```python
# First time only
python scripts/concept2_auth.py
# Opens browser, saves token to config.yml
```

Tokens expire after 6 months - refresh with same script.

### Data Quality
- Workout IDs are unique from API
- Split/stroke numbers are sequential within workout
- Monthly partitioning due to large stroke data volume (20k+ records per rowing workout)

### Parsing Notes
- BikeErg: Uses `cadence_rpm` instead of `stroke_rate`
- SkiErg/RowErg: Use `stroke_rate`
- Watts calculated from pace using C2 formula

---

## JEFIT (Resistance Training)

### Source Details
- **Format:** CSV export from JEFIT app
- **Frequency:** Manual exports (weekly/monthly)
- **Granularity:** Set-by-set logs
- **Timezone:** None (lossy) → Strategy A

### Tables Created
- `jefit_workouts` - Workout session summaries
- `jefit_sets` - Individual sets (exercise, reps, weight)

### Ingestion Process
```bash
make ingest-jefit
```

**Steps:**
1. Load JEFIT CSV export
2. Generate workout_id from (date, workout_name, exercises)
3. Generate set_id from (workout_id, exercise, set_number)
4. Assume America/Los_Angeles timezone
5. Calculate total volume: sum(reps × weight)
6. Write to `silver/jefit/{table}/{year}/{month}.parquet`

### Exercise Taxonomy
Maintain `exercises_taxonomy` for classification:
- `exercise_name` → standardized name
- `primary_muscle_group` (chest, back, legs, etc.)
- `movement_type` (compound, isolation)
- `equipment_type` (barbell, dumbbell, machine, bodyweight)

Used for filtering and volume analysis by muscle group.

### Data Quality
- Deduplicate by workout_id (hash-based)
- Weight: 0-500 kg (sanity check)
- Reps: 1-50 (sanity check)

---

## Oura Ring

### Source Details
- **Format:** JSON from Oura API v2 (`sleep`, `daily_sleep`)
- **Authentication:** OAuth2 client ID/secret + refresh token (`Data/oura_tokens.json`)
- **Frequency:** Daily sync via `make fetch-oura`
- **Granularity:** Daily per `day`. (No intraday HR yet.)
- **Timezone:** Oura-provided local dates

### Table Created
- `oura_summary` — merged daily measurements + scores:
  - Sleep durations: total, deep, light, REM, awake
  - Sleep score + contributor map
  - Readiness score + contributors + temperature deviation
  - Resting HR (lowest_heart_rate) and HRV (average_hrv)
  - Activity fields present but currently NULL until endpoint added

### Endpoints Used
- `/v2/usercollection/sleep` — full durations, HR, HRV, readiness block
- `/v2/usercollection/daily_sleep` — sleep score + contributors

### Ingestion
- Raw JSON saved under `Data/Raw/Oura/sleep/oura_{endpoint}_{day}.json`
- `make ingest-oura` merges and writes `oura_summary` parquet

---

## Laboratory Results

### Source Details
- **Format:** Manual entry from Quest/LabCorp PDF reports
- **Frequency:** Variable (weekly during protocols, monthly baseline)
- **Granularity:** Individual biomarker results
- **Timezone:** Date-only (no time component)

### Tables Created
- `labs_results` - Individual biomarker measurements
- `biomarker_mappings` - Canonical names and reference ranges

### Ingestion Process
```bash
make ingest-labs
```

**Steps:**
1. Download lab PDF from Quest/LabCorp portal
2. Extract text (manual or automated)
3. Structure into JSON: `{test_date, biomarker, value, unit, range}`
4. Match biomarker name to canonical mapping
5. Write to `silver/labs/{table}/{year}.parquet`

### Biomarker Standardization
**Problem:** Different labs use different names
- Quest: "Testosterone, Total"
- LabCorp: "Total Testosterone"

**Solution:** Canonical mapping
```
canonical_name: testosterone_total
aliases: [
  "Testosterone, Total",
  "Total Testosterone", 
  "Testosterone Total"
]
```

On ingestion, match `aliases` → store as `canonical_name`.

### Reference Ranges
Store both:
- `reference_range_low/high` - Lab-provided normal ranges
- `optimal_range_low/high` - Longevity-focused targets

Calculate:
- `in_reference_range` (boolean)
- `in_optimal_range` (boolean)

Flag results outside optimal even if "normal".

### Common Biomarkers
- **Lipids:** Total cholesterol, LDL, HDL, triglycerides, ApoB
- **Hormones:** Testosterone, estradiol, SHBG, prolactin
- **Metabolic:** Glucose, HbA1c, insulin, uric acid
- **Minerals:** Iron panel (ferritin, TIBC, saturation), magnesium, zinc
- **Inflammatory:** hsCRP, homocysteine
- **Liver:** ALT, AST, GGT, ALP
- **Kidney:** Creatinine, BUN, eGFR
- **Blood:** CBC (hemoglobin, hematocrit, RBC, WBC, platelets)

---

## Supplement & Medication Protocols

### Source Details
- **Format:** Manual logging (CSV or JSON)
- **Frequency:** Daily or as-changed
- **Granularity:** Individual doses with timing
- **Timezone:** Date-level → Strategy A

### Tables Created
- `protocols_doses` - Individual dose logs
- `compounds_catalog` - Supplement/medication reference
- `protocols_phases` - Protocol periods with objectives

### Ingestion Process
```bash
make ingest-protocols
```

**Steps:**
1. Load protocol CSV/JSON
2. Match compound names to `compounds_catalog`
3. Calculate daily totals if multiple doses
4. Link to active protocol phases
5. Write to `silver/protocols/{table}/{year}/{month}.parquet`

### Compound Catalog
Each compound includes:
- `compound_name` - Standardized name
- `category` (supplement, medication, hormone, etc.)
- `mechanism_of_action` - How it works
- `expected_half_life_hours` - Duration in system
- `optimal_timing` (morning, evening, with_meals, fasting)
- `interactions` - Compounds to separate timing

### Protocol Phases
Track specific interventions:
```
phase: "Iron Repletion Protocol"
start_date: 2024-10-15
compounds: [
  {name: "iron_bisglycinate", dose_mg: 200, frequency: "alternate_days"},
  {name: "vitamin_c", dose_mg: 500, frequency: "daily", timing: "with_iron"}
]
success_metrics: [
  "ferritin > 100 ng/mL",
  "iron_saturation 25-35%"
]
```

### Interaction Checking
Flag potential issues:
- Iron blocks zinc, magnesium absorption → separate by 4+ hours
- Calcium blocks iron absorption → separate
- Vitamin D + magnesium synergistic → can take together

### Data Quality
- Deduplicate by (date, compound_id, time_of_day)
- Sum multiple doses of same compound
- Validate dose ranges (warn if outside typical therapeutic range)

---

## Adding New Sources

To add a new data source, follow this checklist:

1. **Define Bronze Format**
   - Where does data come from? (API, CSV, manual)
   - How is authentication handled?
   - What's the update frequency?

2. **Design Silver Schema**
   - What tables are needed?
   - What are the primary/composite keys?
   - Partitioning strategy (monthly vs yearly)?
   - Timezone strategy (A or B)?

3. **Implement MPM Ingestion**
   - Script to Move source → bronze
   - Parser to Process bronze → silver
   - Aggregation to Move silver → gold

4. **Add to Gold Integration**
   - Join new source into `integrated_daily`
   - Create source-specific summary views

5. **Document**
   - Add section to this file
   - Update Schema.md with new tables
   - Add decision log if complex

---

**See Also:**
- [Architecture.md](Architecture.md) - System design overview
- [Schema.md](Schema.md) - Complete table schemas
- [TimestampHandling.md](TimestampHandling.md) - Timezone strategies
