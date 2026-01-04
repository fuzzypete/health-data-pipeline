# HDP Dashboard Addendum: Custom Scores & Advanced Features

**Extends:** `HDP_Dashboard_Requirements.md`  
**Author:** Claude (Opus 4.5) with Peter  
**Date:** January 3, 2026 (Updated)  
**Purpose:** Specification for custom scores, body composition, vitals, and advanced dashboard features

---

## Overview & Relationship to Main Spec

This addendum extends the main HDP Dashboard Requirements document with:

1. **Peter's Recovery Score (PRS)** - Custom recovery metric incorporating Oura + HDP training data
2. **Peter's Cardio Score (PCS)** - Multi-dimensional cardiovascular health metric
3. **Peter's Vitals Score (PVS)** - NEW: Composite vital signs health indicator
4. **Body Composition Panel** - NEW: Weight, body fat %, lean mass tracking
5. **Blood Pressure Panel** - NEW: BP monitoring with trend analysis
6. **Glucose/CGM Panel** - NEW: Blood glucose trends and time-in-range
7. **VO2max Tracking** - NEW: Standalone KPI (pending validation analysis)
8. **Revised KPI Layout** - Expanded to 16-card layout across 4 rows
9. **Compound Visibility Controls** - Demo mode and protocol aliasing
10. **Decision Gates Panel** - Cycle clearance criteria tracking

**For Claude Code:** Read the main spec first for overall architecture, then apply these modifications/additions.

---

## Revised KPI Card Layout

**REPLACES:** Main spec "Hero KPI Cards" section (lines 251-309)

### New Layout: 16 KPIs in 4 Rows

Expanded from 12 to 16 KPIs to incorporate body composition, vitals, and VO2max:

```
┌─────────────────────────────────────────────────────────────────────┐
│ ROW 1: RECOVERY & READINESS                                         │
│ [Recovery Score] [Sleep Quality] [HRV vs Baseline] [Training Load] │
├─────────────────────────────────────────────────────────────────────┤
│ ROW 2: CARDIOVASCULAR                                               │
│ [Cardio Score] [HR Response] [Max HR] [VO2max]                     │
├─────────────────────────────────────────────────────────────────────┤
│ ROW 3: BODY COMPOSITION & VITALS                                    │
│ [Vitals Score] [Weight] [Body Fat %] [Blood Pressure]              │
├─────────────────────────────────────────────────────────────────────┤
│ ROW 4: BIOMARKERS (Decision Gates)                                  │
│ [Ferritin] [HDL] [Hematocrit] [Glucose (CGM)]                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Mobile Layout

On mobile, display as 2x2 grids per row, or single column with most important KPIs first:
1. Recovery Score
2. Cardio Score  
3. Vitals Score
4. Ferritin
5. HR Response Time
6. Weight
7. Blood Pressure
8. (remaining KPIs in expandable section)

### KPI Card Behavior

Each KPI card should support:
- **Tap to expand:** Shows sparkline + component breakdown (for composite scores)
- **Trend indicator:** Arrow + percentage vs 7 days ago
- **Status color:** Green/yellow/orange/red based on thresholds
- **Target line:** Where applicable (e.g., Ferritin target >60)

### Alternative Layouts

**Compact (12 cards):** Combine Vitals Score components into single expandable card
**Extended (20 cards):** Add eGFR, ALT, Zone 2 Power, Lean Mass as separate KPIs

---

## Peter's Recovery Score (PRS)

### Purpose

Answers: **"How recovered am I? Can I train hard today?"**

Builds on Oura's Readiness concept but incorporates HDP-unique training load data and is tuned to Peter's physiology.

### Score Range & Interpretation

| Score | Status | Color | Recommendation |
|-------|--------|-------|----------------|
| 85-100 | Optimal | 🟢 Green | Push hard, good day for intervals or PR attempts |
| 70-84 | Moderate | 🟡 Yellow | Normal training, listen to body |
| 50-69 | Compromised | 🟠 Orange | Reduce volume/intensity, prioritize Zone 2 |
| <50 | Recovery Needed | 🔴 Red | Rest day or very light movement only |

### Component Structure

#### Tier 1: Sleep & Rest (40% of total)

| Component | Weight | Source | Calculation |
|-----------|--------|--------|-------------|
| Sleep Duration | 15% | Oura `total_sleep_duration` | `min(100, (hours / 7.5) * 100)` |
| Sleep Efficiency | 10% | Oura `sleep_efficiency` | Direct value (already 0-100) |
| Sleep Debt (7d) | 15% | Oura (calculated) | `max(0, 100 - (abs(debt_hours) * 20))` |

**Sleep Debt Calculation:**
```python
def calculate_sleep_debt(oura_data, days=7):
    """
    Rolling sleep debt: cumulative difference from 7.5hr target
    Negative = deficit, Positive = surplus (capped at 0)
    """
    target_hours = 7.5
    total_debt = 0
    for day in oura_data[-days:]:
        daily_diff = day['total_sleep_duration'] - target_hours
        total_debt += daily_diff
    # Cap surplus at 0 (can't bank unlimited sleep)
    return min(0, total_debt)
```

#### Tier 2: Autonomic State (30% of total)

| Component | Weight | Source | Calculation |
|-----------|--------|--------|-------------|
| HRV vs Baseline | 20% | Oura `hrv_avg` | See below |
| Resting HR vs Baseline | 10% | Oura `resting_heart_rate` | See below |

**HRV Score Calculation:**
```python
def calculate_hrv_score(current_hrv, baseline_hrv):
    """
    Score based on % of 90-day baseline
    100% of baseline = 85 points (not 100, to allow upside)
    >120% of baseline = 100 points (cap)
    <60% of baseline = 0 points
    """
    ratio = current_hrv / baseline_hrv
    if ratio >= 1.2:
        return 100
    elif ratio <= 0.6:
        return 0
    else:
        # Linear interpolation: 0.6 -> 0, 1.2 -> 100
        return (ratio - 0.6) / 0.6 * 100
```

**Resting HR Score Calculation:**
```python
def calculate_rhr_score(current_rhr, baseline_rhr):
    """
    Lower is better (inverted scale)
    At baseline = 85 points
    10+ bpm above baseline = 0 points
    5+ bpm below baseline = 100 points
    """
    diff = current_rhr - baseline_rhr
    if diff <= -5:
        return 100
    elif diff >= 10:
        return 0
    else:
        # Linear: -5 -> 100, +10 -> 0
        return 100 - ((diff + 5) / 15 * 100)
```

#### Tier 3: Training Load (30% of total)

| Component | Weight | Source | Calculation |
|-----------|--------|--------|-------------|
| Acute:Chronic Ratio | 15% | HDP (Concept2 + JEFIT) | See below |
| Days Since Rest | 10% | HDP | See below |
| Yesterday's Intensity | 5% | HDP | See below |

**Acute:Chronic Workload Ratio (ACWR):**
```python
def calculate_acwr_score(acute_load, chronic_load):
    """
    ACWR = 7-day load / 28-day average load
    Sweet spot: 0.8 - 1.3 (training optimally)
    Too low (<0.5): Detraining
    Too high (>1.5): Injury/overtraining risk
    
    Scoring:
    0.8-1.3 = 100 points
    0.5-0.8 or 1.3-1.5 = linear dropoff
    <0.5 or >1.5 = 50 points (not zero, just suboptimal)
    """
    if chronic_load == 0:
        return 50  # No baseline, neutral score
    
    acwr = acute_load / chronic_load
    
    if 0.8 <= acwr <= 1.3:
        return 100
    elif 0.5 <= acwr < 0.8:
        return 50 + (acwr - 0.5) / 0.3 * 50
    elif 1.3 < acwr <= 1.5:
        return 100 - (acwr - 1.3) / 0.2 * 50
    else:
        return 50
```

**Days Since Rest Score:**
```python
def calculate_rest_days_score(days_since_rest):
    """
    1-2 days since rest = 100 (fresh)
    3 days = 80
    4 days = 50
    5+ days = 20
    """
    scores = {0: 100, 1: 100, 2: 100, 3: 80, 4: 50}
    return scores.get(days_since_rest, 20)
```

**Yesterday's Intensity Score:**
```python
def calculate_yesterday_intensity_score(workout_type):
    """
    What you did yesterday affects today's recovery
    """
    scores = {
        'rest': 100,
        'zone2': 90,
        'strength': 75,
        'intervals': 50,
        'race': 30
    }
    return scores.get(workout_type, 75)
