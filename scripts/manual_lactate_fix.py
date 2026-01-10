
import pandas as pd
from datetime import datetime, timedelta, timezone
import pytz
from pipeline.common.parquet_io import upsert_by_key
from pipeline.common.schema import get_schema
from pipeline.paths import LACTATE_PATH

# Define the readings
data = [
    {
        # Mid-workout (~22 mins in)
        "workout_id": "concept2_20260109_182100",
        "reading_sequence": 1,
        "workout_start_utc": pd.Timestamp("2026-01-09 18:21:00").tz_localize("UTC"),
        "timestamp_utc": pd.Timestamp("2026-01-09 18:43:00").tz_localize("UTC"),
        "lactate_mmol": 2.4,
        "watts_at_reading": 108,
        "hr_at_reading": 108, # Approx from avg
        "notes": "Manual fix: Mid-workout reading",
        "measurement_context": "mid_workout",
        "source": "Concept2"
    },
    {
        # End of workout (30 mins)
        "workout_id": "concept2_20260109_182100",
        "reading_sequence": 2,
        "workout_start_utc": pd.Timestamp("2026-01-09 18:21:00").tz_localize("UTC"),
        "timestamp_utc": pd.Timestamp("2026-01-09 18:51:00").tz_localize("UTC"),
        "lactate_mmol": 2.2,
        "watts_at_reading": 108,
        "hr_at_reading": 108, 
        "notes": "Manual fix: End reading",
        "measurement_context": "post_workout",
        "source": "Concept2"
    }
]

df = pd.DataFrame(data)

# Add required lineage fields
df["ingest_time_utc"] = datetime.now(timezone.utc)
df["ingest_run_id"] = "manual_fix_20260109"
df["date"] = "2026-01-01" # Monthly partition

# Ensure schema alignment
schema = get_schema("lactate")
for col in schema.names:
    if col not in df.columns:
        df[col] = None

df = df[schema.names]

print("Upserting manual lactate readings...")
upsert_by_key(
    df,
    LACTATE_PATH,
    primary_key=["workout_start_utc", "lactate_mmol"], # Using value as part of key to allow multiple per workout if timestamps differ
    partition_cols=["date", "source"],
    schema=schema
)
print("Done.")
