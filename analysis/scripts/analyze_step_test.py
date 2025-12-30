#!/usr/bin/env python3
"""
Analyze a lactate step test from Concept2 BikeErg data.

Assumes:
- Free ride workout with breaks (dips in power) for lactate readings
- Lactate readings stored in notes field, comma-delimited
- Readings align from end of workout back to each detected dip

Usage:
    python analyze_step_test.py                    # Most recent BikeErg workout
    python analyze_step_test.py --date 2025-12-28  # Specific date
    python analyze_step_test.py --workout-id 123   # Specific workout ID
"""

import argparse
import pandas as pd
import pyarrow.parquet as pq
from pathlib import Path
from datetime import datetime

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
PARQUET_PATH = PROJECT_ROOT / "Data" / "Parquet"


def load_workout(workout_id: str = None, date: str = None) -> tuple[pd.Series, pd.DataFrame]:
    """Load workout and stroke data."""
    workouts = pq.read_table(PARQUET_PATH / "workouts").to_pandas()

    # Filter to BikeErg
    bike = workouts[workouts['erg_type'] == 'bike'].copy()

    if workout_id:
        workout = bike[bike['workout_id'] == workout_id].iloc[0]
    elif date:
        bike['date_str'] = bike['start_time_local'].astype(str).str[:10]
        workout = bike[bike['date_str'] == date].sort_values('start_time_local', ascending=False).iloc[0]
    else:
        # Most recent
        workout = bike.sort_values('start_time_local', ascending=False).iloc[0]

    # Load strokes
    strokes = pq.read_table(PARQUET_PATH / "cardio_strokes").to_pandas()
    stroke_data = strokes[strokes['workout_id'] == str(workout['workout_id'])].sort_values('time_cumulative_s')

    return workout, stroke_data


