## Analysis Ideas Backlog

**Purpose:** Capture analysis ideas as they emerge, then triage into the active catalog when ready.

**Status Key:**
- 💡 New idea - needs scoping
- 🔍 Scoped - ready for prioritization
- 📋 Prioritized - ready to execute
- ✅ Completed - moved to main catalog

---

### Current Ideas (As of Dec 4, 2025)

#### BP-1: Blood Pressure Correlation Analysis
**Status:** 💡 New idea  
**Priority:** TBD  
**Questions:**
- What changed between spring/summer BP peak and current lower readings?
- Compound correlations: TRT dose, DHT derivatives, ancillaries?
- Lifestyle factors: training volume, sleep quality, stress periods?
- Temporal patterns: morning vs evening, day-to-day volatility?

**Data Sources:** `minute_facts` (BP readings), `protocol_history`, `workouts`, Oura sleep  
**Output:** Timeline visualization with compound overlays, correlation matrix  
**Estimated Time:** 2-3 hours  
**Next Steps:** 
1. Validate BP data completeness in minute_facts
2. Query monthly averages to spot spring/summer spike
3. Identify protocol changes during that period
4. Build correlation script

---

#### SLP-1: Sleep → Next-Day Performance
**Status:** 💡 New idea  
**Priority:** High (crisis management relevant)  
**Questions:**
- Oura recovery score vs actual Concept2 power output
- Sleep debt accumulation vs resistance training volume tolerance
- Minimum sleep threshold for productive training
- HRV as predictor of training capacity

**Data Sources:** Oura summary, `minute_facts`, `workouts`, `cardio_splits`  
**Output:** Daily readiness predictor model, actionable thresholds  
**Estimated Time:** 3-4 hours  
**Next Steps:**
1. Join Oura recovery → next-day workout performance
2. Calculate rolling 7-day sleep debt
3. Correlate with power output, HR response
4. Identify minimum viable sleep for training

---

#### RES-1: Resistance Training Trend During Stress
**Status:** 💡 New idea  
**Priority:** High (crisis management relevant)  
**Questions:**
- JEFIT volume/frequency patterns before mental health crashes
- Minimum effective frequency to prevent detraining (maintenance floor)
- Which movements maintain strength vs which drop fastest
- Volume tolerance during high-stress periods

**Data Sources:** JEFIT logs, `workouts`, compound protocol  
**Output:** Minimum maintenance program, detraining rate by movement  
**Estimated Time:** 2-3 hours  
**Next Steps:**
1. Extract JEFIT resistance training logs
2. Identify pre-crash volume patterns
3. Calculate detraining rates by lift
4. Define minimal effective dose for maintenance

---

#### COMP-1: Compound Impact on Recovery Metrics
**Status:** 💡 New idea  
**Priority:** Medium (ongoing monitoring)  
**Questions:**
- Iron protocol timing vs Oura recovery scores
- Supplement changes vs sleep quality, HRV
- TRT + stress periods vs recovery capacity
- Optimal timing for iron vs zinc vs other compounds

**Data Sources:** `protocol_history`, Oura summary, `labs`  
**Output:** Compound timing optimization guide  
**Estimated Time:** 2 hours  
**Next Steps:**
1. Overlay protocol changes with Oura metrics
2. Identify pre/post changes in HRV, sleep quality
3. Flag periods of combined stress + protocol changes
4. Document optimal timing strategies

---

#### READ-1: Daily Readiness Composite Score
**Status:** 🔍 Scoped  
**Priority:** High (crisis management + long-term)  
**Questions:**
- Create composite: Oura recovery + sleep debt + recent training volume
- Correlate with actual performance in minute_facts
- Does data-driven readiness predict output better than subjective feel?
- Actionable thresholds: "Zone 2 day" vs "push resistance training"

**Data Sources:** Oura summary, `minute_facts`, `workouts`, sleep debt calculation  
**Output:** Daily readiness algorithm, training recommendation engine  
**Estimated Time:** 4-6 hours (includes validation)  
**Next Steps:**
1. Define composite score formula
2. Build historical dataset of readiness + performance
3. Validate predictive power
4. Set actionable thresholds
5. Create daily dashboard view

---