```

### Baseline Calculations

**90-Day Rolling Baselines (recalculate daily):**

```sql
-- HRV Baseline
SELECT AVG(hrv_avg) as hrv_baseline
FROM read_parquet('Data/Parquet/oura_daily_summaries/**/*.parquet')
WHERE summary_date BETWEEN CURRENT_DATE - INTERVAL '90 days' AND CURRENT_DATE - INTERVAL '1 day'
  AND hrv_avg IS NOT NULL;

-- Resting HR Baseline
SELECT AVG(resting_heart_rate) as rhr_baseline
FROM read_parquet('Data/Parquet/oura_daily_summaries/**/*.parquet')
WHERE summary_date BETWEEN CURRENT_DATE - INTERVAL '90 days' AND CURRENT_DATE - INTERVAL '1 day'
  AND resting_heart_rate IS NOT NULL;
```

**Training Load Calculations:**

```sql
-- Acute Load (7 days)
WITH daily_load AS (
    SELECT 
        workout_date,
        SUM(total_seconds / 60.0) as minutes
    FROM read_parquet('Data/Parquet/concept2_workouts/**/*.parquet')
    WHERE workout_date BETWEEN CURRENT_DATE - INTERVAL '7 days' AND CURRENT_DATE - INTERVAL '1 day'
    GROUP BY workout_date
    
    UNION ALL
    
    SELECT 
        workout_date,
        COUNT(DISTINCT set_id) * 2 as minutes  -- Estimate: 2 min per set
    FROM read_parquet('Data/Parquet/jefit_logs/**/*.parquet')
    WHERE workout_date BETWEEN CURRENT_DATE - INTERVAL '7 days' AND CURRENT_DATE - INTERVAL '1 day'
    GROUP BY workout_date
)
SELECT COALESCE(SUM(minutes), 0) as acute_load FROM daily_load;

-- Chronic Load (28 days, then divide by 4 for weekly average)
-- Same query with 28-day window, then: chronic_load = total / 4
```

### Final Score Aggregation

```python
def calculate_recovery_score(components: dict) -> dict:
    """
    Aggregate component scores into final PRS
    
    components = {
        'sleep_duration': 96,
        'sleep_efficiency': 88,
        'sleep_debt': 64,
        'hrv_vs_baseline': 62,
        'resting_hr': 80,
        'acwr': 95,
        'days_since_rest': 100,
        'yesterday_intensity': 75
    }
    """
    
    # Tier scores (weighted average within tier)
    sleep_tier = (
        components['sleep_duration'] * (15/40) +
        components['sleep_efficiency'] * (10/40) +
        components['sleep_debt'] * (15/40)
    )
    
    autonomic_tier = (
        components['hrv_vs_baseline'] * (20/30) +
        components['resting_hr'] * (10/30)
    )
    
    training_tier = (
        components['acwr'] * (15/30) +
        components['days_since_rest'] * (10/30) +
        components['yesterday_intensity'] * (5/30)
    )
    
    # Final score (tier weights)
    total = (
        sleep_tier * 0.40 +
        autonomic_tier * 0.30 +
        training_tier * 0.30
    )
    
    return {
        'total': round(total),
        'status': get_status(total),
        'tiers': {
            'sleep_rest': {
                'score': round(sleep_tier),
                'weight': '40%',
                'components': {
                    'sleep_duration': components['sleep_duration'],
                    'sleep_efficiency': components['sleep_efficiency'],
                    'sleep_debt': components['sleep_debt']
                }
            },
            'autonomic': {
                'score': round(autonomic_tier),
                'weight': '30%',
                'components': {
                    'hrv_vs_baseline': components['hrv_vs_baseline'],
                    'resting_hr': components['resting_hr']
                }
            },
            'training_load': {
                'score': round(training_tier),
                'weight': '30%',
                'components': {
                    'acwr': components['acwr'],
                    'days_since_rest': components['days_since_rest'],
                    'yesterday_intensity': components['yesterday_intensity']
                }
            }
        }
    }

def get_status(score):
    if score >= 85:
        return '🟢 Optimal'
    elif score >= 70:
        return '🟡 Moderate'
    elif score >= 50:
        return '🟠 Compromised'
    else:
        return '🔴 Recovery Needed'
```

### UI Specification: Oura-Style Drill-Down

```
┌─────────────────────────────────────────────────────────────────┐
│  😴 Recovery Score                                          78  │
│  ████████████████████████████████░░░░░░░░░░  🟡 Moderate        │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Sleep & Rest (40%)                                       82  │
│    ├─ Sleep Duration        7.2 hr    ████████████████░░░  96  │
│    ├─ Sleep Efficiency      88%       █████████████████░░  88  │
│    └─ Sleep Debt (7d)       -1.8 hr   ████████████░░░░░░░  64  │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Autonomic State (30%)                                    68  │
│    ├─ HRV vs Baseline       -12%      ████████████░░░░░░░  62  │
│    └─ Resting HR            +3 bpm    ████████████████░░░  80  │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Training Load (30%)                                      82  │
│    ├─ Acute:Chronic         1.1       ███████████████████  95  │
│    ├─ Days Since Rest       2 days    ████████████████████ 100 │
│    └─ Yesterday             Strength  ███████████████░░░░░  75  │
└─────────────────────────────────────────────────────────────────┘
```

**Streamlit Implementation:**

```python
def render_recovery_score(score_data: dict):
    """Render PRS with Oura-style expandable tiers"""
    
    # Header
    st.subheader("😴 Recovery Score")
    
    col1, col2 = st.columns([4, 1])
    with col1:
        st.progress(score_data['total'] / 100)
    with col2:
        st.metric(label="", value=score_data['total'], label_visibility="collapsed")
    
    st.caption(score_data['status'])
    
    # Expandable tiers
    for tier_name, tier_data in score_data['tiers'].items():
        display_name = tier_name.replace('_', ' ').title()
        with st.expander(f"{display_name} ({tier_data['weight']}) — {tier_data['score']}"):
            for comp_name, comp_score in tier_data['components'].items():
                col1, col2, col3 = st.columns([2, 2, 1])
                with col1:
                    st.write(comp_name.replace('_', ' ').title())
                with col2:
                    st.progress(comp_score / 100)
                with col3:
                    st.write(f"{comp_score}")
```

---

## Peter's Cardio Score (PCS)

### Purpose

Answers: **"How is my cardiovascular system functioning across all dimensions?"**

Captures multiple aspects of CV health that a single metric (VO2max, max HR) cannot. Particularly relevant during iron recovery when different aspects recover at different rates.

### Score Range & Interpretation

| Score | Status | Color | Implication |
|-------|--------|-------|-------------|
| 85-100 | Excellent | 🟢 Green | Cardiovascular system fully functional |
| 70-84 | Good | 🟡 Yellow | Minor limitations, can train normally |
| 50-69 | Compromised | 🟠 Orange | Noticeable limitations, modify intensity |
| <50 | Impaired | 🔴 Red | Significant dysfunction, prioritize recovery |

### Component Structure

#### Tier 1: Capacity & Ceiling (35% of total)

| Component | Weight | Source | Baseline Type |
|-----------|--------|--------|---------------|
| Max HR vs Peak | 20% | Concept2 | Fixed: 161 bpm (May 2024 peak) |
| Zone 2 Power Ceiling | 15% | Concept2 | Fixed: 147W (May 2024 peak) |

**Max HR Score:**
```python
def calculate_max_hr_score(recent_max_hr, peak_max_hr=161):
    """
    7-day max HR as percentage of known peak
    Capped at 100 (can't exceed peak by definition)
    """
    return min(100, (recent_max_hr / peak_max_hr) * 100)
```

**Zone 2 Power Score:**
```python
def calculate_zone2_power_score(current_z2_watts, peak_z2_watts=147):
    """
    Current sustainable Zone 2 power vs peak
    """
    return min(100, (current_z2_watts / peak_z2_watts) * 100)
```

#### Tier 2: Responsiveness & Dynamics (35% of total)

| Component | Weight | Source | Target |
|-----------|--------|--------|--------|
| HR Response Time | 20% | HAE + Concept2 | <4 min to reach 140 bpm |
| HR Recovery (1-min) | 15% | HAE + Concept2 | >30 bpm drop in 1 min |

**HR Response Time Score:**
```python
def calculate_hr_response_score(minutes_to_140):
    """
    Time to reach 140 bpm from workout start
    
    <4 min = 100 (target met)
    4-8 min = linear 100 -> 50
    8-12 min = linear 50 -> 0
    >12 min = 0
    """
    if minutes_to_140 <= 4:
        return 100
    elif minutes_to_140 <= 8:
        return 100 - ((minutes_to_140 - 4) / 4 * 50)
    elif minutes_to_140 <= 12:
        return 50 - ((minutes_to_140 - 8) / 4 * 50)
    else:
        return 0
