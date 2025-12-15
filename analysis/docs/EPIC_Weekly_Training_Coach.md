# EPIC: Weekly Training Progression Coach

**Status:** 🚀 Active  
**Priority:** P0 (Core Feature)  
**Owner:** Peter  
**Timeline:** Dec 2025 - Jan 2026

## Vision

Replace generic fitness app recommendations with a personalized, data-driven training coach that:
- Knows my complete training history
- Understands my recovery state
- Adjusts for life stress and compound protocols
- Provides specific, actionable weekly targets
- Motivates with progress context

**Phase 1:** Strength training only (JEFIT-based)  
**Phase 2:** Full training coach (cardio + strength integration)

---

## Phase 1: Strength Training Coach

### Success Criteria
- [ ] Generates weekly training plan every Sunday
- [ ] Includes specific lift targets (exercise, sets, reps, weight)
- [ ] Adjusts volume based on recovery metrics
- [ ] Shows progression context (current vs recent vs peak)
- [ ] Prevents overtraining with safety warnings
- [ ] Takes 5min to review, provides week of guidance

---

## Dependency Map

### Data Dependencies (D-Series)

#### D1: JEFIT Data Validation ✅ COMPLETE
**Status:** 🟢 Validated  
**Priority:** P0  
**Effort:** 30 mins  
**Blockers:** None

**Tasks:**
- [x] Query JEFIT table in DuckDB
- [x] Verify date range coverage
- [x] Check exercise naming consistency
- [x] Validate sets/reps/weight columns
- [x] Identify any data quality issues

**Output:** Data quality report

**Findings:**
- Date range: Jan 21, 2025 → Dec 6, 2025 (11 months, 124 workout days)
- 44 unique exercises, 1,326 total sets
- Exercise naming: Clean and consistent ✅
- Recent data: Through yesterday, 28 active exercises
- Data quality: Excellent, no blockers identified
- Note: Stress-induced training pattern visible (some exercises dropped off)

**SQL to run:**
```sql
-- Check JEFIT data availability
SELECT 
    MIN(workout_date) as earliest,
    MAX(workout_date) as latest,
    COUNT(DISTINCT workout_date) as workout_days,
    COUNT(DISTINCT exercise_name) as unique_exercises,
    COUNT(*) as total_sets
FROM lake.jefit_logs;

-- Check recent data (last 12 weeks)
SELECT 
    exercise_name,
    COUNT(*) as sets,
    AVG(weight) as avg_weight,
    MAX(workout_date) as last_performed
FROM lake.jefit_logs
WHERE workout_date >= CURRENT_DATE - INTERVAL '12 weeks'
GROUP BY exercise_name
ORDER BY last_performed DESC;
```

---

#### D2: Oura Recovery Data Access ✅ COMPLETE
**Status:** 🟢 Available  
**Priority:** P1  
**Effort:** 15 mins  
**Blockers:** None

**Tasks:**
- [x] Query Oura recovery score availability
- [x] Verify last 30 days coverage
- [x] Document where it lives (minute_facts vs oura_summary)

**Findings:**
- **Sleep data** in `minute_facts`: daily totals for sleep_total_hr, sleep_deep_hr, sleep_rem_hr ✅
- **HRV data** in both `minute_facts` (5-9 readings/day) and `oura_summary` (daily avg) ✅
- **Resting HR** in `oura_summary`: resting_heart_rate_bpm ✅
- **Coverage:** Last 30+ days confirmed ✅
- **Data quality:** Good, some concerning sleep patterns visible (3.88-8.55 hr range)

**Note:** Activity metrics in oura_summary mostly NULL - not critical for EPIC.

---

#### D3: Sleep Debt Calculator ✅ COMPLETE
**Status:** 🟢 Implemented
**Priority:** P1
**Effort:** 1 hour
**Blockers:** None

**Tasks:**
- [x] Define sleep debt formula (baseline - actual, rolling 7-day)
- [x] Query sleep data from minute_facts
- [x] Create calculation function
- [x] Validate against known high/low sleep periods

**Implementation:** `analysis/scripts/calculate_sleep_metrics.py`

**Usage:**
```bash
make sleep.metrics                    # Default: 30 days, 7.5hr baseline
python analysis/scripts/calculate_sleep_metrics.py --days 14 --baseline 8.0
```

**Output:** `analysis/outputs/sleep_metrics_YYYYMMDD.csv`

**Features:**
- Rolling 7-day sleep debt calculation
- Recovery state classification (OPTIMAL/MODERATE/POOR)
- Sleep efficiency tracking
- HRV integration for recovery assessment
- Validated against Nov 2025 stress period (correctly flagged 17 POOR days)

---