#### MIN-1: Minute Facts Cross-Domain Exploration
**Status:** 💡 New idea  
**Priority:** Low (exploratory)  
**Questions:**
- What patterns exist across minute-level data we haven't thought to look for?
- Unusual correlations between disparate metrics?
- Time-of-day patterns in various metrics?
- Leading indicators for performance/recovery?

**Data Sources:** All `minute_facts` columns  
**Output:** Correlation matrix, surprising findings, new hypotheses  
**Estimated Time:** 3-4 hours  
**Next Steps:**
1. Generate full correlation matrix across minute_facts
2. Identify high-correlation pairs
3. Visualize interesting temporal patterns
4. Flag unexpected relationships for investigation

#### PROG-1: Weekly Training Progression Coach → PROMOTED TO EPIC ✅
**Status:** 🚀 Active EPIC (see EPIC_Weekly_Training_Coach.md)  
**Priority:** P0 (Core Feature)  
**Current Sprint:** Sprint 1 - Data Foundation  
**Questions:**
- Based on recent performance, what should I target this week?
- What volume can I handle given recovery state?
- Which movements need attention (lagging lifts)?
- What's my minimal maintenance floor vs optimal progression?
- How do I periodize during stress vs recovery phases?

**Phase 1 Scope (Strength Training):**
- Weekly resistance training plan generator
- Lift-by-lift progression analysis (current → recent → semi-recent)
- Recovery-adjusted volume recommendations
- Specific targets: exercises, sets, reps, weights
- Motivational context ("last week you hit X, aim for Y")
- Deload warnings when recovery is compromised

**Phase 2 Scope (Full Training Coach):**
- Zone 2 cardio: watt targets + durations for bike/rowing
- VO2 max sessions: interval structure based on current capacity
- Integrated weekly plan across all modalities
- Auto-adjust based on performance + recovery data

**Data Sources:**
- **Primary:** JEFIT logs (all lifts, sets, reps, weights, dates)
- **Context:** Oura recovery, sleep debt, recent training volume
- **Adjustments:** Protocol changes (compounds affecting strength)
- **Future:** Concept2 power progression, lactate thresholds

**Output:**
- Weekly training prescription (markdown format)
- Lift-specific targets with rationale
- Volume guidance (sessions/week based on recovery)
- Progressive overload tracking (are you advancing?)
- Historical context (peak performance vs current)

**Technical Implementation:**
1. Query JEFIT data: last 4-12 weeks per lift
2. Calculate progression rates (weekly/monthly)
3. Identify lagging movements
4. Pull Oura recovery + sleep metrics
5. Generate recommendations with safety checks
6. Format as actionable weekly plan

**Estimated Time:** 
- Phase 1 (strength only): 4-6 hours
- Phase 2 (full coach): +3-4 hours

**Success Criteria:**
- Provides specific targets you can execute
- Motivates by showing recent progress
- Prevents overtraining with recovery-based adjustments
- Replaces need for JEFIT's coach feature
- Feels more useful than generic app recommendations

**Next Steps:**
1. Validate JEFIT data structure in HDP
2. Design weekly report format (what info do you want to see?)
3. Build progression calculator (conservative vs aggressive)
4. Integrate recovery metrics for volume adjustment
5. Create first weekly report, iterate on format

---

### Triage Process

**Weekly Review:**
1. Review new ideas
2. Move 💡 → 🔍 (scope out)
3. Move 🔍 → 📋 (prioritize)
4. Move 📋 → Active Analysis Catalog (execute)
5. Move completed analyses ✅ → main catalog

**Prioritization Criteria:**
- **Immediate value:** Helps current crisis management?
- **Recovery phase:** Supports Oct 2025 - Apr 2026 goals?
- **Actionable:** Will produce concrete decisions/changes?
- **Data ready:** Have clean data needed for analysis?
- **Time cost:** Can complete in single focused session?

---

### Template for New Ideas

```markdown
#### [ID]: [Title]
**Status:** 💡 New idea  
**Priority:** TBD  
**Questions:**
- Key question 1
- Key question 2
- Key question 3

**Data Sources:** [Tables/sources needed]  
**Output:** [What gets produced]  
**Estimated Time:** [Hours]  
**Next Steps:**
1. Step 1
2. Step 2
3. Step 3
```

---

**Last Updated:** 2025-12-04  
**Review Cycle:** Weekly
