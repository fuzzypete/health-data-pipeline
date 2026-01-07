"""
VO2 Analysis Page - Detailed analysis of VO2 stimulus using Polar H10 respiratory data.
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
    get_vo2_interval_sessions,
    query_polar_respiratory,
    get_vo2_analysis,
    get_workout_stroke_data,
)

# =============================================================================
# Page Configuration
# =============================================================================

st.set_page_config(
    page_title="VO2 Analysis | HDP",
    page_icon="🫁",
    layout="wide",
)

st.title("VO2 Stimulus Analysis")
st.caption("Advanced cardiovascular analysis using ECG-derived respiratory rate (Polar H10)")

# =============================================================================
# Workout Selector
# =============================================================================

# Get workouts with Polar data (filtered for high intensity)
workouts_df = get_vo2_interval_sessions()

if workouts_df.empty:
    st.warning("No high-intensity workouts (Max HR >= 135) with Polar data found.")
    st.info("Zone 2 workouts are excluded from this analysis.")
    st.stop()

# Create workout selector
workout_options = []
for _, row in workouts_df.iterrows():
    date_str = row['workout_date'].strftime('%Y-%m-%d') if hasattr(row['workout_date'], 'strftime') else str(row['workout_date'])
    label = f"{date_str} | {row['erg_type']} | {row['duration_min']:.0f}min | Max HR: {row['max_hr_bpm']:.0f}"
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
    
    # Analysis parameters
    st.subheader("Analysis Parameters")
    warmup_min = st.slider("Warmup Duration (min)", 5, 15, 10)
    interval_sec = st.selectbox("Interval Duration (sec)", [30, 60], index=0)

# =============================================================================
# Load Analysis Data
# =============================================================================

analysis = get_vo2_analysis(str(selected_workout_id))

if "error" in analysis:
    st.error(f"Error calculating VO2 stimulus: {analysis['error']}")
    # Try to load just stroke data for visual
    stroke_df = get_workout_stroke_data(str(selected_workout_id))
    resp_df = query_polar_respiratory(str(selected_workout_id))
    summary = {}
    intervals = []
else:
    # Successfully got analysis
    stroke_df = get_workout_stroke_data(str(selected_workout_id))
    resp_df = query_polar_respiratory(str(selected_workout_id))
    summary = analysis.get("summary", {})
    intervals = analysis.get("intervals", [])

# =============================================================================
# Summary Header
# =============================================================================

col1, col2, col3, col4 = st.columns(4)

with col1:
    stimulus_min = summary.get("true_vo2_time_min", 0)
    st.metric("True VO2 Overlap", f"{stimulus_min:.1f} min")

with col2:
    max_rr = analysis.get("max_respiratory_rate", 0)
    st.metric("Peak Resp Rate", f"{max_rr:.1f} br/min" if max_rr else "N/A")

with col3:
    true_intervals = summary.get("true_vo2_intervals", 0)
    total_intervals = summary.get("total_intervals", 0)
    st.metric("3-Gate Convergence", f"{true_intervals}/{total_intervals}")

with col4:
    time_to_vo2 = summary.get("first_true_vo2_interval", None)
    # Each interval is ~1 min cycle
    st.metric("Start of Stimulus", f"{time_to_vo2} min" if time_to_vo2 else "N/A")

# Secondary summary
with st.expander("Session Details & Baselines", expanded=False):
    c1, c2, c3 = st.columns(3)
    with c1:
        st.write(f"**Session Max HR:** {analysis.get('session_max_hr', 'N/A')} bpm")
        st.write(f"**Warmup Used:** {analysis.get('warmup_min', 'N/A')} min")
    with c2:
        z2 = analysis.get("z2_baseline", {})
        st.write(f"**Z2 RR Median:** {z2.get('rr_median', 'N/A')} br/min")
        st.write(f"**Z2 RR MAD:** {z2.get('rr_mad', 'N/A')} br/min")
    with c3:
        st.write(f"**Probable VO2 Time:** {summary.get('probable_time_min', 0):.1f} min")
        st.write(f"**HR Load Count:** {summary.get('gate1_active_count', 0)} intervals")

st.divider()

# =============================================================================
# Main Chart: Stimulus Overlap Ribbon + Signals
# =============================================================================

if not stroke_df.empty:
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.4, 0.3, 0.3],
        subplot_titles=("Respiratory Rate & Overlap Zone", "Heart Rate", "Power Output"),
    )

    # 1. Respiratory Rate (Top Row)
    if not resp_df.empty:
        fig.add_trace(
            go.Scatter(
                x=resp_df['window_center_min'],
                y=resp_df['respiratory_rate'],
                mode='lines+markers',
                name='Resp Rate',
                line=dict(color='#32CD32', width=2),
                marker=dict(size=4),
                hovertemplate='%{y:.1f} br/min<extra></extra>',
            ),
            row=1, col=1,
        )
        
        # Add baseline threshold lines
        z2 = analysis.get("z2_baseline", {})
        if z2:
            rr_med = z2.get("rr_median", 28)
            rr_mad = z2.get("rr_mad", 2)
            hi_thresh = rr_med + max(6, 3 * rr_mad)
            
            fig.add_hline(
                y=hi_thresh, line_dash="dash", line_color="rgba(220, 20, 60, 0.5)",
                annotation_text=f"VO2 Zone ({hi_thresh:.1f})", row=1, col=1
            )
            fig.add_hline(
                y=rr_med, line_dash="dot", line_color="rgba(255, 215, 0, 0.5)",
                annotation_text=f"Z2 Baseline ({rr_med:.1f})", row=1, col=1
            )

    # 2. Add Overlap Ribbon (Background of Top Row)
    if intervals:
        for interval in intervals:
            color = 'rgba(128,128,128,0.05)'  # Default empty
            
            if interval['confidence'] == 'TRUE_VO2':
                color = 'rgba(148,0,211,0.4)'  # Purple (all 3)
            elif interval['gates_active'] == 2:
                color = 'rgba(255,165,0,0.2)'  # Orange (2 gates)
            elif interval['gate1_active']:
                color = 'rgba(0,0,255,0.1)'    # Blue (HR only)
            
            fig.add_vrect(
                x0=interval['interval_start_min'],
                x1=interval['interval_end_min'],
                fillcolor=color,
                layer="below",
                line_width=0,
                row=1, col=1
            )

    # 3. Heart Rate (Middle Row)
    fig.add_trace(
        go.Scatter(
            x=stroke_df['elapsed_min'],
            y=stroke_df['heart_rate_bpm'],
            mode='lines',
            name='Heart Rate',
            line=dict(color='#FF6B6B', width=2),
            hovertemplate='%{y:.0f} bpm<extra></extra>',
        ),
        row=2, col=1,
    )
    
    # Add Gate 1 Threshold (90% of max)
    if analysis.get("session_max_hr"):
        hcl_thresh = analysis["session_max_hr"] * 0.9
        fig.add_hline(
            y=hcl_thresh, line_dash="dash", line_color="rgba(255, 107, 107, 0.5)",
            annotation_text=f"90% Max ({hcl_thresh:.0f})", row=2, col=1
        )
    
    # 4. Power (Bottom Row)
    fig.add_trace(
        go.Scatter(
            x=stroke_df['elapsed_min'],
            y=stroke_df['watts'],
            mode='lines',
            name='Power',
            line=dict(color='#00CED1', width=2),
            fill='tozeroy',
            fillcolor='rgba(0, 206, 209, 0.2)',
            hovertemplate='%{y:.0f}W<extra></extra>',
        ),
        row=3, col=1,
    )

    fig.update_layout(
        template='plotly_dark',
        height=800,
        hovermode='x unified',
        legend=dict(orientation='h', yanchor='bottom', y=1.02),
        margin=dict(l=0, r=0, t=40, b=0),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
    )

    fig.update_xaxes(title_text="Time (minutes)", row=3, col=1)
    fig.update_yaxes(title_text="br/min", row=1, col=1)
    fig.update_yaxes(title_text="bpm", row=2, col=1)
    fig.update_yaxes(title_text="Watts", row=3, col=1)

    st.plotly_chart(fig, use_container_width=True)

# =============================================================================
# Stimulus Analysis Tables
# =============================================================================

col1, col2 = st.columns(2)

with col1:
    st.subheader("3-Gate Interval Status")
    if intervals:
        overlap_df = pd.DataFrame(intervals)
        
        # Color scale for confidence
        def color_conf(val):
            if val == 'TRUE_VO2': return 'background-color: rgba(148, 0, 211, 0.3)'
            if val == 'PROBABLE': return 'background-color: rgba(255, 165, 0, 0.2)'
            if val == 'APPROACHING': return 'background-color: rgba(0, 0, 255, 0.1)'
            return ''
        
        display_df = overlap_df[[
            'interval_number', 'gates_active', 'confidence', 
            'gate1_active', 'gate2_active', 'gate3_active'
        ]].copy()
        
        styled_df = display_df.style.applymap(
            color_conf, subset=['confidence']
        )
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
    else:
        st.info("No interval data available.")

with col2:
    st.subheader("Gate Details")
    if intervals:
        # Show specific metrics for each gate
        metrics_df = pd.DataFrame(intervals)[[
            'interval_number', 'gate1_hr_pct', 'gate2_rr', 'gate3_hr_drop'
        ]]
        
        metrics_df.columns = ['#', 'HR % Max', 'RR (br/min)', 'HR Drop']
        
        st.dataframe(
            metrics_df.style.format({
                'HR % Max': '{:.1%}',
                'RR (br/min)': '{:.1f}',
                'HR Drop': '{:+.1f}'
            }), 
            use_container_width=True, 
            hide_index=True
        )

# =============================================================================
# Information Footer
# =============================================================================

st.divider()
with st.expander("About Geepy's VO2 Stimulus Model"):
    st.markdown("""
    This analysis implements the framework for detecting true VO₂ stimulus:
    
    1.  **Autonomic Stress (HR Drop):** As the session progresses, the parasympathetic nervous system's ability to lower HR during easy intervals collapses. 
        - **Early Phase:** HR drop > 8 bpm (Good recovery)
        - **Mid Phase:** HR drop 3-8 bpm (Transitional stress)
        - **Late Phase (VO2 Zone):** HR drop <= 2 bpm (Autonomic collapse)
        
    2.  **Ventilatory Demand (Resp Rate):** ECG-Derived Respiration (EDR) provides a proxy for breathing rate.
        - **< 30 br/min:** Aerobic base
        - **30-38 br/min:** Aerobic/Anaerobic threshold
        - **>= 38 br/min:** VO2 max stimulus zone
        
    **Why both?** High RR proves the metabolic demand is there, while the HR drop collapse proves the autonomic system is sufficiently stressed to trigger adaptation.
    """)
