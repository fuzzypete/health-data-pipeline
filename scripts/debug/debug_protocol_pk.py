#!/usr/bin/env python3
import pyarrow.parquet as pq
import pandas as pd

PATH = "Data/Parquet/protocol_history"

table = pq.read_table(PATH)
df = table.to_pandas()

dups = df[df.duplicated("protocol_id", keep=False)].copy()
dups = dups.sort_values("protocol_id")

print("=== Duplicate protocol_id rows ===")
cols = [
    "protocol_id",
    "start_date",
    "compound_name",
    "dosage",
    "dosage_unit",
    "frequency",
    "reason",
    "notes",
]
existing_cols = [c for c in cols if c in dups.columns]
print(dups[existing_cols].to_string(index=False))
print("\nTotal duplicate rows:", len(dups))
