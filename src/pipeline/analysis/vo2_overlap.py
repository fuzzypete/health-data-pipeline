"""
Three-gate VO₂ overlap calculation.

Combines Gate 1 (HR Load), Gate 2 (RR Engagement), and Gate 3 (Recovery Impairment)
to determine true VO₂ stimulus time where all gates converge.

Confidence levels:
- 1 gate active:  Approaching VO₂ stimulus
- 2 gates active: Probable VO₂ stimulus
- 3 gates active: True VO₂ stimulus (high confidence)
"""
from __future__ import annotations

from typing import Optional

import duckdb
import numpy as np
import pandas as pd

from .vo2_gates import (
    detect_gate1_hr_load,
    detect_gate2_rr_engagement,
    detect_gate3_recovery_impairment,
)


def calculate_gate_overlap(
    strokes_df: pd.DataFrame,
    resp_df: pd.DataFrame,
    warmup_sec: float = 600.0,
    interval_duration_sec: float = 30.0,
    zone2_baseline_rr_med: float = 22.0,
    zone2_baseline_rr_mad: float = 2.0,
) -> pd.DataFrame:
    """
    Calculate 3-gate overlap for each interval.

    Args:
        strokes_df: Stroke data with 'time_cumulative_s', 'heart_rate_bpm'
        resp_df: Respiratory data with 'window_center_min', 'respiratory_rate'
        warmup_sec: Warmup duration in seconds
        interval_duration_sec: Interval duration (default 30s)
        zone2_baseline_rr_med: Median RR from Z2 baseline
        zone2_baseline_rr_mad: MAD of RR from Z2 baseline

    Returns:
        DataFrame with interval-level gate status and overlap count
    """
    warmup_min = warmup_sec / 60.0

    # Calculate each gate
    gate1_df = detect_gate1_hr_load(
        strokes_df,
        warmup_sec=warmup_sec,
        hr_threshold_pct=0.90,
    )

    gate2_df = detect_gate2_rr_engagement(
        resp_df,
        zone2_baseline_rr_med=zone2_baseline_rr_med,
        zone2_baseline_rr_mad=zone2_baseline_rr_mad,
        warmup_min=warmup_min,
        interval_duration_sec=interval_duration_sec,
    )

    gate3_df = detect_gate3_recovery_impairment(
        strokes_df,
        warmup_sec=warmup_sec,
        interval_duration_sec=interval_duration_sec,
        hr_drop_threshold=2.5,
    )

    # If any gate is empty, return empty result
    if gate2_df.empty and gate3_df.empty:
        return pd.DataFrame()

    # Use gate3 intervals as reference (most granular)
    if gate3_df.empty:
        base_df = gate2_df[["interval_number", "interval_start_min", "interval_end_min"]].copy()
    else:
        base_df = gate3_df[["interval_number", "interval_start_min", "interval_end_min"]].copy()

    results = []

    for _, row in base_df.iterrows():
        interval_num = row["interval_number"]
        interval_start_min = row["interval_start_min"]
        interval_end_min = row["interval_end_min"]

        # Gate 1: Check if HR exceeded threshold during this interval
        if not gate1_df.empty:
            interval_start_sec = interval_start_min * 60
            interval_end_sec = interval_end_min * 60
            gate1_window = gate1_df[
                (gate1_df["time_cumulative_s"] >= interval_start_sec)
                & (gate1_df["time_cumulative_s"] <= interval_end_sec)
            ]
            gate1_active = gate1_window["gate1_active"].any() if not gate1_window.empty else False
            gate1_hr_pct = (
                gate1_window["heart_rate_bpm"].max() / gate1_window["session_max_hr"].iloc[0]
                if not gate1_window.empty and len(gate1_window) > 0
                else None
            )
        else:
            gate1_active = False
            gate1_hr_pct = None

        # Gate 2: Check interval match
        if not gate2_df.empty:
            gate2_row = gate2_df[gate2_df["interval_number"] == interval_num]
            gate2_active = gate2_row["gate2_active"].iloc[0] if not gate2_row.empty else False
            gate2_rr = gate2_row["rr_mean"].iloc[0] if not gate2_row.empty else None
            gate2_elevated = gate2_row["elevated"].iloc[0] if not gate2_row.empty else False
            gate2_failing = gate2_row["failing_to_recover"].iloc[0] if not gate2_row.empty else False
        else:
            gate2_active = False
            gate2_rr = None
            gate2_elevated = False
            gate2_failing = False

        # Gate 3: Check interval match
        if not gate3_df.empty:
            gate3_row = gate3_df[gate3_df["interval_number"] == interval_num]
            gate3_active = gate3_row["gate3_active"].iloc[0] if not gate3_row.empty else False
            gate3_hr_drop = gate3_row["hr_drop"].iloc[0] if not gate3_row.empty else None
        else:
            gate3_active = False
            gate3_hr_drop = None

        # Count active gates
        gates_active = sum([gate1_active, gate2_active, gate3_active])

        # Classify confidence level
        if gates_active == 3:
            confidence = "TRUE_VO2"
        elif gates_active == 2:
            confidence = "PROBABLE"
        elif gates_active == 1:
            confidence = "APPROACHING"
        else:
            confidence = "NONE"

        results.append({
            "interval_number": interval_num,
            "interval_start_min": interval_start_min,
            "interval_end_min": interval_end_min,
            # Gate 1
            "gate1_active": gate1_active,
            "gate1_hr_pct": gate1_hr_pct,
            # Gate 2
            "gate2_active": gate2_active,
            "gate2_rr": gate2_rr,
            "gate2_elevated": gate2_elevated,
            "gate2_failing": gate2_failing,
            # Gate 3
            "gate3_active": gate3_active,
            "gate3_hr_drop": gate3_hr_drop,
            # Overlap
            "gates_active": gates_active,
            "confidence": confidence,
        })

    return pd.DataFrame(results)


