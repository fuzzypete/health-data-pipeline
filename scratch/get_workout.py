import pandas as pd

# Get workout to check notes/comments for lactate
workouts = pd.read_parquet('Data/Parquet/workouts')
workout = workouts[workouts['workout_id'] == '108364704'].iloc[0]

print("=" * 70)
print("WORKOUT NOTES")
print("=" * 70)
print(f"Notes: {workout['notes']}")

# Get stroke data
strokes = pd.read_parquet('Data/Parquet/cardio_strokes',
                          filters=[('workout_id', '=', '108364704')])

# FIX: time_cumulative_s is actually in CENTISECONDS, not seconds
valid_strokes = strokes[strokes['pace_500m_cs'] > 0].copy()
valid_strokes['time_min'] = valid_strokes['time_cumulative_s'] / 6000  # Centiseconds to minutes
valid_strokes['pace_500m_sec'] = valid_strokes['pace_500m_cs'] / 100
valid_strokes['pace_1000m_sec'] = valid_strokes['pace_500m_sec'] * 2
valid_strokes['watts'] = 4184 / valid_strokes['pace_1000m_sec']

print("\n" + "=" * 70)
print("WORKOUT SUMMARY")
print("=" * 70)
print(f"Duration: {valid_strokes['time_min'].max():.1f} minutes")
print(f"Total strokes: {len(valid_strokes)}")

# Steady state (HR >= 110)
steady_state = valid_strokes[valid_strokes['heart_rate_bpm'] >= 110].copy()

print("\n" + "=" * 70)
print("STEADY STATE ZONE 2 (HR >= 110 bpm)")
print("=" * 70)
print(f"Duration: {(steady_state['time_min'].max() - steady_state['time_min'].min()):.1f} minutes")
print(f"Average watts: {steady_state['watts'].mean():.1f}W")
print(f"Average HR: {steady_state['heart_rate_bpm'].mean():.1f} bpm")
print(f"Watts CV: {(steady_state['watts'].std() / steady_state['watts'].mean() * 100):.1f}%")
print(f"HR range: {steady_state['heart_rate_bpm'].min():.0f}-{steady_state['heart_rate_bpm'].max():.0f} bpm")

# HR drift
start_time = steady_state['time_min'].min()
end_time = steady_state['time_min'].max()
first_5 = steady_state[steady_state['time_min'] <= (start_time + 5)]
last_5 = steady_state[steady_state['time_min'] >= (end_time - 5)]

print(f"\nFirst 5 min: {first_5['heart_rate_bpm'].mean():.1f} bpm @ {first_5['watts'].mean():.0f}W")
print(f"Last 5 min: {last_5['heart_rate_bpm'].mean():.1f} bpm @ {last_5['watts'].mean():.0f}W")
hr_drift = last_5['heart_rate_bpm'].mean() - first_5['heart_rate_bpm'].mean()
print(f"HR drift: {hr_drift:+.1f} bpm")