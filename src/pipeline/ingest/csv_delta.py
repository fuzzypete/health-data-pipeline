# src/pipeline/ingest/csv_delta.py
"""
HAE CSV ingestion - minute_facts and daily_summary.

Refactored to use source-first directory structure:
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
import pyarrow.parquet as pq
from datetime import datetime, timezone, time as dtime

from pipeline.paths import (
    RAW_HAE_CSV_DIR,
    ARCHIVE_HAE_CSV_DIR,
    MINUTE_FACTS_PATH,
    DAILY_SUMMARY_PATH,
)

log = logging.getLogger(__name__)
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

DEFAULT_SOURCE = "HAE_CSV"

try:
    from pipeline.common.schema import daily_summary_base
except Exception:
    daily_summary_base = None

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


def _add_required_fields(
    df: pd.DataFrame,
    source_value: str,
    csv_path: Path,
    ingest_run_id: str,
) -> pd.DataFrame:
    """
    Ensure timestamps, lineage, and tz — correctly converting local → UTC (handles DST).
    """
    TZ = "America/Los_Angeles"

    if "timestamp_utc" not in df.columns:
        if "timestamp_local" in df.columns:
            local = pd.to_datetime(df["timestamp_local"], errors="coerce", utc=False)
            df["timestamp_local"] = local
            df["timestamp_utc"] = (
                local.dt.tz_localize(TZ, ambiguous="infer", nonexistent="shift_forward")
                    .dt.tz_convert("UTC")
            )
        elif "timestamp" in df.columns:
            local = pd.to_datetime(df["timestamp"], errors="coerce", utc=False)
            df["timestamp"] = local
            df["timestamp_utc"] = (
                local.dt.tz_localize(TZ, ambiguous="infer", nonexistent="shift_forward")
                    .dt.tz_convert("UTC")
            )
        else:
            raise ValueError(f"{csv_path}: expected 'timestamp_utc' or 'timestamp_local'")
    else:
        # If truly UTC in CSV, just parse as UTC
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True)

    # Keep local timestamp if present (naive by design)
    if "timestamp_local" in df.columns:
        df["timestamp_local"] = pd.to_datetime(df["timestamp_local"], errors="coerce", utc=False)
        try:
            df["timestamp_local"] = df["timestamp_local"].dt.tz_localize(None)
        except Exception:
            pass

    if "tz_name" not in df.columns:
        df["tz_name"] = TZ

    df["source"] = source_value
    df["ingest_run_id"] = f"csv-{ingest_run_id}"
    df["ingest_time_utc"] = datetime.now(timezone.utc)
    return df


def _coerce_metric_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce canonical columns to appropriate dtypes.
    """
    int_cols = ["steps", "flights_climbed",
                "heart_rate_min", "heart_rate_max", "heart_rate_avg",
                "sleep_minutes_asleep", "sleep_minutes_in_bed"]
    float_cols = ["active_energy_kcal", "basal_energy_kcal", "calories_kcal",
                  "distance_mi", "sleep_score", "weight_lb", "body_fat_pct", "temperature_degF"]

    for c in int_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
            df[c] = df[c].round(0).astype("Int32")

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


def _to_table_with_partitions(df: pd.DataFrame) -> pa.Table:
    """Convert to PyArrow table with date partition column."""
    ts_utc = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True)
    date_utc = ts_utc.dt.tz_convert("UTC").dt.date
    df = df.assign(date=date_utc)
    return pa.Table.from_pandas(df, preserve_index=False)


def _write_parquet_dataset(table: pa.Table, root: Path) -> None:
    """Write Parquet dataset with partitioning."""
    root.mkdir(parents=True, exist_ok=True)
    pq.write_to_dataset(table, root_path=str(root))


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
    agg_map = {}
    for c in daily_pick_cols:
        if c not in df.columns:
            continue
        if c in {"steps", "flights_climbed", "distance_mi",
                 "active_energy_kcal", "basal_energy_kcal", "calories_kcal",
                 "sleep_minutes_asleep", "sleep_minutes_in_bed"}:
            agg_map[c] = pd.NamedAgg(column=c, aggfunc=lambda x: x.max() if x.notna().any() else np.nan)
        else:
            agg_map[c] = pd.NamedAgg(column=c, aggfunc="mean")

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
    now_utc = datetime.now(timezone.utc)
    out["source"] = source_value
    out["ingest_time_utc"] = now_utc
    out["ingest_run_id"] = ingest_run_id

    metric_cols = [c for c in out.columns if c not in {"date_utc", "source", "ingest_time_utc", "ingest_run_id"}]
    out = out.loc[out[metric_cols].notna().any(axis=1)].copy()
    if out.empty:
        return None

    # Ensure schema columns exist
    if daily_summary_base is not None:
        for name in daily_summary_base.names:
            if name not in out.columns:
                out[name] = None
        out = out.loc[:, daily_summary_base.names]

    # Arrow table
    table = pa.Table.from_pandas(out, preserve_index=False, schema=(daily_summary_base or None))
    table = table.append_column("date", table.column("date_utc"))
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
        meta = {"timestamp_utc", "timestamp_local", "tz_name", "source", "ingest_time_utc", "ingest_run_id", "date"}
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
def _write_minutes(df: pd.DataFrame) -> None:
    """Write minute-level data."""
    table = _to_table_with_partitions(df)
    _write_parquet_dataset(table, MINUTE_FACTS_PATH)


def process_single_csv(csv_path: Path, source_value: str, ingest_run_id: str) -> None:
    """Process a single CSV file."""
    try:
        df = _load_csv(csv_path)
        df = _add_required_fields(df, source_value=source_value, csv_path=csv_path, ingest_run_id=ingest_run_id)
        df = _coerce_metric_types(df)

        _log_minute_summary(csv_path, df)
        _write_minutes(df)

        daily_tbl = _build_daily_summary(df, source_value=source_value, ingest_run_id=ingest_run_id)
        if daily_tbl is not None:
            _write_parquet_dataset(daily_tbl, DAILY_SUMMARY_PATH)
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
    main()
