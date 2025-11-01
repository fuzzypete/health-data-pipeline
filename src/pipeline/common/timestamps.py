"""
Timestamp handling utilities for Health Data Pipeline.

Implements Strategy A (assumed timezone) and Strategy B (rich timezone)
as specified in docs/TimestampHandling.md.
"""
from __future__ import annotations

import logging
from typing import Tuple
from zoneinfo import ZoneInfo

import pandas as pd

log = logging.getLogger(__name__)

# Default home timezone for Strategy A
DEFAULT_HOME_TIMEZONE = "America/Los_Angeles"


def apply_strategy_a(
    df: pd.DataFrame,
    timestamp_col: str = "timestamp_local",
    home_timezone: str = DEFAULT_HOME_TIMEZONE,
) -> pd.DataFrame:
    """
    Strategy A: Assumed Timezone Ingestion (for lossy sources).
    
    Use for: HAE CSV, HAE Daily JSON → minute_facts, daily_summary
    
    Ignores any timezone info in source data and assumes home timezone consistently.
    This creates consistent data where 95% (home days) is perfect and 5% (travel days)
    is knowingly wrong but consistent.
    
    Args:
        df: DataFrame with timestamp column (as string or naive datetime)
        timestamp_col: Name of column containing timestamps
        home_timezone: IANA timezone to assume (e.g., "America/Los_Angeles")
        
    Returns:
        DataFrame with added columns:
        - timestamp_local: naive timestamp (for Parquet storage)
        - timestamp_utc: UTC timestamp
        - tz_name: timezone name used
        - tz_source: 'assumed'
        
    Modifies the input dataframe in place and returns it.
    """
    # 1. Parse timestamp as naive (ignore any timezone in source)
    if timestamp_col not in df.columns:
        raise ValueError(f"Column '{timestamp_col}' not found in dataframe")
    
    df[timestamp_col] = pd.to_datetime(df[timestamp_col], errors='coerce')
    
    # Drop rows with invalid timestamps
    null_count = df[timestamp_col].isna().sum()
    if null_count > 0:
        log.warning(f"Strategy A: Dropping {null_count} rows with invalid timestamps")
        df = df.dropna(subset=[timestamp_col])
    
    # 2. Localize to assumed home timezone (handles DST correctly)
    tz = ZoneInfo(home_timezone)
    df[timestamp_col] = df[timestamp_col].dt.tz_localize(
        tz,
        ambiguous='infer',           # DST fall-back: use context to infer
        nonexistent='shift_forward'  # DST spring-forward: shift to valid time
    )
    
    # 3. Convert to UTC for pipeline operations
    df['timestamp_utc'] = df[timestamp_col].dt.tz_convert('UTC')
    
    # 4. Store timezone metadata
    df['tz_name'] = home_timezone
    df['tz_source'] = 'assumed'
    
    # 5. Convert local back to naive for Parquet storage
    df[timestamp_col] = df[timestamp_col].dt.tz_localize(None)
    
    log.debug(f"Strategy A applied: {len(df)} rows, timezone={home_timezone}")
    
    return df


def apply_strategy_b(
    timestamp_str: str,
    tz_name: str,
) -> Tuple[pd.Timestamp, pd.Timestamp, str]:
    """
    Strategy B: Rich Timezone Ingestion (for high-quality sources).
    
    Use for: HAE Workout JSON, Concept2 API, JEFIT CSV → workouts, splits, strokes, sets
    
    Trusts the per-event timezone from source (it's correct for these sources).
    Returns 100% accurate timestamps including on travel days.
    
    Args:
        timestamp_str: Timestamp string (e.g., "2025-10-30 13:58:00")
        tz_name: IANA timezone name (e.g., "America/Los_Angeles")
        
    Returns:
        Tuple of (timestamp_utc, timestamp_local_naive, tz_name):
        - timestamp_utc: pd.Timestamp in UTC
        - timestamp_local_naive: pd.Timestamp with no timezone (for Parquet)
        - tz_name: The timezone name passed in
        
    Example:
        utc, local, tz = apply_strategy_b("2025-10-30 13:58:00", "America/Los_Angeles")
        workout_record = {
            'start_time_utc': utc,
            'start_time_local': local,
            'timezone': tz,
            'tz_source': 'actual'
        }
    """
    # 1. Parse timestamp as naive
    timestamp_local = pd.to_datetime(timestamp_str)
    
    # 2. Localize to actual timezone from source
    tz = ZoneInfo(tz_name)
    timestamp_local = timestamp_local.tz_localize(
        tz,
        ambiguous='infer',
        nonexistent='shift_forward'
    )
    
    # 3. Convert to UTC
    timestamp_utc = timestamp_local.tz_convert('UTC')
    
    # 4. Create naive local timestamp for Parquet
    timestamp_local_naive = timestamp_local.tz_localize(None)
    
    return timestamp_utc, timestamp_local_naive, tz_name


