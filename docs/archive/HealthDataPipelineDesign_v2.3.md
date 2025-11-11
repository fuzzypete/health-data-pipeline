# Health Data Pipeline Design Document v2.3

**Last Updated:** 2025-11-10  
**Status:** Active Development

## Overview

This document details the ingestion algorithms, processing logic, and data transformation workflows for all sources in the Health Data Pipeline (HDP). Each source section describes the Move-Process-Move pattern implementation, deduplication logic, timezone handling, and partitioning strategy.

---

## 1. Apple Health Auto Export (HAE)

### 1.1 Source Characteristics
- **Format:** CSV files exported from Health Auto Export iOS app
- **Update Frequency:** Daily automated exports to Google Drive
- **Timezone Information:** Lossy - no timezone metadata in CSV
- **Data Granularity:** Minute-level for most metrics, second-level for some
- **Historical Depth:** 10+ years of data

### 1.2 Ingestion Algorithm

**Phase 1: Move (Google Drive → Bronze)**
```
FOR EACH new HAE CSV file in Drive:
    1. Download to bronze/hae/{date}/ directory
    2. Record in metadata.ingestion_log
    3. Mark source file as processed (don't re-download)
```

**Phase 2: Process (Bronze → Silver)**
```
FOR EACH HAE CSV in bronze:
    1. Read CSV with pandas
    2. Apply timezone assumption (Strategy A):
       - Assume all timestamps are America/Los_Angeles
       - Convert to UTC for storage
       - Accept that travel days will be wrong but consistently wrong
    
    3. Parse into HAE-specific staging tables:
       - hae_heart_rate_minute
       - hae_steps_minute
       - hae_exercise_minutes
       - hae_active_energy_minute
       - hae_resting_energy_minute
       - hae_distance_walking_running
       - hae_flights_climbed
       - hae_vo2max
       - hae_hrv_sdnn
       - hae_body_mass
       - hae_body_fat_percentage
       - hae_lean_body_mass
       
    4. For each table:
       - Deduplicate by (timestamp_utc, metric_value)
       - Keep earliest ingestion_id for duplicates
       
    5. Write to silver/hae/{table}/{year}/{month}.parquet
```

**Phase 3: Move (Silver → Gold)**
```
Currently manual - future automation planned
Will aggregate HAE minute-level data into daily summaries
```

### 1.3 Deduplication Logic
- **Key:** `(timestamp_utc, metric_value, source_device_id)`
- **Rationale:** Same timestamp + value + device = duplicate reading
- **Implementation:** Drop duplicates keeping first occurrence (earliest ingestion)

### 1.4 Schema Mapping
```
HAE CSV → Silver Tables
├── timestamp → timestamp_utc (with timezone assumption)
├── value → metric_value
├── device → source_device_id
└── units → unit_of_measure
```

---

## 2. Concept2 API

### 2.1 Source Characteristics
- **Format:** JSON from Concept2 Logbook API
- **Update Frequency:** Manual pulls (workout completion)
- **Timezone Information:** Rich - full timezone offsets in timestamps
- **Data Granularity:** Stroke-by-stroke for rowing/skiing
- **Historical Depth:** 5+ years of workouts

### 2.2 Ingestion Algorithm

**Phase 1: Move (API → Bronze)**
```
authentication:
    1. Check for valid OAuth token in config
    2. If expired, refresh using refresh_token
    3. If no token, initiate OAuth flow via browser
    
data_pull:
    FOR EACH workout type (RowErg, SkiErg, BikeErg):
        1. GET /api/users/{user_id}/results?type={type}
        2. Save full JSON response to bronze/concept2/workouts/{date}.json
        3. Record in metadata.ingestion_log
        
        FOR EACH workout_id in results:
            IF workout has splits or strokes:
                4. GET /api/users/{user_id}/results/{workout_id}
                5. Save detailed JSON to bronze/concept2/details/{workout_id}.json
```

