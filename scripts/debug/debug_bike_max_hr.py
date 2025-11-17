#!/usr/bin/env python3
import pandas as pd

WORKOUT_ID = "108476638"
C2_CSV_PATH = "data/concept2-result-108476638.csv"  # adjust as needed

print("=== Loading Parquet strokes ===")
strokes = pd.read_parquet(
    "Data/Parquet/cardio_strokes",
    filters=[("workout_id", "=", WORKOUT_ID)],
)

print(strokes.head())
print(strokes.tail())

print("\nColumns in strokes_df:", strokes.columns.tolist())

print("\n=== Loading Concept2 workbook CSV ===")
c2 = pd.read_csv(C2_CSV_PATH)

# Round times so we can join on ~same stroke
strokes["time_round"] = strokes["time_cumulative_s"].round(1)
c2["time_round"] = c2["Time (seconds)"].round(1)

merged = pd.merge(
    strokes,
    c2,
    on="time_round",
    how="inner",
    suffixes=("_parquet", "_csv"),
)

print("\n=== Last 15 strokes comparison ===")
cols_to_show = [
    "time_round",
    "watts_parquet",
    "heart_rate_bpm",
    "Stroke Rate",
    "Pace (seconds)",
    "Watts",
]
print(
    merged.rename(columns={"watts": "watts_parquet"})[cols_to_show]
          .tail(15)
          .to_string(index=False)
)
