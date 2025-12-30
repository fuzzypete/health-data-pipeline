#!/usr/bin/env python3
"""
Analyze Concept2 30/30 interval sessions with trending support.

Usage:
    poetry run python analysis/scripts/analyze_interval_session.py              # Analyze most recent
    poetry run python analysis/scripts/analyze_interval_session.py --workout-id 109902972
    poetry run python analysis/scripts/analyze_interval_session.py --trend      # Show trends across sessions
    poetry run python analysis/scripts/analyze_interval_session.py --list       # List all interval sessions
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np


# Configuration
HISTORY_FILE = Path("analysis/outputs/interval_session_history.parquet")
OUTPUT_DIR = Path("analysis/outputs")


def load_workout_data(workout_id: str | None = None) -> tuple[pd.Series, pd.DataFrame]:
    """Load workout and stroke data for a specific workout or most recent."""
    workouts = pd.read_parquet("Data/Parquet/workouts")
    workouts["start_time_utc"] = pd.to_datetime(workouts["start_time_utc"])

    # Filter to Concept2 bike workouts with splits (interval sessions)
    c2_workouts = workouts[
        (workouts["workout_type"] == "Cycling") &
        (workouts["has_strokes"] == True)
    ].sort_values("start_time_utc", ascending=False)

    if workout_id:
        workout = c2_workouts[c2_workouts["workout_id"] == str(workout_id)].iloc[0]
    else:
        workout = c2_workouts.iloc[0]

    strokes = pd.read_parquet("Data/Parquet/cardio_strokes")
    workout_strokes = strokes[strokes["workout_id"] == str(workout["workout_id"])].copy()
    workout_strokes = workout_strokes.sort_values("time_cumulative_s")

    return workout, workout_strokes


def detect_interval_structure(strokes: pd.DataFrame) -> dict:
    """Detect warmup, intervals, and cooldown from split numbers."""
    splits = sorted(strokes["split_number"].unique())

    if len(splits) < 3:
        return {"type": "unknown", "splits": splits}

    # Analyze each split
    split_stats = []
    for split in splits:
        split_data = strokes[strokes["split_number"] == split]
        duration = split_data["time_cumulative_s"].max() - split_data["time_cumulative_s"].min()
        watts = split_data[split_data["watts"] > 10]["watts"]
        avg_watts = watts.mean() if len(watts) > 0 else 0
        split_stats.append({
            "split": split,
            "duration": duration,
            "avg_watts": avg_watts
        })

    df = pd.DataFrame(split_stats)

    # Detect structure: warmup is usually first long split, cooldown is last long split
    long_splits = df[df["duration"] > 120]  # > 2 minutes
    short_splits = df[(df["duration"] >= 25) & (df["duration"] <= 35)]  # ~30s intervals

    structure = {
        "type": "30/30" if len(short_splits) >= 20 else "unknown",
        "warmup_split": int(long_splits.iloc[0]["split"]) if len(long_splits) > 0 else None,
        "cooldown_split": int(long_splits.iloc[-1]["split"]) if len(long_splits) > 1 else None,
        "interval_splits": sorted(short_splits["split"].tolist()),
        "total_splits": len(splits)
    }

    # Determine hard vs easy based on power
    if structure["type"] == "30/30":
        interval_data = df[df["split"].isin(structure["interval_splits"])]
        even_splits = interval_data[interval_data["split"] % 2 == 0]
        odd_splits = interval_data[interval_data["split"] % 2 == 1]

        even_avg = even_splits["avg_watts"].mean() if len(even_splits) > 0 else 0
        odd_avg = odd_splits["avg_watts"].mean() if len(odd_splits) > 0 else 0

        if even_avg > odd_avg:
            structure["hard_splits"] = sorted(even_splits["split"].tolist())
            structure["easy_splits"] = sorted(odd_splits["split"].tolist())
        else:
            structure["hard_splits"] = sorted(odd_splits["split"].tolist())
            structure["easy_splits"] = sorted(even_splits["split"].tolist())

    return structure


def analyze_intervals(strokes: pd.DataFrame, structure: dict) -> dict:
    """Compute detailed interval metrics."""
    if structure["type"] != "30/30":
        return {"error": "Not a 30/30 session"}

    warmup = strokes[strokes["split_number"] == structure["warmup_split"]]
    hard = strokes[strokes["split_number"].isin(structure["hard_splits"])]
    easy = strokes[strokes["split_number"].isin(structure["easy_splits"])]
    cooldown = strokes[strokes["split_number"] == structure["cooldown_split"]] if structure["cooldown_split"] else pd.DataFrame()
    intervals = strokes[strokes["split_number"].isin(structure["interval_splits"])]

    # Filter out zero watts for averages
    hard_watts = hard[hard["watts"] > 10]["watts"]
    easy_watts = easy[easy["watts"] > 10]["watts"]

    # Per-interval breakdown
    hard_interval_stats = []
    for i, split in enumerate(structure["hard_splits"]):
        split_data = hard[hard["split_number"] == split]
        watts = split_data[split_data["watts"] > 10]["watts"]
        hard_interval_stats.append({
            "interval": i + 1,
            "split": int(split),
            "avg_watts": float(watts.mean()) if len(watts) > 0 else 0,
            "max_watts": float(watts.max()) if len(watts) > 0 else 0,
            "avg_hr": float(split_data["heart_rate_bpm"].mean()),
            "max_hr": float(split_data["heart_rate_bpm"].max())
        })

    # HR recovery during easy intervals
    recovery_stats = []
    for split in structure["easy_splits"]:
        split_data = easy[easy["split_number"] == split].sort_values("time_cumulative_s")
        if len(split_data) > 2:
            hr_start = split_data["heart_rate_bpm"].iloc[:3].mean()
            hr_end = split_data["heart_rate_bpm"].iloc[-3:].mean()
            recovery_stats.append({
                "split": int(split),
                "hr_start": float(hr_start),
                "hr_end": float(hr_end),
                "hr_drop": float(hr_start - hr_end)
            })

    recovery_df = pd.DataFrame(recovery_stats)

    # Time to HR thresholds
    warmup_end_time = warmup["time_cumulative_s"].max()

    def time_to_hr(threshold):
        hits = intervals[intervals["heart_rate_bpm"] >= threshold]
        if len(hits) > 0:
            return float((hits["time_cumulative_s"].min() - warmup_end_time) / 60)
        return None

    # Power progression analysis
    n_hard = len(hard_interval_stats)
    first_half = hard_interval_stats[:n_hard // 2]
    second_half = hard_interval_stats[n_hard // 2:]
    last_three = hard_interval_stats[-3:] if n_hard >= 3 else hard_interval_stats

    metrics = {
        # Power metrics
        "hard_avg_watts": float(hard_watts.mean()),
        "hard_median_watts": float(hard_watts.median()),
        "hard_max_watts": float(hard_watts.max()),
        "hard_std_watts": float(hard_watts.std()),
        "easy_avg_watts": float(easy_watts.mean()),
        "easy_median_watts": float(easy_watts.median()),

        # HR metrics
        "max_hr": float(intervals["heart_rate_bpm"].max()),
        "avg_hr_hard": float(hard["heart_rate_bpm"].mean()),
        "avg_hr_easy": float(easy["heart_rate_bpm"].mean()),
        "time_to_130_bpm": time_to_hr(130),
        "time_to_140_bpm": time_to_hr(140),
        "time_to_150_bpm": time_to_hr(150),

        # Recovery metrics
        "avg_hr_recovery": float(recovery_df["hr_drop"].mean()) if len(recovery_df) > 0 else None,
        "min_hr_recovery": float(recovery_df["hr_drop"].min()) if len(recovery_df) > 0 else None,

        # Progression metrics
        "first_half_avg_watts": float(np.mean([i["avg_watts"] for i in first_half])),
        "second_half_avg_watts": float(np.mean([i["avg_watts"] for i in second_half])),
        "last_three_avg_watts": float(np.mean([i["avg_watts"] for i in last_three])),
        "power_progression": float(np.mean([i["avg_watts"] for i in second_half]) -
                                   np.mean([i["avg_watts"] for i in first_half])),

        # Efficiency
        "cardiac_efficiency_first_half": float(
            np.mean([i["avg_hr"] for i in first_half]) /
            np.mean([i["avg_watts"] for i in first_half]) * 100
        ) if np.mean([i["avg_watts"] for i in first_half]) > 0 else None,
        "cardiac_efficiency_second_half": float(
            np.mean([i["avg_hr"] for i in second_half]) /
            np.mean([i["avg_watts"] for i in second_half]) * 100
        ) if np.mean([i["avg_watts"] for i in second_half]) > 0 else None,

        # Counts
        "num_hard_intervals": len(structure["hard_splits"]),
        "num_easy_intervals": len(structure["easy_splits"]),

        # Detailed breakdowns
        "hard_interval_details": hard_interval_stats,
        "recovery_details": recovery_stats
    }

    return metrics


def generate_visualization(workout: pd.Series, strokes: pd.DataFrame,
                          structure: dict, metrics: dict, output_path: Path) -> None:
    """Generate power + HR visualization."""
    strokes = strokes.copy()
    strokes["time_min"] = strokes["time_cumulative_s"] / 60

    fig, ax1 = plt.subplots(figsize=(16, 8))

    # Shade regions
    warmup_end = strokes[strokes["split_number"] == structure["warmup_split"]]["time_min"].max()
    if structure["cooldown_split"]:
        cooldown_start = strokes[strokes["split_number"] == structure["cooldown_split"]]["time_min"].min()
    else:
        cooldown_start = strokes["time_min"].max()

    ax1.axvspan(0, warmup_end, alpha=0.15, color="blue")
    ax1.axvspan(cooldown_start, strokes["time_min"].max(), alpha=0.15, color="blue")

    for split in structure.get("hard_splits", []):
        split_data = strokes[strokes["split_number"] == split]
        if len(split_data) > 0:
            ax1.axvspan(split_data["time_min"].min(), split_data["time_min"].max(),
                       alpha=0.2, color="red")

    for split in structure.get("easy_splits", []):
        split_data = strokes[strokes["split_number"] == split]
        if len(split_data) > 0:
            ax1.axvspan(split_data["time_min"].min(), split_data["time_min"].max(),
                       alpha=0.2, color="green")

    # Power scatter
    ax1.scatter(strokes["time_min"], strokes["watts"], alpha=0.5, s=5, color="orange")
    ax1.set_xlabel("Time (minutes)", fontsize=12)
    ax1.set_ylabel("Power (watts)", color="orange", fontsize=12)
    ax1.tick_params(axis="y", labelcolor="orange")
    ax1.set_ylim(0, max(350, metrics.get("hard_max_watts", 300) * 1.1))

    # HR line
    ax2 = ax1.twinx()
    ax2.plot(strokes["time_min"], strokes["heart_rate_bpm"],
             color="red", linewidth=1.5, alpha=0.8)
    ax2.set_ylabel("Heart Rate (bpm)", color="red", fontsize=12)
    ax2.tick_params(axis="y", labelcolor="red")
    ax2.set_ylim(60, max(165, metrics.get("max_hr", 150) + 10))

    ax2.axhline(y=140, color="darkred", linestyle="--", alpha=0.5, linewidth=1)
    ax2.text(strokes["time_min"].max() + 0.5, 140, "140 bpm", va="center",
             color="darkred", fontsize=9)

    # Title
    workout_date = pd.to_datetime(workout["start_time_local"]).strftime("%Y-%m-%d")
    plt.title(f"30/30 Interval Session - {workout_date}\n"
              f"Warmup | {metrics['num_hard_intervals']}x(30s Hard/30s Easy) | Cooldown",
              fontsize=14, fontweight="bold")

    # Legend
    warmup_patch = mpatches.Patch(color="blue", alpha=0.15, label="Warmup/Cooldown")
    hard_patch = mpatches.Patch(color="red", alpha=0.2, label="Hard intervals")
    easy_patch = mpatches.Patch(color="green", alpha=0.2, label="Easy intervals")
    power_line = plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="orange",
                            markersize=8, label="Power (W)")
    hr_line = plt.Line2D([0], [0], color="red", linewidth=2, label="Heart Rate (bpm)")
    ax1.legend(handles=[warmup_patch, hard_patch, easy_patch, power_line, hr_line],
               loc="upper left", fontsize=10)

    # Summary box
    time_140 = metrics.get("time_to_140_bpm")
    time_140_str = f"{time_140:.1f} min" if time_140 else "Never"
    recovery_str = f"{metrics.get('avg_hr_recovery', 0):.1f}" if metrics.get("avg_hr_recovery") else "N/A"

    summary_text = (
        f"Summary:\n"
        f"• Avg Hard Watts: {metrics['hard_avg_watts']:.1f} W\n"
        f"• Avg Easy Watts: {metrics['easy_avg_watts']:.1f} W\n"
        f"• Max HR: {metrics['max_hr']:.0f} bpm\n"
        f"• Time to 140bpm: {time_140_str}\n"
        f"• Avg HR recovery: {recovery_str} bpm"
    )
    props = dict(boxstyle="round", facecolor="white", alpha=0.8)
    ax1.text(0.98, 0.02, summary_text, transform=ax1.transAxes, fontsize=9,
             verticalalignment="bottom", horizontalalignment="right", bbox=props)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()


def save_to_history(workout: pd.Series, metrics: dict) -> None:
    """Save session metrics to history file for trending."""
    workout_date = pd.to_datetime(workout["start_time_utc"])

    record = {
        "workout_id": str(workout["workout_id"]),
        "date": workout_date,
        "duration_min": float(workout["duration_s"]) / 60,
        **{k: v for k, v in metrics.items()
           if not isinstance(v, (list, dict))}  # Exclude nested structures
    }

    record_df = pd.DataFrame([record])

    if HISTORY_FILE.exists():
        history = pd.read_parquet(HISTORY_FILE)
        # Remove duplicate if re-analyzing same workout
        history = history[history["workout_id"] != record["workout_id"]]
        history = pd.concat([history, record_df], ignore_index=True)
    else:
        history = record_df

    history = history.sort_values("date", ascending=False)
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    history.to_parquet(HISTORY_FILE, index=False)


def generate_recommendations(metrics: dict) -> list[str]:
    """Generate training recommendations based on session analysis."""
    recommendations = []

    # Power progression analysis
    if metrics["power_progression"] > 20:
        recommendations.append(
            f"Strong negative split (+{metrics['power_progression']:.0f}W). "
            f"Consider starting harder: target {metrics['first_half_avg_watts'] + 15:.0f}-{metrics['first_half_avg_watts'] + 25:.0f}W for first half."
        )
    elif metrics["power_progression"] < -10:
        recommendations.append(
            f"Power faded ({metrics['power_progression']:.0f}W). "
            f"Consider starting more conservatively or building fitness."
        )

    # HR response analysis
    if metrics["time_to_140_bpm"] and metrics["time_to_140_bpm"] > 12:
        recommendations.append(
            f"Took {metrics['time_to_140_bpm']:.1f} min to hit 140bpm. "
            f"First half was aerobically easy - can push harder earlier."
        )
    elif metrics["time_to_140_bpm"] and metrics["time_to_140_bpm"] < 5:
        recommendations.append(
            f"Hit 140bpm quickly ({metrics['time_to_140_bpm']:.1f} min). "
            f"Consider longer warmup or lower initial power."
        )

    # Recovery analysis
    if metrics["avg_hr_recovery"] and metrics["avg_hr_recovery"] < 3:
        recommendations.append(
            f"Minimal HR recovery during easy intervals ({metrics['avg_hr_recovery']:.1f}bpm). "
            f"May indicate high fatigue or insufficient recovery effort."
        )
    elif metrics["avg_hr_recovery"] and metrics["avg_hr_recovery"] > 8:
        recommendations.append(
            f"Excellent HR recovery ({metrics['avg_hr_recovery']:.1f}bpm). "
            f"Good cardiac fitness - can push harder intervals."
        )

    # Efficiency trend
    if metrics["cardiac_efficiency_first_half"] and metrics["cardiac_efficiency_second_half"]:
        eff_change = metrics["cardiac_efficiency_second_half"] - metrics["cardiac_efficiency_first_half"]
        if eff_change < -3:
            recommendations.append(
                f"Cardiac efficiency improved through session (less HR per watt). "
                f"Good warmup effect."
            )

    # Target watts for next session
    target_watts = metrics["hard_avg_watts"]
    if metrics["power_progression"] > 15 and metrics["time_to_140_bpm"] and metrics["time_to_140_bpm"] > 10:
        target_watts = metrics["first_half_avg_watts"] + 20
        recommendations.append(
            f"Recommended target for next session: {target_watts:.0f}-{target_watts+15:.0f}W hard intervals."
        )

    return recommendations


def show_trends() -> None:
    """Display trends across all recorded sessions."""
    if not HISTORY_FILE.exists():
        print("No session history found. Analyze some workouts first.")
        return

    history = pd.read_parquet(HISTORY_FILE)
    history = history.sort_values("date")

    print("=" * 80)
    print("INTERVAL SESSION TRENDS")
    print("=" * 80)
    print(f"Sessions analyzed: {len(history)}")
    print(f"Date range: {history['date'].min().strftime('%Y-%m-%d')} to {history['date'].max().strftime('%Y-%m-%d')}")
    print()

    print("SESSION HISTORY:")
    print("-" * 80)
    print(f"{'Date':<12} {'Hard W':>8} {'Easy W':>8} {'Max HR':>8} {'To 140':>8} {'Recovery':>10}")
    print("-" * 80)

    for _, row in history.iterrows():
        date_str = row["date"].strftime("%Y-%m-%d")
        time_140 = f"{row['time_to_140_bpm']:.1f}m" if pd.notna(row.get("time_to_140_bpm")) else "N/A"
        recovery = f"{row['avg_hr_recovery']:.1f}" if pd.notna(row.get("avg_hr_recovery")) else "N/A"
        print(f"{date_str:<12} {row['hard_avg_watts']:>8.1f} {row['easy_avg_watts']:>8.1f} "
              f"{row['max_hr']:>8.0f} {time_140:>8} {recovery:>10}")

    if len(history) >= 2:
        print()
        print("TRENDS (comparing first vs latest session):")
        print("-" * 80)
        first = history.iloc[0]
        latest = history.iloc[-1]

        metrics_to_compare = [
            ("hard_avg_watts", "Hard interval watts", "W", True),
            ("max_hr", "Max HR", "bpm", False),
            ("time_to_140_bpm", "Time to 140 bpm", "min", False),
            ("avg_hr_recovery", "HR recovery", "bpm", True),
        ]

        for col, label, unit, higher_is_better in metrics_to_compare:
            if col in first and col in latest and pd.notna(first[col]) and pd.notna(latest[col]):
                change = latest[col] - first[col]
                direction = "↑" if change > 0 else "↓" if change < 0 else "→"
                good = (change > 0) == higher_is_better
                status = "✓" if good else "⚠" if abs(change) > 0.1 else ""
                print(f"  {label}: {first[col]:.1f} → {latest[col]:.1f} {unit} ({direction}{abs(change):.1f}) {status}")

    # Generate trend visualization
    if len(history) >= 2:
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))

        # Power trend
        ax = axes[0, 0]
        ax.plot(history["date"], history["hard_avg_watts"], "o-", color="red", label="Hard")
        ax.plot(history["date"], history["easy_avg_watts"], "o-", color="green", label="Easy")
        ax.set_ylabel("Watts")
        ax.set_title("Power Trend")
        ax.legend()
        ax.grid(True, alpha=0.3)

        # Max HR trend
        ax = axes[0, 1]
        ax.plot(history["date"], history["max_hr"], "o-", color="red")
        ax.axhline(y=150, color="orange", linestyle="--", alpha=0.5, label="150 bpm")
        ax.set_ylabel("HR (bpm)")
        ax.set_title("Max HR Trend")
        ax.grid(True, alpha=0.3)

        # Time to 140 trend
        ax = axes[1, 0]
        valid = history[history["time_to_140_bpm"].notna()]
        if len(valid) > 0:
            ax.plot(valid["date"], valid["time_to_140_bpm"], "o-", color="blue")
        ax.set_ylabel("Minutes")
        ax.set_title("Time to 140 bpm (after warmup)")
        ax.grid(True, alpha=0.3)

        # Recovery trend
        ax = axes[1, 1]
        valid = history[history["avg_hr_recovery"].notna()]
        if len(valid) > 0:
            ax.plot(valid["date"], valid["avg_hr_recovery"], "o-", color="purple")
        ax.set_ylabel("HR drop (bpm)")
        ax.set_title("Avg HR Recovery During Easy Intervals")
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        trend_path = OUTPUT_DIR / "interval_session_trends.png"
        plt.savefig(trend_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"\n📊 Trend visualization saved: {trend_path}")


def list_sessions() -> None:
    """List all Concept2 interval sessions."""
    workouts = pd.read_parquet("Data/Parquet/workouts")
    workouts["start_time_utc"] = pd.to_datetime(workouts["start_time_utc"])

    c2_workouts = workouts[
        (workouts["workout_type"] == "Cycling") &
        (workouts["has_strokes"] == True)
    ].sort_values("start_time_utc", ascending=False)

    print("=" * 80)
    print("CONCEPT2 INTERVAL SESSIONS")
    print("=" * 80)
    print(f"{'Date':<20} {'Workout ID':<15} {'Duration':>10} {'Avg HR':>8} {'Max HR':>8}")
    print("-" * 80)

    for _, row in c2_workouts.head(20).iterrows():
        date_str = row["start_time_utc"].strftime("%Y-%m-%d %H:%M")
        duration = f"{row['duration_s']/60:.1f} min"
        avg_hr = f"{row['avg_hr_bpm']:.0f}" if pd.notna(row["avg_hr_bpm"]) else "N/A"
        max_hr = f"{row['max_hr_bpm']:.0f}" if pd.notna(row["max_hr_bpm"]) else "N/A"
        print(f"{date_str:<20} {row['workout_id']:<15} {duration:>10} {avg_hr:>8} {max_hr:>8}")


def main():
    parser = argparse.ArgumentParser(description="Analyze Concept2 30/30 interval sessions")
    parser.add_argument("--workout-id", type=str, help="Specific workout ID to analyze")
    parser.add_argument("--trend", action="store_true", help="Show trends across sessions")
    parser.add_argument("--list", action="store_true", help="List available sessions")
    parser.add_argument("--no-save", action="store_true", help="Don't save to history")
    args = parser.parse_args()

    if args.list:
        list_sessions()
        return

    if args.trend:
        show_trends()
        return

    # Load and analyze workout
    print("Loading workout data...")
    workout, strokes = load_workout_data(args.workout_id)

    workout_date = pd.to_datetime(workout["start_time_local"]).strftime("%Y-%m-%d %H:%M")
    print(f"\n{'=' * 80}")
    print(f"ANALYZING WORKOUT: {workout['workout_id']}")
    print(f"Date: {workout_date}")
    print(f"Duration: {workout['duration_s']/60:.1f} min")
    print(f"{'=' * 80}")

    # Detect structure
    print("\nDetecting interval structure...")
    structure = detect_interval_structure(strokes)

    if structure["type"] != "30/30":
        print(f"Warning: This doesn't appear to be a 30/30 session (detected: {structure['type']})")
        print(f"Total splits: {structure['total_splits']}")
        return

    print(f"Detected: {structure['type']} session")
    print(f"  Warmup: split {structure['warmup_split']}")
    print(f"  Hard intervals: {len(structure['hard_splits'])} x 30s")
    print(f"  Easy intervals: {len(structure['easy_splits'])} x 30s")
    print(f"  Cooldown: split {structure['cooldown_split']}")

    # Analyze
    print("\nAnalyzing intervals...")
    metrics = analyze_intervals(strokes, structure)

    # Print results
    print(f"\n{'=' * 80}")
    print("INTERVAL METRICS")
    print("=" * 80)

    print("\nPOWER:")
    print(f"  Hard intervals: {metrics['hard_avg_watts']:.1f}W avg (median: {metrics['hard_median_watts']:.1f}W, max: {metrics['hard_max_watts']:.1f}W)")
    print(f"  Easy intervals: {metrics['easy_avg_watts']:.1f}W avg (median: {metrics['easy_median_watts']:.1f}W)")
    print(f"  First half avg: {metrics['first_half_avg_watts']:.1f}W")
    print(f"  Second half avg: {metrics['second_half_avg_watts']:.1f}W")
    print(f"  Power progression: {metrics['power_progression']:+.1f}W")

    print("\nHEART RATE:")
    print(f"  Max HR: {metrics['max_hr']:.0f} bpm")
    print(f"  Avg HR (hard): {metrics['avg_hr_hard']:.1f} bpm")
    print(f"  Avg HR (easy): {metrics['avg_hr_easy']:.1f} bpm")
    time_130 = metrics.get("time_to_130_bpm")
    time_140 = metrics.get("time_to_140_bpm")
    time_150 = metrics.get("time_to_150_bpm")
    print(f"  Time to 130 bpm: {time_130:.1f} min" if time_130 else "  Time to 130 bpm: Never")
    print(f"  Time to 140 bpm: {time_140:.1f} min" if time_140 else "  Time to 140 bpm: Never")
    print(f"  Time to 150 bpm: {time_150:.1f} min" if time_150 else "  Time to 150 bpm: Never")

    print("\nRECOVERY:")
    if metrics["avg_hr_recovery"]:
        print(f"  Avg HR drop during easy: {metrics['avg_hr_recovery']:.1f} bpm")
        print(f"  Min HR drop: {metrics['min_hr_recovery']:.1f} bpm")

    print("\nCARDIAC EFFICIENCY (HR per 100W):")
    if metrics["cardiac_efficiency_first_half"]:
        print(f"  First half: {metrics['cardiac_efficiency_first_half']:.1f} bpm/100W")
        print(f"  Second half: {metrics['cardiac_efficiency_second_half']:.1f} bpm/100W")

    # Per-interval breakdown
    print(f"\n{'=' * 80}")
    print("HARD INTERVAL BREAKDOWN")
    print("=" * 80)
    print(f"{'#':>3} {'Split':>6} {'Avg W':>8} {'Max W':>8} {'Avg HR':>8} {'Max HR':>8}")
    print("-" * 50)
    for interval in metrics["hard_interval_details"]:
        print(f"{interval['interval']:>3} {interval['split']:>6} {interval['avg_watts']:>8.1f} "
              f"{interval['max_watts']:>8.1f} {interval['avg_hr']:>8.1f} {interval['max_hr']:>8.0f}")

    # Recommendations
    print(f"\n{'=' * 80}")
    print("RECOMMENDATIONS FOR NEXT SESSION")
    print("=" * 80)
    recommendations = generate_recommendations(metrics)
    for i, rec in enumerate(recommendations, 1):
        print(f"  {i}. {rec}")

    if not recommendations:
        print("  No specific recommendations - workout was well-balanced.")

    # Generate visualization
    output_path = OUTPUT_DIR / f"interval_session_{workout['workout_id']}.png"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generate_visualization(workout, strokes, structure, metrics, output_path)
    print(f"\n📊 Visualization saved: {output_path}")

    # Save to history
    if not args.no_save:
        save_to_history(workout, metrics)
        print(f"📈 Session saved to history: {HISTORY_FILE}")
        print("   Run with --trend to see trends across sessions")


if __name__ == "__main__":
    main()
