"""Tests for score calculation functions."""
import pytest

from analysis.apps.utils.scores import (
    # Recovery score components
    calc_sleep_duration_score,
    calc_sleep_efficiency_score,
    calc_sleep_debt_score,
    calc_hrv_vs_baseline_score,
    calc_rhr_vs_baseline_score,
    calc_acwr_score,
    calc_days_since_rest_score,
    calc_yesterday_intensity_score,
    calculate_recovery_score,
    # Cardio score components
    calc_max_hr_score,
    calc_zone2_power_score,
    calc_hr_response_score,
    calc_hr_recovery_score,
    calc_aerobic_efficiency_score,
    calc_cardio_rhr_score,
    calculate_cardio_score,
    # Vitals score components
    calc_bp_score,
    calc_vitals_rhr_score,
    calc_spo2_score,
    calc_respiratory_rate_score,
    calculate_vitals_score,
    # Other
    calc_vo2max_score,
    calc_glucose_score,
)


class TestRecoveryScoreComponents:
    """Test individual PRS component calculations."""

    def test_sleep_duration_score(self):
        assert calc_sleep_duration_score(7.5) == 100  # Target
        assert calc_sleep_duration_score(6.0) == 80  # 80% of target
        assert calc_sleep_duration_score(9.0) == 100  # Capped at 100
        assert calc_sleep_duration_score(0) == 0

    def test_sleep_efficiency_score(self):
        assert calc_sleep_efficiency_score(95) == 95
        assert calc_sleep_efficiency_score(None) == 50
        assert calc_sleep_efficiency_score(110) == 100  # Capped

    def test_sleep_debt_score(self):
        assert calc_sleep_debt_score(0) == 100  # No debt
        assert calc_sleep_debt_score(-2.5) == 50  # 2.5 hrs debt
        assert calc_sleep_debt_score(-5) == 0  # Max penalty
        assert calc_sleep_debt_score(-6) == 0  # Beyond max

    def test_hrv_vs_baseline_score(self):
        # At baseline (ratio=1.0): linear scale 0.6->0, 1.2->100 gives 66.7
        assert 60 <= calc_hrv_vs_baseline_score(40, 40) <= 70
        # 120% of baseline = 100
        assert calc_hrv_vs_baseline_score(48, 40) == 100
        # 60% of baseline = 0
        assert calc_hrv_vs_baseline_score(24, 40) == 0
        # No baseline
        assert calc_hrv_vs_baseline_score(40, 0) == 50

    def test_rhr_vs_baseline_score(self):
        # At baseline (diff=0): linear scale -5->100, +10->0 gives 66.7
        assert 60 <= calc_rhr_vs_baseline_score(52, 52) <= 70
        # 5 bpm below = 100
        assert calc_rhr_vs_baseline_score(47, 52) == 100
        # 10 bpm above = 0
        assert calc_rhr_vs_baseline_score(62, 52) == 0

    def test_acwr_score(self):
        # Sweet spot (0.8-1.3)
        assert calc_acwr_score(100, 100) == 100  # 1.0
        assert calc_acwr_score(120, 100) == 100  # 1.2
        # Too low
        assert calc_acwr_score(50, 100) == 50  # 0.5
        # Too high
        assert calc_acwr_score(160, 100) == 50  # 1.6
        # No baseline
        assert calc_acwr_score(100, 0) == 50

    def test_days_since_rest_score(self):
        assert calc_days_since_rest_score(0) == 100
        assert calc_days_since_rest_score(2) == 100
        assert calc_days_since_rest_score(3) == 80
        assert calc_days_since_rest_score(4) == 50
        assert calc_days_since_rest_score(7) == 20

    def test_yesterday_intensity_score(self):
        assert calc_yesterday_intensity_score("rest") == 100
        assert calc_yesterday_intensity_score("zone2") == 90
        assert calc_yesterday_intensity_score("strength") == 75
        assert calc_yesterday_intensity_score("intervals") == 50
        assert calc_yesterday_intensity_score("race") == 30
        assert calc_yesterday_intensity_score(None) == 100


class TestRecoveryScore:
    """Test full PRS calculation."""

    def test_recovery_score_optimal(self):
        result = calculate_recovery_score(
            sleep_duration_hours=8.0,
            sleep_efficiency_pct=95,
            sleep_debt_hours=0,
            current_hrv=48,  # 120% of baseline
            baseline_hrv=40,
            current_rhr=47,  # 5 below baseline
            baseline_rhr=52,
            acute_load_min=300,
            chronic_load_min=300,
            days_since_rest=1,
            yesterday_workout_type="rest",
        )
        assert result.total >= 85
        assert result.status == "Optimal"
        assert result.status_color == "green"

    def test_recovery_score_compromised(self):
        result = calculate_recovery_score(
            sleep_duration_hours=5.0,
            sleep_efficiency_pct=70,
            sleep_debt_hours=-4,
            current_hrv=28,  # 70% of baseline
            baseline_hrv=40,
            current_rhr=60,  # 8 above baseline
            baseline_rhr=52,
            acute_load_min=500,  # High acute load
            chronic_load_min=300,
            days_since_rest=5,
            yesterday_workout_type="intervals",
        )
        assert result.total < 70
        assert result.status in ["Compromised", "Recovery Needed"]


