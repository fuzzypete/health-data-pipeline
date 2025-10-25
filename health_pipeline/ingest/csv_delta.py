import os, glob, logging, shutil
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime

from health_pipeline.common import (
    DATA_RAW_CSV_DIR, MINUTE_FACTS_PATH, DATA_ARCHIVE_CSV_DIR, DATA_PARQUET_DIR,
    minute_facts_schema, PARQUET_COMPRESSION
)
from health_pipeline.ingest.utils import clean_column_names, convert_to_utc

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger('ingest.csv')

def _write_dataset(table: pa.Table, root_path: str, partition_cols: list[str]):
    pq.write_to_dataset(
        table,
        root_path=root_path,
        partition_cols=partition_cols,
        existing_data_behavior='overwrite_or_ignore',
        compression=PARQUET_COMPRESSION
    )

def _extract_and_write_daily_summary(df: pd.DataFrame):
    if 'timestamp_utc' not in df.columns or df['timestamp_utc'].isna().all():
        log.info('No timestamp_utc available; skipping daily summary.')
        return
    g = df.copy()
    g['date'] = g['timestamp_utc'].dt.date

    aggs = {}
    if 'steps' in g.columns:
        aggs['total_steps'] = ('steps', 'sum')
    if 'active_energy_kcal' in g.columns:
        aggs['total_active_energy_kcal'] = ('active_energy_kcal', 'sum')
    if 'heart_rate_avg' in g.columns:
        aggs['hr_avg'] = ('heart_rate_avg', 'mean')

    if not aggs:
        log.info('No summary-compatible columns present; skipping daily summary.')
        return

    summary = g.groupby('date').agg(**aggs).reset_index()
    summary['date'] = pd.to_datetime(summary['date']).dt.date.astype(str)
    table = pa.Table.from_pandas(summary, preserve_index=False)
    pq.write_to_dataset(
        table,
        root_path=f"{DATA_PARQUET_DIR}/daily_summary",
        partition_cols=['date'],
        existing_data_behavior='overwrite_or_ignore',
        compression=PARQUET_COMPRESSION
    )
    log.info('Wrote daily summary partitions for %d day(s).', len(summary))

def process_single_csv(csv_path: str) -> bool:
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            return True
        df['source_row_index'] = df.index

        dt_col = next((c for c in df.columns if c.lower() in ('date/time','date_time','datetime','timestamp')), None)
        if not dt_col:
            log.warning('No timestamp column found in %s', csv_path)
            return True

        df['timestamp_local'] = pd.to_datetime(df[dt_col], errors='coerce')
        df = df.dropna(subset=['timestamp_local'])
        df['timestamp_utc'] = convert_to_utc(df['timestamp_local'], df['source_row_index'])

        df = clean_column_names(df)
        df['date_utc'] = df['timestamp_utc'].dt.date.astype(str)

        cols = [f.name for f in minute_facts_schema if f.name in df.columns]
        for must in ['timestamp_utc','timestamp_local','source_row_index']:
            if must not in cols and must in df.columns:
                cols.append(must)

        table = pa.Table.from_pandas(df[cols], schema=minute_facts_schema, preserve_index=False)
        _write_dataset(table, MINUTE_FACTS_PATH, ['date_utc'])

        _extract_and_write_daily_summary(df)

        log.info("Processed %s rows from %s", len(df), os.path.basename(csv_path))
        return True
    except Exception as e:
        log.exception("Failed on %s: %s", csv_path, e)
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

def move_to_error(filepath: str, error_root: str):
    if not os.path.exists(filepath):
        return
    today = datetime.now().strftime('%Y-%m-%d')
    target_dir = os.path.join(error_root, today)
    os.makedirs(target_dir, exist_ok=True)
    base = os.path.basename(filepath)
    target = os.path.join(target_dir, base)
    counter = 1
    name, ext = os.path.splitext(target)
    while os.path.exists(target):
        target = f"{name}_{counter}{ext}"
        counter += 1
    shutil.move(filepath, target)

def main():
    files = sorted(glob.glob(os.path.join(DATA_RAW_CSV_DIR, "*.csv")))
    if not files:
        log.info("No CSV files found.")
        return
    ok, fail = 0, 0
    for f in files:
        if process_single_csv(f):
            archive_file(f, DATA_ARCHIVE_CSV_DIR)
            ok += 1
        else:
            move_to_error(f, os.path.join('Data','Error','CSV'))
            fail += 1
    log.info("Run complete. Processed=%d Failed=%d", ok, fail)

if __name__ == "__main__":
    main()
