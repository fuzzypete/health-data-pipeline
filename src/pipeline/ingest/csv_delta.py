# src/pipeline/ingest/csv_delta.py
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, List
from uuid import uuid4
from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import numpy as np

from pipeline.common.schema import SOURCES, minute_facts_base, daily_summary_base
from pipeline.paths import RAW_CSV_DIR, MINUTE_FACTS_PATH, DAILY_SUMMARY_PATH

DEFAULT_INPUT_DIR = RAW_CSV_DIR
DEFAULT_OUTPUT_DIR = MINUTE_FACTS_PATH
DEFAULT_SOURCE = "HAE_CSV"

# Minimal crosswalk for **daily totals only** (NOT minute metrics)
RENAME_MAP = {
    # time (if daily date stamp exists)
    "Date/Time": "timestamp_local",

    # energy (kcal)
    "Active Energy (kcal)": "active_energy_kcal",
    "Resting Energy (kcal)": "basal_energy_kcal",
    "Dietary Energy (kcal)": "calories_kcal",

    # activity totals
    "Steps (count)": "steps",
    "Walking + Running Distance (mi)": "distance_mi",
    "Distance (mi)": "distance_mi",
    "Flights Climbed (count)": "flights_climbed",
    "Walking + Running Distance (mi)": "walking_running_distance_mi",
    "Distance (mi)": "distance_mi",

    # sleep totals
    "Sleep Minutes Asleep (min)": "sleep_minutes_asleep",
    "Sleep Minutes In Bed (min)": "sleep_minutes_in_bed",
    "Sleep Score": "sleep_score",

    # body (imperial)
    "Body Mass (lb)": "weight_lb",
    "Body Fat Percentage (%)": "body_fat_pct",
    "Body Temperature (degF)": "temperature_degF",
    "Apple Sleeping Wrist Temperature (degF)": "temperature_degF",  # treated as daily temp if present
}

METADATA_COLS = {
    "timestamp_utc",
    "timestamp_local",
    "tz_name",
    "source",
    "ingest_time_utc",
    "ingest_run_id",
}

import re

# Regex-based canonical header crosswalk (used only if RENAME_MAP is absent/empty)
HEADER_CROSSWALK_REGEX: list[tuple[str, str]] = [
    (r"^date/?time$", "timestamp_local"),

    # steps / distance / floors
    (r"^steps\b.*\(count\)$", "steps"),
    (r"^walking\s*\+\s*running\s*distance.*\(mi\)$", "distance_mi"),
    (r"^distance.*\(mi\)$", "distance_mi"),
    (r"^flights\s*climbed.*\(count\)$", "flights_climbed"),

    # energy (kcal)
    (r"^active\s*energy.*\(kcal\)$", "active_energy_kcal"),
    (r"^resting\s*energy.*\(kcal\)$", "basal_energy_kcal"),
    (r"^dietary\s*energy.*\(kcal\)$", "calories_kcal"),

    # cardio / recovery
    (r"^resting\s*heart\s*rate.*\(count/min\)$", "resting_hr_bpm"),
    (r"^heart\s*rate\s*variability.*\(ms\)$", "hrv_ms"),
    (r"^respiratory\s*rate.*\(count/min\)$", "respiratory_rate_bpm"),

    # sleep
    (r"^sleep.*minutes.*asleep$", "sleep_minutes_asleep"),
    (r"^sleep.*minutes.*in\s*bed$", "sleep_minutes_in_bed"),
    (r"^sleep\s*score", "sleep_score"),

    # body (imperial)
    (r"^body\s*mass.*\(lb\)$", "weight_lb"),
    (r"^body\s*fat.*\(%\)$", "body_fat_pct"),
    (r"^(body|skin)?\s*temperature.*(f|°f)\)?$", "temperature_degF"),

    # nutrition
    (r"^protein.*\(g\)$", "protein_g"),
    (r"^carb.*\(g\)$", "carbs_g"),
    (r"^fat.*\(g\)$", "fat_g"),
]

