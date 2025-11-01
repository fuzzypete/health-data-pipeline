# Health Data Pipeline - Concept2 Implementation Package

**Date:** 2025-11-01  
**Version:** 0.2.0

## What's Inside

This archive contains the complete Concept2 API ingestion implementation plus all common utilities.

### Directory Structure

```
.
├── src/pipeline/
│   ├── __init__.py
│   ├── paths.py
│   ├── common/
│   │   ├── __init__.py
│   │   ├── config.py          # Configuration management
│   │   ├── parquet_io.py      # Parquet I/O utilities
│   │   ├── schema.py          # PyArrow schemas (6 tables)
│   │   └── timestamps.py      # Strategy A/B timestamp handling
│   └── ingest/
│       └── concept2_api.py    # Concept2 API ingestion (NEW!)
│
├── docs/
│   ├── TimestampHandling.md                # Comprehensive timestamp spec
│   ├── HealthDataPipelineSchema.md         # Table schemas v2.0
│   ├── HealthDataPipelineArchitecture.md   # System architecture
│   ├── HealthDataPipelineDesign.md         # Design patterns
│   └── HDP_v2.0_Update_Summary.md          # What changed in v2.0
│
├── test_concept2.py           # Test suite for Concept2
├── Makefile                   # Updated with concept2 commands
├── config.yaml.template       # Configuration template
│
└── README files:
    ├── COMMON_UTILITIES_SUMMARY.md   # How to use common utilities
    ├── CONCEPT2_IMPLEMENTATION.md    # Concept2 implementation guide
    └── SETUP_MANUAL.md               # Manual setup instructions
```

## Quick Start

### 1. Extract Archive

```bash
cd ~/your-repo
tar -xzf hdp-concept2-implementation.tar.gz
```

### 2. Install Dependencies

```bash
poetry add pyyaml
```

### 3. Configure

```bash
# Copy template
cp config.yaml.template config.yaml

# Edit with your settings
nano config.yaml  # Add your Concept2 API token

# Add to .gitignore
echo "config.yaml" >> .gitignore
```

### 4. Test

```bash
# Test common utilities
poetry run python -c "from pipeline.common import get_config; print(get_config())"

# Test Concept2 connection
poetry run python test_concept2.py
```

### 5. Ingest Data

```bash
# Quick sync (10 workouts)
make ingest-concept2-recent

# Full sync (50 workouts)
make ingest-concept2
```

## What Changed

### Common Utilities (NEW)

