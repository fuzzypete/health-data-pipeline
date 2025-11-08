# src/pipeline/ingest/hae_csv.py
"""
HAE CSV ingestion - minute_facts and daily_summary.

Refactored to use common utilities for config, timestamps, and I/O.
- Reads from: Data/Raw/HAE/CSV/
- Archives to: Data/Raw/HAE/Archive/ (optional)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
from datetime import datetime, timezone, time as dtime

# --- Refactored Imports ---
from pipeline.paths import (
    RAW_HAE_CSV_DIR,
    ARCHIVE_HAE_CSV_DIR,
    MINUTE_FACTS_PATH,
    DAILY_SUMMARY_PATH,
)
from pipeline.common.config import get_home_timezone
from pipeline.common.schema import get_schema
from pipeline.common.timestamps import apply_strategy_a
from pipeline.common.parquet_io import (
    write_partitioned_dataset,
    add_lineage_fields,
    create_date_partition_column,
)
# --- End Refactored Imports ---

log = logging.getLogger(__name__)

DEFAULT_SOURCE = "HAE_CSV"

# Get schemas once
try:
    MINUTE_FACTS_SCHEMA = get_schema("minute_facts")
    DAILY_SUMMARY_SCHEMA = get_schema("daily_summary")
except ValueError as e:
    log.error(f"Could not load schemas. Have you defined 'minute_facts' and 'daily_summary'? Error: {e}")
    MINUTE_FACTS_SCHEMA = None
    DAILY_SUMMARY_SCHEMA = None

# ---------------------------------------------------------------------
# Column crosswalk: **daily totals only** (NOT minute streams)
# ---------------------------------------------------------------------
RENAME_MAP = {
    # time
    "Date/Time": "timestamp_local",

    # energy totals (kcal)
    "Active Energy (kcal)": "active_energy_kcal",
    "Resting Energy (kcal)": "basal_energy_kcal",
    "Dietary Energy (kcal)": "calories_kcal",

    # activity totals
    "Steps (count)": "steps",
    "Distance (mi)": "distance_mi",
    "Flights Climbed (count)": "flights_climbed",

    # sleep totals
    "Sleep Minutes Asleep (min)": "sleep_minutes_asleep",
    "Sleep Minutes In Bed (min)": "sleep_minutes_in_bed",
    "Sleep Score": "sleep_score",

    # body daily values (imperial)
    "Body Mass (lb)": "weight_lb",
    "Body Fat Percentage (%)": "body_fat_pct",
    "Body Temperature (degF)": "temperature_degF",
}

ML_PER_FL_OZ = 29.5735  # imperial conversion


# ---------------------------------------------------------------------
# CSV loading / normalization
# ---------------------------------------------------------------------
def _load_csv(csv_path: Path) -> pd.DataFrame:
    """
    Load a raw CSV from HAE. Strip headers and apply **daily-total** renames only.
    Any other columns remain unmapped (minute-level metrics by design).
    """
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()

    # Audit before rename so we can see what stays in minutes by design
    orig_columns_before_rename = list(df.columns)

    df = df.rename(columns=RENAME_MAP)

    # Anything not mapped belongs to minute_facts on purpose
    _unmapped = [
        c for c in orig_columns_before_rename
        if c not in RENAME_MAP and c != "timestamp_utc"
    ]
    if _unmapped:
        log.info("unmapped_minute_metrics: count=%d %s", len(_unmapped), _unmapped[:6])

    return df


def _apply_timestamp_strategy(df: pd.DataFrame, csv_path: Path) -> pd.DataFrame:
    """
    Apply Strategy A (Assumed Timezone) using common utility.
    """
    home_tz = get_home_timezone()
    
    # Find the correct timestamp column
    ts_col = None
    if "timestamp_local" in df.columns:
        ts_col = "timestamp_local"
    elif "timestamp" in df.columns:
        ts_col = "timestamp"
    
    if not ts_col:
        raise ValueError(f"{csv_path}: No suitable timestamp column found ('timestamp_local' or 'timestamp')")

    # Rename to the canonical 'timestamp_local' if it's not already
    if ts_col != "timestamp_local":
         df.rename(columns={ts_col: "timestamp_local"}, inplace=True)
         ts_col = "timestamp_local"

    # Use the common Strategy A function
    # This adds: timestamp_local (naive), timestamp_utc (aware), tz_name, tz_source
    df = apply_strategy_a(df, timestamp_col=ts_col, home_timezone=home_tz)
    
    return df


def _coerce_metric_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce canonical columns to appropriate dtypes.
    """
    # Note: Int32 (capital I) allows for <NA> values
    int_cols = ["steps", "flights_climbed",
                "sleep_minutes_asleep", "sleep_minutes_in_bed"]
                
    # These come from minute-level data, which may not be present in every file
    min_lvl_int_cols = ["heart_rate_min", "heart_rate_max", "heart_rate_avg"]

    float_cols = ["active_energy_kcal", "basal_energy_kcal", "calories_kcal",
                  "distance_mi", "sleep_score", "weight_lb", "body_fat_pct", "temperature_degF"]

    for c in int_cols + min_lvl_int_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").round(0).astype("Int32")

    for c in float_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df


