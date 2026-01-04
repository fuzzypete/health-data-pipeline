# HDP Dashboard - Complete Requirements for Implementation

**Project:** Personal Health Data Dashboard  
**Framework:** Streamlit + DuckDB + Plotly  
**Timeline:** Phase 1A (this week), Phase 1B (next week), Phase 2 (later)  
**Developer:** Claude Code (CC)

---

## Project Overview

Build a Streamlit-based personal health dashboard showcasing Peter's Health Data Pipeline (HDP). Primary use case: personal showcase with potential commercial exploration for trainers/coaches.

**Key Value Proposition:**
- Demonstrate sophisticated health data integration across 6+ sources
- Surface correlations between protocols, training, and biomarkers
- Replace generic fitness app recommendations with personalized insights
- Mobile-first design for on-the-spot demos

---

## Technical Constraints

- **Backend:** Python/Poetry, DuckDB queries against Parquet files
- **Frontend:** Streamlit (deploy to Streamlit Community Cloud)
- **Data location:** Local HDP at `~/health-data-pipeline/Data/Parquet/`
- **Mobile-first:** Must work well on phone for on-the-spot demos
- **Authentication:** None initially (single-user showcase)
- **Deployment:** Streamlit Community Cloud (free tier)

---

## HDP Data Architecture

### Available Data Sources

The dashboard queries Parquet files organized in medallion architecture:

```
Data/Parquet/
├── hae_heart_rate_minute/          # Minute-level HR from Apple Health
│   └── year=YYYY/month=MM/data.parquet
├── concept2_workouts/              # Cardio sessions (rowing/biking)
│   └── year=YYYY/month=MM/data.parquet
├── concept2_splits/                # Split data with power output
│   └── year=YYYY/month=MM/data.parquet
├── jefit_logs/                     # Resistance training sets
│   └── year=YYYY/data.parquet
├── oura_daily_summaries/           # Sleep, HRV, readiness
│   └── year=YYYY/month=MM/data.parquet
├── oura_heart_rate_5min/           # 5-min HR samples
│   └── year=YYYY/month=MM/data.parquet
├── labs_results/                   # Biomarker test results
│   └── year=YYYY/data.parquet
└── protocol_history/               # Supplement/compound tracking
    └── year=YYYY/data.parquet
```

### Recommended Query Pattern

```python
import duckdb
from datetime import datetime, timedelta

conn = duckdb.connect()

# Example: Query Concept2 workouts for date range
df = conn.execute("""
    SELECT 
        workout_date,
        workout_type,
        total_meters,
        total_seconds,
        avg_watts,
        avg_heart_rate
    FROM read_parquet('Data/Parquet/concept2_workouts/**/*.parquet')
    WHERE workout_date BETWEEN ? AND ?
    ORDER BY workout_date DESC
""", [start_date, end_date]).df()
```

**Important Notes:**
- All tables use `year=YYYY/month=MM` partitioning (high-volume) or `year=YYYY` (low-volume)
- Use `read_parquet('path/**/*.parquet')` to scan all partitions
- DuckDB automatically prunes partitions based on WHERE clauses
- All timestamps should be in UTC for consistency
- Use `@st.cache_data` decorator for expensive queries

### Key Schema Fields

**concept2_workouts:**
- `workout_date`, `workout_type` (RowErg/BikeErg)
- `avg_watts`, `avg_heart_rate`, `max_heart_rate`
- `total_meters`, `total_seconds`

**concept2_splits:**
- `workout_date`, `split_number`
- `split_watts`, `split_heart_rate`
- Use for intra-workout power analysis

**jefit_logs:**
- `workout_date`, `exercise_name`
- `set_number`, `reps`, `weight_lbs`
- `exercise_category` (Upper Push/Pull, Lower, Core)

**oura_daily_summaries:**
- `summary_date`
- `total_sleep_duration`, `sleep_score`
- `hrv_avg`, `resting_heart_rate`
- `readiness_score`

**labs_results:**
- `test_date`, `biomarker_name`, `value`, `unit`
- `reference_range_low`, `reference_range_high`
- `lab_company` (LabCorp, Quest, etc.)

**protocol_history:**
- `protocol_name`, `start_date`, `end_date`
- `dosage`, `frequency`, `notes`
- `protocol_type` (TRT, HGH, Supplement, Compound)

---

## Existing Code References

Peter has already built components that CC should examine before writing new code:

### 1. Weekly Training Coach
**Location:** `analysis/scripts/generate_weekly_report.py`

This script generates personalized weekly training plans using:
- JEFIT progression analysis
- Oura recovery metrics
- Training mode selection (OPTIMAL/MAINTENANCE/DELOAD)
- Exercise-specific targets with weights

**Key Functions to Reference:**
- `calculate_progression_status()` - determines if exercise ready to progress
- `get_recovery_metrics()` - pulls Oura data for volume adjustment
- `generate_weekly_report()` - main report generator

**Relevant for:** Strength Training section, Recovery section

### 2. Workout Templates
**Location:** `analysis/scripts/workout_templates.py`

Defines workout structures and scheduling:
- Exercise templates by category (Upper A/B, Lower A/B, Core)
- Weekly schedule generation based on training mode
- Superset and progression logic