**src/pipeline/common/**
- `timestamps.py` - Strategy A (assumed TZ) and Strategy B (rich TZ) implementations
- `config.py` - YAML configuration with environment variable overrides
- `parquet_io.py` - DRY functions for write/upsert/lineage
- `schema.py` - Complete PyArrow schemas for all 6 tables
- `paths.py` - Config-based path definitions

### Concept2 Ingestion (NEW)

**src/pipeline/ingest/concept2_api.py**
- `Concept2Client` - API wrapper with retry logic and rate limiting
- 3-tier ingestion: workouts → splits → strokes
- Strategy B timestamp handling (uses actual per-workout timezone)
- Upsert logic for safe re-ingestion
- CLI interface with argparse

### Documentation (UPDATED)

All docs updated with:
- Hybrid timestamp strategy (Strategy A vs B)
- Concept2 ingestion patterns
- JEFIT schema preparation
- Complete timestamp handling specification

## File Manifest

### Source Code (8 files)
- src/pipeline/__init__.py
- src/pipeline/paths.py
- src/pipeline/common/__init__.py
- src/pipeline/common/config.py (NEW - 196 lines)
- src/pipeline/common/parquet_io.py (NEW - 280 lines)
- src/pipeline/common/schema.py (UPDATED - 220 lines)
- src/pipeline/common/timestamps.py (NEW - 225 lines)
- src/pipeline/ingest/concept2_api.py (NEW - 530 lines)

### Documentation (8 files)
- docs/TimestampHandling.md (NEW - 640 lines)
- docs/HealthDataPipelineSchema.md (UPDATED)
- docs/HealthDataPipelineArchitecture.md (UPDATED)
- docs/HealthDataPipelineDesign.md (UPDATED)
- docs/HDP_v2.0_Update_Summary.md
- COMMON_UTILITIES_SUMMARY.md
- CONCEPT2_IMPLEMENTATION.md
- SETUP_MANUAL.md

### Configuration & Tools (3 files)
- config.yaml.template
- test_concept2.py (NEW - 200 lines)
- Makefile (UPDATED)

**Total:** ~2,500 lines of production code + ~3,000 lines of documentation

## Integration with Existing Code

### Files to Keep
These files already exist in your repo and should NOT be overwritten:
- `src/pipeline/ingest/csv_delta.py` (your HAE CSV ingestion)
- `src/pipeline/validate/checks.py` (your validation code)
- Any other custom code you've written

### Files to Merge
If these already exist, you may need to merge:
- `Makefile` - Add the concept2 targets to your existing Makefile
- `pyproject.toml` - Add pyyaml if not present

### Files to Create
These are new and can be copied directly:
- All files in `src/pipeline/common/`
- `src/pipeline/ingest/concept2_api.py`
- `test_concept2.py`
- `config.yaml` (from template)

## Configuration Required

### config.yaml

```yaml
timezone:
  default: "America/Los_Angeles"  # Your home timezone

api:
  concept2:
    token: "YOUR_CONCEPT2_API_TOKEN"  # Get from https://log.concept2.com/developers
```

### Environment Variables (Alternative)

```bash
export HDP_HOME_TIMEZONE="America/Los_Angeles"
export CONCEPT2_API_TOKEN="your_token_here"
```

## Usage Examples

### CLI Commands

```bash
# Ingest recent workouts
make ingest-concept2-recent

# Ingest with date range
poetry run python -m pipeline.ingest.concept2_api --from-date 2025-10-01 --to-date 2025-10-31

# Skip stroke data (faster)
poetry run python -m pipeline.ingest.concept2_api --no-strokes --limit 100

# Debug mode
poetry run python -m pipeline.ingest.concept2_api --debug
```

### Python API

```python
from pipeline.ingest.concept2_api import ingest_recent_workouts

# Ingest programmatically
counts = ingest_recent_workouts(limit=50, fetch_strokes=True)
print(f"Ingested: {counts['workouts']} workouts, {counts['strokes']} strokes")
```

## Testing

```bash
# Test Concept2 API connection
poetry run python test_concept2.py

# Test common utilities
poetry run python -c "from pipeline.common import apply_strategy_b; print('OK')"

# Run full test suite
poetry run pytest
```

## Data Output

After ingestion, data is written to:

```
Data/Parquet/
├── workouts/
│   └── date=2025-10-27/source=Concept2/*.parquet
├── cardio_splits/
│   └── date=2025-10-27/source=Concept2/*.parquet
└── cardio_strokes/
    └── date=2025-10-27/source=Concept2/*.parquet
```

## Troubleshooting

### "API token not configured"
→ Edit config.yaml or set CONCEPT2_API_TOKEN environment variable

### "ModuleNotFoundError: No module named 'yaml'"
→ Run: `poetry add pyyaml`

### "ModuleNotFoundError: No module named 'pipeline.common'"
→ Check directory structure matches what's shown above

### Import test fails
→ Run diagnostic: `poetry run python -c "import sys; print(sys.path)"`

## Next Steps

1. ✅ Extract archive
2. ✅ Install dependencies (`poetry add pyyaml`)
3. ✅ Configure API token in config.yaml
4. ✅ Test connection (`python test_concept2.py`)
5. ✅ Ingest data (`make ingest-concept2-recent`)
6. 🎯 Analyze your workout data!

## Support

See detailed guides:
- **SETUP_MANUAL.md** - Step-by-step setup
- **COMMON_UTILITIES_SUMMARY.md** - How to use common utilities
- **CONCEPT2_IMPLEMENTATION.md** - Complete Concept2 guide
- **docs/TimestampHandling.md** - Timestamp handling specification

## What's Next

Ready to implement:
- **JEFIT ingestion** - Resistance training sets
- **HAE Workout JSON** - Apple Health workout sessions
- **Enrichment queries** - Combine multiple data sources

---

**Questions?** Check the README files in this archive or review the inline code documentation.
