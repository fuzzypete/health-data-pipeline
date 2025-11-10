# src/pipeline/ingest/hae_workouts.py
"""
Ingest HAE Workout JSON files.

Reads from: Data/Raw/JSON/
Writes to: Data/Parquet/workouts/

Uses Strategy B (Rich Timezone) principle, trusting the per-event
timestamps (with offsets) provided in the JSON.

v2.1: Reverted to monthly partitioning. Daily partitioning combined
with upsert_by_key() causes 'Too many open files' error on large
backfills.

v2.2: Added drop_duplicates() before upsert to handle overlapping
raw JSON files (e.g., a daily file and a historical file).
"""
import logging
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any

import pandas as pd

# Import from your common utilities
from pipeline.paths import RAW_HAE_JSON_DIR, ARCHIVE_HAE_JSON_DIR, WORKOUTS_PATH
from pipeline.common.schema import get_schema
from pipeline.common.parquet_io import (
    add_lineage_fields,
    create_date_partition_column,
    upsert_by_key,
)

log = logging.getLogger(__name__)
DEFAULT_SOURCE = "HAE_JSON"

# Cache the schema
WORKOUTS_SCHEMA = get_schema("workouts")

def _archive_file(file_path: Path):
    """Moves a processed file to the archive directory."""
    try:
        ARCHIVE_HAE_JSON_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(file_path), str(ARCHIVE_HAE_JSON_DIR / file_path.name))
        log.info(f"Archived file: {file_path.name}")
    except Exception as e:
        log.warning(f"Failed to archive file {file_path.name}: {e}")


def parse_hae_timestamp(ts_str: str) -> tuple[pd.Timestamp, pd.Timestamp, str]:
    """
    Parses an HAE timestamp string (which includes an offset).
    Returns (utc_timestamp, naive_local_timestamp, tz_name).
    """
    if not ts_str:
        return None, None, None
    
    # Parse the full string to a timezone-aware timestamp
    aware_ts = pd.to_datetime(ts_str)
    
    # 1. UTC timestamp
    utc_ts = aware_ts.tz_convert('UTC')
    
    # 2. Naive local timestamp (wall time)
    naive_local_ts = aware_ts.tz_localize(None)
    
    # 3. Timezone name (offset string)
    tz_name = aware_ts.tzname()
    
    return utc_ts, naive_local_ts, tz_name

def get_qty(data: dict, units: str = None) -> float | None:
    """Helper to safely extract 'qty' from HAE metric dicts."""
    if not data or not isinstance(data, dict):
        return None
    return data.get('qty')


def process_workout_json(workout_json: Dict[str, Any], ingest_run_id: str) -> Dict[str, Any] | None:
    """
    Parses a single HAE workout JSON object into a flat record.
    """
    try:
        start_utc, start_local, tz = parse_hae_timestamp(workout_json.get('start'))
        end_utc, end_local, _ = parse_hae_timestamp(workout_json.get('end'))

        if not start_utc:
            log.warning(f"Skipping workout with no start time: {workout_json.get('id')}")
            return None

        duration_float = workout_json.get('duration')
        record = {
            "workout_id": workout_json.get('id'),
            "source": DEFAULT_SOURCE,
            "workout_type": workout_json.get('name'),
            "start_time_utc": start_utc,
            "end_time_utc": end_utc,
            "start_time_local": start_local,
            "end_time_local": end_local,
            "timezone": tz,
            "tz_source": "actual", # Per Strategy B
            "duration_s": int(round(duration_float)) if duration_float is not None else None,
            "distance_m": None,
            "calories_kcal": get_qty(workout_json.get('activeEnergyBurned')),
        }
        
        record['ingest_time_utc'] = datetime.now(timezone.utc)
        record['ingest_run_id'] = ingest_run_id
        
        return record
        
    except Exception as e:
        log.error(f"Failed to process workout {workout_json.get('id')}: {e}", exc_info=True)
        return None

def ingest_hae_workouts(limit: int = None) -> None:
    """
    Ingest HAE workout JSON files from the raw directory.
    """
    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log.info(f"Starting HAE Workout JSON ingestion (run_id={ingest_run_id})")

    files = list(RAW_HAE_JSON_DIR.glob("*.json"))
    if not files:
        log.info(f"No JSON files found in {RAW_HAE_JSON_DIR}")
        return

    all_workouts: List[Dict[str, Any]] = []
    total_processed_files = 0
    
    for f_path in files:
        log.info(f"Processing file: {f_path.name}")
        file_workouts: List[Dict[str, Any]] = []
        try:
            with open(f_path, 'r') as f:
                data = json.load(f)
            
            workouts_list = data.get('data', {}).get('workouts', [])
            
            for workout_json in workouts_list:
                record = process_workout_json(workout_json, ingest_run_id)
                if record:
                    file_workouts.append(record)
                    
            if limit and len(all_workouts) + len(file_workouts) >= limit:
                remaining_needed = limit - len(all_workouts)
                all_workouts.extend(file_workouts[:remaining_needed])
                log.info(f"Reached processing limit ({limit})")
                break
            
            all_workouts.extend(file_workouts)
            
            # --- We archive *after* processing, not before ---
            # _archive_file(f_path) 
            total_processed_files += 1
                
        except Exception as e:
            log.error(f"Failed to read or parse {f_path.name}: {e}", exc_info=True)
    
    if not all_workouts:
        log.info(f"No valid workouts found to ingest from {total_processed_files} files.")
        return
    
    log.info(f"Read {len(all_workouts)} workouts from {total_processed_files} files.")
    
    df = pd.DataFrame(all_workouts)

    # --- THIS IS THE FIX for Duplicates ---
    # Deduplicate the in-memory list BEFORE writing
    log.info(f"Found {len(df)} total workouts in JSON files, deduplicating...")
    df = df.drop_duplicates(subset=["workout_id", "source"], keep="last")
    log.info(f"Deduplicated to {len(df)} unique workouts.")
    # --- END FIX ---
    
    # Ensure schema
    for col in WORKOUTS_SCHEMA.names:
        if col not in df.columns:
            df[col] = None
    df = df[WORKOUTS_SCHEMA.names] # Reorder
    
    # Create partition column - REVERTED TO MONTHLY ('M')
    df = create_date_partition_column(df, "start_time_utc", "date", "M")

    log.info(f"Writing {len(df)} workouts to {WORKOUTS_PATH}")
    
    # Write using upsert logic
    upsert_by_key(
        df,
        WORKOUTS_PATH,
        primary_key=["workout_id", "source"],
        partition_cols=["date", "source"],
        schema=WORKOUTS_SCHEMA,
    )
    
    # --- NOW we can archive the files ---
    # (Only archive if the upsert was successful)
    if not args.debug: # Add a debug flag check if you want
        log.info(f"Archiving {len(files)} processed JSON files...")
        for f_path in files:
             _archive_file(f_path)
    
    log.info("HAE Workout JSON ingestion complete.")

def main():
    global args # Make args global so ingest_hae_workouts can see it
    import argparse
    parser = argparse.ArgumentParser(description="Ingest HAE Workout JSON")
    parser.add_argument("--limit", type=int, default=None, help="Max number of workouts to process")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging (disables archiving)")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
    
    try:
        ingest_hae_workouts(limit=args.limit)
        print("\n✅ HAE Workout ingestion complete.")
    except Exception as e:
        log.exception("Ingestion failed")
        print(f"\n❌ Ingestion failed: {e}")
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())