#!/usr/bin/env python3
import argparse
import warnings
from datetime import datetime

import pandas as pd

# Suppress warnings from mean() of empty slice
warnings.filterwarnings("ignore", category=RuntimeWarning)


def _format_dt_to_seconds(value) -> str:
    """Format any datetime-like value to 'YYYY-MM-DD HH:MM:SS'."""
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    try:
        dt = pd.to_datetime(value, errors="coerce")
        if pd.isna(dt):
            return str(value)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def analyze_workout(
    workout: pd.Series,
    all_strokes: pd.DataFrame,
    all_lactate: pd.DataFrame,
) -> None:
    """
    Analyze a single workout using its stroke data and lactate measurements.
    """

    workout_id = workout["workout_id"]
    source = workout.get("source", "Unknown")
    workout_type = workout.get("workout_type", "Unknown")
    timezone = workout.get("timezone", "Unknown")
    duration = workout.get("duration_s")
    distance = workout.get("distance_m")

    # --- Load stroke data for this workout first (for optional HR fallback) ---
    if all_strokes is not None and not all_strokes.empty:
        workout_strokes = all_strokes[all_strokes["workout_id"] == workout_id].copy()
    else:
        workout_strokes = pd.DataFrame()

    # --- HR from workouts schema (aligned with schema.py) ---
    avg_hr = workout.get("avg_hr_bpm")
    max_hr = workout.get("max_hr_bpm")

    # Optional fallback to stroke-level HR if workout-level HR is missing
    if (
        workout_strokes is not None
        and not workout_strokes.empty
        and "heart_rate_bpm" in workout_strokes.columns
    ):
        if avg_hr is None or pd.isna(avg_hr):
            avg_hr = float(workout_strokes["heart_rate_bpm"].mean())
        if max_hr is None or pd.isna(max_hr):
            max_hr = float(workout_strokes["heart_rate_bpm"].max())

    avg_hr_str = (
        f"{avg_hr:.1f} bpm" if avg_hr is not None and not pd.isna(avg_hr) else "n/a"
    )
    max_hr_str = (
        f"{max_hr:.1f} bpm" if max_hr is not None and not pd.isna(max_hr) else "n/a"
    )

    # --- Start time formatting to seconds ---
    start_local_raw = workout.get("start_time_local")
    start_local_str = (
        _format_dt_to_seconds(start_local_raw) if start_local_raw is not None else "Unknown"
    )

    print("\n" + "#" * 70)
    print(f"WORKOUT: {workout_id} [{source}]")
    print("#" * 70)
    print(f"Type:        {workout_type}")
    print(f"Start local: {start_local_str} ({timezone})")
    print(f"Duration:    {duration} s")
    print(f"Distance:    {distance} m")
    print(f"Avg HR:      {avg_hr_str}")
    print(f"Max HR:      {max_hr_str}")

    # --- Part 1: Stroke data ---
    if workout_strokes.empty:
        print("\n(no stroke data for this workout)")
    else:
        print("\nStroke-level data:")
        print(
            f"- Rows: {len(workout_strokes)}, "
            f"columns: {', '.join(workout_strokes.columns)}"
        )

        has_pace = "pace_s_per_500m" in workout_strokes.columns
        has_watts = "watts" in workout_strokes.columns
        has_hr_col = "heart_rate_bpm" in workout_strokes.columns

        if has_pace:
            avg_pace = workout_strokes["pace_s_per_500m"].mean()
            if pd.notna(avg_pace):
                avg_pace_str = pd.to_datetime(avg_pace, unit="s").strftime(
                    "%M:%S.%f"
                )[:-5]
                print(f"- Avg pace:  {avg_pace_str} / 500m")

        if has_watts:
            avg_watts = workout_strokes["watts"].mean()
            print(f"- Avg watts: {avg_watts:.1f}")

        if has_hr_col:
            avg_stroke_hr = workout_strokes["heart_rate_bpm"].mean()
            max_stroke_hr = workout_strokes["heart_rate_bpm"].max()
            print(
                f"- Stroke HR: avg={avg_stroke_hr:.1f} bpm, "
                f"max={max_stroke_hr:.1f} bpm"
            )

    # --- Part 2: Lactate measurements ---
    if all_lactate is not None and not all_lactate.empty:
        lactate_rows = all_lactate[all_lactate["workout_id"] == workout_id].copy()
    else:
        lactate_rows = pd.DataFrame()

    if lactate_rows.empty:
        print("\n(no lactate measurements for this workout)")
    else:
        print("\nLactate measurements:")
        display_cols = [
            c
            for c in lactate_rows.columns
            if c
            in {
                "measurement_time_local",
                "minutes_post",
                "lactate_mmol_L",
                "notes",
            }
        ]
        df_lac = lactate_rows[display_cols].copy()
        for col in df_lac.columns:
            if pd.api.types.is_datetime64_any_dtype(df_lac[col]):
                df_lac[col] = df_lac[col].dt.strftime("%Y-%m-%d %H:%M:%S")
        print(df_lac.to_string(index=False))

    # --- Part 3: Additional sanity checks / debugging aids ---
    if not workout_strokes.empty:
        print("\nColumn sample from stroke data:")

        df_sample = workout_strokes.head(3).copy()

        # Format datetimes to seconds, round watts and other floats nicely
        for col in df_sample.columns:
            if pd.api.types.is_datetime64_any_dtype(df_sample[col]):
                df_sample[col] = df_sample[col].dt.strftime("%Y-%m-%d %H:%M:%S")
            elif col == "watts":
                df_sample[col] = df_sample[col].round(1)
            elif col in {
                "time_cumulative_s",
                "distance_cumulative_m",
                "pace_500m_cs",
                "heart_rate_bpm",
                "stroke_rate_spm",
            }:
                df_sample[col] = df_sample[col].round(1)

        print(df_sample.to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze Concept2 workouts (rower or bike) using HDP Parquet data. "
            "By default, analyzes ALL workouts; optionally filter by date and type."
        )
    )
    parser.add_argument(
        "--date",
        help=(
            "Filter workouts by local date (YYYY-MM-DD), based on start_time_local "
            "(e.g., 2025-11-16)."
        ),
    )
    parser.add_argument(
        "--type",
        choices=["Rowing", "Cycling", "All"],
        default="All",
        help="Filter by workout_type; defaults to All.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on number of workouts to analyze (after filters).",
    )

    args = parser.parse_args()
    target_date = args.date
    type_filter = args.type
    limit = args.limit

    print("Loading data...")
    try:
        all_workouts = pd.read_parquet("Data/Parquet/workouts")
        all_strokes = pd.read_parquet("Data/Parquet/cardio_strokes")
        all_lactate = pd.read_parquet("Data/Parquet/lactate")
        print("Data loaded.")
    except Exception as e:
        print(f"❌ Failed to load Parquet files: {e}")
        print("Please run ingestion first.")
        return

    # --- Filter by date if provided ---
    if target_date:
        print(f"\nFiltering workouts to local date: {target_date}")
        if "start_time_local" in all_workouts.columns:
            if not pd.api.types.is_datetime64_any_dtype(all_workouts["start_time_local"]):
                all_workouts["start_time_local"] = pd.to_datetime(
                    all_workouts["start_time_local"], errors="coerce"
                )
            all_workouts["start_date"] = all_workouts["start_time_local"].dt.strftime(
                "%Y-%m-%d"
            )
            mask = all_workouts["start_date"] == target_date
        else:
            print(
                "❌ 'start_time_local' column is missing; can't filter by date reliably."
            )
            print(
                "   (The 'date' column is a monthly partition key, "
                "not the true workout date.)"
            )
            return

        all_workouts = all_workouts[mask].copy()
        if all_workouts.empty:
            print(f"❌ No workouts found on {target_date}")
            return
        else:
            print(f"✅ Found {len(all_workouts)} workout(s) on {target_date}")

    # --- Filter by type, if requested ---
    if type_filter != "All":
        before = len(all_workouts)
        all_workouts = all_workouts[
            all_workouts["workout_type"] == type_filter
        ].copy()
        if all_workouts.empty:
            print(f"❌ No {type_filter} workouts found with current filters.")
            return
        else:
            print(
                f"✅ {len(all_workouts)} {type_filter} workouts after type filter "
                f"(from {before} total filtered workouts)."
            )

    # Apply limit if provided
    if limit is not None and limit > 0:
        if "start_time_utc" in all_workouts.columns:
            all_workouts = all_workouts.sort_values("start_time_utc").head(limit)
        else:
            all_workouts = all_workouts.head(limit)

    # --- Sort and analyze ALL matching workouts ---
    if "start_time_utc" in all_workouts.columns:
        all_workouts = all_workouts.sort_values("start_time_utc")
    else:
        all_workouts = all_workouts.sort_index()

    print("\n" + "#" * 70)
    print(f"Analyzing {len(all_workouts)} workout(s)...")
    print("#" * 70)

    for _, w in all_workouts.iterrows():
        analyze_workout(w, all_strokes, all_lactate)


if __name__ == "__main__":
    main()