def _canonicalize_headers(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """If RENAME_MAP is absent/empty, use regex crosswalk. Returns (renamed_df, audit)."""
    colmap = {}
    for c in df.columns:
        lc = c.strip().lower()
        for pat, target in HEADER_CROSSWALK_REGEX:
            if re.search(pat, lc):
                colmap[c] = target
                break
    df2 = df.rename(columns=colmap)
    audit = {"mapped": colmap, "unmapped": [c for c in df.columns if c not in colmap]}
    return df2, audit

logging.basicConfig(
    level=os.environ.get("PIPELINE_LOGLEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("csv_delta")

def _load_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()

    # If a dict RENAME_MAP exists and has entries, use it.
    use_map = False
    if "RENAME_MAP" in globals() and isinstance(globals()["RENAME_MAP"], dict) and globals()["RENAME_MAP"]:
        use_map = True

    if use_map:
        df = df.rename(columns=globals()["RENAME_MAP"])
        # Light audit so we can see what was missed
        unmapped = [c for c in df.columns if c not in globals()["RENAME_MAP"].values()]
        if unmapped:
            log.info("header-xwalk(map): unmapped=%d %s", len(unmapped), unmapped[:6])
    else:
        # Fallback: regex crosswalk
        df, audit = _canonicalize_headers(df)
        log.info(
            "header-xwalk(regex): mapped=%d, unmapped=%d; examples=%s; left=%s",
            len(audit["mapped"]), len(audit["unmapped"]),
            list(audit["mapped"].items())[:4], audit["unmapped"][:4],
        )
    dups = df.columns[df.columns.duplicated()].tolist()
    if dups:
        log.warning("duplicate column labels after rename: %s", sorted(set(dups)))
    return df

def _add_required_fields(df: pd.DataFrame, source_value: str, csv_path: Path, ingest_run_id: str) -> pd.DataFrame:
    if "timestamp_utc" not in df.columns:
        if "timestamp_local" in df.columns:
            df["timestamp_utc"] = pd.to_datetime(df["timestamp_local"], errors="coerce", utc=True)
        elif "timestamp" in df.columns:
            df["timestamp_utc"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        else:
            raise ValueError(f"{csv_path}: expected 'timestamp_utc' or 'timestamp_local'")
    else:
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True)

    if "timestamp_local" in df.columns:
        df["timestamp_local"] = pd.to_datetime(df["timestamp_local"], errors="coerce", utc=False)

    if "tz_name" not in df.columns:
        df["tz_name"] = pd.NA

    df["source"] = source_value
    df["ingest_run_id"] = f"csv-{ingest_run_id}"
    df["ingest_time_utc"] = datetime.now(timezone.utc)

    return df

def _coerce_metric_types(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce canonical columns to appropriate dtypes.
    Assumes column names are unique (no duplicates) and renaming is already done.

    Notes:
    - This function ONLY coerces types on the per-row frame.
      Any daily reductions (sum/mean/max) are applied in _build_daily_summary().
    - "mx" cumulative-style fields (e.g., distances) are just coerced to float here;
      they are aggregated with MAX in _build_daily_summary.
    """

    # --- Timestamps ---
    if "timestamp_utc" in df.columns:
        # ensure tz-aware UTC
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True)
    if "timestamp_local" in df.columns:
        # keep naive local timestamps (per your design); strip tz if any
        df["timestamp_local"] = pd.to_datetime(df["timestamp_local"], errors="coerce", utc=False)
        try:
            df["timestamp_local"] = df["timestamp_local"].dt.tz_localize(None)
        except Exception:
            # already naive or not datetime-like
            pass

    # --- Canonical numeric sets ---
    int_cols = {
        "steps",
        "flights_climbed",
        "sleep_minutes_asleep",
        "sleep_minutes_in_bed",
        "water_fl_oz",
    }

    float_sum_cols = {
        "active_energy_kcal",
        "basal_energy_kcal",
        "calories_kcal",
        "protein_g",
        "carbs_g",
        "fat_g",
        # daily_summary will later compute energy_total_kcal/net_energy_kcal
    }

    float_mean_cols = {
        "resting_hr_bpm",
        "hrv_ms",
        "respiratory_rate_bpm",
        "sleep_score",
    }

    # "mx" cumulative-style daily signals (coerced to float here, MAX used later)
    float_max_cols = {
        "distance_mi",
        "walking_running_distance_mi",  # include if you kept this distinct
    }

    float_cols = float_sum_cols | float_mean_cols | float_max_cols

    # --- Coerce ints ---
    for c in sorted(int_cols):
        if c in df.columns:
            s = pd.to_numeric(df[c], errors="coerce")
            # round to nearest integer where appropriate (e.g., minutes, counts)
            df[c] = s.round().astype("Int64")

    # --- Coerce floats ---
    for c in sorted(float_cols):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")

    # --- Optional: common aliases you might keep around as floats ---
    for c in ["weight_lb", "body_fat_pct", "temperature_degF"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")

    return df

#def _coerce_metric_types(df: pd.DataFrame) -> pd.DataFrame:
#    # Coerce likely metric columns; leave non-numeric columns untouched
#    metric_cols = [c for c in df.columns if c not in METADATA_COLS]
#    for c in metric_cols:
#        converted = pd.to_numeric(df[c], errors="coerce")
#        # Only adopt conversion if it yielded any numeric values
#        if not converted.isna().all():
#            df[c] = converted
#    return df

def _drop_pk_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    df = df.drop_duplicates(subset=["timestamp_utc", "source"], keep="last")
    after = len(df)
    if after < before:
        log.info("Deduped %d → %d rows on PK (timestamp_utc,source)", before, after)
    return df

def _to_table_with_partitions(df: pd.DataFrame) -> pa.Table:
    for name in ["timestamp_utc", "source", "ingest_time_utc"]:
        if name not in df.columns:
            raise ValueError(f"Missing required column '{name}' before Arrow conversion")
    table = pa.Table.from_pandas(df, preserve_index=False)
    date32 = pa.array(pd.to_datetime(df["timestamp_utc"]).dt.date.astype("datetime64[ns]")).cast(pa.date32())
    table = table.append_column("date", date32)
    return table

# ---------- daily_summary helpers ----------
ML_PER_FL_OZ = 29.5735  # imperial canonical

def _to_int_fl_oz(val, unit: str | None) -> int | None:
    import pandas as pd
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
    # else: treat as fl oz (or already fl_oz)
    if v < 0 or v > (10000 / ML_PER_FL_OZ):  # ~0..338 fl oz
        return None
    return int(round(v))

def _find_water_fl_oz(df: pd.DataFrame) -> pd.Series | None:
    cols = df.columns.str.lower()
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

def _build_daily_summary(df: pd.DataFrame, source_value: str, ingest_run_id: str) -> Optional[pa.Table]:
    """
    Build wide daily_summary per (date_utc, source) with 'midnight-row' preference.

    Strategy:
      1) Prefer extracting daily totals from the 00:00 row of each local day (timestamp_local).
      2) If timestamp_local not available, try 00:00 UTC on timestamp_utc.
      3) If a date has no midnight row, fall back to safe agg (sum/mean/max) for that date.
    """
    if df.empty or "timestamp_utc" not in df.columns:
        return None

    # Derive date_utc (partition key)
    ts_utc = pd.to_datetime(df["timestamp_utc"]).dt.tz_convert("UTC")
    date_utc = ts_utc.dt.date
    df = df.assign(date_utc=date_utc)

    # Identify midnight rows (prefer local)
    have_local = "timestamp_local" in df.columns and pd.api.types.is_datetime64_any_dtype(df["timestamp_local"])
    if have_local:
        midnight_mask = df["timestamp_local"].dt.time == datetime.time(0, 0, 0)
    else:
        midnight_mask = ts_utc.dt.time == datetime.time(0, 0, 0)

    df_midnight = df.loc[midnight_mask].copy()

    # Canonical daily fields we expect to read from midnight rows
    daily_pick_cols = [
        "steps", "active_energy_kcal", "basal_energy_kcal", "calories_kcal",
        "flights_climbed",
        "sleep_minutes_asleep", "sleep_minutes_in_bed", "sleep_score",
        "distance_mi", "walking_running_distance_mi",  # include second if you keep it distinct
        "weight_lb", "body_fat_pct", "temperature_degF",
        # hydration handled below; not via rename
    ]

    parts = []

    # (A) From midnight rows: pick first non-null value per date for each daily field
    if not df_midnight.empty:
        picks = {"date_utc": "first"}
        for c in daily_pick_cols:
            if c in df_midnight.columns:
                picks[c] = lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan

        # groupby-agg on midnight subset
        gmid = df_midnight.groupby("date_utc", as_index=False).agg(picks)
        parts.append(gmid)

    # (B) Fallback for dates with no midnight row: safe agg from the whole day
    #     (sum for totals, mean for rates/scores, max for cumulative distances)
    if True:
        g = df.groupby("date_utc", as_index=False)
        agg_map = {}
        # sums
        for c in ["steps","active_energy_kcal","basal_energy_kcal","calories_kcal",
                  "flights_climbed","sleep_minutes_asleep","sleep_minutes_in_bed"]:
            if c in df.columns:
                agg_map[c] = "sum"
        # means
        for c in ["resting_hr_bpm","hrv_ms","respiratory_rate_bpm","sleep_score","weight_lb","body_fat_pct","temperature_degF"]:
            if c in df.columns:
                agg_map[c] = "mean"
        # max for cumulative-like
        for c in ["distance_mi","walking_running_distance_mi"]:
            if c in df.columns:
                agg_map[c] = "max"

        if agg_map:
            fallback = g.agg(agg_map)
            parts.append(fallback)

    # Merge midnight-first with fallback (midnight wins)
    if not parts:
        return None
    out = parts[0]
    for p in parts[1:]:
        out = out.merge(p, on="date_utc", how="outer", suffixes=("", "_fb"))
    # prefer midnight values; where missing, use fallback
    for c in daily_pick_cols:
        if c in out.columns and f"{c}_fb" in out.columns:
            out[c] = out[c].where(out[c].notna(), out[f"{c}_fb"])
            out = out.drop(columns=[f"{c}_fb"])

    # Hydration (imperial INT) — sum daily if present at any time; midnight rows often carry daily total too
    w = _find_water_fl_oz(df)
    if w is not None:
        wdf = pd.DataFrame({"date_utc": df["date_utc"], "water_fl_oz": w})
        wagg = wdf.groupby("date_utc", as_index=False)["water_fl_oz"].max(min_count=1)  # max or sum; pick what your source semantics imply
        out = out.merge(wagg, on="date_utc", how="left")

    # Derived fields (guarded)
    if {"active_energy_kcal","basal_energy_kcal"}.issubset(out.columns):
        out["energy_total_kcal"] = (out["active_energy_kcal"].fillna(0) + out["basal_energy_kcal"].fillna(0)).round(0)
    if {"sleep_minutes_asleep","sleep_minutes_in_bed"}.issubset(out.columns):
        denom = out["sleep_minutes_in_bed"].replace({0: np.nan})
        out["sleep_efficiency_pct"] = (out["sleep_minutes_asleep"] / denom * 100).round(1)
    if {"calories_kcal","energy_total_kcal"}.issubset(out.columns):
        out["net_energy_kcal"] = (out["calories_kcal"] - out["energy_total_kcal"]).round(0)

    # Lineage and write rule
    now_utc = datetime.now(timezone.utc)
    out["source"] = source_value
    out["ingest_time_utc"] = now_utc
    out["ingest_run_id"] = ingest_run_id

    # Wide-table rule: keep dates where at least one metric exists
    metric_cols = [c for c in out.columns if c not in {"date_utc","source","ingest_time_utc","ingest_run_id"}]
    out = out.loc[out[metric_cols].notna().any(axis=1)].copy()
    if out.empty:
        return None

    # Ensure all schema fields exist
    for name in daily_summary_base.names:
        if name not in out.columns:
            out[name] = None
    out = out.loc[:, daily_summary_base.names]

    table = pa.Table.from_pandas(out, preserve_index=False, schema=daily_summary_base)
    table = table.append_column("date", table.column("date_utc"))
    return table

# ---------- logging helpers ----------
def _log_minute_summary(csv_path: Path, df: pd.DataFrame) -> None:
    try:
        rows = len(df)
        if rows == 0:
            log.info("minutes: %s → rows=0 (nothing to do)", csv_path.name)
            return
        ts = pd.to_datetime(df["timestamp_utc"], errors="coerce")
        tmin, tmax = ts.min(), ts.max()
        meta = {"timestamp_utc","timestamp_local","tz_name","source","ingest_time_utc","ingest_run_id","date"}
        metric_cols = [c for c in df.columns if c not in meta]
        nonnull_counts = []
        for c in metric_cols:
            try:
                nonnull_counts.append((c, int(df[c].notna().sum())))
            except Exception:
                continue
        nonnull_counts.sort(key=lambda x: (-x[1], x[0]))
        top = ", ".join(f"{k}:{v}" for k,v in nonnull_counts[:6])
        log.info("minutes: %s → rows=%d, window=%s..%s, non_null_top=[%s]",
                 csv_path.name, rows, tmin, tmax, top)
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
        for k in ["steps","active_energy_kcal","energy_total_kcal","calories_kcal",
                  "sleep_minutes_asleep","sleep_efficiency_pct","water_fl_oz"]:
            if k in pdf.columns and pd.notna(sample.get(k)):
                val = sample[k]
                if isinstance(val, float):
                    val = int(val) if abs(val - int(val)) < 1e-6 else round(val, 1)
                fields.append(f"{k}={val}")
        metrics_str = ", ".join(fields) if fields else "no-metrics"
        log.info("daily_summary: rows=%d, dates=%s..%s, sample={%s}", n, dmin, dmax, metrics_str)
    except Exception as e:
        log.warning("daily_summary: summary failed: %s", e)

def _write_parquet_dataset(table: pa.Table, out_dir: Path) -> None:
    partition_schema = pa.schema([pa.field("date", pa.date32()), pa.field("source", pa.string())])
    ds.write_dataset(
        data=table,
        base_dir=str(out_dir),
        format="parquet",
        partitioning=ds.partitioning(partition_schema, flavor="hive"),
        existing_data_behavior="overwrite_or_ignore",
    )

def process_single_csv(csv_path: Path, out_dir: Path, source_value: str) -> bool:
    try:
        if source_value not in SOURCES:
            raise ValueError(f"Unknown source '{source_value}'. Allowed: {sorted(SOURCES)}")

        ingest_run_id = str(uuid4())
        df = _load_csv(csv_path)
        df = _add_required_fields(df, source_value=source_value, csv_path=csv_path, ingest_run_id=ingest_run_id)
        df = _coerce_metric_types(df)
        df = _drop_pk_duplicates(df)

        _log_minute_summary(csv_path, df)
        table = _to_table_with_partitions(df)
        _write_parquet_dataset(table, out_dir)
        
        daily_tbl = _build_daily_summary(df, source_value=source_value, ingest_run_id=ingest_run_id)
        if daily_tbl is not None:
            _write_parquet_dataset(daily_tbl, DAILY_SUMMARY_PATH)
            _log_daily_summary_written(daily_tbl)
            log.info("OK: %s → %s (daily_summary written)", csv_path.name, DAILY_SUMMARY_PATH)
        else:
            log.info("OK: %s → %s (daily_summary skipped: no metrics)", csv_path.name, DAILY_SUMMARY_PATH)

        log.info("OK: %s → %s", csv_path.name, out_dir)
        return True
    except Exception as e:
        log.exception("Failed on %s: %s", csv_path, e)
        return False

def discover_csvs(input_dir: Path) -> list[Path]:
    return sorted([p for p in input_dir.glob("*.csv") if p.is_file()])

def run(input_dir: Path, out_dir: Path, source_value: str = DEFAULT_SOURCE) -> int:
    csvs = discover_csvs(input_dir)
    processed = 0
    failed = 0

    if not csvs:
        log.info("No CSV files found in %s", input_dir)
        return 0

    for p in csvs:
        ok = process_single_csv(p, out_dir, source_value)
        processed += int(ok)
        failed += int(not ok)

    log.info("Run complete. Processed=%d Failed=%d", processed, failed)
    return 0 if failed == 0 else 1

def _parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Ingest HAE CSV (wide→wide) to Parquet (Schema v1.2)")
    ap.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR), help=f"CSV directory (default: {DEFAULT_INPUT_DIR})")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR), help=f"Parquet dataset dir (default: {DEFAULT_OUTPUT_DIR})")

    ap.add_argument("--source", default=DEFAULT_SOURCE, choices=sorted(SOURCES), help="Source tag (default: HAE_CSV)")
    return ap.parse_args(argv)

def main(argv: Optional[Iterable[str]] = None) -> None:
    args = _parse_args(argv)
    raise SystemExit(run(Path(args.input_dir), Path(args.out_dir), args.source))

if __name__ == "__main__":
    main()
