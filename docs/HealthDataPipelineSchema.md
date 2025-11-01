# Health Data Pipeline — Schema Specification (v2.0)
**Date:** 2025-11-01

## 0) Overview & Global Rules

**Major v2.0 Changes:**
- Added `cardio_splits` and `cardio_strokes` tables for Concept2 granular data
- Added `resistance_sets` table for JEFIT strength training
- Expanded `workouts` table to universal session container
- Added `JEFIT` source enum

**Design Philosophy:**
- **Wide → Wide:** Minute-level CSV input is wide (one row per minute, multiple metric columns), and the `minute_facts` table remains wide.
- **Universal workouts table:** Single parent table for all workout types (cardio, strength, flexibility, etc.)
- **Optional granular children:** Not every workout has splits/strokes/sets - nullable relationships

**Lineage fields (present in all tables):**
- `source` (**enum**, non-null): One of `HAE_CSV`, `HAE_JSON`, `Concept2`, `JEFIT`
- `ingest_time_utc` (timestamp UTC, non-null): Time the pipeline wrote the row
- `ingest_run_id` (string): Identifier for the ingest execution that produced the row

**Timezone policy:** The pipeline uses a **hybrid timestamp strategy** with three timestamps (timestamp_utc, timestamp_local, tz_name) to support both pipeline operations and circadian analysis. See `docs/TimestampHandling.md` for comprehensive details on Strategy A (assumed timezone for lossy sources) vs Strategy B (rich timezone for high-quality sources).

**Partitioning (Hive-style):** Each dataset is partitioned by **date** and **source**.

**Nullability:** Explicitly specified in column tables. Fields not listed as non-null are nullable.

**Uniqueness:** Each table defines a logical **Primary Key (PK)**; ingesters must enforce dedupe on the PK.

---

## 1) Table: minute_facts (WIDE)
**Row grain:** 1 minute × 1 source  
**PK:** (`timestamp_utc`, `source`)  
**Partitions:** `date = DATE(timestamp_utc)` and `source`

| Column            | Type            | Null | Description |
|-------------------|-----------------|------|-------------|
| timestamp_utc     | timestamp (UTC) | NO   | **Pipeline canonical time.** Absolute, normalized timestamp used for joins, dedup, partitioning, sorting. Always calculated from timestamp_local + tz_name. |
| timestamp_local   | timestamp (no TZ) | NO   | **Analysis time.** The "wall clock" time for circadian analysis. Used for grouping by hour-of-day, time-since-waking, bedtime patterns. Stored naive (no TZ) in Parquet. |
| tz_name           | string          | YES  | **Context for local time.** IANA timezone name (e.g., "America/Los_Angeles") that makes timestamp_local unambiguous. Strategy A sources use assumed home timezone; Strategy B sources use actual timezone from source. |
| tz_source         | string          | YES  | **Timezone provenance.** Either "assumed" (Strategy A: HAE CSV/JSON) or "actual" (Strategy B: workouts with rich timezone data). Documents reliability of tz_name. |
| **metric columns…** | numeric         | YES  | One column per metric (e.g., `steps`, `heart_rate_avg`, `active_energy_kcal`). Extensible set. |
| source            | enum(string)    | NO   | `HAE_CSV` |
| ingest_time_utc   | timestamp (UTC) | NO   | Pipeline write time for this row |
| ingest_run_id     | string          | YES  | Ingest execution identifier |

**Note:** See `TimestampHandling.md` for detailed Strategy A (assumed timezone) vs Strategy B (rich timezone) ingestion rules.

---

## 2) Table: daily_summary
**Row grain:** 1 calendar day × 1 source  
**PK:** (`date_utc`, `source`)  
**Partitions:** `date = date_utc` and `source`

| Column          | Type            | Null | Description |
|-----------------|-----------------|------|-------------|
| date_utc        | date            | NO   | Calendar date in UTC |
| **metric columns…** | numeric         | YES  | One column per daily metric |
| source          | enum(string)    | NO   | `HAE_CSV` |
| ingest_time_utc | timestamp (UTC) | NO   | Pipeline write time for this row |
| ingest_run_id   | string          | YES  | Ingest execution identifier |

---

## 3) Table: workouts (Universal Session Container)
**Row grain:** 1 workout/session  
**PK:** (`workout_id`, `source`)  
**Partitions:** `date = DATE(start_time_utc)` and `source`

