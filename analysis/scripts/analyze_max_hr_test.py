#!/usr/bin/env python3
"""
Analyze max HR test workout
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

# Find most recent workout
workouts = pd.read_parquet('Data/Parquet/workouts')
workouts['date'] = workouts['date'].astype(str)
workouts['date'] = pd.to_datetime(workouts['date'])
most_recent = workouts['date'].max()
test_workout = workouts[workouts['date'] == most_recent].iloc[0]

print("="*80)
print("MAX HR RESPONSE TEST - ANALYSIS")
print("="*80)
print(f"Date: {test_workout['date']}")
print(f"Workout ID: {test_workout['workout_id']}")
print(f"Type: {test_workout['workout_type']}")
print(f"Duration: {test_workout['duration_s']/60:.1f} min")
print(f"Distance: {test_workout['distance_m']:.0f}m")
print()

print("="*80)
print("HEADLINE RESULTS")
print("="*80)
print(f"Max HR: {test_workout['max_hr_bpm']:.0f} bpm")
print(f"Avg HR: {test_workout['avg_hr_bpm']:.0f} bpm")
print()

# Decision gate
TARGET_HR = 150
if test_workout['max_hr_bpm'] >= TARGET_HR:
    print(f"✅ GATE CLEARED: {test_workout['max_hr_bpm']:.0f} >= {TARGET_HR} bpm")
    print("   → Chronotropic capacity confirmed")
else:
    gap = TARGET_HR - test_workout['max_hr_bpm']
    print(f"❌ Below target: Need {gap:.0f} more bpm")
print()

# Stroke-by-stroke analysis
strokes = pd.read_parquet(
    'Data/Parquet/cardio_strokes',
    filters=[('workout_id', '==', test_workout['workout_id'])]
)

if len(strokes) > 0:
    print("="*80)
    print("HR RESPONSE KINETICS")
    print("="*80)
    
    thresholds = [120, 130, 140, 150, 153]
    for threshold in thresholds:
        hits = strokes[strokes['heart_rate_bpm'] >= threshold]
        if len(hits) > 0:
            time_to = hits['time_cumulative_s'].min()
            print(f"Time to {threshold} bpm: {time_to:.0f}s ({time_to/60:.1f} min)")
        else:
            print(f"Time to {threshold} bpm: Never reached")
    print()
    
    print("="*80)
    print("FINAL 60 SECONDS")
    print("="*80)
    last_60 = strokes[strokes['time_cumulative_s'] >= (strokes['time_cumulative_s'].max() - 60)]
    print(f"Avg HR: {last_60['heart_rate_bpm'].mean():.0f} bpm")
    print(f"Max HR: {last_60['heart_rate_bpm'].max():.0f} bpm")
    print(f"Avg Power: {last_60['watts'].mean():.0f}W")
    print(f"Peak Power: {last_60['watts'].max():.0f}W")
    print()
    
    # Visualization
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=('Heart Rate Response', 'Power Output'),
        vertical_spacing=0.15,
        shared_xaxes=True
    )
    
    fig.add_trace(
        go.Scatter(
            x=strokes['time_cumulative_s']/60,
            y=strokes['heart_rate_bpm'],
            mode='lines',
            name='Heart Rate',
            line=dict(color='red', width=2)
        ),
        row=1, col=1
    )
    
    fig.add_hline(
        y=TARGET_HR, 
        line_dash="dash", 
        line_color="green",
        annotation_text=f"Target: {TARGET_HR} bpm",
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(
            x=strokes['time_cumulative_s']/60,
            y=strokes['watts'],
            mode='lines',
            name='Power',
            line=dict(color='blue', width=2)
        ),
        row=2, col=1
    )
    
    fig.update_xaxes(title_text="Time (minutes)", row=2, col=1)
    fig.update_yaxes(title_text="Heart Rate (bpm)", row=1, col=1)
    fig.update_yaxes(title_text="Power (W)", row=2, col=1)
    
    fig.update_layout(
        height=800,
        title_text=f"Max HR Test - {test_workout['date']}<br><sub>Workout ID: {test_workout['workout_id']}</sub>",
        showlegend=False
    )
    
    output_file = f"analysis/outputs/max_hr_test_{test_workout['date']}.html"
    fig.write_html(output_file)
    print(f"📊 Chart saved: {output_file}")
    print()
else:
    print("⚠️  No stroke data found for this workout")
    print()

# Recent comparison
print("="*80)
print("RECENT MAX HR EFFORTS (Last 30 days)")
print("="*80)
recent = workouts[
    (workouts['date'] >= most_recent - timedelta(days=30)) &
    (workouts['max_hr_bpm'] > 0)
].sort_values('max_hr_bpm', ascending=False).head(5)

print(recent[['date', 'workout_type', 'max_hr_bpm', 'distance_m']].to_string(index=False))