"""Energy Balance Calculator for HDP Dashboard.

Provides weekly target calculations based on:
1. BMR (from profile or Mifflin-St Jeor)
2. NEAT baseline (BMR * 1.3 for desk job + daily movement)
3. Planned exercise calories (from actual power data or estimates)
4. Goal adjustment (maintenance, deficit, surplus)
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd

# =============================================================================
# Constants (Personalized for Peter)
# =============================================================================

# Profile data
BMR_KCAL = 1490  # Mifflin-St Jeor calculated
NEAT_MULTIPLIER = 1.3  # Desk job + daily movement
BODYWEIGHT_LB = 155  # Target for protein calculation

# Exercise calorie estimates
ZONE2_KCAL_PER_MIN = 10  # ~150W @ ~10 kcal/min
VO2MAX_KCAL_PER_MIN = 14  # ~200W @ ~14 kcal/min
STRENGTH_KCAL_PER_SESSION = 225  # ~5 kcal/min * 45 min

# TDEE estimates by training level
TDEE_BY_LEVEL = {
    "rest": 2050,  # Rest days
    "light": 2200,  # Light training
    "moderate": 2400,  # 3x zone2 + 2x strength
    "heavy": 2600,  # 3x zone2 + 2x row + 1x VO2 + 3x strength
}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class WeeklyTarget:
    """Weekly calorie and macro targets."""

    daily_target_kcal: float
    weekly_target_kcal: float
    protein_target_g: float
    breakdown: dict
    goal: str


@dataclass
class CardioSession:
    """Planned cardio session."""

    session_type: Literal["zone2", "vo2max", "easy"]
    duration_min: int
    equipment: Literal["bike", "row", "ski"] = "bike"


# =============================================================================
# Weekly Energy Balance Calculator
# =============================================================================


class WeeklyEnergyBalance:
    """
    Calculates weekly targets based on:
    1. BMR (from profile or Mifflin-St Jeor)
    2. NEAT baseline (BMR * 1.3 for desk job + daily movement)
    3. Planned exercise calories (from actual power data or estimates)
    4. Goal adjustment (maintenance, deficit, surplus)
    """

    def __init__(
        self,
        bmr: float = BMR_KCAL,
        neat_multiplier: float = NEAT_MULTIPLIER,
        bodyweight_lb: float = BODYWEIGHT_LB,
    ):
        """Initialize calculator with personal parameters.

        Args:
            bmr: Basal metabolic rate in kcal
            neat_multiplier: NEAT multiplier (1.2-1.4 typical)
            bodyweight_lb: Body weight for protein calculation
        """
        self.bmr = bmr
        self.neat_multiplier = neat_multiplier
        self.bodyweight_lb = bodyweight_lb
        self.neat_baseline = bmr * neat_multiplier

    def calculate_exercise_kcal(
        self,
        cardio_sessions: list[CardioSession],
        strength_sessions: int,
    ) -> float:
        """Calculate total exercise calories for planned sessions.

        Args:
            cardio_sessions: List of planned cardio sessions
            strength_sessions: Number of strength training sessions

        Returns:
            Total exercise kcal for the week
        """
        exercise_kcal = 0.0

        for session in cardio_sessions:
            if session.session_type == "zone2":
                # Zone 2 @ ~150W = ~10 kcal/min
                exercise_kcal += session.duration_min * ZONE2_KCAL_PER_MIN
            elif session.session_type == "vo2max":
                # VO2max @ ~200W = ~14 kcal/min
                exercise_kcal += session.duration_min * VO2MAX_KCAL_PER_MIN
            else:  # easy
                exercise_kcal += session.duration_min * 7  # ~7 kcal/min easy

        # Strength: ~5 kcal/min, assume 45 min sessions
        exercise_kcal += strength_sessions * STRENGTH_KCAL_PER_SESSION

        return exercise_kcal

    def calculate_week_target(
        self,
        cardio_sessions: list[CardioSession] | None = None,
        strength_sessions: int = 0,
        goal: Literal["maintenance", "cut", "lean_bulk"] = "maintenance",
    ) -> WeeklyTarget:
        """Calculate weekly calorie and macro targets.

        Args:
            cardio_sessions: List of planned cardio sessions
            strength_sessions: Number of strength sessions
            goal: Weight goal (maintenance, cut, lean_bulk)

        Returns:
            WeeklyTarget with daily/weekly targets and breakdown
        """
        if cardio_sessions is None:
            cardio_sessions = []

        # Calculate exercise calories
        exercise_kcal = self.calculate_exercise_kcal(cardio_sessions, strength_sessions)

        # Weekly TDEE = (NEAT * 7) + exercise
        weekly_tdee = (self.neat_baseline * 7) + exercise_kcal
        daily_avg_tdee = weekly_tdee / 7

        # Goal adjustment
        if goal == "maintenance":
            target = daily_avg_tdee
            goal_adjustment = 0
        elif goal == "cut":
            target = daily_avg_tdee - 300  # 300 kcal deficit
            goal_adjustment = -300
        else:  # lean_bulk
            target = daily_avg_tdee + 200  # 200 kcal surplus
            goal_adjustment = 200

        # Protein target: 1g/lb bodyweight
        protein_target = self.bodyweight_lb

        return WeeklyTarget(
            daily_target_kcal=round(target, 0),
            weekly_target_kcal=round(target * 7, 0),
            protein_target_g=round(protein_target, 0),
            breakdown={
                "bmr": self.bmr,
                "neat": round(self.neat_baseline - self.bmr, 0),
                "neat_total": round(self.neat_baseline, 0),
                "exercise_weekly": round(exercise_kcal, 0),
                "exercise_daily_avg": round(exercise_kcal / 7, 0),
                "goal_adjustment": goal_adjustment,
                "daily_tdee": round(daily_avg_tdee, 0),
            },
            goal=goal,
        )

    def quick_estimate(
        self,
        training_level: Literal["rest", "light", "moderate", "heavy"] = "moderate",
        goal: Literal["maintenance", "cut", "lean_bulk"] = "maintenance",
    ) -> WeeklyTarget:
        """Quick estimate using pre-calculated TDEE levels.

        Args:
            training_level: Activity level (rest, light, moderate, heavy)
            goal: Weight goal

        Returns:
            WeeklyTarget with estimated targets
        """
        base_tdee = TDEE_BY_LEVEL.get(training_level, 2400)

        # Goal adjustment
        if goal == "maintenance":
            target = base_tdee
            goal_adjustment = 0
        elif goal == "cut":
            target = base_tdee - 300
            goal_adjustment = -300
        else:  # lean_bulk
            target = base_tdee + 200
            goal_adjustment = 200

        return WeeklyTarget(
            daily_target_kcal=target,
            weekly_target_kcal=target * 7,
            protein_target_g=self.bodyweight_lb,
            breakdown={
                "bmr": self.bmr,
                "neat_total": round(self.neat_baseline, 0),
                "estimated_tdee": base_tdee,
                "goal_adjustment": goal_adjustment,
                "training_level": training_level,
            },
            goal=goal,
        )


# =============================================================================
# Incomplete Day Detection
# =============================================================================


def detect_incomplete_days(
    df: pd.DataFrame,
    min_calories: int = 1000,
    max_calories: int = 5000,
    min_protein: int = 80,
    rolling_threshold: float = 0.6,
) -> pd.DataFrame:
    """Detect incomplete nutrition logging days.

    Multi-factor completeness check:
    - Hard limits: calories between min_calories-max_calories
    - Protein sanity check: >= min_protein for someone lifting
    - Contextual check: >= rolling_threshold of 30-day rolling average

    Args:
        df: DataFrame with 'date', 'calories', 'protein_g' columns
        min_calories: Minimum plausible calorie intake
        max_calories: Maximum plausible calorie intake
        min_protein: Minimum protein for active individual
        rolling_threshold: Fraction of rolling average considered complete

    Returns:
        DataFrame with additional 'is_complete' and 'incomplete_reason' columns
    """
    if df.empty:
        return df

    result = df.copy()

    # Calculate 30-day rolling average
    result["cal_30d_avg"] = result["calories"].rolling(
        window=30, min_periods=1
    ).mean().shift(1)

    # Initialize completeness
    result["is_complete"] = True
    result["incomplete_reason"] = ""

    # Check conditions
    # No entry
    mask_no_entry = result["calories"].isna()
    result.loc[mask_no_entry, "is_complete"] = False
    result.loc[mask_no_entry, "incomplete_reason"] = "NO_ENTRY"

    # Below minimum
    mask_low = result["calories"] < min_calories
    result.loc[mask_low & result["is_complete"], "is_complete"] = False
    result.loc[mask_low & (result["incomplete_reason"] == ""), "incomplete_reason"] = (
        f"LOW_ABSOLUTE (<{min_calories})"
    )

    # Above maximum
    mask_high = result["calories"] > max_calories
    result.loc[mask_high & result["is_complete"], "is_complete"] = False
    result.loc[mask_high & (result["incomplete_reason"] == ""), "incomplete_reason"] = (
        f"HIGH_ABSOLUTE (>{max_calories})"
    )

    # Low protein (if available)
    if "protein_g" in result.columns:
        mask_low_protein = (result["protein_g"].notna()) & (result["protein_g"] < min_protein)
        result.loc[mask_low_protein & result["is_complete"], "is_complete"] = False
        result.loc[mask_low_protein & (result["incomplete_reason"] == ""), "incomplete_reason"] = (
            f"LOW_PROTEIN (<{min_protein}g)"
        )

    # Below rolling average threshold
    mask_low_vs_avg = (
        result["cal_30d_avg"].notna() &
        (result["calories"] < result["cal_30d_avg"] * rolling_threshold)
    )
    result.loc[mask_low_vs_avg & result["is_complete"], "is_complete"] = False
    result.loc[mask_low_vs_avg & (result["incomplete_reason"] == ""), "incomplete_reason"] = (
        result.apply(
            lambda r: f"LOW_VS_AVG (<{rolling_threshold*100:.0f}% of {r['cal_30d_avg']:.0f})"
            if pd.notna(r["cal_30d_avg"]) else "",
            axis=1
        )
    )

    return result


# =============================================================================
# Helper Functions
# =============================================================================


def calculate_implied_tdee(
    avg_intake: float,
    weight_change_lb: float,
    days: int,
) -> float:
    """Calculate implied TDEE from intake and weight change.

    Formula: TDEE = Avg Intake - (Weight Change × 3500 kcal/lb) / Days

    Args:
        avg_intake: Average daily calorie intake
        weight_change_lb: Weight change over period (positive = gained)
        days: Number of days in period

    Returns:
        Implied TDEE in kcal
    """
    if days <= 0:
        return avg_intake

    # 1 lb body weight = ~3500 kcal
    return avg_intake - (weight_change_lb * 3500 / days)


def get_training_level_from_sessions(
    cardio_sessions: int,
    strength_sessions: int,
    vo2_sessions: int = 0,
) -> str:
    """Determine training level from session counts.

    Args:
        cardio_sessions: Number of cardio sessions
        strength_sessions: Number of strength sessions
        vo2_sessions: Number of VO2max sessions

    Returns:
        Training level: "rest", "light", "moderate", or "heavy"
    """
    total_sessions = cardio_sessions + strength_sessions + vo2_sessions

    if total_sessions == 0:
        return "rest"
    elif total_sessions <= 2:
        return "light"
    elif total_sessions <= 5:
        return "moderate"
    else:
        return "heavy"


def format_target_summary(target: WeeklyTarget) -> str:
    """Format a WeeklyTarget as a readable summary.

    Args:
        target: WeeklyTarget object

    Returns:
        Formatted string summary
    """
    breakdown = target.breakdown

    lines = [
        f"**Daily Target: {target.daily_target_kcal:.0f} kcal**",
        f"Weekly Total: {target.weekly_target_kcal:.0f} kcal",
        f"Protein: {target.protein_target_g:.0f}g/day",
        "",
        "Breakdown:",
        f"- BMR: {breakdown.get('bmr', 0):.0f} kcal",
        f"- NEAT: {breakdown.get('neat', 0):.0f} kcal",
    ]

    if "exercise_daily_avg" in breakdown:
        lines.append(f"- Exercise: {breakdown['exercise_daily_avg']:.0f} kcal/day avg")

    if breakdown.get("goal_adjustment", 0) != 0:
        adj = breakdown["goal_adjustment"]
        sign = "+" if adj > 0 else ""
        lines.append(f"- Goal Adjustment: {sign}{adj:.0f} kcal ({target.goal})")

    return "\n".join(lines)