#### D4: Training Volume Calculator ✅ COMPLETE
**Status:** 🟢 Data validated  
**Priority:** P1  
**Effort:** 15 mins (validation complete)  
**Blockers:** None

**Tasks:**
- [x] Define training volume metric (sets × reps × weight)
- [x] Calculate recent volume (last 4 weeks by exercise)
- [x] Identify training frequency (sessions/week)
- [x] Validate data availability and quality

**Findings:**
- **Volume data:** 20 active exercises with complete metrics ✅
- **Frequency:** 2-3 sessions/week current (reduced from 4/week peak)
- **Recent pattern:** Stress-induced reduction visible (Nov 24-Dec 6)
- **Top exercises by 4wk volume:**
  - Dumbbell Bench Press: 7,910 lbs (18 sets, 70 lbs avg)
  - Dumbbell Squat: 6,825 lbs (9 sets, 98 lbs avg)  
  - Dumbbell Calf Raise: 6,700 lbs (10 sets, 38 lbs avg)
- **Data quality:** ✅ Excellent - through Dec 6, 2025

**SQL Validation:**
```sql
SELECT 
    exercise_name,
    COUNT(*) as total_sets,
    SUM(actual_reps * weight_lbs) as volume,
    AVG(weight_lbs) as avg_weight
FROM lake.resistance_sets
WHERE workout_start_utc >= CURRENT_DATE - INTERVAL '4 weeks'
GROUP BY exercise_name
ORDER BY volume DESC;
```

**Next:** Build calculator in Sprint 2 (A1-A3)

---
    
    volume = recent.groupby('exercise_category').apply(
        lambda x: (x['sets'] * x['reps'] * x['weight']).sum()
    )
    
    return volume
```

---

### Analysis Dependencies (A-Series)

#### A1: Progression Rate Calculator 🟡 CORE LOGIC
**Status:** 🔴 Blocked - needs implementation  
**Priority:** P0  
**Effort:** 2-3 hours  
**Blockers:** D1 (need JEFIT data)

**Tasks:**
- [ ] Define progression algorithm (linear? exponential?)
- [ ] Calculate per-lift progression rates (last 4, 8, 12 weeks)
- [ ] Identify stagnant lifts (no progress in 4+ weeks)
- [ ] Calculate recommended next targets
- [ ] Include safety bounds (max 5-10lb increase, conservative)

**Key Logic:**
```python
def calculate_progression(lift_history_df, conservative=True):
    """
    Recommend next workout target based on history.
    
    Rules:
    - If last 3 sessions successful: +5-10 lbs
    - If last session failed: maintain weight
    - If stagnant >4 weeks: reduce weight 10%, rebuild
    - Conservative mode: lower increases, more caution
    """
    pass  # Implementation
```

---

#### A2: Recovery-Based Volume Adjustment 🟡 CORE LOGIC
**Status:** 🔴 Blocked - needs implementation  
**Priority:** P0  
**Effort:** 2 hours  
**Blockers:** D2 (Oura), D3 (sleep debt), D4 (volume)

**Tasks:**
- [ ] Define recovery state thresholds (Good/Moderate/Poor)
- [ ] Map recovery state → training mode (Optimal/Maintenance/Deload)
- [ ] Create volume adjustment rules per mode
- [ ] Validate against known high/low stress periods

**Key Logic:**
```python
def determine_training_mode(recovery_score, sleep_debt, recent_volume):
    """
    Assign weekly training mode based on recovery.
    
    Modes:
    - OPTIMAL: High recovery, low sleep debt → progressive overload
    - MAINTENANCE: Moderate recovery → maintain strength
    - DELOAD: Poor recovery, high sleep debt → reduce volume 40%
    
    Returns:
        mode: str
        volume_adjustment: float (multiplier, e.g. 0.6 = 60% volume)
        session_frequency: int (sessions/week)
    """
    pass  # Implementation
