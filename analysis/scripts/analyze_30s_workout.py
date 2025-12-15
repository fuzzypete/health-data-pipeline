import pandas as pd
from datetime import datetime

workouts = pd.read_parquet('Data/Parquet/workouts')
strokes = pd.read_parquet('Data/Parquet/cardio_strokes')

# Get today's workout
workouts['date'] = workouts['date'].astype(str)
workouts['date'] = pd.to_datetime(workouts['date'])
today = pd.Timestamp.now().normalize()
todays_workout = workouts[workouts['date'] >= today].iloc[0]

print(f"Workout: {todays_workout['workout_id']}")
print(f"Duration: {todays_workout['duration_s']/60:.1f} min")
print(f"Max HR: {todays_workout['max_hr_bpm']:.0f} bpm")
print(f"Avg HR: {todays_workout['avg_hr_bpm']:.0f} bpm")

# Get stroke data to analyze intervals
workout_strokes = strokes[strokes['workout_id'] == todays_workout['workout_id']].copy()
workout_strokes['time_min'] = workout_strokes['time_cumulative_s'] / 60

# Show power distribution
print(f"\nPower stats:")
print(f"Max: {workout_strokes['watts'].max():.0f}W")
print(f"Mean: {workout_strokes['watts'].mean():.0f}W")
print(f"Median: {workout_strokes['watts'].median():.0f}W")

# Show HR progression
print(f"\nHR stats:")
print(f"Max: {workout_strokes['heart_rate_bpm'].max():.0f} bpm")
print(f"Mean: {workout_strokes['heart_rate_bpm'].mean():.0f} bpm")
print(f"Time to 140 bpm: {workout_strokes[workout_strokes['heart_rate_bpm'] >= 140]['time_cumulative_s'].min()/60:.1f} min")
print(f"Time to 150 bpm: {workout_strokes[workout_strokes['heart_rate_bpm'] >= 150]['time_cumulative_s'].min()/60:.1f} min" if len(workout_strokes[workout_strokes['heart_rate_bpm'] >= 150]) > 0 else "Never hit 150")