# HDP v2.0 Documentation Update Summary

**Date:** 2025-11-01

## What Changed

All three core documentation files have been updated from v1.x to v2.0 to reflect the addition of cardio and resistance training data.

### Updated Files:
1. ✅ **HealthDataPipelineSchema.md** (v1.2 → v2.0)
2. ✅ **HealthDataPipelineArchitecture.md** (v1.0 → v2.0)
3. ✅ **HealthDataPipelineDesign.md** (v1.0 → v2.0)
4. ✅ **TimestampHandling.md** (NEW - v1.0) - Comprehensive timestamp strategy specification

---

## Schema Changes (v2.0)

### New Tables Added
- **cardio_splits** - Concept2 interval-level data (500m/time splits)
- **cardio_strokes** - Concept2 stroke-by-stroke data (~1,200 rows per 60-min workout)
- **resistance_sets** - JEFIT set-level data (weight, reps, rest)

### Modified Tables
- **workouts** - Expanded to universal session container
  - Added Concept2-specific fields (erg_type, drag_factor, stroke_rate, etc.)
  - Added resistance training fields (total_sets, total_reps, total_volume_lbs)
  - Now handles: Apple Health walks, Concept2 cardio, JEFIT strength, flexibility, etc.

### New Source Enum
- Added `JEFIT` to source enum (now: HAE_CSV, HAE_JSON, Concept2, JEFIT)

---

## Timestamp Handling (NEW)

### New Documentation: TimestampHandling.md
Created comprehensive specification for timestamp handling across the entire pipeline.

**Key Concepts:**
- **Hybrid Strategy:** Different approaches for different data quality levels
  - **Strategy A (Assumed Timezone):** HAE CSV/Daily JSON → assume home timezone consistently
  - **Strategy B (Rich Timezone):** Workouts, Concept2, JEFIT → use actual per-event timezone
- **Three-Timestamp Schema:** timestamp_utc (pipeline), timestamp_local (analysis), tz_name (context)
- **Travel Day Problem:** HAE exports lose per-event timezone, creating corruption on travel days
- **Trade-off:** Consistent wrong data (Strategy A) beats randomly corrupted data

**Implementation Updates:**
- Added `tz_source` field to all tables ('assumed' vs 'actual')
- Updated all core docs to reference TimestampHandling.md
- DST handling: ambiguous='infer', nonexistent='shift_forward'
- Parquet storage: naive timestamps + separate tz_name string

**Benefits:**
- Clean circadian analysis from consistent minute_facts data
- Perfect workout accuracy including travel days
- Can correct travel day data later with manual travel log
- Query patterns documented for both local and UTC time

---

## Architecture Changes (v2.0)

### New Data Flows
1. **Concept2 Logbook API** → 3-tier ingestion (session → splits → strokes)
2. **JEFIT CSV Export** → 2-tier ingestion (session → sets)

### Storage Structure
Added new partitioned datasets:
```
Data/Parquet/
  ├── cardio_splits/    # date=YYYY-MM-DD/source=Concept2/
  ├── cardio_strokes/   # date=YYYY-MM-DD/source=Concept2/
  └── resistance_sets/  # date=YYYY-MM-DD/source=JEFIT/
```

### New Ingestion Modules (to be implemented)
- `src/pipeline/ingest/concept2_api.py`
- `src/pipeline/ingest/jefit_csv.py`

---

## Design Changes (v2.0)

### New Algorithms

**Concept2 3-tier ingestion:**
1. Fetch workout summary → workouts table
2. If has_splits → fetch embedded splits → cardio_splits table
3. If has_strokes → fetch /strokes endpoint → cardio_strokes table

**JEFIT CSV parsing:**
1. Parse ROUTINES section → identify sessions
2. Parse MYLOGS section → extract sets
3. Aggregate session-level metrics → workouts table
4. Store individual sets → resistance_sets table

### New Validation Rules
- Workout validation: duration > 0, start <= end, etc.
- Resistance training: reps >= 0, weight >= 0, sequential set numbers
- Stroke data: cumulative time/distance monotonically increasing

---

## Implementation Roadmap

### Phase 1: Schema Implementation ✓ (Documented)
- [x] Schema spec written
- [x] Architecture documented
- [x] Design algorithms documented

### Phase 2: Code Implementation (Next Steps)

