import os, glob, logging
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime
from pipeline.common.schema import SOURCES, minute_facts_base
from pipeline.paths import MINUTE_FACTS_PATH
from pipeline.ingest.utils import clean_column_names, convert_to_utc
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def process_single_csv(csv_path: str) -> bool:
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            return True
        df['source_row_index'] = df.index
        dt_col = next((c for c in df.columns if c.lower() in ('date/time','date_time','datetime','timestamp')), None)
        if not dt_col:
            logging.warning('No timestamp column found in %s', csv_path)
            return True
        df['timestamp_local'] = pd.to_datetime(df[dt_col], errors='coerce')
        df = df.dropna(subset=['timestamp_local'])
        df['timestamp_utc'] = convert_to_utc(df['timestamp_local'], df['source_row_index'])
        df['date_utc'] = df['timestamp_utc'].dt.date.astype(str)
        df = clean_column_names(df)
        cols = [f.name for f in minute_facts_schema if f.name in df.columns]
        for must in ['timestamp_utc','timestamp_local','source_row_index']:
            if must not in cols and must in df.columns:
                cols.append(must)
        table = pa.Table.from_pandas(df[cols], schema=minute_facts_schema, preserve_index=False)
        pq.write_to_dataset(table, root_path=MINUTE_FACTS_PATH, partition_cols=['date_utc'], existing_data_behavior='overwrite_or_ignore', compression=PARQUET_COMPRESSION)
        logging.info("Processed %s rows from %s", len(df), os.path.basename(csv_path))
        return True
    except Exception as e:
        logging.exception("Failed on %s: %s", csv_path, e)
        return False

def archive_file(filepath: str, archive_root: str):
    if not os.path.exists(filepath):
        return
    today = datetime.now().strftime('%Y-%m-%d')
    target_dir = os.path.join(archive_root, today)
    os.makedirs(target_dir, exist_ok=True)
    base = os.path.basename(filepath)
    target = os.path.join(target_dir, base)
    counter = 1
    name, ext = os.path.splitext(target)
    while os.path.exists(target):
        target = f"{name}_{counter}{ext}"
        counter += 1
    os.rename(filepath, target)

def main():
    files = sorted(glob.glob(os.path.join(DATA_RAW_CSV_DIR, "*.csv")))
    if not files:
        logging.info("No CSV files found.")
        return
    ok, fail = 0, 0
    for f in files:
        if process_single_csv(f):
            archive_file(f, DATA_ARCHIVE_CSV_DIR)
            ok += 1
        else:
            fail += 1
    logging.info("Run complete. Processed=%d Failed=%d", ok, fail)

if __name__ == "__main__":
    main()