def calculate_vo2_stimulus_summary(overlap_df: pd.DataFrame) -> dict:
    """
    Calculate summary metrics from gate overlap analysis.

    Args:
        overlap_df: Output from calculate_gate_overlap()

    Returns:
        dict with summary metrics
    """
    if overlap_df.empty:
        return {
            "total_intervals": 0,
            "true_vo2_intervals": 0,
            "probable_intervals": 0,
            "approaching_intervals": 0,
            "true_vo2_time_min": 0.0,
            "probable_time_min": 0.0,
            "first_true_vo2_interval": None,
            "gate1_active_count": 0,
            "gate2_active_count": 0,
            "gate3_active_count": 0,
        }

    # Interval duration in minutes (assumes 30s intervals = 0.5 min)
    interval_duration_min = 0.5

    # Count intervals by confidence level
    true_vo2 = overlap_df[overlap_df["confidence"] == "TRUE_VO2"]
    probable = overlap_df[overlap_df["confidence"] == "PROBABLE"]
    approaching = overlap_df[overlap_df["confidence"] == "APPROACHING"]

    # First TRUE_VO2 interval
    first_true_vo2 = int(true_vo2.iloc[0]["interval_number"]) if not true_vo2.empty else None

    return {
        "total_intervals": len(overlap_df),
        "true_vo2_intervals": len(true_vo2),
        "probable_intervals": len(probable),
        "approaching_intervals": len(approaching),
        "true_vo2_time_min": len(true_vo2) * interval_duration_min,
        "probable_time_min": len(probable) * interval_duration_min,
        "first_true_vo2_interval": first_true_vo2,
        "gate1_active_count": int(overlap_df["gate1_active"].sum()),
        "gate2_active_count": int(overlap_df["gate2_active"].sum()),
        "gate3_active_count": int(overlap_df["gate3_active"].sum()),
    }


