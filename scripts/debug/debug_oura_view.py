import duckdb
import pandas as pd
import datetime
import os

DB_PATH = 'Data/duck/health.duckdb'
OUTPUT_CSV = 'analysis/outputs/comprehensive_historical_timeline.csv'
START_DATE = '2024-01-01' # Filter for recent data

print("Running Comprehensive Historical Timeline Analysis (v14 - Using Oura Summary Correctly)")
print(f"Database: {DB_PATH}")

if not os.path.exists(DB_PATH):
    print(f"Error: Database file not found at {DB_PATH}")
    exit()

try:
    con = duckdb.connect(database=DB_PATH, read_only=True)

    # 1. Query Lab Results (Ferritin & HDL)
    print("Querying lake.labs...")
    labs_sql = """
    SELECT
        CAST(date AS DATE) AS date,
        MAX(CASE WHEN marker = 'Ferritin' THEN value ELSE NULL END) AS ferritin,
        MAX(CASE WHEN marker = 'HDL' THEN value ELSE NULL END) AS hdl
    FROM lake.labs
    WHERE CAST(date AS DATE) >= CAST(? AS DATE)
    GROUP BY 1
    """
    labs_df = con.execute(labs_sql, [START_DATE]).fetch_df()
    labs_df['date'] = pd.to_datetime(labs_df['date'])

    # 2. Query Performance (Cycling Avg Watts)
    print("Querying lake.workouts and lake.cardio_strokes for avg_watts...")
    perf_sql = """
    SELECT
        CAST(w.start_time_utc AS DATE) AS date,
        AVG(s.watts) AS avg_watts
    FROM lake.workouts AS w
    JOIN lake.cardio_strokes AS s
        ON w.workout_id = s.workout_id
    WHERE
        w.erg_type = 'bike' -- Corrected based on concept2_api.py
        AND s.watts IS NOT NULL
        AND CAST(w.start_time_utc AS DATE) >= CAST(? AS DATE)
    GROUP BY 1
    """
    perf_df = con.execute(perf_sql, [START_DATE]).fetch_df()
    perf_df['date'] = pd.to_datetime(perf_df['date'])

    # 3. Query Events (from Protocol History)
    print("Querying lake.protocol_history...")
    events_sql = """
    SELECT
        CAST(start_date AS DATE) AS date,
        compound_name || COALESCE(': ' || reason, '') AS event_description
    FROM lake.protocol_history
    WHERE CAST(start_date AS DATE) >= CAST(? AS DATE)
    """
    events_df = con.execute(events_sql, [START_DATE]).fetch_df()
    events_df['date'] = pd.to_datetime(events_df['date'])

    # 4. Query Health Metrics (BP, VO2Max, Exercise)
    print("Querying lake.minute_facts for non-Oura metrics...")
    health_sql = """
    SELECT
        CAST(timestamp_utc AS DATE) AS date,
        AVG(blood_pressure_systolic_mmhg) AS bp_systolic,
        AVG(blood_pressure_diastolic_mmhg) AS bp_diastolic,
        MAX(vo2_max_ml_kg_min) AS vo2_max,
        SUM(apple_exercise_time_min) AS exercise_minutes
    FROM lake.minute_facts
    WHERE CAST(timestamp_utc AS DATE) >= CAST(? AS DATE)
    GROUP BY 1
    ORDER BY 1
    """
    health_df = con.execute(health_sql, [START_DATE]).fetch_df()
    health_df['date'] = pd.to_datetime(health_df['date'])
    
    # 5. Query Oura Metrics (Sleep, RHR, HRV)
    print("Querying lake.oura_summary for sleep, RHR, and HRV...")
    # Using column names from your DESCRIBE output
    oura_sql = """
    SELECT
        CAST(day AS DATE) AS date,
        MAX(sleep_score) AS sleep_score,
        MAX(total_sleep_duration_s) / 60.0 AS sleep_minutes,
        MAX(resting_heart_rate_bpm) AS resting_hr,
        MAX(hrv_ms) AS hrv
    FROM lake.oura_summary
    WHERE CAST(day AS DATE) >= CAST(? AS DATE)
    GROUP BY 1
    """
    oura_df = con.execute(oura_sql, [START_DATE]).fetch_df()
    oura_df['date'] = pd.to_datetime(oura_df['date'])


    # 6. Combine all data sources
    print("Combining data sources...")
    
    end_date = datetime.date.today()
    all_dates = pd.date_range(start=START_DATE, end=end_date, freq='D')
    base_df = pd.DataFrame({'date': all_dates})

    final_df = (base_df
                .merge(labs_df, on='date', how='left')
                .merge(perf_df, on='date', how='left')
                .merge(health_df, on='date', how='left')
                .merge(oura_df, on='date', how='left') # <<< ADDED OURA MERGE
                .merge(events_df, on='date', how='left')
               )
    
    final_df = final_df.sort_values(by='date')

    # 7. Apply sane rounding for cleaner data
    print("Applying decimal rounding...")
    rounding_rules = {
        'ferritin': 1,
        'hdl': 1,
        'avg_watts': 2,
        'bp_systolic': 1,
        'bp_diastolic': 1,
        'resting_hr': 1,
        'hrv': 2,
        'vo2_max': 2,
        'exercise_minutes': 0,
        'sleep_score': 1, 
        'sleep_minutes': 0
    }
    final_df = final_df.round(rounding_rules)

    # 8. Create output directory if it doesn't exist
    output_dir = os.path.dirname(OUTPUT_CSV)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created directory: {output_dir}")

    # Save to CSV
    final_df.to_csv(OUTPUT_CSV, index=False)
    
    print("\n======================================================================")
    print(f"✅ Results saved: {OUTPUT_CSV}")
    print(f"   Rows: {len(final_df)}")
    print(f"   Columns: {', '.join(final_df.columns)}")
    print("======================================================================")
    print("\nLast 10 rows of the new file:")
    print(final_df.tail(10))
    
    con.close()

except duckdb.Error as e:
    print(f"\nA DuckDB error occurred: {e}")
    print("Please check your table and column names.")
except Exception as e:
    print(f"\nAn unexpected error occurred: {e}")