#!/usr/bin/env python3
"""
HDP Dashboard - Personal Health Data Pipeline

A Streamlit-based dashboard showcasing Peter's Health Data Pipeline.
Mobile-first design for on-the-spot demos.

Usage:
    cd ~/src/health-data-pipeline
    streamlit run analysis/apps/hdp_dashboard.py
"""

from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots


def check_password() -> bool:
    """Simple password protection for deployment.

    Returns True if password is correct or not configured.
    Uses st.secrets for the password (set in Streamlit Cloud).
    """
    # Skip auth if no password configured (local dev)
    if "password" not in st.secrets:
        return True

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    st.title("HDP Dashboard")
    st.markdown("---")

    password = st.text_input("Enter password to access dashboard:", type="password")

    if password:
        if password == st.secrets["password"]:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")

    st.stop()
    return False

# Import utilities
from utils.constants import (
    BIOMARKER_TARGETS,
    CARDIO_BASELINES,
    COLORS,
    TIME_RANGES,
    get_date_range,
)
from utils.queries import (
    get_latest_ferritin,
    get_max_hr_7d,
    get_weekly_training_volume,
    query_ferritin,
    query_hrv_data,
    query_labs,
    query_lactate,
    query_lift_maxes,
    query_oura_summary,
    query_workouts,
    query_zone2_workouts,
)

# =============================================================================
# Page Configuration
# =============================================================================