```

**HR Recovery Score:**
```python
def calculate_hr_recovery_score(hr_drop_1min):
    """
    HR drop in first 60 seconds after peak effort
    
    >30 bpm = 100 (excellent parasympathetic response)
    20-30 bpm = linear 50-100
    <15 bpm = 0 (poor recovery, potential issue)
    """
    if hr_drop_1min >= 30:
        return 100
    elif hr_drop_1min >= 20:
        return 50 + ((hr_drop_1min - 20) / 10 * 50)
    elif hr_drop_1min >= 15:
        return (hr_drop_1min - 15) / 5 * 50
    else:
        return 0
```

#### Tier 3: Efficiency & Baseline (30% of total)

| Component | Weight | Source | Baseline Type |
|-----------|--------|--------|---------------|
| Aerobic Efficiency | 15% | Concept2 | Rolling: personal best W/bpm ratio |
| Resting HR | 10% | Oura | Rolling: 90-day average |
| HRV Health | 5% | Oura | Rolling: 90-day average |

**Aerobic Efficiency Score:**
```python
def calculate_aerobic_efficiency_score(current_efficiency, best_efficiency):
    """
    Watts per heartbeat at steady-state Zone 2
    Higher = more efficient (more work per heartbeat)
    
    current_efficiency = avg_watts / avg_hr during steady Z2
    best_efficiency = historical best (calculate from past data)
    """
    return min(100, (current_efficiency / best_efficiency) * 100)
```

**Resting HR Score (for Cardio context):**
```python
def calculate_cardio_rhr_score(resting_hr):
    """
    Absolute scale for cardiovascular health
    Lower resting HR = stronger cardiovascular system
    
    <50 bpm = 100 (athlete level)
    50-55 = 90
    55-60 = 80
    60-65 = 70
    65-70 = 60
    >70 = 50
    """
    if resting_hr < 50:
        return 100
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
```

### Data Retrieval Queries

**HR Response Time Calculation:**

```sql
-- Get workout start time and find when HR first hits 140
WITH workout_hr AS (
    SELECT 
        w.workout_date,
        w.workout_id,
        w.start_time,
        h.timestamp,
        h.heart_rate,
        EXTRACT(EPOCH FROM (h.timestamp - w.start_time)) / 60.0 as minutes_from_start
    FROM read_parquet('Data/Parquet/concept2_workouts/**/*.parquet') w
    JOIN read_parquet('Data/Parquet/hae_heart_rate_minute/**/*.parquet') h
        ON DATE(h.timestamp) = w.workout_date
        AND h.timestamp >= w.start_time
        AND h.timestamp <= w.start_time + INTERVAL '20 minutes'
    WHERE w.workout_date = ?
    ORDER BY h.timestamp
)
SELECT 
    MIN(minutes_from_start) as minutes_to_140
FROM workout_hr
WHERE heart_rate >= 140;
```

**HR Recovery Calculation:**

```sql
-- Get peak HR in last 2 min of workout, then HR at 60s post
WITH workout_end AS (
    SELECT 
        workout_id,
        end_time,
        (SELECT MAX(heart_rate) 
         FROM hae_heart_rate_minute 
         WHERE timestamp BETWEEN end_time - INTERVAL '2 minutes' AND end_time
        ) as peak_hr,
        (SELECT heart_rate 
         FROM hae_heart_rate_minute 
         WHERE timestamp = end_time + INTERVAL '1 minute'
        ) as hr_at_60s
    FROM concept2_workouts
    WHERE workout_date = ?
)
SELECT peak_hr - hr_at_60s as hr_recovery_1min FROM workout_end;
```

**Aerobic Efficiency Calculation:**

```sql
-- Calculate W/bpm during steady-state portion of Zone 2 workouts
WITH steady_state AS (
    SELECT 
        s.workout_id,
        AVG(s.split_watts) as avg_watts,
        AVG(s.split_heart_rate) as avg_hr
    FROM read_parquet('Data/Parquet/concept2_splits/**/*.parquet') s
    JOIN read_parquet('Data/Parquet/concept2_workouts/**/*.parquet') w
        ON s.workout_id = w.workout_id
    WHERE w.workout_date BETWEEN ? AND ?
        AND w.workout_type = 'BikeErg'
        AND s.split_number > 2  -- Skip warmup
        AND s.split_number < (SELECT MAX(split_number) - 1 FROM concept2_splits WHERE workout_id = s.workout_id)  -- Skip cooldown
    GROUP BY s.workout_id
)
SELECT 
    avg_watts / avg_hr as efficiency
FROM steady_state
ORDER BY workout_id DESC
LIMIT 1;
```

### Fixed vs Rolling Baselines

| Component | Baseline Type | Value | Rationale |
|-----------|---------------|-------|-----------|
| Max HR | Fixed | 161 bpm | Known peak from May 2024 |
| Zone 2 Power | Fixed | 147W | Known peak from May 2024 |
| HR Response Target | Fixed | 4 min | General athletic standard |
| HR Recovery Target | Fixed | 30 bpm | General athletic standard |
| Aerobic Efficiency | Rolling | Personal best | Adapts as fitness improves |
| Resting HR | Absolute scale | N/A | Standard cardiovascular health ranges |
| HRV | Rolling | 90-day avg | Personal variation too high for fixed |

### Final Score Aggregation

```python
def calculate_cardio_score(components: dict) -> dict:
    """
    Aggregate component scores into final PCS
    """
    
    # Tier scores
    capacity_tier = (
        components['max_hr'] * (20/35) +
        components['zone2_power'] * (15/35)
    )
    
    responsiveness_tier = (
        components['hr_response_time'] * (20/35) +
        components['hr_recovery'] * (15/35)
    )
    
    efficiency_tier = (
        components['aerobic_efficiency'] * (15/30) +
        components['resting_hr'] * (10/30) +
        components['hrv_health'] * (5/30)
    )
    
    # Final score
    total = (
        capacity_tier * 0.35 +
        responsiveness_tier * 0.35 +
        efficiency_tier * 0.30
    )
    
    return {
        'total': round(total),
        'status': get_cardio_status(total),
        'tiers': {
            'capacity_ceiling': {
                'score': round(capacity_tier),
                'weight': '35%',
                'components': {
                    'max_hr': components['max_hr'],
                    'zone2_power': components['zone2_power']
                }
            },
            'responsiveness': {
                'score': round(responsiveness_tier),
                'weight': '35%',
                'components': {
                    'hr_response_time': components['hr_response_time'],
                    'hr_recovery': components['hr_recovery']
                }
            },
            'efficiency_baseline': {
                'score': round(efficiency_tier),
                'weight': '30%',
                'components': {
                    'aerobic_efficiency': components['aerobic_efficiency'],
                    'resting_hr': components['resting_hr'],
                    'hrv_health': components['hrv_health']
                }
            }
        }
    }
```

### UI Specification

```
┌─────────────────────────────────────────────────────────────────┐
│  ❤️ Cardio Score                                            64  │
│  ████████████████████░░░░░░░░░░░░░░░░░░░░  🟠 Compromised       │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Capacity & Ceiling (35%)                                 82  │
│    ├─ Max HR (7d)           153/161    ███████████████████  95  │
│    └─ Zone 2 Power          142/147W   █████████████░░░░░░  68  │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Responsiveness (35%)                                     45  │  ← LIMITER
│    ├─ HR Response Time      9.2 min    ███████░░░░░░░░░░░░  38  │
│    └─ HR Recovery (1m)      22 bpm     ███████████░░░░░░░░  55  │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Efficiency & Baseline (30%)                              72  │
│    ├─ Aerobic Efficiency    1.05 W/bpm ███████████████░░░░  75  │
│    ├─ Resting HR            58 bpm     ████████████████░░░  80  │
│    └─ HRV Health            -8%        ████████████░░░░░░░  62  │
└─────────────────────────────────────────────────────────────────┘
```

**Key insight visible:** The Responsiveness tier (45) is dragging down the overall score, specifically HR Response Time (38). This matches Peter's experience—max HR recovered but responsiveness hasn't.

---

## Compound Visibility Controls

### Purpose

Allow Peter to demo the dashboard without exposing AAS usage, while maintaining full tracking capability for personal use.

### Implementation

#### Configuration

```python
# config/visibility.py

COMPOUND_VISIBILITY = {
    # Always visible (legal, medically supervised)
    "TRT": "always",
    "HGH": "always", 
    "HCG": "always",
    "Supplements": "always",
    "Peptides": "always",  # BPC-157, TB-500 - grey area but common
    
    # Only visible when authenticated/not in demo mode
    "AAS": "authenticated",
    "Controlled": "authenticated"
}

