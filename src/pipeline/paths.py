# src/pipeline/paths.py
from pathlib import Path

DATA_ROOT     = Path("Data")
PARQUET_ROOT  = DATA_ROOT / "Parquet"
RAW_ROOT      = DATA_ROOT / "Raw"

MINUTE_FACTS_PATH  = PARQUET_ROOT / "minute_facts"
DAILY_SUMMARY_PATH = PARQUET_ROOT / "daily_summary"
WORKOUTS_PATH      = PARQUET_ROOT / "workouts"

RAW_CSV_DIR        = RAW_ROOT / "CSV"

__all__ = [
    "DATA_ROOT", "PARQUET_ROOT", "RAW_ROOT",
    "MINUTE_FACTS_PATH", "DAILY_SUMMARY_PATH", "WORKOUTS_PATH",
    "RAW_CSV_DIR",
]
