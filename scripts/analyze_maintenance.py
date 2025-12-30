#!/usr/bin/env python3
"""
Analyze calorie maintenance state using nutrition, weight, and performance data.

Detects maintenance state by analyzing:
- Nutrition intake (diet_calories_kcal from daily_summary)
- Body weight trends (weight_lb from daily_summary)
- Performance validation (power output at Zone 2 HR from Concept2 workouts)
- Strength training validation (estimated 1RM trends from resistance training)
- Protocol context (supplements/medications affecting weight interpretation)

Outputs:
- Parquet: analysis/outputs/maintenance_analysis.parquet
- CSV: analysis/outputs/maintenance_analysis_{YYYYMMDD}.csv
- Console: Summary stats with current state assessment

Usage:
    python scripts/analyze_maintenance.py
    python scripts/analyze_maintenance.py --start-date 2025-09-01 --end-date 2025-12-01
    python scripts/analyze_maintenance.py --output-dir /custom/path
"""
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import duckdb
import pandas as pd


# Constants
DATA_DIR = Path("Data/Parquet")
DEFAULT_OUTPUT_DIR = Path("analysis/outputs")

# Thresholds
MIN_CALORIES_ABSOLUTE = 800  # Suspicious if below this (unless fasting)
MIN_CALORIES_RATIO = 0.5  # Suspicious if below 50% of 30-day avg
MAINTENANCE_BALANCE_THRESHOLD = 250  # cal/day for maintenance detection
MAINTENANCE_CONSECUTIVE_DAYS = 14  # Days needed to confirm maintenance
ZONE2_HR_MIN = 120
ZONE2_HR_MAX = 140
POWER_DECLINE_THRESHOLD = 0.05  # 5% decline flags concern
STRENGTH_DECLINE_THRESHOLD = 0.05  # 5% decline in estimated 1RM
MIN_EXERCISE_SESSIONS = 3  # Minimum sessions to track an exercise

# Weight-affecting compound categories for protocol context
WEIGHT_AFFECTING_COMPOUNDS = {
    'GLP1': {
        'compounds': ['Retatrutide', 'Semaglutide', 'Tirzepatide', 'Ozempic', 'Wegovy', 'Mounjaro'],
        'effect': 'Suppresses appetite, affects TDEE estimation',
        'weight_impact': 'loss',
    },
    'SGLT2i': {
        'compounds': ['Brenzavvy', 'bexagliflozin', 'Jardiance', 'empagliflozin', 'Farxiga', 'dapagliflozin'],
        'effect': 'Causes glycosuria and 2-4 lb water loss initially',
        'weight_impact': 'loss',
    },
    'AAS': {
        'compounds': ['Testosterone', 'Anavar', 'Masteron', 'Nandrolone', 'Proviron', 'Primobolan'],
        'effect': 'Affects muscle retention and water balance',
        'weight_impact': 'variable',
    },
    'Creatine': {
        'compounds': ['Creatine'],
        'effect': 'Causes 3-5 lb water retention (stable long-term)',
        'weight_impact': 'gain',
    },
    'HGH': {
        'compounds': ['HGH', 'Somatropin'],
        'effect': 'Can cause water retention',
        'weight_impact': 'gain',
    },
    'Diuretic': {
        'compounds': ['Furosemide', 'Hydrochlorothiazide', 'Spironolactone'],
        'effect': 'Causes water loss',
        'weight_impact': 'loss',
    },
}


@dataclass
class MaintenanceResult:
    """Container for maintenance analysis results."""
    df: pd.DataFrame
    incomplete_days: pd.DataFrame
    summary: dict