def analyze_vo2_session_3gate(
    workout_id: str,
    warmup_min: float = 10.0,
    interval_duration_sec: float = 30.0,
    zone2_baseline_rr_med: float = 22.0,
    zone2_baseline_rr_mad: float = 2.0,
    data_path: str = "Data/Parquet",
) -> dict:
    """
    Comprehensive 3-gate VO₂ session analysis.

    Args:
        workout_id: Concept2 workout ID
        warmup_min: Warmup duration in minutes
        interval_duration_sec: Interval duration (default 30s for 30/30)
        zone2_baseline_rr_med: Median RR from lactate-verified Z2 sessions
        zone2_baseline_rr_mad: MAD of RR from Z2 sessions
        data_path: Path to Parquet data root

    Returns:
        dict with comprehensive VO₂ metrics using 3-gate model
    """
    warmup_sec = warmup_min * 60.0
    con = duckdb.connect()

    # Get stroke data for HR and Gate 3
    strokes = con.execute(
        f"""
        SELECT time_cumulative_s, heart_rate_bpm
        FROM read_parquet('{data_path}/cardio_strokes/**/*.parquet')
        WHERE workout_id = '{workout_id}'
          AND heart_rate_bpm IS NOT NULL
        ORDER BY time_cumulative_s
    """
    ).df()

    # Get respiratory rate data (from Polar)
    try:
        resp = con.execute(
            f"""
            SELECT window_center_min, respiratory_rate, avg_hr
            FROM read_parquet('{data_path}/polar_respiratory/**/*.parquet')
            WHERE workout_id = '{workout_id}'
            ORDER BY window_center_min
        """
        ).df()
    except Exception:
        resp = pd.DataFrame()

    # Calculate gate overlap
    overlap_df = calculate_gate_overlap(
        strokes,
        resp,
        warmup_sec=warmup_sec,
        interval_duration_sec=interval_duration_sec,
        zone2_baseline_rr_med=zone2_baseline_rr_med,
        zone2_baseline_rr_mad=zone2_baseline_rr_mad,
    )

    # Get summary metrics
    summary = calculate_vo2_stimulus_summary(overlap_df)

    # Session metadata
    session_max_hr = strokes[strokes["time_cumulative_s"] > warmup_sec]["heart_rate_bpm"].max() if not strokes.empty else None
    avg_rr = resp[resp["window_center_min"] >= warmup_min]["respiratory_rate"].mean() if not resp.empty else None
    max_rr = resp[resp["window_center_min"] >= warmup_min]["respiratory_rate"].max() if not resp.empty else None

    return {
        "workout_id": workout_id,
        "warmup_min": warmup_min,
        "interval_duration_sec": interval_duration_sec,
        # Session overview
        "session_max_hr": session_max_hr,
        "avg_respiratory_rate": avg_rr,
        "max_respiratory_rate": max_rr,
        "has_respiratory_data": not resp.empty,
        # 3-gate summary
        "summary": summary,
        # Interval details
        "intervals": overlap_df.to_dict("records") if not overlap_df.empty else [],
        # Z2 baseline used
        "z2_baseline": {
            "rr_median": zone2_baseline_rr_med,
            "rr_mad": zone2_baseline_rr_mad,
        },
    }


def get_zone2_baseline_from_sessions(
    session_ids: Optional[list[str]] = None,
    data_path: str = "Data/Parquet",
) -> dict:
    """
    Calculate Zone 2 baseline RR metrics from lactate-verified sessions.

    Args:
        session_ids: List of workout_ids known to be Z2 (optional)
        data_path: Path to Parquet data root

    Returns:
        dict with z2_rr_median and z2_rr_mad
    """
    con = duckdb.connect()

    if session_ids:
        # Use provided session IDs
        ids_str = "', '".join(session_ids)
        query = f"""
            SELECT respiratory_rate
            FROM read_parquet('{data_path}/polar_respiratory/**/*.parquet')
            WHERE workout_id IN ('{ids_str}')
        """
    else:
        # Find sessions with lactate <= 2.0
        query = f"""
            WITH z2_workouts AS (
                SELECT DISTINCT workout_id
                FROM read_parquet('{data_path}/lactate/**/*.parquet')
                WHERE lactate_mmol <= 2.2
            )
            SELECT r.respiratory_rate
            FROM read_parquet('{data_path}/polar_respiratory/**/*.parquet') r
            INNER JOIN z2_workouts z ON r.workout_id = z.workout_id
        """

    try:
        rr_data = con.execute(query).df()
    except Exception:
        # Return defaults if no data
        return {"z2_rr_median": 22.0, "z2_rr_mad": 2.0}

    if rr_data.empty:
        return {"z2_rr_median": 22.0, "z2_rr_mad": 2.0}

    rr_median = rr_data["respiratory_rate"].median()
    rr_mad = (rr_data["respiratory_rate"] - rr_median).abs().median()

    return {
        "z2_rr_median": float(rr_median),
        "z2_rr_mad": float(rr_mad),
    }
