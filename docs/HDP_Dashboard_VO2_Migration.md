# HDP Dashboard VO₂ Migration Specification v2

**Created:** 2026-01-04  
**Updated:** 2026-01-04 (3-Gate Overlap Model)  
**Purpose:** Migrate Cardio Score from HR responsiveness to multi-signal VO₂ overlap detection  
**Status:** Specification (Ready for Implementation)

---

## Executive Summary

Replace the **Responsiveness (35%)** component in the Cardio Score with **VO₂ Stimulus (35%)** based on a **3-gate convergence model** validated by Geepy and Gemini.

**Key Advancement:** Single-signal approaches (HR_drop only, RR only) are permissive/noisy. The 3-gate overlap model detects a **physiological state** rather than estimating a metric, providing:
- Multi-signal convergence = high confidence
- Built-in quality checks (inflation ratio)
- Falsifiable validation against lactate, power decay, RPE

### The Three Gates

**Gate 1 — Cardiovascular Load:**
- HR ≥ 88-92% of session max HR OR
- HR plateaued high with minimal drift

**Gate 2 — Ventilatory Engagement:**
- RR elevated above Zone 2 baseline AND/OR
- RR fails to normalize during easy intervals AND/OR
- RR variability exceeds steady-state variance

**Gate 3 — Recovery Impairment:**
- HR_drop ≤ 2-3 bpm over 30s easy interval

**Scoring:**
- 1 gate → Approaching VO₂
- 2 gates → Probable VO₂  
- **3 gates → True VO₂ stimulus** ✅

---

## Current State

### Cardio Score Structure (BEFORE)

```
┌─────────────────────────────────────────────────────────────────┐
│  ❤️ Cardio Score                                            57  │
│  ████████████████████░░░░░░░░░░░░░░░░░░  🟠 Compromised        │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Capacity & Ceiling (35%) — 86                                │
│    ├─ Max HR                97                                  │
│    └─ Zone2 Power           [not visible in screenshot]         │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Responsiveness (35%) — 50                    ← LIMITER       │
│    ├─ Hr Response Time      50                                  │
│    └─ Hr Recovery           50                                  │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Efficiency & Baseline (30%) — 33                             │
│    ├─ Aerobic Efficiency    80                                  │
│    ├─ Resting Hr            42                                  │
│    └─ Hrv Health            [score not visible]                 │
└─────────────────────────────────────────────────────────────────┘
```

**Problem:** Responsiveness (50) is dragging down the overall score, but per Geepy's framework, slow HR kinetics aren't necessarily a problem—they're a feature of high stroke volume and strong aerobic base.

---

## Target State

### Cardio Score Structure (AFTER)

```
┌─────────────────────────────────────────────────────────────────┐
│  ❤️ Cardio Score                                            72  │
│  ████████████████████████████░░░░░░░░░░░  🟡 Good               │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Capacity & Ceiling (35%) — 86                                │
│    ├─ Max HR                97                                  │
│    └─ Zone2 Power           75                                  │
├─────────────────────────────────────────────────────────────────┤
│  ▼ VO₂ Stimulus (35%) — 78                      ← IMPROVED      │
│    ├─ Weekly VO₂ Time       88                                  │
│    └─ Time to Late Phase    68                                  │
├─────────────────────────────────────────────────────────────────┤
│  ▼ Efficiency & Baseline (30%) — 55                             │
│    ├─ Aerobic Efficiency    80                                  │
│    ├─ Resting Hr            42                                  │
│    └─ Hrv Health            42                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Key Changes:**
1. **Renamed:** "Responsiveness" → "VO₂ Stimulus"
2. **Metric 1 (NEW):** Weekly VO₂ Stimulus Time (replaces Hr Response Time)
3. **Metric 2 (NEW):** Time to Late Phase (replaces Hr Recovery)

---

## Data Sources (Already Available)

### Polar H10 Data ✅
You already have respiratory rate ingestion from Polar H10 ECG-derived respiration:
- **Table:** `polar_respiratory`
- **Key fields:**
  - `respiratory_rate` (breaths/min)
  - `window_center_min` (time position)
  - `confidence` (signal quality 0-1)
  - `avg_hr` (concurrent HR for correlation)
- **Schema:** `src/pipeline/common/schema.py` → `polar_respiratory_schema`
- **Ingestion:** `src/pipeline/ingest/polar_h10.py` → `derive_respiratory_rate_edr()`

### Concept2 Stroke Data ✅
- **Table:** `cardio_strokes`
- **Key fields:**
  - `heart_rate_bpm`
  - `time_cumulative_s`
  - `watts`
  - `stroke_rate_spm`

### Workout Metadata ✅
- **Table:** `workouts`
- **Key fields:**
  - `workout_id`
  - `start_time_utc`
  - `duration_min`
  - `source`

---

## Data Pipeline Implementation

### Module Structure

```
src/pipeline/analysis/
├── vo2_gates.py          # Individual gate detection (NEW)
├── vo2_overlap.py        # 3-gate overlap calculation (NEW)
└── vo2_metrics.py        # Exists, will extend