**Phase 2: Process (Bronze → Silver)**
```
FOR EACH workout JSON in bronze:
    1. Parse workout metadata:
       - workout_id (primary key)
       - workout_type (RowErg, SkiErg, BikeErg)
       - date_utc (convert timezone-aware timestamp)
       - date_local (preserve original timezone)
       - duration_seconds
       - distance_meters
       - average_pace_500m
       - average_watts
       - average_heart_rate
       - average_stroke_rate (for rowing/skiing)
       - average_cadence_rpm (for biking)
       
    2. Parse split data if present:
       - workout_id (foreign key)
       - split_number (1-indexed)
       - distance_meters
       - duration_seconds
       - pace_500m
       - watts
       - heart_rate
       - stroke_rate or cadence_rpm
       
    3. Parse stroke data if present:
       - workout_id (foreign key)
       - stroke_number (1-indexed)
       - timestamp_offset_seconds
       - distance_meters_cumulative
       - heart_rate
       - stroke_rate
       - watts
       
    4. Deduplicate each table by primary key:
       - workouts: workout_id
       - splits: (workout_id, split_number)
       - strokes: (workout_id, stroke_number)
       
    5. Write to silver/concept2/{table}/{year}/{month}.parquet
       - Monthly partitioning due to large stroke data volume
```

**Phase 3: Move (Silver → Gold)**
```
Aggregate to daily summaries:
    FOR EACH day:
        1. Group workouts by date_local
        2. Calculate totals:
           - total_distance_meters
           - total_duration_seconds
           - total_calories (estimated from watts)
           - average_heart_rate (time-weighted)
           - workout_count
           
        3. Write to gold/concept2_daily_summary/{year}.parquet
```

### 2.3 Deduplication Logic
- **Workouts:** Unique `workout_id` from API
- **Splits:** Composite key `(workout_id, split_number)`
- **Strokes:** Composite key `(workout_id, stroke_number)`
- **Rationale:** API provides guaranteed unique IDs; stroke_number is sequential within workout

### 2.4 Timezone Handling (Strategy B)
```
Concept2 timestamps include timezone offsets:
    "2024-11-10T14:23:45-08:00"
    
Storage approach:
    1. Parse with full timezone awareness
    2. Store BOTH:
       - date_utc: converted to UTC for joins
       - date_local: original timezone preserved for display
    3. Allows accurate cross-source correlation via UTC
    4. Preserves local context for analysis
```

---

## 3. JEFIT Resistance Training

### 3.1 Source Characteristics
- **Format:** Exported CSV from JEFIT app
- **Update Frequency:** Manual exports (weekly/monthly)
- **Timezone Information:** Lossy - no timezone in export
- **Data Granularity:** Set-by-set exercise logs
- **Historical Depth:** 10+ years of training logs

### 3.2 Ingestion Algorithm

**Phase 1: Move (Export → Bronze)**
```
FOR EACH JEFIT CSV export:
    1. Download/copy to bronze/jefit/{date}/ directory
    2. Record in metadata.ingestion_log
    3. Note export date range for deduplication
```

**Phase 2: Process (Bronze → Silver)**
```
FOR EACH JEFIT CSV in bronze:
    1. Read CSV with pandas
    2. Apply timezone assumption (Strategy A):
       - Assume America/Los_Angeles
       - Convert to UTC for storage
       
    3. Parse into two tables:
    
       jefit_workouts:
       - workout_id (generated hash)
       - date_utc
       - date_local
       - workout_name (e.g., "Upper Body A")
       - duration_minutes (estimated from set timestamps)
       - total_volume_kg (sum of sets × reps × weight)
       
       jefit_sets:
       - set_id (generated hash)
       - workout_id (foreign key)
       - exercise_name
       - set_number
       - reps_completed
       - weight_kg
       - rpe (Rate of Perceived Exertion, if logged)
       - notes
       
    4. Deduplicate by workout_id:
       - Hash based on (date, workout_name, exercises)
       - If duplicate workout exists, keep newest ingestion
       
    5. Write to silver/jefit/{table}/{year}/{month}.parquet
```

**Phase 3: Move (Silver → Gold)**
```
Aggregate to training summaries:
    FOR EACH week:
        1. Group by week_start_date
        2. Calculate:
           - total_volume_kg
           - workout_count
           - exercise_frequency (map of exercise → count)
           - muscle_group_split (classify exercises by target)
           
        3. Write to gold/jefit_weekly_summary/{year}.parquet
```

### 3.3 Deduplication Logic
- **Workout ID:** Hash of `(date, workout_name, sorted_exercise_list)`
- **Set ID:** Hash of `(workout_id, exercise_name, set_number)`
- **Rationale:** JEFIT export has no native IDs, must generate stable identifiers

