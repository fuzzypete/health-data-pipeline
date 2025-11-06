# Labs & Protocol History Implementation

## Design Decisions

### Labs: Long Format (Normalized)
Rather than wide format (one column per test), use **long format** (one row per test result):

**Why long format?**
- ✅ New tests don't require schema changes
- ✅ Each marker has metadata (units, reference ranges)
- ✅ Easy time-series queries: `SELECT date, value FROM labs WHERE marker='Ferritin'`
- ✅ Handles missing data naturally (no NULLs in wide table)
- ✅ Scalable as you add more specialized tests

**Trade-off:**
- ❌ Requires pivot/join for multi-marker analysis
- ✅ But modern query engines (DuckDB, BigQuery) handle this efficiently

---

## Schema Designs

### 1. Labs Table (Normalized)

```python
labs_schema = pa.schema([
    # Lab visit metadata
    pa.field("lab_id", pa.string(), nullable=False),  # Hash of (date, lab_name)
    pa.field("date", pa.date32(), nullable=False),
    pa.field("lab_name", pa.string(), nullable=True),  # "Quest Diagnostics", "Labcorp"
    pa.field("reason", pa.string(), nullable=True),  # "Self Comprehensive", "TRT Clinic"
    
    # Test result
    pa.field("marker", pa.string(), nullable=False),  # "Ferritin", "Glucose", "Testosterone"
    pa.field("value", pa.float64(), nullable=True),  # Numeric value
    pa.field("value_text", pa.string(), nullable=True),  # Original value if non-numeric ("<10", ">1500")
    pa.field("unit", pa.string(), nullable=True),  # "ng/mL", "mg/dL", "%"
    
    # Reference ranges (for context)
    pa.field("ref_low", pa.float64(), nullable=True),  # Lower bound of normal range
    pa.field("ref_high", pa.float64(), nullable=True),  # Upper bound of normal range
    pa.field("flag", pa.string(), nullable=True),  # "L" (low), "H" (high), "N" (normal), null
    
    # Lineage
    pa.field("source", pa.string(), nullable=False),  # "AllLabsv8_Manual"
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),
    
    # Hive partitioning (by year for labs)
    pa.field("year", pa.string(), nullable=True),
])

# Primary key: (lab_id, marker)
# Partitions: year
```

**Example rows:**
```
lab_id              | date       | marker      | value | unit   | ref_low | ref_high | flag
--------------------|------------|-------------|-------|--------|---------|----------|-----
2025-10-03_Quest    | 2025-10-03 | Ferritin    | 15.0  | ng/mL  | 30.0    | 400.0    | L
2025-10-03_Quest    | 2025-10-03 | Glucose     | 75.0  | mg/dL  | 70.0    | 100.0    | N
2025-10-03_Quest    | 2025-10-03 | HDL         | 31.0  | mg/dL  | 40.0    | null     | L
2025-10-03_Quest    | 2025-10-03 | Testosterone| 981.0 | ng/dL  | 264.0   | 916.0    | H
```

### 2. Protocol History Table (Supplements/Meds)

```python
protocol_history_schema = pa.schema([
    # Event identification
    pa.field("protocol_id", pa.string(), nullable=False),  # UUID
    pa.field("start_date", pa.date32(), nullable=False),
    pa.field("end_date", pa.date32(), nullable=True),  # NULL if ongoing
    
    # Compound details
    pa.field("compound_name", pa.string(), nullable=False),  # "Ferrous Sulfate", "Niacin", "Anavar"
    pa.field("compound_type", pa.string(), nullable=True),  # "Supplement", "Medication", "AAS", "TRT"
    pa.field("dosage", pa.float64(), nullable=True),  # 200.0
    pa.field("dosage_unit", pa.string(), nullable=True),  # "mg", "mg/week", "IU"
    pa.field("frequency", pa.string(), nullable=True),  # "EOD", "Daily", "2x/week"
    
    # Context
    pa.field("reason", pa.string(), nullable=True),  # "Iron repletion", "Lipid management"
    pa.field("notes", pa.string(), nullable=True),  # Free text
    
    # Lineage
    pa.field("source", pa.string(), nullable=False),  # "Manual", "Recovery_Plan_Import"
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),
    
    # Hive partitioning
    pa.field("year", pa.string(), nullable=True),  # Year of start_date
])

# Primary key: protocol_id
# Partitions: year (of start_date)
```

