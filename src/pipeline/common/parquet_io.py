"""
Parquet I/O utilities for Health Data Pipeline.

DRY functions for writing partitioned datasets with consistent patterns.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

log = logging.getLogger(__name__)


def write_partitioned_dataset(
    data_to_write: pd.DataFrame | pa.Table,
    table_path: Path,
    partition_cols: list[str],
    schema: Optional[pa.Schema] = None,
    mode: str = 'delete_matching',
):
    """
    Write DataFrame or Table to partitioned Parquet dataset.

    Uses Hive-style partitioning with Snappy compression.

    Args:
        data_to_write: DataFrame or Table to write
        table_path: Root path for the table (e.g., Data/Parquet/minute_facts)
        partition_cols: Columns to partition by (e.g., ['date', 'source'])
        schema: Optional PyArrow schema for validation
        mode: Write mode — one of:
            - 'overwrite_or_ignore' → safe overwrite-or-skip
            - 'delete_matching'     → delete matching partitions first (true overwrite)
            - 'error'               → fail if existing data is present
            - 'append'              → treated as 'overwrite_or_ignore'
    """
    
    table: pa.Table
    num_rows: int

    if isinstance(data_to_write, pd.DataFrame):
        df = data_to_write  # It's a DataFrame
        if df.empty:
            log.warning(f"Skipping write to {table_path}: DataFrame is empty")
            return
        num_rows = len(df)
        
        # Ensure partition columns exist
        for col in partition_cols:
            if col not in df.columns:
                raise ValueError(f"Partition column '{col}' not found in DataFrame")

        # Convert to PyArrow table
        if schema is not None:
            # Ensure all schema columns exist (fill with None if missing)
            for field in schema:
                if field.name not in df.columns:
                    df[field.name] = None
            
            # Reorder columns to match schema
            df = df[[field.name for field in schema]]
            table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
        else:
            table = pa.Table.from_pandas(df, preserve_index=False)
    
    elif isinstance(data_to_write, pa.Table):
        table = data_to_write  # It's already a Table
        if table.num_rows == 0:
            log.warning(f"Skipping write to {table_path}: Table is empty")
            return
        num_rows = table.num_rows
        
        # Ensure partition columns exist
        for col in partition_cols:
            if col not in table.schema.names:
                raise ValueError(f"Partition column '{col}' not found in Table schema")
    
    else:
        raise TypeError(f"data_to_write must be pd.DataFrame or pa.Table, got {type(data_to_write)}")

    
    # Create table path
    table_path.mkdir(parents=True, exist_ok=True)
    
    # Defensively normalize old mode names (append/overwrite) to PyArrow’s supported ones.
    mode_map = {
        "append": "overwrite_or_ignore",      # legacy synonym for safe append
        "overwrite": "overwrite_or_ignore",   # replace or skip existing rows
        "overwrite_or_ignore": "overwrite_or_ignore",
        "delete_matching": "delete_matching",
        "error": "error",
    }
    pa_mode = mode_map.get(mode, "overwrite_or_ignore")

    # Write with partitioning
    pq.write_to_dataset(
        table,
        root_path=str(table_path),
        partition_cols=partition_cols,
        existing_data_behavior=pa_mode,
        compression='snappy',
        max_partitions=2048, 
    )
    
    log.info(f"Wrote {num_rows} rows to {table_path} (partitions: {partition_cols})")


def read_partitioned_dataset(
    table_path: Path,
    filters: Optional[list] = None,
    columns: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Read Parquet dataset with optional filters.
    
    Args:
        table_path: Root path for the table
        filters: PyArrow filters (e.g., [('date', '>=', '2025-01-01')])
        columns: Columns to read (None = all)
        
    Returns:
        DataFrame with requested data
        
    Example:
        >>> df = read_partitioned_dataset(
        ...     Path('Data/Parquet/minute_facts'),
        ...     filters=[('date', '>=', '2025-10-01'), ('source', '=', 'HAE_CSV')]
        ... )
    """
    if not table_path.exists():
        log.warning(f"Table path does not exist: {table_path}")
        return pd.DataFrame()
    
    dataset = ds.dataset(table_path, format='parquet', partitioning='hive')
    
    table = dataset.to_table(filter=filters, columns=columns)
    df = table.to_pandas()
    
    log.debug(f"Read {len(df)} rows from {table_path}")
    return df