#### 2.1 Update Schema Definitions
```bash
# Update PyArrow schemas in code
src/pipeline/common/schema.py
  - Add workouts_schema (expanded)
  - Add cardio_splits_schema
  - Add cardio_strokes_schema
  - Add resistance_sets_schema
```

#### 2.2 Implement Concept2 Ingestion
```bash
# Create new module
src/pipeline/ingest/concept2_api.py
  - fetch_recent_workouts()
  - fetch_workout_detail()
  - fetch_strokes()
  - ingest_concept2_workout() # orchestrator
```

**Dependencies:**
- Concept2 API token (already have: Ph2KW2lznHKNQibKUWS3BvYQsCNSZqKGPn74tMcZ)
- requests library (already in pyproject.toml)

**Test data available:**
- API exploration output shows exact JSON structure
- User has RowErg and BikeErg data

#### 2.3 Implement JEFIT Ingestion
```bash
# Create new module
src/pipeline/ingest/jefit_csv.py
  - parse_jefit_csv()
  - extract_routines()
  - extract_mylogs()
  - create_workout_records()
  - create_set_records()
```

**Test data available:**
- `/mnt/project/PeterWickersham_jefit_20251030.csv`
- CSV structure already understood

#### 2.4 Update Makefile
```makefile
.PHONY: ingest-concept2
ingest-concept2:
	poetry run python -m pipeline.ingest.concept2_api

.PHONY: ingest-jefit
ingest-jefit:
	poetry run python -m pipeline.ingest.jefit_csv --input $(JEFIT_FILE)
```

#### 2.5 Add Tests
```bash
tests/
  ├── test_concept2_ingest.py
  └── test_jefit_ingest.py
```

### Phase 3: Enrichment & Analysis (Future)
- Join workouts with minute_facts for HR context
- Calculate volume periodization trends
- Power curve analysis (Concept2)
- Auto-generate compound tracker

---

## Storage Estimates

**Annual data volume (estimated user profile):**
- 100 walks/hikes: 100 rows (workouts only)
- 150 Concept2 workouts (40 min avg):
  - Workouts: 150 rows
  - Splits: 900 rows (~6 per workout)
  - Strokes: 180,000 rows (~1,200 per workout)
- 100 JEFIT sessions (8 exercises × 3 sets):
  - Workouts: 100 rows
  - Sets: 2,400 rows

**Total:** ~183,500 rows/year (98% are stroke data)

**Compressed size:** ~60-80 MB/year (parquet snappy compression)

---

## Next Actions

### Immediate (This Session)
1. **Copy updated docs to your repo:**
   ```bash
   cp /mnt/user-data/outputs/docs/*.md /path/to/health-pipeline/docs/
   ```

2. **Commit documentation:**
   ```bash
   git add docs/
   git commit -m "v2.0: Add cardio splits/strokes and resistance sets tables"
   ```

### Short-term (This Week)
3. **Update schema.py with PyArrow definitions**
4. **Implement Concept2 ingestion** (highest value - rich data available)
5. **Test with your actual API data**

### Medium-term (Next 2 Weeks)
6. **Implement JEFIT ingestion**
7. **Add validation tests**
8. **Update Makefile with new commands**

### Long-term (Next Month)
9. **Build enrichment queries**
10. **Create analysis dashboards**
11. **Auto-generate compound tracker**

---

## Questions to Consider

1. **Concept2 sync frequency:** Daily? Weekly? On-demand?
2. **JEFIT export frequency:** After each workout? Weekly batch?
3. **Historical backfill:** How far back to ingest? (API has limits)
4. **Stroke data storage:** Keep all strokes? Or sample/aggregate for older workouts?
5. **Analysis priorities:** What questions do you want to answer first?

---

## Resources

**Documentation:**
- [Schema v2.0](computer:///mnt/user-data/outputs/docs/HealthDataPipelineSchema.md)
- [Architecture v2.0](computer:///mnt/user-data/outputs/docs/HealthDataPipelineArchitecture.md)
- [Design v2.0](computer:///mnt/user-data/outputs/docs/HealthDataPipelineDesign.md)

**API Output:**
- Concept2 API exploration: output.txt (uploaded)

**Test Data:**
- JEFIT CSV: `/mnt/project/PeterWickersham_jefit_20251030.csv`
- Concept2 CSV: `/mnt/project/concept2-season-*.csv`

**Project Repo:**
- Health Data Pipeline (GitHub - configured in project)