**Example rows:**
```
protocol_id | start_date | end_date   | compound_name    | dosage | unit  | frequency | reason
------------|------------|------------|------------------|--------|-------|-----------|------------------
uuid-001    | 2025-10-17 | null       | Ferrous Sulfate  | 200.0  | mg    | EOD       | Iron repletion
uuid-002    | 2025-10-17 | null       | Niacin           | 1500.0 | mg    | Daily     | HDL recovery
uuid-003    | 2024-08-01 | 2025-10-11 | Anavar           | 35.0   | mg    | Daily     | Cycle
uuid-004    | 2024-08-01 | 2025-10-11 | Testosterone Cyp | 200.0  | mg/wk | Weekly    | TRT base
```

---

## Ingestion Approach

### Labs: Excel → Long Format

**Transformation steps:**
1. Read Excel wide format (53 columns)
2. Melt to long format (unpivot)
3. Extract units from column names using regex
4. Parse special values (`<10` → value_text="<10", value=10.0, flag="L")
5. Add reference ranges (hardcoded dict or separate config)
6. Generate lab_id hash
7. Write to parquet

**Input (wide):**
```
Date       | Ferritin (ng/mL) | HDL (mg/dL) | Glucose (mg/dL)
-----------|------------------|-------------|----------------
2025-10-03 | 15.0             | 31.0        | 75
```

**Output (long):**
```
date       | marker   | value | unit  
-----------|----------|-------|-------
2025-10-03 | Ferritin | 15.0  | ng/mL
2025-10-03 | HDL      | 31.0  | mg/dL
2025-10-03 | Glucose  | 75.0  | mg/dL
```

### Protocol History: Manual Entry or CSV Import

**Two input methods:**

**Method 1: Manual CSV**
```csv
start_date,end_date,compound_name,dosage,dosage_unit,frequency,compound_type,reason,notes
2025-10-17,,Ferrous Sulfate,200,mg,EOD,Supplement,Iron repletion,Take with Vitamin C
2025-10-17,,Niacin,1500,mg,Daily,Supplement,HDL recovery,Extended release
2024-08-01,2025-10-11,Anavar,35,mg,Daily,AAS,Cycle,"Ran 8 weeks"
```

**Method 2: Structured YAML** (for recovery plan import)
```yaml
protocols:
  - compound_name: Ferrous Sulfate
    start_date: 2025-10-17
    dosage: 200
    dosage_unit: mg
    frequency: EOD
    compound_type: Supplement
    reason: Iron repletion
    notes: With 1000mg Vitamin C
    
  - compound_name: Niacin
    start_date: 2025-10-17
    dosage: 1500
    dosage_unit: mg
    frequency: Daily
    compound_type: Supplement
    reason: HDL recovery
```

---

## Implementation Files

### File Structure
```
src/pipeline/
  common/
    schema.py             # Add labs_schema, protocol_history_schema
    labs_normalization.py # NEW: Column name parsing, unit extraction
  ingest/
    labs_excel.py         # NEW: Excel → long format → parquet
    protocol_csv.py       # NEW: CSV/YAML → parquet
  paths.py                # Add LABS_PATH, PROTOCOL_HISTORY_PATH

scripts/
  import_recovery_plan_protocol.py  # NEW: Extract from markdown → protocol_history

Data/
  Raw/
    labs/
      AllLabsv8.xlsx      # Master spreadsheet (sync from Drive)
    protocol/
      supplements.csv     # Manual entry CSV
      recovery_plan.yaml  # Extracted from Iron_Depletion doc
  Parquet/
    labs/                 # year=2025/
    protocol_history/     # year=2025/
```

---

## Query Examples

### Labs Queries

**Ferritin trend:**
```python
import pyarrow.parquet as pq

labs = pq.read_table(
    'Data/Parquet/labs',
    filters=[('marker', '=', 'Ferritin')]
).to_pandas()

print(labs[['date', 'value', 'unit', 'flag']].sort_values('date'))
```