### 3.4 Exercise Classification
```
Maintain exercise taxonomy:
    exercises_taxonomy:
    - exercise_name
    - primary_muscle_group
    - movement_type (compound, isolation)
    - equipment_type
    
Used for:
    - Filtering by muscle group
    - Analyzing volume distribution
    - Detecting program adherence
```

---

## 4. Oura Ring

### 4.1 Source Characteristics
- **Format:** JSON from Oura API v2
- **Update Frequency:** Daily automated sync (nightly data)
- **Timezone Information:** Rich - timestamps with offsets
- **Data Granularity:** Daily summaries + intraday details
- **Historical Depth:** 2-3 years typical

### 4.2 Ingestion Algorithm

**Phase 1: Move (API → Bronze)**
```
authentication:
    1. Check for valid Personal Access Token
    2. Refresh if needed (6-month expiry)
    
data_pull:
    FOR EACH endpoint:
        /v2/usercollection/daily_readiness
        /v2/usercollection/daily_sleep
        /v2/usercollection/daily_activity
        /v2/usercollection/sleep_time (detailed)
        /v2/usercollection/heartrate (5-min intervals)
        
        1. GET with date range parameters
        2. Save response to bronze/oura/{endpoint}/{date}.json
        3. Record in metadata.ingestion_log
```

**Phase 2: Process (Bronze → Silver)**
```
FOR EACH Oura JSON response:
    
    oura_readiness_daily:
    - date (summary date)
    - score (0-100)
    - temperature_deviation_celsius
    - temperature_trend_deviation
    - recovery_index
    - hrv_balance
    - previous_night_score
    - sleep_balance_score
    - activity_balance_score
    
    oura_sleep_daily:
    - date (sleep night date)
    - score (0-100)
    - total_sleep_duration_seconds
    - time_in_bed_seconds
    - efficiency_percentage
    - onset_latency_seconds
    - deep_sleep_duration_seconds
    - light_sleep_duration_seconds
    - rem_sleep_duration_seconds
    - awake_duration_seconds
    - restlessness_percentage
    - average_heart_rate_bpm
    - lowest_heart_rate_bpm
    - average_hrv_ms
    - temperature_delta_celsius
    
    oura_activity_daily:
    - date
    - score (0-100)
    - active_calories_kcal
    - total_calories_kcal
    - steps
    - equivalent_walking_distance_meters
    - high_activity_minutes
    - medium_activity_minutes
    - low_activity_minutes
    - sedentary_minutes
    - average_met
    - inactivity_alerts
    - target_calories_kcal
    - target_meters
    
    oura_heart_rate_5min:
    - timestamp_utc
    - heart_rate_bpm
    - source (sleep, awake, workout, etc.)
    
    Deduplicate by date or timestamp
    Write to silver/oura/{table}/{year}/{month}.parquet
```

**Phase 3: Move (Silver → Gold)**
```
Oura data already in daily summary format
Minimal transformation needed for gold layer
Potential aggregations:
    - Weekly readiness trends
    - Monthly sleep quality averages
    - Correlation with training load
```

### 4.3 Deduplication Logic
- **Daily summaries:** Unique by `date`
- **5-min HR:** Unique by `timestamp_utc`
- **Rationale:** Oura provides one summary per day; HR readings have precise timestamps

### 4.4 Temperature Tracking
```
Oura provides multiple temperature metrics:
    - temperature_deviation_celsius: deviation from baseline
    - temperature_trend_deviation: trend vs recent baseline
    - temperature_delta_celsius: sleep-specific deviation
    
Pipeline stores all three for correlation analysis with:
    - Illness/infection
    - Menstrual cycle (if applicable)
    - Training load
    - Supplement effects
```

---

## 5. Laboratory Results

### 5.1 Source Characteristics
- **Format:** Manual entry from Quest/LabCorp PDF reports
- **Update Frequency:** Variable (weekly during protocols, monthly baseline)
- **Timezone Information:** Date-only (no intraday timing)
- **Data Granularity:** Biomarker-level results
- **Historical Depth:** 10+ years of lab panels

### 5.2 Ingestion Algorithm

**Phase 1: Move (PDF → Bronze)**
```
manual_process:
    1. Download lab report PDF from Quest/LabCorp portal
    2. Save to bronze/labs/pdfs/{date}_{lab_company}.pdf
    3. Extract text using PyPDF2 or manual transcription
    4. Save structured data to bronze/labs/raw/{date}.json
```

