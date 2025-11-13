#!/usr/bin/env python3
"""
Debug script to ingest a single Concept2 workout by ID.

Usage:
    python scripts/ingest_concept2_by_id.py <workout_id> [--dry-run] [--skip-strokes]

Examples:
    python scripts/ingest_concept2_by_id.py 87112473
    python scripts/ingest_concept2_by_id.py 87112473 --dry-run
    python scripts/ingest_concept2_by_id.py 87112473 --skip-strokes
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pipeline.ingest.concept2_api import (
    Concept2Client,
    process_workout_summary,
    process_splits,
    process_strokes,
)
from pipeline.common.parquet_io import upsert_by_key
from pipeline.paths import WORKOUTS_PATH, CARDIO_SPLITS_PATH, CARDIO_STROKES_PATH

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


def fetch_and_display_workout(client: Concept2Client, workout_id: str):
    """Fetch workout and display its structure."""
    log.info(f"Fetching workout {workout_id}...")
    
    try:
        response = client._request('GET', f'/users/me/results/{workout_id}')
        workout_data = response.get('data')
        
        if not workout_data:
            log.error("No workout data returned")
            return None
        
        log.info(f"\n{'='*80}")
        log.info("WORKOUT SUMMARY JSON:")
        log.info(f"{'='*80}")
        print(json.dumps(workout_data, indent=2))
        
        return workout_data
    
    except Exception as e:
        log.error(f"Failed to fetch workout: {e}")
        return None


def fetch_and_display_strokes(client: Concept2Client, workout_id: str):
    """Fetch strokes and display their structure."""
    log.info(f"\nFetching strokes for workout {workout_id}...")
    
    try:
        response = client._request('GET', f'/users/me/results/{workout_id}/strokes')
        strokes_data = response.get('data', [])
        
        log.info(f"\n{'='*80}")
        log.info("STROKES RESPONSE STRUCTURE:")
        log.info(f"{'='*80}")
        log.info(f"Response type: {type(response)}")
        log.info(f"Response keys: {list(response.keys())}")
        log.info(f"Data type: {type(strokes_data)}")
        log.info(f"Data length: {len(strokes_data) if strokes_data else 0}")
        
        if strokes_data:
            log.info(f"First element type: {type(strokes_data[0])}")
            
            if isinstance(strokes_data[0], dict):
                log.info(f"First element keys: {list(strokes_data[0].keys())}")
                log.info(f"\nFirst stroke sample:")
                print(json.dumps(strokes_data[0], indent=2))
            elif isinstance(strokes_data[0], list):
                log.error("⚠️  PROBLEM: First element is a LIST, not a dict!")
                log.info(f"First list length: {len(strokes_data[0])}")
                if strokes_data[0]:
                    log.info(f"First list's first element type: {type(strokes_data[0][0])}")
                    if isinstance(strokes_data[0][0], dict):
                        log.info(f"First list's first element keys: {list(strokes_data[0][0].keys())}")
            else:
                log.error(f"⚠️  UNEXPECTED TYPE: {type(strokes_data[0])}")
            
            if len(strokes_data) > 1:
                log.info(f"\nSecond element type: {type(strokes_data[1])}")
            
            # Show full structure for first few elements
            log.info(f"\n{'='*80}")
            log.info("FULL STROKES DATA (first 3):")
            log.info(f"{'='*80}")
            print(json.dumps(strokes_data[:3], indent=2))
        
        return strokes_data
    
    except Exception as e:
        log.error(f"Failed to fetch strokes: {e}")
        return None


def process_workout(client: Concept2Client, workout_id: str, dry_run: bool = True, fetch_strokes: bool = True):
    """Process a workout through the pipeline."""
    ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    
    # Fetch workout summary
    workout_json = fetch_and_display_workout(client, workout_id)
    if not workout_json:
        return False
    
    # Process summary
    log.info(f"\n{'='*80}")
    log.info("PROCESSING WORKOUT SUMMARY:")
    log.info(f"{'='*80}")
    try:
        workout_record = process_workout_summary(workout_json, ingest_run_id)
        log.info(f"✓ Workout summary processed:")
        for key, value in workout_record.items():
            log.info(f"  {key}: {value}")
    except Exception as e:
        log.error(f"✗ Failed to process workout summary: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Process splits
    log.info(f"\n{'='*80}")
    log.info("PROCESSING SPLITS:")
    log.info(f"{'='*80}")
    if workout_record.get("has_splits"):
        try:
            workout_data = workout_json.get("workout")
            if isinstance(workout_data, dict):
                splits_json = workout_data.get("splits", [])
            else:
                splits_json = []
            
            if splits_json:
                splits_df = process_splits(
                    workout_record["workout_id"],
                    workout_record["start_time_utc"],
                    splits_json,
                    ingest_run_id
                )
                log.info(f"✓ Processed {len(splits_df)} splits")
                log.info(f"\nSplits DataFrame:\n{splits_df.to_string()}")
            else:
                log.info("No splits data found")
        except Exception as e:
            log.error(f"✗ Failed to process splits: {e}")
            import traceback
            traceback.print_exc()
    else:
        log.info("Workout has no splits")
    
    # Process strokes
    if fetch_strokes and workout_record.get("has_strokes"):
        log.info(f"\n{'='*80}")
        log.info("PROCESSING STROKES:")
        log.info(f"{'='*80}")
        
        strokes_json = fetch_and_display_strokes(client, workout_id)
        
        if strokes_json:
            try:
                erg_type = workout_record.get("erg_type", "rower")
                log.info(f"Using erg_type: {erg_type}")
                
                strokes_df = process_strokes(
                    workout_record["workout_id"],
                    workout_record["start_time_utc"],
                    strokes_json,
                    ingest_run_id,
                    erg_type
                )
                log.info(f"✓ Processed {len(strokes_df)} strokes")
                log.info(f"\nFirst 10 strokes:\n{strokes_df.head(10).to_string()}")
                log.info(f"\nLast 10 strokes:\n{strokes_df.tail(10).to_string()}")
            except Exception as e:
                log.error(f"✗ Failed to process strokes: {e}")
                import traceback
                traceback.print_exc()
                return False
    elif not fetch_strokes:
        log.info("Skipping strokes (--skip-strokes flag)")
    else:
        log.info("Workout has no strokes")
    
    if not dry_run:
        log.info(f"\n{'='*80}")
        log.info("WRITING TO PARQUET:")
        log.info(f"{'='*80}")
        log.warning("⚠️  NOT IMPLEMENTED YET - Use --dry-run for now")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Debug script to ingest a single Concept2 workout by ID"
    )
    parser.add_argument("workout_id", help="Concept2 workout ID")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Don't write to parquet (default: True)")
    parser.add_argument("--skip-strokes", action="store_true",
                        help="Skip fetching/processing strokes")
    parser.add_argument("--write", action="store_true",
                        help="Write to parquet (overrides --dry-run)")
    
    args = parser.parse_args()
    
    dry_run = not args.write
    
    log.info(f"{'='*80}")
    log.info(f"CONCEPT2 SINGLE WORKOUT INGESTION - Workout ID: {args.workout_id}")
    log.info(f"Mode: {'DRY RUN' if dry_run else 'WRITE TO PARQUET'}")
    log.info(f"Fetch strokes: {not args.skip_strokes}")
    log.info(f"{'='*80}\n")
    
    client = Concept2Client()
    
    success = process_workout(
        client,
        args.workout_id,
        dry_run=dry_run,
        fetch_strokes=not args.skip_strokes
    )
    
    if success:
        log.info(f"\n{'='*80}")
        log.info("✓ SUCCESS")
        log.info(f"{'='*80}")
    else:
        log.error(f"\n{'='*80}")
        log.error("✗ FAILED")
        log.error(f"{'='*80}")
        sys.exit(1)


if __name__ == "__main__":
    main()
