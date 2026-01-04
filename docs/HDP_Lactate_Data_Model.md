# HDP Lactate Data Model Specification

**Project:** Health Data Pipeline (HDP)  
**Author:** Claude (Opus 4.5) with Peter  
**Date:** January 3, 2026  
**Status:** Draft - Extends existing lactate_schema in schema.py

---

## Overview

This document specifies enhancements to the existing HDP lactate data model to support Peter's three testing scenarios while maintaining proper context (elapsed time, power output, test type) that gets lost when forcing one reading per workout.

### Current State (schema.py)

Your existing `lactate_schema` in `src/pipeline/common/schema.py`:

```python
lactate_schema = pa.schema([
    # Link to workout
    pa.field("workout_id", pa.string(), nullable=False),
    pa.field("workout_start_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    
    # Measurement
    pa.field("lactate_mmol", pa.float64(), nullable=False),  # mmol/L
    pa.field("measurement_time_utc", pa.timestamp("us", tz="UTC"), nullable=True),
    pa.field("measurement_context", pa.string(), nullable=True),  # e.g., "post-workout"
    pa.field("notes", pa.string(), nullable=True),  # Original comment text
    
    # Lineage
    pa.field("source", pa.string(), nullable=False),  # 'Concept2_Comment' or 'Manual'
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),
    
    # Hive partitioning
    pa.field("date", pa.string(), nullable=True),
])
```

**Current primary key:** `["workout_id", "source"]` (from validate_parquet_tables.py)

### Problem Statement

Current approach: One lactate reading per workout, extracted from Concept2 comments via `lactate_extraction.py`.

