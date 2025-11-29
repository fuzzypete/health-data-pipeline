# Health Data Pipeline - Interactive Dashboard Implementation Guide

## TL;DR: From Static Charts to Interactive Correlation Discovery

**Problem:** Static matplotlib charts make correlation discovery difficult
**Solution:** Interactive Plotly + optional Streamlit UI
**Effort:** 15 minutes to first working version, 2-3 hours to polish
**Result:** Dynamic overlays with toggle controls, perfect for visual troubleshooting

---

## Implementation Path

### Phase 1: Jupyter + Plotly (Start Here - 15 minutes)

**What you get:**
- ✅ Interactive charts in Jupyter notebooks
- ✅ Zoom, pan, hover details
- ✅ Toggle individual traces on/off
- ✅ Multiple y-axes for different units
- ✅ Query DuckDB directly

**When to use:**
- Ad-hoc correlation exploration
- One-off investigations
- Rapid iteration

**Setup:**
```bash
pip install plotly duckdb pandas --break-system-packages

# In Jupyter:
from hdp_interactive_dashboard import HealthDashboard

dashboard = HealthDashboard()
metrics = [
    ('Ferritin', 'labs'),
    ('Total Meters', 'training'),
    ('Iron', 'supplements')
]
fig = dashboard.create_overlay_chart(metrics)
fig.show()
```

**Output:** Interactive chart opens in browser, fully explorable

---

### Phase 2: Streamlit App (Next Step - 2-3 hours)

**What you get:**
- ✅ Persistent UI (not lost when kernel restarts)
- ✅ Checkbox controls for adding/removing datasets
- ✅ Date range pickers
- ✅ Preset correlation analyses (one-click)
- ✅ Data table views
- ✅ Export to HTML/PNG

**When to use:**
- Regular correlation analysis
- Sharing with others (doctors, trainers)
- Systematic investigation

**Setup:**
```bash
pip install streamlit plotly duckdb pandas --break-system-packages

streamlit run hdp_streamlit_dashboard.py
# Opens at http://localhost:8501
```

**Output:** Full web UI, navigable with mouse, shareable

---

### Phase 3: Advanced Features (Optional - if needed)

**Add later if you want:**
- Statistical correlation coefficients (Pearson, Spearman)
- Lag analysis (e.g., "HRV drops 36 hours after high volume")
- Anomaly detection (highlight unusual patterns)
- Automated insight generation
- Custom annotation layers

**Don't add unless you need them** - start simple, add complexity as patterns emerge

---

## Your Specific Use Cases

### Use Case 1: Iron Repletion Efficacy

**Question:** "Is my iron supplementation protocol working?"

**Metrics to overlay:**
1. Ferritin (ng/mL) - primary outcome
2. Iron supplement dose (mg) - intervention
3. Hemoglobin (g/dL) - secondary outcome
4. Total training volume (meters) - confounding variable

**What to look for:**
- Ferritin slope change when iron started (Oct 14)
- Correlation between dose consistency and ferritin rise
- Training volume impact on ferritin (higher volume = more depletion)

**Code:**
```python
dashboard = HealthDashboard(
    start_date=datetime(2025, 10, 1),
    end_date=datetime.now()
)

metrics = [
    ('Ferritin', 'labs'),
    ('Iron', 'supplements'),
    ('Hemoglobin', 'labs'),
    ('Total Meters', 'training')
]

fig = dashboard.create_overlay_chart(metrics)
fig.update_layout(title='Iron Protocol Efficacy Analysis')
fig.show()
```

**Expected insight:** 
- Ferritin rises 15-25 ng/mL per month during consistent supplementation
- Drops or plateaus when doses missed
- Training volume inversely correlated with ferritin (visible lag)

---

### Use Case 2: HGH → Kidney Function Causality

**Question:** "Did HGH cause my creatinine to rise?"

**Metrics to overlay:**
1. Creatinine (mg/dL) - outcome
2. eGFR (mL/min) - outcome
3. HGH dose (IU/week) - intervention
4. Training volume (meters) - confounding variable

**What to look for:**
- Temporal relationship: creatinine rise starts when HGH starts (May 2025)
- Dose-response: did creatinine jump when dose increased?
- Reversal: did reduction from 14→10 IU slow the trend?

