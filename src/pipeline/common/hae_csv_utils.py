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
        "active_energy_kcal", "basal_energy_kcal", "calories_kcal",
        "distance_mi", "sleep_score", "weight_lb", "body_fat_pct", "temperature_degF",
        "sleeping_wrist_temp_degf", "blood_glucose_mg_dl", "blood_oxygen_saturation_pct",
        "blood_pressure_diastolic_mmhg", "blood_pressure_systolic_mmhg",
        "body_mass_index_count", "carbohydrates_g", "cardio_recovery_count_min",
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
    ts_utc = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True)
    df["date_utc"] = ts_utc.dt.date

    daily_pick_cols = [
        "steps", "distance_mi", "flights_climbed",
        "active_energy_kcal", "basal_energy_kcal", "calories_kcal",
        "sleep_minutes_asleep", "sleep_minutes_in_bed", "sleep_score",
        "weight_lb", "body_fat_pct", "temperature_degF",
        "resting_hr_bpm", "hrv_ms", "respiratory_rate_count_min", # Note: 'respiratory_rate_bpm' in schema
        "protein_g", "carbs_g", "fat_g"
    ]
    daily_pick_cols = [c for c in daily_pick_cols if c in df.columns]

    parts = []

    if "timestamp_local" in df.columns:
        ts_local = pd.to_datetime(df["timestamp_local"], errors="coerce", utc=False)
        df["time_local"] = ts_local.dt.time
        midnight_mask = df["time_local"] == dtime(0, 0)
        midnight_df = df.loc[midnight_mask]
        if not midnight_df.empty:
            midnight_df = midnight_df.groupby("date_utc").first().reset_index()
            parts.append(midnight_df[["date_utc"] + daily_pick_cols])

    def safe_max(x):
        return x.max() if x.notna().any() else np.nan
        
    def safe_mean(x):
        return x.mean() if x.notna().any() else np.nan

    agg_map = {}
    for c in daily_pick_cols:
        if c not in df.columns: continue
        if c in {"steps", "flights_climbed", "distance_mi",
                "active_energy_kcal", "basal_energy_kcal", "calories_kcal",
                "sleep_minutes_asleep", "sleep_minutes_in_bed",
                "protein_g", "carbs_g", "fat_g"}:
            agg_map[c] = safe_max
        else:
            agg_map[c] = safe_mean

    g = df.groupby("date_utc", as_index=False)
    if agg_map:
        fallback = g.agg(agg_map)
        parts.append(fallback)

    if not parts:
        log.warning("No daily summary data could be built (no midnight row or aggregable data)")
        return None

    out = parts[0]
    for p in parts[1:]:
        out = out.merge(p, on="date_utc", how="outer", suffixes=("", "_fb"))
    for c in daily_pick_cols:
        if c in out.columns and f"{c}_fb" in out.columns:
            out[c] = out[c].where(out[c].notna(), out[f"{c}_fb"])
            out = out.drop(columns=[f"{c}_fb"])

    w = _find_water_fl_oz(df)
    if w is not None:
        wdf = pd.DataFrame({"date_utc": df["date_utc"], "water_fl_oz": w})
        wagg = wdf.groupby("date_utc", as_index=False)["water_fl_oz"].max(min_count=1)
        out = out.merge(wagg, on="date_utc", how="left")

    if {"active_energy_kcal", "basal_energy_kcal"}.issubset(out.columns):
        out["energy_total_kcal"] = (out["active_energy_kcal"].fillna(0) + out["basal_energy_kcal"].fillna(0)).round(0)
    if {"sleep_minutes_asleep", "sleep_minutes_in_bed"}.issubset(out.columns):
        denom = out["sleep_minutes_in_bed"].replace({0: np.nan})
        out["sleep_efficiency_pct"] = (out["sleep_minutes_asleep"] / denom * 100).round(1)
    if {"calories_kcal", "energy_total_kcal"}.issubset(out.columns):
        out["net_energy_kcal"] = (out["calories_kcal"] - out["energy_total_kcal"]).round(0)

    out = add_lineage_fields(out, source_value, ingest_run_id)
    metric_cols = [c for c in out.columns if c not in {"date_utc", "source", "ingest_time_utc", "ingest_run_id"}]
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

    out = create_date_partition_column(out, 'date_utc', 'date', 'D')
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
                  "sleep_minutes_asleep", "sleep_efficiency_pct", "water_fl_oz"]:
            if k in pdf.columns and pd.notna(sample.get(k)):
                val = sample[k]
                if isinstance(val, float):
                    val = int(val) if abs(val - int(val)) < 1e-6 else round(val, 1)
                fields.append(f"{k}={val}")
        metrics_str = ", ".join(fields) if fields else "no-metrics"
        log.info("daily_summary: rows=%d, dates=%s..%s, sample={%s}", n, dmin, dmax, metrics_str)
    except Exception as e:
        log.warning("daily_summary: summary failed: %s", e)


def _process_minute_facts(df: pd.DataFrame, source_value: str, ingest_run_id: str) -> None:
    """
    Process and write minute-level data.
    """
    df = add_lineage_fields(df, source_value, ingest_run_id)
    df = create_date_partition_column(df, 'timestamp_utc', 'date', 'D')
    
    write_partitioned_dataset(
        df,
        MINUTE_FACTS_PATH,
        partition_cols=['date', 'source'],
        schema=MINUTE_FACTS_SCHEMA,
        mode='delete_matching' # <-- THIS IS THE FIX
    )


def run_hae_csv_pipeline(
    csv_path: Path, 
    df: pd.DataFrame, 
    source_value: str, 
    ingest_run_id: str,
    home_timezone: str
) -> None:
    """
    The common "Load" pipeline for HAE CSV data.
    
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
        daily_df = df

        _log_minute_summary(csv_path, minute_df)
        _process_minute_facts(minute_df, source_value, ingest_run_id)

        daily_tbl = _build_daily_summary(daily_df, source_value=source_value, ingest_run_id=ingest_run_id)
        if daily_tbl is not None:
            write_partitioned_dataset(
                daily_tbl,
                DAILY_SUMMARY_PATH,
                partition_cols=['date', 'source'],
                schema=DAILY_SUMMARY_SCHEMA,
                mode='delete_matching'
            )
            _log_daily_summary_written(daily_tbl)
            log.info("OK: %s → %s (daily_summary written)", csv_path.name, DAILY_SUMMARY_PATH)
        else:
            log.info("OK: %s → %s (daily_summary skipped: no metrics)", csv_path.name, DAILY_SUMMARY_PATH)

        log.info("OK: %s → %s", csv_path.name, MINUTE_FACTS_PATH)
    except Exception as e:
        log.error("Failed on %s: %s", csv_path, e, exc_info=True)
        raise