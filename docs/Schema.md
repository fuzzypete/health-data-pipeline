# Schema

> **NOTE:** This document may be stale. Always defer to `src/pipeline/common/schema.py` as the source of truth.

**Version:** 2.3  
**Last Updated:** 2025-11-10

## Overview

This document defines the normalized table schemas for all data sources in the silver layer. Tables are organized by source, with field definitions, data types, constraints, and partitioning strategies.

---

## Metadata Tables

### metadata.ingestion_log
Tracks all ingestion operations for observability.

| Field | Type | Description |
|-------|------|-------------|
| ingestion_id | UUID | Primary key |
| source_name | STRING | Source system (hae, concept2, jefit, oura, labs, protocols) |
| table_name | STRING | Target table name |
| ingestion_timestamp_utc | TIMESTAMP | When ingestion ran |
| records_processed | INT | Total records in source |
| records_deduplicated | INT | Duplicate records removed |
| records_inserted | INT | New records added |
| bronze_file_path | STRING | Source file location |
| silver_file_path | STRING | Output parquet location |
| processing_duration_seconds | FLOAT | Execution time |
| status | STRING | success \| partial \| failed |
| error_message | STRING | Error details if failed |

**Partitioning:** By `ingestion_timestamp_utc` year-month

---

## Apple Health Auto Export (HAE)

All HAE tables use **Strategy A** timezone handling (assumed America/Los_Angeles → UTC).

### Common Fields (All HAE Tables)
| Field | Type | Description |
|-------|------|-------------|
| timestamp_utc | TIMESTAMP | Measurement time (UTC) |
| source_device_id | STRING | Device identifier from Health app |
| unit_of_measure | STRING | Unit (bpm, steps, kcal, etc.) |
| ingestion_id | UUID | Foreign key to ingestion_log |

### hae_heart_rate_minute
Continuous heart rate monitoring.

| Field | Type | Description |
|-------|------|-------------|
| heart_rate_bpm | INT | Heart rate (30-220 range) |

**Deduplication Key:** (timestamp_utc, heart_rate_bpm, source_device_id)  
**Partitioning:** `year/month`

### hae_steps_minute
Step count per minute.

| Field | Type | Description |
|-------|------|-------------|
| steps | INT | Steps counted |

**Deduplication Key:** (timestamp_utc, steps, source_device_id)  
**Partitioning:** `year/month`

### hae_exercise_minutes
Exercise time tracking.

| Field | Type | Description |
|-------|------|-------------|
| exercise_minutes | FLOAT | Minutes of exercise |

**Deduplication Key:** (timestamp_utc, exercise_minutes, source_device_id)  
**Partitioning:** `year/month`

### hae_active_energy_minute
Active calories burned.

| Field | Type | Description |
|-------|------|-------------|
| active_energy_kcal | FLOAT | Active calories |

**Deduplication Key:** (timestamp_utc, active_energy_kcal, source_device_id)  
**Partitioning:** `year/month`

### hae_resting_energy_minute
Basal metabolic rate calories.

| Field | Type | Description |
|-------|------|-------------|
| resting_energy_kcal | FLOAT | BMR calories |

**Deduplication Key:** (timestamp_utc, resting_energy_kcal, source_device_id)  
**Partitioning:** `year/month`

### hae_distance_walking_running
Movement distance tracking.

| Field | Type | Description |
|-------|------|-------------|
| distance_meters | FLOAT | Distance covered |

**Deduplication Key:** (timestamp_utc, distance_meters, source_device_id)  
**Partitioning:** `year/month`

### hae_flights_climbed
Stair climbing activity.

| Field | Type | Description |
|-------|------|-------------|
| flights_climbed | INT | Number of flights |

**Deduplication Key:** (timestamp_utc, flights_climbed, source_device_id)  
**Partitioning:** `year/month`

### hae_vo2max
Cardiorespiratory fitness estimates.

| Field | Type | Description |
|-------|------|-------------|
| vo2max_ml_kg_min | FLOAT | VO2 max estimate |

**Deduplication Key:** (timestamp_utc, vo2max_ml_kg_min, source_device_id)  
**Partitioning:** `year/month`

### hae_hrv_sdnn
Heart rate variability (SDNN method).

| Field | Type | Description |
|-------|------|-------------|
| hrv_sdnn_ms | FLOAT | HRV in milliseconds |

**Deduplication Key:** (timestamp_utc, hrv_sdnn_ms, source_device_id)  
**Partitioning:** `year/month`

### hae_body_mass
Weight measurements.