def upsert_by_key(
    new_df: pd.DataFrame,
    table_path: Path,
    primary_key: list[str],
    partition_cols: list[str],
    schema: Optional[pa.Schema] = None,
) -> None:
    """
    Upsert (update or insert) rows by primary key.
    
    Use for workout tables where we want to replace existing workouts
    if they're ingested again (e.g., after Concept2 sync).
    
    Args:
        new_df: New data to upsert
        table_path: Root path for the table
        primary_key: Columns that form the primary key
        partition_cols: Partition columns
        schema: Optional PyArrow schema
        
    Process:
        1. Read existing data for relevant partitions
        2. Remove rows with matching primary keys
        3. Append new rows
        4. Write back to dataset
    """
    if new_df.empty:
        log.warning("Skipping upsert: new DataFrame is empty")
        return
    
    # Ensure primary key columns exist
    for col in primary_key:
        if col not in new_df.columns:
            raise ValueError(f"Primary key column '{col}' not found in new DataFrame")
    
    # If table doesn't exist, just write
    if not table_path.exists():
        log.info(f"Table doesn't exist, performing initial write to {table_path}")
        write_partitioned_dataset(new_df, table_path, partition_cols, schema)
        return
    
    # Get partition values from new data
    partition_values = new_df[partition_cols].drop_duplicates()
    
    # Build filter for affected partitions
    filters = []
    for _, row in partition_values.iterrows():
        partition_filter = [(col, '=', row[col]) for col in partition_cols]
        if len(partition_filter) == 1:
            filters.append(partition_filter[0])
        else:
            filters.append(('and', *partition_filter))
    
    # Read existing data for affected partitions
    try:
        existing_df = read_partitioned_dataset(table_path)
        
        # Normalize partition column types to match new_df (handles migration from old formats)
        if not existing_df.empty:
            for col in partition_cols:
                if col in existing_df.columns and col in new_df.columns:
                    target_dtype = new_df[col].dtype
                    if existing_df[col].dtype != target_dtype:
                        if col == 'date':
                            # Normalize date column to string format (YYYY-MM-DD)
                            existing_df[col] = pd.to_datetime(existing_df[col]).dt.strftime('%Y-%m-%d')
                            log.debug(f"Converted existing '{col}' column to string format for schema compatibility")
                        else:
                            existing_df[col] = existing_df[col].astype(target_dtype)
        
        if not existing_df.empty:
            # Filter to affected partitions
            mask = pd.Series([False] * len(existing_df))
            for col in partition_cols:
                if col in existing_df.columns:
                    mask |= existing_df[col].isin(new_df[col].unique())
            existing_affected = existing_df[mask]
            existing_unaffected = existing_df[~mask]
            
            # Remove rows with matching primary keys
            pk_tuple = lambda df: df[primary_key].apply(tuple, axis=1)
            new_keys = set(pk_tuple(new_df))
            
            # Keep existing rows that don't match any new keys
            to_keep = existing_affected[~pk_tuple(existing_affected).isin(new_keys)]
            
            # Combine: unaffected + kept + new
            combined_df = pd.concat([existing_unaffected, to_keep, new_df], ignore_index=True)
            
            log.info(f"Upsert: {len(new_df)} new rows, {len(to_keep)} kept, {len(existing_affected) - len(to_keep)} replaced")
        else:
            combined_df = new_df
            log.info(f"Upsert: {len(new_df)} new rows (table was empty)")
        
        # Overwrite the entire table
        # (Could be optimized to only overwrite affected partitions)
        write_partitioned_dataset(
            combined_df,
            table_path,
            partition_cols,
            schema
        )
        
    except Exception as e:
        log.error(f"Upsert failed: {e}")
        raise


