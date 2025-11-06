"""
Lactate measurement extraction utilities.

Extracts lactate readings from comment fields (primarily Concept2).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import pyarrow as pa

from pipeline.common.schema import get_schema


def extract_lactate_from_comment(comment: str) -> float | None:
    """
    Extract lactate reading from comment text.
    
    Handles patterns like:
    - Bare numbers: "2.1"
    - With text: "Lactate 2.1"
    - Reversed: "1.7 lactate"
    - With punctuation: "Lactate 2.9!"
    - With context: "2.5 lactate . Later . Full fasted"
    
    Args:
        comment: Comment text to parse
        
    Returns:
        Lactate value in mmol/L, or None if not found
    """
    if not comment or not isinstance(comment, str):
        return None
    
    comment = comment.strip()
    
    # First try: bare number (most common in Concept2 CSV)
    # If comment is just a number (possibly with leading/trailing whitespace)
    if re.match(r'^\d+\.?\d*$', comment):
        try:
            value = float(comment)
            # Sanity check: lactate typically 0.5-20 mmol/L
            if 0.1 <= value <= 25.0:
                return value
        except ValueError:
            pass
    
    # Second try: text with "lactate" keyword
    patterns = [
        r'lactate\s+(\d+\.?\d*)',  # "Lactate 2.1"
        r'(\d+\.?\d*)\s+lactate',  # "2.1 lactate"
    ]
    
    comment_lower = comment.lower()
    
    for pattern in patterns:
        match = re.search(pattern, comment_lower)
        if match:
            try:
                value = float(match.group(1))
                # Sanity check: lactate typically 0.5-20 mmol/L
                if 0.1 <= value <= 25.0:
                    return value
            except (ValueError, IndexError):
                continue
    
    return None


def extract_lactate_from_workouts(
    workouts_df: pd.DataFrame,
    ingest_run_id: str,
    source: str = "Concept2_Comment",
) -> pd.DataFrame:
    """
    Extract lactate measurements from workout comments.
    
    Args:
        workouts_df: DataFrame with columns: date, workout_id, start_time_utc, notes
        ingest_run_id: Ingestion run identifier
        source: Data source identifier
        
    Returns:
        DataFrame with lactate measurements (may be empty)
    """
    if workouts_df.empty or 'notes' not in workouts_df.columns:
        return pd.DataFrame()
    
    records = []
    now_utc = datetime.now(timezone.utc)
    
    for _, row in workouts_df.iterrows():
        lactate = extract_lactate_from_comment(row.get('notes'))
        
        if lactate is not None:
            # Use workout end time as measurement time (most lactate readings are post-workout)
            measurement_time = row.get('end_time_utc') or row['start_time_utc']
            
            records.append({
                'workout_id': row['workout_id'],
                'workout_start_utc': row['start_time_utc'],
                'lactate_mmol': lactate,
                'measurement_time_utc': measurement_time,
                'measurement_context': 'post-workout',
                'notes': row.get('notes'),
                'source': source,
                'ingest_time_utc': now_utc,
                'ingest_run_id': ingest_run_id,
            })
    
    if not records:
        return pd.DataFrame()
    
    df = pd.DataFrame(records)
    
    return df


def create_lactate_table(lactate_df: pd.DataFrame) -> pa.Table:
    """
    Convert lactate DataFrame to PyArrow Table with schema validation.
    
    Args:
        lactate_df: Lactate measurements DataFrame
        
    Returns:
        PyArrow Table
    """
    if lactate_df.empty:
        return pa.table({}, schema=get_schema('lactate'))
    
    # Ensure schema compliance
    schema = get_schema('lactate')
    table = pa.Table.from_pandas(lactate_df, schema=schema, preserve_index=False)
    
    return table
