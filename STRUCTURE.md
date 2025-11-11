# HDP Documentation Structure

```
hdp-docs/
│
├── README.md                          # Start here - main entry point
├── QUICK_REFERENCE.md                 # Task-based navigation
├── DELIVERY_SUMMARY.md                # What's included and how to use
│
├── docs/                              # LIVING DOCUMENTATION (Update these)
│   ├── Architecture.md                # System design, data flow, principles
│   ├── DataSources.md                 # Ingestion details for all 6 sources  
│   ├── Schema.md                      # All 35+ table definitions
│   ├── TimestampHandling.md           # Strategy A vs B, timezone handling
│   ├── StorageAndQuery.md             # DuckDB patterns, Parquet optimization
│   ├── Deployment.md                  # Docker, automation, multi-machine
│   │
│   ├── archive/                       # COMPREHENSIVE REFERENCES
│   │   └── HealthDataPipelineDesign_v2.3.md  # Exhaustive algorithms
│   │
│   └── decisions/                     # DECISION LOGS (Why we did X)
│       ├── PartitioningStrategy.md    # Monthly > daily, PyArrow limits
│       ├── TimezoneStrategy.md        # Strategy A vs B trade-offs
│       ├── DeduplicationApproaches.md # Composite keys, hash generation
│       └── LabsStandardization.md     # Canonical biomarker naming
```

## File Sizes

| Document | Size | Purpose |
|----------|------|---------|
| **Living Docs** |
| Architecture.md | 6.5 KB | High-level design |
| DataSources.md | 11 KB | Source ingestion details |
| Schema.md | 13.5 KB | Table definitions |
| TimestampHandling.md | 9.5 KB | Timezone strategies |
| StorageAndQuery.md | 11 KB | Query optimization |
| Deployment.md | 13 KB | Automation and deployment |
| **Archive** |
| HealthDataPipelineDesign_v2.3.md | 25 KB | Comprehensive algorithms |
| **Decision Logs** |
| PartitioningStrategy.md | 4.5 KB | Monthly partitioning rationale |
| TimezoneStrategy.md | 8 KB | Strategy A vs B decision |
| DeduplicationApproaches.md | 7 KB | Deduplication keys |
| LabsStandardization.md | 7.5 KB | Biomarker canonical naming |
| **Navigation** |
| README.md | 4 KB | Main entry point |
| QUICK_REFERENCE.md | 4 KB | Task-based index |
| DELIVERY_SUMMARY.md | 6 KB | Implementation summary |

**Total:** ~100 KB across 12 markdown files

## Usage Patterns

### I want to...
**Understand the system** → Start with `README.md` → Read `docs/Architecture.md`

**Ingest new data** → `docs/DataSources.md` → Find your source section

**Query data** → `docs/StorageAndQuery.md` → Find query pattern

**Deploy automation** → `docs/Deployment.md` → Pick deployment mode

**Debug timestamps** → `docs/TimestampHandling.md` → Check edge cases

**Understand a decision** → `docs/decisions/` → Read relevant log

**Deep dive on algorithms** → `docs/archive/HealthDataPipelineDesign_v2.3.md`

### I'm making changes...
**Adding data source** → Update `DataSources.md` + `Schema.md`

**Changing architecture** → Read decision logs first → Update living docs → Write new decision log

**Fixing bugs** → Check relevant decision log for context

## Maintenance

✅ **DO:**
- Update living docs when behavior changes
- Write decision logs for significant choices
- Archive old versions with date suffix
- Keep README current

❌ **DON'T:**
- Delete decision logs (even if decision changes, keep historical context)
- Let living docs get stale
- Skip writing decision logs for "obvious" choices (they won't be obvious in 6 months)

## Navigation Helpers

**By Task:**
- See `QUICK_REFERENCE.md` for "I need to..." navigation

**By Topic:**
- Architecture: `docs/Architecture.md`
- Specific Source: `docs/DataSources.md` + search
- Schema Question: `docs/Schema.md` + search
- Historical Context: `docs/decisions/` + browse

**By Depth:**
- Overview: `README.md`
- Working Knowledge: Living docs in `docs/`
- Deep Dive: Archive docs
- Context: Decision logs
