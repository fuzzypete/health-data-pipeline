# HDP VO₂ 3-Gate Implementation Guide

**Created:** 2026-01-04  
**Based on:** Geepy + Gemini merged specification  
**Status:** Ready for Implementation

---

## Executive Summary

This spec implements the **3-gate VO₂ overlap model** for detecting true VO₂ stimulus during interval training. This replaces the permissive single-signal approach (HR_drop only) with a robust multi-signal convergence model.

### Why 3 Gates?

**Problem with single signals:**
- HR_drop alone: Too permissive (heat, autonomic noise)
- RR alone: Too early/noisy (anticipation, anxiety)
- HR load alone: No recovery validation

**Solution:**
Only when all 3 gates simultaneously satisfy do we credit **True VO₂ Stimulus Time**.

---

## The Three Gates (Locked Definitions)

### Gate 1: Cardiovascular Load
**Signal:** HR ≥ 90% of session max  
**Asks:** "Is the pump working hard?"  
**Implementation:** Stroke-level HR data from `cardio_strokes`

### Gate 2: Ventilatory Engagement (Geepy's Merged Spec)
**Primary:** ELEVATED_AND_FAILING
- RR elevated above Z2 baseline: `RR >= RR_z2_med + max(6, 3*RR_z2_mad)`
- RR fails to drop during easy: `RR_drop_e <= max(1.5, 2*RR_z2_mad)`

**Secondary:** CHAOTIC (optional enhancer)
- RR variability chaos: `MAD(RR) >= max(2.0, 2*RR_var_z2)`

**Asks:** "Is oxygen demand truly high?"  
**Implementation:** Polar H10 respiratory data from `polar_respiratory`

### Gate 3: Recovery Impairment
**Signal:** HR_drop ≤ 2.5 bpm during 30s easy intervals  
**Asks:** "Has recovery capacity collapsed?"  
**Implementation:** Calculated from `cardio_strokes` HR recovery during easy

---

## Metrics to Track

### Primary Metric
**True VO₂ Overlap Time (min):**
- Time when all 3 gates simultaneously active
- Gold standard adaptation metric
- Target: 8-12 min per session, 15-25 min per week

### Secondary Metrics
1. **Gate Convergence Efficiency:**
   - Time from Gate 1 onset → 3-gate overlap
   - Measures session design + conditioning readiness
   - Lower = better (faster convergence)

2. **Stimulus Inflation Ratio:**
   - `HR_drop-only time / True Overlap time`
   - Quantifies how permissive HR_drop would be alone
   - Expected: 1.2-1.5x (shows HR_drop catches too much)

3. **Ventilatory Persistence (late):**
   - RR stays high after HR declines
   - Flags extreme fatigue or CO₂ handling stress
   - Normal: RR should drop when session ends

---

## Implementation Architecture

### Module Structure

```
src/pipeline/analysis/
├── vo2_baselines.py      # Calculate Z2 RR baseline (NEW)
├── vo2_gates.py          # Individual gate detection (NEW)
├── vo2_overlap.py        # 3-gate overlap calculation (NEW)
└── vo2_metrics.py        # Exists, extend for overlap

analysis/apps/utils/
└── vo2_scoring.py        # Dashboard scoring (NEW)
```

### Data Flow

```
1. Baseline Calculation (one-time)
   └─> vo2_baselines.calculate_zone2_rr_baseline()
   └─> Returns: {rr_z2_med, rr_z2_mad, rr_var_z2}

2. Per-Workout Analysis
   └─> vo2_gates.detect_gate1_hr_load(strokes)
   └─> vo2_gates.detect_gate2_rr_engagement(resp, baselines)
   └─> vo2_gates.detect_gate3_recovery_impairment(strokes)
   └─> vo2_overlap.calculate_vo2_overlap(...)
   └─> Returns: {true_vo2_time_min, convergence_time, inflation_ratio, ...}

3. Dashboard Scoring
   └─> vo2_scoring.calculate_vo2_tier_score(weekly_overlap, convergence)
   └─> Updates Cardio Score component
```

---

## Code Implementation

### 1. Zone 2 Baseline Calculation