def get_daily_data(
    conn: duckdb.DuckDBPyConnection,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Load daily nutrition and weight data from daily_summary parquet.

    Handles multiple sources by taking the most recent entry per date.
    """
    date_filter = ""
    if start_date:
        date_filter += f" AND date_utc >= '{start_date}'"
    if end_date:
        date_filter += f" AND date_utc <= '{end_date}'"

    query = f"""
    WITH ranked AS (
        SELECT
            date_utc as date,
            diet_calories_kcal as calories,
            protein_g,
            carbs_g,
            total_fat_g,
            weight_lb,
            source,
            ROW_NUMBER() OVER (
                PARTITION BY date_utc
                ORDER BY ingest_time_utc DESC
            ) as rn
        FROM read_parquet('{DATA_DIR}/daily_summary/**/*.parquet')
        WHERE 1=1 {date_filter}
    )
    SELECT
        date,
        calories,
        protein_g,
        carbs_g,
        total_fat_g,
        weight_lb,
        source
    FROM ranked
    WHERE rn = 1
    ORDER BY date
    """

    return conn.execute(query).df()


def get_workout_power(
    conn: duckdb.DuckDBPyConnection,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Get average power from Zone 2 Concept2 workouts.

    Calculates average watts from cardio_strokes for workouts where
    overall avg HR is in Zone 2 range (120-140 bpm).
    """
    date_filter = ""
    if start_date:
        date_filter += f" AND w.start_time_utc >= '{start_date}'"
    if end_date:
        date_filter += f" AND w.start_time_utc <= '{end_date}'::DATE + INTERVAL '1 day'"

    query = f"""
    WITH stroke_power AS (
        SELECT
            workout_id,
            AVG(watts) as avg_watts,
            COUNT(*) as stroke_count
        FROM read_parquet('{DATA_DIR}/cardio_strokes/**/*.parquet')
        WHERE watts IS NOT NULL AND watts > 0
        GROUP BY workout_id
    )
    SELECT
        DATE_TRUNC('day', w.start_time_utc)::DATE as date,
        w.erg_type,
        w.avg_hr_bpm,
        sp.avg_watts,
        w.duration_s
    FROM read_parquet('{DATA_DIR}/workouts/**/*.parquet') w
    JOIN stroke_power sp ON w.workout_id = sp.workout_id
    WHERE w.source = 'Concept2'
      AND w.avg_hr_bpm BETWEEN {ZONE2_HR_MIN} AND {ZONE2_HR_MAX}
      AND sp.avg_watts > 0
      {date_filter}
    ORDER BY date
    """

    return conn.execute(query).df()


def get_strength_data(
    conn: duckdb.DuckDBPyConnection,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Get resistance training data with estimated 1RM per exercise per session.

    Uses Brzycki formula: 1RM = weight × (36 / (37 - reps))
    Simplified approximation: 1RM = weight × (1 + reps/30)
    """
    date_filter = ""
    if start_date:
        date_filter += f" AND workout_start_utc >= '{start_date}'"
    if end_date:
        date_filter += f" AND workout_start_utc <= '{end_date}'::DATE + INTERVAL '1 day'"

    query = f"""
    WITH set_data AS (
        SELECT
            workout_id,
            DATE_TRUNC('day', workout_start_utc)::DATE as workout_date,
            exercise_name,
            weight_lbs,
            actual_reps,
            -- Estimated 1RM using simplified Brzycki formula
            weight_lbs * (1 + actual_reps / 30.0) as estimated_1rm
        FROM read_parquet('{DATA_DIR}/resistance_sets/**/*.parquet')
        WHERE weight_lbs > 0
          AND actual_reps > 0
          AND actual_reps <= 20  -- Exclude very high rep sets (less accurate 1RM)
          {date_filter}
    ),
    -- Get best estimated 1RM per exercise per session
    session_best AS (
        SELECT
            workout_id,
            workout_date,
            exercise_name,
            MAX(estimated_1rm) as best_1rm,
            MAX(weight_lbs) as max_weight,
            COUNT(*) as sets_count
        FROM set_data
        GROUP BY workout_id, workout_date, exercise_name
    ),
    -- Filter to exercises with enough sessions
    exercise_counts AS (
        SELECT exercise_name, COUNT(DISTINCT workout_id) as session_count
        FROM session_best
        GROUP BY exercise_name
        HAVING COUNT(DISTINCT workout_id) >= {MIN_EXERCISE_SESSIONS}
    )
    SELECT
        sb.workout_date,
        sb.exercise_name,
        sb.best_1rm,
        sb.max_weight,
        sb.sets_count
    FROM session_best sb
    JOIN exercise_counts ec ON sb.exercise_name = ec.exercise_name
    ORDER BY sb.exercise_name, sb.workout_date
    """

    return conn.execute(query).df()


def calculate_strength_trends(strength_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate rolling strength trends per exercise.

    Returns DataFrame with exercise-level 14-day rolling 1RM averages
    and decline detection.
    """
    if len(strength_df) == 0:
        return pd.DataFrame()

    results = []

    for exercise in strength_df['exercise_name'].unique():
        ex_df = strength_df[strength_df['exercise_name'] == exercise].copy()
        ex_df = ex_df.sort_values('workout_date')

        # Need at least 2 data points to calculate trend
        if len(ex_df) < 2:
            continue

        # Calculate rolling 14-day average (by session, not calendar day)
        # Use window of last 3 sessions as proxy for ~2 weeks
        ex_df['rolling_1rm_avg'] = ex_df['best_1rm'].rolling(3, min_periods=2).mean()

        # Compare to prior period
        ex_df['prior_1rm_avg'] = ex_df['rolling_1rm_avg'].shift(3)
        ex_df['change_pct'] = (
            (ex_df['rolling_1rm_avg'] - ex_df['prior_1rm_avg']) / ex_df['prior_1rm_avg']
        )

        # Flag decline > threshold
        ex_df['declining'] = ex_df['change_pct'] < -STRENGTH_DECLINE_THRESHOLD

        results.append(ex_df)

    if not results:
        return pd.DataFrame()

    return pd.concat(results, ignore_index=True)


def add_strength_data(
    df: pd.DataFrame,
    strength_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add strength training metrics to main dataframe.

    Aggregates across exercises to create a daily strength decline flag.
    """
    if len(strength_df) == 0:
        df['exercises_declining'] = 0
        df['strength_decline_flag'] = False
        return df

    # Calculate strength trends
    trends_df = calculate_strength_trends(strength_df)

    if len(trends_df) == 0:
        df['exercises_declining'] = 0
        df['strength_decline_flag'] = False
        return df

    # Aggregate to daily: count exercises showing decline on each day
    daily_strength = trends_df.groupby('workout_date').agg({
        'declining': 'sum',  # Count of declining exercises
        'exercise_name': 'count'  # Total exercises trained
    }).reset_index()
    daily_strength.columns = ['date', 'exercises_declining', 'exercises_trained']

    # Merge with main dataframe
    df['date'] = pd.to_datetime(df['date'])
    daily_strength['date'] = pd.to_datetime(daily_strength['date'])
    df = df.merge(daily_strength[['date', 'exercises_declining']], on='date', how='left')

    # Fill NaN with 0 for days without strength training
    df['exercises_declining'] = df['exercises_declining'].fillna(0).astype(int)

    # Forward fill the decline count for context (up to 14 days)
    # Replace 0 with NaN, forward fill, then back to 0
    temp = df['exercises_declining'].where(df['exercises_declining'] > 0)
    temp = temp.ffill(limit=14).fillna(0)
    df['exercises_declining_recent'] = temp.astype(int)

    # Flag concerning pattern: exercises declining while weight stable
    df['strength_decline_flag'] = (
        (df['exercises_declining_recent'] >= 2) &  # 2+ exercises declining
        (df['weight_change_7d'].abs() < 1.0)  # Weight stable within 1 lb
    )

    # Clean up
    df = df.drop(columns=['exercises_declining_recent'], errors='ignore')

    return df


def get_strength_summary(strength_df: pd.DataFrame) -> dict:
    """
    Generate summary statistics for strength training.
    """
    if len(strength_df) == 0:
        return {}

    trends_df = calculate_strength_trends(strength_df)
    if len(trends_df) == 0:
        return {}

    summary = {}

    # Count exercises tracked
    summary['exercises_tracked'] = trends_df['exercise_name'].nunique()
    summary['total_sessions'] = trends_df['workout_date'].nunique()

    # Get latest status per exercise
    latest_by_exercise = trends_df.groupby('exercise_name').last().reset_index()

    declining = latest_by_exercise[latest_by_exercise['declining'] == True]
    improving = latest_by_exercise[latest_by_exercise['change_pct'] > STRENGTH_DECLINE_THRESHOLD]
    stable = latest_by_exercise[
        (latest_by_exercise['change_pct'].abs() <= STRENGTH_DECLINE_THRESHOLD) &
        (latest_by_exercise['declining'] == False)
    ]

    summary['exercises_declining'] = len(declining)
    summary['exercises_improving'] = len(improving)
    summary['exercises_stable'] = len(stable)

    # List of declining exercises
    if len(declining) > 0:
        summary['declining_list'] = declining['exercise_name'].tolist()

    return summary


def get_protocol_data(
    conn: duckdb.DuckDBPyConnection,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Get protocol history data for the analysis period.

    Returns protocols that were active at any point during the period.
    """
    date_filter = ""
    if start_date:
        date_filter += f" AND (end_date IS NULL OR end_date >= '{start_date}')"
    if end_date:
        date_filter += f" AND start_date <= '{end_date}'"

    query = f"""
    SELECT
        compound_name,
        compound_type,
        start_date,
        end_date,
        dosage,
        dosage_unit,
        frequency,
        notes
    FROM read_parquet('{DATA_DIR}/protocol_history/**/*.parquet')
    WHERE 1=1 {date_filter}
    ORDER BY compound_name, start_date
    """

    return conn.execute(query).df()


def _match_compound_category(compound_name: str) -> Optional[str]:
    """Check if a compound matches any weight-affecting category."""
    compound_lower = compound_name.lower()
    for category, info in WEIGHT_AFFECTING_COMPOUNDS.items():
        for comp in info['compounds']:
            if comp.lower() in compound_lower:
                return category
    return None


def get_protocol_context(
    protocol_df: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> dict:
    """
    Analyze protocols for weight-affecting compounds and changes.

    Returns dict with:
    - active_weight_compounds: list of weight-affecting compounds active
    - protocol_changes: list of changes during period
    - analysis_confidence: HIGH/MODERATE/LOW based on protocol stability
    - warnings: specific warnings about confounders
    """
    context = {
        'active_weight_compounds': [],
        'protocol_changes': [],
        'dose_changes': [],
        'warnings': [],
        'analysis_confidence': 'HIGH',
    }

    if len(protocol_df) == 0:
        return context

    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)

    # Find weight-affecting compounds that were active during the period
    for _, row in protocol_df.iterrows():
        category = _match_compound_category(row['compound_name'])
        if category:
            compound_info = {
                'compound': row['compound_name'],
                'category': category,
                'effect': WEIGHT_AFFECTING_COMPOUNDS[category]['effect'],
                'start_date': row['start_date'],
                'end_date': row['end_date'],
                'dosage': f"{row['dosage']} {row['dosage_unit']}" if pd.notna(row['dosage']) else 'unknown',
            }
            context['active_weight_compounds'].append(compound_info)

    # Detect protocol changes (starts/stops) during the analysis period
    for compound in protocol_df['compound_name'].unique():
        comp_rows = protocol_df[protocol_df['compound_name'] == compound].sort_values('start_date')

        for _, row in comp_rows.iterrows():
            row_start = pd.to_datetime(row['start_date'])
            row_end = pd.to_datetime(row['end_date']) if pd.notna(row['end_date']) else None

            # Check if this compound started during the period
            if start_dt <= row_start <= end_dt:
                category = _match_compound_category(compound)
                if category:
                    context['protocol_changes'].append({
                        'type': 'START',
                        'compound': compound,
                        'category': category,
                        'date': row['start_date'],
                        'dosage': f"{row['dosage']} {row['dosage_unit']}" if pd.notna(row['dosage']) else None,
                    })

            # Check if this compound stopped during the period
            if row_end and start_dt <= row_end <= end_dt:
                category = _match_compound_category(compound)
                if category:
                    context['protocol_changes'].append({
                        'type': 'STOP',
                        'compound': compound,
                        'category': category,
                        'date': row['end_date'],
                    })

        # Check for dose changes (multiple entries for same compound)
        if len(comp_rows) > 1:
            category = _match_compound_category(compound)
            if category:
                for i in range(1, len(comp_rows)):
                    prev = comp_rows.iloc[i-1]
                    curr = comp_rows.iloc[i]
                    if pd.to_datetime(curr['start_date']) >= start_dt:
                        if prev['dosage'] != curr['dosage']:
                            context['dose_changes'].append({
                                'compound': compound,
                                'category': category,
                                'date': curr['start_date'],
                                'from_dose': f"{prev['dosage']} {prev['dosage_unit']}",
                                'to_dose': f"{curr['dosage']} {curr['dosage_unit']}",
                            })

    # Generate warnings for specific confounders
    for comp in context['active_weight_compounds']:
        if comp['category'] == 'SGLT2i':
            # Check if started recently (within 14 days of analysis start)
            if pd.notna(comp['start_date']):
                comp_start = pd.to_datetime(comp['start_date'])
                if comp_start >= start_dt - pd.Timedelta(days=14):
                    context['warnings'].append(
                        f"SGLT2i ({comp['compound']}) started recently - expect 2-4 lb water loss"
                    )

        if comp['category'] == 'GLP1':
            context['warnings'].append(
                f"GLP-1 agonist ({comp['compound']}) active - appetite suppression affects TDEE estimates"
            )

    # Determine analysis confidence
    num_changes = len(context['protocol_changes']) + len(context['dose_changes'])
    if num_changes >= 5:
        context['analysis_confidence'] = 'LOW'
    elif num_changes >= 2 or len(context['warnings']) > 0:
        context['analysis_confidence'] = 'MODERATE'
    else:
        context['analysis_confidence'] = 'HIGH'

    return context


def detect_incomplete_days(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag days with suspicious calorie entries.

    Flags days where:
    - Calories < 50% of 30-day rolling average
    - OR Calories < 800 (unless potentially fasting)

    Returns DataFrame with flagged dates and reason codes.
    """
    df = df.copy()

    # Calculate 30-day rolling average for reference
    df['calories_30d_avg'] = df['calories'].rolling(30, min_periods=7).mean()

    # Flag incomplete days
    incomplete_flags = []

    for idx, row in df.iterrows():
        flags = []
        cal = row['calories']
        avg_30d = row['calories_30d_avg']

        if pd.isna(cal):
            flags.append('NO_ENTRY')
        elif cal < MIN_CALORIES_ABSOLUTE:
            flags.append(f'LOW_ABSOLUTE (<{MIN_CALORIES_ABSOLUTE})')
        elif pd.notna(avg_30d) and cal < avg_30d * MIN_CALORIES_RATIO:
            flags.append(f'LOW_VS_AVG (<{MIN_CALORIES_RATIO*100:.0f}% of {avg_30d:.0f})')

        if flags:
            incomplete_flags.append({
                'date': row['date'],
                'calories': cal,
                'calories_30d_avg': avg_30d,
                'reason_codes': '; '.join(flags)
            })

    return pd.DataFrame(incomplete_flags)


def calculate_rolling_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate rolling energy balance metrics.

    Computes:
    - 7-day rolling averages for intake and weight
    - Implied daily energy balance from weight change
    - Estimated TDEE
    """
    df = df.copy()

    # 7-day rolling averages
    df['avg_intake_7d'] = df['calories'].rolling(7, min_periods=4).mean()
    df['avg_weight_7d'] = df['weight_lb'].rolling(7, min_periods=3).mean()

    # Weight from 7 days ago (for balance calculation)
    df['weight_7d_ago'] = df['weight_lb'].shift(7)

    # Implied daily balance: (weight change over 7 days) * 3500 cal/lb / 7 days
    # Positive = surplus, Negative = deficit
    df['weight_change_7d'] = df['avg_weight_7d'] - df['avg_weight_7d'].shift(7)
    df['implied_balance'] = (df['weight_change_7d'] * 3500) / 7

    # Estimate TDEE: average intake adjusted for weight change
    # TDEE = intake - implied_balance (if gaining, TDEE < intake)
    df['est_tdee'] = df['avg_intake_7d'] - df['implied_balance']

    return df


def detect_maintenance_periods(df: pd.DataFrame) -> pd.DataFrame:
    """
    Identify periods of caloric maintenance.

    Maintenance defined as:
    - abs(implied_balance) < 250 cal/day for 14+ consecutive days
    """
    df = df.copy()

    # Check if in maintenance (low implied balance)
    df['in_maintenance_range'] = (
        df['implied_balance'].abs() < MAINTENANCE_BALANCE_THRESHOLD
    )

    # Count consecutive maintenance days
    df['maintenance_streak'] = 0
    streak = 0
    for i in range(len(df)):
        if df.iloc[i]['in_maintenance_range']:
            streak += 1
        else:
            streak = 0
        df.iloc[i, df.columns.get_loc('maintenance_streak')] = streak

    # Flag as maintenance if streak >= threshold
    df['maintenance_flag'] = df['maintenance_streak'] >= MAINTENANCE_CONSECUTIVE_DAYS

    return df


def add_performance_data(
    df: pd.DataFrame,
    power_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Add Zone 2 power metrics and calculate rolling average.
    """
    if len(power_df) == 0:
        df['avg_power_7d'] = None
        df['power_decline_flag'] = False
        return df

    # Aggregate to daily (average across workouts if multiple)
    daily_power = power_df.groupby('date').agg({
        'avg_watts': 'mean',
        'erg_type': 'first'  # Take first erg type for the day
    }).reset_index()
    daily_power.columns = ['date', 'daily_avg_watts', 'erg_type']

    # Merge with main dataframe
    df['date'] = pd.to_datetime(df['date'])
    daily_power['date'] = pd.to_datetime(daily_power['date'])
    df = df.merge(daily_power[['date', 'daily_avg_watts']], on='date', how='left')

    # Forward fill power data (only for 7 days) and calculate rolling average
    df['daily_avg_watts_filled'] = df['daily_avg_watts'].ffill(limit=7)
    df['avg_power_7d'] = df['daily_avg_watts_filled'].rolling(7, min_periods=1).mean()

    # Check for power decline while weight stable
    df['power_7d_ago'] = df['avg_power_7d'].shift(7)
    df['power_change_pct'] = (
        (df['avg_power_7d'] - df['power_7d_ago']) / df['power_7d_ago']
    )

    # Flag concerning pattern: stable weight but declining power (deficit masking)
    df['power_decline_flag'] = (
        (df['power_change_pct'] < -POWER_DECLINE_THRESHOLD) &
        (df['weight_change_7d'].abs() < 1.0)  # Weight stable within 1 lb
    )

    # Clean up temp columns
    df = df.drop(columns=['daily_avg_watts_filled', 'power_7d_ago', 'power_change_pct'], errors='ignore')

    return df


def determine_current_state(df: pd.DataFrame, incomplete_days: pd.DataFrame) -> dict:
    """
    Analyze data to determine current maintenance state.
    """
    summary = {}

    # Basic stats
    summary['total_days'] = len(df)
    summary['days_with_calories'] = df['calories'].notna().sum()
    summary['days_with_weight'] = df['weight_lb'].notna().sum()
    summary['incomplete_days_count'] = len(incomplete_days)
    summary['incomplete_pct'] = (
        len(incomplete_days) / len(df) * 100 if len(df) > 0 else 0
    )

    # Date range
    if len(df) > 0:
        summary['date_range_start'] = df['date'].min()
        summary['date_range_end'] = df['date'].max()

    # Recent metrics (last 7 days)
    recent = df.tail(7)
    if len(recent) > 0:
        summary['recent_avg_intake'] = recent['calories'].mean()
        summary['recent_avg_weight'] = recent['weight_lb'].mean()
        summary['recent_implied_balance'] = recent['implied_balance'].mean()
        summary['recent_est_tdee'] = recent['est_tdee'].mean()

    # 30-day trend
    last_30 = df.tail(30)
    if len(last_30) >= 14:
        first_half = last_30.head(15)
        second_half = last_30.tail(15)

        weight_trend = (
            second_half['weight_lb'].mean() - first_half['weight_lb'].mean()
        )
        summary['30d_weight_trend_lb'] = weight_trend

        if weight_trend < -0.5:
            summary['30d_trend'] = 'DEFICIT'
        elif weight_trend > 0.5:
            summary['30d_trend'] = 'SURPLUS'
        else:
            summary['30d_trend'] = 'MAINTENANCE'
    else:
        summary['30d_trend'] = 'INSUFFICIENT_DATA'

    # Current maintenance status
    if len(df) > 0 and 'maintenance_flag' in df.columns:
        summary['currently_in_maintenance'] = df.iloc[-1]['maintenance_flag']
        summary['current_maintenance_streak'] = int(df.iloc[-1]['maintenance_streak'])

    # Performance concerns
    if 'power_decline_flag' in df.columns:
        summary['power_decline_warnings'] = int(df['power_decline_flag'].sum())

    if 'strength_decline_flag' in df.columns:
        summary['strength_decline_warnings'] = int(df['strength_decline_flag'].sum())

    return summary


def print_summary(summary: dict, incomplete_days: pd.DataFrame):
    """Print formatted console summary."""
    print("\n" + "=" * 60)
    print("MAINTENANCE ANALYSIS SUMMARY")
    print("=" * 60)

    # Date range
    if 'date_range_start' in summary:
        print(f"\nDate Range: {summary['date_range_start']} to {summary['date_range_end']}")

    # Data coverage
    print(f"\n--- Data Coverage ---")
    print(f"  Total days analyzed: {summary['total_days']}")
    print(f"  Days with calorie data: {summary['days_with_calories']}")
    print(f"  Days with weight data: {summary['days_with_weight']}")

    # Incomplete days
    print(f"\n--- Data Quality ---")
    print(f"  Incomplete/flagged days: {summary['incomplete_days_count']} ({summary['incomplete_pct']:.1f}%)")

    if len(incomplete_days) > 0:
        print(f"\n  Top 10 flagged days:")
        for _, row in incomplete_days.head(10).iterrows():
            cal_str = f"{row['calories']:.0f}" if pd.notna(row['calories']) else "N/A"
            print(f"    {row['date']}: {cal_str} cal - {row['reason_codes']}")

    # Current state
    print(f"\n--- Current State (Last 7 Days) ---")
    if 'recent_avg_intake' in summary and pd.notna(summary['recent_avg_intake']):
        print(f"  Avg intake: {summary['recent_avg_intake']:.0f} cal/day")
    if 'recent_avg_weight' in summary and pd.notna(summary['recent_avg_weight']):
        print(f"  Avg weight: {summary['recent_avg_weight']:.1f} lb")
    if 'recent_implied_balance' in summary and pd.notna(summary['recent_implied_balance']):
        balance = summary['recent_implied_balance']
        direction = "surplus" if balance > 0 else "deficit"
        print(f"  Implied balance: {abs(balance):.0f} cal/day {direction}")
    if 'recent_est_tdee' in summary and pd.notna(summary['recent_est_tdee']):
        print(f"  Estimated TDEE: {summary['recent_est_tdee']:.0f} cal/day")

    # Maintenance status
    print(f"\n--- Maintenance Status ---")
    if 'currently_in_maintenance' in summary:
        status = "YES" if summary['currently_in_maintenance'] else "NO"
        streak = summary.get('current_maintenance_streak', 0)
        print(f"  Currently in maintenance: {status}")
        print(f"  Current streak: {streak} days (need {MAINTENANCE_CONSECUTIVE_DAYS} for confirmation)")

    # 30-day trend
    if '30d_trend' in summary:
        trend_emoji = {
            'DEFICIT': '📉',
            'SURPLUS': '📈',
            'MAINTENANCE': '➡️',
            'INSUFFICIENT_DATA': '❓'
        }
        trend = summary['30d_trend']
        emoji = trend_emoji.get(trend, '')
        print(f"  30-day trend: {emoji} {trend}")
        if '30d_weight_trend_lb' in summary and pd.notna(summary['30d_weight_trend_lb']):
            print(f"  30-day weight change: {summary['30d_weight_trend_lb']:+.1f} lb")

    # Performance warnings
    has_power_warning = summary.get('power_decline_warnings', 0) > 0
    has_strength_warning = summary.get('strength_decline_warnings', 0) > 0

    if has_power_warning or has_strength_warning:
        print(f"\n--- Performance Warnings ---")
        if has_power_warning:
            print(f"  ⚠️  {summary['power_decline_warnings']} periods of cardio power decline with stable weight")
        if has_strength_warning:
            print(f"  ⚠️  {summary['strength_decline_warnings']} periods of strength decline with stable weight")
        if has_power_warning or has_strength_warning:
            print(f"      (May indicate deficit masking from muscle loss)")

    # Strength training summary
    if 'exercises_tracked' in summary:
        print(f"\n--- Strength Training ---")
        print(f"  Exercises tracked: {summary['exercises_tracked']}")
        print(f"  Sessions in period: {summary['total_sessions']}")
        improving = summary.get('exercises_improving', 0)
        stable = summary.get('exercises_stable', 0)
        declining = summary.get('exercises_declining', 0)
        print(f"  Status: {improving} improving, {stable} stable, {declining} declining")

        if 'declining_list' in summary and summary['declining_list']:
            print(f"  Declining exercises:")
            for ex in summary['declining_list'][:5]:  # Show top 5
                print(f"    - {ex}")
            if len(summary['declining_list']) > 5:
                print(f"    ... and {len(summary['declining_list']) - 5} more")

    # Protocol context
    if 'protocol_context' in summary:
        ctx = summary['protocol_context']
        print(f"\n--- Protocol Context ---")

        # Analysis confidence
        confidence_emoji = {'HIGH': '🟢', 'MODERATE': '🟡', 'LOW': '🔴'}
        conf = ctx.get('analysis_confidence', 'HIGH')
        print(f"  Analysis confidence: {confidence_emoji.get(conf, '')} {conf}")

        # Active weight-affecting compounds
        active = ctx.get('active_weight_compounds', [])
        if active:
            # Deduplicate by compound name (keep latest)
            seen = {}
            for comp in active:
                seen[comp['compound']] = comp
            unique_compounds = list(seen.values())

            print(f"  Weight-affecting compounds active: {len(unique_compounds)}")
            for comp in unique_compounds[:5]:
                print(f"    - {comp['compound']} ({comp['category']}): {comp['dosage']}")
            if len(unique_compounds) > 5:
                print(f"    ... and {len(unique_compounds) - 5} more")

        # Protocol changes during period
        changes = ctx.get('protocol_changes', [])
        dose_changes = ctx.get('dose_changes', [])
        if changes or dose_changes:
            print(f"  Changes during period: {len(changes)} start/stop, {len(dose_changes)} dose changes")
            for change in changes[:3]:
                print(f"    - {change['type']}: {change['compound']} on {change['date']}")
            for dc in dose_changes[:3]:
                print(f"    - DOSE: {dc['compound']} {dc['from_dose']} → {dc['to_dose']} on {dc['date']}")

        # Warnings
        warnings = ctx.get('warnings', [])
        if warnings:
            print(f"  ⚠️  Confounders detected:")
            for w in warnings:
                print(f"    - {w}")

    print("\n" + "=" * 60)


def analyze_maintenance(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> MaintenanceResult:
    """
    Main analysis function.

    Args:
        start_date: Start date (YYYY-MM-DD), defaults to 90 days ago
        end_date: End date (YYYY-MM-DD), defaults to today
        output_dir: Directory for output files

    Returns:
        MaintenanceResult with dataframe, incomplete days, and summary
    """
    # Set defaults
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
    if not start_date:
        start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Analyzing maintenance state from {start_date} to {end_date}...")

    # Connect to DuckDB (in-memory for reading parquet)
    conn = duckdb.connect(':memory:')

    # Load data
    print("\nLoading daily summary data...")
    df = get_daily_data(conn, start_date, end_date)
    print(f"  Loaded {len(df)} days")

    if len(df) == 0:
        print("ERROR: No data found for the specified date range.")
        return MaintenanceResult(
            df=pd.DataFrame(),
            incomplete_days=pd.DataFrame(),
            summary={'error': 'No data found'}
        )

    print("\nLoading Zone 2 workout power data...")
    power_df = get_workout_power(conn, start_date, end_date)
    print(f"  Found {len(power_df)} Zone 2 workouts")

    print("\nLoading strength training data...")
    strength_df = get_strength_data(conn, start_date, end_date)
    exercises_count = strength_df['exercise_name'].nunique() if len(strength_df) > 0 else 0
    sessions_count = strength_df['workout_date'].nunique() if len(strength_df) > 0 else 0
    print(f"  Found {exercises_count} exercises across {sessions_count} sessions")

    print("\nLoading protocol history...")
    protocol_df = get_protocol_data(conn, start_date, end_date)
    print(f"  Found {len(protocol_df)} protocol entries")

    # Close connection
    conn.close()

    # Detect incomplete days
    print("\nDetecting incomplete days...")
    incomplete_days = detect_incomplete_days(df)
    print(f"  Flagged {len(incomplete_days)} days")

    # Calculate rolling metrics
    print("\nCalculating rolling energy balance...")
    df = calculate_rolling_metrics(df)

    # Detect maintenance periods
    print("\nDetecting maintenance periods...")
    df = detect_maintenance_periods(df)

    # Add performance validation
    print("\nAdding cardio performance data...")
    df = add_performance_data(df, power_df)

    # Add strength training validation
    print("\nAdding strength training data...")
    df = add_strength_data(df, strength_df)

    # Determine current state
    summary = determine_current_state(df, incomplete_days)

    # Add strength summary
    strength_summary = get_strength_summary(strength_df)
    summary.update(strength_summary)

    # Add protocol context
    print("\nAnalyzing protocol context...")
    protocol_context = get_protocol_context(protocol_df, start_date, end_date)
    summary['protocol_context'] = protocol_context
    print(f"  Analysis confidence: {protocol_context['analysis_confidence']}")
    if protocol_context['warnings']:
        print(f"  Warnings: {len(protocol_context['warnings'])}")

    # Prepare output columns
    output_cols = [
        'date', 'calories', 'weight_lb', 'avg_intake_7d', 'avg_weight_7d',
        'weight_7d_ago', 'implied_balance', 'est_tdee', 'avg_power_7d',
        'maintenance_flag', 'maintenance_streak', 'power_decline_flag',
        'exercises_declining', 'strength_decline_flag'
    ]
    # Only include columns that exist
    output_cols = [c for c in output_cols if c in df.columns]
    output_df = df[output_cols].copy()

    # Save outputs
    timestamp = datetime.now().strftime('%Y%m%d')

    # Parquet (primary)
    parquet_path = output_dir / 'maintenance_analysis.parquet'
    output_df.to_parquet(parquet_path, index=False)
    print(f"\n✅ Parquet saved: {parquet_path}")

    # CSV (secondary)
    csv_path = output_dir / f'maintenance_analysis_{timestamp}.csv'
    output_df.to_csv(csv_path, index=False)
    print(f"✅ CSV saved: {csv_path}")

    # Incomplete days CSV
    if len(incomplete_days) > 0:
        incomplete_path = output_dir / f'incomplete_days_{timestamp}.csv'
        incomplete_days.to_csv(incomplete_path, index=False)
        print(f"✅ Incomplete days saved: {incomplete_path}")

    # Print summary
    print_summary(summary, incomplete_days)

    return MaintenanceResult(df=output_df, incomplete_days=incomplete_days, summary=summary)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze calorie maintenance state from nutrition and weight data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Analyze last 90 days (default)
    python scripts/analyze_maintenance.py

    # Analyze specific date range
    python scripts/analyze_maintenance.py --start-date 2025-09-01 --end-date 2025-12-01

    # Custom output directory
    python scripts/analyze_maintenance.py --output-dir /tmp/analysis
        """
    )
    parser.add_argument(
        '--start-date',
        type=str,
        default=None,
        help='Start date (YYYY-MM-DD), defaults to 90 days ago'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        default=None,
        help='End date (YYYY-MM-DD), defaults to today'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help='Output directory (default: analysis/outputs)'
    )

    args = parser.parse_args()

    result = analyze_maintenance(
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
    )

    return result


if __name__ == "__main__":
    main()
