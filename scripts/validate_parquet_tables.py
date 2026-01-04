#!/usr/bin/env python3
"""
Comprehensive Parquet Table Validation Script

Validates:
1. Partition structure (daily vs monthly - based on write strategy)
2. Primary key uniqueness within partitions
3. Expected schema fields present
4. Source values match expected enum
5. Timestamp consistency (UTC vs local)

Usage:
    poetry run python scripts/validate_parquet_tables.py
    poetry run python scripts/validate_parquet_tables.py --table workouts
    poetry run python scripts/validate_parquet_tables.py --verbose
"""
from __future__ import annotations

import argparse
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

# Table configurations
TABLE_CONFIGS = {
    "minute_facts": {
        "path": "Data/Parquet/minute_facts",
        "partition_period": "D",  # Daily - uses delete_matching
        "write_strategy": "delete_matching",
        "partition_cols": ["date", "source"],
        "primary_key": ["timestamp_utc", "source"],
        "expected_sources": ["HAE_CSV", "HAE_CSV_Quick", "HAE_CSV_Automation"],
        "required_fields": ["timestamp_utc", "timestamp_local", "tz_name", "source"],
    },
    "daily_summary": {
        "path": "Data/Parquet/daily_summary",
        "partition_period": "D",  # Daily - uses delete_matching
        "write_strategy": "delete_matching",
        "partition_cols": ["date", "source"],
        "primary_key": ["date_utc", "source"],
        "expected_sources": ["HAE_CSV", "HAE_CSV_Quick", "HAE_CSV_Automation"],
        "required_fields": ["date_utc", "source"],
    },
    "workouts": {
        "path": "Data/Parquet/workouts",
        "partition_period": "M",  # Monthly - uses upsert_by_key
        "write_strategy": "upsert_by_key",
        "partition_cols": ["date", "source"],
        "primary_key": ["workout_id", "source"],
        "expected_sources": ["HAE_JSON", "Concept2", "JEFIT"],
        "required_fields": ["workout_id", "start_time_utc", "start_time_local", "source"],
    },
    "cardio_splits": {
        "path": "Data/Parquet/cardio_splits",
        "partition_period": "M",  # Monthly - uses upsert_by_key
        "write_strategy": "upsert_by_key",
        "partition_cols": ["date", "source"],
        "primary_key": ["workout_id", "split_number", "source"],
        "expected_sources": ["Concept2"],
        "required_fields": ["workout_id", "split_number", "source", "workout_start_utc"],
    },
    "cardio_strokes": {
        "path": "Data/Parquet/cardio_strokes",
        "partition_period": "M",  # Monthly - uses upsert_by_key
        "write_strategy": "upsert_by_key",
        "partition_cols": ["date", "source"],
        "primary_key": ["workout_id", "stroke_number", "source"],
        "expected_sources": ["Concept2"],
        "required_fields": ["workout_id", "stroke_number", "source", "workout_start_utc"],
    },
    "resistance_sets": {
        "path": "Data/Parquet/resistance_sets",
        "partition_period": "M",  # Monthly - uses upsert_by_key
        "write_strategy": "upsert_by_key",
        "partition_cols": ["date", "source"],
        "primary_key": ["workout_id", "exercise_id", "set_number", "source"],
        "expected_sources": ["JEFIT"],
        "required_fields": ["workout_id", "exercise_name", "set_number", "source"],
    },
    "lactate": {
        "path": "Data/Parquet/lactate",
        "partition_period": "M",  # Monthly - uses upsert_by_key
        "write_strategy": "upsert_by_key",
        "partition_cols": ["date", "source"],
        "primary_key": ["workout_id", "source", "reading_sequence"],  # Supports multiple readings per workout
        "expected_sources": ["Concept2_Comment", "Manual"],
        "required_fields": ["workout_id", "measurement_time_utc", "lactate_mmol", "source", "reading_sequence"],
    },
    "oura_summary": {
        "path": "Data/Parquet/oura_summary",
        "partition_period": "D",  # Daily - uses delete_matching
        "write_strategy": "delete_matching",
        "partition_cols": ["date", "source"],
        "primary_key": ["day", "source"],
        "expected_sources": ["Oura"],
        "required_fields": ["day", "source"],
    },
    "labs": {
        "path": "Data/Parquet/labs",
        "partition_period": "Y", # Yearly
        "write_strategy": "delete_matching", # Full file replacement
        "partition_cols": ["year"],
        "primary_key": ["lab_id", "marker"],
        "expected_sources": ["labs-master-latest.xlsx"], # Source is filename
        "required_fields": ["lab_id", "date", "marker"], # 'value' can be null if 'value_text' is present
    },
    "protocol_history": {
        "path": "Data/Parquet/protocol_history",
        "partition_period": "Y", # Yearly
        "write_strategy": "delete_matching", # Full file replacement
        "partition_cols": ["year"],
        "primary_key": ["protocol_id"],
        "expected_sources": ["protocols-master-latest.xlsx"],
        "required_fields": ["protocol_id", "start_date", "compound_name"],
    },
}

