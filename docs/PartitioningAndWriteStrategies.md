# Health Data Pipeline — Partitioning and Write Strategies (v2.2)
**Date:** 2025-11-10  
**Last Updated:** Added comprehensive rationale for write strategy selection

---

## Overview

The Health Data Pipeline uses two distinct write strategies for different data models:
- **`delete_matching`** for time-series data with complete date-range ingestion
- **`upsert_by_key`** for event-based data with natural unique identifiers

This document explains the design rationale, implementation details, and partitioning implications of each strategy.

---

## Core Principle: Data Model Determines Write Strategy

The choice between `delete_matching` and `upsert_by_key` is **not arbitrary** - it follows directly from the data model and ingestion patterns:

| Data Model | Write Strategy | Partition Period | Rationale |
|------------|----------------|------------------|-----------|
| **Time-Series** | `delete_matching` | Daily (`'D'`) | Complete date ranges, atomic replacement |
| **Event-Based** | `upsert_by_key` | Monthly (`'M'`) | Natural IDs, incremental updates, overlapping fetches |

---

## Write Strategy Details

### 1. delete_matching (Time-Series Data)

#### Characteristics

**Data Model:**
- High-frequency measurements (minute-level, daily aggregates)
- Data arrives in complete date-range chunks
- No natural unique identifier per row (just timestamp + source)
- Re-ingestion means "replace this entire date's data"

**Ingestion Pattern:**
```python
# Example: HAE minute-level metrics
Day 1: Process health_export_2025-11-10.csv
       → Writes 1,440 rows to minute_facts for date=2025-11-10

Day 2: Bug fix, re-process health_export_2025-11-10.csv
       → delete_matching removes ALL rows for date=2025-11-10, source=HAE_CSV
       → Writes fresh 1,440 rows
       → Result: Clean replacement, no duplicates
```

**Implementation:**
```python
def process_hae_csv(df, source, ingest_run_id):
    # Add partition column
    df = create_date_partition_column(df, 'timestamp_utc', 'date', 'D')
    
    # Write with delete_matching
    write_partitioned_dataset(
        df,
        MINUTE_FACTS_PATH,
        partition_cols=['date', 'source'],
        schema=MINUTE_FACTS_SCHEMA,
        mode='delete_matching'  # Replaces partition atomically
    )
```

**What Happens:**
1. PyArrow identifies affected partitions (e.g., `date=2025-11-10/source=HAE_CSV/`)
2. Deletes all existing files in that partition
3. Writes new files with incoming data
4. Other partitions remain untouched

**Benefits:**
- ✅ **Idempotent:** Re-ingesting same file produces identical result
- ✅ **Simple:** No complex deduplication logic needed
- ✅ **Fast:** No need to read existing data for comparison
- ✅ **Atomic:** Entire partition replaced as single operation
- ✅ **Correct semantics:** "Replace this day's data" matches intent

**Limitations:**
- ❌ Cannot incrementally add data to a date (must replace entire date)
- ❌ Careful date-range tracking required to avoid data loss
- ❌ Not suitable for overlapping exports

#### Tables Using delete_matching

| Table | Rows/Day | Data Type | Why delete_matching |
|-------|----------|-----------|---------------------|
| `minute_facts` | 1,440 | Time-series measurements | Complete day ingested at once |
| `daily_summary` | 1 | Derived daily aggregates | Recompute entire day atomically |
| `oura_summary` | 1 | Daily sleep/activity summary | API returns complete day summary |

---

### 2. upsert_by_key (Event-Based Data)

#### Characteristics

**Data Model:**
- Discrete events with natural unique identifiers (workout_id, exercise_id)
- Data can arrive incrementally or with overlapping date ranges
- Same event might appear in multiple fetches (API pagination, re-exports)
- Need row-level deduplication by primary key

**Ingestion Pattern:**
```python
# Example: Concept2 API fetches
Day 1: Fetch workouts from 2025-11-01 to 2025-11-10
       → Returns workout IDs: [101, 102, 103, ..., 150]
       → Writes 50 workouts

Day 2: Fetch workouts from 2025-11-05 to 2025-11-15
       → Returns workout IDs: [110, 111, ..., 150, 151, 152, 153]
       → Overlap: 110-150 already exist (40 duplicates)
       → Result: Replace 110-150, add 151-153 (3 new)
       → No duplicate rows
```