### Core Fields (all workouts)

| Column              | Type            | Null | Description |
|---------------------|-----------------|------|-------------|
| workout_id          | string          | NO   | Natural ID from source or synthesized stable ID |
| source              | enum(string)    | NO   | `HAE_JSON`, `Concept2`, `JEFIT` |
| workout_type        | string          | YES  | Activity type: "Rowing", "Cycling", "Walking", "TraditionalStrengthTraining", etc. |
| start_time_utc      | timestamp (UTC) | NO   | **Pipeline canonical time.** Calculated from start_time_local + timezone for joins, partitioning. |
| end_time_utc        | timestamp (UTC) | YES  | **Pipeline canonical time.** Calculated from end_time_local + timezone. |
| start_time_local    | timestamp (no TZ) | NO   | **Analysis time.** Wall clock start time. Stored naive in Parquet. |
| end_time_local      | timestamp (no TZ) | YES  | **Analysis time.** Wall clock end time. Stored naive in Parquet. |
| timezone            | string          | YES  | **Context for local times.** IANA timezone (e.g., "America/Los_Angeles"). Strategy B sources (HAE_JSON, Concept2, JEFIT) store actual per-workout timezone from source. |
| tz_source           | string          | YES  | Always "actual" for workouts (all workout sources have rich timezone data - Strategy B). |
| duration_s          | int64           | YES  | Duration in seconds |
| device_id           | string          | YES  | Device identifier |
| notes               | string          | YES  | User notes/comments |

### Cardio Fields (nullable, for cardio workouts)

| Column              | Type            | Null | Description |
|---------------------|-----------------|------|-------------|
| distance_m          | float64         | YES  | Distance in meters |
| avg_hr_bpm          | float64         | YES  | Average heart rate |
| max_hr_bpm          | float64         | YES  | Max heart rate |
| min_hr_bpm          | float64         | YES  | Min heart rate |
| calories_kcal       | float64         | YES  | Calories expended |
| avg_pace_sec_per_500m | float64       | YES  | Average pace (rowing/biking) |

### Concept2-Specific Fields (nullable, Concept2 only)

| Column              | Type            | Null | Description |
|---------------------|-----------------|------|-------------|
| c2_workout_type     | string          | YES  | "FixedTimeSplits", "FixedDistance", "JustRow", etc. |
| erg_type            | string          | YES  | "rower", "bikeerg", "skierg" |
| stroke_rate         | float64         | YES  | Average strokes/cadence per minute |
| stroke_count        | int32           | YES  | Total strokes |
| drag_factor         | int32           | YES  | Drag factor setting |
| ranked              | boolean         | YES  | Whether ranked on Concept2 leaderboard |
| verified            | boolean         | YES  | Verified by Concept2 |
| has_splits          | boolean         | YES  | Whether split data available |
| has_strokes         | boolean         | YES  | Whether stroke data available |

### Resistance Training Fields (nullable, strength workouts)

| Column              | Type            | Null | Description |
|---------------------|-----------------|------|-------------|
| total_sets          | int32           | YES  | Total sets completed |
| total_reps          | int32           | YES  | Total reps completed |
| total_volume_lbs    | float64         | YES  | Total volume (weight × reps) |
| exercises_count     | int32           | YES  | Number of distinct exercises |

### Lineage Fields

| Column              | Type            | Null | Description |
|---------------------|-----------------|------|-------------|
| ingest_time_utc     | timestamp (UTC) | NO   | Pipeline write time |
| ingest_run_id       | string          | YES  | Ingest execution ID |

---

## 4) Table: cardio_splits
**Row grain:** 1 split interval within a workout  
**PK:** (`workout_id`, `split_number`, `source`)  
**Partitions:** `date = DATE(workout_start_utc)` and `source`

| Column              | Type            | Null | Description |
|---------------------|-----------------|------|-------------|
| workout_id          | string          | NO   | Links to workouts.workout_id |
| workout_start_utc   | timestamp (UTC) | NO   | For partitioning |
| split_number        | int32           | NO   | 1, 2, 3... (sequential) |
| split_time_s        | int32           | YES  | Duration of this split (seconds) |
| split_distance_m    | int32           | YES  | Distance of this split (meters) |
| calories_total      | int32           | YES  | Calories in this split |
| stroke_rate         | float64         | YES  | Average stroke rate for split |
| avg_hr_bpm          | float64         | YES  | Average HR for split |
| min_hr_bpm          | float64         | YES  | Min HR for split |
| max_hr_bpm          | float64         | YES  | Max HR for split |
| ending_hr_bpm       | float64         | YES  | Ending HR for split |
| source              | enum(string)    | NO   | `Concept2` |
| ingest_time_utc     | timestamp (UTC) | NO   | Pipeline write time |
| ingest_run_id       | string          | YES  | Ingest execution ID |