# --- VALIDATION CHECKS ---


def check_partition_structure(
    df: pd.DataFrame, config: dict, report: ValidationReport
) -> bool:
    """Check if partition values match expected period."""
    table_name = config["path"].split("/")[-1]
    if "date" not in df.columns:
        if "year" in config.get("partition_cols", []):
             # For 'year' partition, just check it exists
             if df["year"].isnull().any():
                 report.error(table_name, "Found null values in 'year' partition")
                 return False
             report.success(table_name, f"Partitioning OK ({config['partition_period']})")
             return True
        report.warn(table_name, "No 'date' partition column found, skipping structure check")
        return True

    df["is_daily"] = df["date"].str.match(r"^\d{4}-\d{2}-\d{2}$")
    df["is_monthly"] = df["date"].str.match(r"^\d{4}-\d{2}-01$")
    
    all_daily = df["is_daily"].all()
    all_monthly = df["is_monthly"].all()

    if config["partition_period"] == "D" and not all_daily:
        bad_partitions = df[~df["is_daily"]]["date"].unique()
        report.error(table_name, f"Found non-daily partitions in a 'D' table: {bad_partitions}")
        return False
    if config["partition_period"] == "M" and not all_monthly:
        bad_partitions = df[~df["is_monthly"]]["date"].unique()
        report.error(table_name, f"Found non-monthly partitions in a 'M' table: {bad_partitions}")
        return False
    
    report.success(table_name, f"Partitioning OK ({config['partition_period']})")
    return True


def check_pk_uniqueness(
    df: pd.DataFrame, config: dict, report: ValidationReport, verbose: bool
) -> bool:
    """Check for duplicate primary keys within each partition."""
    table_name = config["path"].split("/")[-1]
    pk = config["primary_key"]
    
    # Check if PK columns exist
    missing_pk_cols = [col for col in pk if col not in df.columns]
    if missing_pk_cols:
        report.error(table_name, f"Missing primary key columns: {missing_pk_cols}")
        return False

    duplicates = df.duplicated(subset=pk, keep=False)
    
    if duplicates.any():
        report.error(table_name, f"Found {duplicates.sum()} duplicate rows based on PK {pk}")
        if verbose:
            print(f"\n--- Duplicates for {table_name} ---")
            print(df[duplicates].sort_values(by=pk))
            print("----------------------------------\n")
        return False
    
    report.success(table_name, f"PK {pk} OK")
    return True


def check_schema(
    schema: pq.ParquetSchema, config: dict, report: ValidationReport
) -> bool:
    """Check if required fields are present in the schema."""
    table_name = config["path"].split("/")[-1]
    schema_cols = set(schema.names)
    missing_fields = [
        col for col in config["required_fields"] if col not in schema_cols
    ]
    
    if missing_fields:
        report.error(table_name, f"Missing required fields: {missing_fields}")
        return False
    
    report.success(table_name, "Schema fields OK")
    return True


