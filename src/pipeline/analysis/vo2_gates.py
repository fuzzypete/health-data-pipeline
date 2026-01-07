"""
Three-gate VO₂ stimulus detection.

Implements the 3-gate convergence model for detecting true VO₂ stimulus:
- Gate 1: Cardiovascular Load (HR ≥ 90% session max)
- Gate 2: Ventilatory Engagement (RR elevated + fails to recover)
- Gate 3: Recovery Impairment (HR_drop ≤ 2.5 bpm)

Multi-signal convergence provides high confidence detection.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def detect_gate1_hr_load(
    strokes_df: pd.DataFrame,
    warmup_sec: float = 120.0,
    hr_threshold_pct: float = 0.90,
) -> pd.DataFrame:
    """
    Gate 1: Cardiovascular Load

    Detects when HR ≥ 90% of session max (post-warmup).

    Args:
        strokes_df: Stroke data with 'time_cumulative_s', 'heart_rate_bpm'
        warmup_sec: Seconds to skip for warmup (default 2 min)
        hr_threshold_pct: Percentage of max HR for threshold (default 90%)

    Returns:
        DataFrame with time windows and gate1_active boolean
    """
    if strokes_df.empty or "heart_rate_bpm" not in strokes_df.columns:
        return pd.DataFrame()

    df = strokes_df.copy()

    # Get session max HR (after warmup)
    post_warmup = df[df["time_cumulative_s"] > warmup_sec]
    if post_warmup.empty:
        return pd.DataFrame()

    session_max_hr = post_warmup["heart_rate_bpm"].max()
    hr_threshold = session_max_hr * hr_threshold_pct

    # Mark periods where HR meets threshold
    df["gate1_active"] = df["heart_rate_bpm"] >= hr_threshold
    df["session_max_hr"] = session_max_hr
    df["hr_threshold"] = hr_threshold

    return df[["time_cumulative_s", "heart_rate_bpm", "gate1_active", "session_max_hr", "hr_threshold"]]


def detect_gate2_rr_engagement(
    resp_df: pd.DataFrame,
    zone2_baseline_rr_med: float = 22.0,  # Typical Z2 baseline
    zone2_baseline_rr_mad: float = 2.0,   # Typical Z2 variability
    warmup_min: float = 10.0,
    interval_duration_sec: float = 30.0,
) -> pd.DataFrame:
    """
    Gate 2: Ventilatory Engagement (Geepy's Merged Specification)

    Primary: ELEVATED_AND_FAILING
    - RR elevated above Z2 baseline
    - RR fails to drop during easy intervals

    Secondary: CHAOTIC (optional enhancer)
    - RR variability exceeds Z2 baseline chaos

    Args:
        resp_df: Respiratory data with 'window_center_min', 'respiratory_rate'
        zone2_baseline_rr_med: Median RR from lactate-verified Z2 sessions
        zone2_baseline_rr_mad: MAD of RR from Z2 sessions
        warmup_min: Warmup duration in minutes
        interval_duration_sec: Easy interval duration (default 30s)

    Returns:
        DataFrame with interval-level gate status
    """
    if resp_df.empty or "respiratory_rate" not in resp_df.columns:
        return pd.DataFrame()

    # Preprocessing: 15s rolling median to strip jitter
    df = resp_df.copy()
    df["rr_smoothed"] = (
        df["respiratory_rate"]
        .rolling(window=3, min_periods=1, center=True)
        .median()
    )

    # Filter to work period
    work_resp = df[df["window_center_min"] >= warmup_min].copy()
    if work_resp.empty:
        return pd.DataFrame()

    # Personalized thresholds
    rr_hi = zone2_baseline_rr_med + max(6, 3 * zone2_baseline_rr_mad)
    rr_drop_min = max(1.5, 2 * zone2_baseline_rr_mad)
    rr_var_hi = max(2.0, 2 * zone2_baseline_rr_mad)

    results = []

    # Analyze each 1-minute interval block
    max_elapsed = work_resp["window_center_min"].max() - warmup_min
    interval_count = int(max_elapsed)

    for i in range(interval_count):
        # Easy interval: starts at 0.5 min into each cycle
        easy_start = warmup_min + i * 1.0 + 0.5
        easy_end = easy_start + 0.5

        easy_windows = work_resp[
            (work_resp["window_center_min"] >= easy_start)
            & (work_resp["window_center_min"] <= easy_end)
        ]

        if len(easy_windows) < 2:
            continue

        # RR at start/end of easy interval
        rr_start_e = easy_windows.iloc[0]["rr_smoothed"]
        rr_end_e = easy_windows.iloc[-1]["rr_smoothed"]
        rr_drop_e = rr_start_e - rr_end_e
        rr_mean_e = easy_windows["rr_smoothed"].median()

        # Primary condition: ELEVATED_AND_FAILING
        elevated = rr_mean_e >= rr_hi
        failing = rr_drop_e <= rr_drop_min
        elevated_and_failing = elevated and failing

        # Secondary condition: CHAOTIC
        chaos_window = work_resp[
            (work_resp["window_center_min"] >= easy_start - 0.5)
            & (work_resp["window_center_min"] <= easy_end + 0.5)
        ]

        if len(chaos_window) >= 3:
            rr_median = chaos_window["rr_smoothed"].median()
            rr_mad = (chaos_window["rr_smoothed"] - rr_median).abs().median()
            chaotic = rr_mad >= rr_var_hi
        else:
            chaotic = False

        # Final Gate 2 decision
        gate2_active = elevated_and_failing or chaotic

        results.append(
            {
                "interval_number": i + 1,
                "interval_start_min": easy_start,
                "interval_end_min": easy_end,
                "rr_mean": rr_mean_e,
                "rr_drop": rr_drop_e,
                "rr_threshold": rr_hi,
                "elevated": elevated,
                "failing_to_recover": failing,
                "elevated_and_failing": elevated_and_failing,
                "chaotic": chaotic,
                "gate2_active": gate2_active,
            }
        )

    return pd.DataFrame(results)


def detect_gate3_recovery_impairment(
    strokes_df: pd.DataFrame,
    warmup_sec: float = 600.0,  # 10 min warmup for 30/30
    interval_duration_sec: float = 30.0,
    hr_drop_threshold: float = 2.5,
) -> pd.DataFrame:
    """
    Gate 3: Recovery Impairment

    Detects when HR_drop ≤ 2.5 bpm during 30s easy intervals.

    Args:
        strokes_df: Stroke data with 'time_cumulative_s', 'heart_rate_bpm'
        warmup_sec: Warmup duration in seconds
        interval_duration_sec: Easy interval duration
        hr_drop_threshold: HR drop threshold for impairment

    Returns:
        DataFrame with interval-level gate status
    """
    if strokes_df.empty:
        return pd.DataFrame()

    df = strokes_df.copy()
    results = []

    # Total work duration
    total_duration = df["time_cumulative_s"].max()
    work_start = warmup_sec

    # Each cycle is 60s (30s work + 30s easy)
    cycle_duration = interval_duration_sec * 2
    work_duration = total_duration - work_start
    interval_count = int(work_duration / cycle_duration)

    for i in range(interval_count):
        # Easy interval starts at work_start + i*60 + 30
        easy_start = work_start + i * cycle_duration + interval_duration_sec
        easy_end = easy_start + interval_duration_sec

        # Get HR at start/end of easy interval
        hr_start_rows = df[
            (df["time_cumulative_s"] >= easy_start)
            & (df["time_cumulative_s"] < easy_start + 5)
        ]
        hr_end_rows = df[
            (df["time_cumulative_s"] >= easy_end - 5)
            & (df["time_cumulative_s"] <= easy_end)
        ]

        if hr_start_rows.empty or hr_end_rows.empty:
            continue

        hr_start = hr_start_rows["heart_rate_bpm"].mean()
        hr_end = hr_end_rows["heart_rate_bpm"].mean()
        hr_drop = hr_start - hr_end

        # Gate 3 active if HR_drop ≤ threshold (recovery impaired)
        gate3_active = hr_drop <= hr_drop_threshold

        results.append(
            {
                "interval_number": i + 1,
                "interval_start_min": easy_start / 60,
                "interval_end_min": easy_end / 60,
                "hr_start": hr_start,
                "hr_end": hr_end,
                "hr_drop": hr_drop,
                "hr_drop_threshold": hr_drop_threshold,
                "gate3_active": gate3_active,
            }
        )

    return pd.DataFrame(results)
