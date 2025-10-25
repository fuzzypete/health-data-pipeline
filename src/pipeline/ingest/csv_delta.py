# src/pipeline/ingest/csv_delta.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime, timezone, time as dtime

log = logging.getLogger(__name__)
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

# ---------------------------------------------------------------------
# Optional imports from your project; fallback to local defaults
# ---------------------------------------------------------------------
DEFAULT_SOURCE = "HAE_CSV"

try:
    # If your project exposes canonical paths + schema
    from pipeline.common.paths import DATA_DIR, MINUTE_FACTS_PATH, DAILY_SUMMARY_PATH  # type: ignore
except Exception:
    DATA_DIR = Path("Data")
    MINUTE_FACTS_PATH = DATA_DIR / "Parquet" / "minute_facts"
    DAILY_SUMMARY_PATH = DATA_DIR / "Parquet" / "daily_summary"

try:
    from pipeline.common.schema import daily_summary_base  # type: ignore
except Exception:
    daily_summary_base = None  # we will build without explicit schema if not found

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
# NOTE: DO NOT map "Apple Sleeping Wrist Temperature (degF)" — it’s a minute stream.

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
    Assumes column names are unique and renaming is already done.
    Defensive: if duplicate-labeled access slips through, select the first column.
    """

    def _series_or_first(col: str) -> pd.Series:
        s = df[col]
        if getattr(s, "ndim", 1) == 2:
            s = s.iloc[:, 0]  # defensive
        return s

    # Timestamps
    if "timestamp_utc" in df.columns:
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True)
    if "timestamp_local" in df.columns:
        tl = pd.to_datetime(df["timestamp_local"], errors="coerce", utc=False)
        try:
            df["timestamp_local"] = tl.dt.tz_localize(None)
        except Exception:
            df["timestamp_local"] = tl

    # Integer-like daily totals
    int_cols = {
        "steps",
        "flights_climbed",
        "sleep_minutes_asleep",
        "sleep_minutes_in_bed",
        "water_fl_oz",
    }
    for c in sorted(int_cols):
        if c in df.columns:
            s = _series_or_first(c)
            s = pd.to_numeric(s, errors="coerce").round()
            df[c] = s.astype("Int64")

    # Floats — sums/means/max are handled later in daily_summary
    float_cols = {
        "active_energy_kcal",
        "basal_energy_kcal",
        "calories_kcal",
        "protein_g",
        "carbs_g",
        "fat_g",
        "resting_hr_bpm",
        "hrv_ms",
        "respiratory_rate_bpm",
        "sleep_score",
        "distance_mi",
        "walking_running_distance_mi" 
        "weight_lb",
        "body_fat_pct",
        "temperature_degF",
    }
    for c in sorted(float_cols):
        if c in df.columns:
            s = _series_or_first(c)
            df[c] = pd.to_numeric(s, errors="coerce").astype("float64")

    return df


# ---------------------------------------------------------------------
# Hydration helpers
# ---------------------------------------------------------------------
def _to_int_fl_oz(val, unit: Optional[str]) -> Optional[int]:
    if pd.isna(val):
        return None
    try:
        v = float(val)
    except Exception:
        return None
    if unit == "ml":
        v = v / ML_PER_FL_OZ
    elif unit == "l":
        v = (v * 1000.0) / ML_PER_FL_OZ
    if v < 0 or v > (10000 / ML_PER_FL_OZ):  # ~0..338 fl oz guard
        return None
    return int(round(v))


def _find_water_fl_oz(df: pd.DataFrame) -> Optional[pd.Series]:
    cols = [c.lower() for c in df.columns]
    for i, c in enumerate(cols):
        if "water" in c:
            unit = (
                "ml" if "ml" in c else
                ("l" if ("l" in c and "fl" not in c and "oz" not in c) else "fl_oz")
            )
            s = df.iloc[:, i].apply(lambda x: _to_int_fl_oz(x, unit))
            s.name = "water_fl_oz"
            return s
    return None


# ---------------------------------------------------------------------
# Arrow writing
# ---------------------------------------------------------------------
def _to_table_with_partitions(df: pd.DataFrame) -> pa.Table:
    """
    Prepare minutes table with required partition column 'date' (UTC calendar date).
    """
    ts_utc = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True)
    date_utc = ts_utc.dt.tz_convert("UTC").dt.date
    df = df.assign(date=date_utc)
    return pa.Table.from_pandas(df, preserve_index=False)


def _write_parquet_dataset(table: pa.Table, root: Path) -> None:
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

    Strategy:
      1) Prefer extracting daily totals from the 00:00 row of each local day (timestamp_local).
      2) If local not available, try 00:00 UTC.
      3) If a date has no midnight row, fall back to safe agg (sum/mean/max) for that date.
    """
    if df.empty or "timestamp_utc" not in df.columns:
        return None

    ts_utc = pd.to_datetime(df["timestamp_utc"]).dt.tz_convert("UTC")
    date_utc = ts_utc.dt.date
    df = df.assign(date_utc=date_utc)

    # Identify midnight rows (prefer local if present and datetime-like)
    if "timestamp_local" in df.columns and pd.api.types.is_datetime64_any_dtype(df["timestamp_local"]):
        midnight_mask = df["timestamp_local"].dt.time == dtime(0, 0, 0)
    else:
        midnight_mask = ts_utc.dt.time == dtime(0, 0, 0)

    df_midnight = df.loc[midnight_mask].copy()

    daily_pick_cols = [
        "steps",
        "active_energy_kcal",
        "basal_energy_kcal",
        "calories_kcal",
        "flights_climbed",
        "sleep_minutes_asleep",
        "sleep_minutes_in_bed",
        "sleep_score",
        "distance_mi",
        "walking_running_distance_mi",  # add if you split distances
        "weight_lb",
        "body_fat_pct",
        "temperature_degF",
    ]

    parts: list[pd.DataFrame] = []

    # (A) From midnight rows: pick first non-null per date for each field
    if not df_midnight.empty:
        picks: dict[str, str | callable] = {"date_utc": "first"}
        for c in daily_pick_cols:
            if c in df_midnight.columns:
                picks[c] = lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan
        gmid = df_midnight.groupby("date_utc", as_index=False).agg(picks)
        parts.append(gmid)

    # (B) Fallback: safe agg for dates lacking a midnight row
    g = df.groupby("date_utc", as_index=False)
    agg_map: dict[str, str] = {}
    # sums
    for c in ["steps", "active_energy_kcal", "basal_energy_kcal",
              "calories_kcal", "flights_climbed",
              "sleep_minutes_asleep", "sleep_minutes_in_bed"]:
        if c in df.columns:
            agg_map[c] = "sum"
    # means
    for c in ["resting_hr_bpm", "hrv_ms", "respiratory_rate_bpm", "sleep_score",
              "weight_lb", "body_fat_pct", "temperature_degF"]:
        if c in df.columns:
            agg_map[c] = "mean"
    # max for cumulative-like
    for c in ["distance_mi"]:
        if c in df.columns:
            agg_map[c] = "max"

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

    # Hydration: daily max (or sum—pick based on your source semantics)
    w = _find_water_fl_oz(df)
    if w is not None:
        wdf = pd.DataFrame({"date_utc": df["date_utc"], "water_fl_oz": w})
        wagg = wdf.groupby("date_utc", as_index=False)["water_fl_oz"].max(min_count=1)
        out = out.merge(wagg, on="date_utc", how="left")

    # Derived (guarded)
    if {"active_energy_kcal", "basal_energy_kcal"}.issubset(out.columns):
        out["energy_total_kcal"] = (out["active_energy_kcal"].fillna(0) + out["basal_energy_kcal"].fillna(0)).round(0)
    if {"sleep_minutes_asleep", "sleep_minutes_in_bed"}.issubset(out.columns):
        denom = out["sleep_minutes_in_bed"].replace({0: np.nan})
        out["sleep_efficiency_pct"] = (out["sleep_minutes_asleep"] / denom * 100).round(1)
    if {"calories_kcal", "energy_total_kcal"}.issubset(out.columns):
        out["net_energy_kcal"] = (out["calories_kcal"] - out["energy_total_kcal"]).round(0)

    # Lineage + write rule
    now_utc = datetime.now(timezone.utc)
    out["source"] = source_value
    out["ingest_time_utc"] = now_utc
    out["ingest_run_id"] = ingest_run_id

    metric_cols = [c for c in out.columns if c not in {"date_utc", "source", "ingest_time_utc", "ingest_run_id"}]
    out = out.loc[out[metric_cols].notna().any(axis=1)].copy()
    if out.empty:
        return None

    # Ensure schema columns exist (if provided)
    if daily_summary_base is not None:
        for name in daily_summary_base.names:
            if name not in out.columns:
                out[name] = None
        out = out.loc[:, daily_summary_base.names]

    # Arrow table (+ hive partition column 'date')
    table = pa.Table.from_pandas(out, preserve_index=False, schema=(daily_summary_base or None))
    table = table.append_column("date", table.column("date_utc"))
    return table


# ---------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------
def _log_minute_summary(csv_path: Path, df: pd.DataFrame) -> None:
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
    table = _to_table_with_partitions(df)
    _write_parquet_dataset(table, MINUTE_FACTS_PATH)


def process_single_csv(csv_path: Path, source_value: str, ingest_run_id: str) -> None:
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
    return sorted(raw_dir.glob("*.csv"))


def main() -> None:
    raw_csv_dir = DATA_DIR / "Raw" / "CSV"
    raw_csv_dir.mkdir(parents=True, exist_ok=True)
    files = list(_iter_raw_csvs(raw_csv_dir))
    if not files:
        log.info("No CSV files found in %s", raw_csv_dir)
        return

    processed = 0
    failed = 0
    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for f in files:
        try:
            process_single_csv(f, DEFAULT_SOURCE, ingest_run_id)
            processed += 1
        except Exception:
            failed += 1
    log.info("Run complete. Processed=%d Failed=%d", processed, failed)


if __name__ == "__main__":
    main()
