"""
Concept2 Logbook API ingestion.

Fetches workout data from Concept2 API and ingests into:
- workouts (session summary)
- cardio_splits (interval-level data)
- cardio_strokes (stroke-by-stroke data)

Uses Strategy B (rich timezone) as Concept2 provides per-workout timezone.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
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
from pipeline.paths import WORKOUTS_PATH, CARDIO_SPLITS_PATH, CARDIO_STROKES_PATH

log = logging.getLogger(__name__)

# Map Concept2 erg types to workout types
ERG_TYPE_MAP = {
    'rower': 'Rowing',
    'bikeerg': 'Cycling',
    'skierg': 'Skiing',
}


class Concept2Client:
    """
    Client for Concept2 Logbook API.
    
    API Documentation: https://log.concept2.com/developers
    """
    
    def __init__(self, api_token: Optional[str] = None, base_url: Optional[str] = None):
        """
        Initialize Concept2 API client.
        
        Args:
            api_token: API token (defaults to config)
            base_url: API base URL (defaults to config)
        """
        self.api_token = api_token or get_concept2_token()
        self.base_url = (base_url or get_concept2_base_url()).rstrip('/')
        
        if not self.api_token:
            raise ValueError(
                "Concept2 API token not configured. "
                "Set CONCEPT2_API_TOKEN environment variable or add to config.yaml"
            )
        
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json',
        })
        
        # Rate limiting
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
        """
        Make API request with retry logic.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., '/users/me/results')
            params: Query parameters
            retry_count: Current retry attempt
            
        Returns:
            Response JSON as dict
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = self.session.request(method, url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:  # Rate limited
                if retry_count < self.max_retries:
                    wait_time = self.retry_delay * (2 ** retry_count)
                    log.warning(f"Rate limited. Waiting {wait_time}s before retry {retry_count + 1}/{self.max_retries}")
                    time.sleep(wait_time)
                    return self._request(method, endpoint, params, retry_count + 1)
                else:
                    log.error("Max retries exceeded for rate limiting")
                    raise
            else:
                log.error(f"HTTP error {e.response.status_code}: {e}")
                raise
        
        except requests.exceptions.RequestException as e:
            if retry_count < self.max_retries:
                wait_time = self.retry_delay * (2 ** retry_count)
                log.warning(f"Request failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                return self._request(method, endpoint, params, retry_count + 1)
            else:
                log.error(f"Request failed after {self.max_retries} retries: {e}")
                raise
    

    def get_recent_workouts(
        self,
        limit: int = None,  # Changed: None means fetch all
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list[dict]:
        """
        Fetch recent workouts with automatic pagination.
        
        Args:
            limit: Max number of workouts to fetch (None = fetch all available)
            from_date: Start date (ISO format: YYYY-MM-DD)
            to_date: End date (ISO format: YYYY-MM-DD)
            
        Returns:
            List of workout dicts
        """
        all_workouts = []
        page = 1
        
        while True:
            params = {'limit': 50, 'page': page}
            if from_date:
                params['from'] = from_date
            if to_date:
                params['to'] = to_date
            
            log.info(f"Fetching page {page} (limit=50, from={from_date}, to={to_date})")
            response = self._request('GET', '/users/me/results', params=params)
            
            workouts = response.get('data', [])
            all_workouts.extend(workouts)
            
            # Check pagination metadata
            meta = response.get('meta', {})
            pagination = meta.get('pagination', {})
            total = pagination.get('total', 0)
            current_page = pagination.get('current_page', page)
            total_pages = pagination.get('total_pages', 1)
            
            log.info(f"Page {current_page}/{total_pages}: fetched {len(workouts)} workouts (total so far: {len(all_workouts)}/{total})")
            
            # Stop if we've reached the limit or there are no more pages
            if limit and len(all_workouts) >= limit:
                all_workouts = all_workouts[:limit]
                break
            
            if current_page >= total_pages:
                break
            
            page += 1
        
        log.info(f"Fetched {len(all_workouts)} total workouts")
        return all_workouts
    
    def get_workout_strokes(self, workout_id: str) -> Optional[list[dict]]:
        """
        Fetch stroke-by-stroke data for a workout.
        
        Args:
            workout_id: Workout ID
            
        Returns:
            List of stroke dicts, or None if not available
        """
        try:
            log.debug(f"Fetching strokes for workout {workout_id}")
            response = self._request('GET', f'/users/me/results/{workout_id}/strokes')
            strokes = response.get('data', [])
            log.debug(f"Fetched {len(strokes)} strokes for workout {workout_id}")
            return strokes
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                log.debug(f"No stroke data available for workout {workout_id}")
                return None
            raise


def process_workout_summary(workout_json: dict, ingest_run_id: str) -> dict:
    """
    Process workout summary into workouts table record.
    
    Uses Strategy B (rich timezone) - trusts per-workout timezone from API.
    
    Args:
        workout_json: Workout JSON from API
        ingest_run_id: Ingestion run identifier
        
    Returns:
        Dict ready for workouts table
    """
    # Extract timestamps with Strategy B
    timestamp_str = workout_json['date']  # "2025-10-30 13:58:00"
    tz_name = workout_json['timezone']    # "America/Los_Angeles"
    
    start_utc, start_local, tz = apply_strategy_b(timestamp_str, tz_name)
    
    # Calculate end time if duration available
    end_utc = None
    end_local = None
    if 'time' in workout_json:
        duration_s = workout_json['time']
        end_utc = start_utc + pd.Timedelta(seconds=duration_s)
        end_local = start_local + pd.Timedelta(seconds=duration_s)
    
    # Map erg type to workout type
    erg_type = workout_json.get('type', 'rower')
    workout_type = ERG_TYPE_MAP.get(erg_type, 'Rowing')
    
    # Extract heart rate data
    hr_data = workout_json.get('heart_rate', {})
    
    # Build workout record
    workout = {
        'workout_id': str(workout_json['id']),
        'source': 'Concept2',
        'workout_type': workout_type,
        'start_time_utc': start_utc,
        'end_time_utc': end_utc,
        'start_time_local': start_local,
        'end_time_local': end_local,
        'timezone': tz,
        'tz_source': 'actual',
        'duration_s': workout_json.get('time'),
        'distance_m': float(workout_json['distance']) if 'distance' in workout_json else None,
        'avg_hr_bpm': float(hr_data.get('average')) if hr_data.get('average') else None,
        'max_hr_bpm': float(hr_data.get('maximum')) if hr_data.get('maximum') else None,
        'min_hr_bpm': float(hr_data.get('minimum')) if hr_data.get('minimum') else None,
        'calories_kcal': float(workout_json.get('calories')) if workout_json.get('calories') else None,
        
        # Concept2-specific
        'c2_workout_type': workout_json.get('workout', {}).get('type'),
        'erg_type': erg_type,
        'stroke_rate': float(workout_json.get('stroke_rate')) if workout_json.get('stroke_rate') else None,
        'stroke_count': int(workout_json.get('stroke_count')) if workout_json.get('stroke_count') else None,
        'drag_factor': int(workout_json.get('drag_factor')) if workout_json.get('drag_factor') else None,
        'ranked': workout_json.get('ranked', False),
        'verified': workout_json.get('verified', False),
        'has_splits': bool(workout_json.get('workout', {}).get('splits')),
        'has_strokes': workout_json.get('stroke_data', False),
        
        # Lineage
        'ingest_time_utc': datetime.now(timezone.utc),
        'ingest_run_id': ingest_run_id,
    }
    
    return workout


def process_splits(
    workout_id: str,
    workout_start_utc: pd.Timestamp,
    splits_json: list[dict],
    ingest_run_id: str,
) -> pd.DataFrame:
    """
    Process splits data into cardio_splits table records.
    
    Args:
        workout_id: Parent workout ID
        workout_start_utc: Workout start time (for partitioning)
        splits_json: List of split dicts from API
        ingest_run_id: Ingestion run identifier
        
    Returns:
        DataFrame ready for cardio_splits table
    """
    if not splits_json:
        return pd.DataFrame()
    
    splits = []
    for i, split in enumerate(splits_json, start=1):
        hr_data = split.get('heart_rate', {})
        
        split_record = {
            'workout_id': workout_id,
            'workout_start_utc': workout_start_utc,
            'split_number': i,
            'split_time_s': int(split.get('time')) if split.get('time') else None,
            'split_distance_m': int(split.get('distance')) if split.get('distance') else None,
            'calories_total': int(split.get('calories')) if split.get('calories') else None,
            'stroke_rate': float(split.get('stroke_rate')) if split.get('stroke_rate') else None,
            'avg_hr_bpm': float(hr_data.get('average')) if hr_data.get('average') else None,
            'min_hr_bpm': float(hr_data.get('minimum')) if hr_data.get('minimum') else None,
            'max_hr_bpm': float(hr_data.get('maximum')) if hr_data.get('maximum') else None,
            'ending_hr_bpm': float(hr_data.get('ending')) if hr_data.get('ending') else None,
        }
        splits.append(split_record)
    
    df = pd.DataFrame(splits)
    df = add_lineage_fields(df, source='Concept2', ingest_run_id=ingest_run_id)
    
    return df


def process_strokes(
    workout_id: str,
    workout_start_utc: pd.Timestamp,
    strokes_json: list[dict],
    ingest_run_id: str,
) -> pd.DataFrame:
    """
    Process stroke data into cardio_strokes table records.
    
    Args:
        workout_id: Parent workout ID
        workout_start_utc: Workout start time (for partitioning)
        strokes_json: List of stroke dicts from API
        ingest_run_id: Ingestion run identifier
        
    Returns:
        DataFrame ready for cardio_strokes table
    """
    if not strokes_json:
        return pd.DataFrame()
    
    strokes = []
    for i, stroke in enumerate(strokes_json, start=1):
        stroke_record = {
            'workout_id': workout_id,
            'workout_start_utc': workout_start_utc,
            'stroke_number': i,
            'time_cumulative_s': int(stroke['t']),
            'distance_cumulative_m': int(stroke['d']),
            'pace_500m_cs': int(stroke.get('p')) if stroke.get('p') else None,
            'heart_rate_bpm': int(stroke.get('hr')) if stroke.get('hr') else None,
            'stroke_rate_spm': int(stroke.get('spm')) if stroke.get('spm') else None,
        }
        strokes.append(stroke_record)
    
    df = pd.DataFrame(strokes)
    df = add_lineage_fields(df, source='Concept2', ingest_run_id=ingest_run_id)
    
    return df


def ingest_workout(
    client: Concept2Client,
    workout_json: dict,
    ingest_run_id: str,
    fetch_strokes: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Ingest a single workout (3-tier: summary + splits + strokes).
    
    Args:
        client: Concept2 API client
        workout_json: Workout JSON from API
        ingest_run_id: Ingestion run identifier
        fetch_strokes: Whether to fetch stroke data (can be slow for many workouts)
        
    Returns:
        Tuple of (workouts_df, splits_df, strokes_df)
    """
    # Tier 1: Workout summary
    workout_record = process_workout_summary(workout_json, ingest_run_id)
    workouts_df = pd.DataFrame([workout_record])
    
    workout_id = workout_record['workout_id']
    workout_start_utc = workout_record['start_time_utc']
    
    # Tier 2: Splits (if available)
    splits_df = pd.DataFrame()
    if workout_record['has_splits']:
        splits_json = workout_json.get('workout', {}).get('splits', [])
        if splits_json:
            splits_df = process_splits(workout_id, workout_start_utc, splits_json, ingest_run_id)
            log.debug(f"Processed {len(splits_df)} splits for workout {workout_id}")
    
    # Tier 3: Strokes (if available and requested)
    strokes_df = pd.DataFrame()
    if fetch_strokes and workout_record['has_strokes']:
        strokes_json = client.get_workout_strokes(workout_id)
        if strokes_json:
            strokes_df = process_strokes(workout_id, workout_start_utc, strokes_json, ingest_run_id)
            log.debug(f"Processed {len(strokes_df)} strokes for workout {workout_id}")
    
    return workouts_df, splits_df, strokes_df


def ingest_recent_workouts(
    limit: int = 50,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    fetch_strokes: bool = True,
) -> dict[str, int]:
    """
    Ingest recent workouts from Concept2 API.
    
    Args:
        limit: Number of workouts to fetch
        from_date: Start date (ISO format: YYYY-MM-DD)
        to_date: End date (ISO format: YYYY-MM-DD)
        fetch_strokes: Whether to fetch stroke-by-stroke data
        
    Returns:
        Dict with counts: {'workouts': N, 'splits': N, 'strokes': N}
    """
    client = Concept2Client()
    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    
    log.info(f"Starting Concept2 ingestion (run_id={ingest_run_id})")
    
    # Fetch workouts
    workouts_json = client.get_recent_workouts(limit, from_date, to_date)
    
    if not workouts_json:
        log.info("No workouts to ingest")
        return {'workouts': 0, 'splits': 0, 'strokes': 0}
    
    # Process all workouts
    all_workouts = []
    all_splits = []
    all_strokes = []
    
    for workout_json in workouts_json:
        try:
            workouts_df, splits_df, strokes_df = ingest_workout(
                client, workout_json, ingest_run_id, fetch_strokes
            )
            
            all_workouts.append(workouts_df)
            if not splits_df.empty:
                all_splits.append(splits_df)
            if not strokes_df.empty:
                all_strokes.append(strokes_df)
        
        except Exception as e:
            log.error(f"Failed to process workout {workout_json.get('id')}: {e}")
            continue
    
    # Combine and write
    counts = {'workouts': 0, 'splits': 0, 'strokes': 0}
    
    if all_workouts:
        # After pd.concat, before upsert_by_key:
        workouts_combined = pd.concat(all_workouts, ignore_index=True)

        # Ensure date partition column is int (YYYYMMDD format)
        if 'date' in workouts_combined.columns:
            workouts_combined['date'] = pd.to_datetime(workouts_combined['date']).dt.strftime('%Y%m%d').astype(int)

        workouts_combined = create_date_partition_column(workouts_combined, 'start_time_utc', 'date')
        
        upsert_by_key(
            workouts_combined,
            WORKOUTS_PATH,
            primary_key=['workout_id', 'source'],
            partition_cols=['date', 'source'],
            schema=get_schema('workouts'),
        )
        counts['workouts'] = len(workouts_combined)
        log.info(f"Wrote {counts['workouts']} workouts")
    
    if all_splits:
        splits_combined = pd.concat(all_splits, ignore_index=True)
        splits_combined = create_date_partition_column(splits_combined, 'workout_start_utc', 'date')
        
        upsert_by_key(
            splits_combined,
            CARDIO_SPLITS_PATH,
            primary_key=['workout_id', 'split_number', 'source'],
            partition_cols=['date', 'source'],
            schema=get_schema('cardio_splits'),
        )
        counts['splits'] = len(splits_combined)
        log.info(f"Wrote {counts['splits']} splits")
    
    if all_strokes:
        strokes_combined = pd.concat(all_strokes, ignore_index=True)
        strokes_combined = create_date_partition_column(strokes_combined, 'workout_start_utc', 'date')
        
        upsert_by_key(
            strokes_combined,
            CARDIO_STROKES_PATH,
            primary_key=['workout_id', 'stroke_number', 'source'],
            partition_cols=['date', 'source'],
            schema=get_schema('cardio_strokes'),
        )
        counts['strokes'] = len(strokes_combined)
        log.info(f"Wrote {counts['strokes']} strokes")
    
    log.info(f"Concept2 ingestion complete: {counts}")
    return counts


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Ingest workouts from Concept2 API')
    parser.add_argument('--limit', type=int, default=50, help='Number of workouts to fetch')
    parser.add_argument('--from-date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--to-date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--no-strokes', action='store_true', help='Skip stroke data (faster)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    try:
        counts = ingest_recent_workouts(
            limit=args.limit,
            from_date=args.from_date,
            to_date=args.to_date,
            fetch_strokes=not args.no_strokes,
        )
        
        print(f"\n✅ Ingestion complete:")
        print(f"   Workouts: {counts['workouts']}")
        print(f"   Splits: {counts['splits']}")
        print(f"   Strokes: {counts['strokes']}")
        
    except Exception as e:
        log.exception("Ingestion failed")
        print(f"\n❌ Ingestion failed: {e}")
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())
