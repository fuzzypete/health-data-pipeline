"""
Custom health score calculations for HDP Dashboard.

Implements:
- Peter's Recovery Score (PRS): Sleep + Autonomic + Training Load
- Peter's Cardio Score (PCS): Capacity + Responsiveness + Efficiency
- Peter's Vitals Score (PVS): BP + RHR + HRV + SpO2 + Respiratory Rate

All scores are 0-100 scale with status thresholds:
- 85-100: Optimal/Excellent (Green)
- 70-84: Moderate/Good (Yellow)
- 50-69: Compromised/Attention (Orange)
- <50: Recovery Needed/Concern (Red)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

# =============================================================================
# Type Definitions
# =============================================================================

Status = Literal["optimal", "moderate", "compromised", "recovery_needed"]
CardioStatus = Literal["excellent", "good", "compromised", "impaired"]
VitalsStatus = Literal["excellent", "good", "attention", "concern"]


@dataclass
class TierResult:
    """Result for a score tier with components."""
    score: int
    weight: str
    components: dict[str, int]


@dataclass
class ScoreResult:
    """Result for a composite score."""
    total: int
    status: str
    status_color: str
    tiers: dict[str, TierResult]


# =============================================================================
# Status Helpers
# =============================================================================

def get_recovery_status(score: int) -> tuple[str, str]:
    """Get status label and color for recovery score."""
    if score >= 85:
        return "Optimal", "green"
    elif score >= 70:
        return "Moderate", "yellow"
    elif score >= 50:
        return "Compromised", "orange"
    else:
        return "Recovery Needed", "red"


def get_cardio_status(score: int) -> tuple[str, str]:
    """Get status label and color for cardio score."""
    if score >= 85:
        return "Excellent", "green"
    elif score >= 70:
        return "Good", "yellow"
    elif score >= 50:
        return "Compromised", "orange"
    else:
        return "Impaired", "red"


def get_vitals_status(score: int) -> tuple[str, str]:
    """Get status label and color for vitals score."""
    if score >= 85:
        return "Excellent", "green"
    elif score >= 70:
        return "Good", "yellow"
    elif score >= 50:
        return "Attention", "orange"
    else:
        return "Concern", "red"


# =============================================================================
# Peter's Recovery Score (PRS) - Component Calculations
# =============================================================================

def calc_sleep_duration_score(hours: float | None, target: float = 7.5) -> int:
    """
    Sleep duration score.

    Args:
        hours: Total sleep duration in hours
        target: Target sleep hours (default 7.5)

    Returns:
        Score 0-100
    """
    if hours is None or (isinstance(hours, float) and math.isnan(hours)) or hours <= 0:
        return 0
    return min(100, int((hours / target) * 100))


def calc_sleep_efficiency_score(efficiency_pct: float) -> int:
    """
    Sleep efficiency score (direct mapping, already 0-100).

    Args:
        efficiency_pct: Sleep efficiency percentage from Oura

    Returns:
        Score 0-100
    """
    if efficiency_pct is None or (isinstance(efficiency_pct, float) and math.isnan(efficiency_pct)):
        return 50  # Neutral if missing
    return min(100, max(0, int(efficiency_pct)))


def calc_sleep_debt_score(debt_hours: float) -> int:
    """
    Sleep debt score based on 7-day cumulative deficit.

    Args:
        debt_hours: Cumulative sleep debt (negative = deficit)

    Returns:
        Score 0-100 (more debt = lower score)
    """
    if debt_hours is None or (isinstance(debt_hours, float) and math.isnan(debt_hours)):
        return 50 # Neutral if unknown

    # Each hour of debt costs 20 points
    # Max penalty at 5+ hours of debt
    return max(0, int(100 - (abs(debt_hours) * 20)))


def calc_hrv_vs_baseline_score(current_hrv: float, baseline_hrv: float) -> int:
    """
    HRV score based on percentage of 90-day baseline.

    Args:
        current_hrv: Current HRV value (ms)
        baseline_hrv: 90-day average HRV (ms)

    Returns:
        Score 0-100
        - 100% of baseline = 85 points
        - >120% of baseline = 100 points (cap)
        - <60% of baseline = 0 points
    """
    if baseline_hrv <= 0 or current_hrv is None or (isinstance(current_hrv, float) and math.isnan(current_hrv)):
        return 50  # Neutral if no baseline

    ratio = current_hrv / baseline_hrv

    if ratio >= 1.2:
        return 100
    elif ratio <= 0.6:
        return 0
    else:
        # Linear interpolation: 0.6 -> 0, 1.2 -> 100
        return int((ratio - 0.6) / 0.6 * 100)


def calc_rhr_vs_baseline_score(current_rhr: float, baseline_rhr: float) -> int:
    """
    Resting HR score (lower is better, inverted scale).

    Args:
        current_rhr: Current resting HR (bpm)
        baseline_rhr: 90-day average RHR (bpm)

    Returns:
        Score 0-100
        - At baseline = 85 points
        - 5+ bpm below baseline = 100 points
        - 10+ bpm above baseline = 0 points
    """
    if baseline_rhr <= 0 or current_rhr is None or (isinstance(current_rhr, float) and math.isnan(current_rhr)):
        return 50  # Neutral if no baseline

    diff = current_rhr - baseline_rhr

    if diff <= -5:
        return 100
    elif diff >= 10:
        return 0
    else:
        # Linear: -5 -> 100, +10 -> 0
        return int(100 - ((diff + 5) / 15 * 100))


def calc_acwr_score(acute_load: float, chronic_load: float) -> int:
    """
    Acute:Chronic Workload Ratio score.

    ACWR = 7-day load / 28-day average load
    Sweet spot: 0.8 - 1.3 (training optimally)

    Args:
        acute_load: 7-day training load (minutes)
        chronic_load: 28-day weekly average load (minutes)

    Returns:
        Score 0-100
    """
    if chronic_load <= 0 or (isinstance(acute_load, float) and math.isnan(acute_load)):
        return 50  # No baseline, neutral score

    acwr = acute_load / chronic_load

    if 0.8 <= acwr <= 1.3:
        return 100
    elif 0.5 <= acwr < 0.8:
        return int(50 + (acwr - 0.5) / 0.3 * 50)
    elif 1.3 < acwr <= 1.5:
        return int(100 - (acwr - 1.3) / 0.2 * 50)
    else:
        return 50  # Too low or too high


def calc_days_since_rest_score(days: int) -> int:
    """
    Days since rest day score.

    Args:
        days: Number of consecutive training days

    Returns:
        Score 0-100
    """
    scores = {0: 100, 1: 100, 2: 100, 3: 80, 4: 50}
    return scores.get(days, 20)


def calc_yesterday_intensity_score(workout_type: str | None) -> int:
    """
    Yesterday's workout intensity score.

    Args:
        workout_type: Type of workout ('rest', 'zone2', 'strength', 'intervals', 'race')

    Returns:
        Score 0-100
    """
    if workout_type is None:
        return 100  # Assume rest

    scores = {
        "rest": 100,
        "zone2": 90,
        "strength": 75,
        "intervals": 50,
        "race": 30,
    }
    return scores.get(workout_type.lower(), 75)


def calculate_recovery_score(
    sleep_duration_hours: float,
    sleep_efficiency_pct: float | None,
    sleep_debt_hours: float,
    current_hrv: float | None,
    baseline_hrv: float,
    current_rhr: float | None,
    baseline_rhr: float,
    acute_load_min: float,
    chronic_load_min: float,
    days_since_rest: int,
    yesterday_workout_type: str | None,
) -> ScoreResult:
    """
    Calculate Peter's Recovery Score (PRS).

    Tiers:
    - Sleep & Rest (40%): duration, efficiency, debt
    - Autonomic State (30%): HRV vs baseline, RHR vs baseline
    - Training Load (30%): ACWR, days since rest, yesterday intensity

    Returns:
        ScoreResult with total score, status, and tier breakdown
    """
    # Calculate component scores
    sleep_duration = calc_sleep_duration_score(sleep_duration_hours)
    sleep_efficiency = calc_sleep_efficiency_score(sleep_efficiency_pct)
    sleep_debt = calc_sleep_debt_score(sleep_debt_hours)
    hrv_score = calc_hrv_vs_baseline_score(current_hrv, baseline_hrv)
    rhr_score = calc_rhr_vs_baseline_score(current_rhr, baseline_rhr)
    acwr_score = calc_acwr_score(acute_load_min, chronic_load_min)
    rest_days_score = calc_days_since_rest_score(days_since_rest)
    yesterday_score = calc_yesterday_intensity_score(yesterday_workout_type)

    # Calculate tier scores (weighted average within tier)
    sleep_tier = (
        sleep_duration * (15 / 40) +
        sleep_efficiency * (10 / 40) +
        sleep_debt * (15 / 40)
    )

    autonomic_tier = (
        hrv_score * (20 / 30) +
        rhr_score * (10 / 30)
    )

    training_tier = (
        acwr_score * (15 / 30) +
        rest_days_score * (10 / 30) +
        yesterday_score * (5 / 30)
    )

    # Final score (tier weights)
    total = (
        sleep_tier * 0.40 +
        autonomic_tier * 0.30 +
        training_tier * 0.30
    )

    status_label, status_color = get_recovery_status(int(total))

    return ScoreResult(
        total=int(total),
        status=status_label,
        status_color=status_color,
        tiers={
            "sleep_rest": TierResult(
                score=int(sleep_tier),
                weight="40%",
                components={
                    "sleep_duration": sleep_duration,
                    "sleep_efficiency": sleep_efficiency,
                    "sleep_debt": sleep_debt,
                },
            ),
            "autonomic": TierResult(
                score=int(autonomic_tier),
                weight="30%",
                components={
                    "hrv_vs_baseline": hrv_score,
                    "resting_hr": rhr_score,
                },
            ),
            "training_load": TierResult(
                score=int(training_tier),
                weight="30%",
                components={
                    "acwr": acwr_score,
                    "days_since_rest": rest_days_score,
                    "yesterday_intensity": yesterday_score,
                },
            ),
        },
    )


# =============================================================================
# Peter's Cardio Score (PCS) - Component Calculations
# =============================================================================

# Fixed baselines from May 2024 peak
PEAK_MAX_HR = 161  # bpm
PEAK_ZONE2_POWER = 147  # watts
TARGET_HR_RESPONSE_MIN = 4.0  # minutes to reach 140 bpm
TARGET_HR_RECOVERY_BPM = 30  # bpm drop in 1 minute


def calc_max_hr_score(recent_max_hr: int, peak_max_hr: int = PEAK_MAX_HR) -> int:
    """
    Max HR score as percentage of known peak.

    Args:
        recent_max_hr: 7-day max HR (bpm)
        peak_max_hr: Known peak max HR

    Returns:
        Score 0-100
    """
    if recent_max_hr <= 0 or (isinstance(recent_max_hr, float) and math.isnan(recent_max_hr)):
        return 0
    return min(100, int((recent_max_hr / peak_max_hr) * 100))


def calc_zone2_power_score(
    current_z2_watts: float,
    peak_z2_watts: float = PEAK_ZONE2_POWER,
) -> int:
    """
    Zone 2 power ceiling score.

    Args:
        current_z2_watts: Current sustainable Z2 power
        peak_z2_watts: Known peak Z2 power

    Returns:
        Score 0-100
    """
    if current_z2_watts <= 0 or (isinstance(current_z2_watts, float) and math.isnan(current_z2_watts)):
        return 0
    return min(100, int((current_z2_watts / peak_z2_watts) * 100))


def calc_hr_response_score(minutes_to_140: float) -> int:
    """
    HR response time score (time to reach 140 bpm).

    Args:
        minutes_to_140: Minutes from workout start to 140 bpm

    Returns:
        Score 0-100
        - <4 min = 100 (target met)
        - 4-8 min = linear 100 -> 50
        - 8-12 min = linear 50 -> 0
        - >12 min = 0
    """
    if minutes_to_140 is None or (isinstance(minutes_to_140, float) and math.isnan(minutes_to_140)):
        return 50  # Unknown

    if minutes_to_140 <= 4:
        return 100
    elif minutes_to_140 <= 8:
        return int(100 - ((minutes_to_140 - 4) / 4 * 50))
    elif minutes_to_140 <= 12:
        return int(50 - ((minutes_to_140 - 8) / 4 * 50))
    else:
        return 0


def calc_hr_recovery_score(hr_drop_1min: int | None) -> int:
    """
    HR recovery score (drop in first 60 seconds after peak).

    Args:
        hr_drop_1min: HR drop in bpm over 1 minute

    Returns:
        Score 0-100
        - >30 bpm = 100 (excellent parasympathetic response)
        - 20-30 bpm = linear 50-100
        - <15 bpm = 0 (poor recovery)
    """
    if hr_drop_1min is None or (isinstance(hr_drop_1min, float) and math.isnan(hr_drop_1min)):
        return 50  # Unknown

    if hr_drop_1min >= 30:
        return 100
    elif hr_drop_1min >= 20:
        return int(50 + ((hr_drop_1min - 20) / 10 * 50))
    elif hr_drop_1min >= 15:
        return int((hr_drop_1min - 15) / 5 * 50)
    else:
        return 0


def calc_aerobic_efficiency_score(
    current_efficiency: float,
    best_efficiency: float,
) -> int:
    """
    Aerobic efficiency score (watts per heartbeat at Z2).

    Args:
        current_efficiency: Current W/bpm ratio
        best_efficiency: Historical best W/bpm ratio

    Returns:
        Score 0-100
    """
    if best_efficiency <= 0 or current_efficiency is None or (isinstance(current_efficiency, float) and math.isnan(current_efficiency)):
        return 50
    return min(100, int((current_efficiency / best_efficiency) * 100))


def calc_cardio_rhr_score(resting_hr: int) -> int:
    """
    Resting HR score for cardiovascular health (absolute scale).

    Args:
        resting_hr: Resting heart rate in bpm

    Returns:
        Score 0-100
    """
    if resting_hr is None or (isinstance(resting_hr, float) and math.isnan(resting_hr)):
        return 50

    if resting_hr < 50:
        return 100  # Athlete level
    elif resting_hr < 55:
        return 90
    elif resting_hr < 60:
        return 80
    elif resting_hr < 65:
        return 70
    elif resting_hr < 70:
        return 60
    else:
        return 50


def calc_hrv_health_score(current_hrv: float, baseline_hrv: float) -> int:
    """
    HRV health score for cardio context.

    Same calculation as recovery HRV score.
    """
    return calc_hrv_vs_baseline_score(current_hrv, baseline_hrv)


def calculate_cardio_score(
    recent_max_hr: int,
    current_zone2_watts: float,
    hr_response_minutes: float | None,
    hr_recovery_1min: int | None,
    current_efficiency: float | None,
    best_efficiency: float,
    resting_hr: int | None,
    current_hrv: float | None,
    baseline_hrv: float,
) -> ScoreResult:
    """
    Calculate Peter's Cardio Score (PCS).

    Tiers:
    - Capacity & Ceiling (35%): max HR, Zone 2 power
    - Responsiveness (35%): HR response time, HR recovery
    - Efficiency & Baseline (30%): aerobic efficiency, resting HR, HRV

    Returns:
        ScoreResult with total score, status, and tier breakdown
    """
    # Calculate component scores
    max_hr = calc_max_hr_score(recent_max_hr)
    zone2_power = calc_zone2_power_score(current_zone2_watts)
    hr_response = calc_hr_response_score(hr_response_minutes)
    hr_recovery = calc_hr_recovery_score(hr_recovery_1min)
    aero_efficiency = calc_aerobic_efficiency_score(current_efficiency, best_efficiency)
    rhr = calc_cardio_rhr_score(resting_hr)
    hrv = calc_hrv_health_score(current_hrv, baseline_hrv)

    # Calculate tier scores
    capacity_tier = (
        max_hr * (20 / 35) +
        zone2_power * (15 / 35)
    )

    responsiveness_tier = (
        hr_response * (20 / 35) +
        hr_recovery * (15 / 35)
    )

    efficiency_tier = (
        aero_efficiency * (15 / 30) +
        rhr * (10 / 30) +
        hrv * (5 / 30)
    )

    # Final score
    total = (
        capacity_tier * 0.35 +
        responsiveness_tier * 0.35 +
        efficiency_tier * 0.30
    )

    status_label, status_color = get_cardio_status(int(total))

    return ScoreResult(
        total=int(total),
        status=status_label,
        status_color=status_color,
        tiers={
            "capacity_ceiling": TierResult(
                score=int(capacity_tier),
                weight="35%",
                components={
                    "max_hr": max_hr,
                    "zone2_power": zone2_power,
                },
            ),
            "responsiveness": TierResult(
                score=int(responsiveness_tier),
                weight="35%",
                components={
                    "hr_response_time": hr_response,
                    "hr_recovery": hr_recovery,
                },
            ),
            "efficiency_baseline": TierResult(
                score=int(efficiency_tier),
                weight="30%",
                components={
                    "aerobic_efficiency": aero_efficiency,
                    "resting_hr": rhr,
                    "hrv_health": hrv,
                },
            ),
        },
    )


# =============================================================================
# Peter's Vitals Score (PVS) - Component Calculations
# =============================================================================

def calc_bp_score(systolic: float, diastolic: float) -> int:
    """
    Blood pressure score based on AHA categories.

    Args:
        systolic: Systolic BP (mmHg)
        diastolic: Diastolic BP (mmHg)

    Returns:
        Score 0-100
    """
    if systolic is None or diastolic is None:
        return 50
    if (isinstance(systolic, float) and math.isnan(systolic)) or (isinstance(diastolic, float) and math.isnan(diastolic)):
        return 50

    if systolic > 180 or diastolic > 120:
        return 0  # Hypertensive crisis
    elif systolic >= 140 or diastolic >= 90:
        return 30  # Stage 2 HTN
    elif systolic >= 130 or diastolic >= 80:
        return 60  # Stage 1 HTN
    elif systolic >= 120 and diastolic < 80:
        return 85  # Elevated
    else:
        return 100  # Normal


def calc_vitals_rhr_score(resting_hr: int | None) -> int:
    """
    Resting HR score for vitals context (absolute scale).

    Args:
        resting_hr: Resting heart rate in bpm

    Returns:
        Score 0-100
    """
    if resting_hr is None or (isinstance(resting_hr, float) and math.isnan(resting_hr)):
        return 50

    if resting_hr < 50:
        return 100  # Athlete level
    elif resting_hr < 55:
        return 95
    elif resting_hr < 60:
        return 85
    elif resting_hr < 65:
        return 75
    elif resting_hr < 70:
        return 60
    elif resting_hr < 80:
        return 40
    else:
        return 20  # Elevated


def calc_spo2_score(spo2: float | None) -> int:
    """
    Oxygen saturation score.

    Args:
        spo2: SpO2 percentage

    Returns:
        Score 0-100
    """
    if spo2 is None or (isinstance(spo2, float) and math.isnan(spo2)):
        return 50

    if spo2 >= 98:
        return 100
    elif spo2 >= 95:
        return 90
    elif spo2 >= 92:
        return 50  # Mild hypoxemia
    elif spo2 >= 88:
        return 20  # Moderate hypoxemia
    else:
        return 0  # Severe


def calc_respiratory_rate_score(breaths_per_min: float | None) -> int:
    """
    Respiratory rate score.

    Normal adult: 12-20 breaths/min
    Athletes: 8-12 breaths/min

    Args:
        breaths_per_min: Respiratory rate

    Returns:
        Score 0-100
    """
    if breaths_per_min is None or (isinstance(breaths_per_min, float) and math.isnan(breaths_per_min)):
        return 50

    if 12 <= breaths_per_min <= 16:
        return 100  # Optimal
    elif 10 <= breaths_per_min < 12 or 16 < breaths_per_min <= 18:
        return 90  # Good
    elif 8 <= breaths_per_min < 10 or 18 < breaths_per_min <= 20:
        return 75  # Acceptable
    elif breaths_per_min < 8 or breaths_per_min > 24:
        return 30  # Concerning
    else:
        return 50  # Suboptimal


def calculate_vitals_score(
    systolic: float | None,
    diastolic: float | None,
    resting_hr: int | None,
    current_hrv: float | None,
    baseline_hrv: float,
    spo2: float | None,
    respiratory_rate: float | None,
) -> ScoreResult:
    """
    Calculate Peter's Vitals Score (PVS).

    Components:
    - Blood Pressure (30%)
    - Resting HR (25%)
    - HRV (25%)
    - SpO2 (10%)
    - Respiratory Rate (10%)

    Returns:
        ScoreResult with total score, status, and component breakdown
    """
    # Calculate component scores
    bp = calc_bp_score(systolic, diastolic)
    rhr = calc_vitals_rhr_score(resting_hr)
    hrv = calc_hrv_vs_baseline_score(current_hrv, baseline_hrv)
    spo2_score = calc_spo2_score(spo2)
    resp = calc_respiratory_rate_score(respiratory_rate)

    # Final score (weighted)
    total = (
        bp * 0.30 +
        rhr * 0.25 +
        hrv * 0.25 +
        spo2_score * 0.10 +
        resp * 0.10
    )

    status_label, status_color = get_vitals_status(int(total))

    # For vitals, we don't use tiers - just components
    return ScoreResult(
        total=int(total),
        status=status_label,
        status_color=status_color,
        tiers={
            "components": TierResult(
                score=int(total),
                weight="100%",
                components={
                    "blood_pressure": bp,
                    "resting_hr": rhr,
                    "hrv": hrv,
                    "spo2": spo2_score,
                    "respiratory_rate": resp,
                },
            ),
        },
    )


# =============================================================================
# VO2max Scoring (Standalone)
# =============================================================================

def calc_vo2max_score(vo2max: float, age: int = 56) -> dict:
    """
    Score VO2max based on age-adjusted percentiles (ACSM men 55-59).

    Args:
        vo2max: VO2max in ml/kg/min
        age: Age in years (for percentile lookup)

    Returns:
        Dict with score, category, percentile, value
    """
    if vo2max is None or vo2max <= 0 or (isinstance(vo2max, float) and math.isnan(vo2max)):
        return {
            "score": 0,
            "category": "Unknown",
            "percentile": "N/A",
            "value": None,
        }

    # Age 55-59 male percentiles (ACSM)
    if vo2max >= 41:
        score = 100
        category = "Superior"
        percentile = "90th+"
    elif vo2max >= 36:
        score = 90
        category = "Excellent"
        percentile = "75th-90th"
    elif vo2max >= 32:
        score = 75
        category = "Good"
        percentile = "50th-75th"
    elif vo2max >= 27:
        score = 55
        category = "Fair"
        percentile = "25th-50th"
    else:
        score = 30
        category = "Poor"
        percentile = "<25th"

    status_label, status_color = get_cardio_status(score)

    return {
        "score": score,
        "category": category,
        "percentile": percentile,
        "value": vo2max,
        "status": status_label,
        "status_color": status_color,
    }


# =============================================================================
# Glucose Scoring (for CGM panel)
# =============================================================================

def calc_glucose_score(
    time_in_range_pct: float,
    avg_glucose: float,
    coefficient_of_variation: float,
) -> int:
    """
    Composite glucose score.

    Args:
        time_in_range_pct: % time between 70-140 mg/dL
        avg_glucose: Average glucose (mg/dL)
        coefficient_of_variation: CV = std/mean * 100

    Returns:
        Score 0-100
    """
    # Check for NaNs
    if math.isnan(time_in_range_pct) or math.isnan(avg_glucose) or math.isnan(coefficient_of_variation):
        return 0

    # Time in range score (target >70%)
    if time_in_range_pct >= 85:
        tir_score = 100
    elif time_in_range_pct >= 70:
        tir_score = int(70 + (time_in_range_pct - 70) * 2)
    else:
        tir_score = int(time_in_range_pct)

    # Average glucose score (target 80-100 mg/dL)
    if 80 <= avg_glucose <= 100:
        avg_score = 100
    elif 70 <= avg_glucose < 80 or 100 < avg_glucose <= 110:
        avg_score = 85
    elif 60 <= avg_glucose < 70 or 110 < avg_glucose <= 125:
        avg_score = 65
    else:
        avg_score = 40

    # Variability score (CV target <20%)
    if coefficient_of_variation < 15:
        cv_score = 100
    elif coefficient_of_variation < 20:
        cv_score = 80
    elif coefficient_of_variation < 25:
        cv_score = 60
    else:
        cv_score = 40

    # Weighted total
    return int(tir_score * 0.5 + avg_score * 0.3 + cv_score * 0.2)