**Relevant for:** Strength Training section, NOW page (current week's plan)

### 3. Starter Dashboard
**Location:** `analysis/apps/hdp_interactive_dashboard.py`

Incomplete Plotly-based dashboard with:
- Basic metric retrieval functions
- Chart structure examples
- Query patterns

**Status:** Incomplete, but has useful boilerplate for DuckDB queries

**Action:** CC should review this file, extract useful patterns, then build new dashboard from scratch using Streamlit instead of raw Plotly.

---

## Dashboard Structure

### Layout Hierarchy

```
┌─────────────────────────────────────────────────────────┐
│ HEADER: HDP Dashboard | Weekly Plan | NOW | Updated    │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│ KPI CARDS (2x3 grid on desktop, vertical on mobile)    │
│ [Ferritin] [Zone2 W] [MaxHR] [HRV] [Sleep] [Volume]   │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│ 📊 CARDIOVASCULAR PERFORMANCE (expandable)              │
│ - Zone 2 progression chart                             │
│ - Max HR recovery trend                                │
│ - Volume by week                                        │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│ 💪 STRENGTH TRAINING (expandable)                       │
│ - Lift progression for key movements                   │
│ - Volume by muscle group                               │
│ - Progress indicators                                   │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│ 😴 RECOVERY METRICS (expandable)                        │
│ - HRV trend with training load                         │
│ - Sleep quality                                         │
│ - Training mode indicator                              │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│ 🔬 LABS & PROTOCOLS (expandable)                        │
│ - Timeline visualization                               │
│ - Recent lab results table                             │
│ - Protocol detail panel                                │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│ 🔍 CORRELATION EXPLORER (expandable)                    │
│ - Interactive scatter plot                             │
│ - Metric selectors (X/Y axis)                          │
│ - Preset correlations                                  │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│ 📍 NOW PAGE (expandable)                                │
│ - Current phase & status                               │
│ - Active protocols                                      │
│ - Next milestones                                       │
└─────────────────────────────────────────────────────────┘

[Global Time Range: 30d | 90d | 6mo | 1y | All]
```

---

## Detailed Component Specifications

### Top Navigation Bar

**Components:**
- Dashboard title: "Health Data Pipeline"
- Link to latest weekly training plan (opens in new tab)
- Link to NOW page (scrolls to NOW section)
- Last data refresh timestamp

**Implementation:**
```python
col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
with col1:
    st.title("🏃 HDP Dashboard")
with col2:
    st.link_button("📋 Weekly Plan", url="/weekly_plan")
with col3:
    st.button("📍 NOW", on_click=lambda: scroll_to_section("now"))
with col4:
    st.caption(f"Updated: {last_refresh}")
```

**Weekly Plan Link:**
- Should open most recent file from `analysis/outputs/weekly_report_*.md`
- Format as rendered markdown or link to file

---

### Hero KPI Cards (Always Visible)

Six key metrics displayed as cards with trend indicators.

**Card 1: Ferritin**
- **Query:** Latest ferritin value from `labs_results` where `biomarker_name = 'Ferritin'`
- **Display:** "57 ng/mL" with trend arrow
- **Target:** ">60 ng/mL" shown as subtitle
- **Trend:** Compare to value 4 weeks prior
- **Sparkline:** Last 6 measurements over past year

**Card 2: Zone 2 Power Ceiling**
- **Query:** Recent workouts from `concept2_workouts` where workout is Zone 2 intensity
- **Logic:** Find max sustained watts at lactate 1.6-1.9 mmol/L range
- **Display:** "145-150W" with trend
- **Trend:** Compare to 4 weeks ago
- **Sparkline:** Max Zone 2 watts by week (last 12 weeks)

**Card 3: Max HR Achieved**
- **Query:** `MAX(max_heart_rate)` from `concept2_workouts` in last 7 days
- **Display:** "153 bpm" with context "(baseline: 161)"
- **Target:** Show % of baseline (153/161 = 95%)
- **Trend:** Compare to 4 weeks prior
- **Sparkline:** Max HR by week

**Card 4: HRV 7-day Average**
- **Query:** `AVG(hrv_avg)` from `oura_daily_summaries` for last 7 days
- **Display:** "65 ms" with trend
- **Baseline:** Calculate personal baseline from last 90 days
- **Trend:** % deviation from baseline
- **Sparkline:** Daily HRV last 30 days

**Card 5: Sleep Debt**
- **Query:** Calculate cumulative sleep debt using Oura sleep duration vs 7.5hr target
- **Display:** "-3.2 hours" (negative = deficit)
- **Trend:** Improving/worsening over last week
- **Color:** Green if <2hr deficit, yellow 2-5hr, red >5hr

**Card 6: Weekly Training Volume**
- **Query:** Sum of workout minutes from all sources (concept2 + jefit) for current week
- **Display:** "315 min" with comparison to 4-week average
- **Breakdown:** Show split (cardio vs strength) in tooltip
- **Trend:** This week vs average

**Card Implementation Pattern:**
```python
def render_kpi_card(title, value, unit, trend_pct, target=None, sparkline_data=None):
    with st.container():
        st.metric(
            label=title,
            value=f"{value} {unit}",
            delta=f"{trend_pct:+.1f}%",
            delta_color="normal" if trend_pct > 0 else "inverse"
        )
        if target:
            st.caption(f"Target: {target}")
        if sparkline_data:
            st.line_chart(sparkline_data, height=50)
```

---

### Section 1: Cardiovascular Performance

**Primary Chart: Zone 2 Power Progression**

**Data Requirements:**
- X-axis: Workout date
- Y-axis: Average watts during workout
- Filter: Only workouts classified as "Zone 2" intensity
- Overlay: Ferritin levels from labs (secondary Y-axis or background shading)

**Query Pattern:**
```python
# Get Zone 2 workouts
zone2_workouts = conn.execute("""
    SELECT 
        workout_date,
        avg_watts,
        avg_heart_rate,
        total_seconds / 60.0 as duration_min
    FROM read_parquet('Data/Parquet/concept2_workouts/**/*.parquet')
    WHERE workout_type = 'BikeErg'
        AND avg_watts BETWEEN 140 AND 160  -- Approximate Zone 2 range
        AND workout_date >= ?
    ORDER BY workout_date
""", [start_date]).df()

# Get ferritin values for overlay
ferritin = conn.execute("""
    SELECT 
        test_date,
        value as ferritin_ng_ml
    FROM read_parquet('Data/Parquet/labs_results/**/*.parquet')
    WHERE biomarker_name = 'Ferritin'
        AND test_date >= ?
    ORDER BY test_date
""", [start_date]).df()
```

**Chart Implementation:**
```python
import plotly.graph_objects as go
from plotly.subplots import make_subplots

fig = make_subplots(specs=[[{"secondary_y": True}]])

# Zone 2 power as scatter plot
fig.add_trace(
    go.Scatter(
        x=zone2_workouts['workout_date'],
        y=zone2_workouts['avg_watts'],
        mode='markers+lines',
        name='Zone 2 Power',
        marker=dict(size=8),
    ),
    secondary_y=False
)

# Ferritin as line overlay
fig.add_trace(
    go.Scatter(
        x=ferritin['test_date'],
        y=ferritin['ferritin_ng_ml'],
        mode='lines+markers',
        name='Ferritin',
        line=dict(dash='dash', color='orange'),
        marker=dict(size=10, symbol='diamond'),
    ),
    secondary_y=True
)

# Add reference line for ferritin target
fig.add_hline(y=60, line_dash="dot", line_color="green", 
              annotation_text="Ferritin Target", secondary_y=True)

fig.update_xaxes(title_text="Date")
fig.update_yaxes(title_text="Power (watts)", secondary_y=False)
fig.update_yaxes(title_text="Ferritin (ng/mL)", secondary_y=True)

st.plotly_chart(fig, use_container_width=True)
```

**Protocol Annotations:**
Add vertical lines or shaded regions for protocol changes:
```python
# Query protocol history
protocols = conn.execute("""
    SELECT 
        protocol_name,
        start_date,
        end_date
    FROM read_parquet('Data/Parquet/protocol_history/**/*.parquet')
    WHERE protocol_type IN ('Supplement', 'Compound')
        AND start_date >= ?
""", [start_date]).df()

# Add vertical lines for protocol starts
for _, protocol in protocols.iterrows():
    fig.add_vline(
        x=protocol['start_date'],
        line_dash="dot",
        annotation_text=f"Started {protocol['protocol_name']}",
        annotation_position="top"
    )
```

**Secondary Metrics:**

1. **Lactate Response Chart**
   - Parse lactate values from `concept2_workouts.comment` field
   - Regex pattern: `r'lactate[:\s]+(\d+\.\d+)'` 
   - Plot: Lactate (mmol/L) vs Power (watts) as scatter
   - Show Zone 2 target band (1.6-1.9 mmol/L)

2. **Max HR Recovery Trend**
   - Query: `MAX(max_heart_rate)` by week from concept2_workouts
   - Display: Line chart with baseline (161 bpm) reference
   - Annotation: Current deficit (e.g., "-8 bpm from baseline")

3. **Cardio Volume by Week**
   - Stacked bar chart: Zone 2 minutes + Interval minutes
   - X-axis: Week
   - Y-axis: Total minutes
   - Color: Zone 2 (blue), Intervals (red)

**Filters:**
- Equipment type: BikeErg | RowErg | Both
- Intensity: Zone 2 only | Include intervals
- Time range: Inherited from global selector

**Mobile Considerations:**
- Stack charts vertically
- Primary chart always visible
- Secondary charts in expandable sections
- Touch-friendly controls (large buttons)

---

### Section 2: Strength Training

**Primary Chart: Lift Progression**

**Data Requirements:**
- Multi-line chart showing weight progression for top compound lifts
- Lines for: Bench Press, Squat, Deadlift, Overhead Press
- Show max weight achieved per session (not per set)

**Query Pattern:**
```python
# Get top compound lifts
key_lifts = ['Barbell Bench Press', 'Barbell Squat', 'Deadlift', 'Overhead Press']

lift_progression = conn.execute("""
    SELECT 
        workout_date,
        exercise_name,
        MAX(weight_lbs) as max_weight
    FROM read_parquet('Data/Parquet/jefit_logs/**/*.parquet')
    WHERE exercise_name IN (?, ?, ?, ?)
        AND workout_date >= ?
    GROUP BY workout_date, exercise_name
    ORDER BY workout_date, exercise_name
""", key_lifts + [start_date]).df()
```

**Chart Implementation:**
```python
fig = go.Figure()

for lift in key_lifts:
    lift_data = lift_progression[lift_progression['exercise_name'] == lift]
    fig.add_trace(go.Scatter(
        x=lift_data['workout_date'],
        y=lift_data['max_weight'],
        mode='lines+markers',
        name=lift,
        line=dict(width=2),
        marker=dict(size=6)
    ))

fig.update_layout(
    title="Key Lift Progression",
    xaxis_title="Date",
    yaxis_title="Weight (lbs)",
    hovermode='x unified'
)

st.plotly_chart(fig, use_container_width=True)
```

**Weekly Coach Integration:**

Show current week's targets as annotations on chart:
```python
# Assume weekly targets loaded from generate_weekly_report.py output
for exercise, target_weight in weekly_targets.items():
    # Add horizontal line at target weight
    fig.add_hline(
        y=target_weight,
        line_dash="dash",
        annotation_text=f"{exercise} target: {target_weight} lbs"
    )
```

**Secondary Metrics:**

1. **Volume by Muscle Group**
   - Bar chart: Total weekly volume (sets × reps × weight)
   - Categories: Upper Push | Upper Pull | Lower | Core
   - Query requires exercise categorization (use `exercise_category` field if available)

2. **Progress Indicators Table**
   - Columns: Exercise | Current Weight | Peak Weight | Status | Action
   - Status values: "Ready to progress" (green), "Building" (yellow), "Stagnant" (red)
   - Action: "Add 5 lbs" or "Maintain" or "Deload"
   - This data should come from weekly coach logic

**Example Table:**
```python
progress_data = {
    'Exercise': ['Bench Press', 'Squat', 'Deadlift'],
    'Current': ['185 lbs', '225 lbs', '275 lbs'],
    'Peak': ['205 lbs', '245 lbs', '315 lbs'],
    'Status': ['🟢 Ready', '🟡 Building', '🔴 Stagnant'],
    'Action': ['Add 5 lbs', 'Maintain', 'Focus on form']
}

st.dataframe(
    progress_data,
    use_container_width=True,
    hide_index=True
)
```

**Filters:**
- Exercise category: All | Upper | Lower | Core
- Show top N exercises by volume (default: 10)
- Date range from global selector

---

### Section 3: Recovery Metrics

**Primary Chart: HRV vs Training Load**

**Data Requirements:**
- Dual Y-axis chart showing relationship between HRV and training stress
- Left axis: HRV (ms)
- Right axis: Training load (calculated metric)

**Query Pattern:**
```python
# Get HRV data
hrv_data = conn.execute("""
    SELECT 
        summary_date,
        hrv_avg,
        resting_heart_rate,
        sleep_score,
        readiness_score
    FROM read_parquet('Data/Parquet/oura_daily_summaries/**/*.parquet')
    WHERE summary_date >= ?
    ORDER BY summary_date
""", [start_date]).df()

# Calculate training load (sum of workout minutes in past 7 days)
training_load = conn.execute("""
    SELECT 
        workout_date,
        SUM(total_seconds / 60.0) OVER (
            ORDER BY workout_date 
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) as rolling_7day_minutes
    FROM read_parquet('Data/Parquet/concept2_workouts/**/*.parquet')
    WHERE workout_date >= ?
    
    UNION ALL
    
    SELECT 
        workout_date,
        COUNT(*) * 45 as estimated_minutes  -- Assume 45min per session
    FROM read_parquet('Data/Parquet/jefit_logs/**/*.parquet')
    WHERE workout_date >= ?
    GROUP BY workout_date
""", [start_date, start_date]).df()
```

**Chart Implementation:**
```python
fig = make_subplots(specs=[[{"secondary_y": True}]])

# HRV trend
fig.add_trace(
    go.Scatter(x=hrv_data['summary_date'], y=hrv_data['hrv_avg'],
               mode='lines', name='HRV', line=dict(color='green', width=2)),
    secondary_y=False
)

# Add HRV baseline (90-day average)
hrv_baseline = hrv_data['hrv_avg'].mean()
fig.add_hline(y=hrv_baseline, line_dash="dash", line_color="darkgreen",
              annotation_text="Baseline", secondary_y=False)

# Training load
fig.add_trace(
    go.Bar(x=training_load['workout_date'], y=training_load['rolling_7day_minutes'],
           name='7-day Load', marker_color='lightblue', opacity=0.6),
    secondary_y=True
)

fig.update_yaxes(title_text="HRV (ms)", secondary_y=False)
fig.update_yaxes(title_text="Training Load (min)", secondary_y=True)

st.plotly_chart(fig, use_container_width=True)
```

**Secondary Metrics:**

1. **Sleep Duration + Quality**
   - Combined chart: Bar (duration in hours) + Line (quality score)
   - Query `total_sleep_duration` and `sleep_score` from oura_daily_summaries
   - Show target line at 7.5 hours

2. **Resting HR Deviation**
   - Line chart showing deviation from baseline
   - Baseline = 90-day average resting HR
   - Flag days with +5 bpm deviation (potential under-recovery)

3. **Sleep Debt Cumulative**
   - Running total of (7.5hr - actual sleep) per night
   - Show as area chart to visualize accumulation/paydown
   - Color: Green when debt < 2hr, Yellow 2-5hr, Red > 5hr

4. **Oura Readiness Trend**
   - Simple line chart of readiness score over time
   - Reference line at 85 (good readiness threshold)

**Training Mode Indicator:**

Large badge showing current training mode from weekly coach:
```python
if training_mode == "OPTIMAL":
    st.success("🟢 OPTIMAL - Recovery good, push hard")
elif training_mode == "MAINTENANCE":
    st.warning("🟡 MAINTENANCE - Reduce volume, focus on technique")
else:
    st.error("🔴 DELOAD - Body needs rest, light work only")

# Show rationale
st.caption(f"Reason: {mode_rationale}")
# Example: "Sleep debt >5hrs, HRV -15% from baseline"
```

**Filters:**
- Metric to highlight: HRV | Sleep | Resting HR | Readiness
- Show/hide training load overlay

---

### Section 4: Labs & Protocols Timeline

**Primary View: Gantt-style Timeline**

**Data Requirements:**
- Horizontal bars showing active periods for each protocol
- Vertical markers for lab draw dates
- Clickable elements to show details

**Query Pattern:**
```python
# Get all protocols
protocols = conn.execute("""
    SELECT 
        protocol_name,
        protocol_type,
        start_date,
        end_date,
        dosage,
        frequency
    FROM read_parquet('Data/Parquet/protocol_history/**/*.parquet')
    WHERE start_date >= ?
    ORDER BY protocol_type, start_date
""", [start_date]).df()

# Get lab dates
lab_dates = conn.execute("""
    SELECT DISTINCT test_date
    FROM read_parquet('Data/Parquet/labs_results/**/*.parquet')
    WHERE test_date >= ?
    ORDER BY test_date
""", [start_date]).df()
```

**Chart Implementation:**
```python
fig = go.Figure()

# Group protocols by type for color coding
protocol_types = protocols['protocol_type'].unique()
colors = {'TRT': 'blue', 'HGH': 'purple', 'Supplement': 'green', 'Compound': 'orange'}

for i, protocol in protocols.iterrows():
    # Handle ongoing protocols (end_date is null)
    end = protocol['end_date'] if pd.notna(protocol['end_date']) else datetime.now()
    
    fig.add_trace(go.Scatter(
        x=[protocol['start_date'], end],
        y=[protocol['protocol_name'], protocol['protocol_name']],
        mode='lines',
        line=dict(color=colors.get(protocol['protocol_type'], 'gray'), width=20),
        name=protocol['protocol_name'],
        hovertemplate=f"{protocol['protocol_name']}<br>" +
                      f"Dose: {protocol['dosage']}<br>" +
                      f"Freq: {protocol['frequency']}<extra></extra>"
    ))

# Add vertical lines for lab dates
for lab_date in lab_dates['test_date']:
    fig.add_vline(
        x=lab_date,
        line_dash="dot",
        line_color="red",
        annotation_text="Labs"
    )

fig.update_layout(
    title="Protocol Timeline",
    xaxis_title="Date",
    yaxis_title="",
    showlegend=False,
    height=400
)

st.plotly_chart(fig, use_container_width=True)
```

**Lab Results Table:**

Sortable/filterable table of recent lab results:
```python
# Get recent labs
recent_labs = conn.execute("""
    SELECT 
        test_date,
        biomarker_name,
        value,
        unit,
        reference_range_low,
        reference_range_high,
        lab_company
    FROM read_parquet('Data/Parquet/labs_results/**/*.parquet')
    WHERE test_date >= ?
    ORDER BY test_date DESC, biomarker_name
""", [datetime.now() - timedelta(days=180)]).df()

# Add status column
def get_status(row):
    if pd.isna(row['reference_range_low']) or pd.isna(row['reference_range_high']):
        return '⚪ Unknown'
    if row['value'] < row['reference_range_low']:
        return '🔴 Low'
    if row['value'] > row['reference_range_high']:
        return '🔴 High'
    # Check optimal ranges (tighter than reference)
    # This logic could be more sophisticated
    return '🟢 Optimal'

recent_labs['Status'] = recent_labs.apply(get_status, axis=1)

# Display with formatting
st.dataframe(
    recent_labs[['test_date', 'biomarker_name', 'value', 'unit', 'Status']],
    use_container_width=True,
    hide_index=True
)
```

**Protocol Detail Panel:**

When user clicks on timeline bar, show expandable detail:
```python
selected_protocol = st.selectbox(
    "View Protocol Details:",
    protocols['protocol_name'].unique()
)

if selected_protocol:
    protocol_detail = protocols[protocols['protocol_name'] == selected_protocol].iloc[0]
    
    with st.expander(f"📋 {selected_protocol}", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Start Date", protocol_detail['start_date'].strftime('%Y-%m-%d'))
        with col2:
            st.metric("Dosage", protocol_detail['dosage'])
        with col3:
            st.metric("Frequency", protocol_detail['frequency'])
        
        if pd.notna(protocol_detail['end_date']):
            st.info(f"Ended: {protocol_detail['end_date'].strftime('%Y-%m-%d')}")
        else:
            st.success("Currently Active")
```

**Key Use Case: "What was I taking when X changed?"**

Add interactive query feature:
```python
st.subheader("🔍 Protocol Query")

selected_biomarker = st.selectbox(
    "Show protocols active during changes in:",
    ['Ferritin', 'Testosterone', 'HDL', 'LDL', 'Hemoglobin']
)

if selected_biomarker:
    # Get biomarker change dates
    biomarker_data = conn.execute("""
        SELECT test_date, value
        FROM read_parquet('Data/Parquet/labs_results/**/*.parquet')
        WHERE biomarker_name = ?
        ORDER BY test_date
    """, [selected_biomarker]).df()
    
    # Find dates with significant changes (>10% from previous)
    # Then query overlapping protocols
    # Display as timeline with both biomarker values and active protocols
```

---

### Section 5: Correlation Explorer

**Interactive Scatter Plot:**

Allow user to select any two metrics and visualize correlation.

**Implementation:**
```python
st.subheader("🔍 Correlation Explorer")

col1, col2 = st.columns(2)

# Build metric options from available data
available_metrics = {
    'Ferritin': ('labs_results', 'Ferritin'),
    'Testosterone': ('labs_results', 'Testosterone'),
    'Zone 2 Power': ('concept2_workouts', 'avg_watts'),
    'Max HR': ('concept2_workouts', 'max_heart_rate'),
    'HRV': ('oura_daily_summaries', 'hrv_avg'),
    'Sleep Score': ('oura_daily_summaries', 'sleep_score'),
    'Bench Press Max': ('jefit_logs', 'weight_lbs', 'Barbell Bench Press'),
}

with col1:
    x_metric = st.selectbox("X-axis:", list(available_metrics.keys()))

with col2:
    y_metric = st.selectbox("Y-axis:", list(available_metrics.keys()), index=1)

# Query data for selected metrics
# This requires dynamic query building based on selections
# Join data by date to create scatter plot

# Calculate correlation
correlation = df.corr().iloc[0, 1]
st.metric("Correlation (R)", f"{correlation:.3f}")

# Plot
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=df[x_metric],
    y=df[y_metric],
    mode='markers',
    marker=dict(size=8, opacity=0.6),
    text=df['date'],  # Show date on hover
    hovertemplate='%{text}<br>X: %{x}<br>Y: %{y}<extra></extra>'
))

# Add trend line
from sklearn.linear_model import LinearRegression
model = LinearRegression()
X = df[[x_metric]].values
y = df[y_metric].values
model.fit(X, y)
trend_y = model.predict(X)

fig.add_trace(go.Scatter(
    x=df[x_metric],
    y=trend_y,
    mode='lines',
    name='Trend',
    line=dict(dash='dash', color='red')
))

st.plotly_chart(fig, use_container_width=True)
```

**Preset Correlations:**

Quick buttons for known interesting correlations:
```python
st.subheader("🎯 Preset Correlations")

presets = {
    "Power vs Ferritin": ("Zone 2 Power", "Ferritin"),
    "Max HR vs Ferritin": ("Max HR", "Ferritin"),
    "HRV vs Training Load": ("HRV", "Training Load"),
    "Sleep vs Next-Day HRV": ("Sleep Score", "HRV"),
}

preset_cols = st.columns(len(presets))
for i, (name, (x, y)) in enumerate(presets.items()):
    with preset_cols[i]:
        if st.button(name):
            # Update x_metric and y_metric selections
            # Re-run correlation analysis
            pass
```

**Color By Options:**
```python
color_by = st.radio(
    "Color points by:",
    ["None", "Protocol Active", "Training Phase", "Time Period"]
)

if color_by == "Protocol Active":
    # Query which protocols were active on each date
    # Color points by whether specific protocol was active
    pass
```

---

### Section 6: NOW Page (Dynamic Status)

**Current Phase:**
```python
st.subheader("📍 NOW - Current Status")

# This should be pulled from NOW.md Google Doc or hardcoded
current_phase = "Iron Recovery - Week 10/16"
phase_description = "Rebuilding ferritin stores to enable full cardiovascular training"

st.info(f"**{current_phase}**")
st.caption(phase_description)
```

**Key Biomarkers:**
```python
col1, col2, col3 = st.columns(3)

# Query latest values
latest_ferritin = conn.execute("""
    SELECT value, test_date
    FROM read_parquet('Data/Parquet/labs_results/**/*.parquet')
    WHERE biomarker_name = 'Ferritin'
    ORDER BY test_date DESC
    LIMIT 1
""").fetchone()

latest_max_hr = conn.execute("""
    SELECT MAX(max_heart_rate) as max_hr
    FROM read_parquet('Data/Parquet/concept2_workouts/**/*.parquet')
    WHERE workout_date >= ?
""", [datetime.now() - timedelta(days=7)]).fetchone()

with col1:
    st.metric(
        "Ferritin",
        f"{latest_ferritin[0]} ng/mL",
        delta=f"Target: >60",
        delta_color="off"
    )
    st.caption(f"Tested: {latest_ferritin[1].strftime('%Y-%m-%d')}")

with col2:
    st.metric(
        "Max HR (7d)",
        f"{latest_max_hr[0]} bpm",
        delta=f"Baseline: 161 ({latest_max_hr[0] - 161:+d})",
        delta_color="normal" if latest_max_hr[0] > 153 else "inverse"
    )

# Add more biomarkers as needed
```

**Active Protocols:**
```python
st.subheader("💊 Active Protocols")

active_protocols = conn.execute("""
    SELECT 
        protocol_name,
        protocol_type,
        dosage,
        frequency,
        start_date
    FROM read_parquet('Data/Parquet/protocol_history/**/*.parquet')
    WHERE end_date IS NULL  -- Still active
    ORDER BY protocol_type, protocol_name
""").df()

for _, protocol in active_protocols.iterrows():
    with st.expander(f"{protocol['protocol_name']} ({protocol['protocol_type']})"):
        st.write(f"**Dose:** {protocol['dosage']}")
        st.write(f"**Frequency:** {protocol['frequency']}")
        st.write(f"**Started:** {protocol['start_date'].strftime('%Y-%m-%d')}")
        st.write(f"**Duration:** {(datetime.now().date() - protocol['start_date']).days} days")
```

**Training Status:**
```python
st.subheader("🏋️ Training Status")

# Get current training mode from weekly coach
training_mode = "OPTIMAL"  # This should come from generate_weekly_report.py logic

mode_badge = {
    "OPTIMAL": ("🟢", "Recovery good - push hard"),
    "MAINTENANCE": ("🟡", "Reduce volume, maintain intensity"),
    "DELOAD": ("🔴", "Light work, focus on recovery")
}

badge, description = mode_badge[training_mode]
st.info(f"{badge} **{training_mode}** - {description}")

st.write("**Current Focus:**")
st.write("- Building Zone 2 cardiovascular base")
st.write("- Reintroducing resistance training at 70% previous volume")
st.write("- Monitoring HR response for chronotropic incompetence recovery")

st.write("**Restrictions:**")
st.write("- Max HR limited to ~150 bpm until ferritin >60")
st.write("- Avoid training to failure on lower body (GI stress)")
```

**Next Milestones:**
```python
st.subheader("🎯 Next Milestones")

milestones = [
    ("January 2026", "Comprehensive lab panel (GetHealthspan 86 markers)", "pending"),
    ("January 2026", "Ferritin recheck - must be >60 for cycle go-ahead", "pending"),
    ("February 2026", "Nandrolone cycle start (if criteria met)", "conditional"),
]

for date, description, status in milestones:
    if status == "pending":
        st.write(f"⏳ **{date}**: {description}")
    elif status == "conditional":
        st.write(f"❓ **{date}**: {description}")
```

**Recent Wins:**
```python
st.subheader("🏆 Recent Wins")

# Auto-populate from data
# Example: Check if any PRs in last 2 weeks

recent_prs = conn.execute("""
    SELECT 
        exercise_name,
        MAX(weight_lbs) as new_pr,
        workout_date
    FROM read_parquet('Data/Parquet/jefit_logs/**/*.parquet')
    WHERE workout_date >= ?
    GROUP BY exercise_name, workout_date
    -- Logic to compare against historical max
""", [datetime.now() - timedelta(days=14)]).df()

if len(recent_prs) > 0:
    for _, pr in recent_prs.iterrows():
        st.success(f"🎉 {pr['exercise_name']}: {pr['new_pr']} lbs PR on {pr['workout_date'].strftime('%m/%d')}")

# Also check cardio achievements
zone2_pr = conn.execute("""
    SELECT MAX(avg_watts) as max_watts, workout_date
    FROM read_parquet('Data/Parquet/concept2_workouts/**/*.parquet')
    WHERE workout_date >= ?
        AND workout_type = 'BikeErg'
""", [datetime.now() - timedelta(days=14)]).fetchone()

if zone2_pr and zone2_pr[0] >= 150:
    st.success(f"🚴 Sustained {zone2_pr[0]:.0f}W Zone 2 on {zone2_pr[1].strftime('%m/%d')}")
```

---

## Global Controls

### Time Range Selector

**Implementation:**
```python
st.sidebar.header("⚙️ Controls")

time_range = st.sidebar.selectbox(
    "Time Range",
    ["30 days", "90 days", "6 months", "1 year", "All time", "Custom"]
)

if time_range == "Custom":
    start_date = st.sidebar.date_input("Start Date")
    end_date = st.sidebar.date_input("End Date")
else:
    # Calculate dates based on selection
    range_days = {
        "30 days": 30,
        "90 days": 90,
        "6 months": 180,
        "1 year": 365,
        "All time": 3650  # ~10 years
    }
    end_date = datetime.now()
    start_date = end_date - timedelta(days=range_days[time_range])
```

This start_date and end_date should be passed to all query functions.

### Data Refresh

**Implementation:**
```python
if st.sidebar.button("🔄 Refresh Data"):
    # Clear all cached queries
    st.cache_data.clear()
    st.rerun()

# Show last refresh time
last_refresh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
st.sidebar.caption(f"Last refresh: {last_refresh}")
```

### Export Options (Stretch Goal)

```python
st.sidebar.header("📥 Export")

if st.sidebar.button("Download as PDF"):
    # Generate PDF of current dashboard state
    # This is complex and can be Phase 2
    pass

if st.sidebar.button("Export Data (CSV)"):
    # Allow user to download filtered data
    pass
```

---

## Performance Requirements

- **Initial load:** <5 seconds
- **Query execution:** <2 seconds per section
- **Mobile load:** <8 seconds on 4G
- **Use Streamlit caching:** `@st.cache_data` for all DuckDB queries

**Caching Example:**
```python
@st.cache_data(ttl=3600)  # Cache for 1 hour
def query_zone2_workouts(start_date, end_date):
    conn = duckdb.connect()
    return conn.execute("""
        SELECT * FROM read_parquet('Data/Parquet/concept2_workouts/**/*.parquet')
        WHERE workout_date BETWEEN ? AND ?
    """, [start_date, end_date]).df()
```

---

## Styling & UX

### Theme
```python
# In .streamlit/config.toml
[theme]
primaryColor = "#00CED1"  # Teal (cardiovascular)
backgroundColor = "#0E1117"  # Dark background
secondaryBackgroundColor = "#262730"  # Slightly lighter
textColor = "#FAFAFA"  # Light text
font = "sans serif"
```

### Color Palette
- **Cardiovascular:** Blue/Teal (#00CED1)
- **Strength:** Orange/Red (#FF6347)
- **Recovery:** Green (#32CD32)
- **Labs/Optimal:** Green (#32CD32)
- **Warning/Suboptimal:** Yellow (#FFD700)
- **Alert/Out of Range:** Red (#DC143C)

### Mobile Optimization
- Single column layout on mobile (Streamlit handles this automatically)
- Use `st.columns()` with responsive breakpoints
- Large touch targets (buttons min 44px)
- Collapsible sections via `st.expander()`
- Charts should use `use_container_width=True`

### Typography
- Headers: Bold, clear hierarchy (H1 > H2 > H3)
- Metrics: Large, readable numbers
- Captions: Smaller text for context
- Use emojis sparingly for visual anchors

---

## Development Phases

### Phase 1A: Foundation (This Week)

**Goal:** Get something impressive deployed

**Tasks:**
1. ✅ Setup Streamlit app structure
2. ✅ Implement global time range selector
3. ✅ Build Hero KPI cards with real data
4. ✅ Implement Cardiovascular section (Zone 2 chart + ferritin overlay)
5. ✅ Basic NOW page (hardcoded for now)
6. ✅ Mobile responsive testing

**Deliverable:** Working dashboard with 3 sections, deployed locally

**Time Estimate:** 8-12 hours

---

### Phase 1B: Enhancement (Next Week)

**Goal:** Add depth and deploy to cloud

**Tasks:**
1. ✅ Labs & Protocols timeline
2. ✅ Recovery metrics section
3. ✅ Polish mobile UX
4. ✅ Add caching for performance
5. ✅ Deploy to Streamlit Community Cloud
6. ✅ Test on actual phone

**Deliverable:** Deployed dashboard with 5 sections, public URL

**Time Estimate:** 6-8 hours

---

### Phase 2: Advanced Features (Later)

**Goal:** Build out remaining functionality

**Tasks:**
1. ⬜ Strength training section with weekly coach integration
2. ⬜ Correlation explorer
3. ⬜ Export functionality (PDF/CSV)
4. ⬜ NOW page from Google Doc (automated)
5. ⬜ Advanced visualizations
6. ⬜ User feedback iteration

**Deliverable:** Complete dashboard with all 6 sections

**Time Estimate:** 12-16 hours

---

## Out of Scope (For Now)

- User authentication
- Multi-user support
- Real-time data ingestion (use static Parquet snapshots)
- Editing data through UI
- Notifications/alerts
- Automated scheduling
- Integration with external APIs during runtime (data should be pre-loaded in Parquet)

---

## Questions to Resolve During Development

1. **NOW page content:** Should this be:
   - Hardcoded in the app initially?
   - Pulled from Google Doc via API?
   - Generated from data (current protocols + latest biomarkers)?
   
   **Recommendation:** Start with hardcoded, migrate to generated later.

2. **Weekly training plan link:** Should this:
   - Link to latest markdown file in `analysis/outputs/`?
   - Be embedded in the dashboard as a section?
   - Open in new tab vs scroll to section?
   
   **Recommendation:** Link to file, avoid duplicating content.

3. **Lactate data:** Is this:
   - In separate table?
   - Parsed from `concept2_workouts.comment` field?
   - Logged elsewhere?
   
   **Action:** Check `concept2_workouts` schema, parse from comments if present.

4. **Protocol timeline granularity:** Should we show:
   - Only major protocols (TRT, HGH, compounds)?
   - All supplements?
   - Configurable filter?
   
   **Recommendation:** Default to major protocols, add filter to show all.

5. **Exercise categorization:** Does `jefit_logs` have:
   - `exercise_category` field?
   - Need to be manually mapped?
   
   **Action:** Check schema, create mapping dict if needed.

---

## File Structure for Implementation

```
analysis/apps/
├── hdp_dashboard.py              # Main Streamlit app
├── components/
│   ├── kpi_cards.py              # Hero KPI cards
│   ├── cardiovascular.py         # Cardio section
│   ├── strength.py               # Strength section
│   ├── recovery.py               # Recovery section
│   ├── labs_protocols.py         # Labs & timeline
│   ├── correlation.py            # Correlation explorer
│   └── now_page.py               # NOW status page
├── utils/
│   ├── queries.py                # DuckDB query functions
│   ├── calculations.py           # Metric calculations
│   ├── formatting.py             # Chart formatting helpers
│   └── constants.py              # Color schemes, metric definitions
└── .streamlit/
    └── config.toml               # Theme configuration
```

**Main App Structure:**
```python
# hdp_dashboard.py
import streamlit as st
from components import kpi_cards, cardiovascular, strength, recovery, labs_protocols, now_page
from utils import queries

st.set_page_config(
    page_title="HDP Dashboard",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Sidebar controls
start_date, end_date = render_sidebar_controls()

# Header
render_header()

# Hero KPIs
kpi_cards.render(start_date, end_date)

# Main sections
with st.expander("📊 Cardiovascular Performance", expanded=True):
    cardiovascular.render(start_date, end_date)

with st.expander("💪 Strength Training", expanded=False):
    strength.render(start_date, end_date)

# ... etc
```

---

## Deployment Instructions

### Local Development

1. **Navigate to project root:**
   ```bash
   cd ~/health-data-pipeline
   ```

2. **Install dependencies:**
   ```bash
   poetry add streamlit plotly duckdb pandas scikit-learn
   ```

3. **Run dashboard:**
   ```bash
   streamlit run analysis/apps/hdp_dashboard.py
   ```

4. **Open browser:**
   - Should auto-open at `http://localhost:8501`
   - If not, navigate manually

### Deployment to Streamlit Community Cloud

1. **Push code to GitHub:**
   ```bash
   git add analysis/apps/
   git commit -m "Add HDP dashboard"
   git push origin main
   ```

2. **Create Streamlit Cloud account:**
   - Visit https://share.streamlit.io
   - Sign in with GitHub

3. **Deploy app:**
   - Click "New app"
   - Select repository: `health-data-pipeline`
   - Branch: `main`
   - Main file path: `analysis/apps/hdp_dashboard.py`
   - Click "Deploy"

4. **Configure (if needed):**
   - Set working directory to repo root
   - Add secrets (if using Google Drive API)
   - Configure custom domain (optional)

5. **Access deployed app:**
   - URL will be: `https://<username>-hdp-dashboard.streamlit.app`
   - Share this URL for demos

### Data Handling for Cloud Deployment

Since Parquet files are local and won't be in GitHub:

**Option A: Static Export**
- Export recent data to smaller Parquet files
- Include in repo (if <100 MB)
- Update via git push

**Option B: Cloud Storage**
- Upload Parquet files to Google Cloud Storage / S3
- Configure app to read from cloud
- More complex but enables real-time updates

**Recommendation for Phase 1:** Use Option A with 6-12 months of data exported to smaller files.

---

## Success Criteria

### Phase 1A Complete When:
- ✅ Dashboard loads without errors
- ✅ All KPI cards show real data with trends
- ✅ Cardiovascular chart renders with ferritin overlay
- ✅ Time range selector works and filters data
- ✅ Mobile layout is usable (test on phone)
- ✅ Load time <5 seconds

### Phase 1B Complete When:
- ✅ Labs timeline shows protocol history
- ✅ Recovery section shows HRV + training load
- ✅ App deployed to Streamlit Cloud with public URL
- ✅ All charts are interactive (zoom, pan, hover)
- ✅ No console errors
- ✅ Dashboard survives Peter's critique 😊

### Phase 2 Complete When:
- ✅ All 6 sections fully implemented
- ✅ Correlation explorer functional
- ✅ Export features work
- ✅ Weekly coach integration seamless
- ✅ Dashboard becomes Peter's primary health analytics tool

---

## Additional Context for CC

### Peter's Priorities

1. **Impressiveness > Completeness:** Better to have 3 polished sections than 6 half-baked ones
2. **Mobile-first:** Peter will demo this on his phone, so mobile UX is critical
3. **Data accuracy:** Get the queries right - bad data is worse than no data
4. **Performance:** Fast load times matter for demos
5. **Aesthetic:** This is a showcase - make it look professional

### Known Data Quirks

- **Lactate values:** May not be in structured table, might need parsing from comments
- **Exercise categories:** Might need manual mapping if not in schema
- **Protocol end dates:** Many will be NULL (ongoing), handle gracefully
- **Reference ranges:** Some biomarkers might not have reference_range fields
- **Timezone handling:** All data should be in UTC, but check assumptions

### Development Workflow

1. **Start simple:** Get one section working end-to-end before adding more
2. **Test with real data:** Use actual Parquet files, don't mock
3. **Iterate on visuals:** First make it work, then make it pretty
4. **Ask for clarification:** If schema is unclear, ask Peter or check docs
5. **Commit often:** Small, working increments

---

## Final Notes

This dashboard is:
- A personal showcase of Peter's HDP
- A demonstration of data-driven health optimization
- Potentially a commercial proof-of-concept

It should:
- Be impressive enough to show to trainers/coaches
- Surface insights Peter didn't know existed
- Make complex data accessible and actionable
- Work seamlessly on mobile for on-the-spot demos

It should NOT:
- Try to be a full medical EMR system
- Include features Peter won't use
- Sacrifice performance for features
- Be overly complex to maintain

---

**Good luck, CC! Build something awesome. 🚀**
