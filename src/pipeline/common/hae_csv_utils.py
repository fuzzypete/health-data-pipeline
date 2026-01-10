# src/pipeline/common/hae_csv_utils.py
"""
Shared "Load" logic for both HAE CSV ingestion scripts.

This module contains all the common functions for processing a
DataFrame after it has been loaded and transformed (renamed, units converted)
by its specific ingestion script.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa
from datetime import time as dtime

from pipeline.paths import MINUTE_FACTS_PATH, DAILY_SUMMARY_PATH
from pipeline.common.schema import get_schema
from pipeline.common.timestamps import apply_strategy_a
from pipeline.common.parquet_io import (
    write_partitioned_dataset,
    upsert_by_key,
    read_partitioned_dataset,
    add_lineage_fields,
    create_date_partition_column,
)

log = logging.getLogger(__name__)

# Get schemas once
try:
    MINUTE_FACTS_SCHEMA = get_schema("minute_facts")
    DAILY_SUMMARY_SCHEMA = get_schema("daily_summary")
except ValueError as e:
    log.error(f"Could not load schemas. Have you defined 'minute_facts' and 'daily_summary'? Error: {e}")
    MINUTE_FACTS_SCHEMA = None
    DAILY_SUMMARY_SCHEMA = None

ML_PER_FL_OZ = 29.5735  # imperial conversion

# ---------------------------------------------------------------------
# Shared "Load" Functions
# ---------------------------------------------------------------------

def _coerce_metric_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce canonical columns to appropriate dtypes.
    """
    # Note: Int32 (capital I) allows for <NA> values
    int_cols = [
        "steps", "flights_climbed", "sleep_minutes_asleep", 
        "sleep_minutes_in_bed", "apple_exercise_time_min", 
        "mindful_minutes_min", "time_in_daylight_min"
    ]
                
    float_cols = [
        "active_energy_kcal", "basal_energy_kcal", "diet_calories_kcal",
        "distance_mi", "sleep_score", "weight_lb", "body_fat_pct", "temperature_degF",
        "sleeping_wrist_temp_degf", "blood_glucose_mg_dl", "blood_oxygen_saturation_pct",
        "blood_pressure_diastolic_mmhg", "blood_pressure_systolic_mmhg",
        "body_mass_index_count", "carbs_g", "cardio_recovery_count_min",
        "cycling_distance_mi", "fiber_g", "hrv_ms", "heart_rate_avg",
        "heart_rate_max", "heart_rate_min", "lean_body_mass_lb",
        "physical_effort_kcal_hr_kg", "protein_g", "respiratory_rate_count_min",
        "resting_hr_bpm", "sleep_asleep_hr", "sleep_awake_hr", "sleep_core_hr",
        "sleep_deep_hr", "sleep_in_bed_hr", "sleep_rem_hr", "sleep_total_hr",
        "total_fat_g", "vo2_max_ml_kg_min", "walking_running_distance_mi", "water_fl_oz"
    ]

    for c in int_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").round(0).astype("Int32")

    for c in float_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df


def _find_water_fl_oz(df: pd.DataFrame) -> Optional[pd.Series]:
    """Find water column and convert to fl oz if needed."""
    
    if 'water_fl_oz' in df.columns:
         # It's already float, just round and cast to Int32 for daily summary
        return df['water_fl_oz'].round(0).astype('Int32')

    # Fallback for old "Water (ml)" column
    for col in df.columns:
        cl = col.lower()
        if "water (ml)" in cl:
            w = pd.to_numeric(df[col], errors="coerce")
            w = w / ML_PER_FL_OZ
            w = w.round(0).astype('Int32') 
            return w
            
    return None


