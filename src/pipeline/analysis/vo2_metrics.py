"""
VO₂ stimulus calculation based on HR recovery dynamics and respiratory rate.

Implements Geepy's framework for measuring VO₂ training quality:
- HR_drop during easy intervals (autonomic recovery collapse)
- Respiratory rate as direct proxy for ventilatory demand

Phase classification:
- Early: HR_drop >= 8 bpm (good parasympathetic recovery)
- Mid: HR_drop 3-8 bpm (transitional)
- Late: HR_drop <= 2 bpm (autonomic collapse = VO₂ stimulus zone)

Respiratory rate thresholds:
- Low: < 30 br/min (aerobic, below threshold)
- Moderate: 30-38 br/min (threshold zone)
- High: >= 38 br/min (VO₂ stimulus zone)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import duckdb
import numpy as np
import pandas as pd


def calculate_hr_drop(
    workout_df: pd.DataFrame,
    warmup_min: float = 10.0,
    interval_duration: float = 30.0,
) -> pd.DataFrame:
    """
    Calculate HR_drop for each easy interval in a 30/30 session.

    Parameters:
        workout_df: Stroke-level data with columns ['time_cumulative_s', 'heart_rate_bpm']
        warmup_min: Minutes to skip (warmup period)
        interval_duration: Duration of each interval in seconds

    Returns:
        DataFrame with columns:
            - interval_number
            - hard_hr: Avg HR during hard interval
            - easy_hr: Avg HR during easy interval
            - hr_drop: Decrease in HR during easy interval
            - phase: 'Early', 'Mid', or 'Late'
    """
    if workout_df.empty:
        return pd.DataFrame()

    # Convert to minutes for easier calculation
    df = workout_df.copy()
    df["time_min"] = df["time_cumulative_s"] / 60.0

    # Skip warmup
    work_df = df[df["time_min"] >= warmup_min].copy()
    work_df["elapsed_min"] = work_df["time_min"] - warmup_min

    if work_df.empty:
        return pd.DataFrame()

    results = []
    interval_min = interval_duration / 60.0
    cycle_min = interval_min * 2  # hard + easy = 1 minute for 30/30

    # Determine number of complete intervals
    total_work_min = work_df["elapsed_min"].max()
    num_intervals = int(total_work_min / cycle_min)

    for i in range(num_intervals):
        # Hard interval: i * cycle_min to i * cycle_min + interval_min
        hard_start = i * cycle_min
        hard_end = hard_start + interval_min

        # Easy interval: follows hard
        easy_start = hard_end
        easy_end = easy_start + interval_min

        hard_data = work_df[
            (work_df["elapsed_min"] >= hard_start) & (work_df["elapsed_min"] < hard_end)
        ]
        easy_data = work_df[
            (work_df["elapsed_min"] >= easy_start) & (work_df["elapsed_min"] < easy_end)
        ]

        if len(hard_data) < 3 or len(easy_data) < 3:
            continue

        hard_hr = hard_data["heart_rate_bpm"].mean()
        easy_hr = easy_data["heart_rate_bpm"].mean()
        hr_drop = hard_hr - easy_hr

        # Classify phase based on HR_drop
        if hr_drop >= 8:
            phase = "Early"
        elif hr_drop >= 3:
            phase = "Mid"
        else:
            phase = "Late"  # VO₂ stimulus zone

        results.append(
            {
                "interval_number": i + 1,
                "hard_hr": hard_hr,
                "easy_hr": easy_hr,
                "hr_drop": hr_drop,
                "phase": phase,
            }
        )

    return pd.DataFrame(results)


def calculate_vo2_stimulus_time(
    hr_drop_df: pd.DataFrame,
    interval_duration: float = 30.0,
) -> dict:
    """
    Calculate VO₂ stimulus metrics from HR drop analysis.

    Returns:
        dict with keys:
            - vo2_stimulus_min: Minutes in Late phase (HR_drop <= 2)
            - time_to_late_phase_min: Minutes until first Late phase interval
            - late_phase_intervals: Number of intervals in Late phase
            - total_intervals: Total number of intervals
    """
    if hr_drop_df.empty:
        return {
            "vo2_stimulus_min": 0,
            "time_to_late_phase_min": None,
            "late_phase_intervals": 0,
            "total_intervals": 0,
        }

    late_phase = hr_drop_df[hr_drop_df["phase"] == "Late"]
    late_phase_intervals = len(late_phase)

    # VO₂ stimulus time = Late phase intervals * interval duration
    vo2_stimulus_min = (late_phase_intervals * interval_duration) / 60.0

    # Time to late phase = first Late phase interval number * cycle time
    if not late_phase.empty:
        first_late_interval = late_phase.iloc[0]["interval_number"]
        time_to_late_phase_min = first_late_interval  # Each cycle is ~1 min for 30/30
    else:
        time_to_late_phase_min = None

    return {
        "vo2_stimulus_min": vo2_stimulus_min,
        "time_to_late_phase_min": time_to_late_phase_min,
        "late_phase_intervals": late_phase_intervals,
        "total_intervals": len(hr_drop_df),
    }


def calculate_respiratory_vo2_metrics(
    resp_df: pd.DataFrame,
    warmup_min: float = 10.0,
    high_resp_threshold: float = 38.0,
) -> dict:
    """
    Calculate VO₂ stimulus metrics from respiratory rate data.

    Respiratory rate >= 38 br/min indicates high ventilatory demand
    characteristic of VO₂ stimulus zone.

    Parameters:
        resp_df: DataFrame with 'window_center_min' and 'respiratory_rate' columns
        warmup_min: Minutes to skip (warmup period)
        high_resp_threshold: Respiratory rate threshold for VO₂ zone (br/min)

    Returns:
        dict with keys:
            - vo2_stimulus_min: Minutes with high respiratory rate
            - avg_respiratory_rate: Average respiratory rate during work
            - max_respiratory_rate: Peak respiratory rate
            - time_to_high_resp_min: Time to first high respiratory rate window
    """
    if resp_df.empty:
        return {
            "vo2_stimulus_min": 0,
            "avg_respiratory_rate": None,
            "max_respiratory_rate": None,
            "time_to_high_resp_min": None,
        }

    # Filter to work period (after warmup)
    work_resp = resp_df[resp_df["window_center_min"] >= warmup_min].copy()

    if work_resp.empty:
        return {
            "vo2_stimulus_min": 0,
            "avg_respiratory_rate": None,
            "max_respiratory_rate": None,
            "time_to_high_resp_min": None,
        }

    # High respiratory rate windows
    high_resp = work_resp[work_resp["respiratory_rate"] >= high_resp_threshold]

    # Estimate time in high resp zone (assuming 15-30s windows)
    # Each window represents ~15-30 seconds depending on step size
    window_duration_min = 0.5  # Approximate
    vo2_stimulus_min = len(high_resp) * window_duration_min

    # Time to first high respiratory rate
    if not high_resp.empty:
        first_high = high_resp.iloc[0]["window_center_min"]
        time_to_high_resp_min = first_high - warmup_min
    else:
        time_to_high_resp_min = None

    return {
        "vo2_stimulus_min": vo2_stimulus_min,
        "avg_respiratory_rate": float(work_resp["respiratory_rate"].mean()),
        "max_respiratory_rate": float(work_resp["respiratory_rate"].max()),
        "time_to_high_resp_min": time_to_high_resp_min,
    }


def analyze_vo2_session(
    workout_id: str,
    warmup_min: float = 10.0,
    interval_duration: float = 30.0,
) -> dict:
    """
    Comprehensive VO₂ session analysis combining HR drop and respiratory rate.

    Parameters:
        workout_id: Concept2 workout ID
        warmup_min: Warmup duration in minutes
        interval_duration: Interval duration in seconds (30 for 30/30)

    Returns:
        dict with comprehensive VO₂ metrics
    """
    con = duckdb.connect()

    # Get stroke data for HR drop analysis
    strokes = con.execute(
        f"""
        SELECT time_cumulative_s, heart_rate_bpm
        FROM read_parquet('Data/Parquet/cardio_strokes/**/*.parquet')
        WHERE workout_id = '{workout_id}'
          AND heart_rate_bpm IS NOT NULL
        ORDER BY time_cumulative_s
    """
    ).df()

    # Get respiratory rate data if available (from Polar)
    try:
        resp = con.execute(
            f"""
            SELECT window_center_min, respiratory_rate, avg_hr
            FROM read_parquet('Data/Parquet/polar_respiratory/**/*.parquet')
            WHERE workout_id = '{workout_id}'
            ORDER BY window_center_min
        """
        ).df()
    except Exception:
        resp = pd.DataFrame()

    # Calculate HR drop metrics
    hr_drop_df = calculate_hr_drop(strokes, warmup_min, interval_duration)
    hr_metrics = calculate_vo2_stimulus_time(hr_drop_df, interval_duration)

    # Calculate respiratory metrics if available
    if not resp.empty:
        resp_metrics = calculate_respiratory_vo2_metrics(resp, warmup_min)
        has_respiratory_data = True
    else:
        resp_metrics = {
            "vo2_stimulus_min": None,
            "avg_respiratory_rate": None,
            "max_respiratory_rate": None,
            "time_to_high_resp_min": None,
        }
        has_respiratory_data = False

    # Combine results
    return {
        "workout_id": workout_id,
        "warmup_min": warmup_min,
        "interval_duration_sec": interval_duration,
        # HR drop metrics
        "hr_drop": {
            "total_intervals": hr_metrics["total_intervals"],
            "late_phase_intervals": hr_metrics["late_phase_intervals"],
            "vo2_stimulus_min": hr_metrics["vo2_stimulus_min"],
            "time_to_late_phase_min": hr_metrics["time_to_late_phase_min"],
            "interval_details": hr_drop_df.to_dict("records") if not hr_drop_df.empty else [],
        },
        # Respiratory metrics
        "respiratory": {
            "has_data": has_respiratory_data,
            "vo2_stimulus_min": resp_metrics["vo2_stimulus_min"],
            "avg_rate": resp_metrics["avg_respiratory_rate"],
            "max_rate": resp_metrics["max_respiratory_rate"],
            "time_to_high_resp_min": resp_metrics["time_to_high_resp_min"],
        },
        # Combined assessment
        "primary_metric": "respiratory" if has_respiratory_data else "hr_drop",
        "vo2_stimulus_min": (
            resp_metrics["vo2_stimulus_min"]
            if has_respiratory_data and resp_metrics["vo2_stimulus_min"]
            else hr_metrics["vo2_stimulus_min"]
        ),
    }


def query_weekly_vo2_metrics(end_date: datetime, days: int = 7) -> dict:
    """
    Query VO₂ metrics for the past N days.

    Returns:
        dict with weekly aggregate metrics
    """
    start_date = end_date - timedelta(days=days)
    con = duckdb.connect()

    # Find 30/30 workouts (duration 25-40 min, characteristic of this protocol)
    workouts = con.execute(
        f"""
        SELECT workout_id, start_time_utc, duration_s
        FROM read_parquet('Data/Parquet/workouts/**/*.parquet')
        WHERE source = 'Concept2'
          AND start_time_utc >= '{start_date}'
          AND start_time_utc <= '{end_date}'
          AND duration_s BETWEEN 1500 AND 2400  -- 25-40 min
        ORDER BY start_time_utc DESC
    """
    ).df()

    total_vo2_stimulus_min = 0
    sessions_with_respiratory = 0
    all_sessions = []

    for _, workout in workouts.iterrows():
        metrics = analyze_vo2_session(workout["workout_id"])
        all_sessions.append(metrics)

        if metrics["vo2_stimulus_min"]:
            total_vo2_stimulus_min += metrics["vo2_stimulus_min"]

        if metrics["respiratory"]["has_data"]:
            sessions_with_respiratory += 1

    return {
        "period_days": days,
        "sessions_analyzed": len(workouts),
        "sessions_with_respiratory": sessions_with_respiratory,
        "weekly_vo2_stimulus_min": total_vo2_stimulus_min,
        "sessions": all_sessions,
    }


def compare_hr_drop_vs_respiratory(workout_id: str) -> pd.DataFrame:
    """
    Compare HR drop and respiratory rate metrics for validation.

    Returns DataFrame with interval-by-interval comparison.
    """
    metrics = analyze_vo2_session(workout_id)

    if not metrics["respiratory"]["has_data"]:
        return pd.DataFrame({"error": ["No respiratory data available"]})

    hr_intervals = pd.DataFrame(metrics["hr_drop"]["interval_details"])

    # Get respiratory data aligned to intervals
    con = duckdb.connect()
    resp = con.execute(
        f"""
        SELECT window_center_min, respiratory_rate
        FROM read_parquet('Data/Parquet/polar_respiratory/**/*.parquet')
        WHERE workout_id = '{workout_id}'
        ORDER BY window_center_min
    """
    ).df()

    warmup = metrics["warmup_min"]

    # Align respiratory rate to intervals
    comparison = []
    for _, interval in hr_intervals.iterrows():
        interval_start = warmup + (interval["interval_number"] - 1)
        interval_end = interval_start + 1

        interval_resp = resp[
            (resp["window_center_min"] >= interval_start)
            & (resp["window_center_min"] < interval_end)
        ]

        avg_resp = interval_resp["respiratory_rate"].mean() if len(interval_resp) > 0 else None

        comparison.append(
            {
                "interval": interval["interval_number"],
                "hr_drop": interval["hr_drop"],
                "hr_phase": interval["phase"],
                "respiratory_rate": avg_resp,
                "resp_zone": (
                    "High"
                    if avg_resp and avg_resp >= 38
                    else "Moderate"
                    if avg_resp and avg_resp >= 30
                    else "Low"
                    if avg_resp
                    else None
                ),
            }
        )

    return pd.DataFrame(comparison)