def add_lineage_fields(
    df: pd.DataFrame,
    source: str,
    ingest_run_id: Optional[str] = None,
) -> pd.DataFrame:
    """
    Add standard lineage fields to DataFrame.
    
    Args:
        df: DataFrame to augment
        source: Source identifier (e.g., 'HAE_CSV', 'Concept2')
        ingest_run_id: Optional run identifier (defaults to current timestamp)
        
    Returns:
        DataFrame with added fields:
        - source
        - ingest_time_utc
        - ingest_run_id
    """
    if ingest_run_id is None:
        ingest_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    
    df['source'] = source
    df['ingest_time_utc'] = datetime.now(timezone.utc)
    df['ingest_run_id'] = ingest_run_id
    
    return df


def create_date_partition_column(
    data: pd.DataFrame | pa.Table,
    timestamp_col: str = 'timestamp_utc',
    partition_col: str = 'date',
    period: str = 'D',
) -> pd.DataFrame | pa.Table:
    """
    Create date partition column from timestamp.

    Converts a UTC timestamp to date for use as partition key.
    Supports both daily and monthly partitioning.

    Args:
        data: DataFrame or Table with timestamp column
        timestamp_col: Name of timestamp column
        partition_col: Name of partition column to create
        period: Pandas period code - 'D' for daily (default), 'M' for monthly
        
    Returns:
        Original data type (DataFrame or Table) with added partition column
        
    Examples:
        Daily partitioning (Concept2 workouts):
        >>> create_date_partition_column(df, 'start_time_utc', 'date', 'D')
        # Creates: '2024-10-15'
        
        Monthly partitioning (Jefit workouts):
        >>> create_date_partition_column(df, 'start_time_utc', 'date', 'M')
        # Creates: '2024-10-01' (first day of month)
    """
    if isinstance(data, pa.Table):
        # Handle PyArrow Table
        if timestamp_col not in data.schema.names:
            raise ValueError(f"Timestamp column '{timestamp_col}' not found in Table")
        
        timestamps = data.column(timestamp_col).to_pandas()
        
        if period == 'M':
            dates = timestamps.dt.to_period('M').dt.to_timestamp().dt.strftime('%Y-%m-%d')
        else:
            dates = timestamps.dt.strftime('%Y-%m-%d')
            
        return data.append_column(partition_col, pa.array(dates))

    elif isinstance(data, pd.DataFrame):
        # Handle pandas DataFrame
        df = data # Use df for clarity
        if timestamp_col not in df.columns:
            raise ValueError(f"Timestamp column '{timestamp_col}' not found in DataFrame")
        
        # Ensure timestamp is datetime (coerce to UTC if needed)
        if not pd.api.types.is_datetime64_any_dtype(df[timestamp_col]):
            df[timestamp_col] = pd.to_datetime(df[timestamp_col], utc=True)
        
        if period == 'M':
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', 'Converting to PeriodArray/Index representation will drop timezone information')
                df[partition_col] = (
                    df[timestamp_col]
                    .dt.to_period('M')
                    .dt.to_timestamp()  # Returns first day of month
                    .dt.strftime('%Y-%m-%d')
                )
        else:
            # Daily (default): extract date as YYYY-MM-DD
            df[partition_col] = df[timestamp_col].dt.strftime('%Y-%m-%d')
        
        return df
    
    else:
        raise TypeError(f"data must be pd.DataFrame or pa.Table, got {type(data)}")


def get_existing_partitions(table_path: Path) -> list[dict]:
    """
    Get list of existing partitions in a table.
    
    Args:
        table_path: Root path for the table
        
    Returns:
        List of dicts with partition values (e.g., [{'date': '2025-10-30', 'source': 'HAE_CSV'}])
    """
    if not table_path.exists():
        return []
    
    try:
        dataset = ds.dataset(table_path, format='parquet', partitioning='hive')
        partitions = []
        
        for fragment in dataset.get_fragments():
            partition_dict = {}
            if fragment.partition_expression:
                # Parse partition expression
                expr_str = str(fragment.partition_expression)
                # Simple parsing (assumes format like "date=2025-10-30 and source=HAE_CSV")
                for part in expr_str.split(' and '):
                    if '=' in part:
                        key, val = part.split('=', 1)
                        partition_dict[key.strip()] = val.strip().strip('"\'')
            
            if partition_dict:
                partitions.append(partition_dict)
        
        return partitions
    except Exception as e:
        log.error(f"Failed to get partitions from {table_path}: {e}")
        return []