def _build_daily_summary(
    df: pd.DataFrame,
    source_value: str,
    ingest_run_id: str
) -> Optional[pa.Table]:
    """
    Build wide daily_summary per (date_utc, source) with 'midnight-row' preference.
    """
    df = df.copy()
    
    # --- FIX: Group by LOCAL Date (Strategy A) ---
    # Strategy A guarantees 'timestamp_local' exists and reflects the user's wall clock time.
    # We want '2026-01-09' to mean Jan 9th Pacific, not Jan 9th UTC.
    if "timestamp_local" in df.columns:
        ts_local = pd.to_datetime(df["timestamp_local"], errors="coerce")
        df["date_group"] = ts_local.dt.date
        date_col = "date_group"
    else:
        # Fallback to UTC if local is missing (shouldn't happen with Strategy A)
        log.warning("timestamp_local missing, falling back to UTC date aggregation")
        ts_utc = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True)
        df["date_group"] = ts_utc.dt.date
        date_col = "date_group"

    daily_pick_cols = [
        "steps", "distance_mi", "flights_climbed",
        "active_energy_kcal", "basal_energy_kcal", "diet_calories_kcal",
        "sleep_minutes_asleep", "sleep_minutes_in_bed", "sleep_score",
        "weight_lb", "body_fat_pct", "temperature_degF",
        "resting_hr_bpm", "hrv_ms", "respiratory_rate_count_min", # Note: 'respiratory_rate_bpm' in schema
        "protein_g", "carbs_g", "fat_g"
    ]
    daily_pick_cols = [c for c in daily_pick_cols if c in df.columns]

    def safe_sum(x):
        return x.sum() if x.notna().any() else np.nan

    def safe_mean(x):
        return x.mean() if x.notna().any() else np.nan

    # Columns that should be SUMMED (cumulative daily totals from minute-level data)
    # These MUST use sum aggregation, not midnight row values
    sum_cols = {"steps", "flights_climbed", "distance_mi",
                "active_energy_kcal", "basal_energy_kcal", "diet_calories_kcal",
                "sleep_minutes_asleep", "sleep_minutes_in_bed",
                "protein_g", "carbs_g", "fat_g"}

    # Build aggregate for all columns
    agg_map = {}
    for c in daily_pick_cols:
        if c not in df.columns: continue
        if c in sum_cols:
            agg_map[c] = safe_sum
        else:
            agg_map[c] = safe_mean

    g = df.groupby("date_group", as_index=False)
    if not agg_map:
        log.warning("No daily summary data could be built (no aggregable columns)")
        return None

    out = g.agg(agg_map)

    # Rename grouping key to canonical 'date' for schema
    out = out.rename(columns={"date_group": "date"})

    # For non-sum columns only, prefer midnight row values if available
    # (point-in-time measurements like weight, body_fat, resting_hr)
    midnight_cols = [c for c in daily_pick_cols if c not in sum_cols]
    if midnight_cols and "timestamp_local" in df.columns:
        ts_local = pd.to_datetime(df["timestamp_local"], errors="coerce", utc=False)
        df["time_local"] = ts_local.dt.time
        midnight_mask = df["time_local"] == dtime(0, 0)
        midnight_df = df.loc[midnight_mask]
        if not midnight_df.empty:
            # Group midnight rows by local date too
            midnight_df["date"] = pd.to_datetime(midnight_df["timestamp_local"]).dt.date
            midnight_df = midnight_df.groupby("date").first().reset_index()
            midnight_df = midnight_df[["date"] + midnight_cols]
            out = out.merge(midnight_df, on="date", how="left", suffixes=("", "_mid"))
            for c in midnight_cols:
                if f"{c}_mid" in out.columns:
                    # Prefer midnight value if available
                    out[c] = out[f"{c}_mid"].where(out[f"{c}_mid"].notna(), out[c])
                    out = out.drop(columns=[f"{c}_mid"])

    w = _find_water_fl_oz(df)
    if w is not None:
        # Water grouping also needs to align
        wdf = pd.DataFrame({"date": df["date_group"], "water_fl_oz": w})
        wagg = wdf.groupby("date", as_index=False)["water_fl_oz"].sum(min_count=1)
        out = out.merge(wagg, on="date", how="left")

    if {"active_energy_kcal", "basal_energy_kcal"}.issubset(out.columns):
        out["energy_total_kcal"] = (out["active_energy_kcal"].fillna(0) + out["basal_energy_kcal"].fillna(0)).round(0)
    if {"sleep_minutes_asleep", "sleep_minutes_in_bed"}.issubset(out.columns):
        denom = out["sleep_minutes_in_bed"].replace({0: np.nan})
        out["sleep_efficiency_pct"] = (out["sleep_minutes_asleep"] / denom * 100).round(1)
    if {"calories_kcal", "energy_total_kcal"}.issubset(out.columns):
        out["net_energy_kcal"] = (out["diet_calories_kcal"] - out["energy_total_kcal"]).round(0)

    out = add_lineage_fields(out, source_value, ingest_run_id)
    metric_cols = [c for c in out.columns if c not in {"date", "source", "ingest_time_utc", "ingest_run_id"}]
    out = out.loc[out[metric_cols].notna().any(axis=1)].copy()
    if out.empty:
        return None

    if DAILY_SUMMARY_SCHEMA is not None:
        for name in DAILY_SUMMARY_SCHEMA.names:
            if name == 'respiratory_rate_bpm' and 'respiratory_rate_count_min' in out.columns:
                out[name] = out['respiratory_rate_count_min']
            elif name not in out.columns:
                out[name] = None
        out = out[DAILY_SUMMARY_SCHEMA.names]

    # Partition by the new local 'date' column
    # Since 'date' is already YYYY-MM-DD object, we can just cast to string
    # create_date_partition_column is usually for timestamps, but here we have the date.
    # We can just ensure it's a string.
    out["date"] = out["date"].astype(str)
    
    # We don't need create_date_partition_column anymore as we built 'date' manually
    # But write_partitioned_dataset expects it.
    # Convert to PyArrow table
    table = pa.Table.from_pandas(out, preserve_index=False, schema=DAILY_SUMMARY_SCHEMA)
    return table


