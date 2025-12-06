# Session Summary - Dec 6, 2025

## Major Accomplishments

### 1. Iron Protocol Optimization ✅
**Problem Identified:** Protocol inconsistency (daily vs EOD switching) caused suboptimal absorption
- Oct 29-Nov 13: Daily dosing triggered hepcidin elevation
- Ferritin gain: Only 1.4 points/week (vs target 3+ points/week)

**Solution Implemented:**
- **New Protocol:** Dual-pathway iron absorption
  - Proferrin (heme): 36mg daily (12mg × 3: morning, afternoon, bedtime)
  - Thorne bisglycinate: 200mg every other day (AM fasted)
  - Vitamin C: 500mg with Thorne dose
- **Expected Results:** 4-5 points/week gain (LabCorp scale)
- **Timeline:** Ferritin >70 by early February 2026 (vs late March on old protocol)

**Support Supplements Optimized:**
- ✅ Keep: Proferrin 3x/day, Thorne EOD, Vitamin C
- ❌ Drop: Citrus bergamot (HDL recovered to 59 mg/dL)
- ❌ Reduce/Drop: Psyllium 12g (timing conflicts with iron)

### 2. Lab Analysis & Assay Variance Discovery ✅
**Quest vs LabCorp Ferritin:**
- LabCorp reads ~25-30 points HIGHER than Quest
- Nov 12 LabCorp: 54 ng/mL
- Nov 22 Quest: 25 ng/mL
- **Not actual depletion** - different assay calibrations

**Actual Progression (Quest scale):**
- Oct 3: 15 ng/mL
- Nov 22: 25 ng/mL
- Gain: +10 points in 50 days = +1.4 points/week (too slow)

**Going Forward:** Use LabCorp exclusively for ferritin tracking (closer location, consistency)

### 3. NOW.md Major Revision ✅
**Critical Corrections:**

**Max HR Status:**
- ❌ OLD: "Max HR <150" constraint
- ✅ NEW: Max HR = 155 bpm (tested mid-Nov) - Gate 2a CLEARED

**Real Limitation Identified:**
- **HR Response Time:** 8-12+ minutes to reach 140 bpm
- Normal: 3-4 minutes to 140 bpm
- **This is the actual training limiter**, not max HR ceiling or ferritin

**PCP Insights Added:**
- Hemoglobin (16.6) matters more than ferritin for performance
- Challenged old ferritin studies (was involved in kinesiology research)
- HCT 51% not concerning with normal Hgb
- Hard NO on IV iron (too risky for athletic optimization)
- Recommended heme iron over bisglycinate ✅

**Training Unlocked:**
- ❌ OLD: "No intensity until ferritin >70"
- ✅ NEW: Modified intervals allowed NOW
- "Peter Intervals": 2 × 10-12 min at 170-180W (power-based)
- Progressive resistance training cleared (not gated by ferritin)

**Critical Experiment Added:**
- Does HR response improve BEFORE ferritin >70?
- If yes → PCP is right (Hgb matters, not ferritin stores)
- If no → Traditional view confirmed
- Timeline: 12-16 weeks will answer definitively

### 4. EPIC PROG-1: Sprint 1 Complete ✅
**Data Foundation - 100% Complete:**

✅ **D1: JEFIT Data Validation**
- 11 months of clean data (Jan 21 - Dec 6, 2025)
- 124 workout days, 1,326 total sets
- 44 unique exercises with consistent naming

✅ **D2: Oura Recovery Data Access**  
- Sleep: `minute_facts` has daily totals (sleep_total_hr, deep, REM)
- HRV: 5-9 readings/day in `minute_facts`, daily avg in `oura_summary`
- Resting HR: `oura_summary.resting_heart_rate_bpm`

✅ **D3: Sleep Data Source Identified**
- Ready to build calculator
- Source: `minute_facts.sleep_total_hr`
- Baseline: 7.5 hours sleep need

✅ **D4: Training Volume Data Validated**
- 20 active exercises with volume metrics
- Frequency: 2-3 sessions/week (reduced from 4/week due to stress)
- Top exercises: Dumbbell Bench Press (7,910 lbs), Squat (6,825 lbs), Calf Raise (6,700 lbs)
- Stress impact visible: Nov 24-Dec 6 volume reduction

**Time Invested:** ~1.5 hours  
**Ready for Sprint 2:** Core algorithm development (A1-A3)

---

## Key Decisions Made

### Iron Protocol
1. **Dual-pathway approach** (heme + non-heme EOD) for maximum absorption
2. **Lab consistency:** LabCorp only for ferritin tracking
3. **Support supps streamlined:** Drop citrus bergamot and psyllium

### Training Approach
1. **Modified intervals NOW** (not waiting for ferritin >70)
2. **HR response time** is the metric to track monthly
3. **Test PCP hypothesis:** Can train effectively with normal Hgb despite low ferritin

### Project Management
1. **Sprint 1 complete:** All data dependencies validated
2. **Next priority:** Build sleep debt calculator (D3, 1 hour)
3. **Then:** Progression rate calculator (A1, 2-3 hours)

---

## Next Session Prep

### Priority 1: Build Sleep Debt Calculator (D3)
**Effort:** 1 hour  
**File:** `analysis/scripts/calculate_sleep_metrics.py`  
**Output:** Rolling 7-day sleep debt for daily readiness

**Implementation:**
```python
def calculate_sleep_debt(sleep_df, baseline_hours=7.5):
    sleep_df['daily_deficit'] = baseline_hours - sleep_df['total_sleep_hours']
    sleep_df['sleep_debt_7d'] = sleep_df['daily_deficit'].rolling(7).sum()
    return sleep_df
```

### Priority 2: Start Progression Rate Calculator (A1)
**Effort:** 2-3 hours  
**Core logic:** Analyze exercise progression trajectories  
**Input:** JEFIT data from D1  
**Output:** Progressive overload recommendations per exercise

### Priority 3: Mid-January Labs
**LabCorp Panel (6 weeks):**
- Ferritin (target: 70+ ng/mL)
- CBC (Hgb, HCT)
- Iron, TIBC

**Performance Test:**
- HR Response: Ramp protocol, measure time to 140 bpm
- Correlation: Did HR response improve independent of ferritin?

---

## Outstanding Questions

1. **HR Response vs Ferritin:** Will HR response improve before ferritin >70? (Tests PCP hypothesis)
2. **Training Progression:** Can maintain/build with modified intervals during iron recovery?
3. **Protocol Stability:** Will dual-pathway iron achieve 4-5 points/week gain?

**Timeline to Answers:** Mid-January 2026 (6-week recheck)

---

## Files Created/Updated

### Created:
- `Session_Summary_Dec6_2025.md` (this file)
- `Analysis_Ideas_Backlog_Addition.md` (6 analysis ideas for future work)

### Updated:
- `NOW.md` - Major revision with PCP insights, max HR correction, training unlocked
- `EPIC_Weekly_Training_Coach.md` - Sprint 1 complete, D4 validation added
- `CompoundMasterLog.xlsx` - Current as of Dec 6, 2025

### Referenced:
- `AllLabsHistory.xlsx` - Quest vs LabCorp variance discovery

---

## Session Stats

**Start Time:** ~21:00 PST  
**End Time:** ~23:30 PST  
**Duration:** ~2.5 hours  
**Major Topics:** Iron protocol, lab analysis, training clearance, EPIC Sprint 1  
**Key Insight:** HR response time is the limiter, not max HR or ferritin (challenges assumptions)  
**Productivity:** High - completed full sprint, major protocol optimization, critical training unlock
