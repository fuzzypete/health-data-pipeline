#!/usr/bin/env python3
"""
Calculate strength training progression rates and recommend next targets.

Analyzes JEFIT resistance training data to:
- Track per-lift progression over 4/8/12 week windows
- Identify stagnant lifts (no progress in 4+ weeks)
- Recommend next workout targets with safety bounds
- Integrate with recovery state for volume adjustment

Usage:
    python analysis/scripts/calculate_progression.py
    python analysis/scripts/calculate_progression.py --weeks 8
    python analysis/scripts/calculate_progression.py --exercise "Dumbbell Bench Press"
"""
import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow.parquet as pq

# Paths
DATA_DIR = Path("Data/Parquet")
OUTPUT_DIR = Path("analysis/outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ProgressionStatus:
    """Status of an exercise's progression."""

    PROGRESSING = "PROGRESSING"  # Recently increased weight
    READY = "READY"  # Stable weight, reps good, ready to increase
    STABLE = "STABLE"  # Maintaining, not ready to progress
    STAGNANT = "STAGNANT"  # Same weight 4+ sessions, no improvement
    DELOAD = "DELOAD"  # Performance declining, needs deload


@dataclass
class ExerciseAnalysis:
    """Analysis results for a single exercise."""

    exercise_name: str
    total_sessions: int
    last_session_date: str
    days_since_last: int

    # Current performance
    current_weight: float
    current_avg_reps: float
    current_sets_per_session: float

    # Historical context
    peak_weight: float
    peak_weight_date: str
    sessions_at_current_weight: int

    # Progression metrics
    weight_change_4wk: float
    weight_change_8wk: float
    rep_trend: str  # "improving", "stable", "declining"

    # Status and recommendation
    status: str
    recommended_weight: float
    recommendation_reason: str


def load_resistance_data() -> pd.DataFrame:
    """Load resistance training data from parquet."""
    rs = pq.read_table(DATA_DIR / "resistance_sets").to_pandas()
    rs["workout_date"] = pd.to_datetime(rs["workout_start_utc"]).dt.date
    return rs


def analyze_exercise(
    df: pd.DataFrame,
    exercise_name: str,
    analysis_date: Optional[datetime] = None,
) -> Optional[ExerciseAnalysis]:
    """
    Analyze progression for a single exercise.

    Args:
        df: Full resistance_sets DataFrame
        exercise_name: Name of exercise to analyze
        analysis_date: Date to analyze from (default: today)

    Returns:
        ExerciseAnalysis or None if insufficient data
    """
    if analysis_date is None:
        analysis_date = datetime.now()

    ex_data = df[df["exercise_name"] == exercise_name].copy()
    if len(ex_data) < 3:  # Need at least 3 sets to analyze
        return None

    # Skip bodyweight exercises (no weight data)
    if ex_data["weight_lbs"].isna().all():
        return None

    # Group by session
    sessions = (
        ex_data.groupby("workout_date")
        .agg(
            max_weight=("weight_lbs", "max"),
            avg_weight=("weight_lbs", "mean"),
            avg_reps=("actual_reps", "mean"),
            total_reps=("actual_reps", "sum"),
            sets=("set_number", "count"),
        )
        .reset_index()
        .sort_values("workout_date")
    )

    if len(sessions) < 1:
        return None

    # Skip if all weights are NaN after aggregation
    if sessions["max_weight"].isna().all():
        return None

    # Basic metrics
    last_session = sessions.iloc[-1]
    last_date = last_session["workout_date"]
    days_since = (analysis_date.date() - last_date).days

    # Current performance (last session)
    current_weight = last_session["max_weight"]
    current_avg_reps = last_session["avg_reps"]
    current_sets = last_session["sets"]

    # Historical peak
    peak_idx = sessions["max_weight"].idxmax()
    peak_weight = sessions.loc[peak_idx, "max_weight"]
    peak_date = sessions.loc[peak_idx, "workout_date"]

    # Sessions at current weight
    sessions_at_weight = 0
    for _, row in sessions.iloc[::-1].iterrows():
        if row["max_weight"] == current_weight:
            sessions_at_weight += 1
        else:
            break

    # Weight changes over time windows
    def get_weight_change(weeks: int) -> float:
        cutoff = analysis_date.date() - timedelta(weeks=weeks)
        window = sessions[sessions["workout_date"] >= cutoff]
        if len(window) < 2:
            return 0.0
        return window.iloc[-1]["max_weight"] - window.iloc[0]["max_weight"]

    weight_change_4wk = get_weight_change(4)
    weight_change_8wk = get_weight_change(8)

    # Rep trend (last 4 sessions at current weight)
    recent_at_weight = sessions[sessions["max_weight"] == current_weight].tail(4)
    if len(recent_at_weight) >= 2:
        first_reps = recent_at_weight.iloc[0]["avg_reps"]
        last_reps = recent_at_weight.iloc[-1]["avg_reps"]
        rep_diff = last_reps - first_reps
        if rep_diff > 0.5:
            rep_trend = "improving"
        elif rep_diff < -0.5:
            rep_trend = "declining"
        else:
            rep_trend = "stable"
    else:
        rep_trend = "stable"

    # Determine status and recommendation
    status, recommended_weight, reason = _determine_progression(
        current_weight=current_weight,
        current_reps=current_avg_reps,
        sessions_at_weight=sessions_at_weight,
        rep_trend=rep_trend,
        peak_weight=peak_weight,
        days_since_last=days_since,
    )

    return ExerciseAnalysis(
        exercise_name=exercise_name,
        total_sessions=len(sessions),
        last_session_date=str(last_date),
        days_since_last=days_since,
        current_weight=current_weight,
        current_avg_reps=current_avg_reps,
        current_sets_per_session=current_sets,
        peak_weight=peak_weight,
        peak_weight_date=str(peak_date),
        sessions_at_current_weight=sessions_at_weight,
        weight_change_4wk=weight_change_4wk,
        weight_change_8wk=weight_change_8wk,
        rep_trend=rep_trend,
        status=status,
        recommended_weight=recommended_weight,
        recommendation_reason=reason,
    )


def _determine_progression(
    current_weight: float,
    current_reps: float,
    sessions_at_weight: int,
    rep_trend: str,
    peak_weight: float,
    days_since_last: int,
) -> tuple[str, float, str]:
    """
    Determine progression status and next weight recommendation.

    Rules:
    - If last 3 sessions successful (6+ reps): ready to increase +5 lbs
    - If reps declining: maintain weight
    - If stagnant >4 sessions with no rep improvement: consider deload
    - Safety: max +5 lbs for dumbbells, +10 lbs for barbells

    Returns:
        (status, recommended_weight, reason)
    """
    # Default to maintaining current weight
    recommended = current_weight
    status = ProgressionStatus.STABLE
    reason = "Maintain current weight"

    # Long layoff - be conservative
    if days_since_last > 14:
        status = ProgressionStatus.STABLE
        recommended = current_weight * 0.9  # Start 10% lighter after layoff
        reason = f"Layoff ({days_since_last} days) - start lighter"
        return status, round(recommended / 5) * 5, reason  # Round to nearest 5

    # Check if ready to progress
    if sessions_at_weight >= 3 and current_reps >= 6 and rep_trend != "declining":
        # Ready to increase
        status = ProgressionStatus.READY
        increase = 5.0  # Conservative 5 lb increase
        recommended = current_weight + increase
        reason = f"3+ sessions at {current_weight}lbs with good reps - increase +{increase}lbs"

        # Cap at peak weight + 5 for safety
        if recommended > peak_weight + 5:
            recommended = peak_weight + 5
            reason += f" (capped near peak)"

        return status, recommended, reason

    # Recent weight increase - still progressing
    if sessions_at_weight <= 2:
        status = ProgressionStatus.PROGRESSING
        reason = f"Recently changed to {current_weight}lbs - continue building"
        return status, current_weight, reason

    # Stagnant check
    if sessions_at_weight >= 4:
        if rep_trend == "improving":
            status = ProgressionStatus.READY
            recommended = current_weight + 5
            reason = f"Stagnant weight but reps improving - try +5lbs"
        elif rep_trend == "declining":
            status = ProgressionStatus.DELOAD
            recommended = current_weight * 0.9
            recommended = round(recommended / 5) * 5
            reason = f"Stagnant with declining reps - deload to {recommended}lbs"
        else:
            status = ProgressionStatus.STAGNANT
            reason = f"4+ sessions at same weight, reps stable - push harder or accept plateau"

    return status, recommended, reason


def print_analysis(analyses: list[ExerciseAnalysis], weeks: int):
    """Print formatted analysis report."""
    print(f"\n{'='*70}")
    print("STRENGTH PROGRESSION ANALYSIS")
    print(f"{'='*70}")
    print(f"Analysis window: {weeks} weeks")
    print(f"Exercises analyzed: {len(analyses)}")

    # Group by status
    by_status = {}
    for a in analyses:
        by_status.setdefault(a.status, []).append(a)

    # Print by category
    status_order = [
        ProgressionStatus.READY,
        ProgressionStatus.PROGRESSING,
        ProgressionStatus.STAGNANT,
        ProgressionStatus.DELOAD,
        ProgressionStatus.STABLE,
    ]
    status_emoji = {
        ProgressionStatus.READY: "🟢",
        ProgressionStatus.PROGRESSING: "📈",
        ProgressionStatus.STAGNANT: "🟡",
        ProgressionStatus.DELOAD: "🔴",
        ProgressionStatus.STABLE: "⚪",
    }

    for status in status_order:
        if status not in by_status:
            continue

        exercises = by_status[status]
        emoji = status_emoji.get(status, "")
        print(f"\n{emoji} {status} ({len(exercises)} exercises)")
        print("-" * 50)

        for a in sorted(exercises, key=lambda x: -x.current_weight):
            trend_arrow = {"improving": "↑", "declining": "↓", "stable": "→"}[
                a.rep_trend
            ]
            print(
                f"  {a.exercise_name[:30]:<30} "
                f"{a.current_weight:>5.0f}lbs × {a.current_avg_reps:.1f} {trend_arrow}"
            )
            if a.status in [ProgressionStatus.READY, ProgressionStatus.DELOAD]:
                print(f"    → Recommended: {a.recommended_weight:.0f}lbs")
                print(f"      {a.recommendation_reason}")

    # Summary stats
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    ready = len(by_status.get(ProgressionStatus.READY, []))
    stagnant = len(by_status.get(ProgressionStatus.STAGNANT, []))
    deload = len(by_status.get(ProgressionStatus.DELOAD, []))

    print(f"  Ready to progress: {ready}")
    print(f"  Stagnant (needs attention): {stagnant}")
    print(f"  Needs deload: {deload}")


def main():
    parser = argparse.ArgumentParser(description="Analyze strength progression")
    parser.add_argument(
        "--weeks", type=int, default=12, help="Weeks of history to analyze (default: 12)"
    )
    parser.add_argument(
        "--exercise", type=str, default=None, help="Analyze specific exercise only"
    )
    parser.add_argument(
        "--min-sessions",
        type=int,
        default=3,
        help="Minimum sessions to include exercise (default: 3)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output CSV filename",
    )
    args = parser.parse_args()

    print("Loading resistance training data...")
    df = load_resistance_data()

    # Filter to analysis window
    cutoff = datetime.now() - timedelta(weeks=args.weeks)
    df_window = df[df["workout_date"] >= cutoff.date()]

    print(f"  Total sets in window: {len(df_window)}")
    print(f"  Date range: {df_window['workout_date'].min()} to {df_window['workout_date'].max()}")

    # Get exercises to analyze
    if args.exercise:
        exercises = [args.exercise]
    else:
        # Get exercises with minimum sessions
        exercise_counts = df_window.groupby("exercise_name")["workout_date"].nunique()
        exercises = exercise_counts[exercise_counts >= args.min_sessions].index.tolist()

    print(f"  Analyzing {len(exercises)} exercises...")

    # Analyze each exercise
    analyses = []
    for ex in exercises:
        analysis = analyze_exercise(df, ex)
        if analysis:
            analyses.append(analysis)

    # Print report
    print_analysis(analyses, args.weeks)

    # Save to CSV
    if analyses:
        timestamp = datetime.now().strftime("%Y%m%d")
        output_name = args.output or f"progression_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_name

        # Convert to DataFrame
        records = []
        for a in analyses:
            records.append(
                {
                    "exercise": a.exercise_name,
                    "current_weight_lbs": a.current_weight,
                    "current_reps": a.current_avg_reps,
                    "peak_weight_lbs": a.peak_weight,
                    "sessions_at_weight": a.sessions_at_current_weight,
                    "weight_change_4wk": a.weight_change_4wk,
                    "weight_change_8wk": a.weight_change_8wk,
                    "rep_trend": a.rep_trend,
                    "status": a.status,
                    "recommended_weight_lbs": a.recommended_weight,
                    "recommendation": a.recommendation_reason,
                    "last_session": a.last_session_date,
                    "days_since_last": a.days_since_last,
                    "total_sessions": a.total_sessions,
                }
            )

        out_df = pd.DataFrame(records)
        out_df.to_csv(output_path, index=False)
        print(f"\n✅ Output saved: {output_path}")

    return analyses


if __name__ == "__main__":
    main()
