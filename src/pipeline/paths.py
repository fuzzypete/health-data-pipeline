#from __future__ import annotations

from pathlib import Path
DATA_DIR = Path('Data')
"""
Path definitions for Health Data Pipeline.

All paths are derived from configuration (config.yaml or environment variables).
"""

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

# Raw data directories - organized by source
RAW_HAE_DIR = RAW_ROOT / "HAE"
RAW_HAE_CSV_DIR = RAW_HAE_DIR / "CSV"
RAW_HAE_JSON_DIR = RAW_HAE_DIR / "JSON"
RAW_JEFIT_DIR = RAW_ROOT / "JEFIT"
RAW_CONCEPT2_DIR = RAW_ROOT / "Concept2"
RAW_LABS_DIR = RAW_ROOT / "labs"

# Archive directories - organized by source
ARCHIVE_HAE_DIR = ARCHIVE_ROOT / "HAE"
ARCHIVE_HAE_CSV_DIR = ARCHIVE_HAE_DIR / "CSV"
ARCHIVE_HAE_JSON_DIR = ARCHIVE_HAE_DIR / "JSON"
ARCHIVE_JEFIT_DIR = ARCHIVE_ROOT / "JEFIT"
ARCHIVE_CONCEPT2_DIR = ARCHIVE_ROOT / "Concept2"
ARCHIVE_LABS_DIR = ARCHIVE_ROOT / "labs"

# Parquet table paths
MINUTE_FACTS_PATH = PARQUET_ROOT / "minute_facts"
DAILY_SUMMARY_PATH = PARQUET_ROOT / "daily_summary"
WORKOUTS_PATH = PARQUET_ROOT / "workouts"
CARDIO_SPLITS_PATH = PARQUET_ROOT / "cardio_splits"
CARDIO_STROKES_PATH = PARQUET_ROOT / "cardio_strokes"
LACTATE_PATH = PARQUET_ROOT / "lactate"
RESISTANCE_SETS_PATH = PARQUET_ROOT / "resistance_sets"
LABS_PATH = PARQUET_ROOT / "labs"
PROTOCOL_HISTORY_PATH = PARQUET_ROOT / "protocol_history" 

# Create directories on import
for path in [
    RAW_HAE_CSV_DIR,
    RAW_HAE_JSON_DIR,
    RAW_JEFIT_DIR,
    RAW_CONCEPT2_DIR,
    ARCHIVE_HAE_CSV_DIR,
    ARCHIVE_HAE_JSON_DIR,
    ARCHIVE_JEFIT_DIR,
    ARCHIVE_CONCEPT2_DIR,
    ARCHIVE_LABS_DIR,
    ERROR_ROOT,
]:
    path.mkdir(parents=True, exist_ok=True)

__all__ = [
    "DATA_ROOT",
    "RAW_ROOT",
    "PARQUET_ROOT",
    "ARCHIVE_ROOT",
    "ERROR_ROOT",
    # HAE paths
    "RAW_HAE_DIR",
    "RAW_HAE_CSV_DIR",
    "RAW_HAE_JSON_DIR",
    "ARCHIVE_HAE_DIR",
    "ARCHIVE_HAE_CSV_DIR",
    "ARCHIVE_HAE_JSON_DIR",
    # JEFIT paths
    "RAW_JEFIT_DIR",
    "ARCHIVE_JEFIT_DIR",
    # Concept2 paths
    "RAW_CONCEPT2_DIR",
    "ARCHIVE_CONCEPT2_DIR",
    # Labs paths
    "RAW_LABS_DIR",
    "ARCHIVE_LABS_DIR",
    # Parquet table paths
    "MINUTE_FACTS_PATH",
    "DAILY_SUMMARY_PATH",
    "WORKOUTS_PATH",
    "CARDIO_SPLITS_PATH",
    "CARDIO_STROKES_PATH",
    "RESISTANCE_SETS_PATH",
    "LABS_PATH",
    "PROTOCOL_HISTORY_PATH",  
]