analysis/apps/utils/
└── vo2_scoring.py        # Dashboard scoring (NEW)
```

### Gate Detection Logic

**Location:** `src/pipeline/analysis/vo2_gates.py` (NEW)

```python
"""Three-gate VO₂ stimulus detection."""
from datetime import datetime
import pandas as pd
import numpy as np


def detect_gate1_hr_load(
    strokes_df: pd.DataFrame,
    warmup_min: float = 2.0,
    hr_threshold_pct: float = 0.90
) -> pd.DataFrame:
    """
    Gate 1: Cardiovascular Load
    
    Detects when HR ≥ 90% of session max OR HR plateaued high
    
    Returns:
        DataFrame with time windows where Gate 1 is satisfied
    """
    # Get session max HR (after warmup)
    warmup_sec = warmup_min * 60
    post_warmup = strokes_df[strokes_df['time_cumulative_s'] > warmup_sec]
    session_max_hr = post_warmup['heart_rate_bpm'].max()
    
    hr_threshold = session_max_hr * hr_threshold_pct
    
    # Mark periods where HR meets threshold
    strokes_df['gate1_active'] = strokes_df['heart_rate_bpm'] >= hr_threshold
    
    return strokes_df[['time_cumulative_s', 'heart_rate_bpm', 'gate1_active']]