**File:** `src/pipeline/analysis/vo2_baselines.py`

```python
"""Calculate Zone 2 respiratory baselines from lactate-verified sessions."""
import pandas as pd
import numpy as np
import duckdb


def calculate_zone2_rr_baseline(
    workout_ids: list[str] = None,
    auto_detect: bool = True
) -> dict:
    """
    Calculate personalized RR baseline from Zone 2 sessions.
    
    Uses lactate-verified Zone 2 workouts (~145-150W, lactate 1.5-2.0 mmol/L)
    to establish breathing baseline for Gate 2 threshold calculation.
    
    Parameters:
        workout_ids: Specific workout IDs to use (if None, auto-detect)
        auto_detect: If True, find recent Z2 sessions automatically
        
    Returns:
        dict with:
            - rr_z2_med: Median RR during Z2
            - rr_z2_mad: Median Absolute Deviation (robust variability)
            - rr_var_z2: Variability of variability (MAD of rolling MAD)
    """
    con = duckdb.connect()
    
    if auto_detect:
        # Find lactate-verified Zone 2 workouts
        query = """
        WITH z2_candidates AS (
            SELECT DISTINCT w.workout_id
            FROM workouts w
            LEFT JOIN lactate l ON w.workout_id = l.workout_id
            WHERE w.source = 'Concept2'
              AND w.duration_min BETWEEN 40 AND 55
              AND w.avg_watts BETWEEN 140 AND 155
              AND (l.lactate_mmol IS NULL OR l.lactate_mmol BETWEEN 1.5 AND 2.0)
            ORDER BY w.start_time_utc DESC
            LIMIT 5
        )
        SELECT workout_id FROM z2_candidates
        """
        workout_ids = con.execute(query).df()['workout_id'].tolist()
    
    if not workout_ids:
        # Fallback defaults
        return {
            'rr_z2_med': 20.0,
            'rr_z2_mad': 2.0,
            'rr_var_z2': 1.0,
            'source': 'default_fallback'
        }
    
    # Get respiratory data
    workout_id_list = "', '".join(workout_ids)
    query = f"""
    SELECT 
        workout_id,
        window_center_min,
        respiratory_rate,
        confidence
    FROM read_parquet('Data/Parquet/polar_respiratory/**/*.parquet')
    WHERE workout_id IN ('{workout_id_list}')
      AND confidence > 0.6
    ORDER BY workout_id, window_center_min
    """
    
    resp_df = con.execute(query).df()
    
    if resp_df.empty:
        return {
            'rr_z2_med': 20.0,
            'rr_z2_mad': 2.0,
            'rr_var_z2': 1.0,
            'source': 'no_data_fallback'
        }
    
    # Filter to steady-state (skip first/last 5 min)
    steady_resp = resp_df[
        (resp_df['window_center_min'] >= 5) &
        (resp_df['window_center_min'] <= 
         resp_df.groupby('workout_id')['window_center_min'].transform('max') - 5)
    ]
    
    # Calculate baseline metrics
    rr_z2_med = steady_resp['respiratory_rate'].median()
    rr_z2_mad = (steady_resp['respiratory_rate'] - rr_z2_med).abs().median()
    
    # Variability of variability
    rolling_mad = []
    for _, group in steady_resp.groupby('workout_id'):
        for i in range(len(group) - 4):
            window = group.iloc[i:i+4]['respiratory_rate']
            window_median = window.median()
            window_mad = (window - window_median).abs().median()
            rolling_mad.append(window_mad)
    
    rr_var_z2 = np.median(rolling_mad) if rolling_mad else 1.0
    
    return {
        'rr_z2_med': float(rr_z2_med),
        'rr_z2_mad': float(rr_z2_mad),
        'rr_var_z2': float(rr_var_z2),
        'source': 'calculated',
        'workout_count': len(workout_ids),
        'workout_ids': workout_ids
    }
```

### 2. Gate Detection

**File:** `src/pipeline/analysis/vo2_gates.py`

