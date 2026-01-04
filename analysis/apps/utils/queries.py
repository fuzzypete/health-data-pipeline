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
