import pandas as pd
import pyarrow.parquet as pq

# Read today's workout from the workouts table
workouts_df = pd.read_parquet('Data/Parquet/workouts', 
                               filters=[('date', '=', '2025-11-12')])

print("TODAY'S WORKOUT SUMMARY:")
print(workouts_df[['workout_id', 'workout_type', 'duration_min', 
                    'avg_watts', 'avg_hr_bpm', 'max_hr_bpm', 
                    'distance_m', 'calories']].to_string(index=False))

# If you want stroke-by-stroke data for HR analysis
strokes_df = pd.read_parquet('Data/Parquet/cardio_strokes',
                              filters=[('date', '=', '2025-11-12')])

print("\nSTROKE-BY-STROKE STATS:")
print(f"Total strokes: {len(strokes_df)}")
print(f"HR range: {strokes_df['heart_rate_bpm'].min():.0f}-{strokes_df['heart_rate_bpm'].max():.0f} bpm")
print(f"Average HR: {strokes_df['heart_rate_bpm'].mean():.1f} bpm")
print(f"HR std dev: {strokes_df['heart_rate_bpm'].std():.1f} bpm")