**Implementation:**
```python
def process_concept2_workouts(workouts_df, ingest_run_id):
    # Add partition column
    workouts_df = create_date_partition_column(
        workouts_df, 'start_time_utc', 'date', 'M'  # Monthly for upsert
    )
    
    # Upsert by primary key
    upsert_by_key(
        workouts_df,
        WORKOUTS_PATH,
        primary_key=['workout_id', 'source'],  # Natural composite key
        partition_cols=['date', 'source'],
        schema=get_schema('workouts'),
    )
```

**What Happens:**
```python
def upsert_by_key(new_df, table_path, primary_key, partition_cols, schema):
    """
    1. Read entire existing table
    2. For each row in new_df:
       - If PK exists in existing: remove old row, add new row (UPDATE)
       - If PK not in existing: add new row (INSERT)
    3. Write entire combined table back
    """
    existing_df = read_partitioned_dataset(table_path)  # All partitions
    
    if not existing_df.empty:
        # Dedupe: remove existing rows that match new PKs
        pk_tuple = lambda df: df[primary_key].apply(tuple, axis=1)
        new_keys = set(pk_tuple(new_df))
        to_keep = existing_df[~pk_tuple(existing_df).isin(new_keys)]
        
        # Combine kept + new
        combined_df = pd.concat([to_keep, new_df], ignore_index=True)
    else:
        combined_df = new_df
    
    # Rewrite entire table
    write_partitioned_dataset(combined_df, table_path, partition_cols, schema)
```

**Benefits:**
- ✅ **Handles overlaps:** Same event in multiple fetches = automatic deduplication
- ✅ **Incremental updates:** Add new events without re-ingesting everything
- ✅ **Retroactive updates:** API can update existing events (e.g., recalculated calories)
- ✅ **Forgiving:** Don't need precise date-range tracking
- ✅ **Natural semantics:** "Add or update this workout" matches intent

**Limitations:**
- ❌ **Rewrites entire table:** Opens all partition files simultaneously
- ❌ **File descriptor limits:** Requires monthly partitioning (see below)
- ❌ **Slower:** Must read existing data to dedupe
- ❌ **More complex:** Deduplication logic more intricate than simple replacement

#### Tables Using upsert_by_key

| Table | Primary Key | Why upsert_by_key |
|-------|-------------|-------------------|
| `workouts` | [`workout_id`, `source`] | Multiple exports can overlap, API returns overlapping windows |
| `cardio_splits` | [`workout_id`, `split_number`, `source`] | Child of workouts, same ingestion pattern |
| `cardio_strokes` | [`workout_id`, `stroke_number`, `source`] | Child of workouts, same ingestion pattern |
| `resistance_sets` | [`workout_id`, `exercise_id`, `set_number`, `source`] | JEFIT exports are "all time" every time |
| `lactate` | [`workout_id`, `source`] | Extracted from workout comments, may be updated |

---

## Partitioning Strategy

### Rule: Write Strategy Determines Partition Period

The partition period (daily vs monthly) is **not based on data volume** or **query patterns** - it's determined by the **implementation constraints** of the write strategy.

| Write Strategy | Partition Period | Constraint |
|----------------|------------------|------------|
| `delete_matching` | **Daily (`'D'`)** | Only touches specific partitions, no file descriptor issues |
| `upsert_by_key` | **Monthly (`'M'`)** | Opens ALL partition files, must limit total count |

### Why Monthly for upsert_by_key?

The current `upsert_by_key` implementation has a critical scaling limitation:

```python
def upsert_by_key(...):
    # Step 1: Read ENTIRE table (all partitions loaded)
    existing_df = read_partitioned_dataset(table_path)
    
    # Step 2: Dedupe in memory (all rows processed)
    combined_df = merge_and_dedupe(existing_df, new_df)
    
    # Step 3: Write ENTIRE table back (ALL partition files opened)
    write_partitioned_dataset(combined_df, table_path, ...)
    # ↑ This opens file handles for EVERY partition simultaneously
```

**The File Descriptor Problem:**

| Partition Period | 5 Years | File Descriptors | Result |
|------------------|---------|------------------|--------|
| **Daily** | 1,825 partitions | 1,825 files open | ❌ Exceeds OS limit (1,024-4,096) |
| **Monthly** | 60 partitions | 60 files open | ✅ Well under limit |