# What to show for hidden compounds in demo mode
DEMO_MODE_ALIAS = "Performance Protocol"

# Protocol types shown in demo mode
DEMO_VISIBLE_TYPES = ["TRT", "HGH", "HCG", "Supplements", "Peptides"]
```

#### Demo Mode Toggle

```python
# In sidebar
demo_mode = st.sidebar.toggle("Demo Mode", value=False, 
    help="Hide sensitive protocol details for demos")

# Or via URL parameter
demo_mode = st.query_params.get("demo", "false") == "true"
```

#### Protocol Query Modification

```python
def get_protocols(start_date, end_date, demo_mode=False):
    """Query protocols with optional filtering for demo mode"""
    
    base_query = """
        SELECT 
            protocol_name,
            protocol_type,
            start_date,
            end_date,
            dosage,
            frequency
        FROM read_parquet('Data/Parquet/protocol_history/**/*.parquet')
        WHERE start_date <= ? AND (end_date >= ? OR end_date IS NULL)
    """
    
    if demo_mode:
        # Filter to only demo-safe protocols
        base_query += f"""
            AND protocol_type IN ({','.join(f"'{t}'" for t in DEMO_VISIBLE_TYPES)})
        """
    
    return conn.execute(base_query, [end_date, start_date]).df()
```

#### Alternative: Protocol Aliasing

Instead of hiding completely, alias sensitive protocols:

```python
def alias_protocol(protocol_name, protocol_type, demo_mode=False):
    """Return display name, potentially aliased"""
    if not demo_mode:
        return protocol_name
    
    if protocol_type == "AAS":
        # "Nandrolone 200mg/wk" -> "Protocol N-200"
        first_letter = protocol_name[0]
        dose = extract_dose(protocol_name)  # regex to find "200mg"
        return f"Protocol {first_letter}-{dose}"
    
    return protocol_name
```

### Demo Mode Behavior Summary

| Feature | Full Mode | Demo Mode |
|---------|-----------|-----------|
| Protocol Timeline | All protocols | TRT, HGH, Supplements only |
| Protocol Names | Full names | Aliased (optional) |
| Lab Values | All | All (not incriminating) |
| Cardio Metrics | All | All |
| Recovery Metrics | All | All |
| Correlation Explorer | All protocols selectable | Limited to demo-safe |

---

## Decision Gates Panel

### Purpose

Track progress toward cycle clearance criteria. Shows current status of each biomarker gate for upcoming compound phases.

### February 2026 Nandrolone Criteria

| Gate | Target | Current | Status |
|------|--------|---------|--------|
| Ferritin (LabCorp) | >60 ng/mL | 57 | 🟡 Close |
| HDL | >55 mg/dL | 59 | ✅ Met |
| ALT | <65 U/L | 78 | ❌ Not met |
| Hematocrit | <52% | 50.1% | ✅ Met |
| eGFR | Stable | 70 | 🟡 Monitor |

### Implementation

```python
def render_decision_gates():
    """Render cycle clearance criteria panel"""
    
    st.subheader("🚦 Cycle Clearance: Nandrolone (Feb 2026)")
    
    # Define gates
    gates = [
        {
            'name': 'Ferritin',
            'target': '>60 ng/mL',
            'target_value': 60,
            'comparison': 'gt',
            'query': "SELECT value FROM labs WHERE biomarker='Ferritin' ORDER BY date DESC LIMIT 1",
            'note': 'LabCorp only'
        },
        {
            'name': 'HDL',
            'target': '>55 mg/dL',
            'target_value': 55,
            'comparison': 'gt',
            'query': "SELECT value FROM labs WHERE biomarker='HDL' ORDER BY date DESC LIMIT 1"
        },
        {
            'name': 'ALT',
            'target': '<65 U/L',
            'target_value': 65,
            'comparison': 'lt',
            'query': "SELECT value FROM labs WHERE biomarker='ALT' ORDER BY date DESC LIMIT 1"
        },
        {
            'name': 'Hematocrit',
            'target': '<52%',
            'target_value': 52,
            'comparison': 'lt',
            'query': "SELECT value FROM labs WHERE biomarker='Hematocrit' ORDER BY date DESC LIMIT 1"
        },
        {
            'name': 'eGFR',
            'target': 'Stable (>60)',
            'target_value': 60,
            'comparison': 'gt',
            'query': "SELECT value FROM labs WHERE biomarker='eGFR' ORDER BY date DESC LIMIT 1"
        }
    ]
    
    # Calculate status
    met_count = 0
    for gate in gates:
        current = query_latest_value(gate['query'])
        
        if gate['comparison'] == 'gt':
            met = current > gate['target_value']
            close = current > gate['target_value'] * 0.9
        else:
            met = current < gate['target_value']
            close = current < gate['target_value'] * 1.1
        
        if met:
            status = '✅'
            met_count += 1
        elif close:
            status = '🟡'
        else:
            status = '❌'
        
        gate['current'] = current
        gate['status'] = status
    
    # Summary
    st.metric("Gates Met", f"{met_count}/{len(gates)}")
    
    # Detail table
    for gate in gates:
        col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
        with col1:
            st.write(gate['name'])
        with col2:
            st.write(gate['target'])
        with col3:
            st.write(f"{gate['current']}")
        with col4:
            st.write(gate['status'])
```

### Placement

Add to NOW section (Section 6 in main spec) as a collapsible panel:

```python
with st.expander("🚦 Cycle Decision Gates", expanded=False):
    render_decision_gates()
```

---

## Peter's Vitals Score (PVS)

### Purpose

Answers: **"How are my vital signs trending? Any red flags?"**

Composite score combining blood pressure, resting heart rate, HRV, SpO2, and respiratory rate into a single health indicator.

### Score Range & Interpretation

| Score | Status | Color | Implication |
|-------|--------|-------|-------------|
| 85-100 | Excellent | 🟢 Green | All vitals in optimal range |
| 70-84 | Good | 🟡 Yellow | Minor deviations, monitor |
| 50-69 | Attention | 🟠 Orange | One or more vitals suboptimal |
| <50 | Concern | 🔴 Red | Multiple vitals out of range, investigate |

### Component Structure

| Component | Weight | Source | Optimal Range | Scoring |
|-----------|--------|--------|---------------|---------|
| Blood Pressure | 30% | HAE minute_facts | <120/80 mmHg | See below |
| Resting HR | 25% | Oura | <60 bpm | Lower is better |
| HRV | 25% | Oura | >baseline | Higher is better |
| SpO2 | 10% | HAE minute_facts | >95% | Flag if drops |
| Respiratory Rate | 10% | HAE minute_facts | 12-20 breaths/min | Middle is best |

### Blood Pressure Score Calculation

```python
def calculate_bp_score(systolic: float, diastolic: float) -> int:
    """
    Score based on AHA blood pressure categories
    
    Categories:
    - Normal: <120 AND <80 = 100 points
    - Elevated: 120-129 AND <80 = 85 points
    - Stage 1 HTN: 130-139 OR 80-89 = 60 points
    - Stage 2 HTN: ≥140 OR ≥90 = 30 points
    - Crisis: >180 OR >120 = 0 points
    """
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
```

### Resting HR Score (for Vitals context)

```python
def calculate_vitals_rhr_score(resting_hr: int) -> int:
    """
    Absolute scale for cardiovascular health
    Based on adult male norms, adjusted for athletic population
    """
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
```

### SpO2 Score

```python
def calculate_spo2_score(spo2: float) -> int:
    """
    Oxygen saturation scoring
    Normal is 95-100%, anything below is concerning
    """
    if spo2 >= 98:
        return 100
    elif spo2 >= 95:
        return 90
    elif spo2 >= 92:
        return 50  # Mild hypoxemia
    elif spo2 >= 88:
        return 20  # Moderate hypoxemia
    else:
        return 0   # Severe - seek medical attention
```

### Respiratory Rate Score

```python
def calculate_resp_rate_score(breaths_per_min: float) -> int:
    """
    Normal adult respiratory rate is 12-20 breaths/min
    Athletes may be lower (8-12)
    """
    if 12 <= breaths_per_min <= 16:
        return 100  # Optimal
    elif 10 <= breaths_per_min < 12 or 16 < breaths_per_min <= 18:
        return 90   # Good
    elif 8 <= breaths_per_min < 10 or 18 < breaths_per_min <= 20:
        return 75   # Acceptable
    elif breaths_per_min < 8 or breaths_per_min > 24:
        return 30   # Concerning
    else:
        return 50   # Suboptimal