**Code:**
```python
dashboard = HealthDashboard(
    start_date=datetime(2024, 1, 1),
    end_date=datetime.now()
)

metrics = [
    ('Creatinine', 'labs'),
    ('eGFR', 'labs'),
    ('HGH', 'supplements'),
    ('Total Meters', 'training')
]

fig = dashboard.create_overlay_chart(metrics)
fig.update_layout(
    title='HGH → Kidney Function Temporal Analysis',
    annotations=[
        dict(x='2025-05-17', y=1.02, text='HGH Started', showarrow=True),
        dict(x='2025-11-24', y=1.32, text='HGH Reduced', showarrow=True)
    ]
)
fig.show()
```

**Expected insight:**
- Clear temporal correlation: creatinine rises after HGH start
- Dose reduction may stabilize (check next labs)
- Training volume increase may be additive factor

---

### Use Case 3: Training Load → Recovery Metrics

**Question:** "How much volume can I handle before HRV crashes?"

**Metrics to overlay:**
1. Total Meters (meters) - training load
2. HRV (ms) - recovery indicator
3. Readiness Score (0-100) - Oura's composite
4. Resting HR (bpm) - stress indicator

**What to look for:**
- HRV drops 1-2 days after high volume (lag effect)
- Threshold: what volume level correlates with <50 readiness?
- Recovery time: how many days until HRV normalizes?

**Code:**
```python
dashboard = HealthDashboard(
    start_date=datetime(2025, 9, 1),
    end_date=datetime.now()
)

metrics = [
    ('Total Meters', 'training'),
    ('HRV', 'recovery'),
    ('Readiness Score', 'recovery'),
    ('Resting HR', 'recovery')
]

fig = dashboard.create_overlay_chart(metrics)
fig.update_layout(title='Training Load vs Recovery Metrics')
fig.show()
```

**Expected insight:**
- Volume >15km correlates with HRV drop next day
- Readiness <60 = need deload
- Resting HR rises before HRV drops (earlier warning signal)

---

### Use Case 4: Compound Cycle → Biomarker Impact

**Question:** "What did Anavar/Masteron actually do to my lipids?"

**Metrics to overlay:**
1. HDL (mg/dL) - primary concern
2. SHBG (nmol/L) - mechanism
3. Anavar dose (mg/week) - intervention
4. Masteron dose (mg/week) - intervention

**What to look for:**
- SHBG crash timing (immediate?)
- HDL drop timing (delayed vs SHBG?)
- Recovery trajectory after stopping

**Code:**
```python
dashboard = HealthDashboard(
    start_date=datetime(2025, 7, 1),
    end_date=datetime.now()
)

metrics = [
    ('HDL', 'labs'),
    ('SHBG', 'labs'),
    ('Anavar', 'supplements'),
    ('Masteron', 'supplements')
]

fig = dashboard.create_overlay_chart(metrics)
fig.update_layout(
    title='Oral Cycle → Lipid Impact Timeline',
    annotations=[
        dict(x='2025-08-05', text='Cycle Start', showarrow=True),
        dict(x='2025-10-10', text='Cycle End', showarrow=True)
    ]
)
fig.show()
```

**Expected insight:**
- SHBG crashes within 2 weeks
- HDL drops 3-4 weeks into cycle
- SHBG recovers slower than HDL after stopping

---

## Technical Implementation Details

### Multiple Y-Axes Strategy

**Problem:** Ferritin (ng/mL) and Training Volume (meters) can't share Y-axis

**Solution:** Plotly supports unlimited overlaying y-axes

**Implementation:**
```python
# Automatic unit grouping
unit_groups = {
    'ng/mL': ['Ferritin', 'Vitamin D'],
    'meters': ['Total Distance', 'Zone 2 Distance'],
    'mg': ['Iron Dose', 'Niacin Dose']
}

# Each unit gets its own y-axis
for i, (unit, metrics) in enumerate(unit_groups.items()):
    yaxis_name = f'y{i+1}' if i > 0 else 'y'
    layout[yaxis_name] = {
        'title': unit,
        'side': 'left' if i == 0 else 'right',
        'overlaying': 'y' if i > 0 else None,
        'position': 1.0 + (0.08 * (i-1)) if i > 0 else None
    }
```

**Result:** Clean overlays without axis confusion

---

### Dynamic Toggle Controls

**Problem:** 10+ metrics on one chart = visual clutter

**Solution:** Plotly updatemenus for show/hide

