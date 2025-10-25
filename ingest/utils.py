import pandas as pd
from health_pipeline.common import LOCAL_TIMEZONE_STR

def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns=lambda c: c.strip().lower().replace(' ', '_'))

def convert_to_utc(timestamps: pd.Series, row_indices: pd.Series, local_tz_str: str = LOCAL_TIMEZONE_STR) -> pd.Series:
    ts = pd.to_datetime(timestamps, errors='coerce', utc=False)
    ts = ts.dt.tz_localize(local_tz_str, ambiguous='infer', nonexistent='shift_forward')
    return ts.dt.tz_convert('UTC')
