# Health Data Pipeline - Analysis Strategy

**Last Updated:** 2025-11-12  
**Version:** 1.0  
**Status:** Active Development

## Overview

This document guides the utilization of HDP data for analysis, dashboards, and insights. Primary focus: Recovery phase tracking (Oct 2025 - Apr 2026) and longitudinal health optimization.

**Data Available:**
- 433 lab results (2017-2025, 8-year baseline)
- 6,571 workouts with granular splits/strokes
- 3.1M minute-level facts (5+ years)
- 97 lactate readings
- 94 protocol history entries
- Current Parquet tables: 10 (all validated)

---

## Current Priority: Recovery Phase Analysis

### Context
**Timeline:** Oct 4, 2025 (cycle cessation) → Present (Nov 12, 2025)  
**Goal:** Track iron repletion, HDL recovery, cardiovascular capacity restoration

**Key Metrics to Monitor:**
- **Ferritin:** 15 → 70+ ng/mL (target by Week 20-24)
- **HDL:** 31 → 50+ mg/dL (target by Month 6)
- **Max HR:** 117 → 150+ bpm (progressive restoration)
- **Training capacity:** Zone 2 sustainability, interval readiness

**Lab Schedule:**
- Week 6-8 (Mid-Dec): First recheck
- Week 12 (Early Jan): Therapeutic Deca decision point
- Month 4 (Early Feb): Mid-recovery assessment
- Month 6 (Early Apr): Pre-bulk baseline

### Immediate Analysis Questions

**Priority 1: Baseline Establishment**
- Where am I starting from? (Oct 4 - Nov 12 performance)
- What's my current training capacity vs historical?
- Are there early signs of improvement?

**Priority 2: Historical Context**
- How did depletion progress? (Oct 2024 - Oct 2025)
- Correlation: TRT start → ferritin decline → HR limitation
- Impact: Blood donations → performance collapse
- Timeline: Compound cycle → lipid crash

**Priority 3: Trajectory Monitoring**
- Is max HR trending up week-over-week?
- Is Zone 2 power improving?
- Are lactate readings showing aerobic capacity restoration?

---

## Tool Selection Framework

### Analysis Approach Matrix

| Approach | Use Case | Tool | Output | Time to Result |
|----------|----------|------|--------|----------------|
| **A: Quick Queries** | Exploration, one-off questions | DuckDB | Terminal output | Minutes |
| **B: Analysis Scripts** | Reproducible reports | Python + pandas | Markdown reports | 30-60 mins |
| **C: Dashboards** | Ongoing monitoring | Streamlit/Plotly | Interactive UI | Hours to build |
| **D: Automated Reports** | Weekly summaries | Jupyter + papermill | PDF/HTML | Setup once, run weekly |

### Recommended Workflow

**Phase 1 (Now - Week 4):** Quick iteration with Approach A
- Build understanding of data patterns
- Answer immediate questions
- Validate hypotheses

**Phase 2 (Week 4-8):** Transition to Approach B
- Create weekly recovery report script
- Track metrics against targets
- Document progress

**Phase 3 (Week 8+):** Add Approach C dashboard
- Interactive recovery monitoring
- Real-time training capacity assessment
- Protocol adjustment decision support

**Phase 4 (Month 4+):** Implement Approach D
- Automated weekly reports
- Historical comparison overlays
- Trend analysis with projections

---

## Analysis Catalog

### Planned Analyses

#### 1. Recovery Baseline Report
**Status:** Not Started  
**Priority:** Immediate (Week 1)  
**Questions:**
- What was my avg/max HR per workout Oct 4 - Nov 12?
- How does this compare to May-Aug 2024 (pre-depletion peak)?
- What's my current Zone 2 power vs historical?
- Any early signs of improvement?

**Data Sources:** workouts, cardio_splits, minute_facts, lactate  
**Output:** Markdown report with summary stats, trend charts  
**Estimated Time:** 30 mins to first version

---