st.set_page_config(
    page_title="HDP Dashboard",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =============================================================================
# Custom CSS for Mobile-First Design
# =============================================================================

st.markdown("""
<style>
    /* Reduce padding for mobile */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
    }

    /* Larger touch targets for mobile */
    .stButton button {
        min-height: 44px;
        font-size: 1rem;
    }

    /* KPI card styling */
    .kpi-card {
        background-color: #262730;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 0.5rem;
    }

    /* Status colors */
    .status-optimal { color: #32CD32; }
    .status-good { color: #90EE90; }
    .status-warning { color: #FFD700; }
    .status-alert { color: #DC143C; }

    /* Mobile responsiveness */
    @media (max-width: 768px) {
        .block-container {
            padding-left: 0.5rem;
            padding-right: 0.5rem;
        }
    }
</style>
""", unsafe_allow_html=True)


# =============================================================================
# Sidebar Controls
# =============================================================================


def render_sidebar() -> tuple[datetime, datetime]:
    """Render sidebar controls and return date range."""
    st.sidebar.header("Controls")

    # Time range selector
    time_range = st.sidebar.selectbox(
        "Time Range",
        options=list(TIME_RANGES.keys()),
        index=1,  # Default: 90 days
        help="Select time range for all charts",
    )

    start_date, end_date = get_date_range(time_range)

    # Custom date range option
    if st.sidebar.checkbox("Custom dates", value=False):
        col1, col2 = st.sidebar.columns(2)
        with col1:
            start_date = datetime.combine(
                st.date_input("Start", value=start_date.date()),
                datetime.min.time()
            )
        with col2:
            end_date = datetime.combine(
                st.date_input("End", value=end_date.date()),
                datetime.max.time()
            )

    # Display selected range
    days = (end_date - start_date).days
    st.sidebar.caption(f"Showing {days} days of data")

    st.sidebar.divider()

    # Refresh button
    if st.sidebar.button("Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    # Last refresh timestamp
    st.sidebar.caption(f"Last refresh: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    return start_date, end_date


# =============================================================================
# Header
# =============================================================================


def render_header():
    """Render dashboard header."""
    col1, col2, col3 = st.columns([3, 1, 1])

    with col1:
        st.title("HDP Dashboard")

    with col2:
        st.link_button(
            "Weekly Plan",
            url="https://github.com/pwickersham/health-data-pipeline",
            help="View weekly training plan",
        )

    with col3:
        st.link_button(
            "NOW",
            url="#now-current-status",
            help="Jump to current status",
        )


# =============================================================================
# KPI Cards
# =============================================================================


def render_kpi_card(
    title: str,
    value: str,
    delta: str | None = None,
    delta_color: str = "normal",
    target: str | None = None,
    sparkline_data: pd.Series | None = None,
):
    """Render a single KPI card with optional sparkline."""
    st.metric(
        label=title,
        value=value,
        delta=delta,
        delta_color=delta_color,
    )
    if target:
        st.caption(f"Target: {target}")
    if sparkline_data is not None and not sparkline_data.empty:
        st.line_chart(sparkline_data, height=50)


def render_hero_kpis(start_date: datetime, end_date: datetime):
    """Render the hero KPI cards row."""
    st.subheader("Key Metrics")

    # Create 3 columns for mobile-friendly layout (2x3 on desktop)
    cols = st.columns(3)

    # KPI 1: Ferritin
    with cols[0]:
        ferritin = get_latest_ferritin()
        if ferritin:
            delta_str = f"{ferritin['trend_pct']:+.1f}%" if ferritin.get("trend_pct") else None
            render_kpi_card(
                title="Ferritin",
                value=f"{ferritin['value']:.0f} {ferritin['unit']}",
                delta=delta_str,
                target=f">{ferritin['target']} {ferritin['unit']}",
            )
        else:
            st.metric("Ferritin", "No data")

    # KPI 2: Max HR (7d)
    with cols[1]:
        max_hr = get_max_hr_7d()
        if max_hr:
            render_kpi_card(
                title="Max HR (7d)",
                value=f"{max_hr['value']} bpm",
                delta=f"{max_hr['deficit']:+d} from peak",
                delta_color="inverse",  # Negative is bad
            )
        else:
            st.metric("Max HR (7d)", "No workouts")

    # KPI 3: Weekly Volume
    with cols[2]:
        volume = get_weekly_training_volume()
        if volume:
            render_kpi_card(
                title="Week Volume",
                value=f"{volume['total']} min",
                target=f"Cardio: {volume['cardio']}min | Strength: {volume['strength']}min",
            )
        else:
            st.metric("Week Volume", "0 min")

    # Second row of KPIs
    cols2 = st.columns(3)

    # KPI 4: HRV (latest)
    with cols2[0]:
        oura_data = query_oura_summary(
            start_date=datetime.now() - timedelta(days=7),
            end_date=datetime.now()
        )
        if not oura_data.empty and "hrv_ms" in oura_data.columns:
            latest_hrv = oura_data.iloc[-1]["hrv_ms"]
            avg_hrv = oura_data["hrv_ms"].mean()
            if pd.notna(latest_hrv):
                delta_pct = ((latest_hrv - avg_hrv) / avg_hrv * 100) if avg_hrv > 0 else 0
                st.metric(
                    "HRV (today)",
                    f"{latest_hrv:.0f} ms",
                    delta=f"{delta_pct:+.1f}% vs 7d avg",
                )
            else:
                st.metric("HRV", "No data")
        else:
            st.metric("HRV", "No Oura data")

    # KPI 5: Sleep Score
    with cols2[1]:
        if not oura_data.empty and "sleep_score" in oura_data.columns:
            latest_sleep = oura_data.iloc[-1]["sleep_score"]
            if pd.notna(latest_sleep):
                status = "optimal" if latest_sleep >= 85 else "good" if latest_sleep >= 70 else "warning"
                st.metric("Sleep Score", f"{latest_sleep:.0f}")
            else:
                st.metric("Sleep Score", "No data")
        else:
            st.metric("Sleep Score", "No Oura data")

    # KPI 6: Readiness
    with cols2[2]:
        if not oura_data.empty and "readiness_score" in oura_data.columns:
            latest_readiness = oura_data.iloc[-1]["readiness_score"]
            if pd.notna(latest_readiness):
                st.metric("Readiness", f"{latest_readiness:.0f}")
            else:
                st.metric("Readiness", "No data")
        else:
            st.metric("Readiness", "No Oura data")


# =============================================================================
# Cardiovascular Section
# =============================================================================


def render_cardiovascular_section(start_date: datetime, end_date: datetime):
    """Render the cardiovascular performance section."""
    with st.expander("Cardiovascular Performance", expanded=True):
        # Query data
        zone2_workouts = query_zone2_workouts(start_date, end_date, erg_type="bike")
        ferritin_data = query_ferritin(start_date, end_date)

        if zone2_workouts.empty:
            st.info("No Zone 2 workouts found in this period.")
            return

        # Create dual-axis chart: Zone 2 Power + Ferritin
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        # Zone 2 Power (primary axis)
        fig.add_trace(
            go.Scatter(
                x=zone2_workouts["workout_date"],
                y=zone2_workouts["avg_watts"],
                mode="markers+lines",
                name="Zone 2 Power",
                marker=dict(size=8, color=COLORS["cardio"]),
                line=dict(color=COLORS["cardio"], width=2),
                hovertemplate="Date: %{x}<br>Power: %{y:.0f}W<extra></extra>",
            ),
            secondary_y=False,
        )

        # Ferritin overlay (secondary axis)
        if not ferritin_data.empty:
            fig.add_trace(
                go.Scatter(
                    x=ferritin_data["test_date"],
                    y=ferritin_data["numeric_value"],
                    mode="lines+markers",
                    name="Ferritin",
                    marker=dict(size=10, symbol="diamond", color=COLORS["ferritin"]),
                    line=dict(color=COLORS["ferritin"], dash="dash", width=2),
                    hovertemplate="Date: %{x}<br>Ferritin: %{y:.0f} ng/mL<extra></extra>",
                ),
                secondary_y=True,
            )

            # Ferritin target line
            fig.add_hline(
                y=60,
                line_dash="dot",
                line_color=COLORS["optimal"],
                annotation_text="Ferritin Target (60)",
                secondary_y=True,
            )

        # Zone 2 power peak reference
        peak_z2 = CARDIO_BASELINES["zone2_power_peak"]
        fig.add_hline(
            y=peak_z2,
            line_dash="dash",
            line_color=COLORS["primary"],
            annotation_text=f"Z2 Peak ({peak_z2}W)",
            secondary_y=False,
        )

        fig.update_layout(
            title="Zone 2 Power Progression + Ferritin",
            hovermode="x unified",
            height=400,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=0, r=0, t=60, b=0),
        )
        fig.update_xaxes(title_text="Date")
        fig.update_yaxes(title_text="Power (watts)", secondary_y=False)
        fig.update_yaxes(title_text="Ferritin (ng/mL)", secondary_y=True)

        st.plotly_chart(fig, use_container_width=True)

        # Summary metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            avg_watts = zone2_workouts["avg_watts"].mean()
            st.metric("Avg Z2 Power", f"{avg_watts:.0f}W")
        with col2:
            max_watts = zone2_workouts["avg_watts"].max()
            st.metric("Max Z2 Power", f"{max_watts:.0f}W")
        with col3:
            workouts_count = len(zone2_workouts)
            st.metric("Z2 Sessions", f"{workouts_count}")


# =============================================================================
# Recovery Section
# =============================================================================


def render_recovery_section(start_date: datetime, end_date: datetime):
    """Render the recovery metrics section."""
    with st.expander("Recovery Metrics", expanded=False):
        oura_data = query_oura_summary(start_date, end_date)

        if oura_data.empty:
            st.info("No Oura data found in this period.")
            return

        # HRV + Readiness trend
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        if "hrv_ms" in oura_data.columns:
            fig.add_trace(
                go.Scatter(
                    x=oura_data["day"],
                    y=oura_data["hrv_ms"],
                    mode="lines",
                    name="HRV (ms)",
                    line=dict(color=COLORS["recovery"], width=2),
                ),
                secondary_y=False,
            )

        if "readiness_score" in oura_data.columns:
            fig.add_trace(
                go.Bar(
                    x=oura_data["day"],
                    y=oura_data["readiness_score"],
                    name="Readiness",
                    marker_color=COLORS["primary"],
                    opacity=0.4,
                ),
                secondary_y=True,
            )

        fig.update_layout(
            title="HRV & Readiness Trend",
            height=350,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=0, r=0, t=60, b=0),
        )
        fig.update_yaxes(title_text="HRV Score", secondary_y=False)
        fig.update_yaxes(title_text="Readiness Score", secondary_y=True)

        st.plotly_chart(fig, use_container_width=True)

        # Sleep metrics
        if "total_sleep_duration_hr" in oura_data.columns:
            st.subheader("Sleep")

            avg_sleep = oura_data["total_sleep_duration_hr"].mean()
            target_sleep = 7.5
            sleep_debt = (target_sleep - avg_sleep) * 7  # Weekly debt

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Avg Sleep", f"{avg_sleep:.1f} hr")
            with col2:
                st.metric("Target", f"{target_sleep} hr")
            with col3:
                delta_color = "inverse" if sleep_debt > 0 else "normal"
                st.metric(
                    "Weekly Debt",
                    f"{abs(sleep_debt):.1f} hr",
                    delta="deficit" if sleep_debt > 0 else "surplus",
                    delta_color=delta_color,
                )


# =============================================================================
# Strength Section
# =============================================================================


def render_strength_section(start_date: datetime, end_date: datetime):
    """Render the strength training section."""
    with st.expander("Strength Training", expanded=False):
        # Key compound lifts
        key_lifts = ["Barbell Bench Press", "Barbell Squat", "Deadlift", "Overhead Press"]
        lift_data = query_lift_maxes(start_date, end_date, exercises=key_lifts)

        if lift_data.empty:
            st.info("No strength training data found in this period.")
            return

        # Multi-line chart of lift progression
        fig = go.Figure()

        for lift in key_lifts:
            lift_subset = lift_data[lift_data["exercise_name"] == lift]
            if not lift_subset.empty:
                fig.add_trace(
                    go.Scatter(
                        x=lift_subset["workout_date"],
                        y=lift_subset["max_weight"],
                        mode="lines+markers",
                        name=lift,
                        marker=dict(size=6),
                        line=dict(width=2),
                    )
                )

        fig.update_layout(
            title="Key Lift Progression",
            xaxis_title="Date",
            yaxis_title="Weight (lbs)",
            hovermode="x unified",
            height=350,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=0, r=0, t=60, b=0),
        )

        st.plotly_chart(fig, use_container_width=True)


