import pyarrow as pa
from zoneinfo import ZoneInfo
LOCAL_TIMEZONE_STR='America/Los_Angeles'
LOCAL_TIMEZONE=ZoneInfo(LOCAL_TIMEZONE_STR)
UTC_TIMEZONE=ZoneInfo('UTC')
PARQUET_COMPRESSION='snappy'
DATA_RAW_CSV_DIR='Data/Raw/CSV'
DATA_RAW_JSON_DIR='Data/Raw/JSON'
DATA_PARQUET_DIR='Data/Parquet'
DATA_ARCHIVE_CSV_DIR='Data/Archive/CSV'
DATA_ARCHIVE_JSON_DIR='Data/Archive/JSON'
MINUTE_FACTS_PATH=f"{DATA_PARQUET_DIR}/minute_facts"
DAILY_SUMMARY_PATH=f"{DATA_PARQUET_DIR}/daily_summary"
WORKOUTS_PATH=f"{DATA_PARQUET_DIR}/workouts"
minute_facts_schema=pa.schema([
 ('source_row_index', pa.int64()),
 ('timestamp_utc', pa.timestamp('us', tz='UTC')),
 ('timestamp_local', pa.timestamp('us')),
 ('source', pa.string()),
 ('steps', pa.int32()),
 ('heart_rate_min', pa.int32()),
 ('heart_rate_max', pa.int32()),
 ('heart_rate_avg', pa.int32()),
 ('active_energy_kcal', pa.float64()),
])