```

---

#### A3: Weekly Report Generator 🟡 OUTPUT FORMAT
**Status:** 🔴 Blocked - needs implementation  
**Priority:** P0  
**Effort:** 2-3 hours  
**Blockers:** A1 (progression), A2 (volume adjustment)

**Tasks:**
- [ ] Design report format (see example in previous message)
- [ ] Build markdown template
- [ ] Populate with calculated targets
- [ ] Add motivational context (progress, peak comparisons)
- [ ] Include safety warnings and notes

---

### Supporting Analyses (S-Series) - Lower Priority

#### S1: Exercise Categorization 🟢 OPTIONAL
**Status:** Nice-to-have  
**Priority:** P2  
**Effort:** 30 mins  

**Tasks:**
- [ ] Map JEFIT exercises to categories (Upper/Lower, Push/Pull/Legs)
- [ ] Identify exercise substitutions (e.g., Bench variants)

---

#### S2: Historical Peak Tracking 🟢 OPTIONAL
**Status:** Nice-to-have  
**Priority:** P2  
**Effort:** 1 hour  

**Tasks:**
- [ ] Calculate all-time peak performance per lift
- [ ] Calculate recent peak (last 6 months)
- [ ] Show current as % of peak

---

## Execution Plan

### Sprint 1: Data Foundation (Week 1)
**Goal:** Validate all data dependencies

**Tasks:**
1. ✅ D1: JEFIT data validation (30 mins) ⚡ START HERE
2. ✅ D2: Oura recovery check (15 mins)
3. ✅ D3: Sleep debt calculator (1 hour)
4. ✅ D4: Training volume calculator (1 hour)

**Total:** ~3 hours  
**Deliverable:** Data quality report + basic calculators

---

### Sprint 2: Core Logic (Week 2)
**Goal:** Build progression and adjustment algorithms

**Tasks:**
1. ✅ A1: Progression rate calculator (2-3 hours)
2. ✅ A2: Recovery-based volume adjustment (2 hours)
3. ✅ Test with sample data (1 hour)

**Total:** ~5-6 hours  
**Deliverable:** Working progression logic

---

### Sprint 3: Report Generation (Week 3)
**Goal:** Generate first weekly report

**Tasks:**
1. ✅ A3: Weekly report generator (2-3 hours)
2. ✅ Generate first report, review format (30 mins)
3. ✅ Iterate on output (1 hour)

**Total:** ~4 hours  
**Deliverable:** First automated weekly training plan

---

### Sprint 4: Automation & Polish (Week 4)
**Goal:** Make it run automatically

**Tasks:**
1. ✅ Add to Makefile: `make training.weekly`
2. ✅ Set up weekly reminder (Sunday)
3. ✅ Add error handling
4. ✅ Document usage

**Total:** ~2 hours  
**Deliverable:** Production-ready weekly coach

---

## Phase 2: Full Training Coach (Future)

### Additional Dependencies

#### D5: Concept2 Power Progression
- Zone 2 watt targets by erg type (bike/rowing)
- Historical power curve analysis
- Lactate threshold tracking

#### D6: VO2 Max Session Design
- Current max HR and target zones
- Interval structure optimization
- Progressive interval difficulty

#### A4: Integrated Weekly Planning
- Balance cardio + strength volume
- Recovery allocation across modalities
- Prevent cardio interference with strength gains

**Timeline:** After Phase 1 proven successful (Feb 2026+)

---

## Risk Mitigation

### Risk 1: JEFIT Data Quality Issues
**Mitigation:** Manual review of recent 12 weeks, clean up naming inconsistencies

### Risk 2: Overly Conservative Recommendations
**Mitigation:** Include aggressive mode toggle, user can override

### Risk 3: Time Commitment Too High
**Mitigation:** Prioritize MVP (basic progression only), add features iteratively

### Risk 4: Algorithm Doesn't Match Feel
**Mitigation:** Include manual override notes, iterate based on actual usage

---

## Success Metrics

### Week 1 Success
- [ ] Can query all needed data from DuckDB
- [ ] Sleep debt and volume calculations working
- [ ] No data quality blockers identified

### Week 2 Success
- [ ] Progression calculator produces sensible targets
- [ ] Recovery adjustment logic matches intuition
- [ ] Tested on 4+ sample weeks successfully

### Week 3 Success
- [ ] First weekly report generated
- [ ] Report takes <5min to review
- [ ] Targets feel actionable and motivating

### Week 4 Success
- [ ] Command `make training.weekly` produces report
- [ ] Using report to guide actual training
- [ ] Prefer this over JEFIT coach feature

---

## Next Immediate Action

**🎉 Sprint 1 COMPLETE + D3 Built**

**Status:** All data dependencies complete
- D1: JEFIT Data ✅
- D2: Oura Recovery Data ✅
- D3: Sleep Debt Calculator ✅ (implemented Dec 14, 2025)
- D4: Training Volume Data ✅

**Current:** 7.1hr sleep debt, POOR recovery state - proceed with caution on training load recommendations.

**Ready for Sprint 2: Core Algorithms**

**Next up: A1 - Progression Rate Calculator**
- Effort: 2-3 hours
- Core algorithm for weekly recommendations
- Analyzes exercise progression trajectories
- Uses JEFIT data to recommend next workout targets

**After A1: A2 - Recovery-Based Volume Adjustment**
- Integrates D3 sleep debt with training recommendations
- Maps recovery state → training mode (Optimal/Maintenance/Deload)

---

**Last Updated:** Dec 14, 2025
**Sprint:** 2 of 4 - Core Algorithms (starting)
**Time Invested:** ~2.5 hours
**Next Task:** A1 Progression Rate Calculator (2-3 hours)
