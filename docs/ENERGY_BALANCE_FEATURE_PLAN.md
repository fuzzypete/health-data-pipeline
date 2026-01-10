# Energy Balance & Nutrition Targets Feature

**Status: IMPLEMENTED** (January 2026)

## Overview

This feature provides nutrition tracking, energy balance calculation, and weekly target planning in the HDP Dashboard. It uses a hybrid approach combining:
- Apple Health TDEE data (basal + active energy)
- Actual power data from Concept2 cardio workouts
- Estimated calorie burn for strength training
- Weight change analysis for implied TDEE validation

---

## Data Sources

| Source | Table | Key Columns | Quality |
|--------|-------|-------------|---------|
| Nutrition Log | `daily_summary` | `diet_calories_kcal`, `protein_g`, `carbs_g`, `total_fat_g` | Sparse (~58 days with calories) |
| Body Comp | `daily_summary` | `weight_lb`, `body_fat_pct` | Good (~75% complete) |
| Cardio | `cardio_strokes` | `watts`, `time_cumulative_s` | Excellent - actual power |
| Strength | `resistance_sets` | Sets, reps, weight | Excellent |
| Recovery | `oura_summary` | `readiness_score`, `sleep_score` | Good |
| Apple Health | `daily_summary` | `basal_energy_kcal`, `active_energy_kcal` | **FIXED** - now summing correctly |

### Key Metrics (Derived from Your Data)

```
Calculated BMR (Mifflin-St Jeor):     ~1,490 kcal
NEAT Baseline (BMR × 1.3):            ~1,940 kcal
Average cardio burn (training days):   ~322 kcal
Average strength burn (estimated):     ~200 kcal/session
```

**TDEE by Activity Level:**
- Rest days: ~2,050 kcal
- Light training: ~2,200 kcal
- Moderate training: ~2,400 kcal
- Heavy training: ~2,600 kcal

---

## Implementation

### Files Created/Modified

1. **`analysis/apps/utils/queries.py`** - Added nutrition query functions
2. **`analysis/apps/utils/energy_balance.py`** - New module for energy calculations
3. **`analysis/apps/hdp_dashboard.py`** - Added Nutrition & Energy section

### Query Functions (`utils/queries.py`)

| Function | Purpose |
|----------|---------|
| `query_nutrition_summary()` | Daily nutrition with multi-factor completeness flags |
| `query_exercise_calories()` | Exercise kcal from actual power data |
| `query_apple_health_energy()` | TDEE from Apple Health (basal + active) |
| `query_implied_tdee()` | Calculate TDEE from weight change + intake |
| `get_nutrition_score_data()` | 7-day averages for dashboard display |

### Energy Balance Module (`utils/energy_balance.py`)

**Classes:**
- `WeeklyEnergyBalance` - Main calculator with personalized parameters
- `CardioSession` - Data class for planned cardio sessions
- `WeeklyTarget` - Data class for calculated targets

**Key Functions:**
- `calculate_week_target()` - Full weekly target from planned sessions
- `quick_estimate()` - Pre-calculated TDEE by training level
- `detect_incomplete_days()` - Multi-factor incomplete day detection
- `format_target_summary()` - Format targets for display

### Dashboard Section

The **Nutrition & Energy** expander includes:
- Weekly summary metrics (avg intake, protein, logging streak)
- Calorie & protein trend chart with target line
- Apple Health TDEE display (7d average basal/active)
- Interactive **Weekly Target Calculator**

---

## Incomplete Day Detection

Multi-factor completeness heuristic (implemented in both SQL and Python):

```python
def is_complete_day(calories, protein, rolling_avg):
    # Hard limits
    if calories is None or calories < 1000 or calories > 5000:
        return False

    # Protein sanity check (for someone lifting)
    if protein is not None and protein < 80:
        return False

    # Contextual check against 30-day rolling average
    if rolling_avg is not None and calories < rolling_avg * 0.6:
        return False

    return True
```

Reason codes: `NO_ENTRY`, `LOW_ABSOLUTE`, `HIGH_ABSOLUTE`, `LOW_PROTEIN`, `LOW_VS_AVG`

---

## Weekly Target Calculator

The interactive calculator in the dashboard accepts:
- Zone 2 sessions (count + avg duration)
- VO2max sessions (count + duration)
- Strength sessions (count)
- Goal: Maintenance / Cut (-300) / Lean Bulk (+200)

**Calculation Formula:**
```
Weekly TDEE = (NEAT_baseline × 7) + exercise_kcal
Daily Target = Weekly TDEE / 7 + goal_adjustment

Where:
- NEAT_baseline = BMR × 1.3 = 1490 × 1.3 = 1937 kcal
- Zone 2 kcal = duration_min × 10 kcal/min
- VO2max kcal = duration_min × 14 kcal/min
- Strength kcal = sessions × 225 kcal
```

---

## Your Specific Targets

| Week Type | Est. TDEE | Recommended Target |
|-----------|-----------|-------------------|
| **Recovery** (light cardio only) | ~2,050 | 2,000-2,100 kcal |
| **Moderate** (3x zone2 + 2x strength) | ~2,350 | 2,300-2,400 kcal |
| **Aggressive** (3x zone2 + 2x row + 1x VO2 + 3x strength) | ~2,550 | 2,500-2,600 kcal |

**Protein target:** 150-160g daily (regardless of training load)

---

## Usage

### Run the Dashboard
```bash
cd ~/src/health-data-pipeline
streamlit run analysis/apps/hdp_dashboard.py
```

### Use Programmatically
```python
from utils.energy_balance import WeeklyEnergyBalance, CardioSession

calculator = WeeklyEnergyBalance(bmr=1490, bodyweight_lb=155)

# Plan a moderate training week
sessions = [
    CardioSession("zone2", 45),
    CardioSession("zone2", 45),
    CardioSession("zone2", 45),
]
target = calculator.calculate_week_target(
    cardio_sessions=sessions,
    strength_sessions=2,
    goal="maintenance"
)

print(f"Daily target: {target.daily_target_kcal} kcal")
print(f"Protein: {target.protein_target_g}g")
```

---

## Future Enhancements (Optional)

1. **Enhance `analyze_maintenance.py`**
   - Add weekly aggregation views
   - Export targets to dashboard-consumable format

2. **Add Macro Targets**
   - Carb/fat distribution based on training day type
   - Pre/post workout nutrition windows

3. **Weight Trend Integration**
   - Automatic TDEE adjustment based on actual weight change
   - Alert when weight trend diverges from goal

4. **Meal Planning**
   - Suggested meal templates to hit targets
   - Integration with nutrition logging apps
