#!/usr/bin/env python3
"""Export parquet subset for Streamlit Cloud deployment.

This script copies the essential tables (excluding large minute-level data)
to a deploy-ready directory that can be committed to the repo.

Usage:
    python scripts/export_for_deploy.py
    python scripts/export_for_deploy.py --months 12  # Last 12 months only
"""

import argparse
import shutil
from datetime import datetime
from pathlib import Path

import duckdb

# Tables to include (excludes minute_facts and cardio_strokes - too large)
TABLES_TO_EXPORT = [
    "workouts",           # 4.8M - Concept2 workouts
    "cardio_splits",      # 768K - Split data
    "resistance_sets",    # 244K - JEFIT strength data
    "oura_summary",       # 6M - Daily recovery metrics
    "labs",               # 136K - Lab results
    "lactate",            # 452K - Lactate measurements
    "protocol_history",   # 60K - Supplement/compound tracking
]

# Tables that are large but could be trimmed by date
OPTIONAL_LARGE_TABLES = [
    "daily_summary",      # 53M - can trim to 1 year
]


def export_table(
    source_root: Path,
    dest_root: Path,
    table_name: str,
    months: int | None = None,
) -> tuple[str, int]:
    """Export a single table, optionally filtering by date.

    Returns:
        Tuple of (table_name, size_bytes)
    """
    source_path = source_root / table_name
    dest_path = dest_root / table_name

    if not source_path.exists():
        print(f"  Skipping {table_name} - not found")
        return table_name, 0

    # If no date filter, just copy the directory
    if months is None:
        if dest_path.exists():
            shutil.rmtree(dest_path)
        shutil.copytree(source_path, dest_path)
        size = sum(f.stat().st_size for f in dest_path.rglob("*.parquet"))
        print(f"  Copied {table_name}: {size / 1024 / 1024:.1f}MB")
        return table_name, size

    # Filter by date - read and rewrite
    from dateutil.relativedelta import relativedelta
    cutoff = datetime.now().replace(day=1) - relativedelta(months=months)

    # Find all parquet files
    parquet_files = list(source_path.rglob("*.parquet"))
    if not parquet_files:
        print(f"  Skipping {table_name} - no parquet files")
        return table_name, 0

    # Read, filter, and write
    conn = duckdb.connect()
    glob_pattern = str(source_path / "**" / "*.parquet")

    # Try different date column names
    date_columns = ["start_time_utc", "workout_start_utc", "day", "date", "date_utc", "test_date"]

    try:
        # Get schema to find date column
        schema = conn.execute(f"DESCRIBE SELECT * FROM read_parquet('{glob_pattern}')").df()
        columns = schema["column_name"].tolist()

        date_col = None
        for dc in date_columns:
            if dc in columns:
                date_col = dc
                break

        if date_col:
            # Filter by date
            df = conn.execute(f"""
                SELECT * FROM read_parquet('{glob_pattern}')
                WHERE {date_col}::DATE >= '{cutoff.date()}'
            """).df()
        else:
            # No date column, copy all
            df = conn.execute(f"SELECT * FROM read_parquet('{glob_pattern}')").df()

        # Write to destination
        dest_path.mkdir(parents=True, exist_ok=True)
        output_file = dest_path / "data.parquet"
        conn.execute(f"COPY df TO '{output_file}' (FORMAT PARQUET)")

        size = output_file.stat().st_size
        print(f"  Exported {table_name}: {size / 1024 / 1024:.1f}MB ({len(df)} rows)")
        return table_name, size

    except Exception as e:
        print(f"  Error exporting {table_name}: {e}")
        # Fallback to direct copy
        if dest_path.exists():
            shutil.rmtree(dest_path)
        shutil.copytree(source_path, dest_path)
        size = sum(f.stat().st_size for f in dest_path.rglob("*.parquet"))
        print(f"  Copied {table_name} (fallback): {size / 1024 / 1024:.1f}MB")
        return table_name, size


def main():
    parser = argparse.ArgumentParser(description="Export parquet for deployment")
    parser.add_argument(
        "--months",
        type=int,
        default=None,
        help="Only export last N months of data (default: all)",
    )
    parser.add_argument(
        "--include-daily-summary",
        action="store_true",
        help="Include daily_summary table (adds ~53MB, or less with --months)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/deploy",
        help="Output directory (default: data/deploy)",
    )
    args = parser.parse_args()

    # Paths
    project_root = Path(__file__).parent.parent
    source_root = project_root / "Data" / "Parquet"
    dest_root = project_root / args.output

    print(f"Exporting parquet data for deployment")
    print(f"  Source: {source_root}")
    print(f"  Destination: {dest_root}")
    if args.months:
        print(f"  Date filter: last {args.months} months")
    print()

    # Clean destination
    if dest_root.exists():
        shutil.rmtree(dest_root)
    dest_root.mkdir(parents=True)

    # Export tables
    tables = TABLES_TO_EXPORT.copy()
    if args.include_daily_summary:
        tables.extend(OPTIONAL_LARGE_TABLES)

    total_size = 0
    for table in tables:
        _, size = export_table(source_root, dest_root, table, args.months)
        total_size += size

    print()
    print(f"Total export size: {total_size / 1024 / 1024:.1f}MB")
    print(f"Output: {dest_root}")
    print()
    print("Next steps:")
    print("  1. Review the exported data")
    print("  2. git add data/deploy/")
    print("  3. git commit -m 'Add deployment data subset'")
    print("  4. git push")


if __name__ == "__main__":
    main()