**Real-World Failure:**
```bash
# Attempting daily partitioning with upsert_by_key
$ make ingest-concept2-history
Processing 5 years of workouts...
Batch 30: 3,049 workouts processed...
Writing to Parquet...
OSError: [Errno 24] Too many open files

# With monthly partitioning
$ make ingest-concept2-history
Processing 5 years of workouts...
✅ Complete: 3,049 workouts written successfully
```

### Partition Period Trade-offs

#### Daily Partitioning

**Pros:**
- Fine-grained query filtering: `WHERE date = '2025-11-10'`
- Smaller file sizes per partition
- Better for time-series queries

**Cons:**
- More partitions to manage (365/year)
- Exceeds file descriptor limits with `upsert_by_key`

**Use for:** Time-series data with `delete_matching`

#### Monthly Partitioning

**Pros:**
- Fewer partitions (12/year)
- Stays under file descriptor limits
- Still reasonable query granularity: `WHERE date >= '2025-11-01' AND date < '2025-12-01'`

**Cons:**
- Coarser query filtering (scans full month for single-day queries)
- Slightly larger files per partition

**Use for:** Event-based data with `upsert_by_key`

---

## Design Rationale: Why Two Strategies?

### Could We Unify on One Strategy?

#### Option 1: Use `upsert_by_key` for Everything

**Problems:**
```python
# minute_facts with upsert_by_key
# 1,440 rows/day × 365 days = 525,600 rows/year

# Every ingestion:
existing = read_table()  # Load 525,600+ rows
pk_check = dedupe(existing, new_1440_rows)  # Check 1,440 against 525k
write_table(combined)  # Write 527k rows
```

- ❌ Expensive: Check 1,440 rows against 525k+ on every ingestion
- ❌ Wrong semantics: Want "replace day" not "merge minutes"
- ❌ Complex PK: Would need (timestamp_utc, source) which isn't really unique
- ❌ Slower: Read + dedupe + write vs simple partition replacement

#### Option 2: Use `delete_matching` for Everything

**Problems:**
```python
# workouts with delete_matching

# Nov 1-30: Load workouts from HAE export
# Nov 10: Fetch Concept2 API for Nov 1-10
# Result: delete_matching removes Nov 1-10, writes new data
# Problem: Lost workouts from HAE for Nov 1-10

# With upsert_by_key:
# Both HAE and Concept2 workouts coexist
# Duplicates removed by workout_id
```

- ❌ Requires strict date-range management to avoid data loss
- ❌ Cannot handle overlapping exports
- ❌ Cannot handle retroactive API updates
- ❌ Error-prone: Easy to accidentally delete data

### Why Current Design Is Optimal

**Each strategy matches its data model:**

| Aspect | Time-Series (delete_matching) | Event-Based (upsert_by_key) |
|--------|------------------------------|----------------------------|
| **Data arrival** | Complete date ranges | Overlapping windows |
| **Re-ingestion** | Replace entire date | Update specific events |
| **Identifier** | Timestamp (not unique) | Natural unique ID |
| **Semantics** | "Replace this day" | "Add or update this event" |
| **Complexity** | Simple | More complex |
| **Speed** | Fast | Slower |
| **Partitioning** | Daily | Monthly (due to implementation) |

---

## Real-World Scenarios

### Scenario 1: API Returns Overlapping Windows

**Concept2 API Example:**
```bash
Day 1: Fetch "last 30 days" (Nov 1-30)
       → Workouts: 101-150 (50 workouts)

Day 2: Fetch "last 30 days" (Nov 2-Dec 1)
       → Workouts: 110-160 (51 workouts)
       → Overlap: 110-150 (40 workouts)
```

**With upsert_by_key:**
```python
# Day 1: Write 101-150
# Day 2: Update 110-150, add 151-160
# Result: 101-160 (all workouts, no duplicates) ✅
```

**With delete_matching:**
```python
# Day 1: Write 101-150 to date=2025-11-01/
# Day 2: Delete date=2025-11-02/, write 110-160
# Result: Missing 101-109 ❌
# Would need complex logic to preserve non-overlapping data
```

### Scenario 2: Bug Fix Re-ingestion

