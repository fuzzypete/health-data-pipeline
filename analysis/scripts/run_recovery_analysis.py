#!/usr/bin/env python3
"""
Run historical and lactate tracking analyses.
Generates CSV outputs for further analysis/visualization.
"""
import duckdb
from pathlib import Path
from datetime import datetime

# Paths
DUCK_DB = Path("Data/duck/health.duckdb")
OUTPUT_DIR = Path("analysis/outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def run_query(query_file: Path, output_name: str):
    """Execute a SQL query and save results to CSV."""
    print(f"\n{'='*70}")
    print(f"Running: {query_file.name}")
    print(f"{'='*70}")
    
    # Read query
    query = query_file.read_text()
    
    # Execute
    conn = duckdb.connect(str(DUCK_DB), read_only=True)
    df = conn.execute(query).fetchdf()
    conn.close()
    
    # Save
    timestamp = datetime.now().strftime("%Y%m%d")
    output_file = OUTPUT_DIR / f"{output_name}_{timestamp}.csv"
    df.to_csv(output_file, index=False)
    
    print(f"✅ Results saved: {output_file}")
    print(f"   Rows: {len(df)}")
    if not df.empty:
        print(f"   Columns: {', '.join(df.columns[:5])}...")
        print(f"\nFirst few rows:")
        print(df.head(3).to_string())
    
    return df

def main():
    print("Historical Depletion & Lactate Tracking Analysis")
    print(f"Database: {DUCK_DB}")
    
    if not DUCK_DB.exists():
        print(f"❌ Database not found: {DUCK_DB}")
        print("   Run 'make duck.views' first")
        return
    
    # Run analyses
    queries = [
        (Path("analysis/queries/historical_depletion.sql"), "historical_timeline"),
        (Path("analysis/queries/lactate_tracking.sql"), "lactate_analysis"),
    ]
    
    results = {}
    for query_file, output_name in queries:
        if not query_file.exists():
            print(f"⚠️  Query file not found: {query_file}")
            continue
        results[output_name] = run_query(query_file, output_name)
    
    # Summary
    print(f"\n{'='*70}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*70}")
    print(f"Output directory: {OUTPUT_DIR}")
    print("\nFiles generated:")
    for f in OUTPUT_DIR.glob("*.csv"):
        print(f"  - {f.name}")
    
    # Quick insights
    if "lactate_analysis" in results and not results["lactate_analysis"].empty:
        lac_df = results["lactate_analysis"]
        print(f"\n{'='*70}")
        print("LACTATE INSIGHTS")
        print(f"{'='*70}")
        print(f"Total readings: {len(lac_df)}")
        print(f"Date range: {lac_df['workout_date'].min()} to {lac_df['workout_date'].max()}")
        print(f"Lactate range: {lac_df['lactate_mmol'].min():.1f} - {lac_df['lactate_mmol'].max():.1f} mmol/L")
        print(f"Mean lactate: {lac_df['lactate_mmol'].mean():.2f} mmol/L")
        print(f"\nBy equipment:")
        print(lac_df.groupby('workout_type')[['lactate_mmol', 'average_watts', 'avg_hr']].mean().round(1))

if __name__ == "__main__":
    main()
