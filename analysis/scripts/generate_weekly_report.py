#!/usr/bin/env python3
"""
Generate weekly training report combining recovery and progression data.

Produces a polished markdown report for Sunday review including:
- Current context from NOW.md (phase, restrictions, biomarkers)
- Recovery status and training mode
- Specific exercise targets for the week
- Progress context (current vs peak performance)
- Volume guidance and safety warnings
- Motivational context

Usage:
    python analysis/scripts/generate_weekly_report.py
    python analysis/scripts/generate_weekly_report.py --output weekly_plan.md
    python analysis/scripts/generate_weekly_report.py --skip-now  # Skip NOW.md fetch
"""
import argparse
import io
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

# Paths
OUTPUT_DIR = Path("analysis/outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# NOW.md Google Drive configuration
NOW_MD_FILE_ID = "11B_VQF7JcfZSSe09tWuuuLav2CapegOsnoFtKipNvOg"


@dataclass
class NowContext:
    """Parsed context from NOW.md document."""

    phase: str = "Unknown"
    ferritin: Optional[str] = None
    max_hr: Optional[str] = None
    hr_response_time: Optional[str] = None
    training_restrictions: list = field(default_factory=list)
    active_protocols: list = field(default_factory=list)
    next_milestones: list = field(default_factory=list)
    decision_gates: list = field(default_factory=list)
    raw_content: str = ""
    fetch_error: Optional[str] = None


def fetch_now_md() -> Optional[str]:
    """
    Fetch NOW.md from Google Drive as plain text.

    Returns the document content or None if fetch fails.
    """
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        return None

    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        return None
    # Expand ~ to home directory
    creds_path = os.path.expanduser(creds_path)
    if not os.path.exists(creds_path):
        return None

    try:
        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)

        # Export Google Doc as plain text
        request = drive.files().export(fileId=NOW_MD_FILE_ID, mimeType="text/plain")
        content = request.execute()

        # Handle bytes vs string response
        if isinstance(content, bytes):
            return content.decode("utf-8")
        return content

    except Exception as e:
        print(f"Warning: Could not fetch NOW.md: {e}", file=sys.stderr)
        return None


def parse_now_md(content: str) -> NowContext:
    """
    Parse NOW.md content to extract key context for training decisions.

    Handles multiple formats:
    - Markdown headers (## Section Name)
    - Plain text sections with underscore dividers
    - Inline "Key: Value" patterns
    """
    ctx = NowContext(raw_content=content)

    if not content:
        ctx.fetch_error = "Empty content"
        return ctx

    lines = content.split("\n")

    # First pass: extract inline values from anywhere in document
    for line in lines:
        line_lower = line.lower()

        # Phase: look for "Phase:" at start of line
        if line_lower.startswith("phase:"):
            phase_text = line.split(":", 1)[1].strip()
            # Clean up trailing "revised)" etc
            phase_text = re.sub(r"\s*revised\)?$", ")", phase_text)
            ctx.phase = phase_text

        # Ferritin: various patterns
        ferritin_match = re.search(r"ferritin[:\s]+(\d+(?:\.\d+)?)", line_lower)
        if ferritin_match and not ctx.ferritin:
            ctx.ferritin = ferritin_match.group(1)

        # Max HR: look for patterns
        hr_match = re.search(r"max\s*hr[:\s]+(\d+)|(\d+)\s*bpm\s*(?:peak|max|ceiling)", line_lower)
        if hr_match and not ctx.max_hr:
            ctx.max_hr = hr_match.group(1) or hr_match.group(2)

        # HR response time: look for patterns like "8-12+ minutes to reach 140"
        response_match = re.search(
            r"(?:takes?\s+)?(\d+(?:-\d+)?(?:\+)?)\s*(?:min(?:utes?)?)\s*(?:to\s+reach|to\s+get\s+to)",
            line_lower
        )
        if response_match and not ctx.hr_response_time:
            ctx.hr_response_time = response_match.group(1)

    # Second pass: detect sections and extract lists
    current_section = None
    section_content = []
    divider_pattern = re.compile(r"^[_\-=]{3,}$")

    for i, line in enumerate(lines):
        line_stripped = line.strip()

        # Detect section headers
        is_header = False

        # Markdown headers
        if line_stripped.startswith("#"):
            is_header = True
            current_section = re.sub(r"^#+\s*", "", line_stripped).lower()

        # Plain text headers (line before underscore divider, or standalone capitalized lines)
        elif divider_pattern.match(line_stripped):
            # Save previous section
            if current_section and section_content:
                _process_section(ctx, current_section, section_content)
            current_section = None
            section_content = []
            continue

        # Detect section-like headers (short lines, often capitalized)
        elif (line_stripped and
              not line_stripped.startswith(("*", "-", "•")) and
              len(line_stripped) < 50 and
              (line_stripped[0].isupper() or line_stripped.startswith("Phase:"))):
            # Check if next line is a divider or if this looks like a section header
            next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if divider_pattern.match(next_line) or (
                not line_stripped.endswith((".", ":", "✅", "❌")) and
                line_stripped.replace(" ", "").replace("-", "").replace("+", "").isalpha()
            ):
                is_header = True
                if current_section and section_content:
                    _process_section(ctx, current_section, section_content)
                current_section = line_stripped.lower()
                section_content = []
                continue

        if is_header and line_stripped.startswith("#"):
            if current_section and section_content:
                _process_section(ctx, current_section, section_content)
            section_content = []
        elif current_section:
            section_content.append(line)

    # Don't forget last section
    if current_section and section_content:
        _process_section(ctx, current_section, section_content)

    return ctx


