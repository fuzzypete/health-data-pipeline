import pandas as pd
from health_pipeline.common import LOCAL_TIMEZONE_STR

_EXPLICIT_MAP = {
    'Active Energy (kcal)': 'active_energy_kcal',
    'Steps (count)': 'steps',
    'Heart Rate [Avg] (count/min)': 'heart_rate_avg',
    'Heart Rate [Min] (count/min)': 'heart_rate_min',
    'Heart Rate [Max] (count/min)': 'heart_rate_max',
}

def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=_EXPLICIT_MAP, errors='ignore')
    df = df.rename(columns=lambda c: c.strip().lower().replace(' ', '_').replace('/', '_').replace('[', '').replace(']', '').replace('(', '').replace(')', ''))
    return df

def convert_to_utc(timestamps: pd.Series, row_indices: pd.Series, local_tz_str: str = LOCAL_TIMEZONE_STR) -> pd.Series:
    ts = pd.to_datetime(timestamps, errors='coerce', utc=False)
    out = []
    last_valid_utc = None
    for t in ts:
        if pd.isna(t):
            out.append(pd.NaT); continue
        try:
            loc = pd.Timestamp(t).tz_localize(local_tz_str, ambiguous='raise', nonexistent='raise')
            utc = loc.tz_convert('UTC')
        except Exception:
            cand = []
            for is_dst in (True, False):
                try:
                    loc = pd.Timestamp(t).tz_localize(local_tz_str, ambiguous=is_dst)
                    cand.append(loc.tz_convert('UTC'))
                except Exception:
                    pass
            if cand and last_valid_utc is not None:
                target = last_valid_utc + pd.Timedelta(minutes=1)
                utc = sorted(cand, key=lambda x: abs((x - target).total_seconds()))[0]
            elif cand:
                utc = cand[0]
            else:
                utc = pd.NaT
        out.append(utc)
        if pd.notna(utc):
            last_valid_utc = utc
    return pd.Series(out, index=ts.index, dtype='datetime64[ns, UTC]')