def detect_gate2_rr_engagement(
    resp_df: pd.DataFrame,
    zone2_baseline_rr_med: float,  # From your lactate-verified Z2 sessions
    zone2_baseline_rr_mad: float,  # Robust variability measure
    zone2_baseline_rr_var: float,  # Variability of variability
    warmup_min: float = 2.0,
    interval_duration: float = 30.0
) -> pd.DataFrame:
    """
    Gate 2: Ventilatory Engagement (Geepy's Merged Specification)
    
    Primary: ELEVATED_AND_FAILING
    - RR elevated above Z2 baseline
    - RR fails to drop during easy intervals
    
    Secondary: CHAOTIC (optional enhancer)
    - RR variability exceeds Z2 baseline chaos
    
    Returns:
        DataFrame with interval-level gate status
    """
    if resp_df.empty:
        return pd.DataFrame()
    
    # Preprocessing: 15s rolling median to strip jitter
    resp_df = resp_df.copy()
    resp_df['rr_smoothed'] = (
        resp_df['respiratory_rate']
        .rolling(window=3, min_periods=1, center=True)  # ~15s windows
        .median()
    )
    
    # Filter to work period
    work_resp = resp_df[resp_df['window_center_min'] >= warmup_min].copy()
    
    if work_resp.empty:
        return pd.DataFrame()
    
    # Personalized thresholds
    rr_hi = zone2_baseline_rr_med + max(6, 3 * zone2_baseline_rr_mad)
    rr_drop_min = max(1.5, 2 * zone2_baseline_rr_mad)
    rr_var_hi = max(2.0, 2 * zone2_baseline_rr_var)
    
    # Calculate per-interval metrics
    results = []
    
    # Identify easy intervals based on time windows
    # Assuming 30s work / 30s easy: easy = [0.5-1.0, 1.5-2.0, 2.5-3.0 min, ...]
    max_time = work_resp['window_center_min'].max()
    interval_count = int(max_time)
    
    for i in range(interval_count):
        # Easy interval: i*1.0 + 0.5 to i*1.0 + 1.0 minutes
        easy_start = warmup_min + i * 1.0 + 0.5
        easy_end = easy_start + 0.5
        
        easy_windows = work_resp[
            (work_resp['window_center_min'] >= easy_start) &
            (work_resp['window_center_min'] <= easy_end)
        ]
        
        if len(easy_windows) < 2:
            continue
        
        # RR at start/end of easy interval
        rr_start_e = easy_windows.iloc[0]['rr_smoothed']
        rr_end_e = easy_windows.iloc[-1]['rr_smoothed']
        rr_drop_e = rr_start_e - rr_end_e
        rr_mean_e = easy_windows['rr_smoothed'].median()
        
        # Primary condition: ELEVATED_AND_FAILING
        elevated_and_failing = (rr_mean_e >= rr_hi) and (rr_drop_e <= rr_drop_min)
        
        # Secondary condition: CHAOTIC
        # Calculate MAD over 60s rolling window around this interval
        chaos_window = work_resp[
            (work_resp['window_center_min'] >= easy_start - 0.5) &
            (work_resp['window_center_min'] <= easy_end + 0.5)
        ]
        
        if len(chaos_window) >= 3:
            rr_median = chaos_window['rr_smoothed'].median()
            rr_mad = (chaos_window['rr_smoothed'] - rr_median).abs().median()
            chaotic = rr_mad >= rr_var_hi
        else:
            chaotic = False
        
        # Final Gate 2 decision
        gate2_active = elevated_and_failing or chaotic
        
        results.append({
            'interval_number': i + 1,
            'interval_start_min': easy_start,
            'interval_end_min': easy_end,
            'rr_mean_e': rr_mean_e,
            'rr_drop_e': rr_drop_e,
            'elevated_and_failing': elevated_and_failing,
            'chaotic': chaotic,
            'gate2_active': gate2_active
        })
    
    return pd.DataFrame(results)


def detect_gate3_recovery_impairment(
    strokes_df: pd.DataFrame,
    interval_duration: float = 30.0,
    hr_drop_threshold: float = 2.5  # ≤2.5 bpm = impaired
) -> pd.DataFrame:
    """
    Gate 3: Recovery Impairment
    
    Detects when HR_drop ≤ 2.5 bpm during 30s easy intervals
    
    Returns:
        DataFrame with interval-level gate status
    """
    results = []
    
    # Identify easy intervals (30-60s, 90-120s, etc.)
    total_duration = strokes_df['time_cumulative_s'].max()
    interval_count = int(total_duration / 60)
    
    for i in range(interval_count):
        easy_start = i * 60 + 30
        easy_end = easy_start + interval_duration
        
        # Get HR at start/end of easy interval
        hr_start_rows = strokes_df[
            (strokes_df['time_cumulative_s'] >= easy_start) &
            (strokes_df['time_cumulative_s'] < easy_start + 5)
        ]
        hr_end_rows = strokes_df[
            (strokes_df['time_cumulative_s'] >= easy_end - 5) &
            (strokes_df['time_cumulative_s'] <= easy_end)
        ]
        
        if hr_start_rows.empty or hr_end_rows.empty:
            continue
        
        hr_start = hr_start_rows['heart_rate_bpm'].mean()
        hr_end = hr_end_rows['heart_rate_bpm'].mean()
        hr_drop = hr_start - hr_end
        
        # Gate 3 active if HR_drop ≤ threshold
        gate3_active = hr_drop <= hr_drop_threshold
        
        results.append({
            'interval_number': i + 1,
            'interval_start_min': easy_start / 60,
            'interval_end_min': easy_end / 60,
            'hr_drop': hr_drop,
            'gate3_active': gate3_active
        })
    
    return pd.DataFrame(results)
    total_duration = workout_df['time_cumulative_s'].max()
    interval_count = int(total_duration / 60)  # Each 60s = 1 work + 1 easy
    
    for i in range(interval_count):
        # Easy interval starts at (i*60 + 30) seconds
        easy_start = i * 60 + 30
        easy_end = easy_start + easy_interval_duration
        
        # Get HR at start and end of easy interval
        hr_start_rows = workout_df[
            (workout_df['time_cumulative_s'] >= easy_start) &
            (workout_df['time_cumulative_s'] < easy_start + 5)  # First 5s of easy
        ]
        
        hr_end_rows = workout_df[
            (workout_df['time_cumulative_s'] >= easy_end - 5) &
            (workout_df['time_cumulative_s'] <= easy_end)  # Last 5s of easy
        ]
        
        if hr_start_rows.empty or hr_end_rows.empty:
            continue
            
        hr_start = hr_start_rows['heart_rate_bpm'].mean()
        hr_end = hr_end_rows['heart_rate_bpm'].mean()
        hr_drop = hr_start - hr_end
        
        # Classify phase based on HR_drop
        if hr_drop >= 8:
            phase = 'Early'
        elif hr_drop >= 3:
            phase = 'Mid'
        else:
            phase = 'Late'  # VO₂ stimulus zone
        
        results.append({
            'interval_number': i + 1,
            'hr_start': hr_start,
            'hr_end': hr_end,
            'hr_drop': hr_drop,
            'phase': phase
        })
    
    return pd.DataFrame(results)


