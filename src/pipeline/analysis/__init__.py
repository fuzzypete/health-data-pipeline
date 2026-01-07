"""VO2 analysis modules."""
from .vo2_gates import (
    detect_gate1_hr_load,
    detect_gate2_rr_engagement,
    detect_gate3_recovery_impairment,
)
from .vo2_metrics import (
    calculate_hr_drop,
    calculate_vo2_stimulus_time,
    calculate_respiratory_vo2_metrics,
    analyze_vo2_session,
)
from .vo2_overlap import (
    calculate_gate_overlap,
    calculate_vo2_stimulus_summary,
    analyze_vo2_session_3gate,
    get_zone2_baseline_from_sessions,
)

__all__ = [
    # Gates
    "detect_gate1_hr_load",
    "detect_gate2_rr_engagement",
    "detect_gate3_recovery_impairment",
    # Metrics
    "calculate_hr_drop",
    "calculate_vo2_stimulus_time",
    "calculate_respiratory_vo2_metrics",
    "analyze_vo2_session",
    # Overlap
    "calculate_gate_overlap",
    "calculate_vo2_stimulus_summary",
    "analyze_vo2_session_3gate",
    "get_zone2_baseline_from_sessions",
]
