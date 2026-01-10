# Energy Balance & Nutrition Targets Feature Plan

## Data Sources Analysis

### Available Data

| Source | Table | Key Columns | Quality |
|--------|-------|-------------|---------|
| Nutrition Log | `daily_summary` | `diet_calories_kcal`, `protein_g`, `carbs_g`, `total_fat_g` | ~80% complete days |
| Body Comp | `daily_summary` | `weight_lb`, `body_fat_pct` | ~75% complete |
| Cardio | `cardio_strokes` | `watts`, `time_cumulative_s` | Excellent - actual power |
| Strength | `resistance_sets` | Sets, reps, weight | Excellent |
| Recovery | `oura_summary` | `readiness_score`, `sleep_score` | Good |
| Protocols | `protocol_history` | Compounds, dosages | Good (affects weight interpretation) |
| Apple Health | `daily_summary` | `basal_energy_kcal`, `active_energy_kcal` | **FIXED** - now summing correctly |

### Key Findings from Your Data

```
Implied TDEE (from weight + intake):  ~2,444 kcal (high variance)
Calculated BMR (Mifflin-St Jeor):     ~1,490 kcal
Average cardio burn (training days):   ~322 kcal
Average strength burn (estimated):     ~200 kcal/session
```

**TDEE by Activity Level (derived from your data):**
- Rest days: ~2,050 kcal
- Light training: ~2,200 kcal
- Moderate training: ~2,400 kcal
- Heavy training: ~2,600 kcal

---

## Incomplete Day Detection Heuristic

Current `analyze_maintenance.py` uses:
- `< 800 kcal` = flagged as incomplete
- `< 50% of 30-day rolling avg` = flagged

**Proposed Enhanced Heuristic:**

```python
def is_complete_nutrition_day(row, rolling_avg):
    """Multi-factor completeness check."""
    cal = row['diet_calories_kcal']
    protein = row['protein_g']

    # Hard limits
    if pd.isna(cal) or cal < 1000 or cal > 5000:
        return False

    # Protein sanity check (for someone lifting)
    if pd.notna(protein) and protein < 80:
        return False  # Probably incomplete

    # Contextual check against rolling average
    if pd.notna(rolling_avg) and cal < rolling_avg * 0.6:
        return False

    # Neighbor check: if both prev and next day are 2x higher, flag
    # (catches single-day logging failures)

    return True
```

---

## Architecture: Weekly Energy Balance Calculator

### Core Calculation

```python
class WeeklyEnergyBalance:
    """
    Calculates weekly targets based on:
    1. BMR (from profile or Mifflin-St Jeor)
    2. NEAT baseline (BMR * 1.3 for desk job + daily movement)
    3. Planned exercise calories (from actual power data or estimates)
    4. Goal adjustment (maintenance, deficit, surplus)
    """

    def calculate_week_target(
        self,
        planned_cardio_sessions: list[dict],  # [{type: 'bike', duration_min: 45, intensity: 'zone2'}]
        planned_strength_sessions: int,
        goal: str = 'maintenance',  # 'maintenance', 'cut', 'lean_bulk'
    ) -> dict:

        bmr = 1490  # From profile
        neat_baseline = bmr * 1.3  # ~1940 kcal

        # Calculate exercise burn
        exercise_kcal = 0
        for session in planned_cardio_sessions:
            if session['intensity'] == 'zone2':
                # Zone 2 @ ~150W = ~10 kcal/min
                exercise_kcal += session['duration_min'] * 10
            elif session['intensity'] == 'vo2max':
                # VO2max @ ~200W = ~14 kcal/min
                exercise_kcal += session['duration_min'] * 14

        # Strength: ~5 kcal/min, assume 45 min sessions
        exercise_kcal += planned_strength_sessions * 225

        weekly_tdee = (neat_baseline * 7) + exercise_kcal
        daily_avg_tdee = weekly_tdee / 7

        # Goal adjustment
        if goal == 'maintenance':
            target = daily_avg_tdee
        elif goal == 'cut':
            target = daily_avg_tdee - 300  # 300 kcal deficit
        elif goal == 'lean_bulk':
            target = daily_avg_tdee + 200  # 200 kcal surplus

        return {
            'daily_target_kcal': target,
            'weekly_target_kcal': target * 7,
            'protein_target_g': 155,  # 1g/lb bodyweight
            'breakdown': {
                'bmr': bmr,
                'neat': neat_baseline - bmr,
                'exercise_daily_avg': exercise_kcal / 7,
                'goal_adjustment': target - daily_avg_tdee,
            }
        }
```

---

## Dashboard Integration

### New Section: "Nutrition & Energy"

Add to `hdp_dashboard.py` after the metabolic section:

```python
def render_nutrition_section(start_date: datetime, end_date: datetime):
    """Render nutrition and energy balance section."""

    st.markdown("### Nutrition & Energy Balance")

    # Weekly summary card
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Weekly Avg Intake",
            f"{weekly_intake:.0f} kcal",
            delta=f"{weekly_intake - target:.0f} vs target"
        )

    with col2:
        st.metric(
            "Avg Protein",
            f"{weekly_protein:.0f}g",
            delta=f"{weekly_protein - 155:.0f}g vs target"
        )

    with col3:
        st.metric(
            "Logging Streak",
            f"{complete_days}/7 days",
            delta="Complete" if complete_days >= 5 else "Incomplete"
        )

    # Weekly target calculator
    with st.expander("Calculate Weekly Target"):
        # Input planned training
        zone2_sessions = st.number_input("Zone 2 sessions", 0, 7, 3)
        zone2_duration = st.number_input("Avg duration (min)", 20, 90, 45)
        strength_sessions = st.number_input("Strength sessions", 0, 6, 3)
        vo2_sessions = st.number_input("VO2max sessions", 0, 3, 1)

        goal = st.selectbox("Goal", ["Maintenance", "Cut (-300)", "Lean Bulk (+200)"])

        # Calculate and display
        target = calculate_weekly_target(...)

        st.markdown(f"""
        **Recommended Daily Target: {target['daily_target_kcal']:.0f} kcal**

        Breakdown:
        - BMR: {target['breakdown']['bmr']:.0f} kcal
        - NEAT: {target['breakdown']['neat']:.0f} kcal
        - Exercise: {target['breakdown']['exercise_daily_avg']:.0f} kcal/day avg
        - Goal adjustment: {target['breakdown']['goal_adjustment']:+.0f} kcal
        """)
```