#### 2. Historical Depletion Timeline
**Status:** Not Started  
**Priority:** Week 1-2  
**Questions:**
- Visualize: Lab results (ferritin, Hgb, HCT) vs workout performance vs protocol changes
- Identify: Key inflection points (TRT start, blood donations, cycle start)
- Understand: Rate of decline, correlation strength

**Data Sources:** labs, workouts, protocol_history  
**Output:** Multi-panel time series visualization  
**Estimated Time:** 1-2 hours (complex alignment)

---

#### 3. Weekly Recovery Dashboard
**Status:** Not Started  
**Priority:** Week 2-3  
**Questions:**
- This week vs last week: Max HR, Zone 2 power, subjective effort
- Trend lines: Am I improving on trajectory?
- Alerts: Any concerning patterns?

**Data Sources:** workouts, cardio_splits, lactate  
**Output:** Streamlit dashboard (run locally)  
**Estimated Time:** 2-3 hours to build

---

#### 4. Training Capacity Index
**Status:** Not Started  
**Priority:** Week 3-4  
**Questions:**
- Create composite metric: Max HR + Zone 2 power + lactate @ threshold
- Track recovery percentage toward baseline
- Project: When will I hit key milestones? (145 bpm, 4min intervals, etc.)

**Data Sources:** workouts, cardio_splits, lactate  
**Output:** Single metric + projections  
**Estimated Time:** 1 hour

---

#### 5. Supplement Protocol Effectiveness
**Status:** Not Started  
**Priority:** Month 2+  
**Questions:**
- Iron absorption patterns (labs every 6-8 weeks)
- HDL response to niacin protocol
- Correlation: Supplement compliance → biomarker changes

**Data Sources:** labs, protocol_history  
**Output:** Before/after comparison, trend analysis  
**Estimated Time:** 30 mins per lab cycle

---

#### 6. Lactate Zone Validation
**Status:** Not Started  
**Priority:** Month 3+  
**Questions:**
- Are current Zone 2 efforts actually <2.0 mmol/L?
- How has lactate @ given power changed over recovery?
- When can I return to threshold intervals?

**Data Sources:** lactate, cardio_splits, workouts  
**Output:** Power-lactate curves over time  
**Estimated Time:** 1 hour

---

### Future Analyses (Post-Recovery)

#### 7. Compound Response Profiling
**Status:** Planned  
**Timeline:** Month 6+ (when considering future cycles)  
**Questions:**
- Individual response: HDL, ferritin, performance per compound
- Dose-response curves
- Optimal duration before diminishing returns

**Data Sources:** labs, protocol_history, workouts  
**Output:** Compound decision matrix

---

#### 8. Periodization Optimization
**Status:** Planned  
**Timeline:** Post-recovery  
**Questions:**
- Optimal training load for iron maintenance
- Recovery metrics (HRV, sleep) vs training volume
- Injury risk patterns

**Data Sources:** workouts, oura_summary, labs  
**Output:** Periodization recommendations

---

#### 9. Biomarker Correlation Matrix
**Status:** Planned  
**Timeline:** Post-recovery  
**Questions:**
- Which biomarkers predict performance changes?
- Lead indicators for declining capacity
- Optimal testing frequency

**Data Sources:** labs, workouts, protocol_history  
**Output:** Correlation heatmap + predictive model

---

## Code Organization

### Proposed Structure
```
analysis/
├── queries/
│   ├── recovery_baseline.sql      # Quick DuckDB queries
│   ├── historical_timeline.sql
│   └── weekly_metrics.sql
│
├── scripts/
│   ├── recovery_report.py         # Standalone analysis scripts
│   ├── depletion_timeline.py
│   └── training_capacity_index.py
│
├── dashboards/
│   ├── recovery_monitor.py        # Streamlit apps
│   └── training_capacity.py
│
├── notebooks/
│   ├── weekly_report_template.ipynb  # Jupyter templates
│   └── exploration.ipynb
│
└── utils/
    ├── data_loader.py             # Reusable functions
    ├── plotting.py
    └── metrics.py
```

