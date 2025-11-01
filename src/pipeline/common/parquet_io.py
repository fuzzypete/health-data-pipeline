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
    df: pd.DataFrame,
    table_path: Path,
    partition_cols: list[str],
    schema: Optional[pa.Schema] = None,
    mode: str = 'overwrite_or_ignore',
) -> None:
    """
    Write DataFrame to partitioned Parquet dataset.
    
    Standard write operation for all tables in the pipeline.
    Uses Hive-style partitioning with snappy compression.
    
    Args:
        df: DataFrame to write
        table_path: Root path for the table (e.g., Data/Parquet/minute_facts)
        partition_cols: Columns to partition by (e.g., ['date', 'source'])
        schema: Optional PyArrow schema for validation
        mode: Write mode - 'overwrite_or_ignore', 'append', 'overwrite'
        
    Example:
        >>> df['date'] = pd.to_datetime(df['timestamp_utc']).dt.date
        >>> write_partitioned_dataset(
        ...     df,
        ...     Path('Data/Parquet/minute_facts'),
        ...     partition_cols=['date', 'source']
        ... )
    """
    if df.empty:
        log.warning(f"Skipping write to {table_path}: DataFrame is empty")
        return
    
    # Ensure partition columns exist
    for col in partition_cols:
        if col not in df.columns:
            raise ValueError(f"Partition column '{col}' not found in DataFrame")
    
    # Create table path
    table_path.mkdir(parents=True, exist_ok=True)
    
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
    
    # Write with partitioning
    pq.write_to_dataset(
        table,
        root_path=str(table_path),
        partition_cols=partition_cols,
        existing_data_behavior=mode,
        compression='snappy',
    )
    
    log.info(f"Wrote {len(df)} rows to {table_path} (partitions: {partition_cols})")


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
            schema,
            mode='overwrite'
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
    df: pd.DataFrame,
    timestamp_col: str = 'timestamp_utc',
    partition_col: str = 'date',
) -> pd.DataFrame:
    """
    Create date partition column from timestamp.
    
    Converts a UTC timestamp to date for use as partition key.
    
    Args:
        df: DataFrame with timestamp column
        timestamp_col: Name of timestamp column
        partition_col: Name of partition column to create
        
    Returns:
        DataFrame with added partition column
    """
    if timestamp_col not in df.columns:
        raise ValueError(f"Timestamp column '{timestamp_col}' not found")
    
    # Ensure timestamp is datetime
    if not pd.api.types.is_datetime64_any_dtype(df[timestamp_col]):
        df[timestamp_col] = pd.to_datetime(df[timestamp_col], utc=True)
    
    # Extract date
    df[partition_col] = df[timestamp_col].dt.date
    
    return df


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