### New Query Functions

Add to `utils/queries.py`:

```python
@st.cache_data(ttl=3600)
def query_nutrition_summary(start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """Query daily nutrition data with completeness flags."""
    conn = get_connection()

    query = f"""
    WITH daily AS (
        SELECT
            date_utc as date,
            diet_calories_kcal as calories,
            protein_g,
            carbs_g,
            total_fat_g,
            weight_lb
        FROM read_parquet('{_parquet_path("daily_summary")}')
        WHERE date_utc BETWEEN '{start_date.date()}' AND '{end_date.date()}'
    ),
    rolling AS (
        SELECT
            *,
            AVG(calories) OVER (ORDER BY date ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING) as cal_30d_avg
        FROM daily
    )
    SELECT
        *,
        CASE
            WHEN calories IS NULL THEN FALSE
            WHEN calories < 1000 OR calories > 5000 THEN FALSE
            WHEN protein_g IS NOT NULL AND protein_g < 80 THEN FALSE
            WHEN cal_30d_avg IS NOT NULL AND calories < cal_30d_avg * 0.6 THEN FALSE
            ELSE TRUE
        END as is_complete
    FROM rolling
    ORDER BY date
    """
    return conn.execute(query).df()


@st.cache_data(ttl=3600)
def query_exercise_calories(start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """Calculate exercise calories from actual power data."""
    conn = get_connection()

    query = f"""
    WITH cardio AS (
        SELECT
            DATE_TRUNC('day', workout_start_utc)::DATE as date,
            SUM(watts * (time_cumulative_s / 60) * 0.065) as cardio_kcal
        FROM read_parquet('{_parquet_path("cardio_strokes")}')
        WHERE workout_start_utc BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY 1
    ),
    strength AS (
        SELECT
            DATE_TRUNC('day', workout_start_utc)::DATE as date,
            COUNT(DISTINCT workout_id) * 200 as strength_kcal  -- ~200 kcal per session
        FROM read_parquet('{_parquet_path("resistance_sets")}')
        WHERE workout_start_utc BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY 1
    )
    SELECT
        COALESCE(c.date, s.date) as date,
        COALESCE(c.cardio_kcal, 0) as cardio_kcal,
        COALESCE(s.strength_kcal, 0) as strength_kcal,
        COALESCE(c.cardio_kcal, 0) + COALESCE(s.strength_kcal, 0) as total_exercise_kcal
    FROM cardio c
    FULL OUTER JOIN strength s ON c.date = s.date
    ORDER BY date
    """
    return conn.execute(query).df()
```

---

## Implementation Steps

1. ~~**Fix Apple Health units issue**~~ ✅ DONE
   - Fixed in `hae_csv_utils.py` - was using `max()` instead of `sum()` for minute aggregation
   - Also fixed data accumulation with upsert + rebuild from minutes

2. ~~**Add query functions to `utils/queries.py`**~~ ✅ DONE
   - `query_nutrition_summary()` - with completeness flags
   - `query_exercise_calories()` - from power data
   - `query_implied_tdee()` - from weight + intake
   - `query_apple_health_energy()` - TDEE from Apple Health
   - `get_nutrition_score_data()` - for dashboard display

3. ~~**Create `utils/energy_balance.py`**~~ ✅ DONE
   - `WeeklyEnergyBalance` class
   - `calculate_weekly_target()` function
   - `quick_estimate()` for pre-calculated TDEE levels
   - Incomplete day detection heuristics (`detect_incomplete_days()`)
   - Helper functions for formatting and calculations

4. ~~**Add dashboard section to `hdp_dashboard.py`**~~ ✅ DONE
   - `render_nutrition_section()`
   - Weekly summary metrics (intake, protein, logging streak)
   - Calorie & protein trend chart
   - Apple Health TDEE display
   - Interactive target calculator with session inputs
   - Trend visualization

5. **Enhance `analyze_maintenance.py`** (optional)
   - Add weekly aggregation
   - Export targets to dashboard-consumable format

---

## Your Specific Targets

Based on your data analysis:

| Week Type | Est. TDEE | Recommended Target |
|-----------|-----------|-------------------|
| **Recovery** (light cardio only) | ~2,050 | 2,000-2,100 kcal |
| **Moderate** (3x zone2 + 2x strength) | ~2,350 | 2,300-2,400 kcal |
| **Aggressive** (3x zone2 + 2x row + 1x VO2 + 3x strength) | ~2,550 | 2,500-2,600 kcal |

**Protein target:** 150-160g daily (regardless of training load)

**Current 2,500 target:**
- Appropriate for aggressive training weeks
- ~400-500 surplus on recovery weeks (will gain ~0.5 lb/week)
- Adjust down to ~2,000-2,100 on recovery/deload weeks

---

## Next Steps

Would you like me to:
1. Implement the query functions first?
2. Build the full dashboard section?
3. Fix the Apple Health energy data units?
4. Start with just the weekly target calculator?
