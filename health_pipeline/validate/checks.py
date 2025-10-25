import logging
import pyarrow.dataset as ds
import pandas as pd
from health_pipeline.common import MINUTE_FACTS_PATH

log = logging.getLogger('validate')

def validate_temporal_integrity():
    try:
        dataset = ds.dataset(MINUTE_FACTS_PATH, format='parquet', partitioning='hive')
        df = dataset.to_table().to_pandas()
        if df.empty:
            log.info('No data found for validation.')
            return
        df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'], errors='coerce', utc=True)

        null_utc = df['timestamp_utc'].isna().sum()
        if null_utc:
            log.warning('Null UTC timestamps: %d', null_utc)

        key_cols = [c for c in ['timestamp_utc','source','steps','heart_rate_avg'] if c in df.columns]
        if 'timestamp_utc' not in key_cols:
            key_cols.insert(0,'timestamp_utc')
        dups = df.duplicated(subset=key_cols, keep=False).sum()
        if dups:
            log.warning('Duplicate rows on %s: %d', key_cols, dups)
        else:
            log.info('No duplicates on %s', key_cols)

    except Exception as e:
        log.exception('Validation failed: %s', e)