---

## 5) Table: cardio_strokes
**Row grain:** 1 stroke/pedal within a workout  
**PK:** (`workout_id`, `stroke_number`, `source`)  
**Partitions:** `date = DATE(workout_start_utc)` and `source`

| Column              | Type            | Null | Description |
|---------------------|-----------------|------|-------------|
| workout_id          | string          | NO   | Links to workouts.workout_id |
| workout_start_utc   | timestamp (UTC) | NO   | For partitioning |
| stroke_number       | int32           | NO   | Sequential stroke number (1, 2, 3...) |
| time_cumulative_s   | int32           | NO   | Cumulative time from workout start (seconds) |
| distance_cumulative_m | int32         | NO   | Cumulative distance from workout start (meters) |
| pace_500m_cs        | int32           | YES  | Instantaneous pace (centiseconds per 500m) |
| heart_rate_bpm      | int32           | YES  | Heart rate at this stroke |
| stroke_rate_spm     | int32           | YES  | Strokes per minute at this point |
| source              | enum(string)    | NO   | `Concept2` |
| ingest_time_utc     | timestamp (UTC) | NO   | Pipeline write time |
| ingest_run_id       | string          | YES  | Ingest execution ID |

---

## 6) Table: resistance_sets
**Row grain:** 1 set of 1 exercise  
**PK:** (`workout_id`, `exercise_id`, `set_number`, `source`)  
**Partitions:** `date = DATE(workout_start_utc)` and `source`

| Column              | Type            | Null | Description |
|---------------------|-----------------|------|-------------|
| workout_id          | string          | NO   | Links to workouts.workout_id |
| workout_start_utc   | timestamp (UTC) | NO   | For partitioning |
| exercise_id         | string          | NO   | Exercise identifier from JEFIT |
| exercise_name       | string          | NO   | "Dumbbell Bench Press", "Barbell Squat", etc. |
| set_number          | int32           | NO   | 1, 2, 3... (within this exercise in this workout) |
| target_reps         | int32           | YES  | Planned reps |
| actual_reps         | int32           | YES  | Completed reps |
| weight_lbs          | float64         | YES  | Load in pounds |
| rest_time_s         | int32           | YES  | Rest period after this set (seconds) |
| is_warmup           | boolean         | YES  | Whether this is a warmup set |
| is_failure          | boolean         | YES  | Whether set taken to failure |
| bodypart            | string          | YES  | "Chest", "Back", "Legs", "Core", etc. |
| equipment           | string          | YES  | "Dumbbell", "Barbell", "Cable", "Bodyweight" |
| notes               | string          | YES  | Set-specific notes |
| source              | enum(string)    | NO   | `JEFIT` |
| ingest_time_utc     | timestamp (UTC) | NO   | Pipeline write time |
| ingest_run_id       | string          | YES  | Ingest execution ID |

---

## 7) Enumerations

**Allowed `source` values:**
```
HAE_CSV      # Apple Health Daily CSV (minute_facts, daily_summary)
HAE_JSON     # Apple Health Workouts JSON
Concept2     # Concept2 Logbook API
JEFIT        # JEFIT app export
```

---

## 8) Relationships

```
workouts (1) ──┬──> (0..n) cardio_splits
               ├──> (0..n) cardio_strokes  
               └──> (0..n) resistance_sets

Foreign Key: workout_id
```

**Multiplicity:**
- Apple Health walk: `workouts` only (no children)
- Concept2 workout: `workouts` + `cardio_splits` + `cardio_strokes`
- JEFIT session: `workouts` + `resistance_sets`

---

## 9) Version History

| Version | Date       | Changes |
|---------|------------|---------|
| v2.0    | 2025-11-01 | Added cardio_splits, cardio_strokes, resistance_sets tables; expanded workouts to universal container; added JEFIT source |
| v1.2    | 2025-10-24 | Wide→Wide minute_facts; added lineage fields; date+source partitions; clarified PKs |
