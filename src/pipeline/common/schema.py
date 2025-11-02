"""
PyArrow schema definitions for Health Data Pipeline tables.

Defines schemas for all tables as specified in docs/HealthDataPipelineSchema.md v2.0.
"""
from __future__ import annotations

import pyarrow as pa

# Valid source enumerations
SOURCES = {"HAE_CSV", "HAE_JSON", "Concept2", "JEFIT"}


# ============================================================================
# Minute-level health metrics (wide table)
# ============================================================================

minute_facts_base = pa.schema([
    # Timestamps (Strategy A - assumed timezone)
    pa.field("timestamp_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("timestamp_local", pa.timestamp("us"), nullable=False),
    pa.field("tz_name", pa.string(), nullable=True),
    pa.field("tz_source", pa.string(), nullable=True),  # 'assumed' or 'actual'
    
    # Common metrics (extensible - add more as needed)
    pa.field("steps", pa.int32(), nullable=True),
    pa.field("heart_rate_avg", pa.float64(), nullable=True),
    pa.field("heart_rate_min", pa.float64(), nullable=True),
    pa.field("heart_rate_max", pa.float64(), nullable=True),
    pa.field("active_energy_kcal", pa.float64(), nullable=True),
    pa.field("basal_energy_kcal", pa.float64(), nullable=True),
    pa.field("distance_mi", pa.float64(), nullable=True),
    
    # Lineage
    pa.field("source", pa.string(), nullable=False),
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),
])


# ============================================================================
# Daily summary (wide table)
# ============================================================================

daily_summary_schema = pa.schema([
    # Date partition
    pa.field("date_utc", pa.date32(), nullable=False),
    
    # Activity totals
    pa.field("steps", pa.int32(), nullable=True),
    pa.field("active_energy_kcal", pa.float64(), nullable=True),
    pa.field("basal_energy_kcal", pa.float64(), nullable=True),
    pa.field("calories_kcal", pa.float64(), nullable=True),
    pa.field("distance_mi", pa.float64(), nullable=True),
    pa.field("flights_climbed", pa.int32(), nullable=True),
    
    # Health metrics
    pa.field("resting_hr_bpm", pa.float64(), nullable=True),
    pa.field("hrv_ms", pa.float64(), nullable=True),
    pa.field("respiratory_rate_bpm", pa.float64(), nullable=True),
    
    # Sleep totals
    pa.field("sleep_minutes_asleep", pa.int32(), nullable=True),
    pa.field("sleep_minutes_in_bed", pa.int32(), nullable=True),
    pa.field("sleep_score", pa.float64(), nullable=True),
    
    # Body metrics (imperial)
    pa.field("weight_lb", pa.float64(), nullable=True),
    pa.field("body_fat_pct", pa.float64(), nullable=True),
    pa.field("temperature_degF", pa.float64(), nullable=True),
    
    # Nutrition
    pa.field("protein_g", pa.float64(), nullable=True),
    pa.field("carbs_g", pa.float64(), nullable=True),
    pa.field("fat_g", pa.float64(), nullable=True),
    pa.field("water_fl_oz", pa.int32(), nullable=True),
    
    # Derived (guarded)
    pa.field("sleep_efficiency_pct", pa.float64(), nullable=True),
    pa.field("energy_total_kcal", pa.float64(), nullable=True),
    pa.field("net_energy_kcal", pa.float64(), nullable=True),
    
    # Lineage
    pa.field("source", pa.string(), nullable=False),
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),
])


# ============================================================================
# Workouts (universal session container)
# ============================================================================

workouts_schema = pa.schema([
    # Core fields
    pa.field("workout_id", pa.string(), nullable=False),
    pa.field("source", pa.string(), nullable=False),
    pa.field("workout_type", pa.string(), nullable=True),
    
    # Timestamps (Strategy B - actual timezone)
    pa.field("start_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("end_time_utc", pa.timestamp("us", tz="UTC"), nullable=True),
    pa.field("start_time_local", pa.timestamp("us"), nullable=False),
    pa.field("end_time_local", pa.timestamp("us"), nullable=True),
    pa.field("timezone", pa.string(), nullable=True),
    pa.field("tz_source", pa.string(), nullable=True),  # Always 'actual' for workouts
    
    pa.field("duration_s", pa.int64(), nullable=True),
    pa.field("device_id", pa.string(), nullable=True),
    pa.field("notes", pa.string(), nullable=True),
    
    # Cardio fields
    pa.field("distance_m", pa.float64(), nullable=True),
    pa.field("avg_hr_bpm", pa.float64(), nullable=True),
    pa.field("max_hr_bpm", pa.float64(), nullable=True),
    pa.field("min_hr_bpm", pa.float64(), nullable=True),
    pa.field("calories_kcal", pa.float64(), nullable=True),
    pa.field("avg_pace_sec_per_500m", pa.float64(), nullable=True),
    
    # Concept2-specific fields
    pa.field("c2_workout_type", pa.string(), nullable=True),
    pa.field("erg_type", pa.string(), nullable=True),  # 'rower', 'bikeerg', 'skierg'
    pa.field("stroke_rate", pa.float64(), nullable=True),
    pa.field("stroke_count", pa.int32(), nullable=True),
    pa.field("drag_factor", pa.int32(), nullable=True),
    pa.field("ranked", pa.bool_(), nullable=True),
    pa.field("verified", pa.bool_(), nullable=True),
    pa.field("has_splits", pa.bool_(), nullable=True),
    pa.field("has_strokes", pa.bool_(), nullable=True),
    
    # Resistance training fields
    pa.field("total_sets", pa.int32(), nullable=True),
    pa.field("total_reps", pa.int32(), nullable=True),
    pa.field("total_volume_lbs", pa.float64(), nullable=True),
    pa.field("exercises_count", pa.int32(), nullable=True),
    
    # Lineage
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),

    # Hive partitioning field (string for directory names)
    pa.field("date", pa.string(), nullable=True),
])