**Multi-marker analysis (iron panel):**
```python
iron_markers = ['Ferritin', 'Hemoglobin', 'Hematocrit', 'MCV', 'MCHC']
labs = pq.read_table(
    'Data/Parquet/labs',
    filters=[('marker', 'in', iron_markers)]
).to_pandas()

pivot = labs.pivot(index='date', columns='marker', values='value')
print(pivot)
```

**Flag all abnormal results:**
```python
abnormal = pq.read_table(
    'Data/Parquet/labs',
    filters=[('flag', 'in', ['L', 'H'])]
).to_pandas()

print(abnormal[['date', 'marker', 'value', 'flag', 'ref_low', 'ref_high']])
```

### Protocol History Queries

**Current protocols:**
```python
protocol = pq.read_table(
    'Data/Parquet/protocol_history'
).to_pandas()

current = protocol[protocol['end_date'].isna()]
print(current[['compound_name', 'dosage', 'dosage_unit', 'frequency', 'start_date']])
```

**Timeline of AAS cycles:**
```python
cycles = protocol[protocol['compound_type'] == 'AAS'].sort_values('start_date')
print(cycles[['start_date', 'end_date', 'compound_name', 'dosage']])
```

**Join labs with protocol (what was I taking when HDL crashed?):**
```python
hdl = labs[labs['marker'] == 'HDL'].copy()
hdl['date'] = pd.to_datetime(hdl['date'])

# Find active protocols at each lab date
for idx, row in hdl.iterrows():
    active = protocol[
        (protocol['start_date'] <= row['date']) &
        ((protocol['end_date'].isna()) | (protocol['end_date'] >= row['date']))
    ]
    print(f"\n{row['date']}: HDL={row['value']}")
    print(active[['compound_name', 'dosage', 'frequency']])
```

---

## Data Quality Handling

### Labs Special Values
```python
# Handle: "<10", ">1500", "Negative", etc.
def parse_lab_value(raw_value):
    if pd.isna(raw_value):
        return None, None, None
    
    val_str = str(raw_value).strip()
    
    # Handle <value
    if val_str.startswith('<'):
        num = float(val_str[1:])
        return num, val_str, 'L'
    
    # Handle >value  
    if val_str.startswith('>'):
        num = float(val_str[1:])
        return num, val_str, 'H'
    
    # Handle numeric
    try:
        return float(val_str), None, None
    except ValueError:
        return None, val_str, None
```

### Reference Ranges
Create a reference ranges config file:

```python
# src/pipeline/common/lab_reference_ranges.py
REFERENCE_RANGES = {
    'Ferritin': {'unit': 'ng/mL', 'low': 30.0, 'high': 400.0},
    'Glucose': {'unit': 'mg/dL', 'low': 70.0, 'high': 100.0},
    'HDL': {'unit': 'mg/dL', 'low': 40.0, 'high': None},  # No upper limit
    'Testosterone': {'unit': 'ng/dL', 'low': 264.0, 'high': 916.0},
    # ... add more as needed
}
```

---

## Next Steps

### Priority Order

1. **Labs ingestion** (highest value - you have years of data)
   - Create labs_normalization.py
   - Create labs_excel.py
   - Test on AllLabsv8.xlsx
   - Backfill all historical data

2. **Protocol history setup** (enables correlation analysis)
   - Create protocol_csv.py
   - Manual entry of current supplements (iron, niacin, etc.)
   - Extract from Iron Recovery Plan markdown

3. **Integration** (connect the dots)
   - Query examples in notebook
   - Correlation analysis (protocol changes → lab impacts)
   - Dashboard prep (identify key metrics to track)

### Implementation Sequence

**Session 1: Labs (this session?)**
- Add labs_schema to schema.py
- Create labs_normalization.py (unit extraction, value parsing)
- Create labs_excel.py (melt + transform + write)
- Test and ingest AllLabsv8.xlsx

**Session 2: Protocol History**
- Add protocol_history_schema
- Create protocol_csv.py
- Manually create supplements.csv
- Extract from recovery plan markdown

**Session 3: Analysis**
- Example queries
- Correlation notebook
- Identify dashboard metrics

Want to start with labs ingestion now?