**Phase 2: Process (Bronze → Silver)**
```
FOR EACH lab result JSON:
    
    labs_results:
    - result_id (generated UUID)
    - test_date (date only, no time component)
    - lab_company (Quest, LabCorp, etc.)
    - biomarker_name (standardized nomenclature)
    - result_value (numeric)
    - result_unit (mg/dL, ng/mL, etc.)
    - reference_range_low
    - reference_range_high
    - flag (normal, high, low, critical)
    - test_method (if specified)
    - fasting_status (boolean)
    
    biomarker_mappings:
    - canonical_name (standardized)
    - aliases (lab-specific names)
    - category (lipid, hormone, mineral, etc.)
    - optimal_range_low
    - optimal_range_high
    - clinical_significance
    
    Deduplicate by (test_date, biomarker_name)
    Keep most recent ingestion if duplicate
    
    Write to silver/labs/{table}/{year}.parquet
```

**Phase 3: Move (Silver → Gold)**
```
Aggregate to longitudinal series:
    FOR EACH biomarker:
        1. Create time series of (test_date, result_value)
        2. Calculate:
           - delta_from_previous
           - days_since_previous_test
           - percentile_in_reference_range
           - trend (improving, stable, declining)
           
        3. Write to gold/labs_longitudinal/{biomarker_category}.parquet
```

### 5.3 Biomarker Standardization
```
Problem: Different labs use different naming conventions
    Quest: "Testosterone, Total"
    LabCorp: "Total Testosterone"
    
Solution: Maintain canonical mapping
    canonical_name: "testosterone_total"
    aliases: ["Testosterone, Total", "Total Testosterone", "Testosterone Total"]
    
Implementation:
    1. On ingestion, match against aliases
    2. Convert to canonical_name for storage
    3. Preserve original_name for audit trail
```

### 5.4 Reference Range Handling
```
Challenge: Reference ranges vary by:
    - Lab company
    - Test methodology
    - Patient demographics (age, sex)
    
Approach:
    1. Store lab-provided reference ranges
    2. Maintain separate optimal_ranges based on longevity literature
    3. Calculate both:
       - in_reference_range (boolean)
       - in_optimal_range (boolean)
    4. Flag results outside optimal even if "normal"
```

---

## 6. Supplement & Medication Protocols

### 6.1 Source Characteristics
- **Format:** Manual logging (structured entry or CSV)
- **Update Frequency:** Daily or as-changed
- **Timezone Information:** Date-level (morning/evening timing)
- **Data Granularity:** Dose-by-dose logs
- **Historical Depth:** 5+ years of supplement tracking

### 6.2 Ingestion Algorithm

**Phase 1: Move (Entry → Bronze)**
```
manual_entry:
    User logs via:
    - Structured form (future)
    - CSV upload
    - JSON API (future automation)
    
    Save to bronze/protocols/{date}.csv or .json
```

**Phase 2: Process (Bronze → Silver)**
```
FOR EACH protocol entry:
    
    protocols_doses:
    - dose_id (generated UUID)
    - compound_id (foreign key to compounds_catalog)
    - date (when dose taken)
    - time_of_day (morning, afternoon, evening, bedtime)
    - dose_amount_mg (or mcg, IU)
    - dose_unit
    - administration_route (oral, injection, topical)
    - taken_with_food (boolean)
    - notes
    
    compounds_catalog:
    - compound_id
    - compound_name (standardized)
    - category (supplement, medication, hormone, etc.)
    - common_aliases
    - mechanism_of_action
    - expected_half_life_hours
    - optimal_timing (morning, evening, with_meals, etc.)
    - interactions (list of compounds to avoid combining)
    
    protocols_phases:
    - phase_id
    - start_date
    - end_date (nullable if ongoing)
    - phase_name (e.g., "Iron Repletion Protocol")
    - primary_objective
    - success_metrics (list of biomarkers to track)
    - associated_compounds (list of compound_ids)
    
    Deduplicate by (date, compound_id, time_of_day)
    If same compound logged multiple times same day, sum doses
    
    Write to silver/protocols/{table}/{year}/{month}.parquet
```