```

### Final Vitals Score Aggregation

```python
def calculate_vitals_score(components: dict) -> dict:
    """
    Aggregate component scores into final PVS
    """
    total = (
        components['bp_score'] * 0.30 +
        components['resting_hr_score'] * 0.25 +
        components['hrv_score'] * 0.25 +
        components['spo2_score'] * 0.10 +
        components['resp_rate_score'] * 0.10
    )
    
    return {
        'total': round(total),
        'status': get_vitals_status(total),
        'components': {
            'blood_pressure': {
                'score': components['bp_score'],
                'value': f"{components['systolic']}/{components['diastolic']} mmHg"
            },
            'resting_hr': {
                'score': components['resting_hr_score'],
                'value': f"{components['resting_hr']} bpm"
            },
            'hrv': {
                'score': components['hrv_score'],
                'value': f"{components['hrv']} ms"
            },
            'spo2': {
                'score': components['spo2_score'],
                'value': f"{components['spo2']}%"
            },
            'respiratory_rate': {
                'score': components['resp_rate_score'],
                'value': f"{components['resp_rate']} breaths/min"
            }
        }
    }
```

### Data Queries

```sql
-- Latest BP readings (7-day average)
SELECT 
    ROUND(AVG(blood_pressure_systolic_mmhg), 1) as avg_systolic,
    ROUND(AVG(blood_pressure_diastolic_mmhg), 1) as avg_diastolic,
    COUNT(*) as readings
FROM lake.minute_facts
WHERE timestamp_utc >= CURRENT_DATE - INTERVAL '7 days'
  AND blood_pressure_systolic_mmhg IS NOT NULL;

-- Latest SpO2 (7-day average)
SELECT 
    ROUND(AVG(blood_oxygen_saturation_pct), 1) as avg_spo2,
    MIN(blood_oxygen_saturation_pct) as min_spo2
FROM lake.minute_facts
WHERE timestamp_utc >= CURRENT_DATE - INTERVAL '7 days'
  AND blood_oxygen_saturation_pct IS NOT NULL;

-- Latest Respiratory Rate (7-day average)
SELECT 
    ROUND(AVG(respiratory_rate_count_min), 1) as avg_resp_rate
FROM lake.minute_facts
WHERE timestamp_utc >= CURRENT_DATE - INTERVAL '7 days'
  AND respiratory_rate_count_min IS NOT NULL;

-- Resting HR and HRV from Oura (most recent)
SELECT 
    resting_heart_rate_bpm,
    hrv_ms
FROM lake.oura_summary
ORDER BY day DESC
LIMIT 1;
```

### UI Specification

```
┌─────────────────────────────────────────────────────────────────┐
│  🩺 Vitals Score                                            82  │
│  ████████████████████████████████░░░░░░░░  🟡 Good             │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Blood Pressure (30%)                                     85  │
│    └─ 122/78 mmHg (7d avg)            ███████████████████░  85  │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Resting HR (25%)                                         85  │
│    └─ 54 bpm                          ███████████████████░  85  │
├─────────────────────────────────────────────────────────────────┤
│  ▼ HRV (25%)                                                72  │
│    └─ 42 ms (-8% vs baseline)         ██████████████░░░░░░  72  │
├─────────────────────────────────────────────────────────────────┤
│  ▼ SpO2 (10%)                                               95  │
│    └─ 97%                             ███████████████████░  95  │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Respiratory Rate (10%)                                   90  │
│    └─ 14 breaths/min                  ██████████████████░░  90  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Body Composition Panel

### Purpose

Track weight, body fat percentage, and lean body mass over time. Essential for monitoring the impact of training, nutrition, and compound protocols.

### Data Sources

| Metric | Source | Field | Unit |
|--------|--------|-------|------|
| Weight | HAE daily_summary | `weight_lb` | lbs |
| Body Fat % | HAE daily_summary | `body_fat_pct` | % |
| Lean Body Mass | HAE daily_summary | `lean_body_mass_lb` | lbs |
| BMI | HAE minute_facts | `body_mass_index_count` | kg/m² |

### Thresholds & Targets

| Metric | Current Target | Optimal Range | Notes |
|--------|---------------|---------------|-------|
| Weight | 180-190 lbs | Stable ±3 lbs/week | Rapid changes warrant investigation |
| Body Fat % | 15-18% | 12-20% | Athletic range for age 56 |
| Lean Body Mass | Maximize | >150 lbs | Track trend, not absolute |

### Data Queries

```sql
-- Latest body composition
SELECT 
    date_utc as date,
    weight_lb,
    body_fat_pct,
    lean_body_mass_lb,
    weight_lb * (1 - body_fat_pct/100.0) as calculated_lbm
FROM lake.daily_summary
WHERE weight_lb IS NOT NULL
ORDER BY date_utc DESC
LIMIT 1;

-- Body composition trend (90 days)
SELECT 
    date_utc as date,
    weight_lb,
    body_fat_pct,
    lean_body_mass_lb
FROM lake.daily_summary
WHERE weight_lb IS NOT NULL
  AND date_utc >= CURRENT_DATE - INTERVAL '90 days'
ORDER BY date_utc;

-- Weekly averages (reduces noise)
SELECT 
    DATE_TRUNC('week', date_utc) as week,
    ROUND(AVG(weight_lb), 1) as avg_weight,
    ROUND(AVG(body_fat_pct), 1) as avg_bf_pct,
    ROUND(AVG(lean_body_mass_lb), 1) as avg_lbm
FROM lake.daily_summary
WHERE weight_lb IS NOT NULL
  AND date_utc >= CURRENT_DATE - INTERVAL '90 days'
GROUP BY DATE_TRUNC('week', date_utc)
ORDER BY week;
```

### UI Specification

```
┌─────────────────────────────────────────────────────────────────┐
│  ⚖️ Body Composition                                            │
├─────────────────────────────────────────────────────────────────┤
│  Weight        185.2 lbs    ▼ 1.3 lbs (7d)     🟢 Stable       │
│  ────────────────────────────────────────────────               │
│  [Sparkline: 30-day weight trend]                               │
├─────────────────────────────────────────────────────────────────┤
│  Body Fat      17.8%        ▼ 0.4% (30d)       🟢 Athletic     │
│  ────────────────────────────────────────────────               │
│  [Sparkline: 30-day BF% trend]                                  │
├─────────────────────────────────────────────────────────────────┤
│  Lean Mass     152.3 lbs    ▲ 1.2 lbs (30d)    🟢 Improving    │
│  ────────────────────────────────────────────────               │
│  [Sparkline: 30-day LBM trend]                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Streamlit Implementation

```python
def render_body_composition_panel():
    """Render body composition panel with trends"""
    
    st.subheader("⚖️ Body Composition")
    
    # Get latest values
    latest = get_latest_body_comp()
    trends = get_body_comp_trends(days=90)
    
    # Weight
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        weight_delta = calculate_delta(trends['weight'], days=7)
        st.metric(
            "Weight", 
            f"{latest['weight_lb']:.1f} lbs",
            delta=f"{weight_delta:+.1f} lbs (7d)"
        )
    with col2:
        render_sparkline(trends['weight'])
    with col3:
        status = "🟢 Stable" if abs(weight_delta) < 2 else "🟡 Changing"
        st.write(status)
    
    # Body Fat %
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        bf_delta = calculate_delta(trends['body_fat_pct'], days=30)
        st.metric(
            "Body Fat",
            f"{latest['body_fat_pct']:.1f}%",
            delta=f"{bf_delta:+.1f}% (30d)",
            delta_color="inverse"  # Lower is better
        )
    with col2:
        render_sparkline(trends['body_fat_pct'])
    with col3:
        if latest['body_fat_pct'] < 15:
            status = "🟢 Lean"
        elif latest['body_fat_pct'] < 20:
            status = "🟢 Athletic"
        elif latest['body_fat_pct'] < 25:
            status = "🟡 Average"
        else:
            status = "🟠 Elevated"
        st.write(status)
    
    # Lean Body Mass
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        lbm_delta = calculate_delta(trends['lean_body_mass'], days=30)
        st.metric(
            "Lean Mass",
            f"{latest['lean_body_mass_lb']:.1f} lbs",
            delta=f"{lbm_delta:+.1f} lbs (30d)"
        )
    with col2:
        render_sparkline(trends['lean_body_mass'])
    with col3:
        status = "🟢 Building" if lbm_delta > 0.5 else "🟡 Maintaining" if lbm_delta > -0.5 else "🟠 Declining"
        st.write(status)