def _log_minute_summary(csv_path: Path, df: pd.DataFrame) -> None:
    try:
        rows = len(df)
        if rows == 0:
            log.info("minutes: %s → rows=0 (nothing to do)", csv_path.name)
            return
        ts = pd.to_datetime(df["timestamp_utc"], errors="coerce")
        tmin, tmax = ts.min(), ts.max()
        meta = {"timestamp_utc", "timestamp_local", "tz_name", "tz_source", "source", "ingest_time_utc", "ingest_run_id", "date"}
        
        metric_cols = [
            c for c in df.columns if c in MINUTE_FACTS_SCHEMA.names and c not in meta
        ]
        
        nonnull_counts = []
        for c in metric_cols:
            try:
                nonnull_counts.append((c, int(pd.Series(df[c]).notna().sum())))
            except Exception:
                continue
        
        nonnull_counts = [x for x in nonnull_counts if x[1] > 0]
        nonnull_counts.sort(key=lambda x: (-x[1], x[0]))
        
        top = ", ".join(f"{k}:{v}" for k, v in nonnull_counts[:6])
        log.info(
            "minutes: %s → rows=%d, window=%s..%s, top_known_metrics=[%s]",
            csv_path.name, rows, tmin, tmax, top
        )
    except Exception as e:
        log.warning("minutes: %s → summary failed: %s", e)


def _log_daily_summary_written(daily_tbl: pa.Table) -> None:
    try:
        pdf = daily_tbl.to_pandas()
        n = len(pdf)
        if n == 0:
            log.info("daily_summary: wrote 0 rows")
            return
        dmin = str(pdf["date_utc"].min())
        dmax = str(pdf["date_utc"].max())
        sample = pdf.sort_values("date_utc").iloc[-1]
        fields = []
        for k in ["steps", "active_energy_kcal", "energy_total_kcal",
                  "sleep_minutes_asleep", "sleep_efficiency_pct", "water_fl_oz",
                  "diet_calories_kcal", "protein_g", "carbs_g", "total_fat_g"]:
            if k in pdf.columns and pd.notna(sample.get(k)):
                val = sample[k]
                if isinstance(val, float):
                    val = int(val) if abs(val - int(val)) < 1e-6 else round(val, 1)
                fields.append(f"{k}={val}")
        metrics_str = ", ".join(fields) if fields else "no-metrics"
        log.info("daily_summary: rows=%d, dates=%s..%s, sample={%s}", n, dmin, dmax, metrics_str)
    except Exception as e:
        log.warning("daily_summary: summary failed: %s", e)

