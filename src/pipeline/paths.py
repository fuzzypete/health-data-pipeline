"""
Path definitions for Health Data Pipeline.

All paths are derived from configuration (config.yaml or environment variables).
"""
from __future__ import annotations

from pathlib import Path

from pipeline.common.config import get_config

# Get configuration
config = get_config()

# Root directories
DATA_ROOT = config.get_data_dir('parquet').parent  # Data/
RAW_ROOT = config.get_data_dir('raw')               # Data/Raw/
PARQUET_ROOT = config.get_data_dir('parquet')       # Data/Parquet/
ARCHIVE_ROOT = config.get_data_dir('archive')       # Data/Archive/
ERROR_ROOT = config.get_data_dir('error')           # Data/Error/

# Raw data directories by source
RAW_CSV_DIR = RAW_ROOT / "CSV"
RAW_JSON_DIR = RAW_ROOT / "JSON"

# Archive directories by source
ARCHIVE_CSV_DIR = ARCHIVE_ROOT / "CSV"
ARCHIVE_JSON_DIR = ARCHIVE_ROOT / "JSON"

# Parquet table paths
MINUTE_FACTS_PATH = PARQUET_ROOT / "minute_facts"
DAILY_SUMMARY_PATH = PARQUET_ROOT / "daily_summary"
WORKOUTS_PATH = PARQUET_ROOT / "workouts"
CARDIO_SPLITS_PATH = PARQUET_ROOT / "cardio_splits"
CARDIO_STROKES_PATH = PARQUET_ROOT / "cardio_strokes"
RESISTANCE_SETS_PATH = PARQUET_ROOT / "resistance_sets"

# Create directories on import
for path in [
    RAW_CSV_DIR,
    RAW_JSON_DIR,
    ARCHIVE_CSV_DIR,
    ARCHIVE_JSON_DIR,
    ERROR_ROOT,
]:
    path.mkdir(parents=True, exist_ok=True)

__all__ = [
    "DATA_ROOT",
    "RAW_ROOT",
    "PARQUET_ROOT",
    "ARCHIVE_ROOT",
    "ERROR_ROOT",
    "RAW_CSV_DIR",
    "RAW_JSON_DIR",
    "ARCHIVE_CSV_DIR",
    "ARCHIVE_JSON_DIR",
    "MINUTE_FACTS_PATH",
    "DAILY_SUMMARY_PATH",
    "WORKOUTS_PATH",
    "CARDIO_SPLITS_PATH",
    "CARDIO_STROKES_PATH",
    "RESISTANCE_SETS_PATH",
]
