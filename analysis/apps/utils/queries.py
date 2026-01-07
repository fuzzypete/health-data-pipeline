"""DuckDB query functions for HDP Dashboard.

All queries use read_parquet() to scan partitioned Parquet files.
Functions are designed to be used with Streamlit's @st.cache_data decorator.
"""

from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

# Resolve paths relative to project root
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# Support both local development and cloud deployment paths
# Cloud: uses deploy/data/ (committed subset)
# Local: uses Data/Parquet/ (full dataset)
DEPLOY_DATA_PATH = PROJECT_ROOT / "deploy" / "data"
LOCAL_DATA_PATH = PROJECT_ROOT / "Data" / "Parquet"

# Use deployed data if it exists (for Streamlit Cloud), otherwise use local
PARQUET_ROOT = DEPLOY_DATA_PATH if DEPLOY_DATA_PATH.exists() else LOCAL_DATA_PATH


@st.cache_resource
def get_connection() -> duckdb.DuckDBPyConnection:
    """Get a cached DuckDB connection."""
    return duckdb.connect()


def _parquet_path(table_name: str) -> str:
    """Get the parquet glob pattern for a table."""
    return str(PARQUET_ROOT / table_name / "**" / "*.parquet")


# =============================================================================
# Workout Queries
# =============================================================================


@st.cache_data(ttl=3600)
def query_workouts(
    start_date: datetime,
    end_date: datetime,
    concept2_only: bool = False,
) -> pd.DataFrame:
    """Query workout data (Concept2 + other sources).

    Args:
        start_date: Start of date range
        end_date: End of date range
        concept2_only: If True, only return Concept2 workouts (has erg_type)

    Returns:
        DataFrame with workout data
    """
    conn = get_connection()

    # Concept2 workouts have erg_type set
    source_filter = "AND erg_type IS NOT NULL" if concept2_only else ""

    query = f"""
        SELECT
            workout_id,
            start_time_utc,
            end_time_utc,
            workout_type,
            erg_type,
            duration_s,
            distance_m,
            avg_pace_sec_per_500m,
            stroke_rate,
            avg_hr_bpm,
            max_hr_bpm,
            calories_kcal,
            notes
        FROM read_parquet('{_parquet_path("workouts")}')
        WHERE start_time_utc BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
        {source_filter}
        ORDER BY start_time_utc DESC
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying workouts: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def query_zone2_workouts(
    start_date: datetime,
    end_date: datetime,
    erg_type: str = "bike",
    min_duration_min: int = 20,
) -> pd.DataFrame:
    """Query Zone 2 workouts for cardio analysis.

    Zone 2 is approximated by steady-state efforts on BikeErg.
    Joins with cardio_strokes to get average watts.
    """
    conn = get_connection()

    # Format dates as strings for SQL
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    query = f"""
        WITH workout_watts AS (
            SELECT
                workout_id,
                AVG(watts) as avg_watts
            FROM read_parquet('{_parquet_path("cardio_strokes")}')
            WHERE workout_start_utc::DATE BETWEEN '{start_str}' AND '{end_str}'
            GROUP BY workout_id
        )
        SELECT
            w.workout_id,
            w.start_time_utc,
            w.start_time_utc::DATE as workout_date,
            w.erg_type,
            w.duration_s / 60.0 as duration_min,
            COALESCE(s.avg_watts, 0) as avg_watts,
            w.avg_hr_bpm,
            w.max_hr_bpm,
            w.notes
        FROM read_parquet('{_parquet_path("workouts")}') w
        LEFT JOIN workout_watts s ON w.workout_id = s.workout_id
        WHERE w.start_time_utc::DATE BETWEEN '{start_str}' AND '{end_str}'
          AND w.erg_type IS NOT NULL
          AND LOWER(w.erg_type) = '{erg_type.lower()}'
          AND w.duration_s >= {min_duration_min * 60}
        ORDER BY w.start_time_utc
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying Zone 2 workouts: {e}")
        return pd.DataFrame()


# =============================================================================
# Oura/Recovery Queries
# =============================================================================