**Implementation:**
```python
# Each trace gets visibility toggle
buttons = [
    dict(
        label='Show All',
        method='update',
        args=[{'visible': [True] * len(traces)}]
    )
]

for i, trace_name in enumerate(trace_names):
    visible = [j == i for j in range(len(traces))]
    buttons.append(dict(
        label=trace_name,
        method='update',
        args=[{'visible': visible}]
    ))

fig.update_layout(updatemenus=[dict(buttons=buttons)])
```

**Result:** Click to isolate individual metrics, "Show All" to compare

---

### Query Performance Optimization

**Problem:** DuckDB queries slow for 8 years of daily data

**Solutions:**

1. **Partition pruning** (already in your HDP)
   ```sql
   -- Only reads relevant partitions
   WHERE date BETWEEN '2025-01-01' AND '2025-12-31'
   ```

2. **Caching** (Streamlit)
   ```python
   @st.cache_data(ttl=300)  # Cache 5 minutes
   def query_metric_data(...):
   ```

3. **Aggregation** (for long date ranges)
   ```sql
   -- Weekly rollups for >1 year views
   SELECT 
       DATE_TRUNC('week', date) as week,
       AVG(numeric_value) as value
   FROM labs_results
   GROUP BY week
   ```

**Result:** Sub-second queries even for multi-year ranges

---

## Progression Timeline

**Day 1 (15 min):**
- Install Plotly
- Run hdp_interactive_dashboard.py example
- Create first correlation chart

**Week 1 (2-3 hours):**
- Customize queries for your HDP schema
- Add your specific metrics
- Create 3-4 preset analyses

**Week 2 (1-2 hours):**
- Set up Streamlit app
- Configure sidebar controls
- Add preset buttons for common investigations

**Month 1 (ongoing):**
- Discover correlations through exploration
- Document insights in HDP outputs
- Build library of correlation analyses

---

## What NOT to Do

**❌ Don't build Grafana stack**
- Requires PostgreSQL/InfluxDB migration
- Overkill for personal analysis
- More maintenance than value

**❌ Don't implement ML correlation detection yet**
- Manual visual discovery finds more actionable patterns
- Statistical correlation ≠ causation
- Add later if you exhaust manual exploration

**❌ Don't optimize prematurely**
- Start with simple queries
- Add aggregation only if slow
- Cache only if actually needed

---

## Integration with Existing HDP

**These dashboards complement your static reports:**

**Static PNG charts (existing):**
- ✅ Documentation
- ✅ PCP appointments
- ✅ Longitudinal comparisons
- ✅ Fixed analysis

**Interactive dashboards (new):**
- ✅ Exploration
- ✅ Ad-hoc investigation
- ✅ Correlation discovery
- ✅ Dynamic analysis

**Workflow:**
1. Use interactive dashboard to discover correlation
2. Generate static chart to document finding
3. Add to PCP presentation or HDP outputs
4. Cite in decision-making (e.g., "Reduced HGH because...")

---

## Next Steps

**Immediate (today):**
1. Install Plotly: `pip install plotly --break-system-packages`
2. Run example: `python hdp_interactive_dashboard.py`
3. Open interactive chart in browser

**This week:**
1. Adjust queries to match your HDP schema
2. Create iron repletion analysis
3. Create HGH→kidney analysis

**This month:**
1. Install Streamlit: `pip install streamlit --break-system-packages`
2. Launch Streamlit app: `streamlit run hdp_streamlit_dashboard.py`
3. Build library of preset analyses

---

## Questions to Answer with These Dashboards

**Iron repletion:**
- At what ferritin level does max HR recover?
- Does EOD iron work as well as daily?
- What training volume is sustainable during repletion?

**Kidney function:**
- Is HGH reduction slowing creatinine rise?
- Does training volume affect creatinine?
- What's the lag between dose change and biomarker change?

**Training optimization:**
- What volume triggers HRV drop?
- How many recovery days after high volume?
- Does Zone 2 improve HRV more than intervals?

**Supplement efficacy:**
- Does niacin actually raise HDL?
- How long until fish oil affects triglycerides?
- What ferritin level eliminates fatigue?

**These questions are impossible to answer with static charts.**

**Interactive overlays reveal patterns you didn't know to look for.**

---

**Start with Phase 1 (Jupyter + Plotly) today. Graduate to Phase 2 (Streamlit) when you want persistent UI.**

**Don't overthink it - just run the example and see what correlations jump out.**