```

---

## Blood Pressure Panel

### Purpose

Track blood pressure trends for cardiovascular health monitoring. Important given compound use and general healthspan optimization.

### Data Sources

| Metric | Source | Field |
|--------|--------|-------|
| Systolic | HAE minute_facts | `blood_pressure_systolic_mmhg` |
| Diastolic | HAE minute_facts | `blood_pressure_diastolic_mmhg` |

### AHA Blood Pressure Categories

| Category | Systolic | Diastolic | Dashboard Color |
|----------|----------|-----------|-----------------|
| Normal | <120 | AND <80 | 🟢 Green |
| Elevated | 120-129 | AND <80 | 🟡 Yellow |
| Stage 1 HTN | 130-139 | OR 80-89 | 🟠 Orange |
| Stage 2 HTN | ≥140 | OR ≥90 | 🔴 Red |
| Crisis | >180 | OR >120 | 🚨 Alert |

### Data Queries

```sql
-- Daily BP readings
SELECT 
    DATE(timestamp_utc) as date,
    ROUND(AVG(blood_pressure_systolic_mmhg), 1) as systolic,
    ROUND(AVG(blood_pressure_diastolic_mmhg), 1) as diastolic,
    COUNT(*) as readings
FROM lake.minute_facts
WHERE blood_pressure_systolic_mmhg IS NOT NULL
  AND timestamp_utc >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY DATE(timestamp_utc)
ORDER BY date;

-- 7-day rolling average
SELECT 
    ROUND(AVG(blood_pressure_systolic_mmhg), 1) as avg_systolic,
    ROUND(AVG(blood_pressure_diastolic_mmhg), 1) as avg_diastolic,
    ROUND(MIN(blood_pressure_systolic_mmhg), 1) as min_systolic,
    ROUND(MAX(blood_pressure_systolic_mmhg), 1) as max_systolic
FROM lake.minute_facts
WHERE blood_pressure_systolic_mmhg IS NOT NULL
  AND timestamp_utc >= CURRENT_DATE - INTERVAL '7 days';

-- Morning vs evening BP (if time of day matters)
SELECT 
    CASE 
        WHEN EXTRACT(HOUR FROM timestamp_local) < 12 THEN 'Morning'
        ELSE 'Evening'
    END as time_of_day,
    ROUND(AVG(blood_pressure_systolic_mmhg), 1) as avg_systolic,
    ROUND(AVG(blood_pressure_diastolic_mmhg), 1) as avg_diastolic
FROM lake.minute_facts
WHERE blood_pressure_systolic_mmhg IS NOT NULL
  AND timestamp_utc >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY 1;
```

### UI Specification

```
┌─────────────────────────────────────────────────────────────────┐
│  🩺 Blood Pressure (7-day avg)                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│     122 / 78 mmHg                          🟢 Normal            │
│     ▔▔▔▔▔   ▔▔▔▔                                               │
│   systolic  diastolic                                           │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ [30-day trend chart with optimal zone shaded]           │   │
│  │                                           ════ Optimal  │   │
│  │     •   •  •    •                                        │   │
│  │  •         •  •    •  •  •                               │   │
│  │ ────────────────────────────────────────────────────    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Range (7d): 118-128 / 74-82 mmHg                              │
└─────────────────────────────────────────────────────────────────┘
```

### Streamlit Implementation

```python
def render_blood_pressure_panel():
    """Render blood pressure panel with trend"""
    
    st.subheader("🩺 Blood Pressure")
    
    # Get data
    current_bp = get_current_bp(days=7)
    bp_trend = get_bp_trend(days=30)
    
    # Main display
    col1, col2 = st.columns([2, 1])
    
    with col1:
        systolic = current_bp['avg_systolic']
        diastolic = current_bp['avg_diastolic']
        
        # Determine category
        if systolic < 120 and diastolic < 80:
            category = "🟢 Normal"
        elif systolic < 130 and diastolic < 80:
            category = "🟡 Elevated"
        elif systolic < 140 or diastolic < 90:
            category = "🟠 Stage 1 HTN"
        else:
            category = "🔴 Stage 2 HTN"
        
        st.metric(
            "7-Day Average",
            f"{systolic:.0f} / {diastolic:.0f} mmHg",
            help="Systolic / Diastolic"
        )
        st.caption(category)
    
    with col2:
        st.write(f"**Range (7d):**")
        st.write(f"{current_bp['min_systolic']:.0f}-{current_bp['max_systolic']:.0f} / "
                 f"{current_bp['min_diastolic']:.0f}-{current_bp['max_diastolic']:.0f}")
    
    # Trend chart
    if not bp_trend.empty:
        fig = go.Figure()
        
        # Systolic line
        fig.add_trace(go.Scatter(
            x=bp_trend['date'],
            y=bp_trend['systolic'],
            mode='lines+markers',
            name='Systolic',
            line=dict(color='#e74c3c')
        ))
        
        # Diastolic line
        fig.add_trace(go.Scatter(
            x=bp_trend['date'],
            y=bp_trend['diastolic'],
            mode='lines+markers',
            name='Diastolic',
            line=dict(color='#3498db')
        ))
        
        # Optimal zone
        fig.add_hrect(y0=70, y1=80, fillcolor="green", opacity=0.1,
                      annotation_text="Optimal Diastolic", line_width=0)
        fig.add_hline(y=120, line_dash="dash", line_color="orange",
                      annotation_text="Elevated threshold")
        
        fig.update_layout(
            height=200,
            margin=dict(l=0, r=0, t=20, b=0),
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02)
        )
        
        st.plotly_chart(fig, use_container_width=True)
```

---

## Glucose/CGM Panel

### Purpose

Track blood glucose trends from CGM data. Important for metabolic health, energy optimization, and monitoring impact of nutrition/training.

### Data Sources

| Metric | Source | Field |
|--------|--------|-------|
| Blood Glucose | HAE minute_facts | `blood_glucose_mg_dl` |

### Key Metrics

| Metric | Target | Description |
|--------|--------|-------------|
| Average Glucose | 80-100 mg/dL | Fasting/baseline |
| Time in Range | >70% | Time between 70-140 mg/dL |
| Glucose Variability | <20% CV | Standard deviation / mean |
| Post-meal Peak | <140 mg/dL | Max after eating |
| Fasting Glucose | 70-90 mg/dL | Morning before eating |

### Data Queries

```sql
-- Daily glucose stats
SELECT 
    DATE(timestamp_utc) as date,
    ROUND(AVG(blood_glucose_mg_dl), 1) as avg_glucose,
    ROUND(MIN(blood_glucose_mg_dl), 1) as min_glucose,
    ROUND(MAX(blood_glucose_mg_dl), 1) as max_glucose,
    ROUND(STDDEV(blood_glucose_mg_dl), 1) as std_glucose,
    COUNT(*) as readings
FROM lake.minute_facts
WHERE blood_glucose_mg_dl IS NOT NULL
  AND timestamp_utc >= CURRENT_DATE - INTERVAL '14 days'
GROUP BY DATE(timestamp_utc)
ORDER BY date;

-- Time in range (70-140 mg/dL)
SELECT 
    ROUND(100.0 * SUM(CASE WHEN blood_glucose_mg_dl BETWEEN 70 AND 140 THEN 1 ELSE 0 END) / COUNT(*), 1) as time_in_range,
    ROUND(100.0 * SUM(CASE WHEN blood_glucose_mg_dl < 70 THEN 1 ELSE 0 END) / COUNT(*), 1) as time_low,
    ROUND(100.0 * SUM(CASE WHEN blood_glucose_mg_dl > 140 THEN 1 ELSE 0 END) / COUNT(*), 1) as time_high
FROM lake.minute_facts
WHERE blood_glucose_mg_dl IS NOT NULL
  AND timestamp_utc >= CURRENT_DATE - INTERVAL '7 days';

-- Glucose by time of day
SELECT 
    EXTRACT(HOUR FROM timestamp_local) as hour,
    ROUND(AVG(blood_glucose_mg_dl), 1) as avg_glucose
FROM lake.minute_facts
WHERE blood_glucose_mg_dl IS NOT NULL
  AND timestamp_utc >= CURRENT_DATE - INTERVAL '14 days'
GROUP BY EXTRACT(HOUR FROM timestamp_local)
ORDER BY hour;

-- Estimated A1C (from 90-day average glucose)
-- Formula: A1C = (avg_glucose + 46.7) / 28.7
SELECT 
    ROUND(AVG(blood_glucose_mg_dl), 1) as avg_glucose_90d,
    ROUND((AVG(blood_glucose_mg_dl) + 46.7) / 28.7, 1) as estimated_a1c