def handle_dst_ambiguous(
    timestamp: pd.Timestamp,
    timezone: ZoneInfo,
    prefer: str = 'earlier'
) -> pd.Timestamp:
    """
    Handle ambiguous timestamps during DST fall-back.
    
    During fall-back (e.g., Nov 3, 2024 in America/Los_Angeles), 
    times like 01:30 AM happen twice (first in PDT, then in PST).
    
    Args:
        timestamp: Naive timestamp
        timezone: ZoneInfo object
        prefer: 'earlier' (first occurrence) or 'later' (second occurrence)
        
    Returns:
        Localized timestamp with ambiguity resolved
    """
    try:
        return timestamp.tz_localize(
            timezone,
            ambiguous=(prefer == 'earlier'),
            nonexistent='shift_forward'
        )
    except Exception as e:
        log.error(f"DST handling failed for {timestamp} in {timezone}: {e}")
        raise


def validate_timezone(tz_name: str) -> bool:
    """
    Validate that a timezone name is valid IANA timezone.
    
    Args:
        tz_name: Timezone name to validate
        
    Returns:
        True if valid, False otherwise
    """
    try:
        ZoneInfo(tz_name)
        return True
    except Exception:
        return False


def get_dst_transitions(
    timezone: str,
    year: int
) -> Tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """
    Get DST transition timestamps for a given timezone and year.
    
    Args:
        timezone: IANA timezone name
        year: Year to check
        
    Returns:
        Tuple of (spring_forward, fall_back) timestamps in UTC.
        Returns (None, None) if timezone doesn't observe DST.
        
    Example:
        >>> spring, fall = get_dst_transitions("America/Los_Angeles", 2024)
        >>> print(spring)  # 2024-03-10 10:00:00+00:00 (2 AM PST → 3 AM PDT)
        >>> print(fall)    # 2024-11-03 09:00:00+00:00 (2 AM PDT → 1 AM PST)
    """
    tz = ZoneInfo(timezone)
    
    # Check a range of dates to find transitions
    dates = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq='D', tz=tz)
    offsets = dates.map(lambda d: d.utcoffset())
    
    # Find where offset changes
    transitions = []
    for i in range(1, len(offsets)):
        if offsets[i] != offsets[i-1]:
            transitions.append(dates[i])
    
    if len(transitions) == 0:
        return None, None
    elif len(transitions) == 2:
        # Determine which is spring forward vs fall back
        if offsets[0] < offsets[1]:
            return transitions[0], transitions[1]  # spring, fall
        else:
            return transitions[1], transitions[0]  # fall, spring
    else:
        log.warning(f"Unexpected DST pattern in {timezone} for {year}: {len(transitions)} transitions")
        return None, None


# Convenience function for bulk Strategy A application
def bulk_apply_strategy_a(
    dfs: list[pd.DataFrame],
    timestamp_col: str = "timestamp_local",
    home_timezone: str = DEFAULT_HOME_TIMEZONE,
) -> list[pd.DataFrame]:
    """
    Apply Strategy A to multiple DataFrames at once.
    
    Useful when processing multiple CSV files in batch.
    """
    return [apply_strategy_a(df, timestamp_col, home_timezone) for df in dfs]
