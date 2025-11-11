#!/usr/bin/env python3
"""
Dedicated PyArrow file discovery debugger.

This script isolates the file-finding logic from the validation script
to see why PyArrow's dataset discovery is failing.
"""

import pyarrow.parquet as pq
import pyarrow as pa
from pathlib import Path
import sys
import os

# Add project root to path to import config
sys.path.append(str(Path.cwd()))
try:
    from scripts.validate_parquet_tables import TABLE_CONFIGS
except ImportError:
    print("FATAL: Could not import TABLE_CONFIGS from scripts.validate_parquet_tables.py")
    print("Please ensure you are running this from the project root.")
    sys.exit(1)

PROJECT_ROOT = Path.cwd()
print(f"== PyArrow File Discovery Debugger ==")
print(f"Project Root: {PROJECT_ROOT}\n")

all_ok = True

for table_name, config in TABLE_CONFIGS.items():
    relative_path = config["path"]
    full_path = PROJECT_ROOT / relative_path
    
    print(f"--- Checking: {table_name} ---")
    print(f"  Path: {full_path}")

    if not full_path.exists():
        print("  ❌ FAILED: Directory does not exist.")
        all_ok = False
        continue

    # 1. Use Python's built-in, reliable glob to find the files
    file_list = list(full_path.glob("**/*.parquet"))
    
    if not file_list:
        print("  ❌ FAILED: Python's glob found no .parquet files in this directory.")
        all_ok = False
        continue
    
    # 2. Convert Path objects to strings for PyArrow
    file_list_str = [str(f) for f in file_list]
    print(f"  [Debug] Found {len(file_list_str)} files via glob. First file: {file_list_str[0].replace(str(PROJECT_ROOT), '...')}")

    try:
        # 3. Pass the *explicit list* of files to pq.read_table
        table = pq.read_table(
            file_list_str,
            partitioning="hive"
        )
        print(f"  ✅ SUCCESS: PyArrow read {table.num_rows} rows from {len(file_list_str)} files.")
    except Exception as e:
        print(f"  ❌ FAILED: PyArrow failed to read the explicit file list.")
        print(f"     Error: {e}")
        all_ok = False

print("\n--- Summary ---")
if all_ok:
    print("✅ All tables were successfully read by PyArrow using Python's glob.")
else:
    print("❌ One or more tables failed. See errors above.")