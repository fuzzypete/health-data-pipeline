#!/usr/bin/env python3
"""
Ingest Protocol History from the master Excel file.

Reads config.yaml for default input path and sheet name ("Events"),
parses the data, adds lineage, and writes to the 'protocol_history' table.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa

# Add src to path to allow imports from pipeline.common
sys.path.append(str(Path(__file__).parent.parent.parent))

from pipeline.common.parquet_io import (
    add_lineage_fields,
    create_date_partition_column,
    write_partitioned_dataset,
)
from pipeline.common.schema import get_schema
from pipeline.common.config import get_drive_source
from pipeline.paths import PROTOCOL_HISTORY_PATH, RAW_ROOT

log = logging.getLogger("ingest_protocol_excel")

def _hash_protocol_id(
    start_date: str, compound: str, dosage: str, unit: str
) -> str:
    """Create a stable, unique ID for the protocol entry."""
    start_str = str(start_date)
    # Use str() to handle None/NaN values gracefully in the hash
    base = f"{start_str}__{str(compound)}__{str(dosage)}__{str(unit)}".encode(
        "utf-8"
    )
    return hashlib.sha1(base).hexdigest()[:16]


def read_protocol_sheet(input_path: Path, sheet_name: str) -> pd.DataFrame:
    """Read the protocol data from the specified Excel sheet."""
    if not input_path.exists():
        log.error(f"Input file not found: {input_path}")
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # --- THIS IS THE FIX ---
    # The variable is 'input_path', not 'input_file'
    log.info(f"Reading protocols from '{input_path.name}' (Sheet: '{sheet_name}')...")
    # --- END FIX ---
    
    df = pd.read_excel(input_path, sheet_name=sheet_name)
    # Normalize all column names
    df.columns = [str(c).lower().strip() for c in df.columns]
    return df


def process_protocols(
    df: pd.DataFrame, source_name: str, ingest_run_id: str
) -> pd.DataFrame:
    """Clean, normalize, and add metadata to the protocol data."""

    schema = get_schema("protocol_history")
    expected_cols = [
        f.name
        for f in schema
        if f.name
        not in ["protocol_id", "source", "ingest_time_utc", "ingest_run_id", "year"]
    ]

    # More comprehensive rename map
    rename_map = {
        "start": "start_date",
        "start date": "start_date",
        "end": "end_date",
        "end date": "end_date",
        "compound": "compound_name",
        "compound name": "compound_name",
        "type": "compound_type",
        "compound type": "compound_type",
        "unit": "dosage_unit",
        "dosage unit": "dosage_unit",
    }
    df = df.rename(columns=rename_map)


    for col in expected_cols:
        if col not in df.columns:
            log.warning(
                f"Column '{col}' not found in Excel sheet. Adding as empty column."
            )
            df[col] = None

    # Parse dates
    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce").dt.date
    df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce").dt.date

    # Drop rows where essential columns are missing
    invalid_start = df["start_date"].isna().sum()
    if invalid_start > 0:
        log.warning(f"Dropping {invalid_start} rows with missing or invalid start_date")
        df = df.dropna(subset=["start_date"])

    invalid_compound = df["compound_name"].isna().sum()
    if invalid_compound > 0:
        log.warning(
            f"Dropping {invalid_compound} rows with missing or invalid compound_name"
        )
        df = df.dropna(subset=["compound_name"])

    if df.empty:
        return pd.DataFrame()

    # Create protocol_id
    df["protocol_id"] = df.apply(
        lambda r: _hash_protocol_id(
            str(r["start_date"]),
            r["compound_name"],
            r["dosage"],
            r["dosage_unit"],
        ),
        axis=1,
    )

    # Add lineage
    df = add_lineage_fields(df, source=source_name, ingest_run_id=ingest_run_id)

    # Add partition column (by year of start_date)
    df_part = create_date_partition_column(df.copy(), "start_date", "date_str", "D")
    df["year"] = pd.to_datetime(df_part["date_str"], errors='coerce').dt.year.astype(str)

    # Select and reorder columns to match schema
    df = df[[f.name for f in schema]]

    log.info(f"Processed {len(df)} protocol records")
    return df


def main():
    # --- Get defaults from config.yaml ---
    protocol_config = get_drive_source("protocols")
    if not protocol_config:
        log.error("Missing 'protocols' section in config.yaml drive_sources")
        sys.exit(1)

    default_path = Path(
        protocol_config.get(
            "output_path", "Data/Raw/labs/protocols-master-latest.xlsx"
        )
    )
    default_sheet = protocol_config.get("sheet_name", "Events")
    # --- End config load ---

    parser = argparse.ArgumentParser(
        description="Ingest Protocol History from Excel sheet."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=default_path,
        help=f"Path to the downloaded protocol Excel file. Default: {default_path}",
    )
    parser.add_argument(
        "--sheet",
        default=default_sheet,
        help=f"Name of the sheet in the Excel file to read. Default: {default_sheet}",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger("pipeline").setLevel(logging.DEBUG)

    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    try:
        # Resolve the path from the project root (where make is run)
        input_file = Path(args.input).resolve()

        df_raw = read_protocol_sheet(input_file, args.sheet)
        df_processed = process_protocols(df_raw, input_file.name, ingest_run_id)

        if df_processed.empty:
            log.info("No valid protocol records found. Nothing to write.")
            return

        table = pa.Table.from_pandas(
            df_processed, schema=get_schema("protocol_history"), preserve_index=False
        )

        write_partitioned_dataset(
            table,
            PROTOCOL_HISTORY_PATH,
            partition_cols=["year"],
            schema=get_schema("protocol_history"),
            mode="delete_matching",  # Overwrite partition
        )
        log.info(f"✅ Successfully wrote {len(df_processed)} protocol records.")

    except Exception as e:
        log.exception(f"Protocol ingestion failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if not log.handlers:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s [%(levelname)-7s] %(message)s"
        )
    main()