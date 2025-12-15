#!/usr/bin/env python3
"""
Calculate sleep debt and recovery metrics from Oura/Apple Health data.

Outputs:
- Rolling 7-day sleep debt
- Daily sleep quality breakdown (deep, REM, total)
- HRV trends for recovery assessment

Usage:
    python analysis/scripts/calculate_sleep_metrics.py
    python analysis/scripts/calculate_sleep_metrics.py --days 30
    python analysis/scripts/calculate_sleep_metrics.py --baseline 8.0
"""
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

# Paths
DATA_DIR = Path("Data/Parquet")
OUTPUT_DIR = Path("analysis/outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_sleep_data() -> pd.DataFrame:
    """Load sleep data from minute_facts parquet."""
    mf = pq.read_table(DATA_DIR / "minute_facts").to_pandas()

    # Filter to rows with sleep data
    sleep_cols = [
        "timestamp_utc",
        "sleep_total_hr",
        "sleep_deep_hr",
        "sleep_rem_hr",
        "sleep_core_hr",
        "sleep_awake_hr",
        "sleep_in_bed_hr",
        "sleep_score",
        "hrv_ms",
        "resting_hr_bpm",
    ]

    df = mf[sleep_cols].copy()
    df["date"] = pd.to_datetime(df["timestamp_utc"]).dt.date

    # Aggregate to daily (take max for cumulative fields)
    daily = df.groupby("date").agg({
        "sleep_total_hr": "max",
        "sleep_deep_hr": "max",
        "sleep_rem_hr": "max",
        "sleep_core_hr": "max",
        "sleep_awake_hr": "max",
        "sleep_in_bed_hr": "max",
        "sleep_score": "max",
        "hrv_ms": "mean",  # Average HRV readings for the day
        "resting_hr_bpm": "min",  # Lowest resting HR
    }).reset_index()

    daily["date"] = pd.to_datetime(daily["date"])
    return daily.sort_values("date")


def calculate_sleep_debt(
    df: pd.DataFrame,
    baseline_hours: float = 7.5,
) -> pd.DataFrame:
    """
    Calculate rolling 7-day sleep debt.

    Sleep debt = cumulative deficit from baseline over rolling window.
    Positive = debt (undersleeping), Negative = surplus (oversleeping).

    Args:
        df: DataFrame with date and sleep_total_hr columns
        baseline_hours: Personal sleep need baseline (default 7.5)

    Returns:
        DataFrame with sleep debt calculations added
    """
    df = df.copy()

    # Daily deficit (positive = undersleep)
    df["daily_deficit_hr"] = baseline_hours - df["sleep_total_hr"]

    # Rolling 7-day sleep debt
    df["sleep_debt_7d_hr"] = df["daily_deficit_hr"].rolling(7, min_periods=1).sum()

    # Rolling averages for context
    df["sleep_avg_7d_hr"] = df["sleep_total_hr"].rolling(7, min_periods=1).mean()
    df["deep_sleep_avg_7d_hr"] = df["sleep_deep_hr"].rolling(7, min_periods=1).mean()
    df["hrv_avg_7d_ms"] = df["hrv_ms"].rolling(7, min_periods=1).mean()

    # Sleep efficiency (time asleep / time in bed)
    df["sleep_efficiency_pct"] = (
        df["sleep_total_hr"] / df["sleep_in_bed_hr"] * 100
    ).clip(0, 100)

    return df


def determine_recovery_state(row: pd.Series) -> str:
    """
    Classify recovery state based on sleep metrics.

    Returns: OPTIMAL, MODERATE, POOR, or UNKNOWN
    """
    debt = row.get("sleep_debt_7d_hr", 0) or 0
    total = row.get("sleep_total_hr")
    deep = row.get("sleep_deep_hr")

    # Unknown if no sleep data for the day
    if pd.isna(total):
        # Fall back to debt-only assessment
        if debt > 7:
            return "POOR"
        elif debt < 3:
            return "MODERATE"
        return "MODERATE"

    total = total or 0
    deep = deep or 0

    # Poor: high sleep debt OR very low sleep last night
    if debt > 7 or total < 5:
        return "POOR"

    # Optimal: low debt AND good sleep quality
    if debt < 3 and total >= 7 and deep >= 1.5:
        return "OPTIMAL"

    return "MODERATE"


def print_summary(df: pd.DataFrame, baseline: float, days: int):
    """Print sleep metrics summary."""
    recent = df.tail(days)
    latest = df.iloc[-1] if len(df) > 0 else None

    print(f"\n{'='*60}")
    print("SLEEP METRICS SUMMARY")
    print(f"{'='*60}")
    print(f"Baseline sleep need: {baseline} hours")
    print(f"Analysis period: {days} days")
    print(f"Date range: {recent['date'].min().date()} to {recent['date'].max().date()}")

    if latest is not None:
        print(f"\n--- Last Night ({latest['date'].date()}) ---")
        print(f"  Total sleep: {latest['sleep_total_hr']:.1f} hr")
        print(f"  Deep sleep:  {latest['sleep_deep_hr']:.1f} hr")
        print(f"  REM sleep:   {latest['sleep_rem_hr']:.1f} hr")
        print(f"  Efficiency:  {latest['sleep_efficiency_pct']:.0f}%")
        if pd.notna(latest.get("hrv_ms")):
            print(f"  HRV:         {latest['hrv_ms']:.0f} ms")

        print(f"\n--- 7-Day Rolling ---")
        print(f"  Sleep debt:  {latest['sleep_debt_7d_hr']:.1f} hr", end="")
        if latest['sleep_debt_7d_hr'] > 5:
            print(" ⚠️  HIGH")
        elif latest['sleep_debt_7d_hr'] < 0:
            print(" ✅ SURPLUS")
        else:
            print(" ✓")
        print(f"  Avg sleep:   {latest['sleep_avg_7d_hr']:.1f} hr/night")
        print(f"  Avg deep:    {latest['deep_sleep_avg_7d_hr']:.1f} hr/night")
        if pd.notna(latest.get("hrv_avg_7d_ms")):
            print(f"  Avg HRV:     {latest['hrv_avg_7d_ms']:.0f} ms")

        recovery = determine_recovery_state(latest)
        emoji = {"OPTIMAL": "🟢", "MODERATE": "🟡", "POOR": "🔴"}[recovery]
        print(f"\n  Recovery State: {emoji} {recovery}")

    # Trends
    print(f"\n--- {days}-Day Trends ---")
    print(f"  Avg total sleep: {recent['sleep_total_hr'].mean():.1f} hr")
    print(f"  Avg deep sleep:  {recent['sleep_deep_hr'].mean():.1f} hr")
    print(f"  Min sleep night: {recent['sleep_total_hr'].min():.1f} hr")
    print(f"  Max sleep night: {recent['sleep_total_hr'].max():.1f} hr")

    # Days below threshold
    poor_nights = (recent["sleep_total_hr"] < 6).sum()
    good_nights = (recent["sleep_total_hr"] >= 7).sum()
    print(f"  Nights < 6hr:    {poor_nights}")
    print(f"  Nights >= 7hr:   {good_nights}")


def main():
    parser = argparse.ArgumentParser(description="Calculate sleep debt metrics")
    parser.add_argument(
        "--days", type=int, default=30, help="Days to analyze (default: 30)"
    )
    parser.add_argument(
        "--baseline",
        type=float,
        default=7.5,
        help="Sleep baseline in hours (default: 7.5)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output CSV filename (default: sleep_metrics_YYYYMMDD.csv)",
    )
    args = parser.parse_args()

    print("Loading sleep data from minute_facts...")
    df = load_sleep_data()
    print(f"  Found {len(df)} days of sleep data")
    print(f"  Date range: {df['date'].min().date()} to {df['date'].max().date()}")

    print(f"\nCalculating sleep debt (baseline: {args.baseline} hr)...")
    df = calculate_sleep_debt(df, baseline_hours=args.baseline)

    # Add recovery state
    df["recovery_state"] = df.apply(determine_recovery_state, axis=1)

    # Print summary
    print_summary(df, args.baseline, args.days)

    # Save output
    timestamp = datetime.now().strftime("%Y%m%d")
    output_name = args.output or f"sleep_metrics_{timestamp}.csv"
    output_path = OUTPUT_DIR / output_name

    # Select columns for output
    output_cols = [
        "date",
        "sleep_total_hr",
        "sleep_deep_hr",
        "sleep_rem_hr",
        "sleep_efficiency_pct",
        "daily_deficit_hr",
        "sleep_debt_7d_hr",
        "sleep_avg_7d_hr",
        "hrv_ms",
        "hrv_avg_7d_ms",
        "resting_hr_bpm",
        "recovery_state",
    ]
    df[output_cols].to_csv(output_path, index=False)
    print(f"\n✅ Output saved: {output_path}")

    return df


if __name__ == "__main__":
    main()
