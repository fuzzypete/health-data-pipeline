"""Dashboard constants and configuration."""

from datetime import datetime, timedelta

# Color palette matching Streamlit theme
COLORS = {
    # Primary colors
    "primary": "#00CED1",      # Teal - cardiovascular
    "secondary": "#FF6347",    # Tomato - strength
    "tertiary": "#32CD32",     # Lime green - recovery

    # Status colors
    "optimal": "#32CD32",      # Green
    "good": "#90EE90",         # Light green
    "warning": "#FFD700",      # Gold/yellow
    "attention": "#FFA500",    # Orange
    "alert": "#DC143C",        # Crimson red

    # Chart colors
    "cardio": "#00CED1",       # Teal
    "strength": "#FF6347",     # Tomato
    "recovery": "#32CD32",     # Lime green
    "labs": "#9370DB",         # Medium purple
    "ferritin": "#FFA500",     # Orange
    "lactate": "#FF69B4",      # Hot pink

    # Background
    "bg_dark": "#0E1117",
    "bg_light": "#262730",
    "text": "#FAFAFA",
}

# Time range options
TIME_RANGES = {
    "30 days": 30,
    "90 days": 90,
    "6 months": 180,
    "1 year": 365,
    "All time": 3650,
}


def get_date_range(time_range: str) -> tuple[datetime, datetime]:
    """Convert time range string to start/end dates."""
    end_date = datetime.now()
    days = TIME_RANGES.get(time_range, 90)
    start_date = end_date - timedelta(days=days)
    return start_date, end_date


# Biomarker reference ranges (from Peter's data)
BIOMARKER_TARGETS = {
    "Ferritin": {"low": 30, "optimal_low": 60, "optimal_high": 150, "high": 300, "unit": "ng/mL"},
    "Hemoglobin": {"low": 13.5, "optimal_low": 14.0, "optimal_high": 17.0, "high": 18.0, "unit": "g/dL"},
    "Hematocrit": {"low": 38, "optimal_low": 40, "optimal_high": 50, "high": 52, "unit": "%"},
    "HDL": {"low": 40, "optimal_low": 55, "optimal_high": 80, "high": 100, "unit": "mg/dL"},
    "LDL": {"low": 0, "optimal_low": 0, "optimal_high": 100, "high": 130, "unit": "mg/dL"},
    "eGFR": {"low": 60, "optimal_low": 90, "optimal_high": 120, "high": 150, "unit": "mL/min"},
    "ALT": {"low": 0, "optimal_low": 0, "optimal_high": 45, "high": 65, "unit": "U/L"},
}

# Cardio baselines (Peter's known peaks from May 2024)
CARDIO_BASELINES = {
    "max_hr_peak": 161,         # bpm - known peak
    "zone2_power_peak": 147,    # watts - known peak
    "hr_response_target": 4.0,  # minutes to 140 bpm
    "hr_recovery_target": 30,   # bpm drop in 1 min
}

# Recovery thresholds
RECOVERY_THRESHOLDS = {
    "optimal": 85,
    "moderate": 70,
    "compromised": 50,
}

# =============================================================================
# Strength Training Constants
# =============================================================================

# Exercise to muscle group mapping (based on workout_templates.py pools)
EXERCISE_MUSCLE_GROUPS = {
    # Upper Push
    "Dumbbell Bench Press": "Upper Push",
    "Dumbbell Incline Bench Press": "Upper Push",
    "Dumbbell Fly": "Upper Push",
    "Weighted Tricep Dip": "Upper Push",
    "Dumbbell One-Arm Press (Palms In)": "Upper Push",
    "Dumbbell Shoulder Press": "Upper Push",
    "Dumbbell Tricep Extension (Supine)": "Upper Push",
    "Dumbbell Tricep Extension": "Upper Push",
    "Dumbbell Tricep Kickback": "Upper Push",
    # Upper Pull
    "Weighted Chin-Up": "Upper Pull",
    "Chin-Up": "Upper Pull",
    "Weighted Pull-Up": "Upper Pull",
    "Pull-Up": "Upper Pull",
    "Dumbbell Bent-Over Row": "Upper Pull",
    "Dumbbell One-Arm Row": "Upper Pull",
    "Dumbbell Reverse Fly": "Upper Pull",
    "Dumbbell Incline Curl": "Upper Pull",
    "Dumbbell One-Arm Preacher Curl": "Upper Pull",
    "Dumbbell Hammer Curl": "Upper Pull",
    "Dumbbell Seated Bicep Curl": "Upper Pull",
    # Shoulders (Lateral)
    "Dumbbell Lateral Raise": "Shoulders",
    "Dumbbell Lateral Raise (Prone)": "Shoulders",
    # Lower Body
    "Bulgarian Split Squat": "Lower",
    "Dumbbell Squat": "Lower",
    "Barbell Hip Thrust": "Lower",
    "Dumbbell Stiff-Leg Deadlift": "Lower",
    "Kettlebell Single-Leg Deadlift": "Lower",
    "Dumbbell Calf Raise": "Lower",
    # Core
    "Dumbbell Side Bend": "Core",
    "Side Bridge": "Core",
    "Hanging Leg Raise": "Core",
    "Ab Rollout": "Core",
    "Dead Bug": "Core",
    "Plank": "Core",
}

# Key lifts for progression tracking (actual exercises used)
KEY_LIFTS = [
    "Dumbbell Bench Press",
    "Weighted Chin-Up",
    "Dumbbell Squat",
    "Barbell Hip Thrust",
]

# Muscle group colors for charts
MUSCLE_GROUP_COLORS = {
    "Upper Push": "#FF6B6B",   # Coral red
    "Upper Pull": "#4ECDC4",   # Teal
    "Shoulders": "#FFE66D",    # Yellow
    "Lower": "#95E1D3",        # Mint
    "Core": "#A8E6CF",         # Light green
}

# Progression status colors
PROGRESSION_STATUS_COLORS = {
    "READY": "#32CD32",        # Green - ready to increase
    "PROGRESSING": "#4169E1",  # Royal blue - recently increased
    "STABLE": "#808080",       # Gray - maintaining
    "STAGNANT": "#FFD700",     # Gold - needs attention
    "DELOAD": "#DC143C",       # Crimson - needs deload
}

# Progression status emoji
PROGRESSION_STATUS_EMOJI = {
    "READY": "🟢",
    "PROGRESSING": "📈",
    "STABLE": "⚪",
    "STAGNANT": "🟡",
    "DELOAD": "🔴",
}