def check_sources(
    df: pd.DataFrame, config: dict, report: ValidationReport
) -> bool:
    """Check if 'source' values are in the expected list."""
    table_name = config["path"].split("/")[-1]
    
    # Handle 'source' column (from data)
    if "source" in df.columns:
        # Check for sources ingested from files (like labs)
        if "labs-master-latest.xlsx" in config["expected_sources"]:
             report.success(table_name, "Source OK (filename)")
             return True
        if "protocols-master-latest.xlsx" in config["expected_sources"]:
             report.success(table_name, "Source OK (filename)")
             return True
        
        unexpected_sources = set(df["source"].unique()) - set(config["expected_sources"])
        if unexpected_sources:
            report.error(table_name, f"Found unexpected 'source' values in column: {unexpected_sources}")
            return False
        
        report.success(table_name, "Source column values OK")
        return True
    
    # Handle 'source' as partition
    elif "source" in config.get("partition_cols", []):
         report.success(table_name, "Source OK (partition)")
         return True
    
    else:
        report.warn(table_name, "No 'source' column found, skipping check")
        return True


def check_timestamps(
    df: pd.DataFrame, config: dict, report: ValidationReport
) -> bool:
    """Check timestamp_utc (aware) and timestamp_local (naive) consistency."""
    table_name = config["path"].split("/")[-1]
    
    # Standardize column names for checking
    utc_col, local_col = None, None
    if "timestamp_utc" in df.columns and "timestamp_local" in df.columns:
        utc_col, local_col = "timestamp_utc", "timestamp_local"
    elif "start_time_utc" in df.columns and "start_time_local" in df.columns:
        utc_col, local_col = "start_time_utc", "start_time_local"
    elif "measurement_time_utc" in df.columns:
        utc_col = "measurement_time_utc"
    elif "workout_start_utc" in df.columns:
        utc_col = "workout_start_utc"
    
    # Check for Strategy A/B timestamps
    if utc_col:
        if not pd.api.types.is_datetime64_any_dtype(df[utc_col]):
             report.error(table_name, f"{utc_col} column is not a datetime type")
             return False
        
        if isinstance(df[utc_col].dtype, pd.DatetimeTZDtype):
            if df[utc_col].dtype.tz is None:
                 report.error(table_name, f"{utc_col} column is timezone-naive, but should be aware")
                 return False
        else:
            if not df[utc_col].isnull().all():
                report.error(table_name, f"{utc_col} column is timezone-naive (numpy), but should be aware")
                return False
        
        if local_col:
            if not pd.api.types.is_datetime64_any_dtype(df[local_col]):
                report.error(table_name, f"{local_col} column is not a datetime type")
                return False
            
            if isinstance(df[local_col].dtype, pd.DatetimeTZDtype):
                if df[local_col].dtype.tz is not None:
                    report.error(table_name, f"{local_col} column is timezone-aware, but should be naive")
                    return False

        report.success(table_name, "Timestamps (UTC/local) OK")
        return True
    
    # Check for simple date columns (like in labs and protocol_history)
    elif ("date_utc" in config["required_fields"] or 
          "day" in config["required_fields"] or 
          "date" in config["required_fields"] or 
          "start_date" in config["required_fields"]):  # <-- ADDED THIS
        report.success(table_name, "Timestamp (date) OK")
        return True
    
    else:
        report.warn(table_name, "No standard timestamp columns found, skipping check")
        return True

# --- MAIN VALIDATION ---