### Workflow
1. Start in `queries/` for exploration
2. Promote to `scripts/` when repeatable
3. Build `dashboards/` for ongoing use
4. Use `notebooks/` for deep dives

---

## Dashboard Design Principles

### Recovery Phase Dashboard (Priority)

**Layout:**
```
┌─────────────────────────────────────────────┐
│  Recovery Progress: Day 39 of ~168         │
│  [====================----------] 23%       │
└─────────────────────────────────────────────┘

┌──────────────┬──────────────┬──────────────┐
│  Max HR      │  Zone 2 Pwr  │  Last Lactate│
│  120 bpm     │  155W        │  1.8 mmol/L  │
│  ↑ +3 vs LW  │  ↑ +5W vs LW │  (Nov 8)     │
└──────────────┴──────────────┴──────────────┘

┌─────────────────────────────────────────────┐
│  Max HR Trend (8 weeks)                     │
│  [Line chart: Week → Max HR]                │
│  Target: 145 bpm by Week 12                 │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  Next Lab: Dec 15 (4 weeks)                 │
│  Expected: Ferritin 35-50, HDL 42-47       │
└─────────────────────────────────────────────┘
```

**Features:**
- Simple, glanceable metrics
- Week-over-week comparisons (primary feedback)
- Trend lines with targets
- Lab schedule reminders
- Alert thresholds (regression warnings)

**Update Frequency:** After each workout (automated)

---

## Data Quality Checks

Before each analysis, verify:

### Completeness
```sql
-- Check for gaps in workout data
SELECT 
    date_trunc('week', date_utc) as week,
    COUNT(*) as workout_count
FROM workouts
WHERE date_utc >= '2025-10-04'
GROUP BY week
ORDER BY week;
```

### Consistency
```sql
-- Verify max HR isn't outlier/error
SELECT 
    workout_id,
    workout_date,
    max_hr,
    average_hr
FROM workouts
WHERE date_utc >= '2025-10-04'
    AND (max_hr > 180 OR max_hr < 60)  -- Flag suspicious values
ORDER BY workout_date;
```

### Alignment
```sql
-- Check protocol_history covers workout periods
SELECT 
    w.workout_date,
    w.workout_id,
    COUNT(p.protocol_id) as protocol_count
FROM workouts w
LEFT JOIN protocol_history p 
    ON w.workout_date BETWEEN p.start_date AND COALESCE(p.end_date, CURRENT_DATE)
WHERE w.date_utc >= '2025-10-04'
GROUP BY w.workout_date, w.workout_id
HAVING COUNT(p.protocol_id) = 0;  -- Find workouts without protocol coverage
```

---

## Iteration Log

### Session 1: 2025-11-12
**Goals:**
- Establish hybrid analysis strategy
- Create this strategy document
- Begin Recovery Baseline Report (Analysis #1)

**Completed:**
- ✅ Strategy framework defined
- ✅ Analysis catalog initialized
- ⏳ Recovery baseline query (in progress)

**Next Session:**
- Complete baseline report
- Review output, refine queries
- Start historical timeline visualization

---

## Notes & Learnings

### What Works
- (To be filled as we iterate)

### Challenges Encountered
- (To be filled as we iterate)

### Quick Wins
- (To be filled as we iterate)

### Workflow Refinements
- (To be filled as we iterate)

---

## References

**Related Documentation:**
- [Schema.md](docs/Schema.md) - Table structures
- [StorageAndQuery.md](docs/StorageAndQuery.md) - DuckDB patterns
- [Iron_Depletion_Recovery_Performance_Plan.md](Iron_Depletion_Recovery_Performance_Plan.md) - Recovery protocol

**External Resources:**
- DuckDB SQL: https://duckdb.org/docs/sql/introduction
- Streamlit: https://docs.streamlit.io/
- Plotly: https://plotly.com/python/

---

**Maintained By:** Peter Kahaian  
**Review Cycle:** Weekly during recovery phase  
**Status:** Living document - update after each analysis session
