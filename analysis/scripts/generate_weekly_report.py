#!/usr/bin/env python3
"""
Generate weekly training report combining recovery and progression data.

Produces a polished markdown report for Sunday review including:
- Recovery status and training mode
- Specific exercise targets for the week
- Progress context (current vs peak performance)
- Volume guidance and safety warnings
- Motivational context

Usage:
    python analysis/scripts/generate_weekly_report.py
    python analysis/scripts/generate_weekly_report.py --output weekly_plan.md
"""
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# Paths
OUTPUT_DIR = Path("analysis/outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_latest_file(pattern: str) -> pd.DataFrame:
    """Load most recent file matching pattern."""
    files = sorted(OUTPUT_DIR.glob(pattern), reverse=True)
    if not files:
        raise FileNotFoundError(f"No files matching {pattern}")
    return pd.read_csv(files[0])


def get_week_dates() -> tuple[str, str]:
    """Get Monday-Sunday dates for current week."""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime("%b %d"), sunday.strftime("%b %d, %Y")


def generate_report() -> str:
    """Generate the weekly training report as markdown."""
    lines = []

    # Load data
    try:
        sleep_df = load_latest_file("sleep_metrics_*.csv")
        prog_df = load_latest_file("progression_*.csv")
        plan_df = load_latest_file("training_plan_*.csv")
    except FileNotFoundError as e:
        return f"# Error\n\nMissing data: {e}\n\nRun `make training.plan` first."

    # Get latest metrics
    sleep_latest = sleep_df.iloc[-1] if len(sleep_df) > 0 else None

    # Determine training mode from plan
    training_mode = plan_df["training_mode"].iloc[0] if len(plan_df) > 0 else "UNKNOWN"
    volume_mult = plan_df["volume_multiplier"].iloc[0] if len(plan_df) > 0 else 1.0

    # Week dates
    week_start, week_end = get_week_dates()

    # === HEADER ===
    mode_emoji = {"OPTIMAL": "🟢", "MAINTENANCE": "🟡", "DELOAD": "🔴"}.get(
        training_mode, "⚪"
    )
    lines.append(f"# Weekly Training Plan")
    lines.append(f"**Week of {week_start} - {week_end}**")
    lines.append("")
    lines.append(f"## {mode_emoji} Training Mode: {training_mode}")
    lines.append("")

    # Mode description
    mode_desc = {
        "OPTIMAL": "Recovery is good. Push for progressive overload this week.",
        "MAINTENANCE": "Recovery is moderate. Focus on maintaining strength, reduced volume.",
        "DELOAD": "Recovery is compromised. Prioritize rest with lighter weights and reduced volume.",
    }
    lines.append(f"> {mode_desc.get(training_mode, 'Follow adjusted recommendations below.')}")
    lines.append("")

    # === RECOVERY STATUS ===
    lines.append("---")
    lines.append("## Recovery Status")
    lines.append("")

    if sleep_latest is not None:
        debt = sleep_latest.get("sleep_debt_7d_hr", 0)
        last_sleep = sleep_latest.get("sleep_total_hr")
        hrv = sleep_latest.get("hrv_avg_7d_ms")
        recovery_state = sleep_latest.get("recovery_state", "UNKNOWN")

        lines.append("| Metric | Value | Status |")
        lines.append("|--------|-------|--------|")

        # Sleep debt
        debt_status = "🟢 Good" if debt < 3 else ("🟡 Elevated" if debt < 7 else "🔴 High")
        lines.append(f"| Sleep Debt (7d) | {debt:.1f} hr | {debt_status} |")

        # Last night
        if pd.notna(last_sleep):
            sleep_status = "🟢" if last_sleep >= 7 else ("🟡" if last_sleep >= 6 else "🔴")
            lines.append(f"| Last Night | {last_sleep:.1f} hr | {sleep_status} |")

        # HRV
        if pd.notna(hrv):
            hrv_status = "🟢" if hrv >= 30 else ("🟡" if hrv >= 20 else "🔴")
            lines.append(f"| HRV (7d avg) | {hrv:.0f} ms | {hrv_status} |")

        lines.append("")

        # Warnings
        warnings = []
        if debt > 7:
            warnings.append(f"High sleep debt ({debt:.1f}hr) - prioritize sleep this week")
        if pd.notna(last_sleep) and last_sleep < 5:
            warnings.append(f"Very low sleep last night ({last_sleep:.1f}hr)")
        if pd.notna(hrv) and hrv < 20:
            warnings.append(f"Low HRV trend ({hrv:.0f}ms) - indicates autonomic stress")

        if warnings:
            lines.append("### ⚠️ Warnings")
            for w in warnings:
                lines.append(f"- {w}")
            lines.append("")

    # === VOLUME GUIDANCE ===
    lines.append("---")
    lines.append("## Volume Guidance")
    lines.append("")

    vol_pct = int(volume_mult * 100)
    if training_mode == "OPTIMAL":
        lines.append("- **Sets:** Full volume (3-4 sets per exercise)")
        lines.append("- **Sessions:** Up to 4 this week")
        lines.append("- **Intensity:** Follow progression targets below")
    elif training_mode == "MAINTENANCE":
        lines.append(f"- **Sets:** Reduced to {vol_pct}% (3 sets → 2-3 sets)")
        lines.append("- **Sessions:** Maximum 3 this week")
        lines.append("- **Intensity:** Maintain current weights")
    else:  # DELOAD
        lines.append(f"- **Sets:** Reduced to {vol_pct}% (3 sets → 2 sets)")
        lines.append("- **Sessions:** Maximum 2 this week")
        lines.append("- **Intensity:** Weights reduced ~10%")
    lines.append("")

    # === EXERCISE TARGETS ===
    lines.append("---")
    lines.append("## This Week's Targets")
    lines.append("")

    # Group exercises by status
    if len(plan_df) > 0:
        # Merge with progression data for peak info
        merged = plan_df.merge(
            prog_df[["exercise", "peak_weight_lbs", "weight_change_4wk", "total_sessions"]],
            on="exercise",
            how="left",
        )

        # Categorize exercises
        categories = {
            "Upper Push": ["Bench Press", "Incline", "Fly", "Tricep", "Press"],
            "Upper Pull": ["Row", "Chin", "Pull", "Curl"],
            "Lower": ["Squat", "Deadlift", "Lunge", "Calf", "Hip Thrust", "Split"],
            "Core": ["Crunch", "Plank", "Side", "Hollow", "Leg Raise", "Ab"],
        }

        def categorize(name):
            for cat, keywords in categories.items():
                if any(kw.lower() in name.lower() for kw in keywords):
                    return cat
            return "Other"

        merged["category"] = merged["exercise"].apply(categorize)

        # Print by category
        for category in ["Upper Push", "Upper Pull", "Lower", "Core", "Other"]:
            cat_df = merged[merged["category"] == category]
            if len(cat_df) == 0:
                continue

            lines.append(f"### {category}")
            lines.append("")
            lines.append("| Exercise | Target | vs Peak | Note |")
            lines.append("|----------|--------|---------|------|")

            for _, row in cat_df.iterrows():
                exercise = row["exercise"][:25]
                current = row["current_weight_lbs"]
                adjusted = row["adjusted_weight_lbs"]
                peak = row.get("peak_weight_lbs", current)
                status = row["adjusted_status"]

                # Target string
                if adjusted != current:
                    target = f"**{adjusted:.0f}** lbs"
                else:
                    target = f"{adjusted:.0f} lbs"

                # vs Peak (with sanity check for bad data)
                if pd.notna(peak) and peak > 0 and peak <= current * 2:
                    # Only show vs peak if peak is reasonable (within 2x current)
                    pct_of_peak = (adjusted / peak) * 100
                    if pct_of_peak >= 100:
                        vs_peak = "🏆 At peak"
                    elif pct_of_peak >= 90:
                        vs_peak = f"{pct_of_peak:.0f}%"
                    else:
                        vs_peak = f"{pct_of_peak:.0f}% ↓"
                else:
                    vs_peak = "-"

                # Note based on status
                note_map = {
                    "READY": "Ready to increase",
                    "PROGRESSING": "Building",
                    "MAINTAIN": "Hold weight",
                    "DELOAD": "Recovery week",
                    "STABLE": "Maintain",
                    "STAGNANT": "Push harder",
                }
                note = note_map.get(status, "")

                lines.append(f"| {exercise} | {target} | {vs_peak} | {note} |")

            lines.append("")

    # === PROGRESS SUMMARY ===
    lines.append("---")
    lines.append("## Progress Summary")
    lines.append("")

    if len(prog_df) > 0:
        ready_count = len(prog_df[prog_df["status"] == "READY"])
        progressing_count = len(prog_df[prog_df["status"] == "PROGRESSING"])
        stagnant_count = len(prog_df[prog_df["status"] == "STAGNANT"])

        # Count exercises at or near peak
        at_peak = len(prog_df[prog_df["current_weight_lbs"] >= prog_df["peak_weight_lbs"] * 0.95])

        lines.append(f"- **{ready_count}** exercises ready to progress")
        lines.append(f"- **{progressing_count}** exercises currently building")
        lines.append(f"- **{at_peak}** exercises at/near peak performance")
        if stagnant_count > 0:
            lines.append(f"- **{stagnant_count}** exercises stagnant (need attention)")
        lines.append("")

        # 4-week trend
        improved = len(prog_df[prog_df["weight_change_4wk"] > 0])
        maintained = len(prog_df[prog_df["weight_change_4wk"] == 0])
        declined = len(prog_df[prog_df["weight_change_4wk"] < 0])

        lines.append(f"**4-Week Trend:** {improved} improved, {maintained} maintained, {declined} declined")
        lines.append("")

    # === WEEKLY SCHEDULE SUGGESTION ===
    lines.append("---")
    lines.append("## Suggested Schedule")
    lines.append("")

    if training_mode == "OPTIMAL":
        lines.append("| Day | Focus | Notes |")
        lines.append("|-----|-------|-------|")
        lines.append("| Mon | Upper Push | Bench, Incline, Triceps |")
        lines.append("| Tue | Lower | Squats, Deadlift, Calves |")
        lines.append("| Wed | Rest | Active recovery or cardio |")
        lines.append("| Thu | Upper Pull | Rows, Chin-ups, Curls |")
        lines.append("| Fri | Lower/Full | Remaining exercises |")
        lines.append("| Sat-Sun | Rest | Recovery |")
    elif training_mode == "MAINTENANCE":
        lines.append("| Day | Focus | Notes |")
        lines.append("|-----|-------|-------|")
        lines.append("| Mon | Upper | Push + Pull combined |")
        lines.append("| Wed | Lower | Squats, Deadlift |")
        lines.append("| Fri | Full Body | Light, maintenance |")
        lines.append("| Other | Rest | Prioritize sleep |")
    else:  # DELOAD
        lines.append("| Day | Focus | Notes |")
        lines.append("|-----|-------|-------|")
        lines.append("| Tue | Light Full Body | 60% volume, -10% weight |")
        lines.append("| Fri | Light Full Body | Focus on movement quality |")
        lines.append("| Other | Rest | Sleep is the priority |")

    lines.append("")

    # === MOTIVATIONAL CLOSE ===
    lines.append("---")
    lines.append("")

    if training_mode == "OPTIMAL":
        lines.append("*Recovery is good - time to push. Trust the process and chase those PRs.*")
    elif training_mode == "MAINTENANCE":
        lines.append("*Recovery needs attention - smart training now pays dividends later. Consistency over intensity.*")
    else:
        lines.append("*Your body is asking for rest. Honor it. A strategic deload now means better gains ahead.*")

    lines.append("")
    lines.append("---")
    lines.append(f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} by Weekly Training Coach*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate weekly training report")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output filename (default: weekly_report_YYYYMMDD.md)",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print to stdout without saving file",
    )
    args = parser.parse_args()

    print("Generating weekly training report...")

    report = generate_report()

    if args.print_only:
        print(report)
    else:
        timestamp = datetime.now().strftime("%Y%m%d")
        output_name = args.output or f"weekly_report_{timestamp}.md"
        output_path = OUTPUT_DIR / output_name

        output_path.write_text(report)
        print(f"✅ Report saved: {output_path}")

        # Also print summary
        print("\n" + "=" * 50)
        print("REPORT PREVIEW")
        print("=" * 50)
        # Print first 40 lines
        preview_lines = report.split("\n")[:40]
        print("\n".join(preview_lines))
        if len(report.split("\n")) > 40:
            print("\n... (see full report in file)")

    return report


if __name__ == "__main__":
    main()
