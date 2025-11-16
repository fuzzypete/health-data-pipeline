"""
Concept2 Logbook API ingestion.

Fetches workout data from Concept2 API and ingests into:
- workouts (session summary)
- cardio_splits (interval-level data)
- cardio_strokes (stroke-by-stroke data)

TIMESTAMPING: Uses Strategy B (rich timezone) as Concept2 provides
per-workout timezone.

PARTITIONING: These tables use upsert_by_key(), which rewrites the entire
dataset. To avoid 'Too many open files' errors, these tables
are partitioned MONTHLY ('M'), not daily.
"""
from __future__ import annotations

import logging
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import pandas as pd
import requests

from pipeline.common import apply_strategy_b, get_schema
from pipeline.common.config import get_concept2_token, get_concept2_base_url, get_config
from pipeline.common.parquet_io import (
    add_lineage_fields,
    create_date_partition_column,
    upsert_by_key,
)
from pipeline.common.lactate_extraction import extract_lactate_from_workouts, create_lactate_table
from pipeline.paths import WORKOUTS_PATH, CARDIO_SPLITS_PATH, CARDIO_STROKES_PATH, LACTATE_PATH

log = logging.getLogger(__name__)

# Map Concept2 erg types to workout types
ERG_TYPE_MAP = {
    "rower": "Rowing",
    "bike": "Cycling",  # API returns "bike", not "bikeerg"
    "ski": "Skiing",    # API returns "ski", not "skierg"
}


def iter_date_chunks(from_date: str, to_date: str, max_days: int = 180):
    """
    Yield (chunk_from, chunk_to) pairs covering [from_date, to_date] inclusive.
    """
    start = pd.to_datetime(from_date).date()
    end = pd.to_datetime(to_date).date()
    delta = timedelta(days=max_days)

    cur_start = start
    while cur_start <= end:
        cur_end = min(cur_start + delta, end)
        yield cur_start.isoformat(), cur_end.isoformat()
        cur_start = cur_end + timedelta(days=1)