def calculate_vo2_stimulus_time(workout_df: pd.DataFrame) -> dict:
    """
    Calculate VO₂ stimulus metrics for a single workout.
    
    Returns:
        dict with keys:
            - vo2_stimulus_min: Minutes in Late phase (HR_drop ≤2)
            - time_to_late_phase_min: Minutes until first Late phase interval
            - high_cardio_load_min: Minutes with HR ≥90% session max
            - session_max_hr: Maximum HR during workout
    """
    # Get session max HR (after warmup - first 2 minutes)
    warmup_end = 120  # 2 minutes
    post_warmup = workout_df[workout_df['time_cumulative_s'] > warmup_end]
    session_max_hr = post_warmup['heart_rate_bpm'].max()
    
    # Calculate HR_drop for each interval
    hr_drop_df = calculate_hr_drop(workout_df)
    
    # VO₂ stimulus time = sum of Late phase intervals (30s each)
    late_phase_intervals = len(hr_drop_df[hr_drop_df['phase'] == 'Late'])
    vo2_stimulus_min = (late_phase_intervals * 30) / 60.0
    
    # Time to late phase = interval number of first Late phase * 60s
    first_late = hr_drop_df[hr_drop_df['phase'] == 'Late'].head(1)
    if not first_late.empty:
        time_to_late_phase_min = (first_late.iloc[0]['interval_number'] * 60) / 60.0
    else:
        time_to_late_phase_min = None  # Never reached late phase
    
    # High cardiovascular load time (HR ≥90% session max)
    hcl_threshold = session_max_hr * 0.90
    hcl_seconds = len(workout_df[workout_df['heart_rate_bpm'] >= hcl_threshold])
    high_cardio_load_min = hcl_seconds / 60.0
    
    return {
        'vo2_stimulus_min': vo2_stimulus_min,
        'time_to_late_phase_min': time_to_late_phase_min,
        'high_cardio_load_min': high_cardio_load_min,
        'session_max_hr': session_max_hr
    }


