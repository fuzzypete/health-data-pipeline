#!/usr/bin/env python3
"""
Backfill lactate measurements from existing Concept2 workout comments.

Reads existing workouts parquet files and extracts any lactate readings
from the notes field.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pyarrow.parquet as pq

from pipeline.common.lactate_extraction import (
    extract_lactate_from_workouts,
    create_lactate_table,
)
from pipeline.common.parquet_io import upsert_by_key, create_date_partition_column
from pipeline.common.schema import get_schema
from pipeline.paths import WORKOUTS_PATH, LACTATE_PATH

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)


def backfill_lactate_from_concept2_workouts():
    """Read all Concept2 workouts and extract lactate measurements."""

    log.info("Starting lactate backfill from Concept2 workouts...")

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

    # Extract lactate
    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_backfill")

    lactate_df = extract_lactate_from_workouts(
        workouts_df, ingest_run_id, source="Concept2_Comment"
    )

    if lactate_df.empty:
        log.info("No lactate measurements found in comments")
        return

    log.info(f"Extracted {len(lactate_df)} lactate measurements")

    # Convert to table and write
    lactate_table = create_lactate_table(lactate_df)
    lactate_table = create_date_partition_column(
        lactate_table, "workout_start_utc", "date"
    )

    upsert_by_key(
        lactate_table,
        LACTATE_PATH,
        primary_key=["workout_id", "source"],
        partition_cols=["date", "source"],
        schema=get_schema("lactate"),
    )

    log.info(f"✅ Backfill complete: {len(lactate_df)} lactate measurements written")

    # Summary stats
    log.info("\nLactate Summary:")
    log.info(f"  Count: {len(lactate_df)}")
    log.info(f"  Mean:  {lactate_df['lactate_mmol'].mean():.2f} mmol/L")
    log.info(f"  Min:   {lactate_df['lactate_mmol'].min():.2f} mmol/L")
    log.info(f"  Max:   {lactate_df['lactate_mmol'].max():.2f} mmol/L")
    log.info(
        f"  Date range: {lactate_df['date'].min()} to {lactate_df['date'].max()}"
    )


if __name__ == "__main__":
    backfill_lactate_from_concept2_workouts()