| Field | Type | Description |
|-------|------|-------------|
| body_mass_kg | FLOAT | Weight in kilograms |

**Deduplication Key:** (timestamp_utc, body_mass_kg, source_device_id)  
**Partitioning:** `year/month`

### hae_body_fat_percentage
Body fat percentage logs.

| Field | Type | Description |
|-------|------|-------------|
| body_fat_percentage | FLOAT | BF% (0-100 range) |

**Deduplication Key:** (timestamp_utc, body_fat_percentage, source_device_id)  
**Partitioning:** `year/month`

### hae_lean_body_mass
Lean body mass measurements.

| Field | Type | Description |
|-------|------|-------------|
| lean_body_mass_kg | FLOAT | LBM in kilograms |

**Deduplication Key:** (timestamp_utc, lean_body_mass_kg, source_device_id)  
**Partitioning:** `year/month`

---

## Concept2

All Concept2 tables use **Strategy B** timezone handling (rich timezone preserved).

### Common Fields (All Concept2 Tables)
| Field | Type | Description |
|-------|------|-------------|
| workout_id | STRING | Unique workout identifier from API |
| date_utc | TIMESTAMP | Workout time in UTC |
| date_local | TIMESTAMP | Workout time in original timezone |
| workout_type | STRING | RowErg \| SkiErg \| BikeErg |
| ingestion_id | UUID | Foreign key to ingestion_log |

### concept2_workouts
Workout session summaries.

| Field | Type | Description |
|-------|------|-------------|
| duration_seconds | INT | Total workout duration |
| distance_meters | FLOAT | Total distance |
| average_pace_500m | STRING | Pace per 500m (mm:ss.s) |
| average_watts | FLOAT | Average power output |
| average_heart_rate | INT | Average HR (if monitor used) |
| average_stroke_rate | FLOAT | Strokes/min (rowing/skiing) |
| average_cadence_rpm | FLOAT | Cadence (biking) |
| total_calories | INT | Estimated calories burned |
| drag_factor | INT | Resistance setting |
| ranked | BOOLEAN | Workout ranked on Concept2 logbook |

**Primary Key:** workout_id  
**Partitioning:** `year/month`

### concept2_splits
Split data (500m or timed intervals).

| Field | Type | Description |
|-------|------|-------------|
| split_number | INT | Split sequence (1-indexed) |
| distance_meters | FLOAT | Split distance |
| duration_seconds | FLOAT | Split duration |
| pace_500m | STRING | Split pace (mm:ss.s) |
| watts | FLOAT | Power output |
| heart_rate | INT | Average HR for split |
| stroke_rate | FLOAT | Strokes/min (rowing/skiing) |
| cadence_rpm | FLOAT | Cadence (biking) |

**Composite Key:** (workout_id, split_number)  
**Partitioning:** `year/month`

### concept2_strokes
Individual stroke data (rowing/skiing only).

| Field | Type | Description |
|-------|------|-------------|
| stroke_number | INT | Stroke sequence (1-indexed) |
| timestamp_offset_seconds | FLOAT | Time since workout start |
| distance_meters_cumulative | FLOAT | Cumulative distance |
| heart_rate | INT | Instantaneous HR |
| stroke_rate | FLOAT | Strokes/min |
| watts | FLOAT | Power output |

**Composite Key:** (workout_id, stroke_number)  
**Partitioning:** `year/month` (monthly due to large volume)

---

## JEFIT

All JEFIT tables use **Strategy A** timezone handling.

### jefit_workouts
Workout session summaries.

| Field | Type | Description |
|-------|------|-------------|
| workout_id | STRING | Generated hash from (date, name, exercises) |
| date_utc | TIMESTAMP | Workout date in UTC |
| date_local | DATE | Workout date in local timezone |
| workout_name | STRING | Workout program name (e.g., "Upper A") |
| duration_minutes | INT | Estimated workout duration |
| total_volume_kg | FLOAT | Sum of (sets × reps × weight) |
| exercise_count | INT | Number of distinct exercises |
| set_count | INT | Total number of sets |
| ingestion_id | UUID | Foreign key to ingestion_log |

**Primary Key:** workout_id  
**Partitioning:** `year/month`

### jefit_sets
Individual exercise sets.

| Field | Type | Description |
|-------|------|-------------|
| set_id | STRING | Generated hash from (workout_id, exercise, set_number) |
| workout_id | STRING | Foreign key to jefit_workouts |
| exercise_name | STRING | Exercise performed |
| set_number | INT | Set sequence within exercise |
| reps_completed | INT | Reps performed |
| weight_kg | FLOAT | Weight used |
| rpe | INT | Rate of Perceived Exertion (6-10 scale) |
| notes | STRING | Optional set notes |