@st.cache_data(ttl=3600)
def query_oura_summary(
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """Query Oura daily summary data."""
    conn = get_connection()

    query = f"""
        SELECT
            day,
            readiness_score,
            sleep_score,
            activity_score,
            hrv_ms,
            temperature_deviation_c,
            resting_heart_rate_bpm,
            total_sleep_duration_s,
            rem_sleep_duration_s,
            deep_sleep_duration_s,
            light_sleep_duration_s
        FROM read_parquet('{_parquet_path("oura_summary")}')
        WHERE day BETWEEN '{start_date.date()}' AND '{end_date.date()}'
        ORDER BY day
    """

    try:
        df = conn.execute(query).df()
        # Convert sleep durations to hours
        if not df.empty:
            for col in ["total_sleep_duration_s", "rem_sleep_duration_s",
                       "deep_sleep_duration_s", "light_sleep_duration_s"]:
                if col in df.columns:
                    df[col.replace("_s", "_hr")] = df[col] / 3600.0
        return df
    except Exception as e:
        st.warning(f"Error querying Oura summary: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def query_hrv_data(
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """Query HRV data from Oura for trend analysis."""
    conn = get_connection()

    query = f"""
        SELECT
            day,
            hrv_ms as hrv,
            resting_heart_rate_bpm as resting_hr
        FROM read_parquet('{_parquet_path("oura_summary")}')
        WHERE day BETWEEN '{start_date.date()}' AND '{end_date.date()}'
          AND hrv_ms IS NOT NULL
        ORDER BY day
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying HRV data: {e}")
        return pd.DataFrame()


# =============================================================================
# Labs Queries
# =============================================================================


@st.cache_data(ttl=3600)
def query_labs(
    start_date: datetime,
    end_date: datetime,
    biomarker: str | None = None,
) -> pd.DataFrame:
    """Query lab results."""
    conn = get_connection()

    biomarker_filter = f"AND marker = '{biomarker}'" if biomarker else ""

    query = f"""
        SELECT
            date as test_date,
            marker as biomarker_name,
            value as numeric_value,
            unit,
            ref_low as reference_low,
            ref_high as reference_high,
            lab_name
        FROM read_parquet('{_parquet_path("labs")}')
        WHERE date BETWEEN '{start_date.date()}' AND '{end_date.date()}'
        {biomarker_filter}
        ORDER BY date, marker
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying labs: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def query_ferritin(start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """Query ferritin values specifically."""
    return query_labs(start_date, end_date, biomarker="Ferritin")


@st.cache_data(ttl=3600)
def query_latest_biomarker(biomarker: str) -> dict | None:
    """Get the most recent value for a biomarker."""
    conn = get_connection()

    query = f"""
        SELECT
            date as test_date,
            marker,
            value,
            unit
        FROM read_parquet('{_parquet_path("labs")}')
        WHERE marker = '{biomarker}'
        ORDER BY date DESC
        LIMIT 1
    """

    try:
        df = conn.execute(query).df()
        if not df.empty:
            row = df.iloc[0]
            return {
                "date": row["test_date"],
                "value": row["value"],
                "unit": row["unit"],
            }
    except Exception:
        pass
    return None


# =============================================================================
# Lactate Queries
# =============================================================================


@st.cache_data(ttl=3600)
def query_lactate(
    start_date: datetime,
    end_date: datetime,
    test_type: str | None = None,
) -> pd.DataFrame:
    """Query lactate measurements."""
    conn = get_connection()

    test_type_filter = f"AND test_type = '{test_type}'" if test_type else ""

    query = f"""
        SELECT
            workout_id,
            workout_start_utc,
            lactate_mmol,
            measurement_context,
            test_type,
            reading_sequence,
            elapsed_minutes,
            watts_at_reading,
            hr_at_reading,
            equipment_type,
            notes
        FROM read_parquet('{_parquet_path("lactate")}')
        WHERE workout_start_utc BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
        {test_type_filter}
        ORDER BY workout_start_utc, reading_sequence
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying lactate: {e}")
        return pd.DataFrame()


# =============================================================================
# Strength Training Queries
# =============================================================================


@st.cache_data(ttl=3600)
def query_resistance_sets(
    start_date: datetime,
    end_date: datetime,
    exercise: str | None = None,
) -> pd.DataFrame:
    """Query resistance training sets (JEFIT data)."""
    conn = get_connection()

    exercise_filter = f"AND exercise_name = '{exercise}'" if exercise else ""

    query = f"""
        SELECT
            workout_id,
            workout_start_utc::DATE as workout_date,
            exercise_name,
            set_number,
            weight_lbs,
            actual_reps as reps,
            weight_lbs * actual_reps as volume_lbs,
            notes
        FROM read_parquet('{_parquet_path("resistance_sets")}')
        WHERE workout_start_utc::DATE BETWEEN '{start_date.date()}' AND '{end_date.date()}'
        {exercise_filter}
        ORDER BY workout_start_utc, exercise_name, set_number
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying resistance sets: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def query_lift_maxes(
    start_date: datetime,
    end_date: datetime,
    exercises: list[str] | None = None,
) -> pd.DataFrame:
    """Query max weight per session for key lifts."""
    conn = get_connection()

    if exercises:
        exercise_list = ", ".join(f"'{e}'" for e in exercises)
        exercise_filter = f"AND exercise_name IN ({exercise_list})"
    else:
        exercise_filter = ""

    query = f"""
        SELECT
            workout_start_utc::DATE as workout_date,
            exercise_name,
            MAX(weight_lbs) as max_weight,
            SUM(weight_lbs * actual_reps) as total_volume
        FROM read_parquet('{_parquet_path("resistance_sets")}')
        WHERE workout_start_utc::DATE BETWEEN '{start_date.date()}' AND '{end_date.date()}'
        {exercise_filter}
        GROUP BY workout_start_utc::DATE, exercise_name
        ORDER BY workout_date, exercise_name
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying lift maxes: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def query_weekly_volume(
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """Query weekly training volume (sets, reps, total lbs)."""
    conn = get_connection()

    query = f"""
        SELECT
            DATE_TRUNC('week', workout_start_utc)::DATE as week_start,
            COUNT(DISTINCT workout_start_utc::DATE) as sessions,
            COUNT(*) as total_sets,
            SUM(actual_reps) as total_reps,
            SUM(weight_lbs * actual_reps) as total_volume_lbs
        FROM read_parquet('{_parquet_path("resistance_sets")}')
        WHERE workout_start_utc::DATE BETWEEN '{start_date.date()}' AND '{end_date.date()}'
        GROUP BY DATE_TRUNC('week', workout_start_utc)
        ORDER BY week_start
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying weekly volume: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def query_volume_by_exercise(
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """Query volume breakdown by exercise for muscle group analysis."""
    conn = get_connection()

    query = f"""
        SELECT
            exercise_name,
            COUNT(DISTINCT workout_start_utc::DATE) as sessions,
            COUNT(*) as total_sets,
            SUM(actual_reps) as total_reps,
            SUM(weight_lbs * actual_reps) as total_volume_lbs,
            MAX(weight_lbs) as max_weight,
            AVG(weight_lbs) as avg_weight
        FROM read_parquet('{_parquet_path("resistance_sets")}')
        WHERE workout_start_utc::DATE BETWEEN '{start_date.date()}' AND '{end_date.date()}'
          AND weight_lbs IS NOT NULL
        GROUP BY exercise_name
        ORDER BY total_sets DESC
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying volume by exercise: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def query_exercise_progression(
    start_date: datetime,
    end_date: datetime,
    exercise: str,
) -> pd.DataFrame:
    """Query detailed progression data for a specific exercise."""
    conn = get_connection()

    query = f"""
        SELECT
            workout_start_utc::DATE as workout_date,
            MAX(weight_lbs) as max_weight,
            AVG(weight_lbs) as avg_weight,
            AVG(actual_reps) as avg_reps,
            COUNT(*) as sets,
            SUM(weight_lbs * actual_reps) as volume_lbs
        FROM read_parquet('{_parquet_path("resistance_sets")}')
        WHERE workout_start_utc::DATE BETWEEN '{start_date.date()}' AND '{end_date.date()}'
          AND exercise_name = '{exercise}'
          AND weight_lbs IS NOT NULL
        GROUP BY workout_start_utc::DATE
        ORDER BY workout_date
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying exercise progression: {e}")
        return pd.DataFrame()


# =============================================================================
# Polar H10 & VO2 Queries
# =============================================================================


@st.cache_data(ttl=3600)
def get_workouts_with_polar(
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> pd.DataFrame:
    """Get all workouts that have associated Polar session data."""
    conn = get_connection()

    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND w.start_time_utc BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'"

    query = f"""
        SELECT
            w.workout_id,
            w.start_time_utc,
            w.start_time_utc::DATE as workout_date,
            w.erg_type,
            w.duration_s / 60.0 as duration_min,
            w.avg_hr_bpm,
            w.max_hr_bpm,
            p.session_id,
            p.avg_hr as polar_avg_hr,
            p.rmssd_ms
        FROM read_parquet('{_parquet_path("workouts")}') w
        JOIN read_parquet('{_parquet_path("polar_sessions")}') p ON w.workout_id = p.workout_id
        WHERE w.erg_type IS NOT NULL
        {date_filter}
        ORDER BY w.start_time_utc DESC
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying workouts with Polar data: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def get_vo2_interval_sessions(
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    min_max_hr: int = 135,
) -> pd.DataFrame:
    """
    Get workouts with Polar data that are likely VO2 interval sessions.
    
    Filters by intensity (Max HR) to exclude Zone 2 work.
    """
    df = get_workouts_with_polar(start_date, end_date)
    if not df.empty and "max_hr_bpm" in df.columns:
        return df[df["max_hr_bpm"] >= min_max_hr].copy()
    return pd.DataFrame()


@st.cache_data(ttl=3600)
def query_polar_sessions(
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """Query Polar H10 session summaries."""
    conn = get_connection()

    query = f"""
        SELECT
            session_id,
            workout_id,
            start_time_utc,
            duration_sec,
            avg_hr,
            max_hr,
            rmssd_ms,
            sdnn_ms,
            source_file
        FROM read_parquet('{_parquet_path("polar_sessions")}')
        WHERE start_time_utc BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
        ORDER BY start_time_utc DESC
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying Polar sessions: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def query_polar_respiratory(workout_id: str) -> pd.DataFrame:
    """Query respiratory rate data for a specific workout."""
    conn = get_connection()

    query = f"""
        SELECT
            window_center_min,
            respiratory_rate,
            avg_hr,
            confidence
        FROM read_parquet('{_parquet_path("polar_respiratory")}')
        WHERE workout_id = '{workout_id}'
        ORDER BY window_center_min
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        # Try session_id if workout_id not found or query fails
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def get_vo2_analysis(workout_id: str) -> dict:
    """Get high-confidence 3-gate VO2 stimulus analysis for a workout."""
    try:
        from pipeline.analysis.vo2_overlap import analyze_vo2_session_3gate
        from pipeline.analysis.vo2_baseline import get_gate2_params
        
        # Get dynamic Z2 params for this environment
        params = get_gate2_params(data_path=str(PARQUET_ROOT))
        
        return analyze_vo2_session_3gate(
            workout_id, 
            data_path=str(PARQUET_ROOT),
            **params
        )
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# Minute Facts / Daily Summary Queries
# =============================================================================


@st.cache_data(ttl=3600)
def query_minute_facts(
    start_date: datetime,
    end_date: datetime,
    limit: int = 10000,
) -> pd.DataFrame:
    """Query minute-level facts (HAE data).

    Warning: This can be a large query - use with caution.
    """
    conn = get_connection()

    query = f"""
        SELECT *
        FROM read_parquet('{_parquet_path("minute_facts")}')
        WHERE timestamp_utc BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'
        ORDER BY timestamp_utc DESC
        LIMIT {limit}
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying minute facts: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def query_daily_summary(
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """Query daily summary data."""
    conn = get_connection()

    query = f"""
        SELECT *
        FROM read_parquet('{_parquet_path("daily_summary")}')
        WHERE date_utc BETWEEN '{start_date.date()}' AND '{end_date.date()}'
        ORDER BY date_utc
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying daily summary: {e}")
        return pd.DataFrame()


# =============================================================================
# KPI Calculation Helpers
# =============================================================================


@st.cache_data(ttl=1800)
def get_latest_ferritin() -> dict | None:
    """Get most recent ferritin value with trend."""
    current = query_latest_biomarker("Ferritin")
    if not current:
        return None

    # Get value from prior test for trend
    conn = get_connection()
    query = f"""
        SELECT value
        FROM read_parquet('{_parquet_path("labs")}')
        WHERE marker = 'Ferritin'
          AND date < '{current["date"]}'
        ORDER BY date DESC
        LIMIT 1
    """

    try:
        df = conn.execute(query).df()
        prior_value = df.iloc[0]["value"] if not df.empty else None
        trend_pct = None
        if prior_value and prior_value > 0:
            trend_pct = ((current["value"] - prior_value) / prior_value) * 100

        return {
            "value": current["value"],
            "unit": current["unit"],
            "date": current["date"],
            "prior_value": prior_value,
            "trend_pct": trend_pct,
            "target": 60,  # Peter's target
        }
    except Exception:
        return current


@st.cache_data(ttl=1800)
def get_max_hr_7d() -> dict | None:
    """Get max heart rate in the last 7 days."""
    conn = get_connection()
    end_date = datetime.now()
    start_date = end_date - pd.Timedelta(days=7)

    query = f"""
        SELECT
            MAX(max_hr_bpm) as max_hr,
            MAX(start_time_utc) as latest_workout
        FROM read_parquet('{_parquet_path("workouts")}')
        WHERE start_time_utc >= '{start_date.isoformat()}'
          AND max_hr_bpm IS NOT NULL
    """

    try:
        df = conn.execute(query).df()
        if not df.empty and df.iloc[0]["max_hr"]:
            max_hr = int(df.iloc[0]["max_hr"])
            baseline = 161  # Peter's known peak
            return {
                "value": max_hr,
                "baseline": baseline,
                "pct_of_baseline": (max_hr / baseline) * 100,
                "deficit": baseline - max_hr,
            }
    except Exception:
        pass
    return None


@st.cache_data(ttl=1800)
def get_weekly_training_volume() -> dict | None:
    """Get current week's training volume in minutes."""
    conn = get_connection()
    end_date = datetime.now()
    # Start of current week (Monday)
    start_date = end_date - pd.Timedelta(days=end_date.weekday())
    start_date = start_date.replace(hour=0, minute=0, second=0)

    # Cardio minutes (Concept2 workouts have erg_type set)
    cardio_query = f"""
        SELECT COALESCE(SUM(duration_s / 60.0), 0) as cardio_min
        FROM read_parquet('{_parquet_path("workouts")}')
        WHERE start_time_utc >= '{start_date.isoformat()}'
          AND erg_type IS NOT NULL
    """

    # Strength minutes (estimate 2 min per set)
    strength_query = f"""
        SELECT COALESCE(COUNT(*) * 2, 0) as strength_min
        FROM read_parquet('{_parquet_path("resistance_sets")}')
        WHERE workout_start_utc::DATE >= '{start_date.date()}'
    """

    try:
        cardio_df = conn.execute(cardio_query).df()
        strength_df = conn.execute(strength_query).df()

        cardio_min = cardio_df.iloc[0]["cardio_min"] if not cardio_df.empty else 0
        strength_min = strength_df.iloc[0]["strength_min"] if not strength_df.empty else 0

        return {
            "total": int(cardio_min + strength_min),
            "cardio": int(cardio_min),
            "strength": int(strength_min),
        }
    except Exception:
        pass
    return None


# =============================================================================
# Score Data Queries (PRS, PCS, PVS)
# =============================================================================


@st.cache_data(ttl=1800)
def get_recovery_score_data() -> dict:
    """
    Get all data needed to calculate Peter's Recovery Score (PRS).

    Returns dict with:
    - sleep_duration_hours: Last night's sleep
    - sleep_efficiency_pct: Sleep efficiency
    - sleep_debt_hours: 7-day cumulative debt
    - current_hrv: Today's HRV
    - baseline_hrv: 90-day HRV average
    - current_rhr: Today's resting HR
    - baseline_rhr: 90-day RHR average
    - acute_load_min: 7-day training load
    - chronic_load_min: 28-day weekly average
    - days_since_rest: Consecutive training days
    - yesterday_workout_type: Type of yesterday's workout
    """
    conn = get_connection()
    result = {}

    # Get latest Oura data (sleep, HRV, RHR)
    # Filter for non-null HRV to ensure we get a completed night's data
    try:
        oura_query = f"""
            SELECT
                day,
                total_sleep_duration_s / 3600.0 as sleep_hours,
                hrv_ms,
                resting_heart_rate_bpm
            FROM read_parquet('{_parquet_path("oura_summary")}')
            WHERE hrv_ms IS NOT NULL
            ORDER BY day DESC
            LIMIT 1
        """
        df = conn.execute(oura_query).df()
        if not df.empty:
            result["sleep_duration_hours"] = df.iloc[0]["sleep_hours"] or 0
            result["current_hrv"] = df.iloc[0]["hrv_ms"]
            result["current_rhr"] = df.iloc[0]["resting_heart_rate_bpm"]
        else:
            result["sleep_duration_hours"] = 0
            result["current_hrv"] = None
            result["current_rhr"] = None
    except Exception:
        result["sleep_duration_hours"] = 0
        result["current_hrv"] = None
        result["current_rhr"] = None

    # Sleep efficiency (from Oura contributors if available, else estimate)
    # Oura stores this in sleep_contributors map - for now estimate from duration
    result["sleep_efficiency_pct"] = min(95, result["sleep_duration_hours"] / 8.0 * 100) if result["sleep_duration_hours"] > 0 else None

    # Calculate 7-day sleep debt
    try:
        debt_query = f"""
            SELECT
                SUM(total_sleep_duration_s / 3600.0 - 7.5) as debt_hours
            FROM read_parquet('{_parquet_path("oura_summary")}')
            WHERE day >= CURRENT_DATE - INTERVAL '7 days'
        """
        df = conn.execute(debt_query).df()
        debt = df.iloc[0]["debt_hours"] if not df.empty and df.iloc[0]["debt_hours"] else 0
        # Cap surplus at 0 (can't bank unlimited sleep)
        result["sleep_debt_hours"] = min(0, debt)
    except Exception:
        result["sleep_debt_hours"] = 0

    # 90-day HRV baseline
    try:
        hrv_baseline_query = f"""
            SELECT AVG(hrv_ms) as baseline
            FROM read_parquet('{_parquet_path("oura_summary")}')
            WHERE day BETWEEN CURRENT_DATE - INTERVAL '90 days' AND CURRENT_DATE - INTERVAL '1 day'
              AND hrv_ms IS NOT NULL
        """
        df = conn.execute(hrv_baseline_query).df()
        result["baseline_hrv"] = df.iloc[0]["baseline"] if not df.empty and df.iloc[0]["baseline"] else 40
    except Exception:
        result["baseline_hrv"] = 40  # Default

    # 90-day RHR baseline
    try:
        rhr_baseline_query = f"""
            SELECT AVG(resting_heart_rate_bpm) as baseline
            FROM read_parquet('{_parquet_path("oura_summary")}')
            WHERE day BETWEEN CURRENT_DATE - INTERVAL '90 days' AND CURRENT_DATE - INTERVAL '1 day'
              AND resting_heart_rate_bpm IS NOT NULL
        """
        df = conn.execute(rhr_baseline_query).df()
        result["baseline_rhr"] = df.iloc[0]["baseline"] if not df.empty and df.iloc[0]["baseline"] else 55
    except Exception:
        result["baseline_rhr"] = 55  # Default

    # Acute load (7 days) - cardio + strength
    try:
        acute_query = f"""
            WITH cardio AS (
                SELECT COALESCE(SUM(duration_s / 60.0), 0) as minutes
                FROM read_parquet('{_parquet_path("workouts")}')
                WHERE start_time_utc >= CURRENT_DATE - INTERVAL '7 days'
                  AND erg_type IS NOT NULL
            ),
            strength AS (
                SELECT COALESCE(COUNT(*) * 2, 0) as minutes
                FROM read_parquet('{_parquet_path("resistance_sets")}')
                WHERE workout_start_utc >= CURRENT_DATE - INTERVAL '7 days'
            )
            SELECT (SELECT minutes FROM cardio) + (SELECT minutes FROM strength) as total
        """
        df = conn.execute(acute_query).df()
        result["acute_load_min"] = df.iloc[0]["total"] if not df.empty else 0
    except Exception:
        result["acute_load_min"] = 0

    # Chronic load (28 days weekly average)
    try:
        chronic_query = f"""
            WITH cardio AS (
                SELECT COALESCE(SUM(duration_s / 60.0), 0) as minutes
                FROM read_parquet('{_parquet_path("workouts")}')
                WHERE start_time_utc >= CURRENT_DATE - INTERVAL '28 days'
                  AND erg_type IS NOT NULL
            ),
            strength AS (
                SELECT COALESCE(COUNT(*) * 2, 0) as minutes
                FROM read_parquet('{_parquet_path("resistance_sets")}')
                WHERE workout_start_utc >= CURRENT_DATE - INTERVAL '28 days'
            )
            SELECT ((SELECT minutes FROM cardio) + (SELECT minutes FROM strength)) / 4.0 as weekly_avg
        """
        df = conn.execute(chronic_query).df()
        result["chronic_load_min"] = df.iloc[0]["weekly_avg"] if not df.empty else 0
    except Exception:
        result["chronic_load_min"] = 0

    # Days since rest
    try:
        rest_query = f"""
            WITH daily_workouts AS (
                SELECT DISTINCT start_time_utc::DATE as workout_date
                FROM read_parquet('{_parquet_path("workouts")}')
                WHERE start_time_utc >= CURRENT_DATE - INTERVAL '14 days'
                UNION
                SELECT DISTINCT workout_start_utc::DATE as workout_date
                FROM read_parquet('{_parquet_path("resistance_sets")}')
                WHERE workout_start_utc >= CURRENT_DATE - INTERVAL '14 days'
            ),
            date_series AS (
                SELECT CURRENT_DATE - INTERVAL '1 day' * generate_series as check_date
                FROM generate_series(0, 13)
            )
            SELECT
                MIN(CASE WHEN d.check_date NOT IN (SELECT workout_date FROM daily_workouts)
                    THEN 0 ELSE NULL END) as found_rest,
                COUNT(*) FILTER (WHERE d.check_date IN (SELECT workout_date FROM daily_workouts)) as consecutive
            FROM date_series d
        """
        # Simplified: count consecutive workout days from today backwards
        simple_query = f"""
            WITH daily_workouts AS (
                SELECT DISTINCT start_time_utc::DATE as workout_date
                FROM read_parquet('{_parquet_path("workouts")}')
                WHERE start_time_utc >= CURRENT_DATE - INTERVAL '14 days'
            )
            SELECT COUNT(DISTINCT workout_date) as workout_days
            FROM daily_workouts
            WHERE workout_date >= CURRENT_DATE - INTERVAL '7 days'
        """
        df = conn.execute(simple_query).df()
        # Estimate: if 7 workouts in 7 days, 7 consecutive
        result["days_since_rest"] = min(7, df.iloc[0]["workout_days"]) if not df.empty else 0
    except Exception:
        result["days_since_rest"] = 0

    # Yesterday's workout type
    try:
        yesterday_query = f"""
            SELECT
                CASE
                    WHEN erg_type IS NOT NULL THEN 'zone2'
                    ELSE 'strength'
                END as workout_type
            FROM read_parquet('{_parquet_path("workouts")}')
            WHERE start_time_utc::DATE = CURRENT_DATE - INTERVAL '1 day'
            LIMIT 1
        """
        df = conn.execute(yesterday_query).df()
        if not df.empty:
            result["yesterday_workout_type"] = df.iloc[0]["workout_type"]
        else:
            # Check strength
            strength_check = f"""
                SELECT 1 FROM read_parquet('{_parquet_path("resistance_sets")}')
                WHERE workout_start_utc::DATE = CURRENT_DATE - INTERVAL '1 day'
                LIMIT 1
            """
            df2 = conn.execute(strength_check).df()
            result["yesterday_workout_type"] = "strength" if not df2.empty else "rest"
    except Exception:
        result["yesterday_workout_type"] = "rest"

    return result


@st.cache_data(ttl=1800)
def get_cardio_score_data() -> dict:
    """
    Get all data needed to calculate Peter's Cardio Score (PCS).

    Returns dict with:
    - recent_max_hr: 7-day max HR
    - current_zone2_watts: Latest Z2 power
    - hr_response_minutes: Time to reach 140 bpm (if available)
    - hr_recovery_1min: HR drop 1 min post-effort (if available)
    - current_efficiency: Current W/bpm ratio
    - best_efficiency: Historical best W/bpm ratio
    - resting_hr: Current resting HR
    - current_hrv: Current HRV
    - baseline_hrv: 90-day HRV baseline
    """
    conn = get_connection()
    result = {}

    # 7-day max HR
    try:
        max_hr_query = f"""
            SELECT MAX(max_hr_bpm) as max_hr
            FROM read_parquet('{_parquet_path("workouts")}')
            WHERE start_time_utc >= CURRENT_DATE - INTERVAL '7 days'
              AND max_hr_bpm IS NOT NULL
        """
        df = conn.execute(max_hr_query).df()
        result["recent_max_hr"] = int(df.iloc[0]["max_hr"]) if not df.empty and df.iloc[0]["max_hr"] else 0
    except Exception:
        result["recent_max_hr"] = 0

    # Latest Zone 2 power (BikeErg, 20+ min)
    try:
        z2_query = f"""
            WITH workout_watts AS (
                SELECT
                    s.workout_id,
                    AVG(s.watts) as avg_watts
                FROM read_parquet('{_parquet_path("cardio_strokes")}') s
                GROUP BY s.workout_id
            )
            SELECT ww.avg_watts
            FROM read_parquet('{_parquet_path("workouts")}') w
            JOIN workout_watts ww ON w.workout_id = ww.workout_id
            WHERE w.erg_type = 'bike'
              AND w.duration_s >= 1200
              AND w.start_time_utc >= CURRENT_DATE - INTERVAL '30 days'
            ORDER BY w.start_time_utc DESC
            LIMIT 1
        """
        df = conn.execute(z2_query).df()
        result["current_zone2_watts"] = float(df.iloc[0]["avg_watts"]) if not df.empty else 0
    except Exception:
        result["current_zone2_watts"] = 0

    # HR response time and recovery - requires minute-level HR data
    # For now, set to None (will show as "Unknown" in score)
    result["hr_response_minutes"] = None
    result["hr_recovery_1min"] = None

    # Aerobic efficiency (W/bpm at steady state)
    try:
        efficiency_query = f"""
            WITH workout_data AS (
                SELECT
                    w.workout_id,
                    w.avg_hr_bpm,
                    (SELECT AVG(watts) FROM read_parquet('{_parquet_path("cardio_strokes")}') s
                     WHERE s.workout_id = w.workout_id) as avg_watts
                FROM read_parquet('{_parquet_path("workouts")}') w
                WHERE w.erg_type = 'bike'
                  AND w.duration_s >= 1200
                  AND w.avg_hr_bpm IS NOT NULL
                  AND w.avg_hr_bpm > 0
            )
            SELECT
                avg_watts / avg_hr_bpm as efficiency,
                workout_id
            FROM workout_data
            WHERE avg_watts IS NOT NULL
            ORDER BY efficiency DESC
        """
        df = conn.execute(efficiency_query).df()
        if not df.empty:
            result["best_efficiency"] = float(df.iloc[0]["efficiency"])
            # Current = most recent workout's efficiency
            result["current_efficiency"] = float(df.iloc[-1]["efficiency"]) if len(df) > 1 else result["best_efficiency"]
        else:
            result["best_efficiency"] = 1.0
            result["current_efficiency"] = None
    except Exception:
        result["best_efficiency"] = 1.0
    # Resting HR and HRV from Oura
    try:
        oura_query = f"""
            SELECT
                resting_heart_rate_bpm,
                hrv_ms
            FROM read_parquet('{_parquet_path("oura_summary")}')
            WHERE resting_heart_rate_bpm IS NOT NULL
            ORDER BY day DESC
            LIMIT 1
        """
        df = conn.execute(oura_query).df()
        if not df.empty:
            result["resting_hr"] = int(df.iloc[0]["resting_heart_rate_bpm"]) if df.iloc[0]["resting_heart_rate_bpm"] else None
            result["current_hrv"] = float(df.iloc[0]["hrv_ms"]) if df.iloc[0]["hrv_ms"] else None
        else:
            result["resting_hr"] = None
            result["current_hrv"] = None
    except Exception:
        result["resting_hr"] = None
        result["current_hrv"] = None

    # 90-day HRV baseline
    try:
        baseline_query = f"""
            SELECT AVG(hrv_ms) as baseline
            FROM read_parquet('{_parquet_path("oura_summary")}')
            WHERE day BETWEEN CURRENT_DATE - INTERVAL '90 days' AND CURRENT_DATE - INTERVAL '1 day'
              AND hrv_ms IS NOT NULL
        """
        df = conn.execute(baseline_query).df()
        result["baseline_hrv"] = float(df.iloc[0]["baseline"]) if not df.empty and df.iloc[0]["baseline"] else 40
    except Exception:
        result["baseline_hrv"] = 40

    return result


@st.cache_data(ttl=1800)
def get_vitals_score_data() -> dict:
    """
    Get all data needed to calculate Peter's Vitals Score (PVS).

    Returns dict with:
    - systolic: 7-day avg systolic BP
    - diastolic: 7-day avg diastolic BP
    - resting_hr: Current resting HR
    - current_hrv: Current HRV
    - baseline_hrv: 90-day HRV baseline
    - spo2: 7-day avg SpO2
    - respiratory_rate: 7-day avg respiratory rate
    """
    conn = get_connection()
    result = {}

    # Blood pressure (7-day average from minute_facts)
    try:
        bp_query = f"""
            SELECT
                AVG(blood_pressure_systolic_mmhg) as systolic,
                AVG(blood_pressure_diastolic_mmhg) as diastolic
            FROM read_parquet('{_parquet_path("minute_facts")}')
            WHERE timestamp_utc >= CURRENT_DATE - INTERVAL '7 days'
              AND blood_pressure_systolic_mmhg IS NOT NULL
        """
        df = conn.execute(bp_query).df()
        if not df.empty and df.iloc[0]["systolic"]:
            result["systolic"] = float(df.iloc[0]["systolic"])
            result["diastolic"] = float(df.iloc[0]["diastolic"])
        else:
            result["systolic"] = None
            result["diastolic"] = None
    except Exception:
        result["systolic"] = None
        result["diastolic"] = None

    # SpO2 (7-day average)
    try:
        spo2_query = f"""
            SELECT AVG(blood_oxygen_saturation_pct) as spo2
            FROM read_parquet('{_parquet_path("minute_facts")}')
            WHERE timestamp_utc >= CURRENT_DATE - INTERVAL '7 days'
              AND blood_oxygen_saturation_pct IS NOT NULL
        """
        df = conn.execute(spo2_query).df()
        result["spo2"] = float(df.iloc[0]["spo2"]) if not df.empty and df.iloc[0]["spo2"] else None
    except Exception:
        result["spo2"] = None

    # Respiratory rate (7-day average)
    try:
        resp_query = f"""
            SELECT AVG(respiratory_rate_count_min) as resp_rate
            FROM read_parquet('{_parquet_path("minute_facts")}')
            WHERE timestamp_utc >= CURRENT_DATE - INTERVAL '7 days'
              AND respiratory_rate_count_min IS NOT NULL
        """
        df = conn.execute(resp_query).df()
        result["respiratory_rate"] = float(df.iloc[0]["resp_rate"]) if not df.empty and df.iloc[0]["resp_rate"] else None
    except Exception:
        result["respiratory_rate"] = None

    # Resting HR and HRV from Oura
    try:
        oura_query = f"""
            SELECT
                resting_heart_rate_bpm,
                hrv_ms
            FROM read_parquet('{_parquet_path("oura_summary")}')
            WHERE resting_heart_rate_bpm IS NOT NULL
            ORDER BY day DESC
            LIMIT 1
        """
        df = conn.execute(oura_query).df()
        if not df.empty:
            result["resting_hr"] = int(df.iloc[0]["resting_heart_rate_bpm"]) if df.iloc[0]["resting_heart_rate_bpm"] else None
            result["current_hrv"] = float(df.iloc[0]["hrv_ms"]) if df.iloc[0]["hrv_ms"] else None
        else:
            result["resting_hr"] = None
            result["current_hrv"] = None
    except Exception:
        result["resting_hr"] = None
        result["current_hrv"] = None

    # 90-day HRV baseline
    try:
        baseline_query = f"""
            SELECT AVG(hrv_ms) as baseline
            FROM read_parquet('{_parquet_path("oura_summary")}')
            WHERE day BETWEEN CURRENT_DATE - INTERVAL '90 days' AND CURRENT_DATE - INTERVAL '1 day'
              AND hrv_ms IS NOT NULL
        """
        df = conn.execute(baseline_query).df()
        result["baseline_hrv"] = float(df.iloc[0]["baseline"]) if not df.empty and df.iloc[0]["baseline"] else 40
    except Exception:
        result["baseline_hrv"] = 40

    return result


@st.cache_data(ttl=3600)
def get_body_composition_data() -> dict:
    """
    Get body composition data for panel display.

    Returns dict with:
    - weight_lb: Current weight
    - body_fat_pct: Current body fat %
    - lean_body_mass_lb: Current lean mass
    - weight_trend: List of (date, weight) for sparkline
    - bf_trend: List of (date, bf%) for sparkline
    """
    conn = get_connection()
    result = {}

    # Latest values
    try:
        latest_query = f"""
            SELECT
                date_utc,
                weight_lb,
                body_fat_pct,
                COALESCE(lean_body_mass_lb, weight_lb * (1 - body_fat_pct/100.0)) as lean_mass
            FROM read_parquet('{_parquet_path("daily_summary")}')
            WHERE weight_lb IS NOT NULL
            ORDER BY date_utc DESC
            LIMIT 1
        """
        df = conn.execute(latest_query).df()
        if not df.empty:
            result["weight_lb"] = float(df.iloc[0]["weight_lb"])
            result["body_fat_pct"] = float(df.iloc[0]["body_fat_pct"]) if df.iloc[0]["body_fat_pct"] else None
            result["lean_body_mass_lb"] = float(df.iloc[0]["lean_mass"]) if df.iloc[0]["lean_mass"] else None
            result["latest_date"] = df.iloc[0]["date_utc"]
        else:
            result["weight_lb"] = None
            result["body_fat_pct"] = None
            result["lean_body_mass_lb"] = None
            result["latest_date"] = None
    except Exception:
        result["weight_lb"] = None
        result["body_fat_pct"] = None
        result["lean_body_mass_lb"] = None
        result["latest_date"] = None

    # 90-day trend for sparklines
    try:
        trend_query = f"""
            SELECT
                date_utc,
                weight_lb,
                body_fat_pct
            FROM read_parquet('{_parquet_path("daily_summary")}')
            WHERE weight_lb IS NOT NULL
              AND date_utc >= CURRENT_DATE - INTERVAL '90 days'
            ORDER BY date_utc
        """
        df = conn.execute(trend_query).df()
        result["weight_trend"] = list(zip(df["date_utc"], df["weight_lb"])) if not df.empty else []
        result["bf_trend"] = list(zip(df["date_utc"], df["body_fat_pct"])) if not df.empty else []
    except Exception:
        result["weight_trend"] = []
        result["bf_trend"] = []

    return result


@st.cache_data(ttl=3600)
def get_blood_pressure_data() -> dict:
    """
    Get blood pressure data for panel display.

    Returns dict with:
    - avg_systolic: 7-day average
    - avg_diastolic: 7-day average
    - min_systolic, max_systolic: 7-day range
    - min_diastolic, max_diastolic: 7-day range
    - trend: List of (date, systolic, diastolic) for chart
    """
    conn = get_connection()
    result = {}

    # 7-day stats
    try:
        stats_query = f"""
            SELECT
                ROUND(AVG(blood_pressure_systolic_mmhg), 1) as avg_sys,
                ROUND(AVG(blood_pressure_diastolic_mmhg), 1) as avg_dia,
                ROUND(MIN(blood_pressure_systolic_mmhg), 1) as min_sys,
                ROUND(MAX(blood_pressure_systolic_mmhg), 1) as max_sys,
                ROUND(MIN(blood_pressure_diastolic_mmhg), 1) as min_dia,
                ROUND(MAX(blood_pressure_diastolic_mmhg), 1) as max_dia,
                COUNT(*) as readings
            FROM read_parquet('{_parquet_path("minute_facts")}')
            WHERE timestamp_utc >= CURRENT_DATE - INTERVAL '7 days'
              AND blood_pressure_systolic_mmhg IS NOT NULL
        """
        df = conn.execute(stats_query).df()
        if not df.empty and df.iloc[0]["avg_sys"]:
            result["avg_systolic"] = float(df.iloc[0]["avg_sys"])
            result["avg_diastolic"] = float(df.iloc[0]["avg_dia"])
            result["min_systolic"] = float(df.iloc[0]["min_sys"])
            result["max_systolic"] = float(df.iloc[0]["max_sys"])
            result["min_diastolic"] = float(df.iloc[0]["min_dia"])
            result["max_diastolic"] = float(df.iloc[0]["max_dia"])
            result["readings"] = int(df.iloc[0]["readings"])
        else:
            result["avg_systolic"] = None
            result["avg_diastolic"] = None
            result["readings"] = 0
    except Exception:
        result["avg_systolic"] = None
        result["avg_diastolic"] = None
        result["readings"] = 0

    # 30-day daily averages for trend
    try:
        trend_query = f"""
            SELECT
                DATE(timestamp_utc) as date,
                ROUND(AVG(blood_pressure_systolic_mmhg), 1) as systolic,
                ROUND(AVG(blood_pressure_diastolic_mmhg), 1) as diastolic
            FROM read_parquet('{_parquet_path("minute_facts")}')
            WHERE timestamp_utc >= CURRENT_DATE - INTERVAL '30 days'
              AND blood_pressure_systolic_mmhg IS NOT NULL
            GROUP BY DATE(timestamp_utc)
            ORDER BY date
        """
        df = conn.execute(trend_query).df()
        result["trend"] = df.to_dict("records") if not df.empty else []
    except Exception:
        result["trend"] = []

    return result


@st.cache_data(ttl=3600)
def get_glucose_data() -> dict:
    """
    Get glucose/CGM data for panel display.

    Returns dict with:
    - avg_glucose: 7-day average
    - time_in_range: % time 70-140 mg/dL
    - time_low: % time <70
    - time_high: % time >140
    - cv: Coefficient of variation
    - estimated_a1c: From 90-day average
    - trace: Minute-level data for chart (sampled)
    """
    conn = get_connection()
    result = {}

    # 7-day stats
    try:
        stats_query = f"""
            SELECT
                ROUND(AVG(blood_glucose_mg_dl), 1) as avg_glucose,
                ROUND(STDDEV(blood_glucose_mg_dl), 1) as std_glucose,
                COUNT(*) as total_readings,
                SUM(CASE WHEN blood_glucose_mg_dl BETWEEN 70 AND 140 THEN 1 ELSE 0 END) as in_range,
                SUM(CASE WHEN blood_glucose_mg_dl < 70 THEN 1 ELSE 0 END) as low,
                SUM(CASE WHEN blood_glucose_mg_dl > 140 THEN 1 ELSE 0 END) as high
            FROM read_parquet('{_parquet_path("minute_facts")}')
            WHERE timestamp_utc >= CURRENT_DATE - INTERVAL '7 days'
              AND blood_glucose_mg_dl IS NOT NULL
        """
        df = conn.execute(stats_query).df()
        if not df.empty and df.iloc[0]["avg_glucose"]:
            avg = float(df.iloc[0]["avg_glucose"])
            std = float(df.iloc[0]["std_glucose"]) if df.iloc[0]["std_glucose"] else 0
            total = int(df.iloc[0]["total_readings"])

            result["avg_glucose"] = avg
            result["time_in_range"] = (int(df.iloc[0]["in_range"]) / total * 100) if total > 0 else 0
            result["time_low"] = (int(df.iloc[0]["low"]) / total * 100) if total > 0 else 0
            result["time_high"] = (int(df.iloc[0]["high"]) / total * 100) if total > 0 else 0
            result["cv"] = (std / avg * 100) if avg > 0 else 0
        else:
            result["avg_glucose"] = None
            result["time_in_range"] = None
            result["cv"] = None
    except Exception:
        result["avg_glucose"] = None
        result["time_in_range"] = None
        result["cv"] = None

    # Estimated A1C (90-day average)
    try:
        a1c_query = f"""
            SELECT ROUND(AVG(blood_glucose_mg_dl), 1) as avg_90d
            FROM read_parquet('{_parquet_path("minute_facts")}')
            WHERE timestamp_utc >= CURRENT_DATE - INTERVAL '90 days'
              AND blood_glucose_mg_dl IS NOT NULL
        """
        df = conn.execute(a1c_query).df()
        if not df.empty and df.iloc[0]["avg_90d"]:
            avg_90d = float(df.iloc[0]["avg_90d"])
            result["estimated_a1c"] = round((avg_90d + 46.7) / 28.7, 1)
        else:
            result["estimated_a1c"] = None
    except Exception:
        result["estimated_a1c"] = None

    # Glucose trace (sampled for chart - every 15 min for 7 days)
    try:
        trace_query = f"""
            SELECT
                timestamp_utc,
                blood_glucose_mg_dl as glucose
            FROM read_parquet('{_parquet_path("minute_facts")}')
            WHERE timestamp_utc >= CURRENT_DATE - INTERVAL '7 days'
              AND blood_glucose_mg_dl IS NOT NULL
              AND EXTRACT(MINUTE FROM timestamp_utc) % 15 = 0
            ORDER BY timestamp_utc
        """
        df = conn.execute(trace_query).df()
        result["trace"] = df.to_dict("records") if not df.empty else []
    except Exception:
        result["trace"] = []

    return result


@st.cache_data(ttl=3600)
def get_vo2max_data() -> dict:
    """
    Get VO2max data for KPI display.

    Returns dict with:
    - current: Latest VO2max value
    - date: Date of latest reading
    - trend: Monthly averages for chart
    """
    conn = get_connection()
    result = {}

    # Latest value
    try:
        latest_query = f"""
            SELECT
                DATE(timestamp_utc) as date,
                MAX(vo2_max_ml_kg_min) as vo2max
            FROM read_parquet('{_parquet_path("minute_facts")}')
            WHERE vo2_max_ml_kg_min IS NOT NULL
            GROUP BY DATE(timestamp_utc)
            ORDER BY date DESC
            LIMIT 1
        """
        df = conn.execute(latest_query).df()
        if not df.empty:
            result["current"] = float(df.iloc[0]["vo2max"])
            result["date"] = df.iloc[0]["date"]
        else:
            result["current"] = None
            result["date"] = None
    except Exception:
        result["current"] = None
        result["date"] = None

    # Monthly trend (12 months)
    try:
        trend_query = f"""
            SELECT
                DATE_TRUNC('month', timestamp_utc) as month,
                ROUND(AVG(vo2_max_ml_kg_min), 1) as avg_vo2max
            FROM read_parquet('{_parquet_path("minute_facts")}')
            WHERE vo2_max_ml_kg_min IS NOT NULL
              AND timestamp_utc >= CURRENT_DATE - INTERVAL '365 days'
            GROUP BY DATE_TRUNC('month', timestamp_utc)
            ORDER BY month
        """
        df = conn.execute(trend_query).df()
        result["trend"] = df.to_dict("records") if not df.empty else []
    except Exception:
        result["trend"] = []

    return result


# =============================================================================
# Zone 2 Analysis Queries
# =============================================================================


@st.cache_data(ttl=3600)
def get_zone2_workouts_with_lactate(
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> pd.DataFrame:
    """
    Get Zone 2 workouts that have lactate readings.

    Returns DataFrame with workout summary and lactate reading count.
    """
    conn = get_connection()

    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND w.start_time_utc BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'"

    query = f"""
        WITH lactate_counts AS (
            SELECT
                workout_id,
                COUNT(*) as reading_count,
                MIN(lactate_mmol) as min_lactate,
                MAX(lactate_mmol) as max_lactate,
                MAX(test_type) as test_type
            FROM read_parquet('{_parquet_path("lactate")}')
            GROUP BY workout_id
        )
        SELECT
            w.workout_id,
            w.start_time_utc,
            w.start_time_utc::DATE as workout_date,
            w.erg_type,
            w.duration_s / 60.0 as duration_min,
            w.avg_hr_bpm,
            w.max_hr_bpm,
            l.reading_count,
            l.min_lactate,
            l.max_lactate,
            l.test_type
        FROM read_parquet('{_parquet_path("workouts")}') w
        JOIN lactate_counts l ON w.workout_id = l.workout_id
        WHERE w.erg_type IS NOT NULL
        {date_filter}
        ORDER BY w.start_time_utc DESC
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying Zone 2 workouts: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def get_workout_lactate_readings(workout_id: str) -> pd.DataFrame:
    """Get all lactate readings for a specific workout."""
    conn = get_connection()

    query = f"""
        SELECT
            reading_sequence,
            elapsed_minutes,
            lactate_mmol,
            watts_at_reading,
            hr_at_reading,
            measurement_context,
            notes
        FROM read_parquet('{_parquet_path("lactate")}')
        WHERE workout_id = '{workout_id}'
        ORDER BY reading_sequence
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying lactate readings: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def get_workout_stroke_data(workout_id: str) -> pd.DataFrame:
    """Get stroke-level data for a workout."""
    conn = get_connection()

    query = f"""
        SELECT
            time_cumulative_s / 60.0 as elapsed_min,
            heart_rate_bpm,
            watts,
            stroke_rate_spm as cadence
        FROM read_parquet('{_parquet_path("cardio_strokes")}')
        WHERE workout_id = '{workout_id}'
          AND heart_rate_bpm IS NOT NULL
          AND heart_rate_bpm > 0
        ORDER BY time_cumulative_s
    """

    try:
        return conn.execute(query).df()
    except Exception as e:
        st.warning(f"Error querying stroke data: {e}")
        return pd.DataFrame()


def calculate_interval_metrics(
    stroke_df: pd.DataFrame,
    lactate_df: pd.DataFrame,
) -> list[dict]:
    """
    Calculate metrics for intervals between lactate readings.

    Args:
        stroke_df: Stroke-level data with elapsed_min, heart_rate_bpm, watts, cadence
        lactate_df: Lactate readings with elapsed_minutes, lactate_mmol

    Returns:
        List of dicts with interval metrics
    """
    if stroke_df.empty or lactate_df.empty:
        return []

    intervals = []
    reading_times = [0] + lactate_df["elapsed_minutes"].tolist()

    for i in range(len(reading_times) - 1):
        start_min = reading_times[i]
        end_min = reading_times[i + 1]

        # Filter strokes for this interval
        mask = (stroke_df["elapsed_min"] >= start_min) & (stroke_df["elapsed_min"] < end_min)
        interval_data = stroke_df[mask]

        if interval_data.empty:
            continue

        # Get HR at start and end of interval for drift calculation
        hr_start = interval_data.iloc[:10]["heart_rate_bpm"].mean() if len(interval_data) >= 10 else interval_data.iloc[0]["heart_rate_bpm"]
        hr_end = interval_data.iloc[-10:]["heart_rate_bpm"].mean() if len(interval_data) >= 10 else interval_data.iloc[-1]["heart_rate_bpm"]

        # Lactate at end of this interval
        lactate_reading = lactate_df[lactate_df["elapsed_minutes"] == end_min]
        lactate_value = lactate_reading["lactate_mmol"].values[0] if not lactate_reading.empty else None

        intervals.append({
            "interval": i + 1,
            "start_min": round(start_min, 1),
            "end_min": round(end_min, 1),
            "duration_min": round(end_min - start_min, 1),
            "avg_watts": round(interval_data["watts"].mean(), 1),
            "avg_hr": round(interval_data["heart_rate_bpm"].mean(), 1),
            "hr_start": round(hr_start, 1),
            "hr_end": round(hr_end, 1),
            "hr_drift": round(hr_end - hr_start, 1),
            "avg_cadence": round(interval_data["cadence"].mean(), 1),
            "lactate_mmol": lactate_value,
        })

    return intervals


def calculate_cardiac_drift(stroke_df: pd.DataFrame, workout_duration_min: float) -> dict:
    """
    Calculate cardiac drift for a workout.

    Cardiac drift = increase in HR over time at constant power.
    Compares average HR of first half vs second half of session,
    excluding periods where power drops (lactate reading pauses).

    Args:
        stroke_df: Stroke-level data with elapsed_min, heart_rate_bpm, watts
        workout_duration_min: Total workout duration

    Returns:
        Dict with drift metrics
    """
    if stroke_df.empty or workout_duration_min < 20:
        return {"drift_pct": None, "drift_bpm": None, "status": "Insufficient data"}

    # Filter out power drops (pauses for lactate readings)
    # Power drops are typically <50% of session median power
    median_power = stroke_df["watts"].median()
    power_threshold = median_power * 0.5  # Below 50% of median = pause
    active_df = stroke_df[stroke_df["watts"] >= power_threshold].copy()

    if len(active_df) < 20:
        return {"drift_pct": None, "drift_bpm": None, "status": "Insufficient active data"}

    # Skip warmup (first 2 minutes)
    active_df = active_df[active_df["elapsed_min"] >= 2]

    if active_df.empty:
        return {"drift_pct": None, "drift_bpm": None, "status": "Insufficient data after warmup"}

    # Split into first half and second half
    midpoint = (active_df["elapsed_min"].min() + active_df["elapsed_min"].max()) / 2

    first_half = active_df[active_df["elapsed_min"] < midpoint]
    second_half = active_df[active_df["elapsed_min"] >= midpoint]

    if first_half.empty or second_half.empty:
        return {"drift_pct": None, "drift_bpm": None, "status": "Insufficient data for halves"}

    # Calculate averages for each half
    first_half_hr = first_half["heart_rate_bpm"].mean()
    second_half_hr = second_half["heart_rate_bpm"].mean()
    first_half_watts = first_half["watts"].mean()
    second_half_watts = second_half["watts"].mean()

    # Check power consistency between halves
    power_change_pct = abs(second_half_watts - first_half_watts) / first_half_watts * 100 if first_half_watts > 0 else 100

    if power_change_pct > 15:
        return {
            "drift_pct": None,
            "drift_bpm": None,
            "status": f"Power not constant ({power_change_pct:.0f}% change)",
            "early_hr": round(first_half_hr, 1),
            "late_hr": round(second_half_hr, 1),
            "early_watts": round(first_half_watts, 1),
            "late_watts": round(second_half_watts, 1),
        }

    # Calculate drift
    drift_bpm = second_half_hr - first_half_hr
    drift_pct = (drift_bpm / first_half_hr) * 100 if first_half_hr > 0 else 0

    # Normalize to per-hour rate
    active_duration_min = active_df["elapsed_min"].max() - active_df["elapsed_min"].min()
    time_span_hr = active_duration_min / 60
    drift_per_hour = drift_pct / time_span_hr if time_span_hr > 0 else drift_pct

    # Status based on drift per hour
    if drift_per_hour < 3:
        status = "Excellent"
    elif drift_per_hour < 5:
        status = "Good"
    elif drift_per_hour < 8:
        status = "Moderate"
    else:
        status = "High"

    # Period labels
    first_half_start = first_half["elapsed_min"].min()
    first_half_end = first_half["elapsed_min"].max()
    second_half_start = second_half["elapsed_min"].min()
    second_half_end = second_half["elapsed_min"].max()

    return {
        "drift_pct": round(drift_pct, 1),
        "drift_bpm": round(drift_bpm, 1),
        "drift_per_hour_pct": round(drift_per_hour, 1),
        "status": status,
        "early_hr": round(first_half_hr, 1),
        "late_hr": round(second_half_hr, 1),
        "early_watts": round(first_half_watts, 1),
        "late_watts": round(second_half_watts, 1),
        "early_period": f"{first_half_start:.0f}-{first_half_end:.0f} min",
        "late_period": f"{second_half_start:.0f}-{second_half_end:.0f} min",
        "excluded_samples": len(stroke_df) - len(active_df),
        "power_threshold": round(power_threshold, 0),
    }


@st.cache_data(ttl=3600)
def get_zone2_workout_analysis(workout_id: str) -> dict:
    """
    Get complete Zone 2 analysis for a workout.

    Returns dict with:
    - workout: Basic workout info
    - lactate_readings: List of lactate readings
    - intervals: Metrics per interval between readings
    - cardiac_drift: Overall drift calculation
    - stroke_summary: Aggregated stroke data for charting
    """
    conn = get_connection()
    result = {}

    # Get workout info
    try:
        workout_query = f"""
            SELECT
                workout_id,
                start_time_utc,
                erg_type,
                duration_s / 60.0 as duration_min,
                avg_hr_bpm,
                max_hr_bpm,
                avg_pace_sec_per_500m,
                notes
            FROM read_parquet('{_parquet_path("workouts")}')
            WHERE workout_id = '{workout_id}'
        """
        df = conn.execute(workout_query).df()
        if not df.empty:
            result["workout"] = df.iloc[0].to_dict()
        else:
            return {"error": "Workout not found"}
    except Exception as e:
        return {"error": str(e)}

    # Get lactate readings
    lactate_df = get_workout_lactate_readings(workout_id)
    result["lactate_readings"] = lactate_df.to_dict("records") if not lactate_df.empty else []

    # Get stroke data
    stroke_df = get_workout_stroke_data(workout_id)

    # Calculate interval metrics
    if not lactate_df.empty and not stroke_df.empty:
        result["intervals"] = calculate_interval_metrics(stroke_df, lactate_df)
    else:
        result["intervals"] = []

    # Calculate cardiac drift
    if not stroke_df.empty:
        result["cardiac_drift"] = calculate_cardiac_drift(
            stroke_df,
            result["workout"]["duration_min"]
        )
    else:
        result["cardiac_drift"] = {"status": "No stroke data"}

    # Aggregate stroke data for charting (1-minute buckets)
    if not stroke_df.empty:
        stroke_df["minute_bucket"] = stroke_df["elapsed_min"].astype(int)
        summary = stroke_df.groupby("minute_bucket").agg({
            "heart_rate_bpm": "mean",
            "watts": "mean",
            "cadence": "mean",
        }).reset_index()
        summary.columns = ["minute", "hr", "watts", "cadence"]
        result["stroke_summary"] = summary.to_dict("records")
    else:
        result["stroke_summary"] = []

    return result
