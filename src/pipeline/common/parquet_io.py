"""
Parquet I/O utilities for Health Data Pipeline.

DRY functions for writing partitioned datasets with consistent patterns.
"""
from __future__ import annotations

import logging
import operator
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Any

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pyarrow.compute as pc

log = logging.getLogger(__name__)

# --- OPERATOR MAP ---
OPERATOR_MAP = {
    '=': operator.eq,
    '==': operator.eq,
    '>': operator.gt,
    '>=': operator.ge,
    '<': operator.lt,
    '<=': operator.le,
    '!=': operator.ne,
}

def _build_dnf_expression(dnf_filter_list: List[Any]) -> Optional[pc.Expression]:
    """
    Converts a DNF (Disjunctive Normal Form) list of tuples into a
    PyArrow compute expression.
    """
    if not dnf_filter_list:
        return None

    def build_conjunctive_clause(clause: tuple) -> pc.Expression:
        # Handles: ('col1', '=', 'a')
        if len(clause) == 3 and isinstance(clause[0], str) and clause[1] in OPERATOR_MAP:
            field, op_str, val = clause
            op_func = OPERATOR_MAP[op_str]
            return op_func(pc.field(field), val)
        
        # Handles: ('and', ('col1', '=', 'a'), ('col2', '!=', 'b'))
        if clause[0] == 'and':
            sub_clauses = [build_conjunctive_clause(c) for c in clause[1:]]
            expr = sub_clauses[0]
            for next_expr in sub_clauses[1:]:
                expr = expr & next_expr
            return expr
        
        raise ValueError(f"Unsupported filter clause format: {clause}")

    # Build a list of all the 'and' expressions
    conjunctive_clauses = [build_conjunctive_clause(clause) for clause in dnf_filter_list]

    if not conjunctive_clauses:
        return None

    # OR them all together
    final_expression = conjunctive_clauses[0]
    for next_expression in conjunctive_clauses[1:]:
        final_expression = final_expression | next_expression
    
    return final_expression


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
                raise ValueError(f"Partition column '{col}' not found in Table")
    
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
        max_partitions=4096, # Increased from 2048
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
        filters: DNF filter list (e.g., [('col1', '=', 'a'), ('col2', '!=', 'b')])
        columns: Columns to read (None = all)
        
    Returns:
        DataFrame with requested data
    """
    if not table_path.exists():
        log.warning(f"Table path does not exist: {table_path}")
        return pd.DataFrame()
    
    dataset = ds.dataset(table_path, format='parquet', partitioning='hive')
    
    # Convert list filter to PyArrow Expression
    pa_filter_expr = None
    if filters:
        try:
            pa_filter_expr = _build_dnf_expression(filters)
        except Exception as e:
            log.error(f"Failed to build PyArrow filter expression from: {filters}. Error: {e}")
            raise

    try:
        table = dataset.to_table(filter=pa_filter_expr, columns=columns)
        df = table.to_pandas()
    except pa.ArrowInvalid as e:
        if "No matching fragments found" in str(e):
            log.warning(f"No data found matching filters in {table_path}")
            return pd.DataFrame()
        raise
    
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
    
    This function is designed to be idempotent and safe for re-running.
    It performs a read-modify-write *only on the affected partitions*.
    
    Args:
        new_df: New data to upsert
        table_path: Root path for the table
        primary_key: Columns that form the primary key
        partition_cols: Partition columns
        schema: Optional PyArrow schema
    """
    if new_df.empty:
        log.warning("Skipping upsert: new DataFrame is empty")
        return
    
    # Ensure all primary key columns are in the dataframe
    pk_cols = list(set(primary_key + partition_cols))
    for col in pk_cols:
        if col not in new_df.columns:
            raise ValueError(f"Required key column '{col}' not found in new DataFrame")
    
    # If table doesn't exist, just write
    if not table_path.exists():
        log.info(f"Table doesn't exist, performing initial write to {table_path}")
        write_partitioned_dataset(new_df, table_path, partition_cols, schema, mode="overwrite_or_ignore")
        return
    
    try:
        # Get partition values from new data
        partition_values = new_df[partition_cols].drop_duplicates()
        
        # Build filter for affected partitions (DNF list of lists)
        filters = []
        for _, row in partition_values.iterrows():
            partition_filter = []
            for col in partition_cols:
                partition_filter.append((col, '=', row[col]))
            
            if len(partition_filter) == 1:
                filters.append(partition_filter[0])
            else:
                filters.append(('and', *partition_filter))
        
        # Read existing data *only* for affected partitions
        existing_affected_df = read_partitioned_dataset(
            table_path,
            filters=filters,
            columns=None # Read all columns
        )
        
        if not existing_affected_df.empty:
            # Normalize partition column types to match new_df
            for col in partition_cols:
                if col in existing_affected_df.columns and col in new_df.columns:
                    target_dtype = new_df[col].dtype
                    if existing_affected_df[col].dtype != target_dtype:
                        try:
                            existing_affected_df[col] = existing_affected_df[col].astype(target_dtype)
                        except Exception as e:
                            log.warning(f"Could not cast column {col} to {target_dtype}: {e}")

            # Remove rows with matching primary keys
            pk_tuple = lambda df: df[primary_key].apply(tuple, axis=1)
            new_keys = set(pk_tuple(new_df))
            
            # Keep existing rows that don't match any new keys
            to_keep = existing_affected_df[~pk_tuple(existing_affected_df).isin(new_keys)]
            
            # Combine: kept old + new
            combined_df = pd.concat([to_keep, new_df], ignore_index=True)
            
            log.info(f"Upsert: {len(new_df)} new rows, {len(to_keep)} kept, {len(existing_affected_df) - len(to_keep)} replaced")
        else:
            combined_df = new_df
            log.info(f"Upsert: {len(new_df)} new rows (no existing data in partitions)")
        
        # Overwrite the affected partitions
        write_partitioned_dataset(
            combined_df,
            table_path,
            partition_cols,
            schema,
            mode="delete_matching" # Delete matching partitions and write new data
        )
        
    except Exception as e:
        log.error(f"Upsert failed: {e}", exc_info=True)
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
    """
    if isinstance(data, pa.Table):
        # Handle PyArrow Table
        if timestamp_col not in data.schema.names:
            raise ValueError(f"Timestamp column '{timestamp_col}' not found in Table")
        
        timestamps = data.column(timestamp_col).to_pandas()
        
        if period == 'M':
            # Convert to month-start string 'YYYY-MM-01'
            dates = timestamps.dt.to_period('M').dt.to_timestamp().dt.strftime('%Y-%m-%d')
        else:
            # Convert to daily string 'YYYY-MM-DD'
            dates = timestamps.dt.strftime('%Y-%m-%d')
            
        return data.append_column(partition_col, pa.array(dates))

    elif isinstance(data, pd.DataFrame):
        # Handle pandas DataFrame
        df = data 
        if timestamp_col not in df.columns:
            raise ValueError(f"Timestamp column '{timestamp_col}' not found in DataFrame")
        
        if not pd.api.types.is_datetime64_any_dtype(df[timestamp_col]):
            df[timestamp_col] = pd.to_datetime(df[timestamp_col], utc=True)
        
        if period == 'M':
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', 'Converting to PeriodArray/Index representation will drop timezone information')
                # Convert to month-start string 'YYYY-MM-01'
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
        
        for frag in dataset.get_fragments():
            part_expr = str(frag.partition_expression)
            part_dict = {}
            # This regex parses: (col1 == "val1") and (col2 == "val2")
            # Note: This is fragile and depends on pyarrow's string representation
            matches = re.findall(r'\(([^=]+) == "([^"]+)"\)', part_expr)
            for key, val in matches:
                part_dict[key.strip()] = val
            
            if part_dict:
                partitions.append(part_dict)
        
        # Deduplicate
        if partitions:
            return [dict(t) for t in {tuple(d.items()) for d in partitions}]
        return []

    except Exception as e:
        log.error(f"Failed to get partitions from {table_path}: {e}")
        return []