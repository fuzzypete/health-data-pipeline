"""
JEFIT CSV ingestion.

Parses JEFIT export CSV and ingests into:
- workouts (session summary)
- resistance_sets (set-level data)

TIMESTAMPING: JEFIT exports provide naive timestamps. Per documentation,
this source uses Strategy A (assumed home timezone).

PARTITIONING: This table uses upsert_by_key(), which rewrites the entire
dataset. To avoid 'Too many open files' errors, this table
is partitioned MONTHLY ('M'), not daily.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from pipeline.common import apply_strategy_a, get_schema, get_home_timezone
from pipeline.common.parquet_io import (
    add_lineage_fields,
    create_date_partition_column,
    upsert_by_key,
)
from pipeline.paths import WORKOUTS_PATH, RESISTANCE_SETS_PATH, RAW_JEFIT_DIR

log = logging.getLogger(__name__)


def parse_jefit_csv(csv_path: Path) -> dict[str, pd.DataFrame]:
    """
    Parse JEFIT CSV into section DataFrames.
    
    JEFIT exports multiple sections in one CSV, each with ### headers.
    
    Returns:
        Dict mapping section name to DataFrame
    """
    sections = {}
    current_section = None
    section_lines = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            
            # Check for section header
            if line.startswith('###'):
                # Save previous section
                if current_section and section_lines:
                    df = _parse_section(section_lines)
                    if df is not None and not df.empty:
                        sections[current_section] = df
                
                # Start new section
                match = re.search(r'### ([A-Z\s]+) #', line)
                if match:
                    current_section = match.group(1).strip().replace(' ', '_')
                    section_lines = []
            
            elif line and not line.startswith('#'):
                section_lines.append(line)
        
        # Save last section
        if current_section and section_lines:
            df = _parse_section(section_lines)
            if df is not None and not df.empty:
                sections[current_section] = df
    
    log.info(f"Parsed {len(sections)} sections from JEFIT CSV")
    return sections


def _parse_section(lines: list[str]) -> Optional[pd.DataFrame]:
    """Parse a section's lines into DataFrame."""
    if len(lines) < 2:  # Need header + at least 1 row
        return None
    
    try:
        from io import StringIO
        csv_text = '\n'.join(lines)
        df = pd.read_csv(StringIO(csv_text))
        return df
    except Exception as e:
        log.warning(f"Failed to parse section: {e}")
        return None


def process_workout_sessions(
    sessions_df: pd.DataFrame,
    exercise_logs_df: pd.DataFrame,
    set_logs_df: pd.DataFrame,
    ingest_run_id: str,
) -> pd.DataFrame:
    """
    Process JEFIT workout sessions into workouts table format.
    
    Aggregates set data and creates workout-level records.
    """
    if sessions_df.empty:
        return pd.DataFrame()
    
    workouts = []
    home_tz = get_home_timezone() # For Strategy A
    
    for _, session in sessions_df.iterrows():
        session_id = session['_id']
        
        # Get exercises for this session
        session_exercises = exercise_logs_df[
            exercise_logs_df['belongsession'] == session_id
        ]
        
        if session_exercises.empty:
            continue
        
        # Get sets for these exercises
        exercise_log_ids = session_exercises['_id'].tolist()
        session_sets = set_logs_df[
            set_logs_df['exercise_log_id'].isin(exercise_log_ids)
        ]
        
        # JEFIT timestamps are Unix epoch seconds. Convert to naive datetime.
        start_naive = pd.to_datetime(session['starttime'], unit='s')
        
        # --- Use Strategy A (Assumed Timezone) ---
        temp_df = pd.DataFrame([{"timestamp_local": start_naive}])
        temp_df = apply_strategy_a(temp_df, home_timezone=home_tz)
        
        if temp_df.empty:
            log.warning(f"Skipping JEFIT session {session_id}, invalid start time")
            continue
            
        start_utc = temp_df.iloc[0]['timestamp_utc']
        start_local = temp_df.iloc[0]['timestamp_local'] # naive
        tz_name = temp_df.iloc[0]['tz_name']
        tz_source = temp_df.iloc[0]['tz_source']
        
        duration_s = session.get('total_time', 0)
        if pd.notna(duration_s) and duration_s > 0:
            end_utc = start_utc + pd.Timedelta(seconds=duration_s)
            end_local = start_local + pd.Timedelta(seconds=duration_s)
        else:
            end_utc = None
            end_local = None
        
        # Calculate aggregates from sets
        total_sets = len(session_sets)
        total_reps = session_sets['reps'].sum() if not session_sets.empty else 0
        total_volume_lbs = (
            (session_sets['weight_lbs'] * session_sets['reps']).sum()
            if not session_sets.empty else 0
        )
        
        workout_record = {
            'workout_id': f"jefit_{session_id}",
            'source': 'JEFIT',
            'workout_type': 'Resistance Training',
            'start_time_utc': start_utc,
            'end_time_utc': end_utc,
            'start_time_local': start_local,
            'end_time_local': end_local,
            'timezone': tz_name,
            'tz_source': tz_source,
            'duration_s': duration_s,
            
            # Resistance training specific
            'total_sets': total_sets,
            'total_reps': int(total_reps) if pd.notna(total_reps) else None,
            'total_volume_lbs': float(total_volume_lbs) if pd.notna(total_volume_lbs) else None,
            
            # Session metadata
            'num_exercises': int(session.get('total_exercise', 0)) if pd.notna(session.get('total_exercise')) else None,
        }
        
        workouts.append(workout_record)
    
    df = pd.DataFrame(workouts)
    df = add_lineage_fields(df, source='JEFIT', ingest_run_id=ingest_run_id)
    
    return df