**HAE Minute Facts Example:**
```bash
Day 1: Ingest health_export_2025-11-10.csv
       → 1,440 rows with bug (wrong heart rate calculation)

Day 2: Fix bug, re-ingest health_export_2025-11-10.csv
       → 1,440 rows with correct data
```

**With delete_matching:**
```python
# Day 2: Delete ALL rows for date=2025-11-10
#        Write fresh 1,440 rows
# Result: Clean replacement ✅
```

**With upsert_by_key:**
```python
# Day 2: Would need PK = (timestamp_utc, source)
#        Check 1,440 new rows against 1,440 existing
#        Replace all 1,440 rows
# Result: Same outcome, but more complex and slower ❌
```

### Scenario 3: Retroactive API Updates

**Concept2 API Example:**
```bash
Nov 10: Log workout, Concept2 shows calories=500 (estimated)
Nov 11: Sync API, get workout_id=12345, calories=500

Nov 12: Concept2 recalculates, now shows calories=523 (finalized)
Nov 13: Sync API again, get workout_id=12345, calories=523
```

**With upsert_by_key:**
```python
# Nov 13: Workout 12345 exists, replace with updated data
# Result: Calories updated to 523 ✅
```

**With delete_matching:**
```python
# Nov 13: Would delete entire partition (month=Nov)
#         Re-write all November workouts
# Result: Works but wasteful ❌
# Better: Use upsert to update single workout
```

### Scenario 4: Multiple Export Sources

**HAE Workouts Example:**
```bash
Oct 31: Export HAE workouts for October
        → Contains: Walking, Cycling, Strength workouts

Nov 15: Export HAE workouts for "last 90 days" (Aug 15 - Nov 15)
        → Contains: Walking, Cycling, Strength workouts (overlaps October)

Also: Concept2 API sync adds Rowing workouts continuously
```

**With upsert_by_key:**
```python
# Oct export: Add workouts [HAE_JSON]
# Nov export: Update October workouts, add new ones [HAE_JSON]
# Concept2: Add rowing workouts [Concept2]
# Result: All sources coexist, deduplicated by (workout_id, source) ✅
```

**With delete_matching:**
```python
# Oct export: Write to date=2025-10-01/source=HAE_JSON/
# Nov export: Would overwrite October partition
# Concept2: Need separate source partition
# Problem: Complex to handle overlapping HAE exports ❌
```

---

## Table Reference

### Complete Table Configuration

| Table | Write Strategy | Partition Period | Primary Key | Rationale |
|-------|----------------|------------------|-------------|-----------|
| `minute_facts` | `delete_matching` | Daily (`'D'`) | N/A (timestamp + source) | Time-series, complete days ingested |
| `daily_summary` | `delete_matching` | Daily (`'D'`) | [`date_utc`, `source`] | Derived aggregates, recompute entire day |
| `oura_summary` | `delete_matching` | Daily (`'D'`) | [`day`, `source`] | API returns complete day summary |
| `workouts` | `upsert_by_key` | Monthly (`'M'`) | [`workout_id`, `source`] | Natural IDs, overlapping exports |
| `cardio_splits` | `upsert_by_key` | Monthly (`'M'`) | [`workout_id`, `split_number`, `source`] | Child of workouts |
| `cardio_strokes` | `upsert_by_key` | Monthly (`'M'`) | [`workout_id`, `stroke_number`, `source`] | Child of workouts |
| `resistance_sets` | `upsert_by_key` | Monthly (`'M'`) | [`workout_id`, `exercise_id`, `set_number`, `source`] | JEFIT exports overlap |
| `lactate` | `upsert_by_key` | Monthly (`'M'`) | [`workout_id`, `source`] | Extracted from workouts, may update |

---

## Future Improvements

### Partition-Aware Upsert

The current limitation (monthly partitioning for upsert tables) stems from the `upsert_by_key` implementation being **not partition-aware**.

**Current Implementation:**
```python
def upsert_by_key(...):
    existing = read_entire_table()      # All partitions
    combined = dedupe(existing, new)     # All rows
    write_entire_table(combined)         # Opens ALL files
```

**Partition-Aware Implementation:**
```python
def upsert_by_key_partition_aware(...):
    # Only process affected partitions
    for partition_key, partition_df in new_df.groupby(partition_cols):
        # Read ONLY this partition
        existing = read_partition(table_path, partition_key)
        
        # Dedupe within partition
        combined = dedupe(existing, partition_df)
        
        # Write ONLY this partition
        write_partition(table_path, partition_key, combined)
        # ↑ Opens only 1 file at a time
```