def _process_minute_facts(df: pd.DataFrame, source_value: str, ingest_run_id: str) -> list:
    """
    Process and write minute-level data using upsert to accumulate data.

    Returns:
        List of affected date strings (YYYY-MM-DD) for rebuilding daily_summary.
    """
    df = add_lineage_fields(df, source_value, ingest_run_id)
    df = create_date_partition_column(df, 'timestamp_utc', 'date', 'D')

    # Get affected dates before writing
    affected_dates = df['date'].unique().tolist()

    # Use upsert to ACCUMULATE minute data (not replace)
    # Primary key is timestamp_utc + source - same minute from same source = update
    upsert_by_key(
        df,
        MINUTE_FACTS_PATH,
        primary_key=['timestamp_utc', 'source'],
        partition_cols=['date', 'source'],
        schema=MINUTE_FACTS_SCHEMA,
    )

    return affected_dates


def run_hae_csv_pipeline(
    csv_path: Path,
    df: pd.DataFrame,
    source_value: str,
    ingest_run_id: str,
    home_timezone: str
) -> None:
    """
    The common "Load" pipeline for HAE CSV data.

    This pipeline ACCUMULATES minute data across multiple files and rebuilds
    daily_summary from the complete accumulated data. This ensures partial-day
    exports eventually produce complete daily totals.

    Args:
        csv_path: The path to the original CSV file (for logging).
        df: The pre-loaded and pre-transformed DataFrame.
        source_value: The source string to use (e.g., "HAE_CSV_Automation").
        ingest_run_id: The unique ID for this ingestion run.
        home_timezone: The IANA timezone string to assume for Strategy A.
    """
    try:
        df = apply_strategy_a(df, timestamp_col="timestamp_local", home_timezone=home_timezone)
        df = _coerce_metric_types(df)

        minute_df = df.copy()

        _log_minute_summary(csv_path, minute_df)

        # Process minute facts with upsert (accumulates data)
        affected_dates = _process_minute_facts(minute_df, source_value, ingest_run_id)
        log.info("OK: %s → %s (affected dates: %s)", csv_path.name, MINUTE_FACTS_PATH, affected_dates)

        # Rebuild daily_summary from ACCUMULATED minute_facts (not just this file)
        if affected_dates:
            _rebuild_daily_summary_from_minutes(
                affected_dates,
                source_value,
                ingest_run_id
            )
        else:
            log.info("OK: %s → daily_summary skipped (no affected dates)", csv_path.name)

    except Exception as e:
        log.error("Failed on %s: %s", csv_path, e, exc_info=True)
        raise


def _rebuild_daily_summary_from_minutes(
    affected_dates: list,
    source_value: str,
    ingest_run_id: str
) -> None:
    """
    Rebuild daily_summary for affected dates from accumulated minute_facts.

    This ensures partial exports eventually produce complete daily totals
    as more data accumulates in minute_facts.
    """
    # Build DNF filter: (date in affected_dates) AND (source = source_value)
    # DNF format: OR across list items, use ('and', ...) for compound AND clauses
    # Each item: ('and', ('date', '=', d), ('source', '=', s))
    filters = [
        ('and', ('date', '=', d), ('source', '=', source_value))
        for d in affected_dates
    ]

    # Read accumulated minute data for affected dates
    try:
        minute_df = read_partitioned_dataset(
            MINUTE_FACTS_PATH,
            filters=filters,
        )
    except Exception as e:
        log.warning("Could not read minute_facts for rebuild: %s", e)
        return

    if minute_df.empty:
        log.warning("No minute data found for affected dates, skipping daily_summary rebuild")
        return

    log.info("Rebuilding daily_summary from %d accumulated minutes for %d dates",
             len(minute_df), len(affected_dates))

    # Build daily summary from complete accumulated data
    daily_tbl = _build_daily_summary(minute_df, source_value=source_value, ingest_run_id=ingest_run_id)

    if daily_tbl is not None:
        write_partitioned_dataset(
            daily_tbl,
            DAILY_SUMMARY_PATH,
            partition_cols=['date', 'source'],
            schema=DAILY_SUMMARY_SCHEMA,
            mode='delete_matching'  # OK to replace - we have complete data now
        )
        _log_daily_summary_written(daily_tbl)
    else:
        log.warning("daily_summary rebuild produced no data")