def _find_water_fl_oz(df: pd.DataFrame) -> Optional[pd.Series]:
    """Find water column and convert to fl oz if needed."""
    for col in df.columns:
        cl = col.lower()
        if "water" in cl:
            w = pd.to_numeric(df[col], errors="coerce")
            if "ml" in cl:
                w = w / ML_PER_FL_OZ
            return w
    return None


# ---------------------------------------------------------------------
# Daily summary (midnight-first, then fallback)
# ---------------------------------------------------------------------
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
        "weight_lb", "body_fat_pct", "temperature_degF"
    ]
    daily_pick_cols = [c for c in daily_pick_cols if c in df.columns]

    parts = []

    # Strategy 1: midnight row (local)
    if "timestamp_local" in df.columns:
        ts_local = pd.to_datetime(df["timestamp_local"], errors="coerce", utc=False)
        df["time_local"] = ts_local.dt.time
        midnight_mask = df["time_local"] == dtime(0, 0)
        midnight_df = df.loc[midnight_mask]
        if not midnight_df.empty:
            midnight_df = midnight_df.groupby("date_utc").first().reset_index()
            parts.append(midnight_df[["date_utc"] + daily_pick_cols])

    # Fallback: aggregation
    def safe_max(x):
        return x.max() if x.notna().any() else np.nan

    agg_map = {}
    for c in daily_pick_cols:
        if c not in df.columns:
            continue
        if c in {"steps", "flights_climbed", "distance_mi",
                "active_energy_kcal", "basal_energy_kcal", "calories_kcal",
                "sleep_minutes_asleep", "sleep_minutes_in_bed"}:
            agg_map[c] = safe_max
        else:
            agg_map[c] = "mean"

    g = df.groupby("date_utc", as_index=False)
    if agg_map:
        fallback = g.agg(agg_map)
        parts.append(fallback)

    if not parts:
        return None

    out = parts[0]
    for p in parts[1:]:
        out = out.merge(p, on="date_utc", how="outer", suffixes=("", "_fb"))
    for c in daily_pick_cols:
        if c in out.columns and f"{c}_fb" in out.columns:
            out[c] = out[c].where(out[c].notna(), out[f"{c}_fb"])
            out = out.drop(columns=[f"{c}_fb"])

    # Hydration
    w = _find_water_fl_oz(df)
    if w is not None:
        wdf = pd.DataFrame({"date_utc": df["date_utc"], "water_fl_oz": w})
        wagg = wdf.groupby("date_utc", as_index=False)["water_fl_oz"].max(min_count=1)
        out = out.merge(wagg, on="date_utc", how="left")

    # Derived
    if {"active_energy_kcal", "basal_energy_kcal"}.issubset(out.columns):
        out["energy_total_kcal"] = (out["active_energy_kcal"].fillna(0) + out["basal_energy_kcal"].fillna(0)).round(0)
    if {"sleep_minutes_asleep", "sleep_minutes_in_bed"}.issubset(out.columns):
        denom = out["sleep_minutes_in_bed"].replace({0: np.nan})
        out["sleep_efficiency_pct"] = (out["sleep_minutes_asleep"] / denom * 100).round(1)
    if {"calories_kcal", "energy_total_kcal"}.issubset(out.columns):
        out["net_energy_kcal"] = (out["calories_kcal"] - out["energy_total_kcal"]).round(0)

    # Lineage
    out = add_lineage_fields(out, source_value, ingest_run_id)

    metric_cols = [c for c in out.columns if c not in {"date_utc", "source", "ingest_time_utc", "ingest_run_id"}]
    out = out.loc[out[metric_cols].notna().any(axis=1)].copy()
    if out.empty:
        return None

    # Ensure schema columns exist
    if DAILY_SUMMARY_SCHEMA is not None:
        for name in DAILY_SUMMARY_SCHEMA.names:
            if name not in out.columns:
                out[name] = None
        # Reorder and select only schema columns
        out = out[DAILY_SUMMARY_SCHEMA.names]

    # Create partition column
    out = create_date_partition_column(out, 'date_utc', 'date', 'D')

    # Arrow table
    table = pa.Table.from_pandas(out, preserve_index=False, schema=DAILY_SUMMARY_SCHEMA)
    return table