**Primary Key:** set_id  
**Composite Key:** (workout_id, exercise_name, set_number)  
**Partitioning:** `year/month`

### exercises_taxonomy
Exercise classification reference table.

| Field | Type | Description |
|-------|------|-------------|
| exercise_name | STRING | Standardized exercise name |
| primary_muscle_group | STRING | chest \| back \| legs \| shoulders \| arms \| core |
| movement_type | STRING | compound \| isolation |
| equipment_type | STRING | barbell \| dumbbell \| machine \| bodyweight \| cable |

**Primary Key:** exercise_name  
**Partitioning:** None (reference table)

---

## Oura Summary Schema

Daily Oura integration is stored in a single `oura_summary` table.

| Field | Type | Description |
|-------|------|-------------|
| day | DATE | Local summary date from Oura (one row per day). |
| activity_score | INT | Oura activity score (0–100). Currently NULL until `daily_activity` endpoint is wired. |
| activity_contributors | MAP<STRING,INT> | Activity contributor name → score map. Currently NULL. |
| active_calories_kcal | INT | Active calories burned. Currently NULL. |
| total_calories_kcal | INT | Total calories (resting + active). Currently NULL. |
| steps | INT | Daily step count. Currently NULL. |
| equivalent_walking_distance_m | INT | Equivalent walking distance (meters). Currently NULL. |
| high_activity_time_s | INT | High-intensity activity time (seconds). Currently NULL. |
| medium_activity_time_s | INT | Medium-intensity activity time (seconds). Currently NULL. |
| low_activity_time_s | INT | Low-intensity activity time (seconds). Currently NULL. |
| sedentary_time_s | INT | Sedentary time (seconds). Currently NULL. |
| non_wear_time_s | INT | Estimated non-wear time (seconds). Currently NULL. |
| sleep_score | INT | Sleep score 0–100 from `daily_sleep` endpoint. |
| sleep_contributors | MAP<STRING,INT> | Sleep contributor name → score map (deep_sleep, efficiency, etc.). |
| total_sleep_duration_s | INT | Total sleep duration (seconds) from `sleep` endpoint. |
| time_in_bed_s | INT | Time in bed (seconds) from `sleep` endpoint. |
| deep_sleep_duration_s | INT | Deep sleep duration (seconds) from `sleep`. |
| light_sleep_duration_s | INT | Light sleep duration (seconds) from `sleep`. |
| rem_sleep_duration_s | INT | REM sleep duration (seconds) from `sleep`. |
| awake_time_s | INT | Awake time during the night (seconds) from `sleep`. |
| readiness_score | INT | Readiness score 0–100 from embedded readiness block in `sleep`. |
| readiness_contributors | MAP<STRING,INT> | Readiness contributor name → score map. |
| temperature_deviation_c | FLOAT | Nightly temperature deviation vs baseline (°C). |
| resting_heart_rate_bpm | INT | Lowest heart rate during sleep (true resting HR). |
| hrv_ms | INT | Average HRV during sleep (milliseconds). |
| source | STRING | Ingestion source label (e.g., `Oura`). |
| ingest_time_utc | TIMESTAMP | Ingestion timestamp (UTC). |
| ingest_run_id | STRING | Optional ingestion run identifier. |
| date | STRING | Hive partition key derived from `day` (`YYYY-MM-DD`). |

**Primary Key:** day  
**Partitioning:** `year/month`

## Laboratory Results

### labs_results
Individual biomarker measurements.

| Field | Type | Description |
|-------|------|-------------|
| result_id | UUID | Primary key |
| test_date | DATE | Lab test date (date only, no time) |
| lab_company | STRING | Quest \| LabCorp \| other |
| biomarker_name | STRING | Canonical biomarker name |
| original_name | STRING | Lab-specific name (audit trail) |
| result_value | FLOAT | Numeric measurement |
| result_unit | STRING | Unit of measure (mg/dL, ng/mL, etc.) |
| reference_range_low | FLOAT | Lab normal range minimum |
| reference_range_high | FLOAT | Lab normal range maximum |
| optimal_range_low | FLOAT | Longevity target minimum |
| optimal_range_high | FLOAT | Longevity target maximum |
| flag | STRING | normal \| high \| low \| critical |
| test_method | STRING | Measurement methodology (if specified) |
| fasting_status | BOOLEAN | Fasted blood draw |
| ingestion_id | UUID | Foreign key to ingestion_log |