class Concept2Client:
    """
    Client for Concept2 Logbook API.

    API Documentation: https://log.concept2.com/developers
    """

    def __init__(self, api_token: Optional[str] = None, base_url: Optional[str] = None):
        self.api_token = api_token or get_concept2_token()
        self.base_url = (base_url or get_concept2_base_url()).rstrip("/")

        if not self.api_token:
            raise ValueError(
                "Concept2 API token not configured. "
                "Set CONCEPT2_API_TOKEN environment variable or add to config.yaml"
            )

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            }
        )

        config = get_config()
        self.max_retries = config.get_max_retries()
        self.retry_delay = config.get_retry_delay()

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        retry_count: int = 0,
    ) -> dict:
        url = f"{self.base_url}{endpoint}"

        try:
            resp = self.session.request(method, url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                if retry_count < self.max_retries:
                    wait_time = self.retry_delay * (2 ** retry_count)
                    log.warning(
                        f"Rate limited. Waiting {wait_time}s before retry {retry_count + 1}/{self.max_retries}"
                    )
                    time.sleep(wait_time)
                    return self._request(method, endpoint, params, retry_count + 1)
                log.error("Max retries exceeded for rate limiting")
                raise
            log.error(f"HTTP error {e.response.status_code}: {e}")
            raise

        except requests.exceptions.RequestException as e:
            if retry_count < self.max_retries:
                wait_time = self.retry_delay * (2 ** retry_count)
                log.warning(f"Request failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                return self._request(method, endpoint, params, retry_count + 1)
            log.error(f"Request failed after {self.max_retries} retries: {e}")
            raise

    def _fetch_page(
        self,
        page: int,
        number: int,
        from_date: Optional[str],
        to_date: Optional[str],
    ) -> dict:
        params = {
            "number": number,  # Concept2 uses "number", max 250
            "page": page,
        }
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        log.info(
            f"Fetching page {page} (number={number}, from={from_date}, to={to_date})"
        )
        return self._request("GET", "/users/me/results", params=params)

    def get_workouts_by_date(
        self,
        from_date: str,
        to_date: str,
        per_page: int = 250,
    ) -> list[dict]:
        """
        Fetch all workouts within a date range with automatic pagination.
        """
        all_workouts: list[dict] = []
        page = 1

        while True:
            resp = self._fetch_page(page, per_page, from_date, to_date)
            data = resp.get("data", [])
            all_workouts.extend(data)

            meta = resp.get("meta", {})
            pagination = meta.get("pagination", {})
            total = pagination.get("total", 0)
            current_page = pagination.get("current_page", page)
            total_pages = pagination.get("total_pages", 1)

            log.info(
                f"Page {current_page}/{total_pages}: fetched {len(data)} workouts (total so far: {len(all_workouts)}/{total})"
            )

            if current_page >= total_pages:
                break

            page += 1

        log.info(f"Fetched {len(all_workouts)} total workouts for window")
        return all_workouts

    def get_workout_strokes(self, workout_id: str) -> Optional[list[dict]]:
        """
        Fetch stroke-by-stroke data for a workout.
        
        Args:
            workout_id: Workout ID
            
        Returns:
            List of stroke dicts or None if not available
        """
        try:
            response = self._request('GET', f'/users/me/results/{workout_id}/strokes')
            return response.get('data', [])
        except Exception as e:
            log.warning(f"Could not fetch strokes for workout {workout_id}: {e}")
            return None


def process_workout_summary(workout_json: dict, ingest_run_id: str) -> dict:
    timestamp_str = workout_json["date"]
    tz_name = workout_json["timezone"]

    start_utc, start_local, tz = apply_strategy_b(timestamp_str, tz_name)

    end_utc = None
    end_local = None
    duration_in_seconds = None # Initialize
    if workout_json.get("time") is not None:
        duration_in_deciseconds = workout_json.get("time")
        duration_in_seconds = duration_in_deciseconds / 10.0
        
        # Calculate end times and round to microseconds to prevent ArrowInvalid
        # errors caused by nanosecond-level floating point noise.
        end_utc_raw = start_utc + pd.Timedelta(seconds=duration_in_seconds)
        end_local_raw = start_local + pd.Timedelta(seconds=duration_in_seconds)
        
        end_utc = end_utc_raw.round("us")
        end_local = end_local_raw.round("us")

    erg_type = workout_json.get("type", "rower").strip().lower()
    workout_type = ERG_TYPE_MAP.get(erg_type, "Rowing")

    hr_data = workout_json.get("heart_rate")
    if not isinstance(hr_data, dict):
        hr_data = {}

    workout_data = workout_json.get("workout")
    if not isinstance(workout_data, dict):
        workout_data = {}
    # ----------------------------------------------------

    return {
        "workout_id": str(workout_json["id"]),
        "source": "Concept2",
        "workout_type": workout_type,
        "start_time_utc": start_utc,
        "end_time_utc": end_utc,
        "start_time_local": start_local,
        "end_time_local": end_local,
        "timezone": tz,
        "tz_source": "actual",
        "duration_s": duration_in_seconds, # Use the calculated seconds
        "distance_m": float(workout_json["distance"])
        if "distance" in workout_json
        else None,
        "avg_hr_bpm": float(hr_data.get("average")) if hr_data.get("average") else None,
        "max_hr_bpm": float(hr_data.get("maximum")) if hr_data.get("maximum") else None,
        "min_hr_bpm": float(hr_data.get("minimum")) if hr_data.get("minimum") else None,
        "calories_kcal": float(workout_json.get("calories"))
        if workout_json.get("calories")
        else None,
        "c2_workout_type": workout_data.get("type"), # Use safe dict
        "erg_type": erg_type,
        "stroke_rate": float(workout_json.get("stroke_rate"))
        if workout_json.get("stroke_rate")
        else None,
        "stroke_count": int(workout_json.get("stroke_count"))
        if workout_json.get("stroke_count")
        else None,
        "drag_factor": int(workout_json.get("drag_factor"))
        if workout_json.get("drag_factor")
        else None,
        "ranked": workout_json.get("ranked", False),
        "verified": workout_json.get("verified", False),
        "notes" : workout_json.get("comments", ""),
        "has_splits": bool(workout_data.get("splits")), # Use safe dict
        "has_strokes": workout_json.get("stroke_data", False),
        "ingest_time_utc": datetime.now(timezone.utc),
        "ingest_run_id": ingest_run_id,
    }

def process_splits(
    workout_id: str,
    workout_start_utc: pd.Timestamp,
    splits_json: list[dict],
    ingest_run_id: str,
) -> pd.DataFrame:
    if not splits_json:
        return pd.DataFrame()

    rows = []
    for i, split in enumerate(splits_json, start=1):
        hr_data = split.get("heart_rate")
        if not isinstance(hr_data, dict):
            hr_data = {}
            
        rows.append(
            {
                "workout_id": workout_id,
                "workout_start_utc": workout_start_utc,
                "split_number": i,
                "split_time_s": int(split.get("time")) / 10.0 if split.get("time") else None,
                "split_distance_m": int(split.get("distance"))
                if split.get("distance")
                else None,
                "calories_total": int(split.get("calories"))
                if split.get("calories")
                else None,
                "stroke_rate": float(split.get("stroke_rate"))
                if split.get("stroke_rate")
                else None,
                "avg_hr_bpm": float(hr_data.get("average"))
                if hr_data.get("average")
                else None,
                "min_hr_bpm": float(hr_data.get("minimum"))
                if hr_data.get("minimum")
                else None,
                "max_hr_bpm": float(hr_data.get("maximum"))
                if hr_data.get("maximum")
                else None,
                "ending_hr_bpm": float(hr_data.get("ending"))
                if hr_data.get("ending")
                else None,
            }
        )

    df = pd.DataFrame(rows)
    df = add_lineage_fields(df, source="Concept2", ingest_run_id=ingest_run_id)
    return df


def process_strokes(
    workout_id: str,
    workout_start_utc: pd.Timestamp,
    strokes_json: list[dict],
    ingest_run_id: str,
    erg_type: str = "rower"
) -> pd.DataFrame:
    """
    Process the stroke-level data for a workout.
    
    The 'p' field is polymorphic:
    - Rower/Ski: 'p' = pace in deciseconds / 500m (same as 't' field)
    - Bike:      'p' = power in deci-watts (watts * 10)
    
    Empty lists in the stroke data mark split boundaries for structured workouts.
    """
    if not strokes_json:
        return pd.DataFrame()

    rows = []
    processed_erg_type = erg_type.strip().lower()
    
    current_split = 1
    stroke_counter = 0

    for stroke in strokes_json:
        # Empty lists mark split boundaries in FixedTimeSplits workouts
        if not isinstance(stroke, dict):
            if isinstance(stroke, list) and len(stroke) == 0:
                current_split += 1
            continue
        
        stroke_counter += 1
        
        p_field = stroke.get("p")
        watts_val = 0.0
        pace_val_cs = None

        # Empirically, for both rower/ski and bike in your data, "p" behaves like
        # pace in deciseconds per 500m, and Concept2's "Watts" column is derived
        # using the standard 2.8 / (pace/500)^3 relationship.

        if p_field is not None:
            try:
                pace_val_cs = int(p_field)  # centiseconds per 500m (deciseconds * 10)
            except (TypeError, ValueError):
                pace_val_cs = None

        if pace_val_cs is not None and pace_val_cs > 0:
            pace_seconds = pace_val_cs / 10.0         # deciseconds → seconds per 500m
            pace_sec_per_meter = pace_seconds / 500.0
            watts_val = 2.80 / (pace_sec_per_meter ** 3)
        else:
            watts_val = 0.0

        hr = stroke.get("hr")
        spm = stroke.get("spm")

        rows.append(
            {
                "workout_id": workout_id,
                "workout_start_utc": workout_start_utc,
                "split_number": current_split,
                "stroke_number": stroke_counter,
                "time_cumulative_s": stroke["t"] / 10.0,
                "distance_cumulative_m": int(stroke["d"]),
                "pace_500m_cs": pace_val_cs,
                "watts": watts_val,
                "heart_rate_bpm": int(hr) if hr is not None else None,
                "stroke_rate_spm": int(spm) if spm is not None else None,
            }
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = add_lineage_fields(df, source="Concept2", ingest_run_id=ingest_run_id) 
    return df

def ingest_workout(
    client: Concept2Client,
    workout_json: dict,
    ingest_run_id: str,
    fetch_strokes: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    workout_record = process_workout_summary(workout_json, ingest_run_id)
    workouts_df = pd.DataFrame([workout_record])

    workout_id = workout_record["workout_id"]
    workout_start_utc = workout_record["start_time_utc"]

    splits_df = pd.DataFrame()
    if workout_record["has_splits"]:
        workout_data = workout_json.get("workout")
        if isinstance(workout_data, dict):
            splits_json = workout_data.get("splits", [])
        else:
            splits_json = []
        
        if splits_json:
            splits_df = process_splits(
                workout_id, workout_start_utc, splits_json, ingest_run_id
            )

    strokes_df = pd.DataFrame()
    if fetch_strokes and workout_record["has_strokes"]:
        strokes_json = client.get_workout_strokes(workout_id)
        if strokes_json:
            erg_type = workout_record.get("erg_type", "rower")
            strokes_df = process_strokes(
                workout_id,
                workout_start_utc,
                strokes_json,
                ingest_run_id,
                erg_type
            )

    return workouts_df, splits_df, strokes_df

def ingest_workouts_by_date(
    from_date: str,
    to_date: str,
    fetch_strokes: bool = True,
) -> dict[str, int]:
    client = Concept2Client()
    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    log.info(f"Starting Concept2 ingestion (run_id={ingest_run_id}) for {from_date} to {to_date}")

    # ---- Fetch workouts (maybe multi-window) ----
    workouts_json: list[dict] = []
    seen_ids: set[str] = set()
    
    # Iterate over 180-day chunks for robust long-range pulls
    for chunk_from, chunk_to in iter_date_chunks(from_date, to_date, max_days=180):
        log.info(f"Fetching chunk {chunk_from} → {chunk_to}")
        chunk_workouts = client.get_workouts_by_date(
            from_date=chunk_from,
            to_date=chunk_to,
            per_page=250,
        )
        for w in chunk_workouts:
            wid = str(w["id"])
            if wid not in seen_ids:
                seen_ids.add(wid)
                workouts_json.append(w)

    if not workouts_json:
        log.info("No workouts to ingest")
        return {"workouts": 0, "splits": 0, "strokes": 0}


    all_workouts: list[pd.DataFrame] = []
    all_splits: list[pd.DataFrame] = []
    all_strokes: list[pd.DataFrame] = []

    # Progress logging setup ---
    total_workouts_to_process = len(workouts_json)
    workouts_processed_count = 0
    strokes_processed_count = 0
    last_log_time = time.time()
    log.info(f"Fetching stroke data for {total_workouts_to_process} workouts...")

# (Inside ingest_workouts_by_date)
    
    for workout_json in workouts_json:
        try:
            wdf, sdf, tdf = ingest_workout(
                client, workout_json, ingest_run_id, fetch_strokes
            )
            all_workouts.append(wdf)
            if not sdf.empty:
                all_splits.append(sdf)
            if not tdf.empty:
                all_strokes.append(tdf)
                
            workouts_processed_count += 1
            strokes_processed_count += len(tdf)

        except Exception as e:
            workout_id = "UNKNOWN (data is not a dict)"
            if isinstance(workout_json, dict):
                workout_id = workout_json.get('id', 'UNKNOWN (id key missing)')

            log.error(f"--- FAILED TO PROCESS WORKOUT (ID: {workout_id}) ---")
            log.error(f"ORIGINAL ERROR: {e}")
            try:
                log.error(f"DUMPING PROBLEMATIC DATA: {json.dumps(workout_json, indent=2)}")
            except Exception as json_e:
                log.error(f"Could not dump data (it might not be JSON serializable): {json_e}")
            
            continue
        
        # Check if it's time to log progress ---
        # (Your existing progress logging code follows)
        current_time = time.time()        
        # Check if it's time to log progress ---
        current_time = time.time()
        if (current_time - last_log_time) >= 30.0:
            log.info(
                f"Progress: Processed {workouts_processed_count}/{total_workouts_to_process} workouts "
                f"({strokes_processed_count:,} total strokes)"
            )
            last_log_time = current_time

    log.info(
        f"Stroke processing complete. Processed {workouts_processed_count}/{total_workouts_to_process} workouts "
        f"({strokes_processed_count:,} total strokes)."
    )

    counts = {"workouts": 0, "splits": 0, "strokes": 0, 'lactate': 0}

    if all_workouts:
        workouts_combined = pd.concat(all_workouts, ignore_index=True)

        if workouts_combined.empty:
            log.info("No workouts found in date range after filtering.")
            all_workouts = [] # Ensure list is empty for next check
        else:        
            # local date filtering (belt-and-suspenders)
            workouts_combined["date_only"] = (
                workouts_combined["start_time_local"].dt.date
            )
            f = pd.to_datetime(from_date).date()
            t = pd.to_datetime(to_date).date()
            workouts_combined = workouts_combined[
                (workouts_combined["date_only"] >= f) &
                (workouts_combined["date_only"] <= t)
            ]
            workouts_combined = workouts_combined.drop(columns=["date_only"])

            workouts_combined = create_date_partition_column(
                workouts_combined, "start_time_utc", "date", "M"
            )

            upsert_by_key(
                workouts_combined,
                WORKOUTS_PATH,
                primary_key=["workout_id", "source"],
                partition_cols=["date", "source"],
                schema=get_schema("workouts"),
            )
            counts["workouts"] = len(workouts_combined)
            log.info(f"Wrote {counts['workouts']} workouts")

            # ---- Extract lactate from comments ----  # 
            log.info("Extracting lactate measurements from comments...")
            lactate_df = extract_lactate_from_workouts(
                workouts_combined,
                ingest_run_id,
                source="Concept2_Comment"
            )
            
            if not lactate_df.empty:
                lactate_df = create_date_partition_column(
                    lactate_df, "workout_start_utc", "date", "M"
                )
                lactate_table = create_lactate_table(lactate_df)
                
                upsert_by_key(
                    lactate_df,
                    LACTATE_PATH,
                    primary_key=["workout_id", "source"],
                    partition_cols=["date", "source"],
                    schema=get_schema("lactate"),
                )
                counts["lactate"] = len(lactate_df)
                log.info(f"Extracted {counts['lactate']} lactate measurements")
            else:
                counts["lactate"] = 0
                log.info("No lactate measurements found in comments")

    if all_splits:
        splits_combined = pd.concat(all_splits, ignore_index=True)
        if splits_combined.empty:
            log.info("No splits found to write.")
            all_splits = [] # Ensure list is empty for next check
        else:
            splits_combined = create_date_partition_column(
                splits_combined, "workout_start_utc", "date", "M"
            )
            upsert_by_key(
                splits_combined,
                CARDIO_SPLITS_PATH,
                primary_key=["workout_id", "split_number", "source"],
                partition_cols=["date", "source"],
                schema=get_schema("cardio_splits"),
            )
            counts["splits"] = len(splits_combined)
            log.info(f"Wrote {counts['splits']} splits")

    if all_strokes:
        strokes_combined = pd.concat(all_strokes, ignore_index=True)
        if strokes_combined.empty:
            log.info("No strokes found to write.")
        else:
            strokes_combined = create_date_partition_column(
                strokes_combined, "workout_start_utc", "date", "M"
            )
            upsert_by_key(
                strokes_combined,
                CARDIO_STROKES_PATH,
                primary_key=["workout_id", "stroke_number", "source"],
                partition_cols=["date", "source"], # <-- REMOVED LEAKED THOUGHT
                schema=get_schema("cardio_strokes"),
            )
            counts["strokes"] = len(strokes_combined)
            log.info(f"Wrote {counts['strokes']} strokes")

    log.info(f"Concept2 ingestion complete: {counts}")
    return counts


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Ingest workouts from Concept2 API")
    parser.add_argument("--from-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--no-strokes", action="store_true", help="Skip stroke data (faster)"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

    try:
        counts = ingest_workouts_by_date(
            from_date=args.from_date,
            to_date=args.to_date,
            fetch_strokes=not args.no_strokes,
        )
        print("\n✅ Ingestion complete:")
        print(f"   Workouts: {counts['workouts']}")
        print(f"   Splits:   {counts['splits']}")
        print(f"   Strokes:  {counts['strokes']}")
        print(f"   Lactate:  {counts['lactate']}")  
    except Exception as e:
        log.exception("Ingestion failed")
        print(f"\n❌ Ingestion failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())