def _process_section(ctx: NowContext, section_name: str, lines: list):
    """Process a parsed section and update context."""
    content = "\n".join(lines).strip()

    if "phase" in section_name or "status" in section_name:
        # Extract phase info
        if content:
            # Take first non-empty line as phase
            for line in lines:
                if line.strip():
                    ctx.phase = line.strip().lstrip("- ").strip()
                    break

    elif "red line" in section_name or "do not cross" in section_name:
        # "Red Lines (Do Not Cross)" section = training restrictions
        for line in lines:
            line_stripped = line.strip()
            if line_stripped and line_stripped.startswith(("*", "-", "•")):
                restriction = line_stripped.lstrip("*-• ").strip()
                if restriction and len(restriction) > 5:
                    ctx.training_restrictions.append(restriction)

    elif "biomarker" in section_name or "metric" in section_name or "key metric" in section_name or "current metric" in section_name:
        # Parse biomarkers
        for line in lines:
            line_lower = line.lower()

            # Ferritin: look for patterns like "Ferritin: 57" or "ferritin 57 ng/ml"
            ferritin_match = re.search(r"ferritin[:\s]+(\d+(?:\.\d+)?)", line_lower)
            if ferritin_match:
                ctx.ferritin = ferritin_match.group(1)

            # Max HR: look for patterns like "Max HR: 155" or "max heart rate 155"
            hr_match = re.search(r"max\s*(?:hr|heart\s*rate)[:\s]+(\d+)", line_lower)
            if hr_match:
                ctx.max_hr = hr_match.group(1)

            # HR response time: look for patterns like "HR response: 8.3min"
            response_match = re.search(
                r"(?:hr\s*)?response\s*(?:time)?[:\s]+(\d+(?:\.\d+)?)\s*(?:min|m)?",
                line_lower
            )
            if response_match:
                ctx.hr_response_time = response_match.group(1)

    elif "restriction" in section_name or "constraint" in section_name:
        # Parse training restrictions
        for line in lines:
            line_stripped = line.strip()
            if line_stripped and line_stripped.startswith(("-", "*", "•")):
                restriction = line_stripped.lstrip("-*• ").strip()
                if restriction:
                    ctx.training_restrictions.append(restriction)

    elif "protocol" in section_name or "compound" in section_name or "supplement" in section_name:
        # Parse active protocols
        for line in lines:
            line_stripped = line.strip()
            if line_stripped and line_stripped.startswith(("-", "*", "•")):
                protocol = line_stripped.lstrip("-*• ").strip()
                if protocol:
                    ctx.active_protocols.append(protocol)

    elif "milestone" in section_name or "next" in section_name:
        # Parse upcoming milestones
        for line in lines:
            line_stripped = line.strip()
            if line_stripped and line_stripped.startswith(("-", "*", "•")):
                milestone = line_stripped.lstrip("-*• ").strip()
                if milestone:
                    ctx.next_milestones.append(milestone)

    elif "decision" in section_name or "gate" in section_name:
        # Parse decision gates
        for line in lines:
            line_stripped = line.strip()
            if line_stripped and line_stripped.startswith(("-", "*", "•")):
                gate = line_stripped.lstrip("-*• ").strip()
                if gate:
                    ctx.decision_gates.append(gate)


def format_now_context(ctx: NowContext) -> list[str]:
    """Format NOW.md context as markdown lines for the report."""
    lines = []

    if ctx.fetch_error:
        lines.append("## Current Context")
        lines.append(f"*Could not load NOW.md: {ctx.fetch_error}*")
        lines.append("")
        return lines

    if not ctx.raw_content:
        return lines  # No context available, skip section

    lines.append("## Current Context (from NOW.md)")
    lines.append("")

    # Phase
    lines.append(f"**Phase:** {ctx.phase}")

    # Key Metrics - compact format
    metrics = []
    if ctx.ferritin:
        metrics.append(f"Ferritin {ctx.ferritin} (target >70)")
    if ctx.max_hr:
        metrics.append(f"Max HR {ctx.max_hr}")
    if ctx.hr_response_time:
        metrics.append(f"HR Response {ctx.hr_response_time}min")

    if metrics:
        lines.append(f"**Key Metrics:** {' | '.join(metrics)}")

    # Active Restrictions - important for training decisions
    if ctx.training_restrictions:
        restrictions_str = "; ".join(ctx.training_restrictions[:2])  # Keep concise
        lines.append(f"**Active Restrictions:** {restrictions_str}")

    # Next Milestone - just the first/most relevant one
    if ctx.next_milestones:
        lines.append(f"**Next Milestone:** {ctx.next_milestones[0]}")

    lines.append("")
    return lines