**Phase 3: Move (Silver → Gold)**
```
Aggregate to protocol analysis:
    FOR EACH protocol phase:
        1. Calculate:
           - adherence_percentage (doses taken / doses prescribed)
           - average_daily_dose
           - duration_days
           
        2. Join with labs_results:
           - biomarker_changes_during_phase
           - pre_phase_baseline
           - post_phase_outcome
           
        3. Generate protocol effectiveness summary
        
        4. Write to gold/protocol_outcomes/{phase_id}.parquet
```

### 6.3 Timing Optimization Logic
```
Goal: Track actual timing vs optimal timing
    
optimal_timing_rules:
    IF compound.mechanism == "iron_supplementation":
        optimal = alternate_days (hepcidin cycling)
        timing = morning, fasting
        
    IF compound.mechanism == "vitamin_d":
        optimal = morning (circadian rhythm support)
        
    IF compound.mechanism == "magnesium":
        optimal = evening (sleep support)
        
recorded_vs_optimal:
    FOR EACH dose:
        1. Check against optimal_timing_rules
        2. Calculate timing_compliance_score
        3. Flag suboptimal timing for review
```

### 6.4 Interaction Checking
```
Problem: Some compounds interfere with absorption or effects
    Example: Iron blocks zinc, magnesium, copper absorption
    
Solution: Maintain interaction matrix
    interactions_matrix:
    - compound_a_id
    - compound_b_id
    - interaction_type (antagonistic, synergistic, neutral)
    - time_separation_required_hours
    - severity (minor, moderate, major)
    
On ingestion:
    FOR EACH dose on a given day:
        1. Check all other doses same day
        2. Flag if known antagonistic compounds within separation window
        3. Generate warning in metadata
```

---

## 7. Cross-Source Integration Patterns

### 7.1 Correlation Analysis
```
Objective: Answer questions like:
    "What supplements was I taking when ferritin dropped?"
    "How did Concept2 volume affect sleep quality?"
    "Did JEFIT leg days impact HRV the next day?"
    
Approach:
    1. All timestamps normalized to UTC in silver tables
    2. Gold layer creates joined views:
    
    gold/integrated_daily:
    - date_utc (join key)
    - concept2_total_meters
    - jefit_total_volume_kg
    - oura_readiness_score
    - oura_hrv_ms
    - hae_average_resting_hr
    - active_protocols (list)
    
    3. Windowing functions for lagged correlations:
       - training_load_7day_rolling_avg
       - readiness_next_day
       - hrv_change_from_baseline
```

### 7.2 Temporal Alignment
```
Challenge: Different sources have different time granularity
    - Labs: date only
    - Oura: daily summaries
    - Concept2: specific workout timestamps
    - HAE: minute-level data
    
Solution: Multiple aggregation levels
    gold/minute_level: HAE + Concept2 strokes (sparse)
    gold/hourly_level: HAE + Concept2 + JEFIT (denser)
    gold/daily_level: All sources (complete)
    
Query optimization:
    - Default to daily level for correlation analysis
    - Drill down to minute level for workout-specific analysis
    - Labs join at date level, broadcast to all minutes/hours that day
```

### 7.3 Protocol Effectiveness Queries
```
Example: "Did Iron + Vitamin C protocol improve ferritin?"

Query pattern:
    1. Identify protocol phase:
       SELECT * FROM protocols_phases
       WHERE phase_name LIKE '%Iron%'
       
    2. Get doses during phase:
       SELECT * FROM protocols_doses
       WHERE date BETWEEN phase.start_date AND phase.end_date
         AND compound_id IN (iron, vitamin_c)
       
    3. Get lab results during phase:
       SELECT * FROM labs_results
       WHERE test_date BETWEEN phase.start_date AND phase.end_date
         AND biomarker_name IN ('ferritin', 'iron_saturation', 'hemoglobin')
       
    4. Calculate pre/post difference:
       SELECT 
           biomarker_name,
           FIRST_VALUE(result_value) as baseline,
           LAST_VALUE(result_value) as outcome,
           (LAST_VALUE - FIRST_VALUE) as delta,
           duration_days
```

---

## 8. Metadata & Observability

