# src/pipeline/common/schema.py
from __future__ import annotations

import pyarrow as pa

SOURCES = {"HAE_CSV", "HAE_JSON", "Concept2"}

# Base fields for wide minute_facts (metric columns are dynamic)
minute_facts_base = pa.schema([
    pa.field("timestamp_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("timestamp_local", pa.timestamp("us"), nullable=True),
    pa.field("tz_name", pa.string(), nullable=True),
    pa.field("source", pa.string(), nullable=False),
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),
])


# Base fields for wide daily_summary (daily grain)
daily_summary_base = pa.schema([
    pa.field("date_utc", pa.date32(), nullable=False),
    pa.field("source", pa.string(), nullable=False),
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),
    # common daily totals (nullable)
    pa.field("steps", pa.int32(), nullable=True),
    pa.field("active_energy_kcal", pa.float64(), nullable=True),
    pa.field("basal_energy_kcal", pa.float64(), nullable=True),
    pa.field("calories_kcal", pa.float64(), nullable=True),
    pa.field("distance_mi", pa.float64(), nullable=True),
    pa.field("flights_climbed", pa.int32(), nullable=True),
    pa.field("resting_hr_bpm", pa.float64(), nullable=True),
    pa.field("hrv_ms", pa.float64(), nullable=True),
    pa.field("respiratory_rate_bpm", pa.float64(), nullable=True),
    pa.field("sleep_minutes_asleep", pa.int32(), nullable=True),
    pa.field("sleep_minutes_in_bed", pa.int32(), nullable=True),
    pa.field("sleep_score", pa.float64(), nullable=True),
    pa.field("weight_lb", pa.float64(), nullable=True),
    pa.field("body_fat_pct", pa.float64(), nullable=True),
    pa.field("temperature_degF", pa.float64(), nullable=True),
    pa.field("protein_g", pa.float64(), nullable=True),
    pa.field("carbs_g", pa.float64(), nullable=True),
    pa.field("fat_g", pa.float64(), nullable=True),
    # hydration (imperial)
    pa.field("water_fl_oz", pa.int32(), nullable=True),
    # derived (guarded)
    pa.field("sleep_efficiency_pct", pa.float64(), nullable=True),
    pa.field("energy_total_kcal", pa.float64(), nullable=True),
    pa.field("net_energy_kcal", pa.float64(), nullable=True),
])

