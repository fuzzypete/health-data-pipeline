#!/usr/bin/env python3
"""
Analyze the most recent 30/30 workout from HDP
Run from HDP root: poetry run python analyze_recent_30_30.py
"""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Get most recent workout
workouts = pd.read_parquet('Data/Parquet/workouts')
workouts['start_time_utc'] = pd.to_datetime(workouts['start_time_utc'])
most_recent = workouts[workouts['source'] == 'Concept2'].sort_values('start_time_utc', ascending=False).iloc[0]

print("="*80)
print("MOST RECENT CONCEPT2 WORKOUT")
print("="*80)
print(f"Workout ID: {most_recent['workout_id']}")
print(f"Date: {most_recent['start_time_utc']}")
print(f"Duration: {most_recent['duration_s']/60:.1f} min")
print(f"Distance: {most_recent['distance_m']:.0f}m")
print(f"Avg HR: {most_recent['avg_hr_bpm']:.0f} bpm")
print(f"Max HR: {most_recent['max_hr_bpm']:.0f} bpm" if pd.notna(most_recent['max_hr_bpm']) else "Max HR: N/A")
print()

# Get stroke data
strokes = pd.read_parquet('Data/Parquet/cardio_strokes')
workout_strokes = strokes[strokes['workout_id'] == most_recent['workout_id']].copy()
workout_strokes = workout_strokes.sort_values('time_cumulative_s')

# Calculate actual max HR from strokes if workout summary is NULL
actual_max_hr = workout_strokes['heart_rate_bpm'].max()
actual_avg_hr = workout_strokes['heart_rate_bpm'].mean()

print("="*80)
print("STROKE DATA ANALYSIS")
print("="*80)
print(f"Total strokes: {len(workout_strokes)}")
print(f"Actual Max HR: {actual_max_hr:.0f} bpm")
print(f"Actual Avg HR: {actual_avg_hr:.0f} bpm")
print(f"Max Watts: {workout_strokes['watts'].max():.0f}W")
print(f"Avg Watts: {workout_strokes['watts'].mean():.0f}W")
print()

# Identify warmup vs intervals
# Assume first 10 minutes is warmup
warmup_end = 600  # 10 minutes in seconds
warmup = workout_strokes[workout_strokes['time_cumulative_s'] < warmup_end]
intervals = workout_strokes[workout_strokes['time_cumulative_s'] >= warmup_end]

if len(intervals) > 0:
    print("="*80)
    print("INTERVAL PORTION ANALYSIS (after 10min warmup)")
    print("="*80)
    
    # Try to detect 30/30 pattern by looking at power variation
    # Create 30-second bins
    intervals = intervals.copy()
    intervals['interval_30s'] = ((intervals['time_cumulative_s'] - warmup_end) // 30).astype(int)
    
    interval_stats = intervals.groupby('interval_30s').agg({
        'watts': ['mean', 'max', 'min'],
        'heart_rate_bpm': ['mean', 'max'],
        'time_cumulative_s': 'count'
    }).round(0)
    
    interval_stats.columns = ['avg_watts', 'max_watts', 'min_watts', 'avg_hr', 'max_hr', 'strokes']
    
    print("\n30-SECOND INTERVAL BLOCKS:")
    print(interval_stats.head(30))
    print()
    
    # Check if alternating pattern exists
    even_intervals = interval_stats[interval_stats.index % 2 == 0]
    odd_intervals = interval_stats[interval_stats.index % 2 == 1]
    
    if len(even_intervals) > 3 and len(odd_intervals) > 3:
        even_avg = even_intervals['avg_watts'].mean()
        odd_avg = odd_intervals['avg_watts'].mean()
        
        if abs(even_avg - odd_avg) > 50:  # Significant difference suggests 30/30
            print("="*80)
            print("30/30 PATTERN DETECTED")
            print("="*80)
            hard_intervals = even_intervals if even_avg > odd_avg else odd_intervals
            easy_intervals = odd_intervals if even_avg > odd_avg else even_intervals
            
            print(f"Hard 30s avg: {hard_intervals['avg_watts'].mean():.0f}W (HR: {hard_intervals['avg_hr'].mean():.0f} bpm)")
            print(f"Easy 30s avg: {easy_intervals['avg_watts'].mean():.0f}W (HR: {easy_intervals['avg_hr'].mean():.0f} bpm)")
            print(f"Number of hard intervals: {len(hard_intervals)}")
            print(f"Max HR during intervals: {interval_stats['max_hr'].max():.0f} bpm")
            print()
            
            # HR progression
            print("HR RESPONSE:")
            print(f"Time to 140 bpm: ", end="")
            hits_140 = intervals[intervals['heart_rate_bpm'] >= 140]
            if len(hits_140) > 0:
                time_to_140 = (hits_140['time_cumulative_s'].min() - warmup_end) / 60
                print(f"{time_to_140:.1f} min into intervals")
            else:
                print("Never reached")
            
            print(f"Time to 150 bpm: ", end="")
            hits_150 = intervals[intervals['heart_rate_bpm'] >= 150]
            if len(hits_150) > 0:
                time_to_150 = (hits_150['time_cumulative_s'].min() - warmup_end) / 60
                print(f"{time_to_150:.1f} min into intervals")
            else:
                print("Never reached")

# Create visualization
fig = make_subplots(
    rows=3, cols=1,
    subplot_titles=('Power Output', 'Heart Rate', 'Stroke Rate'),
    vertical_spacing=0.1,
    shared_xaxes=True
)

time_min = workout_strokes['time_cumulative_s'] / 60

# Power
fig.add_trace(
    go.Scatter(x=time_min, y=workout_strokes['watts'], mode='lines', 
               name='Power', line=dict(color='blue', width=1)),
    row=1, col=1
)

# HR
fig.add_trace(
    go.Scatter(x=time_min, y=workout_strokes['heart_rate_bpm'], mode='lines',
               name='HR', line=dict(color='red', width=1)),
    row=2, col=1
)

# Add 140 bpm line
fig.add_hline(y=140, line_dash="dash", line_color="orange", 
              annotation_text="140 bpm", row=2, col=1)

# Stroke rate
fig.add_trace(
    go.Scatter(x=time_min, y=workout_strokes['stroke_rate_spm'], mode='lines',
               name='Stroke Rate', line=dict(color='green', width=1)),
    row=3, col=1
)

# Add vertical line at 10min (warmup end)
fig.add_vline(x=10, line_dash="dash", line_color="gray", 
              annotation_text="Warmup End")

fig.update_xaxes(title_text="Time (minutes)", row=3, col=1)
fig.update_yaxes(title_text="Watts", row=1, col=1)
fig.update_yaxes(title_text="HR (bpm)", row=2, col=1)
fig.update_yaxes(title_text="SPM", row=3, col=1)

fig.update_layout(height=900, showlegend=False,
                  title_text=f"Workout Analysis - {most_recent['start_time_utc'].date()}")

output_file = f"analysis/outputs/workout_{most_recent['workout_id']}.html"
fig.write_html(output_file)
print(f"\n📊 Visualization saved: {output_file}")
