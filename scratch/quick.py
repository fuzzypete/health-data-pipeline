import pandas as pd

# Get a BikeErg workout from your data
workouts = pd.read_parquet('Data/Parquet/workouts')
bike_workouts = workouts[workouts['erg_type'] == 'bike']
print(bike_workouts[['workout_id', 'date', 'erg_type', 'avg_pace_sec_per_500m']].head())

# Check if pace field exists and is populated for BikeErg
strokes = pd.read_parquet('Data/Parquet/cardio_strokes')
bike_strokes = strokes[strokes['workout_id'].isin(bike_workouts['workout_id'].values)]
print(f"\nBike strokes pace field sample:")
print(bike_strokes[['pace_500m_cs']].head(20))
