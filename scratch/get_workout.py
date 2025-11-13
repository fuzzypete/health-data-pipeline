import pandas as pd
import warnings

# Suppress warnings from mean() of empty slice
warnings.filterwarnings("ignore", category=RuntimeWarning)

def analyze_workout(workout: pd.Series, all_strokes: pd.DataFrame, all_lactate: pd.DataFrame):
    """
    Runs a full analysis for a given workout row (either bike or rower).
    """
    WORKOUT_ID = workout['workout_id']
    WORKOUT_TYPE = workout['workout_type']

    print("\n" + "#" * 70)
    print(f"ANALYZING LATEST {WORKOUT_TYPE.upper()} WORKOUT")
    print("#" * 70)
    print(f"Workout ID: {WORKOUT_ID}")
    print(f"Date: {workout['start_time_local']}")

    # --- Part 1: Get Lactate ---
    print("\n" + "=" * 70)
    print("LACTATE")
    print("=" * 70)
    try:
        lactate_reading = all_lactate[all_lactate['workout_id'] == WORKOUT_ID]
        if not lactate_reading.empty:
            # Corrected column name from lactate_schema
            lactate_val = lactate_reading.iloc[0]['lactate_mmol']
            print(f"✅ Lactate reading: {lactate_val} mmol/L")
        else:
            print("No lactate reading found for this workout.")
            print(f"Fallback workout notes: {workout['notes']}")
    except Exception as e:
        print(f"Could not read lactate data: {e}")
        print(f"Fallback workout notes: {workout['notes']}")

    # --- Part 2: Get stroke data ---
    print("\n" + "=" * 70)
    print("STROKE ANALYSIS")
    print("=" * 70)

    workout_strokes = all_strokes[all_strokes['workout_id'] == WORKOUT_ID].copy()

    if workout_strokes.empty:
        print("❌ No stroke data found for this workout.")
        return  # Stop analysis for this workout

    # --- Part 3: Analyze (Logic varies by type) ---
    valid_strokes = pd.DataFrame()
    
    if WORKOUT_TYPE == 'Rowing':
        valid_strokes = workout_strokes[workout_strokes['pace_500m_cs'] > 0].copy()
        if valid_strokes.empty:
            print("❌ No valid rowing strokes with pace > 0 found.")
            return
        
        valid_strokes['time_min'] = valid_strokes['time_cumulative_s'] / 60.0
        valid_strokes['pace_500m_sec'] = valid_strokes['pace_500m_cs'] / 100.0
        avg_pace_str = pd.to_datetime(valid_strokes['pace_500m_sec'].mean(), unit='s').strftime('%M:%S.%f')[:-5]

        print(f"Read {len(valid_strokes)} valid rowing strokes.")
        print("\n--- WORKOUT SUMMARY (Rowing) ---")
        print(f"Duration: {valid_strokes['time_min'].max():.1f} minutes")
        print(f"Average Watts (all): {valid_strokes['watts'].mean():.1f}W")
        print(f"Average HR (all): {valid_strokes['heart_rate_bpm'].mean():.1f} bpm")
        print(f"Average Pace (all): {avg_pace_str}/500m")

    elif WORKOUT_TYPE == 'Cycling':
        valid_strokes = workout_strokes[workout_strokes['watts'] > 0].copy()
        if valid_strokes.empty:
            print("❌ No valid cycling strokes with watts > 0 found.")
            return

        valid_strokes['time_min'] = valid_strokes['time_cumulative_s'] / 60.0
        print(f"Read {len(valid_strokes)} valid cycling strokes.")

        print("\n--- WORKOUT SUMMARY (Cycling) ---")
        print(f"Duration: {valid_strokes['time_min'].max():.1f} minutes")
        print(f"Average Watts (all): {valid_strokes['watts'].mean():.1f}W")
        print(f"Average HR (all): {valid_strokes['heart_rate_bpm'].mean():.1f} bpm")

    else:
        print(f"🤷 Unknown workout type for analysis: {WORKOUT_TYPE}")
        return

    # --- Part 4: Steady State Analysis (common for both) ---
    steady_state = valid_strokes[valid_strokes['heart_rate_bpm'] >= 110].copy()
    print("\n" + "=" * 70)
    print("STEADY STATE ZONE 2 (HR >= 110 bpm)")
    print("=" * 70)
    
    if not steady_state.empty:
        print(f"Duration: {(steady_state['time_min'].max() - steady_state['time_min'].min()):.1f} minutes")
        print(f"Average watts: {steady_state['watts'].mean():.1f}W")
        print(f"Average HR: {steady_state['heart_rate_bpm'].mean():.1f} bpm")
        print(f"Watts CV: {(steady_state['watts'].std() / steady_state['watts'].mean() * 100):.1f}%")
        print(f"HR range: {steady_state['heart_rate_bpm'].min():.0f}-{steady_state['heart_rate_bpm'].max():.0f} bpm")
    else:
        print("No steady state (HR >= 110) data found.")


# --- Main execution ---
def main():
    print("Loading data...")
    try:
        all_workouts = pd.read_parquet('Data/Parquet/workouts')
        all_strokes = pd.read_parquet('Data/Parquet/cardio_strokes')
        all_lactate = pd.read_parquet('Data/Parquet/lactate')
        print("Data loaded.")
    except Exception as e:
        print(f"❌ Failed to load Parquet files: {e}")
        print("Please run ingestion first.")
        return

    # --- Find Last Rower ---
    rowing_workouts = all_workouts[all_workouts['workout_type'] == 'Rowing'].sort_values(by='start_time_utc', ascending=False)
    if not rowing_workouts.empty:
        analyze_workout(rowing_workouts.iloc[0], all_strokes, all_lactate)
    else:
        print("\n" + "#" * 70)
        print("❌ No rowing workouts found.")
        print("#" * 70)

    # --- Find Last Bike ---
    bike_workouts = all_workouts[all_workouts['workout_type'] == 'Cycling'].sort_values(by='start_time_utc', ascending=False)
    if not bike_workouts.empty:
        analyze_workout(bike_workouts.iloc[0], all_strokes, all_lactate)
    else:
        print("\n" + "#" * 70)
        print("❌ No cycling workouts found.")
        print("#" * 70)

if __name__ == "__main__":
    main()