"""
Lactate measurement extraction utilities.

Extracts lactate readings from comment fields (primarily Concept2).
Supports single readings, multi-reading sessions, and step tests.

Step test detection uses stroke data to identify distinct power plateaus.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa

from pipeline.common.schema import get_schema


def extract_lactate_from_comment(comment: str) -> float | None:
    """
    Extract single lactate reading from comment text.

    Handles patterns like:
    - Bare numbers: "2.1"
    - With text: "Lactate 2.1"
    - Reversed: "1.7 lactate"
    - With punctuation: "Lactate 2.9!"
    - With context: "2.5 lactate . Later . Full fasted"

    Args:
        comment: Comment text to parse

    Returns:
        Lactate value in mmol/L, or None if not found
    """
    if not comment or not isinstance(comment, str):
        return None

    comment = comment.strip()

    # First try: bare number (most common in Concept2 CSV)
    # If comment is just a number (possibly with leading/trailing whitespace)
    if re.match(r"^\d+\.?\d*$", comment):
        try:
            value = float(comment)
            # Sanity check: lactate typically 0.5-20 mmol/L
            if 0.1 <= value <= 25.0:
                return value
        except ValueError:
            pass

    # Second try: text with "lactate" keyword
    patterns = [
        r"lactate\s+(\d+\.?\d*)",  # "Lactate 2.1"
        r"(\d+\.?\d*)\s+lactate",  # "2.1 lactate"
    ]

    comment_lower = comment.lower()

    for pattern in patterns:
        match = re.search(pattern, comment_lower)
        if match:
            try:
                value = float(match.group(1))
                # Sanity check: lactate typically 0.5-20 mmol/L
                if 0.1 <= value <= 25.0:
                    return value
            except (ValueError, IndexError):
                continue

    return None


def is_multi_reading_comment(comment: str) -> bool:
    """
    Detect if a comment contains multiple lactate readings.

    Multi-reading comments have 3+ comma-separated decimal values in lactate range.
    Must be comma-separated to avoid false positives from text like "4/4" or "1 min".
    """
    if not comment or not isinstance(comment, str):
        return False

    # Look for comma-separated decimal numbers (e.g., "1.2, 1.5, 1.9")
    # Must have decimal point to distinguish from other numbers
    # Pattern: number with optional decimal, followed by comma/space, repeated
    comma_values = re.findall(r"(\d+\.\d+)\s*[,\s]\s*", comment + ",")

    if len(comma_values) >= 3:
        try:
            floats = [float(v) for v in comma_values]
            # Lactate values are typically 0.5-12 mmol/L
            valid = [0.5 <= v <= 12.0 for v in floats]
            return sum(valid) >= 3
        except ValueError:
            pass
    return False


def extract_multi_readings(comment: str) -> list[float]:
    """
    Extract multiple lactate readings from a multi-reading comment.

    Args:
        comment: Comment like "1.2, 1.5, 1.9, 2.8, 4.2"

    Returns:
        List of lactate values in order
    """
    if not comment or not isinstance(comment, str):
        return []

    # Extract comma-separated decimal numbers
    # More strict pattern: require decimal point
    values = re.findall(r"(\d+\.\d+)", comment)
    readings = []
    for v in values:
        try:
            f = float(v)
            # Lactate values are typically 0.5-12 mmol/L
            if 0.5 <= f <= 12.0:
                readings.append(f)
        except ValueError:
            continue
    return readings


# Keep old names as aliases for backward compatibility
def is_step_test_comment(comment: str) -> bool:
    """Alias for is_multi_reading_comment for backward compatibility."""
    return is_multi_reading_comment(comment)


def extract_step_test_readings(comment: str) -> list[float]:
    """Alias for extract_multi_readings for backward compatibility."""
    return extract_multi_readings(comment)


def infer_equipment_type(workout_row: pd.Series) -> str | None:
    """Infer equipment type from workout data."""
    erg_type = workout_row.get("erg_type")
    if erg_type:
        mapping = {
            "bike": "BikeErg",
            "rower": "RowErg",
            "skierg": "SkiErg",
        }
        return mapping.get(erg_type.lower())

    workout_type = workout_row.get("workout_type")
    if workout_type:
        if "row" in workout_type.lower():
            return "RowErg"
        elif "bike" in workout_type.lower() or "cycl" in workout_type.lower():
            return "BikeErg"
        elif "ski" in workout_type.lower():
            return "SkiErg"
    return None


def detect_power_steps(
    strokes_df: pd.DataFrame,
    warmup_minutes: int = 8,
    min_step_duration_min: int = 3,
    power_change_threshold: float = 10.0,
) -> list[dict] | None:
    """
    Detect distinct power steps in stroke data.

    A step test has clear power plateaus with significant jumps between them.
    Zone 2 multi-reading sessions have relatively constant power throughout.

    Args:
        strokes_df: Stroke data for a single workout (must have 'time_cumulative_s', 'watts')
        warmup_minutes: Minutes to skip at start (warmup period)
        min_step_duration_min: Minimum duration for a valid step
        power_change_threshold: Minimum watts change to consider a new step

    Returns:
        List of step dicts with avg_watts, start_min, end_min, avg_hr if steps detected.
        None if not a step test (constant power).
    """
    if strokes_df.empty or "watts" not in strokes_df.columns:
        return None

    strokes = strokes_df.copy()
    strokes = strokes.sort_values("time_cumulative_s")

    # Skip warmup
    warmup_seconds = warmup_minutes * 60
    work_strokes = strokes[strokes["time_cumulative_s"] >= warmup_seconds].copy()

    if len(work_strokes) < 100:  # Not enough data
        return None

    # Create minute-by-minute summary
    work_strokes["minute"] = (work_strokes["time_cumulative_s"] // 60).astype(int)

    by_min = work_strokes.groupby("minute").agg({
        "watts": "mean",
        "heart_rate_bpm": "mean",
        "time_cumulative_s": ["min", "max"],
    }).reset_index()
    by_min.columns = ["minute", "watts", "hr", "time_start", "time_end"]

    if len(by_min) < 5:  # Not enough minutes
        return None

    # Detect steps by looking for significant power changes
    steps = []
    current_step = {
        "start_min": int(by_min.iloc[0]["minute"]),
        "watts_sum": by_min.iloc[0]["watts"],
        "hr_sum": by_min.iloc[0]["hr"] if pd.notna(by_min.iloc[0]["hr"]) else 0,
        "count": 1,
    }

    for i in range(1, len(by_min)):
        row = by_min.iloc[i]
        current_avg = current_step["watts_sum"] / current_step["count"]
        power_diff = row["watts"] - current_avg

        # Check if this is a new step (power changed significantly)
        if abs(power_diff) > power_change_threshold:
            # Save current step if it's long enough
            duration = int(row["minute"]) - current_step["start_min"]
            if duration >= min_step_duration_min:
                steps.append({
                    "start_min": current_step["start_min"],
                    "end_min": int(row["minute"]) - 1,
                    "avg_watts": int(round(current_step["watts_sum"] / current_step["count"])),
                    "avg_hr": int(round(current_step["hr_sum"] / current_step["count"])) if current_step["hr_sum"] > 0 else None,
                    "duration_min": duration,
                })

            # Start new step
            current_step = {
                "start_min": int(row["minute"]),
                "watts_sum": row["watts"],
                "hr_sum": row["hr"] if pd.notna(row["hr"]) else 0,
                "count": 1,
            }
        else:
            # Continue current step
            current_step["watts_sum"] += row["watts"]
            current_step["hr_sum"] += row["hr"] if pd.notna(row["hr"]) else 0
            current_step["count"] += 1

    # Don't forget last step
    last_min = int(by_min.iloc[-1]["minute"])
    duration = last_min - current_step["start_min"] + 1
    if duration >= min_step_duration_min:
        steps.append({
            "start_min": current_step["start_min"],
            "end_min": last_min,
            "avg_watts": int(round(current_step["watts_sum"] / current_step["count"])),
            "avg_hr": int(round(current_step["hr_sum"] / current_step["count"])) if current_step["hr_sum"] > 0 else None,
            "duration_min": duration,
        })

    # A step test needs at least 3 distinct steps with increasing power
    if len(steps) < 3:
        return None

    # Check if steps show progression (power should generally increase)
    watts_values = [s["avg_watts"] for s in steps]
    # Allow some variation but overall trend should be upward
    if watts_values[-1] <= watts_values[0]:
        return None  # Power didn't increase overall

    # Check that we have meaningful power spread (at least 30W range)
    power_range = max(watts_values) - min(watts_values)
    if power_range < 30:
        return None  # Not enough variation for a step test

    return steps


def detect_reading_pauses(
    strokes_df: pd.DataFrame,
    num_readings: int,
    min_gap_seconds: float = 15.0,
) -> list[float] | None:
    """
    Detect brief pauses in stroke data where lactate readings were likely taken.

    During a Zone 2 multi-reading session, the athlete briefly stops to take
    a lactate measurement. This creates gaps in the stroke data.

    Args:
        strokes_df: Stroke data with 'time_cumulative_s' column
        num_readings: Expected number of readings to find
        min_gap_seconds: Minimum gap to consider a reading pause

    Returns:
        List of elapsed minutes where readings were taken, or None if not detected.
    """
    if strokes_df.empty or "time_cumulative_s" not in strokes_df.columns:
        return None

    strokes = strokes_df.copy()
    strokes = strokes.sort_values("time_cumulative_s")

    # Calculate time between consecutive strokes
    time_diffs = strokes["time_cumulative_s"].diff()

    # Find significant gaps (longer than min_gap_seconds)
    # Normal stroke intervals are ~2-3 seconds
    gap_mask = time_diffs > min_gap_seconds
    gap_indices = strokes.index[gap_mask].tolist()

    if not gap_indices:
        return None

    # Get the time of each gap (use time at end of gap when reading was taken)
    gap_times = []
    for idx in gap_indices:
        # The gap ends at this index's time (when they resumed)
        # The reading was taken during the gap, so use the time just before resuming
        gap_end_sec = strokes.loc[idx, "time_cumulative_s"]
        gap_times.append(gap_end_sec / 60.0)  # Convert to minutes

    # If we found gaps matching our expected reading count, use them
    # Allow for the final reading at workout end
    if len(gap_times) == num_readings:
        return gap_times
    elif len(gap_times) == num_readings - 1:
        # Last reading was probably at workout end
        total_duration_min = strokes["time_cumulative_s"].max() / 60.0
        gap_times.append(total_duration_min)
        return gap_times

    # If we have more gaps than readings, take the N largest gaps
    if len(gap_times) > num_readings:
        # Get gap durations to pick largest ones
        gaps_with_duration = []
        for idx in gap_indices:
            gap_duration = time_diffs.loc[idx]
            gap_end_time = strokes.loc[idx, "time_cumulative_s"]
            gaps_with_duration.append((gap_end_time / 60.0, gap_duration))

        # Sort by duration (largest gaps) and take top N
        gaps_with_duration.sort(key=lambda x: x[1], reverse=True)
        selected = gaps_with_duration[:num_readings]
        # Sort by time to get chronological order
        selected.sort(key=lambda x: x[0])
        return [g[0] for g in selected]

    return None


def classify_multi_reading_workout(
    workout_id: str,
    num_readings: int,
    strokes_df: pd.DataFrame | None,
) -> tuple[str, list[dict] | None, list[float] | None]:
    """
    Classify a workout with multiple lactate readings.

    Args:
        workout_id: The workout ID
        num_readings: Number of lactate readings in the comment
        strokes_df: Stroke data for this workout (or None if unavailable)

    Returns:
        Tuple of (test_type, steps_data, reading_times)
        - test_type: 'step_test' or 'zone2_multi'
        - steps_data: List of step dicts if step_test, None otherwise
        - reading_times: List of elapsed minutes for zone2_multi, None otherwise
    """
    if strokes_df is None or strokes_df.empty:
        # No stroke data - default to zone2_multi (safer assumption)
        return "zone2_multi", None, None

    # Analyze stroke data for power steps
    steps = detect_power_steps(strokes_df)

    if steps is not None:
        # Check if number of steps roughly matches number of readings
        # Allow some flexibility (readings might not perfectly match steps)
        if abs(len(steps) - num_readings) <= 2:
            return "step_test", steps, None

    # Not a step test - try to detect reading pauses for zone2_multi
    reading_times = detect_reading_pauses(strokes_df, num_readings)

    return "zone2_multi", None, reading_times


def extract_lactate_from_workouts(
    workouts_df: pd.DataFrame,
    ingest_run_id: str,
    source: str = "Concept2_Comment",
    strokes_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Extract lactate measurements from workout comments.

    Supports:
    - Single readings (zone2_single)
    - Multi-readings at constant power (zone2_multi)
    - Step tests with increasing power (step_test) - detected via stroke data

    Args:
        workouts_df: DataFrame with columns: date, workout_id, start_time_utc, notes, etc.
        ingest_run_id: Ingestion run identifier
        source: Data source identifier
        strokes_df: Optional stroke data for step test detection

    Returns:
        DataFrame with lactate measurements (may be empty)
    """
    if workouts_df.empty or "notes" not in workouts_df.columns:
        return pd.DataFrame()

    records = []
    now_utc = datetime.now(timezone.utc)

    for _, row in workouts_df.iterrows():
        comment = row.get("notes")
        if not comment or not isinstance(comment, str):
            continue

        workout_id = row["workout_id"]
        equipment_type = infer_equipment_type(row)

        # Check for multi-reading comment (comma-separated values)
        if is_step_test_comment(comment):
            readings = extract_step_test_readings(comment)

            # Get stroke data for this workout (if available)
            workout_strokes = None
            if strokes_df is not None and not strokes_df.empty:
                workout_strokes = strokes_df[strokes_df["workout_id"] == str(workout_id)]

            # Classify based on stroke data
            test_type, steps_data, reading_times = classify_multi_reading_workout(
                workout_id, len(readings), workout_strokes
            )

            for i, lactate in enumerate(readings, start=1):
                measurement_time = row.get("end_time_utc") or row["start_time_utc"]

                # Get watts/hr from step data if available
                watts_at_reading = None
                hr_at_reading = None
                elapsed_min = None
                step_number = None

                if test_type == "step_test" and steps_data and i <= len(steps_data):
                    step = steps_data[i - 1]
                    watts_at_reading = step["avg_watts"]
                    hr_at_reading = step["avg_hr"]
                    elapsed_min = float(step["end_min"])
                    step_number = i
                elif reading_times and i <= len(reading_times):
                    # Use detected pause times from stroke data
                    elapsed_min = reading_times[i - 1]
                else:
                    # Fallback: estimate elapsed time for zone2_multi
                    # Assume readings roughly evenly spaced
                    duration_s = row.get("duration_s")
                    if duration_s and duration_s > 0:
                        elapsed_min = (duration_s / 60.0) * (i / len(readings))

                records.append({
                    "workout_id": workout_id,
                    "workout_start_utc": row["start_time_utc"],
                    "lactate_mmol": lactate,
                    "measurement_time_utc": measurement_time,
                    "measurement_context": test_type,
                    "notes": comment,
                    "source": source,
                    "ingest_time_utc": now_utc,
                    "ingest_run_id": ingest_run_id,
                    "reading_sequence": i,
                    "elapsed_minutes": elapsed_min,
                    "watts_at_reading": watts_at_reading,
                    "hr_at_reading": hr_at_reading,
                    "test_type": test_type,
                    "step_number": step_number,
                    "equipment_type": equipment_type,
                    "strip_batch": None,
                    "storage_location": None,
                    "is_outlier": False,
                    "outlier_reason": None,
                })
        else:
            # Single reading (zone2_single)
            lactate = extract_lactate_from_comment(comment)

            if lactate is not None:
                measurement_time = row.get("end_time_utc") or row["start_time_utc"]

                # Calculate elapsed minutes from duration
                elapsed_min = None
                duration_s = row.get("duration_s")
                if duration_s and duration_s > 0:
                    elapsed_min = duration_s / 60.0

                records.append({
                    "workout_id": workout_id,
                    "workout_start_utc": row["start_time_utc"],
                    "lactate_mmol": lactate,
                    "measurement_time_utc": measurement_time,
                    "measurement_context": "post-workout",
                    "notes": comment,
                    "source": source,
                    "ingest_time_utc": now_utc,
                    "ingest_run_id": ingest_run_id,
                    "reading_sequence": 1,
                    "elapsed_minutes": elapsed_min,
                    "watts_at_reading": None,
                    "hr_at_reading": None,
                    "test_type": "zone2_single",
                    "step_number": None,
                    "equipment_type": equipment_type,
                    "strip_batch": None,
                    "storage_location": None,
                    "is_outlier": False,
                    "outlier_reason": None,
                })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    # Add partition column (monthly)
    df["date"] = df["workout_start_utc"].dt.to_period("M").dt.to_timestamp().dt.strftime("%Y-%m-01")

    return df


def create_lactate_table(lactate_df: pd.DataFrame) -> pa.Table:
    """
    Convert lactate DataFrame to PyArrow Table with schema validation.

    Args:
        lactate_df: Lactate measurements DataFrame

    Returns:
        PyArrow Table
    """
    if lactate_df.empty:
        return pa.table({}, schema=get_schema("lactate"))

    # Ensure schema compliance
    schema = get_schema("lactate")
    table = pa.Table.from_pandas(lactate_df, schema=schema, preserve_index=False)

    return table
