#!/usr/bin/env python3
"""Validate Energy Balance calculations against historical data."""

import duckdb
import pandas as pd
from pathlib import Path

# Setup
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_PATH = PROJECT_ROOT / "Data" / "Parquet"

conn = duckdb.connect()

def parquet_path(table: str) -> str:
    return str(DATA_PATH / table / "**" / "*.parquet")


print("=" * 60)
print("ENERGY BALANCE VALIDATION AGAINST HISTORICAL DATA")
print("=" * 60)

# 1. Nutrition data availability
print("\n=== NUTRITION DATA AVAILABILITY ===\n")

query = f"""
SELECT
    MIN(date_utc) as first_date,
    MAX(date_utc) as last_date,
    COUNT(*) as total_days,
    COUNT(diet_calories_kcal) as days_with_calories,
    COUNT(protein_g) as days_with_protein,
    COUNT(weight_lb) as days_with_weight,
    ROUND(AVG(diet_calories_kcal), 0) as avg_calories,
    ROUND(AVG(protein_g), 0) as avg_protein
FROM read_parquet('{parquet_path("daily_summary")}')
WHERE diet_calories_kcal IS NOT NULL
  AND diet_calories_kcal > 1000
  AND diet_calories_kcal < 5000
"""
df = conn.execute(query).df()
print(df.to_string(index=False))

# 2. Monthly breakdown
print("\n\n=== NUTRITION BY MONTH ===\n")

query2 = f"""
SELECT
    DATE_TRUNC('month', date_utc) as month,
    COUNT(*) as days,
    COUNT(diet_calories_kcal) FILTER (WHERE diet_calories_kcal > 1000) as valid_cal_days,
    ROUND(AVG(diet_calories_kcal) FILTER (WHERE diet_calories_kcal > 1000), 0) as avg_cal,
    ROUND(AVG(protein_g), 0) as avg_protein,
    COUNT(weight_lb) as weight_days,
    ROUND(AVG(weight_lb), 1) as avg_weight
FROM read_parquet('{parquet_path("daily_summary")}')
WHERE date_utc >= '2025-09-01'
GROUP BY 1
ORDER BY 1
"""
df2 = conn.execute(query2).df()
print(df2.to_string(index=False))

# 3. Best validation period analysis
print("\n\n=== VALIDATION PERIOD ANALYSIS (Sep-Nov 2025) ===\n")

query3 = f"""
SELECT
    date_utc as date,
    diet_calories_kcal as calories,
    protein_g,
    weight_lb,
    body_fat_pct
FROM read_parquet('{parquet_path("daily_summary")}')
WHERE date_utc BETWEEN '2025-09-01' AND '2025-11-30'
ORDER BY date_utc
"""
df3 = conn.execute(query3).df()

# Filter to complete days
complete = df3[(df3['calories'].notna()) & (df3['calories'] > 1000) & (df3['calories'] < 5000)]
print(f"Complete nutrition days: {len(complete)}")

if len(complete) > 0:
    print(f"Date range: {complete['date'].min()} to {complete['date'].max()}")
    print(f"Average calories: {complete['calories'].mean():.0f} kcal")
    if complete['protein_g'].notna().any():
        print(f"Average protein: {complete['protein_g'].mean():.0f}g")

# Weight analysis
weight_data = df3[df3['weight_lb'].notna()]
if len(weight_data) > 0:
    start_weight = weight_data.iloc[0]['weight_lb']
    end_weight = weight_data.iloc[-1]['weight_lb']
    weight_change = end_weight - start_weight
    days = (weight_data['date'].iloc[-1] - weight_data['date'].iloc[0]).days

    print(f"\nWeight trend: {start_weight:.1f} -> {end_weight:.1f} lb")
    print(f"Weight change: {weight_change:+.1f} lb over {days} days")

    if len(complete) > 0 and days > 0:
        avg_intake = complete['calories'].mean()
        implied_tdee = avg_intake - (weight_change * 3500 / days)

        print(f"\n--- IMPLIED TDEE CALCULATION ---")
        print(f"Average intake: {avg_intake:.0f} kcal")
        print(f"Weight change adjustment: {weight_change * 3500 / days:.0f} kcal/day")
        print(f"IMPLIED TDEE: {implied_tdee:.0f} kcal")

# 4. Compare to model predictions
print("\n\n=== MODEL VS ACTUAL COMPARISON ===\n")