def detect_steps(strokes: pd.DataFrame, warmup_minutes: int = 8, dip_threshold_watts: float = 5) -> list[dict]:
    """
    Detect step intervals by finding dips in power (reading breaks).

    Uses a smarter approach: looks for local dips relative to surrounding power,
    not absolute thresholds. A dip is when power drops more than dip_threshold_watts
    below the average of the surrounding minutes.

    Returns list of step dictionaries with start/end times.
    """
    # Create minute-by-minute summary
    strokes = strokes.copy()
    strokes['minute'] = (strokes['time_cumulative_s'] // 60).astype(int)

    by_min = strokes.groupby('minute').agg({
        'watts': 'mean',
        'heart_rate_bpm': 'mean',
        'time_cumulative_s': ['min', 'max']
    }).reset_index()
    by_min.columns = ['minute', 'watts', 'hr', 'time_start', 'time_end']

    # Skip warmup period
    work_mins = by_min[by_min['minute'] >= warmup_minutes].copy()

    # Detect dips using rolling comparison
    # A dip is when power drops from prev AND rises to next (valley pattern)
    # OR when there's a significant jump to the next minute (step change)
    work_mins['prev_watts'] = work_mins['watts'].shift(1)
    work_mins['next_watts'] = work_mins['watts'].shift(-1)

    # Valley: lower than both neighbors
    is_valley = (
        (work_mins['watts'] < work_mins['prev_watts'] - dip_threshold_watts) &
        (work_mins['watts'] < work_mins['next_watts'] - dip_threshold_watts)
    )

    # Step change: next minute jumps up significantly (indicates new step started)
    is_step_change = (work_mins['next_watts'] - work_mins['watts']) > dip_threshold_watts

    work_mins['is_dip'] = is_valley | is_step_change

    # Also mark warmup as not part of steps
    warmup_mins = by_min[by_min['minute'] < warmup_minutes].copy()
    warmup_mins['is_dip'] = True  # Treat warmup as "dip" to exclude from steps

    # Combine
    by_min = pd.concat([warmup_mins, work_mins]).sort_values('minute')

    # Group consecutive non-dip minutes into steps
    steps = []
    current_step = None

    for _, row in by_min.iterrows():
        minute = int(row['minute'])
        if row['is_dip'] or pd.isna(row['is_dip']):
            if current_step is not None:
                current_step['end_min'] = minute - 1
                steps.append(current_step)
                current_step = None
        else:
            if current_step is None:
                current_step = {'start_min': minute, 'end_min': minute}
            else:
                current_step['end_min'] = minute

    # Don't forget last step
    if current_step is not None:
        steps.append(current_step)

    return steps, by_min


def analyze_steps(strokes: pd.DataFrame, steps: list[dict], lactate_readings: list[float]) -> pd.DataFrame:
    """
    Analyze each step and align lactate readings.

    Lactate readings align in order: first reading = first step, etc.
    """
    results = []

    for i, step in enumerate(steps):
        mask = (strokes['time_cumulative_s'] >= step['start_min'] * 60) & \
               (strokes['time_cumulative_s'] < (step['end_min'] + 1) * 60)
        data = strokes[mask]

        if len(data) == 0:
            continue

        avg_watts = data['watts'].mean()
        avg_hr = data['heart_rate_bpm'].mean()
        end_hr = data['heart_rate_bpm'].iloc[-1]
        duration_min = step['end_min'] - step['start_min'] + 1

        # Align lactate in order (first reading = first step)
        lactate = lactate_readings[i] if i < len(lactate_readings) else None

        results.append({
            'step': i,
            'time_range': f"{step['start_min']}:00-{step['end_min']}:59",
            'duration_min': duration_min,
            'avg_watts': round(avg_watts, 0),
            'avg_hr': round(avg_hr, 0),
            'end_hr': round(end_hr, 0),
            'lactate': lactate
        })

    return pd.DataFrame(results)


def find_zone2_ceiling(results: pd.DataFrame, threshold: float = 2.0) -> dict:
    """
    Find the Zone 2 ceiling (where lactate crosses threshold).

    Returns interpolated power at threshold crossing, or None if not reached.
    """
    results_with_lactate = results[results['lactate'].notna()].copy()

    if len(results_with_lactate) < 2:
        return None

    # Find where lactate crosses threshold
    for i in range(1, len(results_with_lactate)):
        prev = results_with_lactate.iloc[i-1]
        curr = results_with_lactate.iloc[i]

        if prev['lactate'] < threshold <= curr['lactate']:
            # Linear interpolation
            ratio = (threshold - prev['lactate']) / (curr['lactate'] - prev['lactate'])
            power_at_threshold = prev['avg_watts'] + ratio * (curr['avg_watts'] - prev['avg_watts'])
            hr_at_threshold = prev['avg_hr'] + ratio * (curr['avg_hr'] - prev['avg_hr'])

            return {
                'power': round(power_at_threshold, 0),
                'hr': round(hr_at_threshold, 0),
                'between_steps': (prev['step'], curr['step']),
                'lactate_before': prev['lactate'],
                'lactate_after': curr['lactate']
            }

    # Check if all readings are below threshold
    max_lactate = results_with_lactate['lactate'].max()
    if max_lactate < threshold:
        # Get power at max lactate and highest tested power
        max_lactate_row = results_with_lactate[results_with_lactate['lactate'] == max_lactate].iloc[0]
        return {
            'not_reached': True,
            'max_lactate': max_lactate,
            'power_at_max_lactate': max_lactate_row['avg_watts'],
            'highest_power_tested': results_with_lactate['avg_watts'].max(),
            'lactate_at_highest': results_with_lactate[results_with_lactate['avg_watts'] == results_with_lactate['avg_watts'].max()].iloc[0]['lactate']
        }

    return None


def print_analysis(workout: pd.Series, results: pd.DataFrame, zone2_ceiling: dict, max_hr: int = None):
    """Print formatted analysis."""
    print()
    print("=" * 90)
    print("LACTATE STEP TEST ANALYSIS")
    print("=" * 90)
    print()
    print(f"Date: {workout['start_time_local']}")
    print(f"Duration: {workout['duration_s'] / 60:.1f} min")
    print(f"Workout ID: {workout['workout_id']}")
    if workout.get('notes'):
        print(f"Notes (lactate): {workout['notes']}")
    print()

    # Results table
    print(f"{'Step':<6} {'Time':<14} {'Duration':<10} {'Power':<10} {'Avg HR':<10} {'End HR':<10} {'Lactate':<12}")
    print("-" * 90)

    for _, row in results.iterrows():
        lactate_str = f"{row['lactate']:.1f} mmol/L" if row['lactate'] else "-"
        print(f"{row['step']:<6} {row['time_range']:<14} {row['duration_min']} min      {row['avg_watts']:.0f}W       {row['avg_hr']:.0f}        {row['end_hr']:.0f}        {lactate_str}")

    print("-" * 90)
    print()

    # Zone 2 analysis
    print("ZONE 2 ANALYSIS")
    print("-" * 40)

    if max_hr:
        print(f"Max HR: {max_hr} bpm")
        results_with_hr = results[results['avg_hr'].notna()]
        if len(results_with_hr) > 0:
            last = results_with_hr.iloc[-1]
            pct = (last['avg_hr'] / max_hr) * 100
            print(f"Final step HR: {last['avg_hr']:.0f} bpm ({pct:.0f}% of max)")

    if zone2_ceiling:
        if zone2_ceiling.get('not_reached'):
            print()
            print(f"Zone 2 ceiling NOT REACHED")
            print(f"  Highest power tested: {zone2_ceiling['highest_power_tested']:.0f}W @ {zone2_ceiling['lactate_at_highest']:.1f} mmol/L")
            print(f"  Max lactate seen: {zone2_ceiling['max_lactate']:.1f} mmol/L @ {zone2_ceiling['power_at_max_lactate']:.0f}W")
            print(f"  Recommendation: Extend test to higher power levels")
        else:
            print()
            print(f"Zone 2 ceiling (lactate = 2.0 mmol/L):")
            print(f"  Power: ~{zone2_ceiling['power']:.0f}W")
            print(f"  HR: ~{zone2_ceiling['hr']:.0f} bpm")
            print(f"  Found between steps {zone2_ceiling['between_steps'][0]} and {zone2_ceiling['between_steps'][1]}")
            print(f"  Lactate: {zone2_ceiling['lactate_before']:.1f} → {zone2_ceiling['lactate_after']:.1f} mmol/L")

    print()

    # Training recommendations
    results_with_lactate = results[results['lactate'].notna()]
    if len(results_with_lactate) > 0:
        below_2 = results_with_lactate[results_with_lactate['lactate'] < 2.0]
        if len(below_2) > 0:
            max_z2_power = below_2['avg_watts'].max()
            print("TRAINING RECOMMENDATION")
            print("-" * 40)
            if zone2_ceiling and not zone2_ceiling.get('not_reached'):
                ceiling = zone2_ceiling['power']
                print(f"Zone 2 range: ~{ceiling * 0.75:.0f}W - {ceiling - 5:.0f}W")
                print(f"Target for Zone 2 training: {ceiling * 0.9:.0f}W - {ceiling - 5:.0f}W")
            else:
                print(f"Confirmed Zone 2: up to {max_z2_power:.0f}W (lactate {zone2_ceiling['lactate_at_highest']:.1f} mmol/L)")
                print(f"Suggested training while awaiting follow-up: {max_z2_power - 5:.0f}W - {max_z2_power:.0f}W")
                print()
                print("FOLLOW-UP TEST PROTOCOL")
                print("-" * 40)
                start_power = int(max_z2_power)
                print(f"Warmup: {start_power - 20}W x 10 min")
                print(f"Baseline: {start_power}W x 5 min → confirm lactate ~1.2")
                for i, p in enumerate(range(start_power + 10, start_power + 50, 10), 1):
                    print(f"Step {i}: {p}W x 5 min → reading")
                print("Stop when lactate crosses 2.0 mmol/L")

    print()
    print("=" * 90)


def main():
    parser = argparse.ArgumentParser(description="Analyze lactate step test")
    parser.add_argument("--date", help="Workout date (YYYY-MM-DD)")
    parser.add_argument("--workout-id", help="Specific workout ID")
    parser.add_argument("--max-hr", type=int, default=155, help="Your max heart rate (default: 155)")
    parser.add_argument("--warmup", type=int, default=8, help="Warmup duration in minutes to skip (default: 8)")
    parser.add_argument("--lactate", help="Override lactate readings (comma-separated, e.g., '1.2,1.4,1.8,2.1')")
    args = parser.parse_args()

    # Load data
    workout, strokes = load_workout(workout_id=args.workout_id, date=args.date)

    # Parse lactate from notes or args
    if args.lactate:
        lactate_readings = [float(x.strip()) for x in args.lactate.split(',')]
    elif workout.get('notes') and isinstance(workout['notes'], str):
        try:
            lactate_readings = [float(x.strip()) for x in workout['notes'].split(',')]
        except ValueError:
            lactate_readings = []
    else:
        lactate_readings = []

    # Detect steps and analyze
    steps, by_min = detect_steps(strokes, warmup_minutes=args.warmup)
    results = analyze_steps(strokes, steps, lactate_readings)

    # Find Zone 2 ceiling
    zone2_ceiling = find_zone2_ceiling(results, threshold=2.0)

    # Print analysis
    print_analysis(workout, results, zone2_ceiling, max_hr=args.max_hr)

    return results, zone2_ceiling


if __name__ == "__main__":
    main()
