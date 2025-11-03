"""
Verify Concept2 ingestion data quality.

Checks for duplicates and shows summary statistics.
"""
import pyarrow.parquet as pq
import pandas as pd

print("=== WORKOUTS ===")
workouts = pq.read_table('Data/Parquet/workouts').to_pandas()
print(f"Total rows: {len(workouts)}")
print(f"Unique workout IDs: {workouts['workout_id'].nunique()}")
print(f"Date range: {workouts['start_time_local'].min()} to {workouts['start_time_local'].max()}")

if len(workouts) != workouts['workout_id'].nunique():
    print(f"\n⚠️ DUPLICATES: {len(workouts) - workouts['workout_id'].nunique()} duplicate workouts")
    dupes = workouts[workouts.duplicated(subset=['workout_id'], keep=False)].sort_values('workout_id')
    print(f"First few duplicates:\n{dupes[['workout_id', 'start_time_local', 'distance_m']].head(10)}")
else:
    print("✅ No duplicate workouts")

print("\n=== SPLITS ===")
splits = pq.read_table('Data/Parquet/cardio_splits').to_pandas()
print(f"Total rows: {len(splits)}")
print(f"Unique (workout_id, split_number): {splits[['workout_id', 'split_number']].drop_duplicates().shape[0]}")

if len(splits) != splits[['workout_id', 'split_number']].drop_duplicates().shape[0]:
    print(f"⚠️ DUPLICATES: {len(splits) - splits[['workout_id', 'split_number']].drop_duplicates().shape[0]} duplicate splits")
else:
    print("✅ No duplicate splits")

print("\n=== STROKES ===")
strokes = pq.read_table('Data/Parquet/cardio_strokes').to_pandas()
print(f"Total rows: {len(strokes)}")
print(f"Unique (workout_id, stroke_number): {strokes[['workout_id', 'stroke_number']].drop_duplicates().shape[0]}")

if len(strokes) != strokes[['workout_id', 'stroke_number']].drop_duplicates().shape[0]:
    print(f"⚠️ DUPLICATES: {len(strokes) - strokes[['workout_id', 'stroke_number']].drop_duplicates().shape[0]} duplicate strokes")
else:
    print("✅ No duplicate strokes")

print("\n=== SUMMARY ===")
print(f"Workouts: {workouts['workout_id'].nunique()} unique")
print(f"Total distance: {workouts['distance_m'].sum() / 1000:.1f} km")
print(f"Avg workout distance: {workouts['distance_m'].mean():.0f} m")
print(f"Workout types:")
for wtype, count in workouts['workout_type'].value_counts().items():
    print(f"  {wtype}: {count}")

# Check for data quality issues
print("\n=== DATA QUALITY ===")
null_hr = workouts['avg_hr_bpm'].isna().sum()
print(f"Workouts missing HR: {null_hr} ({null_hr/len(workouts)*100:.1f}%)")

null_splits = (workouts['has_splits'] == True).sum() - len(splits[['workout_id']].drop_duplicates())
if null_splits != 0:
    print(f"⚠️ Workouts marked has_splits but no splits found: {null_splits}")

print("\n=== PARTITION DISTRIBUTION ===")
print("Workouts per year:")
workouts['year'] = pd.to_datetime(workouts['start_time_local']).dt.year
for year, count in workouts.groupby('year').size().items():
    print(f"  {year}: {count} workouts")