def process_resistance_sets(
    sessions_df: pd.DataFrame,
    exercise_logs_df: pd.DataFrame,
    set_logs_df: pd.DataFrame,
    ingest_run_id: str,
) -> pd.DataFrame:
    """
    Process JEFIT set logs into resistance_sets table format.
    """
    if set_logs_df.empty:
        return pd.DataFrame()
    
    # Join sets with exercise info
    sets_with_exercise = set_logs_df.merge(
        exercise_logs_df[['_id', 'eid', 'ename', 'belongsession', 'mydate']],
        left_on='exercise_log_id',
        right_on='_id',
        how='left',
        suffixes=('', '_exercise')
    )
    
    # Join with session to get workout_start_utc
    session_starts = sessions_df[['_id', 'starttime']].copy()
    
    # Apply Strategy A to get the correct UTC start time
    home_tz = get_home_timezone()
    session_starts['timestamp_local'] = pd.to_datetime(session_starts['starttime'], unit='s')
    session_starts = apply_strategy_a(session_starts, home_timezone=home_tz)
    session_starts = session_starts.rename(columns={'timestamp_utc': 'workout_start_utc'})
    
    sets_with_session = sets_with_exercise.merge(
        session_starts[['_id', 'workout_start_utc']],
        left_on='belongsession',
        right_on='_id',
        how='left',
        suffixes=('', '_session')
    )
    
    resistance_sets = []
    
    for _, row in sets_with_session.iterrows():
        if pd.isna(row.get('workout_start_utc')):
            continue # Skip sets from sessions that failed timestamp conversion

        session_id = row['belongsession']
        workout_id = f"jefit_{session_id}"
        
        set_record = {
            'workout_id': workout_id,
            'workout_start_utc': row['workout_start_utc'],
            'exercise_id': str(row['eid']),
            'exercise_name': row['ename'],
            'set_number': int(row['set_index']) + 1,  # Convert 0-indexed to 1-indexed
            
            # Set data
            'actual_reps': int(row['reps']) if pd.notna(row['reps']) else None,
            'weight_lbs': float(row['weight_lbs']) if pd.notna(row['weight_lbs']) else None,
            'set_type': row.get('set_type', 'default'),
            
            # Optional fields (not in current JEFIT export)
            'target_reps': None,
            'rest_time_s': None,
            'is_warmup': row.get('set_type') == 'warmup',
            'is_failure': None,
            'bodypart': None,
            'equipment': None,
            'notes': None,
        }
        
        resistance_sets.append(set_record)
    
    df = pd.DataFrame(resistance_sets)
    df = add_lineage_fields(df, source='JEFIT', ingest_run_id=ingest_run_id)
    
    return df


