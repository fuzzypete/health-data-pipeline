#!/usr/bin/env python3
"""
Recovery Baseline: Heart Rate Analysis (v5 - Stable Debug)
Execute the HR analysis query and optionally save results
"""
import duckdb
from pathlib import Path
import sys
import argparse
import re

def run_hr_analysis(output_csv: str = None):
    """
    Run the recovery baseline HR analysis
    
    Args:
        output_csv: Optional path to save weekly summary results as CSV
    """
    print("=" * 60)
    print("Recovery Baseline: Heart Rate Analysis")
    print("Period: Oct 4, 2025 → Present")
    print("=" * 60)
    print()
    
    # --- THIS IS THE FIX (PART 1) ---
    # Connect to the persistent, on-disk database, just like 'make duck.query'
    db_path = Path("Data/duck/health.duckdb")
    if not db_path.exists():
        print(f"❌ Error: Database file not found at {db_path}")
        print("   Please run 'make duck.views' one time to create it.")
        sys.exit(1)

    print(f"📂 Connecting to persistent database: {db_path}")
    con = duckdb.connect(database=str(db_path), read_only=True)
    
    # We NO LONGER create a view. We will use the 'lake.workouts' view
    # that 'make duck.views' already created.
    # --- END FIX ---
    
    # Correct SQL File Pathing
    ANALYSIS_DIR = Path(__file__).parent.parent
    sql_path = ANALYSIS_DIR / "queries" / "recovery_baseline_hr.sql"
    
    if not sql_path.exists():
        print(f"❌ Error: {sql_path} not found")
        sys.exit(1)
    
    print(f"🔍 Loading queries from {sql_path.name}...")
    with open(sql_path) as f:
        full_sql_file = f.read()

    # Split the SQL file into individual queries
    sql_no_comments = re.sub(r'--.*', '', full_sql_file)
    sql_queries = [q.strip() for q in sql_no_comments.split(';') if q.strip()]

    if len(sql_queries) != 5:
        print(f"⚠️  Warning: Expected 5 queries in SQL file, but found {len(sql_queries)}. Output may be incomplete.")

    part_titles = [
        "Part 1: Individual Workout Details",
        "Part 2: Weekly Trend Summary",
        "Part 3: Overall Period Summary",
        "Part 4: Week-over-Week Change",
        "Part 5: Comparison to May 2024 Peak"
    ]

    for i, (title, query) in enumerate(zip(part_titles, sql_queries)):
        if not query.upper().startswith("SELECT"):
            continue
            
        print("\n" + "=" * 60)
        print(title)
        print("=" * 60)
        
        try:
            # --- THIS IS THE FIX (PART 2) ---
            # We replace the broken 'workouts' view with the working 'lake.workouts' view
            final_query = query.replace("FROM workouts", "FROM lake.workouts")
            # --- END FIX ---
            
            result_df = con.execute(final_query).df()
            print(result_df)
        except duckdb.Error as e:
            print(f"❌ Error executing query for {title}:")
            print(f"   Query: {final_query[:200]}...")
            print(e)
            sys.exit(1)
            
        if title == "Part 2: Weekly Trend Summary" and output_csv:
            print("\n" + "=" * 60)
            print(f"💾 Saving weekly summary to {output_csv}...")
            
            output_path = Path(output_csv)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            result_df.to_csv(output_path, index=False)
            print(f"✅ Saved to {output_path}")
    
    print("\n" + "=" * 60)
    print("✅ Analysis complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Recovery Baseline HR Analysis")
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Optional: Path to save the weekly summary CSV file (e.g., analytics/outputs/recovery_weekly.csv)"
    )
    args = parser.parse_args()
    
    try:
        run_hr_analysis(output_csv=args.output)
    except duckdb.Error as e:
        print(f"\n❌ A DuckDB error occurred:")
        print(e)
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ An unexpected error occurred:")
        print(e)
        import traceback
        traceback.print_exc()
        sys.exit(1)