# =============================================================================
# NOW Section
# =============================================================================


def render_now_section(start_date: datetime, end_date: datetime):
    """Render the NOW / current status section."""
    with st.expander("NOW - Current Status", expanded=False):
        st.markdown("### Current Phase")
        st.info("**Iron Recovery - Week 10/16**")
        st.caption("Rebuilding ferritin stores to enable full cardiovascular training")

        # Key biomarkers status
        st.markdown("### Decision Gates: Nandrolone (Feb 2026)")

        # Query latest values for gates
        gates = [
            ("Ferritin", ">60 ng/mL", 60, "gt"),
            ("HDL", ">55 mg/dL", 55, "gt"),
            ("ALT", "<65 U/L", 65, "lt"),
            ("Hematocrit", "<52%", 52, "lt"),
        ]

        col1, col2, col3, col4 = st.columns(4)
        columns = [col1, col2, col3, col4]

        for i, (biomarker, target_str, target_val, comparison) in enumerate(gates):
            latest = None
            labs = query_labs(
                start_date=datetime.now() - timedelta(days=365),
                end_date=datetime.now(),
                biomarker=biomarker,
            )
            if not labs.empty:
                latest = labs.iloc[-1]["numeric_value"]

            with columns[i]:
                if latest:
                    if comparison == "gt":
                        met = latest > target_val
                    else:
                        met = latest < target_val

                    status = "met" if met else "close" if abs(latest - target_val) / target_val < 0.1 else "not met"
                    status_emoji = {"met": "OK", "close": "~", "not met": "X"}[status]

                    st.metric(biomarker, f"{latest:.0f}", delta=status_emoji)
                else:
                    st.metric(biomarker, "No data")

        # Current focus
        st.markdown("### Current Focus")
        st.markdown("""
        - Building Zone 2 cardiovascular base
        - Reintroducing resistance training at 70% previous volume
        - Monitoring HR response for chronotropic incompetence recovery
        """)


# =============================================================================
# Main App
# =============================================================================


def main():
    """Main dashboard application."""
    # Password protection (only active when secrets configured)
    check_password()

    # Sidebar
    start_date, end_date = render_sidebar()

    # Header
    render_header()

    # Hero KPIs
    render_hero_kpis(start_date, end_date)

    st.divider()

    # Main sections
    render_cardiovascular_section(start_date, end_date)
    render_recovery_section(start_date, end_date)
    render_strength_section(start_date, end_date)
    render_now_section(start_date, end_date)

    # Footer
    st.divider()
    st.caption(
        "Health Data Pipeline Dashboard | "
        f"Data range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
    )


if __name__ == "__main__":
    main()
