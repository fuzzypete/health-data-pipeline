#!/usr/bin/env python3
"""
Backfill lactate measurements from existing Concept2 workout comments.

Reads existing workouts parquet files and extracts any lactate readings
from the notes field. Supports single readings and step tests.
"""
from __future__ import annotations

import argparse
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

from pipeline.common.lactate_extraction import extract_lactate_from_workouts
from pipeline.common.parquet_io import upsert_by_key
from pipeline.common.schema import get_schema
from pipeline.paths import WORKOUTS_PATH, LACTATE_PATH, CARDIO_STROKES_PATH

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)


def backfill_lactate_from_concept2_workouts(drop_existing: bool = False):
    """Read all Concept2 workouts and extract lactate measurements."""

    log.info("Starting lactate backfill from Concept2 workouts...")

    # Optionally drop existing lactate data
    if drop_existing and LACTATE_PATH.exists():
        backup_path = LACTATE_PATH.parent / "lactate_backup"
        log.info(f"Backing up existing data to {backup_path}")
        if backup_path.exists():
            shutil.rmtree(backup_path)
        shutil.move(str(LACTATE_PATH), str(backup_path))
        log.info("Existing lactate data moved to backup")

    # Read all Concept2 workouts
    log.info(f"Reading workouts from {WORKOUTS_PATH}")

    try:
        workouts_table = pq.read_table(
            WORKOUTS_PATH,
            filters=[("source", "=", "Concept2")],
        )
        workouts_df = workouts_table.to_pandas()
        log.info(f"Found {len(workouts_df)} Concept2 workouts")
    except Exception as e:
        log.error(f"Failed to read workouts: {e}")
        return

    if workouts_df.empty:
        log.info("No Concept2 workouts found")
        return

    # Load stroke data for step test detection
    strokes_df = None
    try:
        if CARDIO_STROKES_PATH.exists():
            log.info(f"Loading stroke data from {CARDIO_STROKES_PATH}")
            strokes_table = pq.read_table(CARDIO_STROKES_PATH)
            strokes_df = strokes_table.to_pandas()
            log.info(f"Loaded {len(strokes_df)} stroke records")
    except Exception as e:
        log.warning(f"Could not load stroke data: {e}")
        log.warning("Step test detection will be disabled")

    # Extract lactate
    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_backfill")

    lactate_df = extract_lactate_from_workouts(
        workouts_df, ingest_run_id, source="Concept2_Comment", strokes_df=strokes_df
    )

    if lactate_df.empty:
        log.info("No lactate measurements found in comments")
        return

    log.info(f"Extracted {len(lactate_df)} lactate readings")

    # Summary by test type
    if "test_type" in lactate_df.columns:
        type_counts = lactate_df["test_type"].value_counts()
        log.info("  By test type:")
        for test_type, count in type_counts.items():
            log.info(f"    {test_type}: {count}")

    # Write using upsert (date column added in extraction)
    upsert_by_key(
        lactate_df,
        LACTATE_PATH,
        primary_key=["workout_id", "source", "reading_sequence"],
        partition_cols=["date", "source"],
        schema=get_schema("lactate"),
    )

    log.info(f"✅ Backfill complete: {len(lactate_df)} lactate readings written")

    # Summary stats
    log.info("\nLactate Summary:")
    log.info(f"  Total readings: {len(lactate_df)}")
    log.info(f"  Unique workouts: {lactate_df['workout_id'].nunique()}")
    log.info(f"  Mean:  {lactate_df['lactate_mmol'].mean():.2f} mmol/L")
    log.info(f"  Min:   {lactate_df['lactate_mmol'].min():.2f} mmol/L")
    log.info(f"  Max:   {lactate_df['lactate_mmol'].max():.2f} mmol/L")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill lactate from Concept2 comments")
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Drop existing lactate data before backfill (backs up first)",
    )
    args = parser.parse_args()

    backfill_lactate_from_concept2_workouts(drop_existing=args.drop_existing)