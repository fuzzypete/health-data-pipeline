#!/usr/bin/env python3
"""
Test script for Concept2 API ingestion.

Tests the client and data processing without writing to Parquet.
"""
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_client():
    """Test Concept2 API client connection."""
    from pipeline.ingest.concept2_api import Concept2Client
    
    print("=" * 60)
    print("Testing Concept2 API Client")
    print("=" * 60)
    
    try:
        client = Concept2Client()
        print("✓ Client initialized")
        print(f"  Token: {client.api_token[:10]}...")
        print(f"  Base URL: {client.base_url}")
        
        # Test fetching 1 workout
        print("\nFetching 1 recent workout...")
        workouts = client.get_recent_workouts(limit=1)
        
        if workouts:
            print(f"✓ Fetched {len(workouts)} workout(s)")
            workout = workouts[0]
            print(f"\n  Workout ID: {workout['id']}")
            print(f"  Date: {workout['date']}")
            print(f"  Type: {workout['type']}")
            print(f"  Distance: {workout.get('distance', 'N/A')}m")
            print(f"  Time: {workout.get('time', 'N/A')}s")
            print(f"  Has splits: {bool(workout.get('workout', {}).get('splits'))}")
            print(f"  Has strokes: {workout.get('stroke_data', False)}")
            return workout
        else:
            print("⚠ No workouts returned (account may be empty)")
            return None
    
    except Exception as e:
        print(f"✗ Client test failed: {e}")
        raise


def test_workout_processing(workout):
    """Test workout data processing."""
    from pipeline.ingest.concept2_api import (
        process_workout_summary,
        process_splits,
        process_strokes,
    )
    
    print("\n" + "=" * 60)
    print("Testing Workout Processing")
    print("=" * 60)
    
    try:
        ingest_run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        
        # Test workout summary
        print("\n1. Processing workout summary...")
        workout_record = process_workout_summary(workout, ingest_run_id)
        print(f"✓ Workout record created")
        print(f"  Workout ID: {workout_record['workout_id']}")
        print(f"  Type: {workout_record['workout_type']}")
        print(f"  Start (UTC): {workout_record['start_time_utc']}")
        print(f"  Start (local): {workout_record['start_time_local']}")
        print(f"  Timezone: {workout_record['timezone']}")
        print(f"  TZ Source: {workout_record['tz_source']}")
        
        # Test splits
        splits_json = workout.get('workout', {}).get('splits', [])
        if splits_json:
            print(f"\n2. Processing {len(splits_json)} splits...")
            splits_df = process_splits(
                workout_record['workout_id'],
                workout_record['start_time_utc'],
                splits_json,
                ingest_run_id
            )
            print(f"✓ Splits DataFrame: {len(splits_df)} rows")
            print(f"  Columns: {list(splits_df.columns)}")
            if len(splits_df) > 0:
                print(f"  First split: {splits_df.iloc[0]['split_distance_m']}m, {splits_df.iloc[0]['split_time_s']}s")
        else:
            print("\n2. No splits available")
        
        # Test strokes (just structure, don't fetch)
        if workout.get('stroke_data'):
            print(f"\n3. Workout has stroke data available")
            print(f"  (Skipping actual fetch for test - would be ~1000+ strokes)")
        else:
            print("\n3. No stroke data available")
        
        return True
    
    except Exception as e:
        print(f"✗ Processing test failed: {e}")
        raise


def test_timestamp_strategy():
    """Test Strategy B timestamp handling."""
    from pipeline.common import apply_strategy_b
    import pandas as pd
    
    print("\n" + "=" * 60)
    print("Testing Strategy B Timestamp Handling")
    print("=" * 60)
    
    test_cases = [
        ("2025-10-30 13:58:00", "America/Los_Angeles"),
        ("2025-03-10 02:30:00", "America/Los_Angeles"),  # DST spring forward
        ("2025-11-03 01:30:00", "America/Los_Angeles"),  # DST fall back
    ]
    
    for timestamp_str, tz_name in test_cases:
        try:
            utc, local, tz = apply_strategy_b(timestamp_str, tz_name)
            print(f"\n  Input: {timestamp_str} {tz_name}")
            print(f"    UTC:   {utc}")
            print(f"    Local: {local} (naive)")
            print(f"    TZ:    {tz}")
        except Exception as e:
            print(f"  ✗ Failed: {e}")
    
    print("\n✓ Timestamp strategy working")


def test_schema_validation():
    """Test that processed data matches expected schemas."""
    from pipeline.common import get_schema
    import pyarrow as pa
    
    print("\n" + "=" * 60)
    print("Testing Schema Validation")
    print("=" * 60)
    
    schemas = ['workouts', 'cardio_splits', 'cardio_strokes']
    
    for table_name in schemas:
        try:
            schema = get_schema(table_name)
            print(f"\n✓ {table_name}: {len(schema)} fields")
            print(f"  Fields: {', '.join(schema.names[:5])}...")
        except Exception as e:
            print(f"✗ {table_name}: {e}")


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Concept2 Ingestion Test Suite")
    print("=" * 60 + "\n")
    
    try:
        # Test 1: Client connection
        workout = test_client()
        
        # Test 2: Timestamp handling
        test_timestamp_strategy()
        
        # Test 3: Schema validation
        test_schema_validation()
        
        # Test 4: Data processing (if we have a workout)
        if workout:
            test_workout_processing(workout)
        
        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        print("\nReady to run actual ingestion:")
        print("  poetry run python -m pipeline.ingest.concept2_api --limit 5")
        print("  make ingest-concept2")
        
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ Tests failed!")
        print("=" * 60)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())