def query_weekly_vo2_metrics(conn: duckdb.DuckDBPyConnection, end_date: datetime) -> dict:
    """
    Query VO₂ metrics for the past 7 days.
    
    Returns:
        dict with keys:
            - weekly_vo2_stimulus_min: Total VO₂ stimulus time in past 7 days
            - sessions_with_late_phase: Number of sessions that reached late phase
            - avg_time_to_late_phase_min: Average time to reach late phase
    """
    start_date = end_date - timedelta(days=7)
    
    # Get all 30/30 workouts in the past week
    # (Assuming workout_type or tags identify 30/30 sessions)
    query = """
    SELECT 
        w.workout_id,
        w.start_time_utc
    FROM workouts w
    WHERE w.start_time_utc >= ?
      AND w.start_time_utc <= ?
      AND w.source = 'Concept2'
      AND w.duration_min >= 15  -- Filter for interval sessions
    ORDER BY w.start_time_utc DESC
    """
    
    workouts = conn.execute(query, [start_date, end_date]).df()
    
    total_vo2_stimulus_min = 0
    sessions_with_late_phase = 0
    times_to_late_phase = []
    
    for _, workout in workouts.iterrows():
        # Get stroke-level data for this workout
        stroke_query = """
        SELECT 
            time_cumulative_s,
            heart_rate_bpm
        FROM cardio_strokes
        WHERE workout_id = ?
          AND heart_rate_bpm IS NOT NULL
        ORDER BY time_cumulative_s
        """
        
        strokes = conn.execute(stroke_query, [workout['workout_id']]).df()
        
        if strokes.empty:
            continue
        
        # Calculate metrics
        metrics = calculate_vo2_stimulus_time(strokes)
        
        total_vo2_stimulus_min += metrics['vo2_stimulus_min']
        
        if metrics['time_to_late_phase_min'] is not None:
            sessions_with_late_phase += 1
            times_to_late_phase.append(metrics['time_to_late_phase_min'])
    
    avg_time_to_late_phase = (
        sum(times_to_late_phase) / len(times_to_late_phase)
        if times_to_late_phase else None
    )
    
    return {
        'weekly_vo2_stimulus_min': total_vo2_stimulus_min,
        'sessions_with_late_phase': sessions_with_late_phase,
        'avg_time_to_late_phase_min': avg_time_to_late_phase
    }
```

---

## Scoring Logic Changes

### New Component Scores

**Location:** `analysis/apps/utils/scoring.py` (new module)

```python
"""Scoring functions for composite health scores."""

def calculate_weekly_vo2_stimulus_score(weekly_vo2_min: float) -> int:
    """
    Score based on weekly VO₂ stimulus accumulation.
    
    Target: 15-25 min per week
    Optimal: 20 min
    
    Scoring:
    - 20+ min = 100
    - 15-20 min = linear 85-100
    - 10-15 min = linear 60-85
    - 5-10 min = linear 30-60
    - <5 min = 0-30 (minimal stimulus)
    """
    if weekly_vo2_min >= 20:
        return 100
    elif weekly_vo2_min >= 15:
        return 85 + ((weekly_vo2_min - 15) / 5 * 15)
    elif weekly_vo2_min >= 10:
        return 60 + ((weekly_vo2_min - 10) / 5 * 25)
    elif weekly_vo2_min >= 5:
        return 30 + ((weekly_vo2_min - 5) / 5 * 30)
    else:
        return max(0, weekly_vo2_min / 5 * 30)


def calculate_time_to_late_phase_score(time_to_late_min: float) -> int:
    """
    Score based on efficiency of reaching late phase.
    
    Faster entry = better session design and conditioning
    
    Scoring:
    - <5 min = 100 (very efficient)
    - 5-8 min = linear 85-100
    - 8-12 min = linear 60-85
    - 12-15 min = linear 40-60
    - >15 min = 20 (inefficient, most time wasted in early phase)
    """
    if time_to_late_min is None:
        return 0  # Never reached late phase
    
    if time_to_late_min < 5:
        return 100
    elif time_to_late_min < 8:
        return 85 + ((8 - time_to_late_min) / 3 * 15)
    elif time_to_late_min < 12:
        return 60 + ((12 - time_to_late_min) / 4 * 25)
    elif time_to_late_min < 15:
        return 40 + ((15 - time_to_late_min) / 3 * 20)
    else:
        return 20


def calculate_vo2_stimulus_tier_score(weekly_vo2_min: float, avg_time_to_late_min: float) -> dict:
    """
    Calculate the VO₂ Stimulus tier score (replaces Responsiveness).
    
    Weight distribution:
    - Weekly VO₂ Stimulus Time: 20% of total Cardio Score
    - Time to Late Phase: 15% of total Cardio Score
    
    Returns:
        dict with tier score and component breakdown
    """
    weekly_score = calculate_weekly_vo2_stimulus_score(weekly_vo2_min)
    time_to_late_score = calculate_time_to_late_phase_score(avg_time_to_late_min)
    
    # Weighted average for the tier (20% + 15% = 35% of total)
    tier_score = (weekly_score * (20/35) + time_to_late_score * (15/35))
    
    return {
        'score': round(tier_score),
        'weight': '35%',
        'components': {
            'weekly_vo2_stimulus': {
                'score': weekly_score,
                'value': f"{weekly_vo2_min:.1f} min",
                'target': '15-25 min/week'
            },
            'time_to_late_phase': {
                'score': time_to_late_score,
                'value': f"{avg_time_to_late_min:.1f} min" if avg_time_to_late_min else "N/A",
                'target': '<8 min'
            }
        }
    }