**Benefits:**
- ✅ Enables daily partitioning for all tables
- ✅ Faster (only processes affected partitions)
- ✅ Lower memory usage (incremental processing)
- ✅ No file descriptor limits (only opens 1-30 files)

**Implementation Effort:** ~12-18 hours

**Priority:** Low - monthly partitioning works fine for current scale (<10 GB dataset)

**See:** `docs/FUTURE_UPSERT_IMPROVEMENT.md` for detailed implementation plan

---

## Query Implications

### Querying Daily-Partitioned Tables

```sql
-- Efficient: Partition pruning works perfectly
SELECT * FROM minute_facts 
WHERE date = '2025-11-10' 
  AND source = 'HAE_CSV';
-- Scans: 1 partition (1 day)

-- Efficient: Range queries work well
SELECT * FROM minute_facts 
WHERE date >= '2025-11-01' 
  AND date < '2025-12-01';
-- Scans: 30 partitions (1 month)
```

### Querying Monthly-Partitioned Tables

```sql
-- Less efficient: Scans full month for single day
SELECT * FROM workouts 
WHERE date = '2025-11-10' 
  AND source = 'Concept2';
-- Scans: 1 partition (entire November)
-- Must filter within partition to get Nov 10 only

-- Efficient: Month-level queries work perfectly
SELECT * FROM workouts 
WHERE date >= '2025-11-01' 
  AND date < '2025-12-01';
-- Scans: 1 partition (November)

-- Still reasonable: Multi-month queries
SELECT * FROM workouts 
WHERE date >= '2025-09-01' 
  AND date < '2025-12-01';
-- Scans: 3 partitions (Sep, Oct, Nov)
```

**Impact:** Monthly partitioning is slightly less efficient for single-day queries but still very reasonable given the data volume (<10 GB total dataset).

---

## Common Patterns

### Pattern 1: Idempotent Daily Ingestion

```python
# HAE automation: Run daily at 2am
def daily_hae_ingestion():
    """Idempotent daily automation using delete_matching."""
    
    # 1. Fetch yesterday's export
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    csv_file = download_hae_export(yesterday)
    
    # 2. Process with delete_matching
    df = parse_hae_csv(csv_file)
    df = create_date_partition_column(df, 'timestamp_utc', 'date', 'D')
    
    write_partitioned_dataset(
        df, MINUTE_FACTS_PATH,
        partition_cols=['date', 'source'],
        schema=get_schema('minute_facts'),
        mode='delete_matching'  # Replaces yesterday's partition
    )
    
    # 3. Archive processed file
    archive_file(csv_file)
    
    # Result: Clean, idempotent, no duplicates
```

### Pattern 2: Incremental Workout Sync

```python
# Concept2 automation: Fetch last 7 days weekly
def weekly_concept2_sync():
    """Incremental sync using upsert_by_key."""
    
    # 1. Fetch last 7 days (includes overlap with previous sync)
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=7)
    
    workouts = concept2_api.get_workouts(start_date, end_date)
    df = process_workouts(workouts)
    df = create_date_partition_column(df, 'start_time_utc', 'date', 'M')
    
    # 2. Upsert handles overlaps automatically
    upsert_by_key(
        df, WORKOUTS_PATH,
        primary_key=['workout_id', 'source'],
        partition_cols=['date', 'source'],
        schema=get_schema('workouts'),
    )
    
    # Result: New workouts added, duplicates removed, no data loss
```

### Pattern 3: Manual Re-ingestion

```python
# Bug fix: Re-process specific date range
def reprocess_hae_data(start_date, end_date):
    """Re-process HAE data for date range."""
    
    for date in date_range(start_date, end_date):
        # Find archived CSV for this date
        csv_file = find_archived_csv(date)
        
        # Process with delete_matching
        df = parse_hae_csv(csv_file)
        df = create_date_partition_column(df, 'timestamp_utc', 'date', 'D')
        
        write_partitioned_dataset(
            df, MINUTE_FACTS_PATH,
            partition_cols=['date', 'source'],
            schema=get_schema('minute_facts'),
            mode='delete_matching'  # Clean replacement
        )
        
        log.info(f"Reprocessed {date}")
    
    # Result: Specified dates replaced cleanly
```