### 8.1 Ingestion Tracking
```
metadata.ingestion_log:
- ingestion_id (UUID)
- source_name (hae, concept2, jefit, oura, labs, protocols)
- table_name
- ingestion_timestamp_utc
- records_processed
- records_deduplicated
- records_inserted
- bronze_file_path
- silver_file_path
- processing_duration_seconds
- status (success, partial, failed)
- error_message (if applicable)
```

### 8.2 Data Quality Checks
```
quality_checks:
    timestamp_validation:
        - No future timestamps
        - No timestamps before birth year
        - Timezone conversions preserve date boundaries
        
    value_validation:
        - Heart rate: 30-220 bpm
        - Weight: 50-150 kg (user-specific)
        - Distance: >= 0 meters
        - Duration: > 0 seconds
        
    completeness_checks:
        - Required fields not null
        - Foreign keys resolve
        - Partition files not empty
        
    consistency_checks:
        - Total distance = sum of split distances
        - Workout duration >= sum of set durations
        - Daily summary metrics align with minute-level sums
```

### 8.3 Pipeline Monitoring
```
metrics_to_track:
    - ingestion_lag_hours (time from data creation to ingestion)
    - processing_duration_per_1k_records
    - storage_growth_mb_per_day
    - query_performance_p95_latency
    - deduplication_hit_rate
    - data_freshness_by_source
    
alerts:
    IF ingestion_lag_hours > 48: notify
    IF processing_errors > 5: notify
    IF storage_growth_anomaly: notify
```

---

## 9. Future Enhancements

### 9.1 Planned Sources
- **Continuous Glucose Monitor (CGM):** 5-minute glucose readings
- **Blood Pressure:** Home monitoring data
- **Body Composition:** DEXA scan results
- **Lactate Testing:** Finger-prick measurements during workouts
- **Sleep Tracking:** Detailed sleep stage data from additional devices

### 9.2 Automation Improvements
- **Scheduled Ingestion:** Cron jobs for Oura, Concept2 daily pulls
- **Error Recovery:** Automatic retry with exponential backoff
- **Data Validation:** Pre-ingestion schema validation
- **Notification System:** Email/Slack alerts for pipeline failures

### 9.3 Analysis Features
- **Anomaly Detection:** Flag unusual biomarker changes
- **Predictive Modeling:** Forecast readiness based on training load
- **Protocol Optimization:** Recommend supplement timing adjustments
- **Visualization:** Automated dashboard generation

---

## Appendix A: Timestamp Strategy Decision Matrix

| Source | Strategy | Rationale |
|--------|----------|-----------|
| HAE CSV | Strategy A (Assume LA) | No timezone info; prioritize consistency |
| Concept2 API | Strategy B (Rich TZ) | Full timezone offsets available |
| JEFIT CSV | Strategy A (Assume LA) | No timezone info; user primarily in LA |
| Oura API | Strategy B (Rich TZ) | Timezone-aware timestamps |
| Labs | N/A (Date only) | No time component in lab reports |
| Protocols | Strategy A (Assume LA) | User logs in single timezone |

**Strategy A:** Assume America/Los_Angeles timezone, convert to UTC, accept travel day inaccuracy  
**Strategy B:** Preserve rich timezone info, store both UTC and local timestamps

---

## Appendix B: Deduplication Algorithms

### B.1 Exact Match Deduplication
```python
def deduplicate_exact(df, key_columns):
    """Remove exact duplicates based on composite key"""
    return df.drop_duplicates(subset=key_columns, keep='first')
```

### B.2 Fuzzy Timestamp Deduplication
```python
def deduplicate_fuzzy_time(df, time_col, threshold_seconds=60):
    """Remove duplicates within time threshold (for HAE edge cases)"""
    df_sorted = df.sort_values(time_col)
    df_sorted['time_diff'] = df_sorted[time_col].diff().dt.total_seconds()
    df_sorted['is_duplicate'] = df_sorted['time_diff'] < threshold_seconds
    return df_sorted[~df_sorted['is_duplicate']]
```

### B.3 Hash-Based ID Generation
```python
def generate_stable_id(*components):
    """Generate deterministic UUID from components"""
    import hashlib
    concatenated = '|'.join(str(c) for c in components)
    hash_digest = hashlib.sha256(concatenated.encode()).hexdigest()
    return hash_digest[:32]  # First 32 chars for readability
```

---

**Document Version:** 2.3  
**Maintained By:** Peter Kahaian  
**Review Cycle:** Monthly or after major source additions
