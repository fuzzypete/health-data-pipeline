import argparse
import hashlib
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Add src to path to allow imports from pipeline.common
sys.path.append(str(Path(__file__).parent.parent.parent))

from pipeline.paths import LABS_PATH, RAW_ROOT
from pipeline.common.schema import get_schema
from pipeline.common.config import get_drive_source
from pipeline.common.parquet_io import write_partitioned_dataset

try:
    from pipeline.common.labs_normalization import parse_column_name, parse_lab_value, calculate_flag, get_reference_range
except Exception:
    from src.pipeline.common.labs_normalization import parse_column_name, parse_lab_value, calculate_flag, get_reference_range  # type: ignore

log = logging.getLogger("ingest_labs_excel")


def _hash_lab_id(date_str: str, lab_name: str) -> str:
    base = f"{date_str}__{lab_name}".encode("utf-8")
    return hashlib.sha1(base).hexdigest()[:16]

def read_excel_wide(input_path: Path, sheet_name: str) -> pd.DataFrame:
    """Read the labs data from the specified Excel sheet."""
    if not input_path.exists():
        log.error(f"Input file not found: {input_path}")
        raise FileNotFoundError(f"Input file not found: {input_path}")
        
    log.info(f"Reading labs from '{input_path.name}' (Sheet: '{sheet_name}')...")
    df = pd.read_excel(input_path, sheet_name=sheet_name)
    df.columns = [str(c).strip() for c in df.columns]
    return df

def melt_to_long(df: pd.DataFrame, source: str, ingest_run_id: str) -> pd.DataFrame:
    """Melt the wide labs format to a long format."""
    
    # Locate key columns
    def find_col(cands):
        for c in df.columns:
            if str(c).strip().lower() in cands:
                return c
        return None

    date_col = find_col({"date","collection date","draw date","collected","reported"}) or ("Date" if "Date" in df.columns else None)
    if date_col is None:
        raise ValueError("Date column not found in Excel sheet.")

    lab_col = find_col({"lab","lab name","provider","vendor"})
    reason_col = find_col({"reason","order reason","notes (visit)"})

    id_cols = [date_col] + ([lab_col] if lab_col else []) + ([reason_col] if reason_col else [])
    value_cols = [c for c in df.columns if c not in id_cols]

    long_df = df.melt(id_vars=id_cols, value_vars=value_cols, var_name="marker_col", value_name="raw_value")
    long_df.rename(columns={date_col:"date"}, inplace=True)
    if lab_col: long_df.rename(columns={lab_col:"lab_name"}, inplace=True)
    if reason_col: long_df.rename(columns={reason_col:"reason"}, inplace=True)

    long_df[["marker","unit_from_col"]] = long_df["marker_col"].apply(lambda c: pd.Series(parse_column_name(str(c))))
    parsed = long_df["raw_value"].apply(parse_lab_value)
    long_df["value"] = parsed.apply(lambda t: t[0])
    long_df["value_text"] = parsed.apply(lambda t: t[1])
    long_df["flag_from_parse"] = parsed.apply(lambda t: t[2])

    refs = long_df["marker"].apply(get_reference_range)
    long_df["ref_low"] = refs.apply(lambda t: t[0])
    long_df["ref_high"] = refs.apply(lambda t: t[1])
    long_df["flag"] = [
        calculate_flag(v, lo, hi, f)
        for v, lo, hi, f in zip(long_df["value"], long_df["ref_low"], long_df["ref_high"], long_df["flag_from_parse"])
    ]

    long_df["unit"] = long_df["unit_from_col"]
    long_df["date"] = pd.to_datetime(long_df["date"]).dt.date
    long_df = long_df[~(long_df["value"].isna() & long_df["value_text"].isna())].copy()

    long_df["lab_name"] = long_df.get("lab_name", pd.Series([None]*len(long_df))).fillna("")
    long_df["lab_id"] = long_df.apply(lambda r: _hash_lab_id(str(r["date"]), str(r["lab_name"])), axis=1)
    long_df["year"] = pd.to_datetime(long_df["date"]).dt.year.astype(str)

    long_df["source"] = source
    long_df["ingest_time_utc"] = pd.Timestamp.utcnow()
    long_df["ingest_run_id"] = ingest_run_id

    # Select and reorder columns to match schema
    schema = get_schema("labs")
    long_df = long_df[[f.name for f in schema]]
    
    return long_df

def main():
    # --- Get defaults from config.yaml ---
    labs_config = get_drive_source("labs")
    if not labs_config:
        log.error("Missing 'labs' section in config.yaml drive_sources")
        sys.exit(1)

    default_path = Path(
        labs_config.get(
            "output_path", "Data/Raw/labs/labs-master-latest.xlsx"
        )
    )
    default_sheet = labs_config.get("sheet_name", "Lab Results")
    # --- End config load ---

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--input",
        type=Path,
        default=default_path,
        help=f"Path to labs Excel file. Default: {default_path}"
    )
    ap.add_argument(
        "--sheet", 
        default=default_sheet, 
        help=f"Worksheet name to read. Default: {default_sheet}"
    )
    ap.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = ap.parse_args()
    
    if args.debug:
        logging.getLogger("pipeline").setLevel(logging.DEBUG)

    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    try:
        # Resolve the path from the project root (where make is run)
        input_file = Path(args.input).resolve()
        
        df_wide = read_excel_wide(input_file, sheet_name=args.sheet)
        df_long = melt_to_long(df_wide, input_file.name, ingest_run_id)

        if df_long.empty:
            log.info("No valid lab records found. Nothing to write.")
            return

        table = pa.Table.from_pandas(
            df_long, schema=get_schema("labs"), preserve_index=False
        )
        
        write_partitioned_dataset(
            table, 
            table_path=LABS_PATH, 
            partition_cols=["year"],
            schema=get_schema("labs"),
            mode="delete_matching" # Overwrite partitions
        )
        log.info(f"✅ Ingestion complete: {len(df_long['lab_id'].unique())} visits, {len(df_long)} results")

    except Exception as e:
        log.exception(f"Labs ingestion failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if not log.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)-7s] %(message)s"
        )
    main()