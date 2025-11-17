#!/usr/bin/env python3
"""
Ingest Oura Sleep JSON data from Raw/Oura/ -> Parquet/oura_summary/

This script:
1. Loads raw JSON files from both 'sleep' and 'daily_sleep' endpoints
2. Merges them on 'day' to combine measurements with scores
3. Extracts all sleep measurements, scores, and embedded readiness data
4. Maps Oura's fields to the 'oura_summary' schema
5. Writes the result to the 'oura_summary' Parquet table with source='Oura'
6. Archives the processed raw JSON files

Data sources:
- 'sleep' endpoint: All measurements (durations, HR, HRV, temperature)
- 'daily_sleep' endpoint: Sleep score and contributor scores
Combined: Complete picture with both raw data and Oura's validated scoring
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa

from pipeline.common.parquet_io import (
    add_lineage_fields,
    create_date_partition_column,
    write_partitioned_dataset,
)
from pipeline.common.schema import get_schema
from pipeline.paths import (
    RAW_OURA_SLEEP_DIR,
    ARCHIVE_OURA_SLEEP_DIR,
    OURA_SUMMARY_PATH,
)

log = logging.getLogger(__name__)

def _load_raw_jsons(data_dir: Path, pattern: str = "*.json") -> pd.DataFrame:
    """Loads JSON files matching pattern from a directory into a DataFrame."""
    files = list(data_dir.glob(pattern))
    if not files:
        return pd.DataFrame()

    records = []
    processed_files = []
    for f in files:
        try:
            with open(f, 'r') as f_in:
                records.append(json.load(f_in))
            processed_files.append(f)
        except json.JSONDecodeError:
            log.warning(f"Skipping malformed JSON file: {f.name}")
    
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    # Keep track of original file for archiving
    df["_file_path"] = processed_files  
    return df

def _archive_processed_files(df: pd.DataFrame, archive_dir: Path):
    """Moves processed JSON files to the archive directory."""
    if "_file_path" not in df.columns or df.empty:
        return

    archive_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for f_path in df["_file_path"].unique():
        if f_path and isinstance(f_path, Path) and f_path.exists():
            try:
                shutil.move(str(f_path), str(archive_dir / f_path.name))
                count += 1
            except Exception as e:
                log.warning(f"Failed to archive {f_path.name}: {e}")
    
    if count > 0:
        log.info(f"Archived {count} files to {archive_dir.relative_to(archive_dir.parent.parent.parent)}")

def _extract_readiness_fields(readiness_obj):
    """Extract fields from nested readiness object."""
    if not isinstance(readiness_obj, dict):
        return None, None, None
    
    temp_dev = readiness_obj.get("temperature_deviation")
    score = readiness_obj.get("score")
    contributors = readiness_obj.get("contributors", {})
    
    return temp_dev, score, contributors

def main():
    """Main ingestion logic."""
    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log.info(f"Starting Oura JSON ingestion (run_id={ingest_run_id})")

    # 1. Load data from both endpoints
    sleep_df = _load_raw_jsons(RAW_OURA_SLEEP_DIR, pattern="oura_sleep_*.json")
    daily_sleep_df = _load_raw_jsons(RAW_OURA_SLEEP_DIR, pattern="oura_daily_sleep_*.json")

    if sleep_df.empty and daily_sleep_df.empty:
        log.info("No new Oura sleep JSON files found to ingest.")
        return

    # 2. Merge sleep measurements with sleep scores on 'day'
    if not sleep_df.empty and not daily_sleep_df.empty:
        log.info(f"Loaded {len(sleep_df)} sleep records and {len(daily_sleep_df)} daily_sleep records.")
        base_df = sleep_df.merge(
            daily_sleep_df, 
            on="day", 
            how="outer", 
            suffixes=("_sleep", "_score")
        )
        log.info(f"Merged into {len(base_df)} daily records.")
    elif not sleep_df.empty:
        log.info(f"Loaded {len(sleep_df)} sleep records (no daily_sleep data).")
        base_df = sleep_df
    else:
        log.info(f"Loaded {len(daily_sleep_df)} daily_sleep records (no sleep data).")
        base_df = daily_sleep_df

    # 3. Map Oura fields to our schema
    out = pd.DataFrame()
    out["day"] = pd.to_datetime(base_df["day"]).dt.date

    # --- Activity Metrics (not available from sleep endpoints) ---
    out["activity_score"] = None
    out["activity_contributors"] = None
    out["active_calories_kcal"] = None
    out["total_calories_kcal"] = None
    out["steps"] = None
    out["equivalent_walking_distance_m"] = None
    out["high_activity_time_s"] = None
    out["medium_activity_time_s"] = None
    out["low_activity_time_s"] = None
    out["sedentary_time_s"] = None
    out["non_wear_time_s"] = None

    # --- Sleep Metrics ---
    # Sleep score from daily_sleep endpoint
    # Handle potential suffix from merge
    if "score_score" in base_df.columns:
        out["sleep_score"] = base_df["score_score"]
    elif "score" in base_df.columns:
        out["sleep_score"] = base_df["score"]
    else:
        out["sleep_score"] = None
    
    # Sleep contributors from daily_sleep endpoint
    if "contributors_score" in base_df.columns:
        out["sleep_contributors"] = base_df["contributors_score"]
    elif "contributors" in base_df.columns:
        out["sleep_contributors"] = base_df["contributors"]
    else:
        out["sleep_contributors"] = None
    
    # Actual measurements from sleep endpoint
    out["total_sleep_duration_s"] = base_df.get("total_sleep_duration")
    out["time_in_bed_s"] = base_df.get("time_in_bed")

    # Sleep stage durations (seconds)
    out["deep_sleep_duration_s"] = base_df.get("deep_sleep_duration")
    out["light_sleep_duration_s"] = base_df.get("light_sleep_duration")
    out["rem_sleep_duration_s"] = base_df.get("rem_sleep_duration")
    out["awake_time_s"] = base_df.get("awake_time")

    # --- Readiness Metrics ---
    # Extract from nested readiness object in sleep endpoint
    if "readiness" in base_df.columns:
        readiness_data = base_df["readiness"].apply(_extract_readiness_fields)
        out["temperature_deviation_c"] = readiness_data.apply(lambda x: x[0] if x else None)
        out["readiness_score"] = readiness_data.apply(lambda x: x[1] if x else None)
        out["readiness_contributors"] = readiness_data.apply(lambda x: x[2] if x else None)
    else:
        out["temperature_deviation_c"] = None
        out["readiness_score"] = None
        out["readiness_contributors"] = None
    
    # Heart rate metrics from sleep measurements
    # lowest_heart_rate during sleep = true resting baseline
    out["resting_heart_rate_bpm"] = base_df.get("lowest_heart_rate")
    
    # HRV from sleep (the gold standard measurement)
    out["hrv_ms"] = base_df.get("average_hrv")

    # 4. Add lineage and partitioning
    out = add_lineage_fields(out, source="Oura", ingest_run_id=ingest_run_id)
    out = create_date_partition_column(out, "day", "date", "D")

    # 5. Filter to schema columns and write
    schema = get_schema("oura_summary")
    final_cols = [f.name for f in schema if f.name in out.columns]
    out = out[final_cols]
    
    # Ensure no-NaN-to-None conversion for pyarrow
    out = out.where(pd.notnull(out), None)

    table = pa.Table.from_pandas(out, schema=schema, preserve_index=False)
    
    log.info(f"Writing {len(table)} processed Oura records to oura_summary")
    write_partitioned_dataset(
        table,
        OURA_SUMMARY_PATH,
        partition_cols=["date", "source"],
        schema=schema,
        mode="delete_matching",  # Overwrite any existing Oura data for these days
    )

    # 6. Archive raw files
    _archive_processed_files(sleep_df, ARCHIVE_OURA_SLEEP_DIR)
    _archive_processed_files(daily_sleep_df, ARCHIVE_OURA_SLEEP_DIR)

    log.info(f"✅ Oura JSON ingestion complete.")


if __name__ == "__main__":
    if not log.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s [%(message)s]",
        )
    main()