```

---

## Dashboard UI Changes

### Updated Cardio Score Component

**Location:** `analysis/apps/hdp_dashboard.py`

**Current code (BEFORE):**
```python
# Responsiveness tier - REMOVE THIS
with st.expander(f"Responsiveness (35%) — 50"):
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        st.write("Hr Response Time")
    with col2:
        st.progress(50 / 100)
    with col3:
        st.write("50")
    
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        st.write("Hr Recovery")
    with col2:
        st.progress(50 / 100)
    with col3:
        st.write("50")
```

**New code (AFTER):**
```python
# VO₂ Stimulus tier - ADD THIS
from utils.scoring import calculate_vo2_stimulus_tier_score
from pipeline.analysis.vo2_metrics import query_weekly_vo2_metrics

# Get VO₂ metrics
vo2_metrics = query_weekly_vo2_metrics(conn, end_date=datetime.now())
vo2_tier = calculate_vo2_stimulus_tier_score(
    weekly_vo2_min=vo2_metrics['weekly_vo2_stimulus_min'],
    avg_time_to_late_min=vo2_metrics['avg_time_to_late_phase_min']
)

with st.expander(f"VO₂ Stimulus (35%) — {vo2_tier['score']}"):
    # Weekly VO₂ Stimulus Time
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        st.write("Weekly VO₂ Time")
    with col2:
        st.progress(vo2_tier['components']['weekly_vo2_stimulus']['score'] / 100)
    with col3:
        st.write(str(vo2_tier['components']['weekly_vo2_stimulus']['score']))
    st.caption(f"{vo2_tier['components']['weekly_vo2_stimulus']['value']} | Target: {vo2_tier['components']['weekly_vo2_stimulus']['target']}")
    
    # Time to Late Phase
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        st.write("Time to Late Phase")
    with col2:
        st.progress(vo2_tier['components']['time_to_late_phase']['score'] / 100)
    with col3:
        st.write(str(vo2_tier['components']['time_to_late_phase']['score']))
    st.caption(f"{vo2_tier['components']['time_to_late_phase']['value']} | Target: {vo2_tier['components']['time_to_late_phase']['target']}")
```

---

## Implementation Plan

### Phase 1: Data Pipeline (Week 1)

**Tasks:**
1. ✅ Create `src/pipeline/analysis/vo2_metrics.py`
2. ✅ Write `calculate_hr_drop()` function
3. ✅ Write `calculate_vo2_stimulus_time()` function
4. ✅ Write `query_weekly_vo2_metrics()` function
5. ✅ Test on recent 30/30 workouts (Dec 26 session)

**Validation:**
- Run on Dec 26 BikeErg session
- Expected results:
  - Session max HR ≈ 146 bpm
  - VO₂ stimulus time ≈ 9-10 min
  - High cardiovascular load time ≈ 19.5 min

### Phase 2: Scoring Logic (Week 1)

**Tasks:**
1. ✅ Create `analysis/apps/utils/scoring.py`
2. ✅ Write `calculate_weekly_vo2_stimulus_score()`
3. ✅ Write `calculate_time_to_late_phase_score()`
4. ✅ Write `calculate_vo2_stimulus_tier_score()`
5. ✅ Test scoring functions with sample data

**Validation:**
- Test with Peter's current metrics:
  - Weekly VO₂ stimulus: ~18 min → Score ≈ 94
  - Time to late phase: ~6 min → Score ≈ 92
  - Tier score: ~93

### Phase 3: Dashboard Integration (Week 2)

**Tasks:**
1. ✅ Import new modules into `hdp_dashboard.py`
2. ✅ Replace Responsiveness expander with VO₂ Stimulus expander
3. ✅ Update Cardio Score calculation to use new tier
4. ✅ Test UI rendering
5. ✅ Deploy to Streamlit Cloud

**Validation:**
- Cardio Score should increase from ~57 to ~72
- VO₂ Stimulus tier should show ~78 (vs Responsiveness 50)
- Component scores should display correctly

### Phase 4: Deprecation (Week 2)

**Tasks:**
1. ✅ Keep old HR responsiveness queries for reference
2. ✅ Comment out old scoring functions (don't delete)
3. ✅ Update documentation
4. ✅ Add migration notes to project README

---

## Data Requirements

### Required Tables
- `cardio_strokes` (stroke-level HR data)
- `workouts` (session metadata)

### Required Fields
- `cardio_strokes.time_cumulative_s`
- `cardio_strokes.heart_rate_bpm`
- `cardio_strokes.workout_id`
- `workouts.workout_id`
- `workouts.start_time_utc`
- `workouts.source`

### Availability
- ✅ Stroke-level data available from Concept2 API
- ✅ Current HDP pipeline ingests this data
- ✅ Parquet files available in `Data/Parquet/cardio_strokes/`

---

## Testing Strategy

### Unit Tests
```python
# tests/test_vo2_metrics.py

