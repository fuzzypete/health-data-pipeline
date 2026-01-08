"""
Historical Timeline Page - Correlate labs, protocols, and performance.
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
    query_labs,
    query_workouts,
    query_zone2_workouts,
)
from utils.constants import COLORS

# =============================================================================
# Page Configuration
# =============================================================================

st.set_page_config(
    page_title="Historical Timeline | HDP",
    page_icon="📈",
    layout="wide",
)

st.title("Historical Depletion & Recovery")
st.caption("Correlating labs, supplement protocols, and cardiovascular performance")

# =============================================================================
# Sidebar Controls
# =============================================================================

with st.sidebar:
    st.header("Timeline Settings")
    
    # Predefined periods
    period = st.selectbox(
        "Focus Period",
        ["Full Recovery (Oct 2025 - Present)", "Depletion Phase (2024-2025)", "All Time"],
        index=0
    )
    
    if period == "Full Recovery (Oct 2025 - Present)":
        start_date = datetime(2025, 10, 4)
        end_date = datetime.now()
    elif period == "Depletion Phase (2024-2025)":
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2025, 10, 4)
    else:
        start_date = datetime(2020, 1, 1)
        end_date = datetime.now()

    st.divider()
    
    # Metric toggles
    st.subheader("Metrics to Display")
    show_ferritin = st.checkbox("Ferritin", value=True)
    show_hdl = st.checkbox("HDL", value=True)
    show_max_hr = st.checkbox("Max HR (7d trend)", value=True)
    show_z2_power = st.checkbox("Zone 2 Power", value=True)
    
    st.divider()
    
    # Protocol toggles
    st.subheader("Protocols")
    show_iron = st.checkbox("Iron Protocol", value=True)
    show_niacin = st.checkbox("Niacin Protocol", value=True)

# =============================================================================
# Load Data
# =============================================================================

@st.cache_data(ttl=3600)
def get_timeline_data(start, end):
    # Labs
    labs_df = query_labs(start, end)
    
    # Workouts (all for max HR trend)
    workouts_df = query_workouts(start, end)
    if not workouts_df.empty:
        workouts_df['start_time_dt'] = pd.to_datetime(workouts_df['start_time_utc'])
        workouts_df['date'] = workouts_df['start_time_dt'].dt.date
        # 7-day rolling max HR (must be sorted by the 'on' column)
        workouts_df = workouts_df.sort_values('start_time_dt')
        workouts_df['max_hr_7d'] = workouts_df.rolling(window='7D', on='start_time_dt')['max_hr_bpm'].max()
    
    # Zone 2 Power
    z2_df = query_zone2_workouts(start, end, erg_type="bike")
    
    # Protocols (from duckdb directly since no query helper yet)
    from utils.queries import get_connection, _parquet_path
    conn = get_connection()
    try:
        prot_df = conn.execute(f"""
            SELECT compound_name, start_date, COALESCE(end_date, CURRENT_DATE) as end_date, dosage, dosage_unit
            FROM read_parquet('{_parquet_path("protocol_history")}')
            WHERE start_date >= '{start.date()}'
        """).df()
    except Exception:
        prot_df = pd.DataFrame()
        
    return labs_df, workouts_df, z2_df, prot_df

labs_df, workouts_df, z2_df, prot_df = get_timeline_data(start_date, end_date)

# =============================================================================
# Main Chart
# =============================================================================

fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.02,
    row_heights=[0.8, 0.2],
    specs=[[{"secondary_y": True}], [{"type": "xy"}]]
)

# 1. Performance & Labs (Top Row)

# Zone 2 Power (Left Axis)
if show_z2_power and not z2_df.empty:
    fig.add_trace(
        go.Scatter(
            x=z2_df['workout_date'],
            y=z2_df['avg_watts'],
            mode='lines+markers',
            name='Zone 2 Power (W)',
            line=dict(color=COLORS['cardio'], width=2),
            marker=dict(size=6),
            hovertemplate='%{y:.0f}W<extra></extra>',
        ),
        row=1, col=1, secondary_y=False
    )

# Max HR (Left Axis)
if show_max_hr and not workouts_df.empty:
    # Filter to sessions with high HR to show potential
    high_hr_sessions = workouts_df[workouts_df['max_hr_bpm'] > 110]
    fig.add_trace(
        go.Scatter(
            x=high_hr_sessions['date'],
            y=high_hr_sessions['max_hr_7d'],
            mode='lines',
            name='Max HR (7d Trend)',
            line=dict(color='#FF6B6B', width=3, dash='dot'),
            hovertemplate='%{y:.0f} bpm<extra></extra>',
        ),
        row=1, col=1, secondary_y=False
    )

# Ferritin (Right Axis)
if show_ferritin and not labs_df.empty:
    ferritin_df = labs_df[labs_df['biomarker_name'] == 'Ferritin']
    if not ferritin_df.empty:
        fig.add_trace(
            go.Scatter(
                x=ferritin_df['test_date'],
                y=ferritin_df['numeric_value'],
                mode='lines+markers',
                name='Ferritin (ng/mL)',
                line=dict(color=COLORS['ferritin'], width=4),
                marker=dict(size=10, symbol='diamond'),
                hovertemplate='%{y:.1f} ng/mL<extra></extra>',
            ),
            row=1, col=1, secondary_y=True
        )

# HDL (Right Axis)
if show_hdl and not labs_df.empty:
    hdl_df = labs_df[labs_df['biomarker_name'] == 'HDL']
    if not hdl_df.empty:
        fig.add_trace(
            go.Scatter(
                x=hdl_df['test_date'],
                y=hdl_df['numeric_value'],
                mode='lines+markers',
                name='HDL (mg/dL)',
                line=dict(color='#9370DB', width=3),
                marker=dict(size=8),
                hovertemplate='%{y:.1f} mg/dL<extra></extra>',
            ),
            row=1, col=1, secondary_y=True
        )

# 2. Protocols (Bottom Row - Swimlanes)
if not prot_df.empty:
    # Filter protocols if requested
    active_compounds = []
    if show_iron: active_compounds.append("Iron")
    if show_niacin: active_compounds.append("Niacin")
    
    display_prot = prot_df[prot_df['compound_name'].str.contains('|'.join(active_compounds), case=False)] if active_compounds else prot_df
    
    # Sort for consistent display
    uniques = sorted(display_prot['compound_name'].unique())
    
    for i, comp in enumerate(uniques):
        sub = display_prot[display_prot['compound_name'] == comp]
        
        # Create continuous lines for swimlanes
        x_pts, y_pts, txt_pts = [], [], []
        for _, row in sub.iterrows():
            x_pts.extend([row['start_date'], row['end_date'], None])
            y_pts.extend([comp, comp, None])
            txt_pts.extend([f"{row['dosage']} {row['dosage_unit']}", f"{row['dosage']} {row['dosage_unit']}", None])
            
        fig.add_trace(
            go.Scatter(
                x=x_pts, y=y_pts,
                mode='lines',
                line=dict(width=15),
                name=comp,
                hovertemplate=f"<b>{comp}</b><br>Dose: %{{text}}<extra></extra>",
                text=txt_pts,
                showlegend=False
            ),
            row=2, col=1
        )

# Layout adjustments
fig.update_layout(
    template='plotly_dark',
    height=700,
    hovermode='x unified',
    legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
    margin=dict(l=0, r=0, t=40, b=0),
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)',
)

fig.update_xaxes(title_text="Date", row=2, col=1)
fig.update_yaxes(title_text="Performance (W / bpm)", secondary_y=False, row=1, col=1)
fig.update_yaxes(title_text="Labs (ng/mL / mg/dL)", secondary_y=True, row=1, col=1)
fig.update_yaxes(showticklabels=True, row=2, col=1)

st.plotly_chart(fig, width="stretch")

# =============================================================================
# Insights & Stats
# =============================================================================

st.subheader("Key Phase Insights")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("**Recovery Milestones**")
    recovery_start = datetime(2025, 10, 4)
    days_in = (datetime.now() - recovery_start).days
    st.info(f"Day {days_in} of Recovery Phase")
    
    if not labs_df.empty:
        ferritin = labs_df[labs_df['biomarker_name'] == 'Ferritin']
        if not ferritin.empty:
            latest_f = ferritin.iloc[-1]['numeric_value']
            st.write(f"- Latest Ferritin: **{latest_f:.1f}** (Target: 70+)")

with col2:
    st.markdown("**Performance Trend**")
    if not z2_df.empty:
        avg_z2 = z2_df['avg_watts'].mean()
        peak_z2 = z2_df['avg_watts'].max()
        st.write(f"- Avg Z2 Power: **{avg_z2:.0f}W**")
        st.write(f"- Peak Z2 Power: **{peak_z2:.0f}W**")
    
    if not workouts_df.empty:
        recent_max = workouts_df['max_hr_bpm'].max()
        st.write(f"- Recent Max HR: **{recent_max:.0f} bpm**")

with col3:
    st.markdown("**Protocol Status**")
    if not prot_df.empty:
        ongoing = prot_df[pd.to_datetime(prot_df['end_date']).dt.date >= datetime.now().date()]
        if not ongoing.empty:
            for _, row in ongoing.iterrows():
                st.write(f"- 💊 **{row['compound_name']}**: {row['dosage']} {row['dosage_unit']}")
        else:
            st.write("No active protocols detected.")