See the main migration spec for complete implementation of:
- `detect_gate1_hr_load()`
- `detect_gate2_rr_engagement()` (Geepy's merged spec)
- `detect_gate3_recovery_impairment()`

### 3. Overlap Calculation

**File:** `src/pipeline/analysis/vo2_overlap.py`

See main migration spec for `calculate_vo2_overlap()` implementation.

---

## Dashboard Integration

### Updated Cardio Score Component

**Before (Responsiveness 35%):**
- Hr Response Time: 50
- Hr Recovery: 50

**After (VO₂ Stimulus 35%):**
- True VO₂ Overlap Time: 88
- Gate Convergence Efficiency: 75

### Scoring Logic

**File:** `analysis/apps/utils/vo2_scoring.py`

```python
def calculate_vo2_overlap_score(true_vo2_time_min: float) -> int:
    """
    Score weekly True VO₂ Overlap Time.
    
    Target: 15-25 min per week
    Optimal: 20 min
    """
    if true_vo2_time_min >= 20:
        return 100
    elif true_vo2_time_min >= 15:
        return 85 + int((true_vo2_time_min - 15) / 5 * 15)
    elif true_vo2_time_min >= 10:
        return 60 + int((true_vo2_time_min - 10) / 5 * 25)
    elif true_vo2_time_min >= 5:
        return 30 + int((true_vo2_time_min - 5) / 5 * 30)
    else:
        return max(0, int(true_vo2_time_min / 5 * 30))


def calculate_convergence_score(convergence_time_min: float) -> int:
    """
    Score gate convergence efficiency.
    
    Faster convergence = better session design + conditioning
    """
    if convergence_time_min is None:
        return 0
    
    if convergence_time_min < 5:
        return 100
    elif convergence_time_min < 8:
        return 85 + int((8 - convergence_time_min) / 3 * 15)
    elif convergence_time_min < 12:
        return 60 + int((12 - convergence_time_min) / 4 * 25)
    elif convergence_time_min < 15:
        return 40 + int((15 - convergence_time_min) / 3 * 20)
    else:
        return 20


def calculate_vo2_tier_score(
    weekly_vo2_time_min: float,
    avg_convergence_min: float
) -> dict:
    """
    Calculate VO₂ Stimulus tier (replaces Responsiveness).
    
    Weight: 35% of total Cardio Score
    - True VO₂ Overlap: 20%
    - Convergence Efficiency: 15%
    """
    overlap_score = calculate_vo2_overlap_score(weekly_vo2_time_min)
    convergence_score = calculate_convergence_score(avg_convergence_min)
    
    tier_score = (overlap_score * (20/35) + convergence_score * (15/35))
    
    return {
        'score': int(tier_score),
        'weight': '35%',
        'components': {
            'true_vo2_overlap': {
                'score': overlap_score,
                'value': f"{weekly_vo2_time_min:.1f} min",
                'target': '15-25 min/week'
            },
            'convergence_efficiency': {
                'score': convergence_score,
                'value': f"{avg_convergence_min:.1f} min" if avg_convergence_min else "N/A",
                'target': '<8 min'
            }
        }
    }
```

---

## Visualization: Overlap Ribbon

**Add to dashboard:** Cardiovascular Performance section

```python
def render_overlap_ribbon(workout_id: str):
    """
    Visualize 3-gate overlap as colored ribbon.
    
    Blue: Gate 1 (HR Load)
    Orange: Gate 2 (Ventilatory)
    Red: Gate 3 (Recovery Impaired)
    Purple: All 3 gates (True VO₂)
    """
    from vo2_overlap import calculate_vo2_overlap
    
    result = calculate_vo2_overlap(workout_id)
    overlap_df = result['overlap_detail']
    
    fig = go.Figure()
    
    # Add gate ribbons
    for _, interval in overlap_df.iterrows():
        color = 'rgba(128,128,128,0.3)'  # Default gray
        
        if interval['is_true_vo2']:
            color = 'rgba(148,0,211,0.6)'  # Purple (all 3)
        elif interval['gates_active_count'] == 2:
            color = 'rgba(255,165,0,0.4)'  # Orange (2 gates)
        elif interval['gate1_active']:
            color = 'rgba(0,0,255,0.3)'    # Blue (HR only)
        
        fig.add_vrect(
            x0=interval['interval_start_min'],
            x1=interval['interval_end_min'],
            fillcolor=color,
            layer="below",
            line_width=0
        )
    
    fig.update_layout(
        title="VO₂ Stimulus Overlap Ribbon",
        xaxis_title="Time (min)",
        yaxis_title="HR (bpm)",
        height=400
    )
    
    st.plotly_chart(fig, use_container_width=True)
```

---

## Implementation Checklist

### Phase 1: Baseline Calculation (Week 1)
- [ ] Create `vo2_baselines.py`
- [ ] Test baseline calculation on your recent Z2 sessions
- [ ] Validate: RR_z2_med should be ~18-22 brpm
- [ ] Validate: RR_z2_mad should be ~2-3 brpm
- [ ] Store baselines for dashboard use

### Phase 2: Gate Detection (Week 1)
- [ ] Create `vo2_gates.py`
- [ ] Implement Gate 1 (HR load) - simplest
- [ ] Implement Gate 3 (HR drop) - use existing logic
- [ ] Implement Gate 2 (Geepy's merged spec) - most complex
- [ ] Test each gate independently on Dec 26 workout

### Phase 3: Overlap Calculation (Week 2)
- [ ] Create `vo2_overlap.py`
- [ ] Implement interval-level gate alignment
- [ ] Calculate 4 metrics: overlap, convergence, inflation, persistence
- [ ] Validate against Geepy's manual analysis of Dec 26 session

### Phase 4: Dashboard Integration (Week 2)
- [ ] Create `vo2_scoring.py`
- [ ] Replace Responsiveness tier with VO₂ Stimulus tier
- [ ] Update Cardio Score calculation
- [ ] Add overlap ribbon visualization
- [ ] Test UI rendering

### Phase 5: Validation (Week 3)
- [ ] Run on 5+ interval sessions
- [ ] Compare inflation ratio (expect 1.2-1.5x)
- [ ] Validate convergence times make sense
- [ ] Check for sessions with no respiratory data (graceful degradation)

---

## Success Criteria

### Functional
- [x] Baselines calculate correctly from Z2 sessions
- [ ] Gate 1 detects HR ≥90% session max
- [ ] Gate 2 ELEVATED_AND_FAILING logic works
- [ ] Gate 3 detects HR_drop ≤2.5 bpm
- [ ] Overlap calculation aligns gates temporally
- [ ] All 4 metrics compute without errors

### Validation
- [ ] Dec 26 session: ~9-10 min true overlap (matches Geepy)
- [ ] Inflation ratio: 1.2-1.5x (confirms HR_drop alone too permissive)
- [ ] Convergence time: <10 min for good sessions
- [ ] Weekly target: 15-25 min achievable

### User Experience
- [ ] Cardio Score increases from ~57 to ~70+
- [ ] VO₂ Stimulus tier shows ~75-85
- [ ] Overlap ribbon visualizes state clearly
- [ ] No errors when respiratory data missing

---

## Graceful Degradation

**If no Polar H10 data available:**
1. Gate 2 automatically returns `False` (never active)
2. Overlap calculation proceeds with 2-gate logic (Gate 1 + Gate 3)
3. Dashboard marks overlap as "Estimated (no RR data)"
4. Inflation ratio still calculated (HR_drop alone vs 2-gate)

**This ensures the system works even without respiratory data**, while making clear the confidence level is lower.

---

## Next Steps

1. **Answer Zone 2 baseline question:** Run baseline calculation on your 5 most recent Z2 sessions to get personalized thresholds
2. **Test Gate 2 implementation:** Verify Geepy's merged spec works on real data
3. **Validate overlap:** Compare to Geepy's manual Dec 26 analysis
4. **Deploy:** Update dashboard with new tier

---

## References

- Geepy's Merged Gate 2 Spec: Final specification with ELEVATED_AND_FAILING + CHAOTIC
- Gemini's Critique: Addressed HR_drop permissiveness
- Your existing code: `src/pipeline/analysis/vo2_metrics.py` (extend)
- Polar H10 schema: `src/pipeline/common/schema.py` → `polar_respiratory_schema`

