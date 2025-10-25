# Health Data Pipeline — Schema Specification (v1.2)
**Date:** 2025-10-24

## 0) Overview & Global Rules
- **Design:** Wide → Wide. Minute-level CSV input is wide (one row per minute, multiple metric columns), and the `minute_facts` table remains wide.
- **Lineage fields (present in all tables):**
  - `source` (**enum**, non-null): One of `HAE_CSV`, `HAE_JSON`, `Concept2`.
  - `_ingest_time_utc_` (timestamp UTC, non-null): Time the pipeline wrote the row.
  - `ingest_run_id` (string): Identifier for the ingest execution that produced the row.
- **Timezone policy:** All operational times are stored in **UTC**. Local timestamps may be retained as explicit columns for audit/display.
- **Partitioning (Hive-style):** Each dataset is partitioned by **date** and **source**.
- **Nullability:** Explicitly specified in column tables. Fields not listed as non-null are nullable.
- **Uniqueness:** Each table defines a logical **Primary Key (PK)**; ingesters must enforce dedupe on the PK.

## 1) Table: minute_facts (WIDE)
**Row grain:** 1 minute × 1 source.  
**PK:** (`timestamp_utc`, `source`)  
**Partitions:** `date = DATE(timestamp_utc)` and `source`

| Column            | Type            | Null | Description |
|-------------------|-----------------|------|-------------|
| timestamp_utc     | timestamp (UTC) | NO   | Minute-level timestamp in UTC. |
| timestamp_local   | timestamp       | YES  | Original local timestamp as exported by source. |
| tz_name           | string          | YES  | IANA timezone name corresponding to `timestamp_local`. |
| **metric columns…** | numeric         | YES  | One column per metric (e.g., `steps`, `heart_rate_avg`, `active_energy_kcal`). Extensible set. |
| source            | enum(string)    | NO   | One of `HAE_CSV`, `HAE_JSON`, `Concept2`. |
| ingest_time_utc   | timestamp (UTC) | NO   | Pipeline write time for this row. |
| ingest_run_id     | string          | YES  | Ingest execution identifier. |

## 2) Table: daily_summary
**Row grain:** 1 calendar day × 1 source.  
**PK:** (`date_utc`, `source`)  
**Partitions:** `date = date_utc` and `source`

| Column          | Type            | Null | Description |
|-----------------|-----------------|------|-------------|
| date_utc        | date            | NO   | Calendar date in UTC. |
| **metric columns…** | numeric         | YES  | One column per daily metric. |
| source          | enum(string)    | NO   | One of `HAE_CSV`, `HAE_JSON`, `Concept2`. |
| ingest_time_utc | timestamp (UTC) | NO   | Pipeline write time for this row. |
| ingest_run_id   | string          | YES  | Ingest execution identifier. |

## 3) Table: workouts
**Row grain:** 1 workout/session.  
**PK:** (`workout_id`, `source`)  
**Partitions:** `date = DATE(start_time_utc)` and `source`

| Column          | Type            | Null | Description |
|-----------------|-----------------|------|-------------|
| workout_id      | string          | NO   | Natural ID from the source when available; otherwise synthesized stable ID. |
| source          | enum(string)    | NO   | One of `HAE_CSV`, `HAE_JSON`, `Concept2`. |
| sport_type      | string          | YES  | Activity type. |
| start_time_utc  | timestamp (UTC) | NO   | Workout start time in UTC. |
| end_time_utc    | timestamp (UTC) | YES  | Workout end time in UTC. |
| duration_s      | int64           | YES  | Duration in seconds. |
| distance_m      | float64         | YES  | Distance in meters. |
| avg_hr_bpm      | float64         | YES  | Average heart rate. |
| max_hr_bpm      | float64         | YES  | Max heart rate. |
| calories_kcal   | float64         | YES  | Calories expended. |
| notes           | string          | YES  | Free-text notes. |
| device_id       | string          | YES  | Device identifier. |
| ingest_time_utc | timestamp (UTC) | NO   | Pipeline write time for this row. |
| ingest_run_id   | string          | YES  | Ingest execution identifier. |

## 4) Enumerations
Allowed `source` values: `HAE_CSV`, `HAE_JSON`, `Concept2`.

## 5) Version History
| Version | Date       | Changes |
|---------|------------|---------|
| v1.2    | 2025-10-24 | Wide→Wide minute_facts; added lineage fields; date+source partitions; clarified PKs. |


### daily_summary additions
- `water_fl_oz` (INT, imperial)
- Derived: sleep_efficiency_pct, energy_total_kcal, net_energy_kcal (guarded)
- Wide-table write rule: write if >=1 metric exists; skip only if all missing
