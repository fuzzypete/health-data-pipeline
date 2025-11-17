# src/pipeline/ingest/hae_quick_csv.py
"""
HAE CSV ingestion - "Quick Export"

This script ingests **Quick Export** CSV files (e.g., "HealthAutoExport-...")
from the "Data/Raw/HAE/Quick/" directory.

NOTE: This format is now identical to the "Automation" (HealthMetrics) format.
It uses the minute-level map and converts sleep data from hours to minutes.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable
import pandas as pd
from datetime import datetime, timezone

from pipeline.paths import RAW_HAE_QUICK_DIR, ARCHIVE_HAE_QUICK_DIR
from pipeline.common.config import get_home_timezone
from pipeline.common.schema import get_schema
# Import the shared "Load" logic
from pipeline.common.hae_csv_utils import run_hae_csv_pipeline

log = logging.getLogger(__name__)

DEFAULT_SOURCE = "HAE_CSV_Quick"

# Get schemas once to build the "known columns" list
try:
    MINUTE_FACTS_SCHEMA = get_schema("minute_facts")
    DAILY_SUMMARY_SCHEMA = get_schema("daily_summary")
except ValueError as e:
    log.error(f"Could not load schemas. Have you defined 'minute_facts' and 'daily_summary'? Error: {e}")
    MINUTE_FACTS_SCHEMA = None
    DAILY_SUMMARY_SCHEMA = None

# ---------------------------------------------------------------------
# Column crosswalk: **minute-level** (Automation "HealthMetrics...")
# This is now used for BOTH Automation and Quick Export
# ---------------------------------------------------------------------
RENAME_MAP_AUTOMATION = {
    "Date/Time": "timestamp_local", # Common
    
    # Automation names -> Canonical Schema names
    'Apple Exercise Time (min)': 'apple_exercise_time_min',
    'Apple Sleeping Wrist Temperature (degF)': 'sleeping_wrist_temp_degf',
    'Blood Glucose (mg/dL)': 'blood_glucose_mg_dl',
    'Blood Oxygen Saturation (%)': 'blood_oxygen_saturation_pct',
    'Blood Pressure [Diastolic] (mmHg)': 'blood_pressure_diastolic_mmhg',
    'Blood Pressure [Systolic] (mmHg)': 'blood_pressure_systolic_mmhg',
    'Body Mass Index (count)': 'body_mass_index_count',
    'Carbohydrates (g)': 'carbs_g',
    'Cardio Recovery (count/min)': 'cardio_recovery_count_min',
    'Cycling Distance (mi)': 'cycling_distance_mi',
    'Fiber (g)': 'fiber_g',
    'Heart Rate Variability (ms)': 'hrv_ms',
    'Heart Rate [Avg] (count/min)': 'heart_rate_avg',
    'Heart Rate [Max] (count/min)': 'heart_rate_max',
    'Heart Rate [Min] (count/min)': 'heart_rate_min',
    'Lean Body Mass (lb)': 'lean_body_mass_lb',
    'Mindful Minutes (min)': 'mindful_minutes_min',
    'Physical Effort (kcal/hr·kg)': 'physical_effort_kcal_hr_kg',
    'Protein (g)': 'protein_g',
    'Respiratory Rate (count/min)': 'respiratory_rate_count_min',
    'Resting Heart Rate (count/min)': 'resting_hr_bpm',
    'Time in Daylight (min)': 'time_in_daylight_min',
    'Total Fat (g)': 'total_fat_g',
    'VO2 Max (ml/(kg·min))': 'vo2_max_ml_kg_min',
    'Walking + Running Distance (mi)': 'walking_running_distance_mi',
    'Water (fl_oz_us)': 'water_fl_oz',
    'Weight (lb)': 'weight_lb', 
    
    'Active Energy (kcal)': 'active_energy_kcal',
    'Resting Energy (kcal)': 'basal_energy_kcal',
    'Steps (count)': 'steps',
    'Distance (mi)': 'distance_mi',
    'Flights Climbed (count)': 'flights_climbed',
    'Dietary Energy (kcal)': 'diet_calories_kcal',
    'Body Fat Percentage (%)': 'body_fat_pct',
    'Body Temperature (degF)': 'temperature_degF',

    'Sleep Analysis [Asleep] (hr)': 'sleep_asleep_hr',
    'Sleep Analysis [Awake] (hr)': 'sleep_awake_hr',
    'Sleep Analysis [Core] (hr)': 'sleep_core_hr',
    'Sleep Analysis [Deep] (hr)': 'sleep_deep_hr',
    'Sleep Analysis [In Bed] (hr)': 'sleep_in_bed_hr',
    'Sleep Analysis [REM] (hr)': 'sleep_rem_hr',
    'Sleep Analysis [Total] (hr)': 'sleep_total_hr',
    
    # Columns from the new Quick Export not in the Automation one
    'Saturated Fat (g)': 'saturated_fat_g', # You may need to add this to schema.py if it's not there
    'Walking Heart Rate Average (count/min)': 'walking_hr_avg_count_min', # You may need to add this
    'Walking Speed (mi/hr)': 'walking_speed_mi_hr', # You may need to add this
}

# --- Master list of all known CANONICAL column names ---
ALL_KNOWN_CANONICAL_COLS = set()
if MINUTE_FACTS_SCHEMA:
    ALL_KNOWN_CANONICAL_COLS.update(MINUTE_FACTS_SCHEMA.names)
if DAILY_SUMMARY_SCHEMA:
    ALL_KNOWN_CANONICAL_COLS.update(DAILY_SUMMARY_SCHEMA.names)
ALL_KNOWN_CANONICAL_COLS.update([
    'sleep_asleep_hr', 'sleep_awake_hr', 'sleep_core_hr', 
    'sleep_deep_hr', 'sleep_in_bed_hr', 'sleep_rem_hr', 'sleep_total_hr',
    'saturated_fat_g', 'walking_hr_avg_count_min', 'walking_speed_mi_hr'
])

# ---------------------------------------------------------------------
# "Extract" and "Transform" steps
# ---------------------------------------------------------------------
def _load_csv(csv_path: Path) -> pd.DataFrame:
    """
    Load a raw "Quick Export" CSV from HAE.
    Applies the "Automation-style" rename map and unit conversions.
    """
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()

    log.info("%s: Applying 'Automation-style' (HealthMetrics) map.", csv_path.name)
    df = df.rename(columns=RENAME_MAP_AUTOMATION)
    
    # --- Perform Unit Conversions (hr -> min) ---
    sleep_cols_hr = {
        'sleep_asleep_hr': 'sleep_minutes_asleep',
        'sleep_in_bed_hr': 'sleep_minutes_in_bed',
    }
    for hr_col, min_col in sleep_cols_hr.items():
        if hr_col in df.columns:
            df[min_col] = pd.to_numeric(df[hr_col], errors='coerce') * 60

    # --- Validation Logging ---
    actual_cols = set(df.columns)
    extra_cols = actual_cols - ALL_KNOWN_CANONICAL_COLS
    if extra_cols:
        log.warning(
            "%s: Found %d UNEXPECTED columns after rename (will be ignored): %s",
            csv_path.name, len(extra_cols), sorted(list(extra_cols))
        )
        
    if "timestamp_local" not in df.columns:
        raise ValueError(f"{csv_path.name}: No 'timestamp_local' column found after rename. Check RENAME_MAP.")

    return df

def _iter_raw_csvs(raw_dir: Path) -> Iterable[Path]:
    """Iterate over CSV files in directory."""
    return sorted(raw_dir.glob("*.csv"))

# ---------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------
def main() -> None:
    """
    Process all CSV files in Data/Raw/HAE/Quick/
    """
    files = list(_iter_raw_csvs(RAW_HAE_QUICK_DIR))
    if not files:
        log.info("No CSV files found in %s", RAW_HAE_QUICK_DIR)
        return

    processed = 0
    failed = 0
    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    home_tz = get_home_timezone()
    
    for f in files:
        try:
            # 1. Extract & Transform
            df = _load_csv(f) 
            
            # 2. Load (using shared logic)
            run_hae_csv_pipeline(f, df, DEFAULT_SOURCE, ingest_run_id, home_tz)
            
            # Optional: Move to archive after successful processing
            # archive_path = ARCHIVE_HAE_QUICK_DIR / f.name
            # f.rename(archive_path)
            # log.info("Archived: %s → %s", f.name, archive_path)
            
            processed += 1
        except Exception:
            failed += 1
            
    log.info("Run complete. Processed=%d Failed=%d", processed, failed)

if __name__ == "__main__":
    if not log.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
    main()