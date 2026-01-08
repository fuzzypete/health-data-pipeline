"""
Zone 2 Analysis Page - Detailed workout analysis with lactate intervals and cardiac drift.
"""
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# Import from parent directory
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.queries import (
    get_zone2_workouts_with_lactate,
    get_zone2_workout_analysis,
)

# =============================================================================
# Page Configuration
# =============================================================================

st.set_page_config(
    page_title="Zone 2 Analysis | HDP",
    page_icon="🚴",
    layout="wide",
)

st.title("Zone 2 Analysis")
st.caption("Detailed workout analysis with lactate intervals and cardiac drift")

# =============================================================================
# Workout Selector
# =============================================================================

# Get workouts with lactate data
workouts_df = get_zone2_workouts_with_lactate()

if workouts_df.empty:
    st.warning("No Zone 2 workouts with lactate data found.")
    st.stop()

# Create workout selector
workout_options = []
for _, row in workouts_df.iterrows():
    date_str = row['workout_date'].strftime('%Y-%m-%d') if hasattr(row['workout_date'], 'strftime') else str(row['workout_date'])
    readings = row['reading_count']
    lactate_range = f"{row['min_lactate']:.1f}-{row['max_lactate']:.1f}" if row['min_lactate'] != row['max_lactate'] else f"{row['min_lactate']:.1f}"
    label = f"{date_str} | {row['erg_type']} | {row['duration_min']:.0f}min | {readings} readings | {lactate_range} mmol/L"
    workout_options.append((label, row['workout_id']))

# Sidebar controls
with st.sidebar:
    st.header("Select Workout")

    selected_idx = st.selectbox(
        "Workout",
        range(len(workout_options)),
        format_func=lambda i: workout_options[i][0],
    )

    selected_workout_id = workout_options[selected_idx][1]

    st.divider()

    # Filter options
    st.subheader("Filter Options")
    show_multi_only = st.checkbox("Multi-reading only", value=False)

    if show_multi_only:
        workouts_df = workouts_df[workouts_df['reading_count'] > 1]

# =============================================================================
# Load Analysis Data
# =============================================================================

analysis = get_zone2_workout_analysis(str(selected_workout_id))

if "error" in analysis:
    st.error(f"Error loading workout: {analysis['error']}")
    st.stop()

workout = analysis["workout"]
lactate_readings = analysis["lactate_readings"]
intervals = analysis["intervals"]
cardiac_drift = analysis["cardiac_drift"]
stroke_summary = analysis["stroke_summary"]

# =============================================================================
# Workout Summary Header
# =============================================================================

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Duration", f"{workout['duration_min']:.0f} min")

with col2:
    st.metric("Avg HR", f"{workout['avg_hr_bpm']:.0f} bpm" if workout['avg_hr_bpm'] else "N/A")

with col3:
    if lactate_readings:
        first_lactate = lactate_readings[0]['lactate_mmol']
        last_lactate = lactate_readings[-1]['lactate_mmol']
        delta = last_lactate - first_lactate
        st.metric(
            "Lactate",
            f"{last_lactate:.1f} mmol/L",
            delta=f"{delta:+.1f}" if delta != 0 else None,
            delta_color="inverse",  # Lower is better
        )
    else:
        st.metric("Lactate", "No data")

with col4:
    drift_status = cardiac_drift.get('status', 'N/A')
    drift_color = {
        'Excellent': '🟢',
        'Good': '🟡',
        'Moderate': '🟠',
        'High': '🔴',
    }.get(drift_status, '⚪')
    st.metric("Cardiac Drift", f"{drift_color} {drift_status}")

st.divider()

# =============================================================================
# Main Charts
# =============================================================================

# Create combined chart with HR, Watts, and Lactate markers
if stroke_summary:
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.6, 0.4],
        subplot_titles=("Heart Rate & Lactate", "Power Output"),
    )

    stroke_df = pd.DataFrame(stroke_summary)

    # HR trace
    fig.add_trace(
        go.Scatter(
            x=stroke_df['minute'],
            y=stroke_df['hr'],
            mode='lines',
            name='Heart Rate',
            line=dict(color='#FF6B6B', width=2),
            hovertemplate='%{y:.0f} bpm<extra></extra>',
        ),
        row=1, col=1,
    )

    # Lactate markers
    if lactate_readings:
        lactate_times = [r['elapsed_minutes'] for r in lactate_readings]
        lactate_values = [r['lactate_mmol'] for r in lactate_readings]

        # Find HR at lactate reading times for positioning
        lactate_hrs = []
        for t in lactate_times:
            closest_hr = stroke_df.iloc[(stroke_df['minute'] - t).abs().argsort()[:1]]['hr'].values
            lactate_hrs.append(closest_hr[0] if len(closest_hr) > 0 else workout['avg_hr_bpm'])

        fig.add_trace(
            go.Scatter(
                x=lactate_times,
                y=lactate_hrs,
                mode='markers+text',
                name='Lactate Reading',
                marker=dict(size=15, color='#4ECDC4', symbol='diamond'),
                text=[f"{v:.1f}" for v in lactate_values],
                textposition='top center',
                textfont=dict(size=12, color='#4ECDC4'),
                hovertemplate='%{text} mmol/L @ %{x:.1f} min<extra></extra>',
            ),
            row=1, col=1,
        )

    # Power trace
    fig.add_trace(
        go.Scatter(
            x=stroke_df['minute'],
            y=stroke_df['watts'],
            mode='lines',
            name='Power',
            line=dict(color='#45B7D1', width=2),
            fill='tozeroy',
            fillcolor='rgba(69, 183, 209, 0.2)',
            hovertemplate='%{y:.0f}W<extra></extra>',
        ),
        row=2, col=1,
    )

    # Add vertical lines at lactate reading times
    if lactate_readings:
        for t in lactate_times:
            fig.add_vline(
                x=t,
                line_dash="dot",
                line_color="rgba(78, 205, 196, 0.5)",
                row="all",
            )

    fig.update_layout(
        template='plotly_dark',
        height=500,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02),
        margin=dict(l=0, r=0, t=40, b=0),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
    )

    fig.update_xaxes(title_text="Time (minutes)", row=2, col=1)
    fig.update_yaxes(title_text="HR (bpm)", row=1, col=1)
    fig.update_yaxes(title_text="Power (W)", row=2, col=1)

    st.plotly_chart(fig, width="stretch")