**Issues:**
1. **Primary key constraint:** `["workout_id", "source"]` only allows ONE reading per workout
2. Multi-reading validation sessions require artificial workout splits
3. Elapsed time context is lost (a reading at "15 min" in workout #2 might really be 40 min into sustained effort)
4. Step tests have multiple readings but need to stay as one logical workout
5. No structured way to track strip batch/storage for QC analysis
6. Outlier flagging not systematic

### Solution

Extend the existing schema with:
- New primary key that supports multiple readings per workout
- Elapsed time tracking
- Test type classification
- QC metadata (strip batch, storage, outlier flags)
- Step number for step tests

---

## Test Scenarios Supported

### Scenario 1: Zone 2 Single Reading

Standard Zone 2 ride/row with one lactate measurement at the end.

**Example:**
- 45-minute BikeErg at 145W
- Single lactate reading: 1.7 mmol/L at completion

**Data representation:**
```
workout: 45 min @ 145W avg
reading: 1.7 mmol/L @ 45 min elapsed, 145W, test_type='zone2_single'
```

---

### Scenario 2: Zone 2 Multi-Reading (Validation)

Zone 2 session at consistent power with multiple readings to validate stability or investigate anomalies (sudden spikes, drift, suspected strip issues).

**Example:**
- 60-minute BikeErg at 142W
- Readings at 15, 30, 32 (retest), and 45 minutes
- Reading at 30 min spiked to 1.9, retest at 32 min showed 1.6 (outlier identified)

**Data representation:**
```
workout: 60 min @ 142W avg
readings:
  - 1.4 mmol/L @ 15 min, test_type='zone2_multi'
  - 1.9 mmol/L @ 30 min, test_type='zone2_multi', is_outlier=true, outlier_reason='retest_lower'
  - 1.6 mmol/L @ 32 min, test_type='zone2_multi', notes='retest of 30min spike'
  - 1.7 mmol/L @ 45 min, test_type='zone2_multi'
```

**Key benefit:** All readings stay linked to one 60-min workout with true elapsed times.

---

### Scenario 3: Step Test

Progressive power steps within a single workout session, with lactate reading at end of each step.

**Example:**
- 50-minute session, 10 min per step
- Steps: 120W → 135W → 150W → 165W → 180W
- Reading at end of each step

**Data representation:**
```
workout: 50 min total, avg_watts=155 (less meaningful for step test)
readings:
  - 1.2 mmol/L @ 10 min, 120W, step_number=1, test_type='step_test'
  - 1.5 mmol/L @ 20 min, 135W, step_number=2, test_type='step_test'
  - 1.9 mmol/L @ 30 min, 150W, step_number=3, test_type='step_test'
  - 2.8 mmol/L @ 40 min, 165W, step_number=4, test_type='step_test'
  - 4.2 mmol/L @ 50 min, 180W, step_number=5, test_type='step_test'
```

**Key benefit:** Existing step test analysis scripts can read from structured table instead of parsing.

---

## Schema Definition

### Enhanced Schema (PyArrow format for schema.py)

This extends your existing `lactate_schema` while maintaining backward compatibility:

```python
# ============================================================================
# Lactate measurements (ENHANCED)
# ============================================================================

lactate_schema = pa.schema([
    # === Existing fields (maintain backward compatibility) ===
    
    # Link to workout
    pa.field("workout_id", pa.string(), nullable=False),
    pa.field("workout_start_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    
    # Measurement
    pa.field("lactate_mmol", pa.float64(), nullable=False),  # mmol/L
    pa.field("measurement_time_utc", pa.timestamp("us", tz="UTC"), nullable=True),
    pa.field("measurement_context", pa.string(), nullable=True),  # e.g., "post-workout"
    pa.field("notes", pa.string(), nullable=True),  # Original comment text
    
    # Lineage
    pa.field("source", pa.string(), nullable=False),  # 'Concept2_Comment', 'Manual', etc.
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),
    
    # Hive partitioning
    pa.field("date", pa.string(), nullable=True),
    
    # === NEW fields for enhanced tracking ===
    
    # Reading identification (for multiple readings per workout)
    pa.field("reading_sequence", pa.int32(), nullable=False),  # 1, 2, 3... within workout
    
    # Timing context
    pa.field("elapsed_minutes", pa.float64(), nullable=True),  # Minutes from workout start
    
    # Context at time of reading
    pa.field("watts_at_reading", pa.int32(), nullable=True),
    pa.field("hr_at_reading", pa.int32(), nullable=True),
    
    # Test classification
    pa.field("test_type", pa.string(), nullable=True),  # 'zone2_single', 'zone2_multi', 'step_test'
    pa.field("step_number", pa.int32(), nullable=True),  # Only for step_test
    
    # Equipment context
    pa.field("equipment_type", pa.string(), nullable=True),  # 'BikeErg', 'RowErg', etc.
    
    # Quality control
    pa.field("strip_batch", pa.string(), nullable=True),  # Manufacturer lot number
    pa.field("storage_location", pa.string(), nullable=True),  # 'bedroom_closet', 'bathroom', etc.
    pa.field("is_outlier", pa.bool_(), nullable=True),  # Flag for outlier readings
    pa.field("outlier_reason", pa.string(), nullable=True),  # 'retest_lower', 'strip_humidity', etc.
])
```

### Key Changes from Current Schema

| Change | Rationale |
|--------|-----------|
| Add `reading_sequence` | Enables multiple readings per workout (new PK component) |
| Add `elapsed_minutes` | True elapsed time from workout start |
| Add `watts_at_reading` | Power context at measurement time |
| Add `hr_at_reading` | HR context at measurement time |
| Add `test_type` | Classify zone2_single vs zone2_multi vs step_test |
| Add `step_number` | For step test analysis |
| Add `strip_batch` | QC tracking for strip lot numbers |
| Add `storage_location` | Track storage conditions (you discovered this matters!) |
| Add `is_outlier` | Systematic outlier flagging |
| Add `outlier_reason` | Document why reading was flagged |

### Updated Primary Key

**Current:** `["workout_id", "source"]`  
**New:** `["workout_id", "source", "reading_sequence"]`

Update in `validate_parquet_tables.py`:

```python
"lactate": {
    "path": "Data/Parquet/lactate",
    "partition_period": "M",
    "write_strategy": "upsert_by_key",
    "partition_cols": ["date", "source"],
    "primary_key": ["workout_id", "source", "reading_sequence"],  # CHANGED
    "expected_sources": ["Concept2_Comment", "Manual"],  # Added Manual
    "required_fields": ["workout_id", "measurement_time_utc", "lactate_mmol", "source", "reading_sequence"],
},
```

### Backward Compatibility

Existing data with single readings per workout will have `reading_sequence = 1`. The extraction code in `lactate_extraction.py` should be updated to set `reading_sequence = 1` for all extracted readings.

### Parquet File Structure

No change needed—continues using existing structure:

```
Data/Parquet/
└── lactate/
    └── date=YYYY-MM-01/
        └── source=Concept2_Comment/
            └── data.parquet
        └── source=Manual/
            └── data.parquet
```

---

## Field Specifications

### test_type

| Value | Description | step_number |
|-------|-------------|-------------|
| `zone2_single` | Standard Z2 session with one final reading | NULL |
| `zone2_multi` | Z2 session with multiple validation readings | NULL |
| `step_test` | Progressive step test protocol | Required (1, 2, 3...) |
| `threshold_test` | Lactate threshold/turn point test | NULL |
| `other` | Any other test type | NULL |

### outlier_reason

Suggested standardized values (free text, but consistency helps):

| Value | Description |
|-------|-------------|
| `retest_lower` | Retest showed significantly lower value |
| `retest_higher` | Retest showed significantly higher value |
| `strip_humidity` | Suspected humidity degradation |
| `strip_expired` | Strip past expiration |
| `technique_error` | Known sampling/application error |
| `meter_error` | Meter malfunction |
| `physiological` | Unusual but valid physiological response |

### storage_location

Track where strips were stored (learned this matters for accuracy):

| Value | Description |
|-------|-------------|
| `bedroom_closet` | Climate controlled, low humidity (preferred) |
| `bathroom` | High humidity (degrades strips) |
| `gym_bag` | Variable conditions |
| `refrigerator` | Some protocols recommend this |

---

## Parquet File Structure

Following HDP medallion architecture:

```
Data/Parquet/
└── lactate_readings/
    └── year=YYYY/
        └── data.parquet
```

**Partitioning rationale:** 
- Year-only partitioning (not year/month) because lactate tests are relatively infrequent (~2-10/month)
- Keeps file count manageable while enabling partition pruning

---

## Integration with Existing Tables

### Relationship to concept2_workouts

```
concept2_workouts (1) ──────< (many) lactate_readings
                     │
                     └── workout_id (FK, nullable)
```

**Join pattern:**
```sql
SELECT 
    w.workout_date,
    w.workout_type,
    w.avg_watts,
    w.total_seconds / 60.0 as duration_min,
    l.elapsed_minutes,
    l.lactate_mmol,
    l.test_type
FROM concept2_workouts w
LEFT JOIN lactate_readings l ON w.workout_id = l.workout_id
WHERE w.workout_date >= '2025-01-01'
ORDER BY w.workout_date, l.elapsed_minutes;
```

### Standalone Tests

Some lactate tests may not correspond to a logged Concept2 workout (e.g., outdoor run, test without PM5). These have `workout_id = NULL` but still have full context via other fields.

---

## Example Data

### Zone 2 Single Reading

```python
{
    # Existing fields
    "workout_id": "abc123",
    "workout_start_utc": datetime(2026, 1, 3, 16, 0, 0, tzinfo=timezone.utc),
    "lactate_mmol": 1.7,
    "measurement_time_utc": datetime(2026, 1, 3, 16, 45, 0, tzinfo=timezone.utc),
    "measurement_context": "post-workout",
    "notes": "1.7",  # Original comment
    "source": "Concept2_Comment",
    "ingest_time_utc": datetime.now(timezone.utc),
    "ingest_run_id": "20260103T170000Z_api",
    "date": "2026-01-01",  # Monthly partition
    
    # New fields
    "reading_sequence": 1,
    "elapsed_minutes": 45.0,
    "watts_at_reading": 145,
    "hr_at_reading": 138,
    "test_type": "zone2_single",
    "step_number": None,
    "equipment_type": "BikeErg",
    "strip_batch": "LOT-2025-12-A",
    "storage_location": "bedroom_closet",
    "is_outlier": False,
    "outlier_reason": None,
}
```

### Zone 2 Multi-Reading Session

```python
[
    {
        "workout_id": "def456",
        "workout_start_utc": datetime(2026, 1, 4, 16, 0, 0, tzinfo=timezone.utc),
        "lactate_mmol": 1.4,
        "measurement_time_utc": datetime(2026, 1, 4, 16, 15, 0, tzinfo=timezone.utc),
        "measurement_context": "mid-workout",
        "notes": "Baseline check @ 15min",
        "source": "Manual",
        "reading_sequence": 1,
        "elapsed_minutes": 15.0,
        "watts_at_reading": 142,
        "hr_at_reading": 132,
        "test_type": "zone2_multi",
        "equipment_type": "BikeErg",
        "strip_batch": "LOT-2025-12-A",
        "is_outlier": False,
        # ... lineage fields
    },
    {
        "workout_id": "def456",
        "lactate_mmol": 1.9,
        "measurement_time_utc": datetime(2026, 1, 4, 16, 30, 0, tzinfo=timezone.utc),
        "notes": "Unexpected spike, retesting",
        "source": "Manual",
        "reading_sequence": 2,
        "elapsed_minutes": 30.0,
        "watts_at_reading": 142,
        "hr_at_reading": 135,
        "test_type": "zone2_multi",
        "is_outlier": True,  # Flagged as outlier
        "outlier_reason": "retest_lower",
        # ...
    },
    {
        "workout_id": "def456",
        "lactate_mmol": 1.6,
        "notes": "Retest of 30min - confirms outlier",
        "source": "Manual",
        "reading_sequence": 3,
        "elapsed_minutes": 32.0,
        "test_type": "zone2_multi",
        "is_outlier": False,
        # ...
    },
    {
        "workout_id": "def456",
        "lactate_mmol": 1.7,
        "notes": "Final reading, stable",
        "source": "Manual",
        "reading_sequence": 4,
        "elapsed_minutes": 45.0,
        "test_type": "zone2_multi",
        "is_outlier": False,
        # ...
    },
]
```

### Step Test

```python
[
    {
        "workout_id": "ghi789",
        "workout_start_utc": datetime(2026, 1, 5, 16, 0, 0, tzinfo=timezone.utc),
        "lactate_mmol": 1.2,
        "measurement_time_utc": datetime(2026, 1, 5, 16, 10, 0, tzinfo=timezone.utc),
        "source": "Manual",
        "reading_sequence": 1,
        "elapsed_minutes": 10.0,
        "watts_at_reading": 120,
        "hr_at_reading": 115,
        "test_type": "step_test",
        "step_number": 1,
        "equipment_type": "BikeErg",
        "strip_batch": "LOT-2025-12-A",
        # ...
    },
    {
        "workout_id": "ghi789",
        "lactate_mmol": 1.5,
        "source": "Manual",
        "reading_sequence": 2,
        "elapsed_minutes": 20.0,
        "watts_at_reading": 135,
        "hr_at_reading": 128,
        "test_type": "step_test",
        "step_number": 2,
        # ...
    },
    {
        "workout_id": "ghi789",
        "lactate_mmol": 1.9,
        "source": "Manual",
        "reading_sequence": 3,
        "elapsed_minutes": 30.0,
        "watts_at_reading": 150,
        "hr_at_reading": 140,
        "test_type": "step_test",
        "step_number": 3,
        # ...
    },
    {
        "workout_id": "ghi789",
        "lactate_mmol": 2.8,
        "source": "Manual",
        "reading_sequence": 4,
        "elapsed_minutes": 40.0,
        "watts_at_reading": 165,
        "hr_at_reading": 152,
        "test_type": "step_test",
        "step_number": 4,
        # ...
    },
    {
        "workout_id": "ghi789",
        "lactate_mmol": 4.2,
        "source": "Manual",
        "reading_sequence": 5,
        "elapsed_minutes": 50.0,
        "watts_at_reading": 180,
        "hr_at_reading": 161,
        "test_type": "step_test",
        "step_number": 5,
        # ...
    },
]
```

---

## Common Queries (DuckDB)

These queries follow HDP patterns using the `lake.lactate` view or direct Parquet reads.

### Zone 2 Power Ceiling Over Time

Get the highest power output where lactate stayed in Zone 2 range (1.6-2.0 mmol/L):

```sql
-- Using DuckDB view
SELECT 
    DATE(measurement_time_utc) as test_date,
    MAX(watts_at_reading) as zone2_ceiling_watts,
    AVG(lactate_mmol) as avg_lactate
FROM lake.lactate
WHERE test_type IN ('zone2_single', 'zone2_multi')
  AND (is_outlier IS NULL OR is_outlier = FALSE)
  AND lactate_mmol BETWEEN 1.6 AND 2.0
GROUP BY DATE(measurement_time_utc)
ORDER BY test_date;
```

### Step Test Analysis (Lactate Curve)

Get data for plotting lactate curve from a specific test:

```sql
SELECT 
    step_number,
    watts_at_reading as watts,
    lactate_mmol as lactate,
    hr_at_reading as heart_rate,
    elapsed_minutes
FROM lake.lactate
WHERE workout_id = ?
  AND test_type = 'step_test'
ORDER BY step_number;
```

### Find LT1 (Lactate Threshold 1) from Step Test

First significant rise above baseline (typically ~2.0 mmol/L):

```sql
WITH step_data AS (
    SELECT 
        step_number,
        watts_at_reading,
        lactate_mmol,
        LAG(lactate_mmol) OVER (ORDER BY step_number) as prev_lactate
    FROM lake.lactate
    WHERE workout_id = ?
      AND test_type = 'step_test'
)
SELECT 
    watts_at_reading as lt1_watts,
    lactate_mmol
FROM step_data
WHERE lactate_mmol >= 2.0
  AND (prev_lactate IS NULL OR prev_lactate < 2.0)
LIMIT 1;
```

### Outlier Rate by Strip Batch (QC)

```sql
SELECT 
    strip_batch,
    storage_location,
    COUNT(*) as total_readings,
    SUM(CASE WHEN is_outlier THEN 1 ELSE 0 END) as outliers,
    ROUND(100.0 * SUM(CASE WHEN is_outlier THEN 1 ELSE 0 END) / COUNT(*), 1) as outlier_pct
FROM lake.lactate
WHERE strip_batch IS NOT NULL
GROUP BY strip_batch, storage_location
ORDER BY outlier_pct DESC;
```

### Multi-Reading Session Stability Analysis

Did lactate stabilize during validation sessions?

```sql
SELECT 
    workout_id,
    DATE(workout_start_utc) as workout_date,
    COUNT(*) as num_readings,
    MIN(lactate_mmol) as min_lac,
    MAX(lactate_mmol) as max_lac,
    MAX(lactate_mmol) - MIN(lactate_mmol) as spread,
    ROUND(AVG(lactate_mmol), 2) as avg_lac,
    ROUND(STDDEV(lactate_mmol), 2) as std_lac
FROM lake.lactate
WHERE test_type = 'zone2_multi'
  AND (is_outlier IS NULL OR is_outlier = FALSE)
GROUP BY workout_id, DATE(workout_start_utc)
HAVING COUNT(*) > 1
ORDER BY spread DESC;
```

### Latest Zone 2 Ceiling (for Dashboard KPI)

```sql
SELECT 
    watts_at_reading as zone2_watts,
    lactate_mmol,
    DATE(measurement_time_utc) as test_date
FROM lake.lactate
WHERE test_type IN ('zone2_single', 'zone2_multi')
  AND (is_outlier IS NULL OR is_outlier = FALSE)
  AND lactate_mmol BETWEEN 1.6 AND 2.0
  AND watts_at_reading IS NOT NULL
ORDER BY measurement_time_utc DESC
LIMIT 1;
```

### Correlation with Workout Data

Join lactate readings with workout metrics:

```sql
SELECT 
    l.workout_id,
    l.lactate_mmol,
    l.elapsed_minutes,
    l.watts_at_reading,
    l.test_type,
    w.workout_type,
    DATE(w.start_time_utc) as workout_date,
    ROUND(w.duration_s / 60.0, 1) as duration_min,
    ROUND(w.avg_hr_bpm, 1) as avg_hr,
    ROUND(w.max_hr_bpm, 1) as max_hr,
    -- Power-to-lactate ratio (higher = better aerobic efficiency)
    ROUND(l.watts_at_reading / l.lactate_mmol, 1) as watts_per_lactate
FROM lake.lactate l
JOIN lake.workouts w ON l.workout_id = w.workout_id
WHERE w.source = 'Concept2'
  AND (l.is_outlier IS NULL OR l.is_outlier = FALSE)
ORDER BY l.measurement_time_utc DESC;
```

---

## Data Entry Methods

### Method 1: Enhanced Concept2 Comment Extraction

Update `lactate_extraction.py` to populate new fields when possible:

```python
def extract_lactate_from_workouts(
    workouts_df: pd.DataFrame,
    ingest_run_id: str,
    source: str = "Concept2_Comment",
) -> pd.DataFrame:
    """
    Extract lactate measurements from workout comments.
    ENHANCED: Adds reading_sequence and infers test_type.
    """
    if workouts_df.empty or 'notes' not in workouts_df.columns:
        return pd.DataFrame()
    
    records = []
    now_utc = datetime.now(timezone.utc)
    
    for _, row in workouts_df.iterrows():
        lactate = extract_lactate_from_comment(row.get('notes'))
        
        if lactate is not None:
            measurement_time = row.get('end_time_utc') or row['start_time_utc']
            
            # Calculate elapsed minutes
            start_time = row['start_time_utc']
            elapsed_min = None
            if measurement_time and start_time:
                elapsed_min = (measurement_time - start_time).total_seconds() / 60.0
            
            # Infer equipment type from workout_type
            equipment_type = None
            if row.get('workout_type') == 'Rowing':
                equipment_type = 'RowErg'
            elif row.get('workout_type') == 'Cycling':
                equipment_type = 'BikeErg'
            
            records.append({
                # Existing fields
                'workout_id': row['workout_id'],
                'workout_start_utc': row['start_time_utc'],
                'lactate_mmol': lactate,
                'measurement_time_utc': measurement_time,
                'measurement_context': 'post-workout',
                'notes': row.get('notes'),
                'source': source,
                'ingest_time_utc': now_utc,
                'ingest_run_id': ingest_run_id,
                
                # NEW fields
                'reading_sequence': 1,  # Single reading from comment
                'elapsed_minutes': elapsed_min,
                'watts_at_reading': None,  # Not available from comment
                'hr_at_reading': None,
                'test_type': 'zone2_single',  # Default assumption
                'step_number': None,
                'equipment_type': equipment_type,
                'strip_batch': None,
                'storage_location': None,
                'is_outlier': False,
                'outlier_reason': None,
            })
    
    return pd.DataFrame(records) if records else pd.DataFrame()
```

### Method 2: Manual CSV Import

Create CSV with all fields for multi-reading sessions:

```csv
workout_id,workout_start_utc,lactate_mmol,measurement_time_utc,reading_sequence,elapsed_minutes,watts_at_reading,hr_at_reading,test_type,step_number,equipment_type,strip_batch,storage_location,is_outlier,notes
def456,2026-01-04T16:00:00Z,1.4,2026-01-04T16:15:00Z,1,15,142,132,zone2_multi,,BikeErg,LOT-2025-12-A,bedroom_closet,false,Baseline check
def456,2026-01-04T16:00:00Z,1.9,2026-01-04T16:30:00Z,2,30,142,135,zone2_multi,,BikeErg,LOT-2025-12-A,bedroom_closet,true,Spike - retesting
def456,2026-01-04T16:00:00Z,1.6,2026-01-04T16:32:00Z,3,32,142,134,zone2_multi,,BikeErg,LOT-2025-12-A,bedroom_closet,false,Retest confirms outlier
def456,2026-01-04T16:00:00Z,1.7,2026-01-04T16:45:00Z,4,45,142,136,zone2_multi,,BikeErg,LOT-2025-12-A,bedroom_closet,false,Final reading
```

Import script:

```python
import pandas as pd
from pipeline.common.parquet_io import upsert_by_key
from pipeline.common.schema import get_schema
from pipeline.paths import LACTATE_PATH

def import_manual_lactate(csv_path: str):
    """Import manually recorded lactate readings."""
    df = pd.read_csv(csv_path, parse_dates=['workout_start_utc', 'measurement_time_utc'])
    
    # Add lineage
    df['source'] = 'Manual'
    df['ingest_time_utc'] = datetime.now(timezone.utc)
    df['ingest_run_id'] = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_manual"
    
    # Add partition column
    df['date'] = df['workout_start_utc'].dt.to_period('M').dt.to_timestamp().dt.strftime('%Y-%m-01')
    
    # Write
    upsert_by_key(
        df,
        LACTATE_PATH,
        primary_key=["workout_id", "source", "reading_sequence"],
        partition_cols=["date", "source"],
        schema=get_schema("lactate"),
    )
    
    print(f"Imported {len(df)} lactate readings")
```

### Method 3: Structured Concept2 Comments

For future readings, use a structured comment format that can be parsed:

**Single reading:**
```
LAC:1.7 W:145 HR:138 BATCH:LOT-2025-12-A
```

**Multi-reading (Zone 2 validation):**
```
LAC:1.4@15m,1.9@30m[outlier],1.6@32m,1.7@45m W:142 TYPE:z2m BATCH:LOT-2025-12-A
```

**Step test:**
```
STEP:1.2@120W,1.5@135W,1.9@150W,2.8@165W,4.2@180W TYPE:step BATCH:LOT-2025-12-A
```

Enhanced parser in `lactate_extraction.py`:

```python
def extract_structured_lactate(comment: str) -> list[dict]:
    """
    Parse structured lactate comment formats.
    Returns list of reading dicts.
    """
    if not comment or not isinstance(comment, str):
        return []
    
    readings = []
    
    # Check for STEP format
    step_match = re.search(r'STEP:(.+?)(?:\s+TYPE|\s+BATCH|$)', comment, re.I)
    if step_match:
        step_data = step_match.group(1)
        # Parse "1.2@120W,1.5@135W,..."
        step_readings = re.findall(r'(\d+\.?\d*)@(\d+)W', step_data)
        for i, (lac, watts) in enumerate(step_readings, 1):
            readings.append({
                'lactate_mmol': float(lac),
                'watts_at_reading': int(watts),
                'reading_sequence': i,
                'test_type': 'step_test',
                'step_number': i,
            })
        return readings
    
    # Check for multi-reading format
    multi_match = re.search(r'LAC:(.+?)(?:\s+W:|\s+TYPE:|$)', comment, re.I)
    if multi_match and ',' in multi_match.group(1):
        lac_data = multi_match.group(1)
        # Parse "1.4@15m,1.9@30m[outlier],..."
        lac_readings = re.findall(r'(\d+\.?\d*)@(\d+)m(\[outlier\])?', lac_data)
        for i, (lac, mins, outlier) in enumerate(lac_readings, 1):
            readings.append({
                'lactate_mmol': float(lac),
                'elapsed_minutes': float(mins),
                'reading_sequence': i,
                'test_type': 'zone2_multi',
                'is_outlier': bool(outlier),
            })
        return readings
    
    # Fall back to simple extraction
    simple_lac = extract_lactate_from_comment(comment)
    if simple_lac:
        readings.append({
            'lactate_mmol': simple_lac,
            'reading_sequence': 1,
            'test_type': 'zone2_single',
        })
    
    return readings
```

### Method 4: Streamlit Entry Form (Future)

Add a tab to HDP dashboard for lactate entry:

```python
def render_lactate_entry_form():
    """Streamlit form for manual lactate entry."""
    
    with st.form("lactate_entry"):
        st.subheader("Log Lactate Reading")
        
        # Link to workout
        workout_id = st.text_input("Workout ID (from Concept2)")
        
        col1, col2 = st.columns(2)
        with col1:
            reading_date = st.date_input("Date", value=date.today())
            elapsed_min = st.number_input("Elapsed Minutes", min_value=0.0, step=1.0)
            lactate = st.number_input("Lactate (mmol/L)", min_value=0.0, max_value=25.0, step=0.1)
        
        with col2:
            watts = st.number_input("Watts", min_value=0, step=5)
            hr = st.number_input("Heart Rate", min_value=0, step=1)
            test_type = st.selectbox("Test Type", ['zone2_single', 'zone2_multi', 'step_test'])
        
        step_num = None
        if test_type == 'step_test':
            step_num = st.number_input("Step Number", min_value=1, step=1)
        
        col3, col4 = st.columns(2)
        with col3:
            strip_batch = st.text_input("Strip Batch (optional)")
            storage = st.selectbox("Storage Location", [None, 'bedroom_closet', 'bathroom', 'gym_bag'])
        with col4:
            is_outlier = st.checkbox("Mark as Outlier")
            outlier_reason = st.text_input("Outlier Reason") if is_outlier else None
        
        notes = st.text_area("Notes (optional)")
        
        if st.form_submit_button("Save Reading"):
            # Build record and save
            save_manual_lactate_reading(...)
            st.success("Reading saved!")
```

---

## Migration / Backfill

### Step 1: Update schema.py

Add the new fields to `lactate_schema` in `src/pipeline/common/schema.py`:

```python
# Add these fields to existing lactate_schema
pa.field("reading_sequence", pa.int32(), nullable=False),
pa.field("elapsed_minutes", pa.float64(), nullable=True),
pa.field("watts_at_reading", pa.int32(), nullable=True),
pa.field("hr_at_reading", pa.int32(), nullable=True),
pa.field("test_type", pa.string(), nullable=True),
pa.field("step_number", pa.int32(), nullable=True),
pa.field("equipment_type", pa.string(), nullable=True),
pa.field("strip_batch", pa.string(), nullable=True),
pa.field("storage_location", pa.string(), nullable=True),
pa.field("is_outlier", pa.bool_(), nullable=True),
pa.field("outlier_reason", pa.string(), nullable=True),
```

### Step 2: Update validate_parquet_tables.py

Change the primary key:

```python
"lactate": {
    "path": "Data/Parquet/lactate",
    "partition_period": "M",
    "write_strategy": "upsert_by_key",
    "partition_cols": ["date", "source"],
    "primary_key": ["workout_id", "source", "reading_sequence"],  # UPDATED
    "expected_sources": ["Concept2_Comment", "Manual"],
    "required_fields": ["workout_id", "measurement_time_utc", "lactate_mmol", "source", "reading_sequence"],
},
```

### Step 3: Backfill Existing Data

Update existing lactate records with new fields:

```python
#!/usr/bin/env python3
"""
Migrate existing lactate data to enhanced schema.
Adds reading_sequence=1 to all existing records and infers other fields where possible.
"""
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq

from pipeline.common.parquet_io import write_partitioned_dataset
from pipeline.common.schema import get_schema
from pipeline.paths import LACTATE_PATH

def migrate_lactate_data():
    """Add new fields to existing lactate records."""
    
    # Read existing data
    print(f"Reading existing lactate data from {LACTATE_PATH}")
    existing = pd.read_parquet(LACTATE_PATH)
    
    if existing.empty:
        print("No existing lactate data to migrate")
        return
    
    print(f"Found {len(existing)} existing records")
    
    # Add new fields with defaults
    existing['reading_sequence'] = 1  # All existing are single readings
    existing['elapsed_minutes'] = None
    existing['watts_at_reading'] = None
    existing['hr_at_reading'] = None
    existing['test_type'] = 'zone2_single'  # Default assumption
    existing['step_number'] = None
    existing['equipment_type'] = None
    existing['strip_batch'] = None
    existing['storage_location'] = None
    existing['is_outlier'] = False
    existing['outlier_reason'] = None
    
    # Infer equipment_type from workout data if possible
    try:
        workouts = pd.read_parquet('Data/Parquet/workouts')
        workout_types = workouts[['workout_id', 'workout_type']].drop_duplicates()
        existing = existing.merge(workout_types, on='workout_id', how='left')
        
        existing.loc[existing['workout_type'] == 'Rowing', 'equipment_type'] = 'RowErg'
        existing.loc[existing['workout_type'] == 'Cycling', 'equipment_type'] = 'BikeErg'
        existing = existing.drop(columns=['workout_type'])
    except Exception as e:
        print(f"Could not infer equipment_type: {e}")
    
    # Backup existing data
    backup_path = LACTATE_PATH.parent / 'lactate_backup'
    print(f"Backing up existing data to {backup_path}")
    import shutil
    if backup_path.exists():
        shutil.rmtree(backup_path)
    shutil.copytree(LACTATE_PATH, backup_path)
    
    # Write with new schema
    print("Writing migrated data...")
    write_partitioned_dataset(
        existing,
        LACTATE_PATH,
        partition_cols=['date', 'source'],
        schema=get_schema('lactate'),
        mode='delete_matching'
    )
    
    print(f"✅ Migration complete: {len(existing)} records updated")

if __name__ == "__main__":
    migrate_lactate_data()
```

### Step 4: Update lactate_extraction.py

Modify `extract_lactate_from_workouts` to populate the new fields (see Data Entry Methods above).

### Step 5: Update DuckDB Views

If using DuckDB views, update to include new columns:

```sql
-- In scripts/sql/create-views.sql.template
CREATE OR REPLACE VIEW lake.lactate AS
SELECT 
    workout_id,
    workout_start_utc,
    lactate_mmol,
    measurement_time_utc,
    measurement_context,
    notes,
    source,
    ingest_time_utc,
    ingest_run_id,
    -- New fields
    reading_sequence,
    elapsed_minutes,
    watts_at_reading,
    hr_at_reading,
    test_type,
    step_number,
    equipment_type,
    strip_batch,
    storage_location,
    is_outlier,
    outlier_reason
FROM read_parquet('Data/Parquet/lactate/**/*.parquet', hive_partitioning=true);
```

---

## Dashboard Integration

### KPI Card: Zone 2 Power Ceiling

```python
@st.cache_data(ttl=3600)
def get_zone2_ceiling() -> dict:
    """Get latest validated Zone 2 power ceiling."""
    
    conn = duckdb.connect('Data/duck/health.duckdb', read_only=True)
    
    result = conn.execute("""
        SELECT 
            watts_at_reading,
            lactate_mmol,
            DATE(measurement_time_utc) as test_date
        FROM lake.lactate
        WHERE test_type IN ('zone2_single', 'zone2_multi')
          AND (is_outlier IS NULL OR is_outlier = FALSE)
          AND lactate_mmol BETWEEN 1.6 AND 2.0
          AND watts_at_reading IS NOT NULL
        ORDER BY measurement_time_utc DESC
        LIMIT 1
    """).fetchone()
    
    conn.close()
    
    if result:
        return {
            'watts': result[0],
            'lactate': result[1],
            'date': result[2]
        }
    return {'watts': None, 'lactate': None, 'date': None}
```

### Chart: Zone 2 Progression

```python
def render_zone2_progression(start_date: date, end_date: date):
    """Zone 2 power ceiling over time with lactate overlay."""
    
    conn = duckdb.connect('Data/duck/health.duckdb', read_only=True)
    
    data = conn.execute("""
        SELECT 
            DATE(measurement_time_utc) as test_date,
            watts_at_reading,
            lactate_mmol,
            test_type
        FROM lake.lactate
        WHERE test_type IN ('zone2_single', 'zone2_multi')
          AND (is_outlier IS NULL OR is_outlier = FALSE)
          AND lactate_mmol BETWEEN 1.0 AND 2.5
          AND measurement_time_utc BETWEEN ? AND ?
        ORDER BY measurement_time_utc
    """, [start_date, end_date]).df()
    
    conn.close()
    
    if data.empty:
        st.info("No lactate data in selected date range")
        return
    
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Power trend
    fig.add_trace(
        go.Scatter(
            x=data['test_date'], 
            y=data['watts_at_reading'],
            mode='markers+lines', 
            name='Power (W)',
            marker=dict(size=10)
        ),
        secondary_y=False
    )
    
    # Lactate values
    fig.add_trace(
        go.Scatter(
            x=data['test_date'], 
            y=data['lactate_mmol'],
            mode='markers', 
            name='Lactate (mmol/L)',
            marker=dict(color='red', size=8)
        ),
        secondary_y=True
    )
    
    # Zone 2 lactate band
    fig.add_hrect(
        y0=1.6, y1=2.0, 
        line_width=0, 
        fillcolor="green", 
        opacity=0.1, 
        secondary_y=True,
        annotation_text="Zone 2 Range"
    )
    
    fig.update_layout(
        title="Zone 2 Power Progression",
        xaxis_title="Date",
        hovermode='x unified'
    )
    fig.update_yaxes(title_text="Power (W)", secondary_y=False)
    fig.update_yaxes(title_text="Lactate (mmol/L)", secondary_y=True)
    
    st.plotly_chart(fig, use_container_width=True)
```

### Chart: Step Test Lactate Curve

```python
def render_step_test(workout_id: str):
    """Plot lactate curve from step test."""
    
    conn = duckdb.connect('Data/duck/health.duckdb', read_only=True)
    
    data = conn.execute("""
        SELECT 
            step_number, 
            watts_at_reading, 
            lactate_mmol, 
            hr_at_reading,
            elapsed_minutes
        FROM lake.lactate
        WHERE workout_id = ?
          AND test_type = 'step_test'
        ORDER BY step_number
    """, [workout_id]).df()
    
    conn.close()
    
    if data.empty:
        st.warning(f"No step test data found for workout {workout_id}")
        return
    
    fig = go.Figure()
    
    # Lactate curve
    fig.add_trace(go.Scatter(
        x=data['watts_at_reading'],
        y=data['lactate_mmol'],
        mode='markers+lines',
        name='Lactate',
        marker=dict(size=12),
        line=dict(width=2)
    ))
    
    # LT1 reference line (~2.0 mmol/L)
    fig.add_hline(
        y=2.0, 
        line_dash="dash", 
        line_color="orange",
        annotation_text="LT1 (~2.0 mmol/L)"
    )
    
    # LT2 reference line (~4.0 mmol/L)
    fig.add_hline(
        y=4.0, 
        line_dash="dash", 
        line_color="red",
        annotation_text="LT2 (~4.0 mmol/L)"
    )
    
    fig.update_layout(
        title="Step Test Lactate Curve",
        xaxis_title="Power (Watts)",
        yaxis_title="Lactate (mmol/L)",
        hovermode='x'
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Show data table
    with st.expander("Step Test Data"):
        st.dataframe(data, use_container_width=True, hide_index=True)
```

### QC Dashboard Panel

```python
def render_lactate_qc():
    """Quality control panel for lactate measurements."""
    
    st.subheader("🔬 Lactate QC")
    
    conn = duckdb.connect('Data/duck/health.duckdb', read_only=True)
    
    # Outlier rate by batch
    batch_qc = conn.execute("""
        SELECT 
            COALESCE(strip_batch, 'Unknown') as batch,
            COALESCE(storage_location, 'Unknown') as storage,
            COUNT(*) as total,
            SUM(CASE WHEN is_outlier THEN 1 ELSE 0 END) as outliers,
            ROUND(100.0 * SUM(CASE WHEN is_outlier THEN 1 ELSE 0 END) / COUNT(*), 1) as outlier_pct
        FROM lake.lactate
        GROUP BY strip_batch, storage_location
        ORDER BY outlier_pct DESC
    """).df()
    
    conn.close()
    
    if not batch_qc.empty:
        st.dataframe(batch_qc, use_container_width=True, hide_index=True)
        
        # Highlight problematic batches
        problem_batches = batch_qc[batch_qc['outlier_pct'] > 10]
        if not problem_batches.empty:
            st.warning(f"⚠️ {len(problem_batches)} batch(es) have >10% outlier rate")
    else:
        st.info("No lactate QC data available yet")
```

---

## Open Questions

1. **Standalone tests:** Should we support lactate readings without a linked `workout_id`? (e.g., outdoor runs, lab tests). Current design requires `workout_id` to be NOT NULL. Could change to nullable with a synthetic ID for standalone tests.

2. **Step test auto-detection:** Your existing `analyze_step_test.py` script parses step data. Should we integrate that logic into the extraction pipeline to automatically detect and tag step tests?

3. **Historical comment parsing:** How much historical lactate data exists in Concept2 comments? Worth investing in a parser to backfill, or just start fresh with the new schema?

4. **Lactate meter tracking:** Should we add a `meter_device` field to track which meter was used? (Useful if you ever compare meters or upgrade.)

5. **Measurement protocol:** Your existing `lactate_measurement_protocol.md` has great detail. Should any protocol fields (e.g., `measurement_delay_seconds`, `body_position`) be added to the schema for QC analysis?

---

## Related Files in HDP

| File | Purpose | Updates Needed |
|------|---------|----------------|
| `src/pipeline/common/schema.py` | Schema definitions | Add new fields to lactate_schema |
| `src/pipeline/common/lactate_extraction.py` | Extract from comments | Populate new fields |
| `scripts/backfill_lactate.py` | Backfill script | Update for new schema |
| `scripts/validate_parquet_tables.py` | Validation | Update primary key |
| `analysis/queries/lactate_tracking.sql` | Query examples | Use new fields |
| `analysis/scripts/analyze_step_test.py` | Step test analysis | Could integrate with new schema |
| `docs/lactate_measurement_protocol.md` | Protocol docs | Reference for QC fields |

---

## Version History

- **v1.0** (2026-01-03): Initial specification
  - Schema extension design (aligned with existing HDP architecture)
  - Three test scenarios (zone2_single, zone2_multi, step_test)
  - Migration path from current schema
  - Query examples using DuckDB
  - Dashboard integration patterns

---

**End of Document**
