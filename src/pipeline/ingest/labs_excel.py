import argparse
import hashlib
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.paths import LABS_PATH, RAW_LABS_DIR

try:
    from pipeline.common.labs_normalization import parse_column_name, parse_lab_value, calculate_flag, get_reference_range
except Exception:
    from src.pipeline.common.labs_normalization import parse_column_name, parse_lab_value, calculate_flag, get_reference_range  # type: ignore



def _hash_lab_id(date_str: str, lab_name: str) -> str:
    base = f"{date_str}__{lab_name}".encode("utf-8")
    return hashlib.sha1(base).hexdigest()[:16]

def read_excel_wide(path: str, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(path,sheet_name=sheet_name)
    df.columns = [str(c).strip() for c in df.columns]
    return df

def melt_to_long(df: pd.DataFrame) -> pd.DataFrame:
    # Locate key columns
    def find_col(cands):
        for c in df.columns:
            if str(c).strip().lower() in cands:
                return c
        return None

    date_col = find_col({"date","collection date","draw date","collected","reported"}) or ("Date" if "Date" in df.columns else None)
    if date_col is None:
        raise ValueError("Date column not found.")

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

    long_df["source"] = Path(DEFAULT_INPUT).name
    long_df["ingest_time_utc"] = pd.Timestamp.utcnow()
    if "ingest_run_id" not in long_df.columns:
        long_df["ingest_run_id"] = None

    cols = ["lab_id","date","lab_name","reason","marker","value","value_text","unit","ref_low","ref_high","flag","source","ingest_time_utc","ingest_run_id","year"]
    return long_df[cols]

def write_parquet(df: pd.DataFrame):
    table = pa.Table.from_pandas(df)
    pq.write_to_dataset(table, root_path=LABS_PATH, partition_cols=["year"])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=None, help="Path to labs Excel file. If not provided, auto-scans for latest Labs fetch in raw data dir.")
    ap.add_argument("--sheet", default="Lab Results", help="Worksheet name or index to read")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    # Determine which file to process
    if args.input:
        input = Path(args.input)
    else:
        # Auto-scan for latest LABS export
        labs_files = list(RAW_LABS_DIR.glob("*.csv"))
        if not labs_files:
            print(f"❌ No Excel files found in {RAW_LABS_DIR}")
            print(f"   Place LABS exports in this directory or specify path explicitly.")
            return 1
        input = max(labs_files, key=lambda p: p.stat().st_mtime)
        log.info(f"Auto-detected latest Labs excel: {input.name}")
    
    if not input.exists():
        print(f"❌ File not found: {input}")
        return 1
    
    df_wide = read_excel_wide(input, sheet_name=args.sheet)
    df_long = melt_to_long(df_wide)
    if args.run_id:
        df_long["ingest_run_id"] = args.run_id
    write_parquet(df_long)
    print(f"Ingestion complete: {len(df_long['lab_id'].unique())} visits, {len(df_long)} results")

if __name__ == "__main__":
    main()