**Composite Key:** (test_date, biomarker_name)  
**Partitioning:** `year`

### biomarker_mappings
Canonical biomarker names and reference data.

| Field | Type | Description |
|-------|------|-------------|
| canonical_name | STRING | Standardized biomarker name |
| aliases | LIST[STRING] | Lab-specific name variations |
| category | STRING | lipid \| hormone \| mineral \| inflammatory \| etc. |
| optimal_range_low | FLOAT | Longevity-focused lower bound |
| optimal_range_high | FLOAT | Longevity-focused upper bound |
| clinical_significance | STRING | Why this biomarker matters |

**Primary Key:** canonical_name  
**Partitioning:** None (reference table)

---

## Supplement & Medication Protocols

All protocol tables use **Strategy A** timezone handling.

### protocols_doses
Individual dose logs.

| Field | Type | Description |
|-------|------|-------------|
| dose_id | UUID | Primary key |
| compound_id | STRING | Foreign key to compounds_catalog |
| date | DATE | Date dose taken |
| time_of_day | STRING | morning \| afternoon \| evening \| bedtime |
| dose_amount | FLOAT | Dose quantity |
| dose_unit | STRING | mg \| mcg \| IU \| mL |
| administration_route | STRING | oral \| injection \| topical |
| taken_with_food | BOOLEAN | Food context |
| notes | STRING | Optional notes |
| ingestion_id | UUID | Foreign key to ingestion_log |

**Composite Key:** (date, compound_id, time_of_day)  
**Partitioning:** `year/month`

### compounds_catalog
Supplement/medication reference data.

| Field | Type | Description |
|-------|------|-------------|
| compound_id | STRING | Primary key |
| compound_name | STRING | Standardized name |
| common_aliases | LIST[STRING] | Alternative names |
| category | STRING | supplement \| medication \| hormone \| vitamin \| mineral |
| mechanism_of_action | STRING | How it works |
| expected_half_life_hours | FLOAT | Duration in system |
| optimal_timing | STRING | morning \| evening \| with_meals \| fasting |
| interactions | LIST[STRING] | Compound IDs to separate timing |

**Primary Key:** compound_id  
**Partitioning:** None (reference table)

### protocols_phases
Protocol period tracking.

| Field | Type | Description |
|-------|------|-------------|
| phase_id | UUID | Primary key |
| start_date | DATE | Protocol start |
| end_date | DATE | Protocol end (nullable if ongoing) |
| phase_name | STRING | Protocol name |
| primary_objective | STRING | Goal description |
| success_metrics | LIST[STRING] | Target biomarkers/outcomes |
| associated_compounds | LIST[STRING] | Compound IDs in protocol |

**Primary Key:** phase_id  
**Partitioning:** None (reference table)

---

## Gold Layer (Analysis Tables)

### integrated_daily
All sources joined by date for cross-source analysis.

| Field | Type | Description |
|-------|------|-------------|
| date_utc | DATE | Join key |
| concept2_total_meters | FLOAT | Daily rowing/skiing/biking distance |
| jefit_total_volume_kg | FLOAT | Daily resistance training volume |
| oura_readiness_score | INT | Readiness score |
| oura_sleep_score | INT | Sleep quality score |
| oura_hrv_ms | FLOAT | Average HRV |
| hae_resting_hr_avg | INT | Daily average resting HR |
| hae_steps_total | INT | Total daily steps |
| active_protocols | LIST[STRING] | Compounds taken this day |
| lab_tests | LIST[STRING] | Biomarkers tested this day |

**Primary Key:** date_utc  
**Partitioning:** `year`  
**Updated:** Daily after silver ingestion

---

## Partitioning Strategy Summary

| Source | Partitioning | Rationale |
|--------|-------------|-----------|
| HAE | `year/month` | High volume, minute-level data |
| Concept2 Workouts | `year/month` | Moderate volume |
| Concept2 Strokes | `year/month` | Very high volume (20k+ per workout) |
| JEFIT | `year/month` | Moderate volume |
| Oura | `year/month` | Daily summaries, moderate volume |
| Labs | `year` | Low frequency, sparse data |
| Protocols | `year/month` | Daily logs, moderate volume |
| Metadata | `year/month` | Operational logs |

**Monthly partitioning** avoids PyArrow's 10k partition limit while maintaining query performance.

---

**See Also:**
- [Architecture.md](Architecture.md) - System design
- [DataSources.md](DataSources.md) - Ingestion details
- [TimestampHandling.md](TimestampHandling.md) - Timezone strategies
- [StorageAndQuery.md](StorageAndQuery.md) - DuckDB query patterns