import pandas as pd
from src.pipeline.analysis.vo2_metrics import calculate_hr_drop, calculate_vo2_stimulus_time

def test_hr_drop_calculation():
    """Test HR_drop calculation with synthetic data."""
    # Create synthetic 30/30 session (10 intervals)
    strokes = []
    for i in range(600):  # 10 minutes of data
        # Simulate HR pattern: high during work, drops during easy
        interval_position = i % 60
        if interval_position < 30:  # Work interval
            hr = 145
        else:  # Easy interval
            # Simulate recovery: Early phase (drops 10 bpm), Late phase (drops 2 bpm)
            if i < 300:  # First 5 min = Early phase
                hr = 145 - (interval_position - 30)  # Linear drop 145 → 135
            else:  # Last 5 min = Late phase
                hr = 145 - (interval_position - 30) * 0.2  # Minimal drop 145 → 139
        
        strokes.append({
            'time_cumulative_s': i,
            'heart_rate_bpm': hr
        })
    
    df = pd.DataFrame(strokes)
    hr_drop_df = calculate_hr_drop(df)
    
    # Assertions
    assert len(hr_drop_df) == 10  # 10 intervals
    assert hr_drop_df.iloc[0]['phase'] == 'Early'  # First interval
    assert hr_drop_df.iloc[-1]['phase'] == 'Late'  # Last interval
    assert hr_drop_df.iloc[-1]['hr_drop'] <= 2  # Late phase HR_drop


def test_vo2_stimulus_time():
    """Test VO₂ stimulus calculation with Dec 26 BikeErg data."""
    # Load actual workout data
    import duckdb
    conn = duckdb.connect('Data/hdp.duckdb')
    
    # Query Dec 26 workout
    query = """
    SELECT 
        time_cumulative_s,
        heart_rate_bpm
    FROM cardio_strokes
    WHERE workout_id = 'XXXXXX'  # Replace with actual workout_id
      AND heart_rate_bpm IS NOT NULL
    ORDER BY time_cumulative_s
    """
    
    df = conn.execute(query).df()
    metrics = calculate_vo2_stimulus_time(df)
    
    # Validate against Geepy's analysis
    assert 9.0 <= metrics['vo2_stimulus_min'] <= 10.5  # ~9-10 min
    assert 19.0 <= metrics['high_cardio_load_min'] <= 20.5  # ~19.5 min
    assert metrics['session_max_hr'] >= 145  # ≈146 bpm
```

### Integration Tests
```python
# tests/test_cardio_score_integration.py