class ValidationReport:
    """Simple class to store and print validation results."""
    def __init__(self):
        self.successes = defaultdict(list)
        self.warnings = defaultdict(list)
        self.errors = defaultdict(list)
        self.stats = {}  # <-- ADD THIS

    def success(self, table, msg):
        self.successes[table].append(msg)

    def warn(self, table, msg):
        self.warnings[table].append(msg)

    def error(self, table, msg):
        self.errors[table].append(msg)
    
    # --- ADD THIS NEW METHOD ---
    def add_stat(self, table: str, stat_message: str):
        """Add a formatted stat string for a table."""
        self.stats[table] = stat_message
    # --- END ADD ---

    def print_report(self):
        print("\n" + "=" * 80)
        print("PARQUET VALIDATION REPORT")
        print("=" * 80 + "\n")
        print("Partitioning Strategy:")
        print("  Daily (D):     delete_matching tables (minute_facts, daily_summary, oura_summary)")
        print("  Monthly (M):   upsert_by_key tables (workouts, cardio_splits, cardio_strokes, resistance_sets, lactate)")
        print("  Yearly (Y):    delete_matching tables (labs, protocol_history)")
        print("  Reason:        upsert_by_key rewrites entire table -> file descriptor limits\n")


        if self.errors:
            print(f"🔴 ERRORS ({sum(len(v) for v in self.errors.values())}):")
            for table, msgs in self.errors.items():
                for msg in msgs:
                    print(f"  ✗ [{table}] {msg}")
        
        if self.warnings:
            print(f"\n⚠️  WARNINGS ({sum(len(v) for v in self.warnings.values())}):")
            for table, msgs in self.warnings.items():
                for msg in msgs:
                    print(f"  ⚠ [{table}] {msg}")

        print("\n" + "=" * 80)
        print("TABLE STATISTICS")
        print("=" * 80)
        
        # --- REPLACE THE OLD 'TABLE STATISTICS' LOOP WITH THIS ---
        for table in sorted(TABLE_CONFIGS.keys()):
            # Get status icon
            if table in self.errors:
                status_icon = "❌ FAILED"
            elif table in self.warnings:
                status_icon = "⚠ WARNED"
            elif table in self.successes:
                status_icon = "✅ PASSED"
            else:
                status_icon = "❔ SKIPPED"

            # Get stat string, default to status if no stats were added
            stat_msg = self.stats.get(table, status_icon)
            
            # For PASSED/WARNED, the stat msg is the primary info
            if status_icon in ("✅ PASSED", "⚠ WARNED"):
                print(f"  - {table:<20} {status_icon:<10} | {stat_msg}")
            else:
                # For FAILED/SKIPPED, the status is the primary info
                print(f"  - {table:<20} {stat_msg}")
        # --- END REPLACEMENT ---

        print("\n" + "=" * 80)
        status = "❌ VALIDATION FAILED" if self.errors else "✅ VALIDATION PASSED"
        print(f"{status}: {sum(len(v) for v in self.errors.values())} errors, {sum(len(v) for v in self.warnings.values())} warnings")
        print("=" * 80)


# In scripts/validate_parquet_tables.py

