# Labs & Protocol History - Implementation Guide

## Overview

Two new tables to enable correlation analysis between labs, protocols, and performance:
1. **Labs** - Test results in normalized (long) format  
2. **Protocol History** - Timeline of supplements, medications, and compounds

---

## Part 1: Labs Implementation

### Files Created

1. **[labs_normalization.py](computer:///mnt/user-data/outputs/labs_normalization.py)** - Utilities for:
   - Extracting units from column names
   - Parsing special values (`<10`, `>1500`)
   - Reference ranges for 40+ common tests
   - Flag calculation (L/H/N)

2. **[labs_excel.py](computer:///mnt/user-data/outputs/labs_excel.py)** - Excel ingestion:
   - Wide → long format transformation
   - Handles AllLabsv8.xlsx structure
   - Generates lab_id hashes
   - CLI interface

### Schema Addition

**Add to `src/pipeline/common/schema.py`:**

```python
# ============================================================================
# Labs (normalized format)
# ============================================================================

labs_schema = pa.schema([
    # Lab visit metadata
    pa.field("lab_id", pa.string(), nullable=False),
    pa.field("date", pa.date32(), nullable=False),
    pa.field("lab_name", pa.string(), nullable=True),
    pa.field("reason", pa.string(), nullable=True),
    
    # Test result
    pa.field("marker", pa.string(), nullable=False),
    pa.field("value", pa.float64(), nullable=True),
    pa.field("value_text", pa.string(), nullable=True),
    pa.field("unit", pa.string(), nullable=True),
    
    # Reference ranges
    pa.field("ref_low", pa.float64(), nullable=True),
    pa.field("ref_high", pa.float64(), nullable=True),
    pa.field("flag", pa.string(), nullable=True),
    
    # Lineage
    pa.field("source", pa.string(), nullable=False),
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),
    
    # Hive partitioning
    pa.field("year", pa.string(), nullable=True),
])

# Update SCHEMAS dict:
SCHEMAS = {
    'minute_facts': minute_facts_base,
    'daily_summary': daily_summary_schema,
    'workouts': workouts_schema,
    'cardio_splits': cardio_splits_schema,
    'cardio_strokes': cardio_strokes_schema,
    'resistance_sets': resistance_sets_schema,
    'lactate': lactate_schema,
    'labs': labs_schema,  # ADD THIS
}
```

### Paths Addition

**Add to `src/pipeline/paths.py`:**

```python
LABS_PATH = DATA_DIR / "Parquet" / "labs"
```

### Makefile Target

**Add to `Makefile`:**

```makefile
.PHONY: ingest-labs
ingest-labs:
	@echo "Ingesting labs from Excel..."
	poetry run python -m pipeline.ingest.labs_excel --input Data/Raw/labs/AllLabsv8.xlsx
```

### Installation Steps

```bash
# 1. Copy files to project
cp /mnt/user-data/outputs/labs_normalization.py src/pipeline/common/
cp /mnt/user-data/outputs/labs_excel.py src/pipeline/ingest/

# 2. Make ingestion script executable
chmod +x src/pipeline/ingest/labs_excel.py

# 3. Create raw data directory
mkdir -p Data/Raw/labs

# 4. Copy your Excel file
cp /mnt/project/AllLabsv8.xlsx Data/Raw/labs/

# 5. Add schema to schema.py (see above)

# 6. Add path to paths.py (see above)

# 7. Run ingestion
make ingest-labs

# Expected output:
# Read 17 lab visits with 53 columns
# Found 50 test columns to process
# Created 437 lab result records from 17 visits
# ✅ Ingestion complete: 17 visits, 437 results
```

### Query Examples

**Ferritin trend:**
```python
import pyarrow.parquet as pq
import matplotlib.pyplot as plt

labs = pq.read_table(
    'Data/Parquet/labs',
    filters=[('marker', '=', 'Ferritin')]
).to_pandas()

labs = labs.sort_values('date')

plt.figure(figsize=(10, 6))
plt.plot(labs['date'], labs['value'], marker='o')
plt.axhline(y=30, color='r', linestyle='--', label='Normal low (30)')
plt.xlabel('Date')
plt.ylabel('Ferritin (ng/mL)')
plt.title('Ferritin Progression')
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

print(labs[['date', 'value', 'flag']])
```

**Iron panel (multi-marker):**
```python
iron_markers = ['Ferritin', 'Hemoglobin', 'Hematocrit', 'MCV', 'MCHC', 'RBC']

labs = pq.read_table(
    'Data/Parquet/labs',
    filters=[('marker', 'in', iron_markers)]
).to_pandas()

# Pivot to wide for analysis
pivot = labs.pivot(index='date', columns='marker', values='value')
pivot = pivot.sort_index()

print(pivot)
```

**All abnormal results:**
```python
abnormal = pq.read_table(
    'Data/Parquet/labs',
    filters=[('flag', 'in', ['L', 'H'])]
).to_pandas()

abnormal = abnormal.sort_values('date', ascending=False)

print(abnormal[['date', 'marker', 'value', 'unit', 'flag', 'ref_low', 'ref_high']])
```

**Lipid panel progression:**
```python
lipid_markers = ['HDL', 'LDL (calc)', 'Triglycerides', 'Cholesterol, Total', 'ApoB']

labs = pq.read_table(
    'Data/Parquet/labs',
    filters=[('marker', 'in', lipid_markers)]
).to_pandas()

pivot = labs.pivot(index='date', columns='marker', values='value')
pivot = pivot.sort_index()

# Plot
pivot.plot(figsize=(12, 6), marker='o')
plt.ylabel('mg/dL')
plt.title('Lipid Panel Trends')
plt.legend(bbox_to_anchor=(1.05, 1))
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()
```

---

## Part 2: Protocol History (Next Session)

### Schema Design

```python
protocol_history_schema = pa.schema([
    pa.field("protocol_id", pa.string(), nullable=False),
    pa.field("start_date", pa.date32(), nullable=False),
    pa.field("end_date", pa.date32(), nullable=True),
    
    pa.field("compound_name", pa.string(), nullable=False),
    pa.field("compound_type", pa.string(), nullable=True),
    pa.field("dosage", pa.float64(), nullable=True),
    pa.field("dosage_unit", pa.string(), nullable=True),
    pa.field("frequency", pa.string(), nullable=True),
    
    pa.field("reason", pa.string(), nullable=True),
    pa.field("notes", pa.string(), nullable=True),
    
    pa.field("source", pa.string(), nullable=False),
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),
    
    pa.field("year", pa.string(), nullable=True),
])
```

### Manual Entry Template

**Create `Data/Raw/protocol/current_protocol.csv`:**

```csv
start_date,end_date,compound_name,dosage,dosage_unit,frequency,compound_type,reason,notes
2025-10-17,,Ferrous Sulfate,200,mg,EOD,Supplement,Iron repletion,Take with 1000mg Vitamin C
2025-10-17,,Vitamin C,1000,mg,With iron doses,Supplement,Iron absorption,
2025-10-17,,Niacin,1500,mg,Daily,Supplement,HDL recovery,Extended release at bedtime
2025-10-17,,Fish Oil,3,caps,Daily,Supplement,Cardiovascular,High EPA formulation
2025-10-17,,Psyllium Husk,10,g,Daily,Supplement,Lipid management,
2025-10-17,,NAC,1200,mg,Daily,Supplement,Liver support post-cycle,
2025-10-17,,CoQ10,200,mg,Daily,Supplement,Cardiovascular,
2024-08-01,2025-10-11,Anavar,35,mg,Daily,AAS,Cycle,
2024-08-01,2025-10-11,Proviron,25,mg,Daily,AAS,Cycle,DHT derivative
2024-08-01,2025-10-11,Masteron P,200,mg/week,2x/week,AAS,Cycle,Injectable
```

### Implementation Files (Next Session)

Will create:
- `protocol_csv.py` - CSV/YAML ingestion
- `extract_recovery_plan_protocol.py` - Parse markdown → CSV
- Query examples for correlation analysis

---

## Correlation Analysis Examples (Future)

**When did HDL crash? What was I taking?**

```python
import pyarrow.parquet as pq
import pandas as pd

# Get HDL labs
hdl_labs = pq.read_table(
    'Data/Parquet/labs',
    filters=[('marker', '=', 'HDL')]
).to_pandas()

# Get protocol history
protocol = pq.read_table('Data/Parquet/protocol_history').to_pandas()

# Find active compounds at each lab date
for _, lab in hdl_labs.iterrows():
    lab_date = pd.to_datetime(lab['date'])
    
    active = protocol[
        (pd.to_datetime(protocol['start_date']) <= lab_date) &
        ((protocol['end_date'].isna()) | (pd.to_datetime(protocol['end_date']) >= lab_date))
    ]
    
    print(f"\n{lab['date']}: HDL = {lab['value']} mg/dL ({lab['flag']})")
    print("Active compounds:")
    for _, compound in active.iterrows():
        print(f"  - {compound['compound_name']}: {compound['dosage']}{compound['dosage_unit']} {compound['frequency']}")
```

**Ferritin response to iron supplementation:**

```python
# Get ferritin labs
ferritin = pq.read_table(
    'Data/Parquet/labs',
    filters=[('marker', '=', 'Ferritin')]
).to_pandas()

# Get iron supplementation periods
iron = protocol[protocol['compound_name'].str.contains('Ferrous|Iron', case=False, na=False)]

# Plot
plt.figure(figsize=(12, 6))

for _, period in iron.iterrows():
    plt.axvspan(
        pd.to_datetime(period['start_date']),
        pd.to_datetime(period['end_date']) if pd.notna(period['end_date']) else pd.Timestamp.now(),
        alpha=0.2, color='green', label='Iron supplementation'
    )

plt.plot(ferritin['date'], ferritin['value'], marker='o', linewidth=2)
plt.axhline(y=30, color='r', linestyle='--', label='Normal low')
plt.xlabel('Date')
plt.ylabel('Ferritin (ng/mL)')
plt.title('Ferritin Response to Iron Supplementation')
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()
```

---

## Storage Estimates

**Labs:**
- 17 visits × ~25 results/visit = ~425 rows currently
- ~4-8 visits/year × ~25 results = 100-200 rows/year
- Compressed size: <1 MB/year

**Protocol History:**
- ~10-20 active compounds at any time
- ~50-100 protocol changes/year
- Compressed size: <1 MB/year

---

## Summary

### Ready to Use (Labs):
- [labs_normalization.py](computer:///mnt/user-data/outputs/labs_normalization.py)
- [labs_excel.py](computer:///mnt/user-data/outputs/labs_excel.py)
- [LABS_PROTOCOL_DESIGN.md](computer:///mnt/user-data/outputs/LABS_PROTOCOL_DESIGN.md)

### Next Steps:
1. **Integrate labs files** into your project
2. **Add schema** to schema.py
3. **Run ingestion** on AllLabsv8.xlsx
4. **Test queries** (ferritin trend, iron panel, etc.)
5. **Build protocol_history** next session

### Expected Results:
```
✅ Ingestion complete:
   Lab visits: 17
   Results:    437 (from 50 different markers)
   
Date range: 2022-06-21 to 2025-10-03
Markers tracked: Ferritin, HDL, Testosterone, Glucose, etc.
```

Want to integrate and test the labs ingestion now, or move to protocol history design first?