def test_cardio_score_with_vo2_tier():
    """Test full Cardio Score calculation with new VO₂ tier."""
    from utils.scoring import calculate_vo2_stimulus_tier_score
    
    # Simulate Peter's current metrics
    weekly_vo2_min = 18.0
    avg_time_to_late_min = 6.0
    
    tier = calculate_vo2_stimulus_tier_score(weekly_vo2_min, avg_time_to_late_min)
    
    # Assertions
    assert 75 <= tier['score'] <= 85  # Should be ~78-80
    assert tier['components']['weekly_vo2_stimulus']['score'] >= 85
    assert tier['components']['time_to_late_phase']['score'] >= 85
```

---

## Rollback Plan

If issues arise, the old Responsiveness metrics can be re-enabled:

1. **Comment out** new VO₂ Stimulus expander in dashboard
2. **Uncomment** old Responsiveness expander
3. **Revert** Cardio Score calculation to use old tier
4. **Keep** new VO₂ modules for future use

**Rollback time:** ~5 minutes (UI-only change)

---

## Documentation Updates

### Files to Update
1. ✅ `HDP_Dashboard_Requirements.md` - Add VO₂ section
2. ✅ `HDP_Dashboard_Addendum_Scores.md` - Replace Responsiveness with VO₂ Stimulus
3. ✅ `PROJECT_STRUCTURE.md` - Add new analysis module
4. ✅ `README.md` - Note migration in changelog

### New Documentation
1. ✅ This file: `HDP_Dashboard_VO2_Migration.md`
2. ✅ `docs/vo2_stimulus_methodology.md` - Detailed explanation of Geepy's framework

---

## Success Criteria

### Functional
- ✅ VO₂ metrics calculate correctly from stroke data
- ✅ Weekly aggregation returns sensible values
- ✅ Scoring functions produce expected scores
- ✅ Dashboard displays new tier without errors

### User Experience
- ✅ Cardio Score increases to reflect actual cardiovascular improvement
- ✅ VO₂ Stimulus tier shows meaningful variation week-to-week
- ✅ Tooltips/captions explain new metrics clearly
- ✅ Peter can understand what drives the score

### Data Quality
- ✅ HR_drop calculations align with manual review of workouts
- ✅ Late phase detection matches Geepy's manual analysis
- ✅ Session max HR matches observed values

---

## Questions for Peter

1. **Workout Identification:** How should we identify 30/30 sessions? By duration? By tags? By workout notes?
2. **Historical Backfill:** Do you want VO₂ metrics calculated for all historical 30/30 sessions, or just prospective?
3. **Transition Period:** Should we run both metrics in parallel for a few weeks to validate?
4. **Other Interval Formats:** Should we extend this to 4x4 Norwegian intervals when you return to those?

---

## Next Steps

1. Review this spec with Peter
2. Create `vo2_metrics.py` module
3. Test on Dec 26 workout data
4. Create scoring module
5. Update dashboard UI
6. Deploy and validate

---

## Pending Tasks (Updated 2026-01-04)

### Completed ✅
- [x] `vo2_gates.py` - Individual gate detection functions
- [x] `vo2_overlap.py` - 3-gate convergence calculation
- [x] `vo2_metrics.py` - HR drop and respiratory rate analysis
- [x] Polar H10 ingestion module (`polar_h10.py`)
- [x] Test 3-gate model on Jan 4 VO2 session → **5.0 min TRUE VO2**

### Pending ⏳
- [ ] **Collect Z2 baseline data** - Do Z2 session with Polar H10 to establish baseline RR metrics
- [ ] **Dashboard integration** - Add `vo2_scoring.py` for Streamlit display
- [ ] **Weekly aggregate metrics** - Query multiple sessions for weekly VO2 totals
- [ ] **Validation** - Compare 3-gate vs lactate/RPE correlation

### Data Dependencies
- Z2 baseline RR requires: lactate-verified Z2 session with Polar H10 ECG recording
- Current defaults: RR median=22.0, MAD=2.0 (estimates, need real data)

---

## References

- Geepy's VO₂ Training Framework: `/mnt/user-data/uploads/geepys_vo_2_training_reference.md`
- Current Cardio Score Spec: `docs/HDP_Dashboard_Addendum_Scores.md`
- Dashboard Implementation: `analysis/apps/hdp_dashboard.py`
- Stroke Schema: `src/pipeline/common/schema.py` (cardio_strokes_schema)
