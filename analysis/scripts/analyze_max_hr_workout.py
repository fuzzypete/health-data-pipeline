#!/usr/bin/env python3
"""
Analyze the max HR test workout (108476638) from raw stroke data.
This script pulls stroke-by-stroke data to see actual watts and HR progression.
"""

import pandas as pd
import pyarrow.parquet as pq

# Workout ID from today's max HR test
WORKOUT_ID = 108476638

print("="*80)
print("MAX HR TEST WORKOUT ANALYSIS")
print("="*80)
print(f"Workout ID: {WORKOUT_ID}")
print()

# Read stroke data from Parquet files
# Actual schema: time_cumulative_s, heart_rate_bpm, watts, stroke_rate_spm
strokes_df = pd.read_parquet(
    'Data/Parquet/cardio_strokes',
    filters=[('workout_id', '=', str(WORKOUT_ID))]
)

print(f"Total strokes: {len(strokes_df)}")
print(f"Duration: {strokes_df['time_cumulative_s'].max():.1f} seconds ({strokes_df['time_cumulative_s'].max()/60:.1f} min)")
print()

# Overall stats
print("="*80)
print("OVERALL STATS")
print("="*80)
print(f"Max HR: {strokes_df['heart_rate_bpm'].max()} bpm")
print(f"Max Watts: {strokes_df['watts'].max():.0f}W")
print(f"Avg Watts: {strokes_df['watts'].mean():.0f}W")
print(f"Avg HR: {strokes_df['heart_rate_bpm'].mean():.0f} bpm")
print()

# Last 30 seconds analysis
last_30_sec = strokes_df['time_cumulative_s'].max() - 30
last_30 = strokes_df[strokes_df['time_cumulative_s'] >= last_30_sec].copy()

print("="*80)
print("LAST 30 SECONDS (ALL-OUT EFFORT)")
print("="*80)
print(f"Strokes: {len(last_30)}")
print(f"Avg Watts: {last_30['watts'].mean():.0f}W")
print(f"Max Watts: {last_30['watts'].max():.0f}W")
print(f"Avg HR: {last_30['heart_rate_bpm'].mean():.0f} bpm")
print(f"Max HR: {last_30['heart_rate_bpm'].max()} bpm")
print()

# Show stroke-by-stroke for final 30 seconds
print("STROKE-BY-STROKE (Final 30s):")
print(last_30[['time_cumulative_s', 'watts', 'heart_rate_bpm', 'stroke_rate_spm']].to_string(index=False))
print()

# Peak power section (>250W)
peak_power = strokes_df[strokes_df['watts'] > 250].copy()
if len(peak_power) > 0:
    print("="*80)
    print("PEAK POWER STROKES (>250W)")
    print("="*80)
    print(peak_power[['time_cumulative_s', 'watts', 'heart_rate_bpm', 'stroke_rate_spm']].to_string(index=False))
    print()
else:
    # Try lower threshold
    peak_power = strokes_df[strokes_df['watts'] > 200].copy()
    if len(peak_power) > 0:
        print("="*80)
        print("HIGH POWER STROKES (>200W)")
        print("="*80)
        print(peak_power[['time_cumulative_s', 'watts', 'heart_rate_bpm', 'stroke_rate_spm']].to_string(index=False))
        print()

# Progressive analysis - 10-second bins
print("="*80)
print("WORKOUT PROGRESSION (10-second bins)")
print("="*80)
strokes_df['time_bin'] = (strokes_df['time_cumulative_s'] // 10) * 10
binned = strokes_df.groupby('time_bin').agg({
    'watts': 'mean',
    'heart_rate_bpm': 'mean',
    'stroke_rate_spm': 'mean'
}).round(0)
print(binned.to_string())
print()

# Find when HR peaked
max_hr_row = strokes_df.loc[strokes_df['heart_rate_bpm'].idxmax()]
print("="*80)
print("MAX HR ACHIEVED")
print("="*80)
print(f"Time: {max_hr_row['time_cumulative_s']:.1f}s into workout")
print(f"HR: {max_hr_row['heart_rate_bpm']} bpm")
print(f"Watts: {max_hr_row['watts']:.0f}W")
print(f"Stroke Rate: {max_hr_row['stroke_rate_spm']:.0f} spm")
print()

# Summary for NOW.md update
print("="*80)
print("SUMMARY FOR NOW.MD")
print("="*80)
print(f"✓ Max HR: {strokes_df['heart_rate_bpm'].max()} bpm")
print(f"✓ Target: >150 bpm")
if strokes_df['heart_rate_bpm'].max() >= 150:
    print("✓ GATE CLEARED - Can unlock intensity training once ferritin >70")
else:
    print(f"✗ Need {150 - strokes_df['heart_rate_bpm'].max()} more bpm to clear gate")
print()
print(f"Peak power: {strokes_df['watts'].max():.0f}W (at {max_hr_row['time_cumulative_s']:.0f}s)")
print(f"Final 30s avg: {last_30['watts'].mean():.0f}W")
print(f"Test duration: {strokes_df['time_cumulative_s'].max()/60:.1f} minutes")
