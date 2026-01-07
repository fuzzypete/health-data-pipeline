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
    get_cardio_score_data,
    get_latest_ferritin,
    get_max_hr_7d,
    get_recovery_score_data,
    get_vitals_score_data,
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
from utils.scores import (
    calculate_cardio_score,
    calculate_recovery_score,
    calculate_vitals_score,
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


# =============================================================================
# Score Cards (PRS, PCS, PVS)
# =============================================================================

STATUS_COLORS = {
    "green": "#32CD32",
    "yellow": "#FFD700",
    "orange": "#FFA500",
    "red": "#DC143C",
}

STATUS_EMOJIS = {
    "Optimal": "🟢",
    "Moderate": "🟡",
    "Compromised": "🟠",
    "Recovery Needed": "🔴",
    "Excellent": "🟢",
    "Good": "🟡",
    "Attention": "🟠",
    "Impaired": "🔴",
    "Concern": "🔴",
}


def render_score_progress_bar(score: int, color: str) -> str:
    """Generate HTML for a score progress bar."""
    filled = int(score / 100 * 20)
    empty = 20 - filled
    bar_color = STATUS_COLORS.get(color, "#888")
    return f'<span style="color: {bar_color};">{"█" * filled}</span><span style="color: #444;">{"░" * empty}</span>'


def render_recovery_score_card():
    """Render Peter's Recovery Score (PRS) card with drill-down."""
    # Fetch data
    data = get_recovery_score_data()

    # Calculate score
    score = calculate_recovery_score(
        sleep_duration_hours=data.get("sleep_duration_hours", 0),
        sleep_efficiency_pct=data.get("sleep_efficiency_pct"),
        sleep_debt_hours=data.get("sleep_debt_hours", 0),
        current_hrv=data.get("current_hrv"),
        baseline_hrv=data.get("baseline_hrv", 40),
        current_rhr=data.get("current_rhr"),
        baseline_rhr=data.get("baseline_rhr", 55),
        acute_load_min=data.get("acute_load_min", 0),
        chronic_load_min=data.get("chronic_load_min", 0),
        days_since_rest=data.get("days_since_rest", 0),
        yesterday_workout_type=data.get("yesterday_workout_type"),
    )

    emoji = STATUS_EMOJIS.get(score.status, "")

    # Main score display
    st.markdown(f"### {emoji} Recovery Score")

    col1, col2 = st.columns([3, 1])
    with col1:
        st.progress(score.total / 100)
    with col2:
        st.markdown(f"**{score.total}**")

    st.caption(f"{score.status}")

    # Expandable tier breakdown
    with st.expander("Score Breakdown", expanded=False):
        # Sleep & Rest Tier
        tier = score.tiers["sleep_rest"]
        st.markdown(f"**Sleep & Rest ({tier.weight})** — {tier.score}")
        for comp_name, comp_score in tier.components.items():
            display_name = comp_name.replace("_", " ").title()
            col1, col2 = st.columns([3, 1])
            with col1:
                st.progress(comp_score / 100)
            with col2:
                st.write(f"{comp_score}")
            st.caption(display_name)

        st.divider()

        # Autonomic Tier
        tier = score.tiers["autonomic"]
        st.markdown(f"**Autonomic State ({tier.weight})** — {tier.score}")
        for comp_name, comp_score in tier.components.items():
            display_name = comp_name.replace("_", " ").title()
            col1, col2 = st.columns([3, 1])
            with col1:
                st.progress(comp_score / 100)
            with col2:
                st.write(f"{comp_score}")
            st.caption(display_name)

        st.divider()

        # Training Load Tier
        tier = score.tiers["training_load"]
        st.markdown(f"**Training Load ({tier.weight})** — {tier.score}")
        for comp_name, comp_score in tier.components.items():
            display_name = comp_name.replace("_", " ").title()
            col1, col2 = st.columns([3, 1])
            with col1:
                st.progress(comp_score / 100)
            with col2:
                st.write(f"{comp_score}")
            st.caption(display_name)


def render_cardio_score_card():
    """Render Peter's Cardio Score (PCS) card with drill-down."""
    # Fetch data
    data = get_cardio_score_data()

    # Calculate score
    score = calculate_cardio_score(
        recent_max_hr=data.get("recent_max_hr", 0),
        current_zone2_watts=data.get("current_zone2_watts", 0),
        hr_response_minutes=data.get("hr_response_minutes"),
        hr_recovery_1min=data.get("hr_recovery_1min"),
        current_efficiency=data.get("current_efficiency"),
        best_efficiency=data.get("best_efficiency", 1.0),
        resting_hr=data.get("resting_hr"),
        current_hrv=data.get("current_hrv"),
        baseline_hrv=data.get("baseline_hrv", 40),
    )

    emoji = STATUS_EMOJIS.get(score.status, "")

    # Main score display
    st.markdown(f"### {emoji} Cardio Score")

    col1, col2 = st.columns([3, 1])
    with col1:
        st.progress(score.total / 100)
    with col2:
        st.markdown(f"**{score.total}**")

    st.caption(f"{score.status}")

    # Expandable tier breakdown
    with st.expander("Score Breakdown", expanded=False):
        # Capacity Tier
        tier = score.tiers["capacity_ceiling"]
        st.markdown(f"**Capacity & Ceiling ({tier.weight})** — {tier.score}")
        for comp_name, comp_score in tier.components.items():
            display_name = comp_name.replace("_", " ").title()
            col1, col2 = st.columns([3, 1])
            with col1:
                st.progress(comp_score / 100)
            with col2:
                st.write(f"{comp_score}")
            st.caption(display_name)

        st.divider()

        # Responsiveness Tier
        tier = score.tiers["responsiveness"]
        is_limiter = tier.score < score.tiers["capacity_ceiling"].score - 10
        limiter_marker = " ← LIMITER" if is_limiter else ""
        st.markdown(f"**Responsiveness ({tier.weight})** — {tier.score}{limiter_marker}")
        for comp_name, comp_score in tier.components.items():
            display_name = comp_name.replace("_", " ").title()
            col1, col2 = st.columns([3, 1])
            with col1:
                st.progress(comp_score / 100)
            with col2:
                st.write(f"{comp_score}")
            st.caption(display_name)

        st.divider()

        # Efficiency Tier
        tier = score.tiers["efficiency_baseline"]
        st.markdown(f"**Efficiency & Baseline ({tier.weight})** — {tier.score}")
        for comp_name, comp_score in tier.components.items():
            display_name = comp_name.replace("_", " ").title()
            col1, col2 = st.columns([3, 1])
            with col1:
                st.progress(comp_score / 100)
            with col2:
                st.write(f"{comp_score}")
            st.caption(display_name)


def render_vitals_score_card():
    """Render Peter's Vitals Score (PVS) card with drill-down."""
    # Fetch data
    data = get_vitals_score_data()

    # Calculate score
    score = calculate_vitals_score(
        systolic=data.get("systolic"),
        diastolic=data.get("diastolic"),
        resting_hr=data.get("resting_hr"),
        current_hrv=data.get("current_hrv"),
        baseline_hrv=data.get("baseline_hrv", 40),
        spo2=data.get("spo2"),
        respiratory_rate=data.get("respiratory_rate"),
    )

    emoji = STATUS_EMOJIS.get(score.status, "")

    # Main score display
    st.markdown(f"### {emoji} Vitals Score")

    col1, col2 = st.columns([3, 1])
    with col1:
        st.progress(score.total / 100)
    with col2:
        st.markdown(f"**{score.total}**")

    st.caption(f"{score.status}")

    # Expandable component breakdown
    with st.expander("Score Breakdown", expanded=False):
        components = score.tiers["components"].components

        # Display each component
        component_labels = {
            "blood_pressure": ("Blood Pressure", "30%"),
            "resting_hr": ("Resting HR", "25%"),
            "hrv": ("HRV", "25%"),
            "spo2": ("SpO2", "10%"),
            "respiratory_rate": ("Respiratory Rate", "10%"),
        }

        for comp_name, comp_score in components.items():
            label, weight = component_labels.get(comp_name, (comp_name, ""))
            st.markdown(f"**{label}** ({weight})")
            col1, col2 = st.columns([3, 1])
            with col1:
                st.progress(comp_score / 100)
            with col2:
                st.write(f"{comp_score}")


def render_score_cards():
    """Render all three score cards in a row."""
    st.subheader("Health Scores")

    cols = st.columns(3)

    with cols[0]:
        render_recovery_score_card()

    with cols[1]:
        render_cardio_score_card()

    with cols[2]:
        render_vitals_score_card()


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
        # Helper to get latest valid value
        def get_latest_valid(df, col):
            if df.empty or col not in df.columns:
                return None
            valid = df[df[col].notna()]
            return valid.iloc[-1][col] if not valid.empty else None

        if not oura_data.empty and "hrv_ms" in oura_data.columns:
            latest_hrv = get_latest_valid(oura_data, "hrv_ms")
            avg_hrv = oura_data["hrv_ms"].mean()
            if pd.notna(latest_hrv):
                delta_pct = ((latest_hrv - avg_hrv) / avg_hrv * 100) if avg_hrv > 0 else 0
                st.metric(
                    "HRV (latest)",
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
            latest_sleep = get_latest_valid(oura_data, "sleep_score")
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
            latest_readiness = get_latest_valid(oura_data, "readiness_score")
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
            template="plotly_dark",
            title="Zone 2 Power Progression + Ferritin",
            hovermode="x unified",
            height=400,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=0, r=0, t=60, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        fig.update_xaxes(title_text="Date")
        fig.update_yaxes(title_text="Power (watts)", secondary_y=False)
        fig.update_yaxes(title_text="Ferritin (ng/mL)", secondary_y=True)

        st.plotly_chart(fig, use_container_width=True)

        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            avg_watts = zone2_workouts["avg_watts"].mean()
            st.metric("Avg Z2 Power", f"{avg_watts:.0f}W")
        with col2:
            max_watts = zone2_workouts["avg_watts"].max()
            st.metric("Max Z2 Power", f"{max_watts:.0f}W")
        with col3:
            workouts_count = len(zone2_workouts)
            st.metric("Z2 Sessions", f"{workouts_count}")
        with col4:
            # Latest VO2 stimulus from Polar data if available
            try:
                from utils.queries import query_polar_sessions, get_vo2_analysis
                polar_sessions = query_polar_sessions(start_date, end_date)
                if not polar_sessions.empty and polar_sessions.iloc[0]["workout_id"]:
                    latest_workout_id = polar_sessions.iloc[0]["workout_id"]
                    vo2_analysis = get_vo2_analysis(latest_workout_id)
                    # Get True VO2 time from summary
                    summary = vo2_analysis.get("summary", {})
                    stimulus_min = summary.get("true_vo2_time_min", 0)
                    st.metric("Latest VO2 Stimulus", f"{stimulus_min:.1f} min")
                else:
                    st.metric("VO2 Stimulus", "No data")
            except Exception:
                st.metric("VO2 Stimulus", "N/A")


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
            template="plotly_dark",
            title="HRV & Readiness Trend",
            height=350,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=0, r=0, t=60, b=0),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
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
    from utils.constants import (
        KEY_LIFTS,
        EXERCISE_MUSCLE_GROUPS,
        MUSCLE_GROUP_COLORS,
        PROGRESSION_STATUS_EMOJI,
    )
    from utils.queries import (
        query_lift_maxes,
        query_weekly_volume,
        query_volume_by_exercise,
    )

    with st.expander("Strength Training", expanded=False):
        # Query all data
        lift_data = query_lift_maxes(start_date, end_date, exercises=KEY_LIFTS)
        weekly_vol = query_weekly_volume(start_date, end_date)
        exercise_vol = query_volume_by_exercise(start_date, end_date)

        if lift_data.empty and weekly_vol.empty:
            st.info("No strength training data found in this period.")
            return

        # --- Weekly Summary Metrics ---
        if not weekly_vol.empty:
            recent_week = weekly_vol.iloc[-1] if len(weekly_vol) > 0 else None
            avg_weekly_sets = weekly_vol["total_sets"].mean()

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                sessions = int(recent_week["sessions"]) if recent_week is not None else 0
                st.metric("Sessions (This Week)", sessions)
            with col2:
                sets = int(recent_week["total_sets"]) if recent_week is not None else 0
                delta = int(sets - avg_weekly_sets) if avg_weekly_sets else None
                st.metric("Sets (This Week)", sets, delta=delta if delta else None)
            with col3:
                reps = int(recent_week["total_reps"]) if recent_week is not None else 0
                st.metric("Reps (This Week)", reps)
            with col4:
                vol = recent_week["total_volume_lbs"] if recent_week is not None else 0
                vol_k = vol / 1000 if vol else 0
                st.metric("Volume (This Week)", f"{vol_k:.1f}K lbs")

        st.markdown("---")

        # --- Key Lift Progression Chart ---
        st.markdown("#### Key Lift Progression")

        if not lift_data.empty:
            fig = go.Figure()

            lift_colors = ["#FF6B6B", "#4ECDC4", "#95E1D3", "#FFE66D"]
            for i, lift in enumerate(KEY_LIFTS):
                lift_subset = lift_data[lift_data["exercise_name"] == lift]
                if not lift_subset.empty:
                    # Shorten name for legend
                    short_name = lift.replace("Dumbbell ", "DB ").replace("Barbell ", "BB ")
                    fig.add_trace(
                        go.Scatter(
                            x=lift_subset["workout_date"],
                            y=lift_subset["max_weight"],
                            mode="lines+markers",
                            name=short_name,
                            marker=dict(size=7),
                            line=dict(width=2, color=lift_colors[i % len(lift_colors)]),
                        )
                    )

            fig.update_layout(
                template="plotly_dark",
                xaxis_title="Date",
                yaxis_title="Weight (lbs)",
                hovermode="x unified",
                height=300,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
                margin=dict(l=0, r=0, t=40, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data for key lifts in this period.")

        # --- Volume by Muscle Group ---
        st.markdown("#### Volume by Muscle Group")

        if not exercise_vol.empty:
            # Map exercises to muscle groups
            exercise_vol["muscle_group"] = exercise_vol["exercise_name"].map(
                EXERCISE_MUSCLE_GROUPS
            ).fillna("Other")

            # Aggregate by muscle group
            mg_vol = (
                exercise_vol.groupby("muscle_group")
                .agg({"total_sets": "sum", "total_volume_lbs": "sum"})
                .reset_index()
                .sort_values("total_sets", ascending=True)
            )

            # Bar chart
            colors = [MUSCLE_GROUP_COLORS.get(mg, "#808080") for mg in mg_vol["muscle_group"]]

            fig_mg = go.Figure()
            fig_mg.add_trace(
                go.Bar(
                    y=mg_vol["muscle_group"],
                    x=mg_vol["total_sets"],
                    orientation="h",
                    marker_color=colors,
                    text=mg_vol["total_sets"],
                    textposition="auto",
                )
            )

            fig_mg.update_layout(
                template="plotly_dark",
                xaxis_title="Total Sets",
                yaxis_title="",
                height=250,
                margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )

            st.plotly_chart(fig_mg, use_container_width=True)

        # --- Progress Indicators Table ---
        st.markdown("#### Exercise Progress")

        if not exercise_vol.empty:
            # Build progress table from exercise data
            progress_data = []
            for _, row in exercise_vol.head(10).iterrows():
                ex_name = row["exercise_name"]
                current_wt = row["max_weight"]
                sessions = row["sessions"]

                # Determine status based on sessions and weight
                if sessions >= 3:
                    status = "READY"
                    action = "+5 lbs"
                elif sessions <= 2:
                    status = "PROGRESSING"
                    action = "Continue"
                else:
                    status = "STABLE"
                    action = "Maintain"

                emoji = PROGRESSION_STATUS_EMOJI.get(status, "⚪")

                # Shorten exercise name for display
                short_name = ex_name.replace("Dumbbell ", "DB ").replace("Barbell ", "BB ")
                if len(short_name) > 25:
                    short_name = short_name[:22] + "..."

                progress_data.append({
                    "Exercise": short_name,
                    "Weight": f"{current_wt:.0f} lbs" if current_wt else "BW",
                    "Sessions": sessions,
                    "Status": f"{emoji} {status}",
                    "Action": action,
                })

            if progress_data:
                import pandas as pd
                progress_df = pd.DataFrame(progress_data)
                st.dataframe(
                    progress_df,
                    use_container_width=True,
                    hide_index=True,
                    height=min(400, 35 * len(progress_data) + 38),
                )


# =============================================================================
# Weekly Coach Section
# =============================================================================


def get_weekly_report_path() -> str | None:
    """Get path to weekly report file (deployed or local)."""
    from pathlib import Path

    # Project root is 2 levels up from this file (analysis/apps/hdp_dashboard.py)
    project_root = Path(__file__).parent.parent.parent

    # Check deployed location first (deploy/data/weekly_report.md)
    deployed_path = project_root / "deploy" / "data" / "weekly_report.md"
    if deployed_path.exists():
        return str(deployed_path)

    # Fall back to local outputs (analysis/outputs/weekly_report_*.md)
    local_dir = project_root / "analysis" / "outputs"
    if local_dir.exists():
        reports = sorted(local_dir.glob("weekly_report_*.md"), reverse=True)
        if reports:
            return str(reports[0])

    return None


def render_weekly_coach_section():
    """Render the Weekly Coach / Training Plan section."""
    with st.expander("Weekly Coach", expanded=False):
        report_path = get_weekly_report_path()

        if not report_path:
            st.info(
                "No weekly report found. "
                "Run `make training.weekly` to generate one."
            )
            return

        # Read the report
        from pathlib import Path
        report_content = Path(report_path).read_text()

        # Extract generation date from footer
        import re
        date_match = re.search(r"Generated (\d{4}-\d{2}-\d{2})", report_content)
        if date_match:
            gen_date = date_match.group(1)
            st.caption(f"Report generated: {gen_date}")

        # Display the markdown report
        st.markdown(report_content)


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

    # Health Scores (PRS, PCS, PVS)
    render_score_cards()

    st.divider()

    # Hero KPIs
    render_hero_kpis(start_date, end_date)

    st.divider()

    # Main sections
    render_cardiovascular_section(start_date, end_date)
    render_recovery_section(start_date, end_date)
    render_strength_section(start_date, end_date)
    render_weekly_coach_section()
    render_now_section(start_date, end_date)

    # Footer
    st.divider()
    st.caption(
        "Health Data Pipeline Dashboard | "
        f"Data range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
    )


if __name__ == "__main__":
    main()