def ingest_jefit_csv(csv_path: Path) -> dict[str, int]:
    """
    Main ingestion function for JEFIT CSV export.
    
    Args:
        csv_path: Path to JEFIT CSV export
        
    Returns:
        Dict with counts: {'workouts': N, 'sets': M}
    """
    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    
    log.info(f"Starting JEFIT ingestion (run_id={ingest_run_id})")
    log.info(f"Reading CSV: {csv_path}")
    
    # Parse CSV sections
    sections = parse_jefit_csv(csv_path)
    
    required_sections = ['WORKOUT_SESSIONS', 'EXERCISE_LOGS', 'EXERCISE_SET_LOGS']
    for section in required_sections:
        if section not in sections:
            raise ValueError(f"Missing required section: {section}")
    
    sessions_df = sections['WORKOUT_SESSIONS']
    exercise_logs_df = sections['EXERCISE_LOGS']
    set_logs_df = sections['EXERCISE_SET_LOGS']
    
    log.info(f"Found {len(sessions_df)} workout sessions")
    log.info(f"Found {len(exercise_logs_df)} exercise logs")
    log.info(f"Found {len(set_logs_df)} set logs")
    
    counts = {'workouts': 0, 'sets': 0}
    
    # Process workouts
    workouts_df = process_workout_sessions(
        sessions_df, exercise_logs_df, set_logs_df, ingest_run_id
    )
    
    if not workouts_df.empty:
        workouts_df = create_date_partition_column(workouts_df, 'start_time_utc', 'date', 'M')
        
        upsert_by_key(
            workouts_df,
            WORKOUTS_PATH,
            primary_key=['workout_id', 'source'],
            partition_cols=['date', 'source'],
            schema=get_schema('workouts'),
        )
        counts['workouts'] = len(workouts_df)
        log.info(f"Wrote {counts['workouts']} workouts")
    
    # Process resistance sets
    sets_df = process_resistance_sets(
        sessions_df, exercise_logs_df, set_logs_df, ingest_run_id
    )
    
    if not sets_df.empty:
        sets_df = create_date_partition_column(sets_df, 'workout_start_utc', 'date', 'M')
        
        upsert_by_key(
            sets_df,
            RESISTANCE_SETS_PATH,
            primary_key=['workout_id', 'exercise_id', 'set_number', 'source'],
            partition_cols=['date', 'source'],
            schema=get_schema('resistance_sets'),
        )
        counts['sets'] = len(sets_df)
        log.info(f"Wrote {counts['sets']} sets")
    
    log.info(f"JEFIT ingestion complete: {counts}")
    return counts


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Ingest JEFIT CSV export")
    parser.add_argument("csv_file", nargs='?', help="Path to JEFIT CSV export (default: latest in Data/Raw/JEFIT/)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
    
    # Determine which file to process
    if args.csv_file:
        csv_path = Path(args.csv_file)
    else:
        # Auto-scan for latest JEFIT export
        jefit_files = list(RAW_JEFIT_DIR.glob("*.csv"))
        if not jefit_files:
            print(f"❌ No CSV files found in {RAW_JEFIT_DIR}")
            print(f"   Place JEFIT exports in this directory or specify path explicitly.")
            return 1
        csv_path = max(jefit_files, key=lambda p: p.stat().st_mtime)
        log.info(f"Auto-detected latest JEFIT export: {csv_path.name}")
    
    if not csv_path.exists():
        print(f"❌ File not found: {csv_path}")
        return 1
    
    try:
        counts = ingest_jefit_csv(csv_path)
        print("\n✅ Ingestion complete:")
        print(f"   Workouts: {counts['workouts']}")
        print(f"   Sets:     {counts['sets']}")
    except Exception as e:
        log.exception("Ingestion failed")
        print(f"\n❌ Ingestion failed: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())