# Get exercise data for the period
exercise_query = f"""
WITH cardio AS (
    SELECT
        COUNT(DISTINCT workout_id) as cardio_sessions,
        SUM(duration_s) / 60.0 as total_cardio_min
    FROM read_parquet('{parquet_path("workouts")}')
    WHERE start_time_utc BETWEEN '2025-09-01' AND '2025-11-30'
      AND erg_type IS NOT NULL
),
strength AS (
    SELECT
        COUNT(DISTINCT workout_id) as strength_sessions
    FROM read_parquet('{parquet_path("resistance_sets")}')
    WHERE workout_start_utc BETWEEN '2025-09-01' AND '2025-11-30'
)
SELECT
    (SELECT cardio_sessions FROM cardio) as cardio_sessions,
    (SELECT total_cardio_min FROM cardio) as total_cardio_min,
    (SELECT strength_sessions FROM strength) as strength_sessions
"""
exercise_df = conn.execute(exercise_query).df()
print("Training volume (Sep-Nov 2025):")
print(exercise_df.to_string(index=False))

# Calculate model TDEE
if not exercise_df.empty:
    cardio_sessions = exercise_df.iloc[0]['cardio_sessions'] or 0
    cardio_min = exercise_df.iloc[0]['total_cardio_min'] or 0
    strength_sessions = exercise_df.iloc[0]['strength_sessions'] or 0

    # Model parameters
    BMR = 1490
    NEAT_MULT = 1.3
    NEAT_BASELINE = BMR * NEAT_MULT  # ~1937

    # Estimate weekly exercise (spread over ~13 weeks)
    weeks = 13
    weekly_cardio_min = cardio_min / weeks
    weekly_strength = strength_sessions / weeks

    # Exercise calories (10 kcal/min for zone2)
    weekly_exercise_kcal = (weekly_cardio_min * 10) + (weekly_strength * 225)

    # Model TDEE
    model_weekly_tdee = (NEAT_BASELINE * 7) + weekly_exercise_kcal
    model_daily_tdee = model_weekly_tdee / 7

    print(f"\nModel parameters:")
    print(f"  BMR: {BMR} kcal")
    print(f"  NEAT baseline: {NEAT_BASELINE:.0f} kcal")
    print(f"  Weekly cardio: {weekly_cardio_min:.0f} min (~{weekly_cardio_min * 10:.0f} kcal)")
    print(f"  Weekly strength: {weekly_strength:.1f} sessions (~{weekly_strength * 225:.0f} kcal)")
    print(f"\nMODEL TDEE: {model_daily_tdee:.0f} kcal/day")

# 5. Apple Health TDEE comparison
print("\n\n=== APPLE HEALTH TDEE COMPARISON ===\n")

ah_query = f"""
SELECT
    COUNT(*) as days,
    ROUND(AVG(basal_energy_kcal), 0) as avg_basal,
    ROUND(AVG(active_energy_kcal), 0) as avg_active,
    ROUND(AVG(COALESCE(basal_energy_kcal, 0) + COALESCE(active_energy_kcal, 0)), 0) as avg_total
FROM read_parquet('{parquet_path("daily_summary")}')
WHERE date_utc BETWEEN '2025-09-01' AND '2025-11-30'
  AND (basal_energy_kcal IS NOT NULL OR active_energy_kcal IS NOT NULL)
"""
ah_df = conn.execute(ah_query).df()
print("Apple Health energy data:")
print(ah_df.to_string(index=False))

# 6. Summary
print("\n\n" + "=" * 60)
print("VALIDATION SUMMARY")
print("=" * 60)

if len(complete) > 0 and len(weight_data) > 0 and days > 0:
    print(f"\nImplied TDEE (from weight + intake):  {implied_tdee:.0f} kcal")
if not exercise_df.empty:
    print(f"Model TDEE (from training plan):      {model_daily_tdee:.0f} kcal")
if not ah_df.empty and ah_df.iloc[0]['avg_total']:
    print(f"Apple Health TDEE (basal + active):   {ah_df.iloc[0]['avg_total']:.0f} kcal")

print("\nTarget ranges from model:")
print("  Rest days:     ~2,050 kcal")
print("  Light:         ~2,200 kcal")
print("  Moderate:      ~2,400 kcal")
print("  Heavy:         ~2,600 kcal")