# =============================================================================
# Interval Analysis Table
# =============================================================================

st.subheader("Interval Analysis")

if intervals:
    interval_df = pd.DataFrame(intervals)

    # Format for display
    display_df = interval_df[[
        'interval', 'start_min', 'end_min', 'avg_watts', 'avg_hr',
        'hr_drift', 'avg_cadence', 'lactate_mmol'
    ]].copy()

    display_df.columns = [
        'Interval', 'Start (min)', 'End (min)', 'Avg Watts', 'Avg HR',
        'HR Drift', 'Cadence', 'Lactate'
    ]

    # Style the dataframe
    def style_drift(val):
        if val > 10:
            return 'color: #FF6B6B'
        elif val > 5:
            return 'color: #FFE66D'
        elif val < -5:
            return 'color: #4ECDC4'
        return ''

    styled_df = display_df.style.map(
        style_drift, subset=['HR Drift']
    ).format({
        'Start (min)': '{:.1f}',
        'End (min)': '{:.1f}',
        'Avg Watts': '{:.0f}',
        'Avg HR': '{:.0f}',
        'HR Drift': '{:+.1f}',
        'Cadence': '{:.0f}',
        'Lactate': '{:.1f}',
    })

    st.dataframe(styled_df, width="stretch", hide_index=True)
else:
    st.info("No interval data available (single lactate reading)")

# =============================================================================
# Cardiac Drift Details
# =============================================================================

st.subheader("Cardiac Drift Analysis")

col1, col2 = st.columns(2)

with col1:
    if cardiac_drift.get('drift_pct') is not None:
        excluded = cardiac_drift.get('excluded_samples', 0)
        excluded_note = f" ({excluded} pause samples excluded)" if excluded > 0 else ""

        st.markdown(f"""
        **Overall Drift:** {cardiac_drift['drift_bpm']:+.1f} bpm ({cardiac_drift['drift_pct']:+.1f}%)

        **Normalized:** {cardiac_drift['drift_per_hour_pct']:+.1f}% per hour

        | Period | HR | Power |
        |--------|-----|-------|
        | 1st Half ({cardiac_drift['early_period']}) | {cardiac_drift['early_hr']:.0f} bpm | {cardiac_drift['early_watts']:.0f}W |
        | 2nd Half ({cardiac_drift['late_period']}) | {cardiac_drift['late_hr']:.0f} bpm | {cardiac_drift['late_watts']:.0f}W |

        *{excluded_note}*
        """)
    else:
        st.info(f"Drift calculation: {cardiac_drift.get('status', 'N/A')}")

with col2:
    st.markdown("""
    **Cardiac Drift Interpretation:**

    | Drift/Hour | Status | Meaning |
    |------------|--------|---------|
    | <3% | 🟢 Excellent | Strong aerobic base |
    | 3-5% | 🟡 Good | Solid fitness |
    | 5-8% | 🟠 Moderate | Room to improve |
    | >8% | 🔴 High | Focus on base building |

    *Drift is measured at constant power output.*
    """)

# =============================================================================
# Lactate Trend
# =============================================================================

if len(lactate_readings) > 1:
    st.subheader("Lactate Progression")

    lactate_df = pd.DataFrame(lactate_readings)

    fig_lactate = go.Figure()

    fig_lactate.add_trace(
        go.Scatter(
            x=lactate_df['elapsed_minutes'],
            y=lactate_df['lactate_mmol'],
            mode='lines+markers',
            name='Lactate',
            line=dict(color='#4ECDC4', width=3),
            marker=dict(size=12),
            hovertemplate='%{y:.1f} mmol/L @ %{x:.1f} min<extra></extra>',
        )
    )

    # Add 2.0 mmol/L threshold line
    fig_lactate.add_hline(
        y=2.0,
        line_dash="dash",
        line_color="rgba(255, 107, 107, 0.7)",
        annotation_text="Zone 2 Threshold (2.0)",
        annotation_position="bottom right",
    )

    fig_lactate.update_layout(
        template='plotly_dark',
        height=300,
        xaxis_title="Time (minutes)",
        yaxis_title="Lactate (mmol/L)",
        margin=dict(l=0, r=0, t=20, b=0),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
    )

    st.plotly_chart(fig_lactate, width="stretch")

    # Lactate interpretation
    first_val = lactate_readings[0]['lactate_mmol']
    last_val = lactate_readings[-1]['lactate_mmol']

    if last_val < first_val:
        st.success(f"✅ Lactate decreased from {first_val:.1f} to {last_val:.1f} mmol/L - good clearance!")
    elif last_val == first_val:
        st.info(f"➡️ Lactate stable at {last_val:.1f} mmol/L")
    else:
        st.warning(f"⚠️ Lactate increased from {first_val:.1f} to {last_val:.1f} mmol/L - may be above Zone 2")