# ============================================================================
# Cardio splits (Concept2 intervals)
# ============================================================================

cardio_splits_schema = pa.schema([
    # Foreign key
    pa.field("workout_id", pa.string(), nullable=False),
    pa.field("workout_start_utc", pa.timestamp("us", tz="UTC"), nullable=False),  # For partitioning
    
    # Split data
    pa.field("split_number", pa.int32(), nullable=False),
    pa.field("split_time_s", pa.int32(), nullable=True),
    pa.field("split_distance_m", pa.int32(), nullable=True),
    pa.field("calories_total", pa.int32(), nullable=True),
    pa.field("stroke_rate", pa.float64(), nullable=True),
    
    # Heart rate
    pa.field("avg_hr_bpm", pa.float64(), nullable=True),
    pa.field("min_hr_bpm", pa.float64(), nullable=True),
    pa.field("max_hr_bpm", pa.float64(), nullable=True),
    pa.field("ending_hr_bpm", pa.float64(), nullable=True),
    
    # Lineage
    pa.field("source", pa.string(), nullable=False),  # Always 'Concept2'
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),

    # Hive partitioning field (string for directory names)
    pa.field("date", pa.string(), nullable=True),
])


# ============================================================================
# Cardio strokes (Concept2 stroke-by-stroke)
# ============================================================================

cardio_strokes_schema = pa.schema([
    # Foreign key
    pa.field("workout_id", pa.string(), nullable=False),
    pa.field("workout_start_utc", pa.timestamp("us", tz="UTC"), nullable=False),  # For partitioning
    
    # Stroke data
    pa.field("stroke_number", pa.int32(), nullable=False),
    pa.field("time_cumulative_s", pa.int32(), nullable=False),
    pa.field("distance_cumulative_m", pa.int32(), nullable=False),
    pa.field("pace_500m_cs", pa.int32(), nullable=True),  # Centiseconds per 500m
    pa.field("heart_rate_bpm", pa.int32(), nullable=True),
    pa.field("stroke_rate_spm", pa.int32(), nullable=True),  # Strokes per minute
    
    # Lineage
    pa.field("source", pa.string(), nullable=False),  # Always 'Concept2'
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),

    # Hive partitioning field (string for directory names)
    pa.field("date", pa.string(), nullable=True),
])


# ============================================================================
# Resistance sets (JEFIT)
# ============================================================================

resistance_sets_schema = pa.schema([
    # Foreign keys
    pa.field("workout_id", pa.string(), nullable=False),
    pa.field("workout_start_utc", pa.timestamp("us", tz="UTC"), nullable=False),  # For partitioning
    pa.field("exercise_id", pa.string(), nullable=False),
    
    # Exercise info
    pa.field("exercise_name", pa.string(), nullable=False),
    pa.field("set_number", pa.int32(), nullable=False),
    
    # Set data
    pa.field("target_reps", pa.int32(), nullable=True),
    pa.field("actual_reps", pa.int32(), nullable=True),
    pa.field("weight_lbs", pa.float64(), nullable=True),
    pa.field("rest_time_s", pa.int32(), nullable=True),
    pa.field("is_warmup", pa.bool_(), nullable=True),
    pa.field("is_failure", pa.bool_(), nullable=True),
    
    # Exercise metadata
    pa.field("bodypart", pa.string(), nullable=True),
    pa.field("equipment", pa.string(), nullable=True),
    pa.field("notes", pa.string(), nullable=True),
    
    # Lineage
    pa.field("source", pa.string(), nullable=False),  # Always 'JEFIT'
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),

    # Hive partitioning field (string for directory names)
    pa.field("date", pa.string(), nullable=True),
])


# ============================================================================
# Schema registry (for convenience)
# ============================================================================

SCHEMAS = {
    'minute_facts': minute_facts_base,
    'daily_summary': daily_summary_schema,
    'workouts': workouts_schema,
    'cardio_splits': cardio_splits_schema,
    'cardio_strokes': cardio_strokes_schema,
    'resistance_sets': resistance_sets_schema,
}


def get_schema(table_name: str) -> pa.Schema:
    """Get PyArrow schema by table name."""
    if table_name not in SCHEMAS:
        raise ValueError(f"Unknown table: {table_name}. Available: {list(SCHEMAS.keys())}")
    return SCHEMAS[table_name]