FROM lake.minute_facts
WHERE blood_glucose_mg_dl IS NOT NULL
  AND timestamp_utc >= CURRENT_DATE - INTERVAL '90 days';
```

### Glucose Score Calculation

```python
def calculate_glucose_score(metrics: dict) -> int:
    """
    Composite glucose score based on:
    - Time in range (70-140): 50%
    - Average glucose: 30%
    - Variability (CV): 20%
    """
    # Time in range score (target >70%)
    tir = metrics['time_in_range']
    if tir >= 85:
        tir_score = 100
    elif tir >= 70:
        tir_score = 70 + (tir - 70) * 2  # 70-100 for 70-85%
    else:
        tir_score = tir  # Direct mapping below 70%
    
    # Average glucose score (target 80-100 mg/dL)
    avg = metrics['avg_glucose']
    if 80 <= avg <= 100:
        avg_score = 100
    elif 70 <= avg < 80 or 100 < avg <= 110:
        avg_score = 85
    elif 60 <= avg < 70 or 110 < avg <= 125:
        avg_score = 65
    else:
        avg_score = 40
    
    # Variability score (CV target <20%)
    cv = metrics['cv']  # coefficient of variation
    if cv < 15:
        cv_score = 100
    elif cv < 20:
        cv_score = 80
    elif cv < 25:
        cv_score = 60
    else:
        cv_score = 40
    
    # Weighted total
    return round(tir_score * 0.5 + avg_score * 0.3 + cv_score * 0.2)
```

### UI Specification

```
┌─────────────────────────────────────────────────────────────────┐
│  📊 Glucose (CGM - 7 day)                                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Average: 94 mg/dL        Time in Range: 82%     🟢 Good       │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ [7-day glucose trace with target zone shaded]           │   │
│  │ ═══════════════════════════════════════ Target Zone     │   │
│  │    ~~~∿∿∿~~~∿∿∿~~~∿∿∿~~~∿∿∿~~~∿∿∿~~~∿∿               │   │
│  │ ─────────────────────────────────────────────────────   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ├─ Time Low (<70): 3%                                         │
│  ├─ Time in Range (70-140): 82%                                │
│  └─ Time High (>140): 15%                                      │
│                                                                 │
│  Estimated A1C: 5.2%       Variability (CV): 18%               │
└─────────────────────────────────────────────────────────────────┘
```

### Streamlit Implementation

```python
def render_glucose_panel():
    """Render CGM glucose panel"""
    
    st.subheader("📊 Glucose (CGM)")
    
    # Get data
    glucose_stats = get_glucose_stats(days=7)
    glucose_trace = get_glucose_trace(days=7)
    time_in_range = get_time_in_range(days=7)
    
    # Summary row
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Average", f"{glucose_stats['avg']:.0f} mg/dL")
    with col2:
        st.metric("Time in Range", f"{time_in_range['in_range']:.0f}%")
    with col3:
        glucose_score = calculate_glucose_score(glucose_stats)
        status = "🟢 Good" if glucose_score >= 80 else "🟡 Fair" if glucose_score >= 60 else "🟠 Monitor"
        st.write(status)
    
    # Glucose trace
    if not glucose_trace.empty:
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=glucose_trace['timestamp'],
            y=glucose_trace['glucose'],
            mode='lines',
            name='Glucose',
            line=dict(color='#9b59b6', width=1)
        ))
        
        # Target zone
        fig.add_hrect(y0=70, y1=140, fillcolor="green", opacity=0.1,
                      annotation_text="Target Range", line_width=0)
        fig.add_hline(y=70, line_dash="dash", line_color="orange")
        fig.add_hline(y=140, line_dash="dash", line_color="orange")
        
        fig.update_layout(
            height=200,
            margin=dict(l=0, r=0, t=20, b=0),
            yaxis_title="mg/dL",
            showlegend=False
        )
        
        st.plotly_chart(fig, use_container_width=True)
    
    # Time in range breakdown
    col1, col2, col3 = st.columns(3)
    with col1:
        st.caption(f"⬇️ Low (<70): {time_in_range['low']:.1f}%")
    with col2:
        st.caption(f"✅ In Range: {time_in_range['in_range']:.1f}%")
    with col3:
        st.caption(f"⬆️ High (>140): {time_in_range['high']:.1f}%")
    
    # Estimated A1C
    if glucose_stats.get('estimated_a1c'):
        st.caption(f"Estimated A1C: {glucose_stats['estimated_a1c']:.1f}% | "
                   f"Variability (CV): {glucose_stats['cv']:.0f}%")
```

---

## VO2max Tracking

### Purpose

Track Apple Watch VO2max estimates as a standalone fitness indicator. This remains separate from the Cardio Score pending analysis to validate Apple's estimates against lactate-derived values.

### Data Sources

| Metric | Source | Field |
|--------|--------|-------|
| VO2max | HAE minute_facts | `vo2_max_ml_kg_min` |

### Age-Adjusted Fitness Categories (Men 55-59)

| Category | VO2max (ml/kg/min) | Score |
|----------|-------------------|-------|
| Superior | ≥41 | 100 |
| Excellent | 36-40 | 90 |
| Good | 32-35 | 75 |
| Fair | 27-31 | 55 |
| Poor | <27 | 30 |

### Data Queries

```sql
-- Latest VO2max reading
SELECT 
    DATE(timestamp_utc) as date,
    MAX(vo2_max_ml_kg_min) as vo2max
FROM lake.minute_facts
WHERE vo2_max_ml_kg_min IS NOT NULL
ORDER BY timestamp_utc DESC
LIMIT 1;

-- VO2max trend (Apple updates infrequently)
SELECT 
    DATE(timestamp_utc) as date,
    MAX(vo2_max_ml_kg_min) as vo2max
FROM lake.minute_facts
WHERE vo2_max_ml_kg_min IS NOT NULL
  AND timestamp_utc >= CURRENT_DATE - INTERVAL '365 days'
GROUP BY DATE(timestamp_utc)
ORDER BY date;

-- Monthly averages
SELECT 
    DATE_TRUNC('month', timestamp_utc) as month,
    ROUND(AVG(vo2_max_ml_kg_min), 1) as avg_vo2max,
    COUNT(DISTINCT DATE(timestamp_utc)) as measurement_days
FROM lake.minute_facts
WHERE vo2_max_ml_kg_min IS NOT NULL
  AND timestamp_utc >= CURRENT_DATE - INTERVAL '365 days'
GROUP BY DATE_TRUNC('month', timestamp_utc)
ORDER BY month;
```

### VO2max Score

```python
def calculate_vo2max_score(vo2max: float, age: int = 56) -> dict:
    """
    Score VO2max based on age-adjusted percentiles
    
    Using ACSM percentile data for men age 55-59
    """
    # Age 55-59 male percentiles
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
    
    return {
        'score': score,
        'category': category,
        'percentile': percentile,
        'value': vo2max
    }
```

### UI Specification

```
┌─────────────────────────────────────────────────────────────────┐
│  🫁 VO2max                                                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│     38.2 ml/kg/min                         🟢 Excellent        │
│     ▔▔▔▔▔▔▔▔▔▔▔▔▔▔                                            │
│     75th-90th percentile (age 55-59)                           │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ [12-month trend - Apple updates infrequently]           │   │
│  │                          •  •   •                        │   │
│  │              •   •  •                                    │   │
│  │     •   •                                                │   │
│  │ ─────────────────────────────────────────────────────   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ⚠️ Note: Apple estimate - pending validation vs lactate tests │
└─────────────────────────────────────────────────────────────────┘
```

### Integration Note

VO2max is displayed as a standalone KPI rather than incorporated into the Cardio Score because:
1. Apple Watch VO2max estimation methodology is opaque
2. Need to validate against lactate step test derived values
3. May not correlate well with your actual cardio performance during iron recovery

Once validated, VO2max could be added to PCS as a Tier 1 component (capacity indicator).

---

### Scope

- **Full Recovery Score:** 2025 onward (requires Oura data)
- **Partial Recovery Score (training load only):** Full history
- **Cardio Score:** Mostly full history, HR Response/Recovery limited to HAE data availability

### Batch Calculation Script

```python
# scripts/backfill_scores.py

import duckdb
from datetime import date, timedelta
from tqdm import tqdm