class TestCardioScoreComponents:
    """Test individual PCS component calculations."""

    def test_max_hr_score(self):
        assert calc_max_hr_score(161) == 100  # At peak
        assert calc_max_hr_score(145) == 90  # 90% of peak
        assert calc_max_hr_score(0) == 0

    def test_zone2_power_score(self):
        assert calc_zone2_power_score(147) == 100  # At peak
        assert calc_zone2_power_score(132) == 89  # ~90%
        assert calc_zone2_power_score(0) == 0

    def test_hr_response_score(self):
        assert calc_hr_response_score(3) == 100  # Under target
        assert calc_hr_response_score(4) == 100  # At target
        assert calc_hr_response_score(6) == 75  # Between 4-8
        assert calc_hr_response_score(10) == 25  # Between 8-12
        assert calc_hr_response_score(15) == 0  # Beyond 12
        assert calc_hr_response_score(None) == 50

    def test_hr_recovery_score(self):
        assert calc_hr_recovery_score(35) == 100  # Excellent
        assert calc_hr_recovery_score(30) == 100  # At target
        assert calc_hr_recovery_score(25) == 75  # Good
        assert calc_hr_recovery_score(10) == 0  # Poor
        assert calc_hr_recovery_score(None) == 50

    def test_cardio_rhr_score(self):
        assert calc_cardio_rhr_score(48) == 100  # Athlete
        assert calc_cardio_rhr_score(52) == 90
        assert calc_cardio_rhr_score(58) == 80
        assert calc_cardio_rhr_score(75) == 50


class TestCardioScore:
    """Test full PCS calculation."""

    def test_cardio_score_responsiveness_limiter(self):
        """Test that responsiveness tier drags down overall score."""
        result = calculate_cardio_score(
            recent_max_hr=153,  # 95% of peak
            current_zone2_watts=142,  # 97% of peak
            hr_response_minutes=9.2,  # Slow - 38 score
            hr_recovery_1min=22,  # Moderate - 55 score
            current_efficiency=1.05,
            best_efficiency=1.12,
            resting_hr=58,
            current_hrv=38,
            baseline_hrv=42,
        )
        # Responsiveness should be the limiter
        assert result.tiers["responsiveness"].score < result.tiers["capacity_ceiling"].score
        assert result.total < 80


class TestVitalsScoreComponents:
    """Test individual PVS component calculations."""

    def test_bp_score(self):
        # Normal
        assert calc_bp_score(115, 75) == 100
        # Elevated
        assert calc_bp_score(125, 75) == 85
        # Stage 1 HTN
        assert calc_bp_score(135, 85) == 60
        # Stage 2 HTN
        assert calc_bp_score(145, 95) == 30
        # Crisis
        assert calc_bp_score(185, 125) == 0

    def test_spo2_score(self):
        assert calc_spo2_score(99) == 100
        assert calc_spo2_score(96) == 90
        assert calc_spo2_score(93) == 50
        assert calc_spo2_score(85) == 0

    def test_respiratory_rate_score(self):
        assert calc_respiratory_rate_score(14) == 100  # Optimal
        assert calc_respiratory_rate_score(11) == 90  # Good
        assert calc_respiratory_rate_score(22) == 50  # Suboptimal
        assert calc_respiratory_rate_score(6) == 30  # Concerning


class TestVitalsScore:
    """Test full PVS calculation."""

    def test_vitals_score_excellent(self):
        result = calculate_vitals_score(
            systolic=115,
            diastolic=75,
            resting_hr=52,
            current_hrv=45,
            baseline_hrv=40,
            spo2=98,
            respiratory_rate=14,
        )
        assert result.total >= 85
        assert result.status == "Excellent"


class TestVO2maxScore:
    """Test VO2max scoring."""

    def test_vo2max_categories(self):
        # Superior
        result = calc_vo2max_score(45)
        assert result["score"] == 100
        assert result["category"] == "Superior"

        # Excellent
        result = calc_vo2max_score(38)
        assert result["score"] == 90
        assert result["category"] == "Excellent"

        # Good
        result = calc_vo2max_score(33)
        assert result["score"] == 75
        assert result["category"] == "Good"

        # Fair
        result = calc_vo2max_score(29)
        assert result["score"] == 55
        assert result["category"] == "Fair"

        # Poor
        result = calc_vo2max_score(25)
        assert result["score"] == 30
        assert result["category"] == "Poor"


class TestGlucoseScore:
    """Test glucose scoring."""

    def test_glucose_score(self):
        # Excellent
        assert calc_glucose_score(90, 90, 12) >= 90

        # Good
        assert 70 <= calc_glucose_score(75, 95, 18) <= 90

        # Fair (low time in range)
        assert calc_glucose_score(60, 110, 25) < 70