---

## Troubleshooting

### Issue: "Too many open files" Error

**Symptoms:**
```
OSError: [Errno 24] Too many open files
Occurs during upsert_by_key write operation
```

**Cause:** 
- Table using `upsert_by_key` has daily partitioning
- 5+ years of data = 1,825+ daily partitions
- Exceeds OS file descriptor limit (typically 1,024-4,096)

**Solution:**
```python
# Change partition period from daily to monthly
# In ingestion script:

# WRONG:
df = create_date_partition_column(df, 'start_time_utc', 'date', 'D')

# CORRECT:
df = create_date_partition_column(df, 'start_time_utc', 'date', 'M')
```

**Verification:**
```bash
# Check partition structure
ls -R Data/Parquet/workouts/date=*/
# Should see: 2025-01-01/, 2025-02-01/, ..., 2025-11-01/
# NOT: 2025-01-01/, 2025-01-02/, 2025-01-03/, ...
```

### Issue: Duplicate Workouts in Table

**Symptoms:**
```
Query returns duplicate workout_id values
Same workout appears multiple times
```

**Cause:**
- `upsert_by_key` not being used, or
- Primary key definition incorrect

**Solution:**
```python
# Verify upsert_by_key is called
upsert_by_key(
    df, table_path,
    primary_key=['workout_id', 'source'],  # Must match natural key
    partition_cols=['date', 'source'],
    schema=schema,
)

# Verify primary key is correct for table
# workouts: ['workout_id', 'source']
# cardio_splits: ['workout_id', 'split_number', 'source']
# cardio_strokes: ['workout_id', 'stroke_number', 'source']
```

**Verification:**
```sql
-- Check for duplicates
SELECT workout_id, source, COUNT(*) as count
FROM workouts
GROUP BY workout_id, source
HAVING count > 1;
-- Should return 0 rows
```

### Issue: Missing Data After Re-ingestion

**Symptoms:**
```
Re-ingested overlapping date range
Now missing data that was previously present
```

**Cause:**
- Used `delete_matching` on event-based data
- Overlapping date range deleted more than intended

**Solution:**
```python
# For event-based data, use upsert_by_key
# WRONG (for workouts):
write_partitioned_dataset(df, WORKOUTS_PATH, mode='delete_matching')

# CORRECT (for workouts):
upsert_by_key(df, WORKOUTS_PATH, primary_key=['workout_id', 'source'], ...)
```

**Recovery:**
```bash
# Restore from backup or re-ingest from original sources
# Event-based data should always use upsert_by_key
```

---

## Summary

### Key Takeaways

1. **Write strategy follows data model:**
   - Time-series → `delete_matching` + daily partitioning
   - Event-based → `upsert_by_key` + monthly partitioning

2. **Monthly partitioning is not a choice, it's a constraint:**
   - Current `upsert_by_key` implementation requires it
   - Daily partitioning would exceed file descriptor limits
   - Future: partition-aware upsert could enable daily everywhere

3. **Each strategy has clear benefits:**
   - `delete_matching`: Simple, fast, idempotent, atomic replacement
   - `upsert_by_key`: Handles overlaps, incremental updates, natural deduplication

4. **Design is deliberate and correct:**
   - Not an inconsistency to be "fixed"
   - Each table uses the strategy that matches its data model
   - Monthly partitioning is pragmatic given implementation constraints

### Decision Matrix

When adding a new table, use this decision tree:

```
Does data have natural unique identifiers (IDs)?
├─ YES: Does data arrive incrementally or with overlapping date ranges?
│  ├─ YES → Use upsert_by_key + monthly partitioning
│  └─ NO → Use delete_matching + daily partitioning
└─ NO → Use delete_matching + daily partitioning

Examples:
- Workouts (has workout_id, overlapping exports) → upsert_by_key + monthly
- Minute metrics (no ID, complete days) → delete_matching + daily
- Daily aggregates (has date, derived) → delete_matching + daily
```

---

## References

- **Architecture:** `docs/HealthDataPipelineArchitecture.md`
- **Schema:** `docs/HealthDataPipelineSchema.md`
- **Timestamp Handling:** `docs/TimestampHandling.md`
- **Future Improvements:** `docs/FUTURE_UPSERT_IMPROVEMENT.md`