def backfill_recovery_scores(start_date: date, end_date: date):
    """Calculate and store historical PRS values"""
    
    conn = duckdb.connect('Data/hdp.duckdb')
    
    # Create scores table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recovery_scores (
            score_date DATE PRIMARY KEY,
            total_score INTEGER,
            sleep_tier_score INTEGER,
            autonomic_tier_score INTEGER,
            training_tier_score INTEGER,
            -- Individual components
            sleep_duration_score INTEGER,
            sleep_efficiency_score INTEGER,
            sleep_debt_score INTEGER,
            hrv_score INTEGER,
            rhr_score INTEGER,
            acwr_score INTEGER,
            rest_days_score INTEGER,
            yesterday_score INTEGER,
            -- Raw values for debugging
            sleep_duration_hours FLOAT,
            sleep_debt_hours FLOAT,
            hrv_value FLOAT,
            hrv_baseline FLOAT,
            rhr_value FLOAT,
            rhr_baseline FLOAT,
            acute_load FLOAT,
            chronic_load FLOAT,
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    current = start_date
    while current <= end_date:
        try:
            # Calculate score for this date
            score = calculate_recovery_score_for_date(conn, current)
            
            # Insert/update
            conn.execute("""
                INSERT OR REPLACE INTO recovery_scores 
                (score_date, total_score, sleep_tier_score, ...)
                VALUES (?, ?, ?, ...)
            """, [current, score['total'], ...])
            
        except Exception as e:
            print(f"Error calculating {current}: {e}")
        
        current += timedelta(days=1)
    
    conn.close()

def backfill_cardio_scores(start_date: date, end_date: date):
    """Calculate and store historical PCS values"""
    # Similar structure to recovery scores
    pass

if __name__ == "__main__":
    # Backfill from Oura start date
    backfill_recovery_scores(date(2025, 1, 1), date.today())
    backfill_cardio_scores(date(2025, 1, 1), date.today())
```

### Storage Schema

```sql
-- Recovery scores table
CREATE TABLE recovery_scores (
    score_date DATE PRIMARY KEY,
    total_score INTEGER,
    status VARCHAR(20),
    -- Tier scores
    sleep_tier INTEGER,
    autonomic_tier INTEGER,
    training_tier INTEGER,
    -- Component scores (for drill-down)
    comp_sleep_duration INTEGER,
    comp_sleep_efficiency INTEGER,
    comp_sleep_debt INTEGER,
    comp_hrv INTEGER,
    comp_rhr INTEGER,
    comp_acwr INTEGER,
    comp_rest_days INTEGER,
    comp_yesterday INTEGER,
    -- Metadata
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cardio scores table  
CREATE TABLE cardio_scores (
    score_date DATE PRIMARY KEY,
    total_score INTEGER,
    status VARCHAR(20),
    -- Tier scores
    capacity_tier INTEGER,
    responsiveness_tier INTEGER,
    efficiency_tier INTEGER,
    -- Component scores
    comp_max_hr INTEGER,
    comp_zone2_power INTEGER,
    comp_hr_response INTEGER,
    comp_hr_recovery INTEGER,
    comp_aero_efficiency INTEGER,
    comp_resting_hr INTEGER,
    comp_hrv_health INTEGER,
    -- Raw values
    max_hr_value INTEGER,
    hr_response_minutes FLOAT,
    -- Metadata
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Query Pattern for Dashboard

```python
@st.cache_data(ttl=3600)
def get_recovery_score(target_date: date) -> dict:
    """Get pre-calculated recovery score, or calculate if missing"""
    
    result = conn.execute("""
        SELECT * FROM recovery_scores WHERE score_date = ?
    """, [target_date]).fetchone()
    
    if result:
        return format_score_result(result)
    else:
        # Calculate on-demand (slower, but handles gaps)
        return calculate_recovery_score_for_date(conn, target_date)
```

---

## Data Dependencies Summary

### Required for Recovery Score

| Data | Source | Required Fields | Available From |
|------|--------|-----------------|----------------|
| Sleep | Oura | total_sleep_duration, sleep_efficiency | 2025 |
| HRV | Oura | hrv_avg | 2025 |
| Resting HR | Oura | resting_heart_rate | 2025 |
| Cardio workouts | Concept2 | workout_date, total_seconds | Full history |
| Strength workouts | JEFIT | workout_date, exercise_name | Full history |

### Required for Cardio Score

| Data | Source | Required Fields | Available From |
|------|--------|-----------------|----------------|
| Max HR | Concept2 | max_heart_rate | Full history |
| Zone 2 Power | Concept2 | avg_watts (filtered) | Full history |
| HR by minute | HAE | timestamp, heart_rate | 2025? (verify) |
| Resting HR | Oura | resting_heart_rate | 2025 |
| HRV | Oura | hrv_avg | 2025 |

### Required for Vitals Score

| Data | Source | Required Fields | Available From |
|------|--------|-----------------|----------------|
| Blood Pressure | HAE minute_facts | blood_pressure_systolic_mmhg, blood_pressure_diastolic_mmhg | Varies by entry |
| Resting HR | Oura | resting_heart_rate_bpm | 2025 |
| HRV | Oura | hrv_ms | 2025 |
| SpO2 | HAE minute_facts | blood_oxygen_saturation_pct | Varies |
| Respiratory Rate | HAE minute_facts | respiratory_rate_count_min | Varies |

### Required for Body Composition

| Data | Source | Required Fields | Available From |
|------|--------|-----------------|----------------|
| Weight | HAE daily_summary | weight_lb | Entry dependent |
| Body Fat % | HAE daily_summary | body_fat_pct | Entry dependent |
| Lean Body Mass | HAE daily_summary | lean_body_mass_lb | Entry dependent |

### Required for Glucose/CGM

| Data | Source | Required Fields | Available From |
|------|--------|-----------------|----------------|
| Blood Glucose | HAE minute_facts | blood_glucose_mg_dl | 2025 (CGM usage) |

### Required for VO2max

| Data | Source | Required Fields | Available From |
|------|--------|-----------------|----------------|
| VO2max | HAE minute_facts | vo2_max_ml_kg_min | Apple Watch updates |

### Validation Queries

```sql
-- Check Oura data availability
SELECT MIN(summary_date), MAX(summary_date), COUNT(*)
FROM read_parquet('Data/Parquet/oura_daily_summaries/**/*.parquet');

-- Check HAE data availability (for HR response calculation)
SELECT MIN(DATE(timestamp)), MAX(DATE(timestamp)), COUNT(*)
FROM read_parquet('Data/Parquet/hae_heart_rate_minute/**/*.parquet');

-- Check for gaps in Oura data
SELECT summary_date
FROM generate_series(
    (SELECT MIN(summary_date) FROM oura_daily_summaries),
    (SELECT MAX(summary_date) FROM oura_daily_summaries),
    INTERVAL '1 day'
) AS d(summary_date)
WHERE summary_date NOT IN (SELECT summary_date FROM oura_daily_summaries);
```

---

## Open Items for CC

1. **Verify HAE data schema:** Need to confirm exact field names and timestamp format for HR Response Time calculation

2. **Concept2 workout_id linking:** Verify how to join Concept2 workouts with HAE minute data (by date? by time overlap?)

3. **JEFIT volume estimation:** Current spec estimates 2 min/set for training load. May need refinement based on actual JEFIT data structure.

4. **Baseline bootstrap:** For users without 90 days of history, need fallback (use available data, or population defaults?)

5. **Score caching strategy:** Pre-calculate nightly via cron, or calculate on-demand with caching? Recommend pre-calculate for historical, on-demand for today.

6. **BP data frequency:** How often is BP being logged? If sparse, may need to adjust averaging windows.

7. **CGM data continuity:** Verify CGM data coverage in 2025. Are there gaps? How to handle missing periods?

8. **VO2max validation:** Peter plans to validate Apple Watch VO2max against lactate-derived estimates. Results may affect whether VO2max gets incorporated into Cardio Score.

9. **Body composition data source:** Confirm if data comes from smart scale, manual entry, or DEXA scans. Affects expected frequency and accuracy.

10. **Temperature alerts:** Consider adding Oura temperature deviation alerts (>0.5°C) as early illness warning.

---

## Version History

- **v1.0** (2026-01-03): Initial addendum created
  - Peter's Recovery Score (PRS) specification
  - Peter's Cardio Score (PCS) specification
  - Compound visibility controls
  - Decision gates panel
  - Historical backfill approach

- **v1.1** (2026-01-03): Major expansion
  - Added Peter's Vitals Score (PVS) specification
  - Added Body Composition panel
  - Added Blood Pressure panel
  - Added Glucose/CGM panel
  - Added VO2max tracking (standalone KPI)
  - Expanded KPI layout from 12 to 16 cards
  - Updated data dependencies for all new sources
  - Added queries for all HAE minute_facts and daily_summary fields

---

**End of Addendum**
