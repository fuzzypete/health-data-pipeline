"""
Test JEFIT CSV ingestion with your actual data.

This will parse your JEFIT export and show what would be ingested.
"""
import sys
sys.path.insert(0, 'src')

from pathlib import Path
from pipeline.ingest.jefit_csv import parse_jefit_csv, process_workout_sessions, process_resistance_sets

# Parse the CSV
csv_path = Path('/mnt/project/PeterWickersham_jefit_20251030.csv')
print(f"Parsing {csv_path}...\n")

sections = parse_jefit_csv(csv_path)

print("=== CSV SECTIONS ===")
for name, df in sections.items():
    print(f"{name}: {len(df)} rows")

print("\n=== SAMPLE WORKOUT SESSION ===")
sessions_df = sections.get('WORKOUT_SESSIONS')
if sessions_df is not None:
    print(sessions_df.head(3))

print("\n=== SAMPLE EXERCISE LOG ===")
exercise_logs_df = sections.get('EXERCISE_LOGS')
if exercise_logs_df is not None:
    print(exercise_logs_df.head(3))

print("\n=== SAMPLE SET LOG ===")
set_logs_df = sections.get('EXERCISE_SET_LOGS')
if set_logs_df is not None:
    print(set_logs_df.head(5))

# Process workouts
print("\n=== PROCESSING WORKOUTS ===")
if all(k in sections for k in ['WORKOUT_SESSIONS', 'EXERCISE_LOGS', 'EXERCISE_SET_LOGS']):
    workouts_df = process_workout_sessions(
        sections['WORKOUT_SESSIONS'],
        sections['EXERCISE_LOGS'],
        sections['EXERCISE_SET_LOGS'],
        'test_run'
    )
    print(f"Processed {len(workouts_df)} workouts")
    print("\nSample workouts:")
    print(workouts_df[['workout_id', 'start_time_local', 'total_sets', 'total_volume_lbs']].head())
    
    # Process sets
    print("\n=== PROCESSING RESISTANCE SETS ===")
    sets_df = process_resistance_sets(
        sections['WORKOUT_SESSIONS'],
        sections['EXERCISE_LOGS'],
        sections['EXERCISE_SET_LOGS'],
        'test_run'
    )
    print(f"Processed {len(sets_df)} sets")
    print("\nSample sets:")
    print(sets_df[['exercise_name', 'set_number', 'weight_lbs', 'actual_reps']].head(10))
    
    # Summary stats
    print("\n=== SUMMARY STATISTICS ===")
    print(f"Total workouts: {len(workouts_df)}")
    print(f"Total sets: {len(sets_df)}")
    print(f"Date range: {workouts_df['start_time_local'].min()} to {workouts_df['start_time_local'].max()}")
    print(f"\nTop exercises by volume:")
    exercise_volume = sets_df.groupby('exercise_name').apply(
        lambda x: (x['weight_lbs'] * x['actual_reps']).sum()
    ).sort_values(ascending=False)
    print(exercise_volume.head(10))
