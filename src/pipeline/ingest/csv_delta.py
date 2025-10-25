# src/pipeline/ingest/csv_delta.py
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, List
from uuid import uuid4

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

from pipeline.common.schema import SOURCES, minute_facts_base
from pipeline.paths import RAW_CSV_DIR, MINUTE_FACTS_PATH

DEFAULT_INPUT_DIR = RAW_CSV_DIR
DEFAULT_OUTPUT_DIR = MINUTE_FACTS_PATH
DEFAULT_SOURCE = "HAE_CSV"

RENAME_MAP = {
    "Date/Time": "timestamp_local",
    "Steps (count)": "steps",
    "Heart Rate [Avg] (count/min)": "heart_rate_avg",
    "Active Energy (kcal)": "active_energy_kcal",
}

METADATA_COLS = {
    "timestamp_utc",
    "timestamp_local",
    "tz_name",
    "source",
    "ingest_time_utc",
    "ingest_run_id",
}

logging.basicConfig(
    level=os.environ.get("PIPELINE_LOGLEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("csv_delta")

def _load_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()
    df = df.rename(columns=RENAME_MAP)
    return df

def _add_required_fields(df: pd.DataFrame, source_value: str, csv_path: Path, ingest_run_id: str) -> pd.DataFrame:
    if "timestamp_utc" not in df.columns:
        if "timestamp_local" in df.columns:
            df["timestamp_utc"] = pd.to_datetime(df["timestamp_local"], errors="coerce", utc=True)
        elif "timestamp" in df.columns:
            df["timestamp_utc"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        else:
            raise ValueError(f"{csv_path}: expected 'timestamp_utc' or 'timestamp_local'")
    else:
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True)

    if "timestamp_local" in df.columns:
        df["timestamp_local"] = pd.to_datetime(df["timestamp_local"], errors="coerce", utc=False)

    if "tz_name" not in df.columns:
        df["tz_name"] = pd.NA

    df["source"] = source_value
    df["ingest_run_id"] = f"csv-{ingest_run_id}"
    df["ingest_time_utc"] = datetime.now(timezone.utc)

    return df

def _coerce_metric_types(df: pd.DataFrame) -> pd.DataFrame:
    # Coerce likely metric columns; leave non-numeric columns untouched
    metric_cols = [c for c in df.columns if c not in METADATA_COLS]
    for c in metric_cols:
        converted = pd.to_numeric(df[c], errors="coerce")
        # Only adopt conversion if it yielded any numeric values
        if not converted.isna().all():
            df[c] = converted
    return df

def _drop_pk_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    df = df.drop_duplicates(subset=["timestamp_utc", "source"], keep="last")
    after = len(df)
    if after < before:
        log.info("Deduped %d → %d rows on PK (timestamp_utc,source)", before, after)
    return df

def _to_table_with_partitions(df: pd.DataFrame) -> pa.Table:
    for name in ["timestamp_utc", "source", "ingest_time_utc"]:
        if name not in df.columns:
            raise ValueError(f"Missing required column '{name}' before Arrow conversion")
    table = pa.Table.from_pandas(df, preserve_index=False)
    date32 = pa.array(pd.to_datetime(df["timestamp_utc"]).dt.date.astype("datetime64[ns]")).cast(pa.date32())
    table = table.append_column("date", date32)
    return table

def _write_parquet_dataset(table: pa.Table, out_dir: Path) -> None:
    partition_schema = pa.schema([pa.field("date", pa.date32()), pa.field("source", pa.string())])
    ds.write_dataset(
        data=table,
        base_dir=str(out_dir),
        format="parquet",
        partitioning=ds.partitioning(partition_schema, flavor="hive"),
        existing_data_behavior="overwrite_or_ignore",
    )

def process_single_csv(csv_path: Path, out_dir: Path, source_value: str) -> bool:
    try:
        if source_value not in SOURCES:
            raise ValueError(f"Unknown source '{source_value}'. Allowed: {sorted(SOURCES)}")

        ingest_run_id = str(uuid4())
        df = _load_csv(csv_path)
        df = _add_required_fields(df, source_value=source_value, csv_path=csv_path, ingest_run_id=ingest_run_id)
        df = _coerce_metric_types(df)
        df = _drop_pk_duplicates(df)

        table = _to_table_with_partitions(df)
        _write_parquet_dataset(table, out_dir)
        log.info("OK: %s → %s", csv_path.name, out_dir)
        return True
    except Exception as e:
        log.exception("Failed on %s: %s", csv_path, e)
        return False

def discover_csvs(input_dir: Path) -> list[Path]:
    return sorted([p for p in input_dir.glob("*.csv") if p.is_file()])

def run(input_dir: Path, out_dir: Path, source_value: str = DEFAULT_SOURCE) -> int:
    csvs = discover_csvs(input_dir)
    processed = 0
    failed = 0

    if not csvs:
        log.info("No CSV files found in %s", input_dir)
        return 0

    for p in csvs:
        ok = process_single_csv(p, out_dir, source_value)
        processed += int(ok)
        failed += int(not ok)

    log.info("Run complete. Processed=%d Failed=%d", processed, failed)
    return 0 if failed == 0 else 1

def _parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Ingest HAE CSV (wide→wide) to Parquet (Schema v1.2)")
    ap.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR), help=f"CSV directory (default: {DEFAULT_INPUT_DIR})")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR), help=f"Parquet dataset dir (default: {DEFAULT_OUTPUT_DIR})")

    ap.add_argument("--source", default=DEFAULT_SOURCE, choices=sorted(SOURCES), help="Source tag (default: HAE_CSV)")
    return ap.parse_args(argv)

def main(argv: Optional[Iterable[str]] = None) -> None:
    args = _parse_args(argv)
    raise SystemExit(run(Path(args.input_dir), Path(args.out_dir), args.source))

if __name__ == "__main__":
    main()
