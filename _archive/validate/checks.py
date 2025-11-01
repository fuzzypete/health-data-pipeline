import logging
import pyarrow.dataset as ds
import pandas as pd
from pipeline.common import MINUTE_FACTS_PATH
log = logging.getLogger(__name__)

def validate_temporal_integrity():
    try:
        dataset = ds.dataset(MINUTE_FACTS_PATH, format='parquet', partitioning='hive')
        df = dataset.to_table().to_pandas()
        df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'], errors='coerce', utc=True)
        if df['timestamp_utc'].isnull().any():
            log.warning("Null UTC timestamps found")
        if not df['timestamp_utc'].is_monotonic_increasing:
            log.warning("Non-monotonic UTC timestamps detected")
        log.info("Validation completed (basic).")
    except Exception as e:
        log.exception("Validation failed: %s", e)