# ---------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------
def _log_minute_summary(csv_path: Path, df: pd.DataFrame) -> None:
    """Log summary of minute-level data."""
    try:
        rows = len(df)
        if rows == 0:
            log.info("minutes: %s → rows=0 (nothing to do)", csv_path.name)
            return
        ts = pd.to_datetime(df["timestamp_utc"], errors="coerce")
        tmin, tmax = ts.min(), ts.max()
        meta = {"timestamp_utc", "timestamp_local", "tz_name", "tz_source", "source", "ingest_time_utc", "ingest_run_id", "date"}
        metric_cols = [c for c in df.columns if c not in meta]
        nonnull_counts = []
        for c in metric_cols:
            try:
                nonnull_counts.append((c, int(pd.Series(df[c]).notna().sum())))
            except Exception:
                continue
        nonnull_counts.sort(key=lambda x: (-x[1], x[0]))
        top = ", ".join(f"{k}:{v}" for k, v in nonnull_counts[:6])
        log.info(
            "minutes: %s → rows=%d, window=%s..%s, non_null_top=[%s]",
            csv_path.name, rows, tmin, tmax, top
        )
    except Exception as e:
        log.warning("minutes: %s → summary failed: %s", csv_path.name, e)


def _log_daily_summary_written(daily_tbl: pa.Table) -> None:
    """Log summary of daily data written."""
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


# ---------------------------------------------------------------------
# Main per-file pipeline
# ---------------------------------------------------------------------
def process_minute_facts(df: pd.DataFrame, source_value: str, ingest_run_id: str) -> None:
    """
    Process and write minute-level data.
    """
    # Add lineage
    df = add_lineage_fields(df, source_value, ingest_run_id)
    
    # Create partition column
    df = create_date_partition_column(df, 'timestamp_utc', 'date', 'D')
    
    # Write using common helper
    write_partitioned_dataset(
        df,
        MINUTE_FACTS_PATH,
        partition_cols=['date', 'source'],
        schema=MINUTE_FACTS_SCHEMA,
        mode='overwrite_or_ignore' # safe mode for time-series
    )


def process_single_csv(csv_path: Path, source_value: str, ingest_run_id: str) -> None:
    """Process a single CSV file."""
    try:
        df = _load_csv(csv_path)
        df = _apply_timestamp_strategy(df, csv_path) # Refactored
        df = _coerce_metric_types(df)

        # Use .copy() to avoid SettingWithCopyWarning
        minute_df = df.copy()
        daily_df = df # No copy needed for last use

        # Process and write minute facts
        _log_minute_summary(csv_path, minute_df)
        process_minute_facts(minute_df, source_value, ingest_run_id) # Refactored

        # Process and write daily summary
        daily_tbl = _build_daily_summary(daily_df, source_value=source_value, ingest_run_id=ingest_run_id)
        if daily_tbl is not None:
            write_partitioned_dataset( # Use common helper
                daily_tbl,
                DAILY_SUMMARY_PATH,
                partition_cols=['date', 'source'],
                schema=DAILY_SUMMARY_SCHEMA,
                mode='delete_matching' # Daily summaries should overwrite
            )
            _log_daily_summary_written(daily_tbl)
            log.info("OK: %s → %s (daily_summary written)", csv_path.name, DAILY_SUMMARY_PATH)
        else:
            log.info("OK: %s → %s (daily_summary skipped: no metrics)", csv_path.name, DAILY_SUMMARY_PATH)

        log.info("OK: %s → %s", csv_path.name, MINUTE_FACTS_PATH)
    except Exception as e:
        log.error("Failed on %s: %s", csv_path, e, exc_info=True)
        raise


def _iter_raw_csvs(raw_dir: Path) -> Iterable[Path]:
    """Iterate over CSV files in directory."""
    return sorted(raw_dir.glob("*.csv"))


def main() -> None:
    """
    Process all CSV files in Data/Raw/HAE/CSV/
    
    Files are read from RAW_HAE_CSV_DIR and processed into:
    - Data/Parquet/minute_facts/
    - Data/Parquet/daily_summary/
    
    To archive processed files, uncomment the archive lines below.
    """
    files = list(_iter_raw_csvs(RAW_HAE_CSV_DIR))
    if not files:
        log.info("No CSV files found in %s", RAW_HAE_CSV_DIR)
        return

    processed = 0
    failed = 0
    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    
    for f in files:
        try:
            process_single_csv(f, DEFAULT_SOURCE, ingest_run_id)
            
            # Optional: Move to archive after successful processing
            # archive_path = ARCHIVE_HAE_CSV_DIR / f.name
            # f.rename(archive_path)
            # log.info("Archived: %s → %s", f.name, archive_path)
            
            processed += 1
        except Exception:
            failed += 1
            
    log.info("Run complete. Processed=%d Failed=%d", processed, failed)


if __name__ == "__main__":
    if not log.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
    main()