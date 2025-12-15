#!/usr/bin/env python3
"""
Calculate recovery-based training mode and adjust workout recommendations.

Integrates sleep debt/recovery state with progression recommendations to:
- Determine weekly training mode (OPTIMAL/MAINTENANCE/DELOAD)
- Adjust volume and intensity based on recovery
- Provide safe, recovery-aware training targets

Usage:
    python analysis/scripts/calculate_training_mode.py
    python analysis/scripts/calculate_training_mode.py --force-mode DELOAD
"""
import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow.parquet as pq

# Paths
DATA_DIR = Path("Data/Parquet")
OUTPUT_DIR = Path("analysis/outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class TrainingMode:
    """Training mode with volume/intensity adjustments."""

    OPTIMAL = "OPTIMAL"
    MAINTENANCE = "MAINTENANCE"
    DELOAD = "DELOAD"


@dataclass
class ModeConfig:
    """Configuration for a training mode."""

    name: str
    description: str
    volume_multiplier: float  # 1.0 = full volume
    intensity_adjustment: float  # Weight adjustment: 1.0 = as recommended, 0.9 = -10%
    max_sessions_per_week: int
    allow_progression: bool  # Whether to recommend weight increases
    emoji: str


# Training mode configurations
MODE_CONFIGS = {
    TrainingMode.OPTIMAL: ModeConfig(
        name="OPTIMAL",
        description="Full progressive overload - recovery supports growth",
        volume_multiplier=1.0,
        intensity_adjustment=1.0,
        max_sessions_per_week=4,
        allow_progression=True,
        emoji="🟢",
    ),
    TrainingMode.MAINTENANCE: ModeConfig(
        name="MAINTENANCE",
        description="Maintain strength - reduced volume to support recovery",
        volume_multiplier=0.8,
        intensity_adjustment=1.0,  # Keep weights same
        max_sessions_per_week=3,
        allow_progression=False,
        emoji="🟡",
    ),
    TrainingMode.DELOAD: ModeConfig(
        name="DELOAD",
        description="Active recovery - reduced load and volume",
        volume_multiplier=0.6,
        intensity_adjustment=0.9,  # Reduce weights 10%
        max_sessions_per_week=2,
        allow_progression=False,
        emoji="🔴",
    ),
}


@dataclass
class RecoveryMetrics:
    """Current recovery state metrics."""

    sleep_debt_7d: float
    last_night_sleep: Optional[float]
    last_night_deep: Optional[float]
    hrv_avg_7d: Optional[float]
    recovery_state: str  # OPTIMAL, MODERATE, POOR
    data_date: str


@dataclass
class TrainingRecommendation:
    """Complete training recommendation for the week."""

    mode: str
    mode_config: ModeConfig
    recovery_metrics: RecoveryMetrics
    volume_adjustment: str
    session_target: int
    intensity_note: str
    warnings: list[str]


def load_sleep_metrics() -> pd.DataFrame:
    """Load sleep metrics from the latest output file."""
    # Find most recent sleep metrics file
    sleep_files = sorted(OUTPUT_DIR.glob("sleep_metrics_*.csv"), reverse=True)
    if not sleep_files:
        raise FileNotFoundError(
            "No sleep metrics found. Run 'make sleep.metrics' first."
        )

    df = pd.read_csv(sleep_files[0])
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_progression_data() -> Optional[pd.DataFrame]:
    """Load progression recommendations from the latest output file."""
    prog_files = sorted(OUTPUT_DIR.glob("progression_*.csv"), reverse=True)
    if not prog_files:
        return None
    return pd.read_csv(prog_files[0])


def get_recovery_metrics(sleep_df: pd.DataFrame) -> RecoveryMetrics:
    """Extract current recovery metrics from sleep data."""
    # Get most recent data point with valid sleep data
    recent = sleep_df.dropna(subset=["sleep_total_hr"]).tail(1)

    if len(recent) == 0:
        # Fall back to most recent row even if sleep is NaN
        recent = sleep_df.tail(1)

    latest = recent.iloc[0]

    return RecoveryMetrics(
        sleep_debt_7d=latest.get("sleep_debt_7d_hr", 0) or 0,
        last_night_sleep=latest.get("sleep_total_hr"),
        last_night_deep=latest.get("sleep_deep_hr"),
        hrv_avg_7d=latest.get("hrv_avg_7d_ms"),
        recovery_state=latest.get("recovery_state", "MODERATE"),
        data_date=str(latest["date"].date()),
    )


def determine_training_mode(
    recovery: RecoveryMetrics,
    force_mode: Optional[str] = None,
) -> TrainingRecommendation:
    """
    Determine training mode based on recovery metrics.

    Mapping:
    - OPTIMAL recovery → OPTIMAL training (progressive overload)
    - MODERATE recovery → MAINTENANCE training (maintain strength)
    - POOR recovery → DELOAD training (active recovery)
    """
    warnings = []

    # Allow manual override
    if force_mode:
        mode = force_mode.upper()
        warnings.append(f"Mode manually set to {mode}")
    else:
        # Map recovery state to training mode
        recovery_to_mode = {
            "OPTIMAL": TrainingMode.OPTIMAL,
            "MODERATE": TrainingMode.MAINTENANCE,
            "POOR": TrainingMode.DELOAD,
        }
        mode = recovery_to_mode.get(recovery.recovery_state, TrainingMode.MAINTENANCE)

    config = MODE_CONFIGS[mode]

    # Generate warnings based on metrics
    if recovery.sleep_debt_7d > 10:
        warnings.append(f"Critical sleep debt: {recovery.sleep_debt_7d:.1f}hr - prioritize sleep")
    elif recovery.sleep_debt_7d > 7:
        warnings.append(f"High sleep debt: {recovery.sleep_debt_7d:.1f}hr - consider extra rest")

    if recovery.last_night_sleep and recovery.last_night_sleep < 5:
        warnings.append(f"Very low sleep last night: {recovery.last_night_sleep:.1f}hr")

    if recovery.hrv_avg_7d and recovery.hrv_avg_7d < 20:
        warnings.append(f"Low HRV trend: {recovery.hrv_avg_7d:.0f}ms - autonomic stress")

    # Build volume adjustment description
    vol_pct = int(config.volume_multiplier * 100)
    if vol_pct == 100:
        volume_adj = "Full volume"
    else:
        volume_adj = f"Reduced to {vol_pct}% volume"

    # Build intensity note
    if config.intensity_adjustment == 1.0:
        if config.allow_progression:
            intensity_note = "Follow progression recommendations"
        else:
            intensity_note = "Maintain current weights"
    else:
        reduction = int((1 - config.intensity_adjustment) * 100)
        intensity_note = f"Reduce weights by {reduction}%"

    return TrainingRecommendation(
        mode=mode,
        mode_config=config,
        recovery_metrics=recovery,
        volume_adjustment=volume_adj,
        session_target=config.max_sessions_per_week,
        intensity_note=intensity_note,
        warnings=warnings,
    )


def adjust_progression_recommendations(
    prog_df: pd.DataFrame,
    recommendation: TrainingRecommendation,
) -> pd.DataFrame:
    """Adjust progression recommendations based on training mode."""
    df = prog_df.copy()
    config = recommendation.mode_config

    # Adjust recommended weights
    if config.intensity_adjustment != 1.0:
        df["adjusted_weight_lbs"] = (
            df["current_weight_lbs"] * config.intensity_adjustment
        ).round(-0)  # Round to nearest 5
        df["adjusted_weight_lbs"] = (df["adjusted_weight_lbs"] / 5).round() * 5
    else:
        if config.allow_progression:
            # Use progression recommendations
            df["adjusted_weight_lbs"] = df["recommended_weight_lbs"]
        else:
            # Maintain current weights
            df["adjusted_weight_lbs"] = df["current_weight_lbs"]

    # Add mode context
    df["training_mode"] = recommendation.mode
    df["volume_multiplier"] = config.volume_multiplier

    # Override status if in DELOAD mode
    if recommendation.mode == TrainingMode.DELOAD:
        df["adjusted_status"] = "DELOAD"
        df["adjusted_recommendation"] = df.apply(
            lambda r: f"Deload: {r['adjusted_weight_lbs']:.0f}lbs (reduced from {r['current_weight_lbs']:.0f}lbs)",
            axis=1,
        )
    elif recommendation.mode == TrainingMode.MAINTENANCE:
        df["adjusted_status"] = df["status"].apply(
            lambda s: "MAINTAIN" if s == "READY" else s
        )
        df["adjusted_recommendation"] = df.apply(
            lambda r: f"Maintain: {r['adjusted_weight_lbs']:.0f}lbs"
            if r["status"] == "READY"
            else r["recommendation"],
            axis=1,
        )
    else:
        df["adjusted_status"] = df["status"]
        df["adjusted_recommendation"] = df["recommendation"]

    return df


def print_recommendation(rec: TrainingRecommendation, prog_df: Optional[pd.DataFrame]):
    """Print formatted training recommendation."""
    config = rec.mode_config
    metrics = rec.recovery_metrics

    print(f"\n{'='*70}")
    print("WEEKLY TRAINING RECOMMENDATION")
    print(f"{'='*70}")

    # Recovery summary
    print(f"\n--- Recovery Status (as of {metrics.data_date}) ---")
    print(f"  Sleep debt (7d):  {metrics.sleep_debt_7d:.1f} hr")
    if metrics.last_night_sleep:
        print(f"  Last night:       {metrics.last_night_sleep:.1f} hr")
    if metrics.hrv_avg_7d:
        print(f"  HRV (7d avg):     {metrics.hrv_avg_7d:.0f} ms")
    print(f"  Recovery state:   {metrics.recovery_state}")

    # Training mode
    print(f"\n--- Training Mode: {config.emoji} {rec.mode} ---")
    print(f"  {config.description}")
    print(f"\n  Volume:     {rec.volume_adjustment}")
    print(f"  Intensity:  {rec.intensity_note}")
    print(f"  Sessions:   {rec.session_target} per week max")

    # Warnings
    if rec.warnings:
        print(f"\n⚠️  Warnings:")
        for w in rec.warnings:
            print(f"    - {w}")

    # Adjusted progression recommendations
    if prog_df is not None and len(prog_df) > 0:
        print(f"\n--- Adjusted Exercise Targets ---")

        # Group by adjusted status
        for status in ["READY", "MAINTAIN", "DELOAD", "PROGRESSING", "STABLE"]:
            status_df = prog_df[prog_df["adjusted_status"] == status]
            if len(status_df) == 0:
                continue

            status_emoji = {
                "READY": "🟢",
                "MAINTAIN": "🟡",
                "DELOAD": "🔴",
                "PROGRESSING": "📈",
                "STABLE": "⚪",
            }.get(status, "")

            print(f"\n{status_emoji} {status}:")
            for _, row in status_df.iterrows():
                exercise = row["exercise"][:28]
                current = row["current_weight_lbs"]
                adjusted = row["adjusted_weight_lbs"]

                if adjusted != current:
                    print(f"    {exercise:<28} {current:>5.0f} → {adjusted:>5.0f} lbs")
                else:
                    print(f"    {exercise:<28} {adjusted:>5.0f} lbs")

    # Volume guidance
    if config.volume_multiplier < 1.0:
        print(f"\n--- Volume Guidance ---")
        print(f"  Reduce sets per exercise to {int(config.volume_multiplier * 100)}% of normal")
        print(f"  Example: 4 sets → {int(4 * config.volume_multiplier)} sets")
        print(f"           3 sets → {int(3 * config.volume_multiplier)} sets")


def main():
    parser = argparse.ArgumentParser(
        description="Calculate recovery-based training mode"
    )
    parser.add_argument(
        "--force-mode",
        type=str,
        choices=["OPTIMAL", "MAINTENANCE", "DELOAD"],
        help="Override automatic mode selection",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output CSV filename",
    )
    args = parser.parse_args()

    print("Loading recovery metrics...")
    try:
        sleep_df = load_sleep_metrics()
        recovery = get_recovery_metrics(sleep_df)
        print(f"  Latest data: {recovery.data_date}")
        print(f"  Recovery state: {recovery.recovery_state}")
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return

    print("\nDetermining training mode...")
    recommendation = determine_training_mode(recovery, args.force_mode)
    print(f"  Mode: {recommendation.mode}")

    print("\nLoading progression recommendations...")
    prog_df = load_progression_data()
    if prog_df is not None:
        print(f"  Found {len(prog_df)} exercises")
        adjusted_df = adjust_progression_recommendations(prog_df, recommendation)
    else:
        print("  No progression data found. Run 'make progression' first.")
        adjusted_df = None

    # Print full recommendation
    print_recommendation(recommendation, adjusted_df)

    # Save output
    if adjusted_df is not None:
        timestamp = datetime.now().strftime("%Y%m%d")
        output_name = args.output or f"training_plan_{timestamp}.csv"
        output_path = OUTPUT_DIR / output_name

        # Select output columns
        output_cols = [
            "exercise",
            "current_weight_lbs",
            "adjusted_weight_lbs",
            "current_reps",
            "adjusted_status",
            "adjusted_recommendation",
            "training_mode",
            "volume_multiplier",
        ]
        adjusted_df[output_cols].to_csv(output_path, index=False)
        print(f"\n✅ Training plan saved: {output_path}")

    return recommendation, adjusted_df


if __name__ == "__main__":
    main()
