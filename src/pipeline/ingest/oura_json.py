#!/usr/bin/env python3
"""
Ingest Oura Daily JSON data from Raw/Oura/ -> Parquet/oura_summary/

This script:
1.  Loads raw JSON files from sleep, activity, and readiness directories.
2.  Merges them into a single DataFrame per day.
3.  Maps Oura's fields to the new 'oura_summary' schema.
4.  Applies unit conversions (e.g., seconds -> minutes).
5.  Writes the result to the 'oura_summary' Parquet table with source='Oura'.
6.  Archives the processed raw JSON files.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pandas as pd
import pyarrow as pa

from pipeline.common.parquet_io import (
    add_lineage_fields,
    create_date_partition_column,
    write_partitioned_dataset,
)
from pipeline.common.schema import get_schema
from pipeline.paths import (
    RAW_OURA_ACTIVITY_DIR,
    RAW_OURA_READINESS_DIR,
    RAW_OURA_SLEEP_DIR,
    ARCHIVE_OURA_ACTIVITY_DIR,
    ARCHIVE_OURA_READINESS_DIR,
    ARCHIVE_OURA_SLEEP_DIR,
    OURA_SUMMARY_PATH,  # Use the new path
)

log = logging.getLogger(__name__)

def _load_raw_jsons(data_dir: Path) -> pd.DataFrame:
    """Loads all JSON files from a directory into a DataFrame."""
    files = list(data_dir.glob("*.json"))
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
    if "_file_path" not in df.columns:
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

def main():
    """Main ingestion logic."""
    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log.info(f"Starting Oura JSON ingestion (run_id={ingest_run_id})")

    # 1. Load all raw data
    sleep_df = _load_raw_jsons(RAW_OURA_SLEEP_DIR)
    activity_df = _load_raw_jsons(RAW_OURA_ACTIVITY_DIR)
    readiness_df = _load_raw_jsons(RAW_OURA_READINESS_DIR)

    if sleep_df.empty and activity_df.empty and readiness_df.empty:
        log.info("No new Oura JSON files found to ingest.")
        return

    # 2. Merge data on 'day'
    # Use 'outer' merge to keep all data even if one file is missing
    base_df = pd.DataFrame()
    
    if not activity_df.empty:
        base_df = activity_df.copy()

    if not sleep_df.empty:
        if base_df.empty:
            base_df = sleep_df.copy()
        else:
            base_df = base_df.merge(sleep_df, on="day", how="outer", suffixes=("_activity", "_sleep"))
    
    if not readiness_df.empty:
        if base_df.empty:
            base_df = readiness_df.copy()
        else:
            base_df = base_df.merge(readiness_df, on="day", how="outer", suffixes=(None, "_readiness"))

    if base_df.empty:
        log.info("No data to process after merge.")
        return
        
    log.info(f"Loaded and merged {len(base_df)} daily records.")

    # 3. Rename, clean, and map to schema
    # Use .get() to safely access columns that might be missing
    out = pd.DataFrame()
    out["day"] = pd.to_datetime(base_df["day"]).dt.date

    # --- Activity Metrics ---
    out["activity_score"] = base_df.get("score_activity") # from activity_df merge
    out["activity_contributors"] = base_df.get("contributors_activity")
    out["active_calories_kcal"] = base_df.get("active_calories")
    out["total_calories_kcal"] = base_df.get("total_calories")
    out["steps"] = base_df.get("steps")
    out["equivalent_walking_distance_m"] = base_df.get("equivalent_walking_distance")
    out["high_activity_time_s"] = base_df.get("high_activity_time")
    out["medium_activity_time_s"] = base_df.get("medium_activity_time")
    out["low_activity_time_s"] = base_df.get("low_activity_time")
    out["sedentary_time_s"] = base_df.get("sedentary_time")
    out["non_wear_time_s"] = base_df.get("non_wear_time")

    # --- Sleep Metrics ---
    out["sleep_score"] = base_df.get("score_sleep") # from sleep_df merge
    out["sleep_contributors"] = base_df.get("contributors_sleep")
    out["total_sleep_duration_s"] = base_df.get("total_sleep_duration")
    out["time_in_bed_s"] = base_df.get("time_in_bed")

    # --- Readiness Metrics ---
    out["readiness_score"] = base_df.get("score") # from readiness_df (no suffix)
    out["readiness_contributors"] = base_df.get("contributors")
    out["temperature_deviation_c"] = base_df.get("temperature_deviation")
    out["resting_heart_rate_bpm"] = base_df.get("resting_heart_rate")
    out["hrv_ms"] = base_df.get("hrv") # Assuming Oura 'hrv' is 'ms'

    # 4. Add lineage and partitioning
    out = add_lineage_fields(out, source="Oura", ingest_run_id=ingest_run_id)
    # Oura 'day' is already a UTC date, so we can use it directly
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
        mode="delete_matching", # Overwrite any existing Oura data for these days
    )

    # 6. Archive raw files
    _archive_processed_files(activity_df, ARCHIVE_OURA_ACTIVITY_DIR)
    _archive_processed_files(sleep_df, ARCHIVE_OURA_SLEEP_DIR)
    _archive_processed_files(readiness_df, ARCHIVE_OURA_READINESS_DIR)

    log.info(f"✅ Oura JSON ingestion complete.")


if __name__ == "__main__":
    if not log.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s [%(message)s]",
        )
    main()