def validate_table(table_name, config, report, verbose):
    """Run all validation checks for a single table."""
    print(f"\n--- Validating: {table_name} ---")

    try:
        table_path = Path.cwd() / config["path"]
        
        if not table_path.exists():
            report.warn(table_name, f"Table directory does not exist at {config['path']}")
            report.add_stat(table_name, "SKIPPED (Not Found?)") # <-- Add stat
            return False

        # --- PROVEN-WORKING READ STRATEGY ---
        if verbose:
            print(f"  [Debug] Using pathlib.glob to find files in: {table_path}")

        try:
            file_list = list(table_path.glob("**/*.parquet"))
            
            if not file_list:
                report.warn(table_name, "Table exists but contains no data fragments")
                report.add_stat(table_name, "0 rows") # <-- Add stat
                return True
            
            file_list_str = [str(f) for f in file_list]
            
            if verbose:
                print(f"  [Debug] Found {len(file_list_str)} files. First: {file_list_str[0].replace(str(Path.cwd()), '...')}")

            df_table = pq.read_table(
                file_list_str,
                partitioning="hive"
            )
            
            if df_table.num_rows == 0:
                report.warn(table_name, "Table exists but contains no data fragments (files are empty)")
                report.add_stat(table_name, "0 rows") # <-- Add stat
                return True

            schema = df_table.schema
            df = df_table.to_pandas()

        except (pa.lib.ArrowInvalid, FileNotFoundError) as e:
            report.warn(table_name, f"Table exists but contains no data fragments ({type(e).__name__})")
            report.add_stat(table_name, "0 rows (read error)") # <-- Add stat
            return True
        # --- END READ STRATEGY ---

        if verbose:
            print(f"  [Debug] Found {len(df)} total rows across all partitions.")
        
        # Check 1: Schema
        if not check_schema(schema, config, report):
            report.add_stat(table_name, f"{len(df)} rows (Schema FAILED)") # <-- Add stat
            return False

        # --- (Checks 2, 3, 4, 5...) ---
        # (No changes needed to the check functions themselves)
        partition_cols = config.get("partition_cols", [])
        if partition_cols:
            missing_part_cols = [c for c in partition_cols if c not in df.columns]
            if missing_part_cols:
                report.error(table_name, f"Partition column(s) {missing_part_cols} not loaded into DataFrame.")
                report.add_stat(table_name, f"{len(df)} rows (Partition FAILED)") # <-- Add stat
                return False
            
            partitions = df[partition_cols].drop_duplicates()
            if not check_partition_structure(partitions, config, report):
                 pass
        else:
            report.warn(table_name, "No partition_cols defined, skipping structure check")

        if not check_pk_uniqueness(df, config, report, verbose):
            report.add_stat(table_name, f"{len(df)} rows (PK FAILED)") # <-- Add stat
            return False

        if not check_sources(df, config, report):
            pass 
        
        if not check_timestamps(df, config, report):
            report.add_stat(table_name, f"{len(df)} rows (Timestamp FAILED)") # <-- Add stat
            return False
        
        # --- ADD STATS ON SUCCESS ---
        row_count = len(df)
        
        # Find the primary date column for stats
        date_col = None
        if "start_time_local" in df.columns: date_col = "start_time_local"
        elif "timestamp_local" in df.columns: date_col = "timestamp_local"
        elif "day" in df.columns: date_col = "day"
        elif "date" in df.columns: date_col = "date"
        elif "start_date" in df.columns: date_col = "start_date"
        elif "workout_start_utc" in df.columns: date_col = "workout_start_utc"
        elif "timestamp_utc" in df.columns: date_col = "timestamp_utc"

        stat_msg = f"{row_count:,} rows" # Add comma for readability
        if date_col:
            try:
                if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
                     df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                
                min_date = df[date_col].min()
                max_date = df[date_col].max()
                
                if pd.notna(min_date) and pd.notna(max_date):
                    stat_msg += f" | {min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}"
            except Exception:
                stat_msg += " | (date range error)"
        
        report.add_stat(table_name, stat_msg)
        # --- END ADD STATS ---

        report.success(table_name, "All checks passed")
        return True

    except Exception as e:
        report.error(table_name, f"Validation failed with exception: {e}")
        report.add_stat(table_name, "FAILED TO LOAD") # <-- Add stat
        if verbose:
            import traceback
            traceback.print_exc()
        return False
                    
def main():
    parser = argparse.ArgumentParser(
        description="Validate Parquet table structure and consistency"
    )
    parser.add_argument(
        "--table",
        help="Validate specific table only (default: all tables)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output including duplicate PKs",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,  # Suppress most logs for cleaner output
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    report = ValidationReport()

    if args.table:
        # Validate single table
        if args.table not in TABLE_CONFIGS:
            print(f"❌ Unknown table: {args.table}")
            print(f"Available tables: {', '.join(TABLE_CONFIGS.keys())}")
            return 1

        config = TABLE_CONFIGS[args.table]
        validate_table(args.table, config, report, args.verbose)

    else:
        # Validate all tables
        for table_name, config in TABLE_CONFIGS.items():
            validate_table(table_name, config, report, args.verbose)

    report.print_report()

    # Exit code based on errors
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())