def apply_now_restrictions(ctx: NowContext, training_mode: str) -> tuple[str, list[str]]:
    """
    Apply NOW.md restrictions to training recommendations.

    Returns:
        - Potentially modified training mode
        - List of additional warnings based on NOW.md context
    """
    warnings = []

    if not ctx.raw_content:
        return training_mode, warnings

    # Check HR response time restriction
    if ctx.hr_response_time:
        try:
            hr_response = float(ctx.hr_response_time)
            if hr_response > 4.0:
                warnings.append(
                    f"HR response time ({hr_response:.1f}min) >4min - "
                    "use power-based intervals only (no HR targets)"
                )
        except ValueError:
            pass

    # Check ferritin levels
    if ctx.ferritin:
        try:
            ferritin = float(ctx.ferritin)
            if ferritin < 50:
                warnings.append(
                    f"Low ferritin ({ferritin:.0f} ng/mL) - "
                    "reduce high-intensity volume, prioritize iron protocol"
                )
            elif ferritin < 70:
                warnings.append(
                    f"Ferritin recovering ({ferritin:.0f} ng/mL) - "
                    "monitor fatigue, continue supplementation"
                )
        except ValueError:
            pass

    # Add explicit restrictions from NOW.md as warnings (avoid duplicates)
    # Skip restrictions that are already covered by automatic checks
    for restriction in ctx.training_restrictions:
        restriction_lower = restriction.lower()
        # Skip if this restriction is already covered by auto-generated warnings
        already_covered = any(
            restriction_lower.split("(")[0].strip() in w.lower() or
            w.lower().split("-")[0].strip() in restriction_lower
            for w in warnings
        )
        if not already_covered:
            warnings.append(restriction)

    return training_mode, warnings


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


def generate_report(now_ctx: Optional[NowContext] = None) -> str:
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

    # Apply NOW.md restrictions if available
    now_warnings = []
    if now_ctx and now_ctx.raw_content:
        training_mode, now_warnings = apply_now_restrictions(now_ctx, training_mode)

    # Week dates
    week_start, week_end = get_week_dates()

    # === HEADER ===
    mode_emoji = {"OPTIMAL": "🟢", "MAINTENANCE": "🟡", "DELOAD": "🔴"}.get(
        training_mode, "⚪"
    )
    lines.append(f"# Weekly Training Plan")
    lines.append(f"**Week of {week_start} - {week_end}**")
    lines.append("")

    # === NOW.MD CONTEXT (inserted right after header) ===
    if now_ctx:
        context_lines = format_now_context(now_ctx)
        if context_lines:
            lines.extend(context_lines)

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

        # Warnings (recovery-based)
        warnings = []
        if debt > 7:
            warnings.append(f"High sleep debt ({debt:.1f}hr) - prioritize sleep this week")
        if pd.notna(last_sleep) and last_sleep < 5:
            warnings.append(f"Very low sleep last night ({last_sleep:.1f}hr)")
        if pd.notna(hrv) and hrv < 20:
            warnings.append(f"Low HRV trend ({hrv:.0f}ms) - indicates autonomic stress")

        # Add NOW.md-based warnings
        warnings.extend(now_warnings)

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
    parser.add_argument(
        "--skip-now",
        action="store_true",
        help="Skip fetching NOW.md from Google Drive",
    )
    args = parser.parse_args()

    print("Generating weekly training report...")

    # Fetch and parse NOW.md context
    now_ctx = None
    if not args.skip_now:
        print("Fetching NOW.md from Google Drive...")
        content = fetch_now_md()
        if content:
            now_ctx = parse_now_md(content)
            print(f"  ✓ Loaded NOW.md (phase: {now_ctx.phase})")
        else:
            print("  ⚠ Could not fetch NOW.md (continuing without context)")
            now_ctx = NowContext(fetch_error="Could not fetch from Google Drive")
    else:
        print("  ⏭ Skipping NOW.md fetch (--skip-now)")

    report = generate_report(now_ctx)

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
        # Print first 50 lines (increased to show NOW.md context)
        preview_lines = report.split("\n")[:50]
        print("\n".join(preview_lines))
        if len(report.split("\n")) > 50:
            print("\n... (see full report in file)")

    return report


if __name__ == "__main__":
    main()
