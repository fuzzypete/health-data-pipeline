# HDP Documentation - Quick Reference

## I Need To...

### Get Started
→ [README.md](README.md) - Start here for overview and setup

### Understand the System
→ [docs/Architecture.md](docs/Architecture.md) - High-level design and data flow
→ [docs/DataSources.md](docs/DataSources.md) - How each source works

### Work with Data
→ [docs/Schema.md](docs/Schema.md) - All table definitions and keys
→ [docs/StorageAndQuery.md](docs/StorageAndQuery.md) - DuckDB queries and Parquet optimization

### Deploy/Automate
→ [docs/Deployment.md](docs/Deployment.md) - Docker, scheduling, multi-machine setup

### Understand Timestamps
→ [docs/TimestampHandling.md](docs/TimestampHandling.md) - Strategy A vs B, timezone handling

## I'm Changing Something...

### Adding a New Data Source
1. Read: [docs/DataSources.md](docs/DataSources.md) - "Adding New Sources" section
2. Define schema: [docs/Schema.md](docs/Schema.md) - Follow existing patterns
3. Check: [docs/decisions/](docs/decisions/) - Review relevant decisions

### Modifying Core Architecture
1. **First:** Read decision logs to understand why things work this way
2. Update affected living docs
3. Consider writing new decision log for significant changes

### Debugging Data Quality Issues
→ [docs/decisions/DeduplicationApproaches.md](docs/decisions/DeduplicationApproaches.md)
→ [docs/decisions/TimezoneStrategy.md](docs/decisions/TimezoneStrategy.md)

## Deep Dives

### Comprehensive References (Archive)
→ [docs/archive/HealthDataPipelineDesign_v2.3.md](docs/archive/HealthDataPipelineDesign_v2.3.md) - Exhaustive design document with all algorithms

### Decision Rationale (Why We Did X)
→ [docs/decisions/PartitioningStrategy.md](docs/decisions/PartitioningStrategy.md) - Why monthly > daily
→ [docs/decisions/TimezoneStrategy.md](docs/decisions/TimezoneStrategy.md) - Strategy A vs B trade-offs
→ [docs/decisions/DeduplicationApproaches.md](docs/decisions/DeduplicationApproaches.md) - Deduplication keys per table
→ [docs/decisions/LabsStandardization.md](docs/decisions/LabsStandardization.md) - Biomarker canonical naming

## Documentation Maintenance

### Living Docs (Update These)
Update when behavior changes:
- [docs/Architecture.md](docs/Architecture.md)
- [docs/DataSources.md](docs/DataSources.md)
- [docs/Schema.md](docs/Schema.md)
- [docs/TimestampHandling.md](docs/TimestampHandling.md)
- [docs/StorageAndQuery.md](docs/StorageAndQuery.md)
- [docs/Deployment.md](docs/Deployment.md)

### Decision Logs (Add New Ones)
Write decision log when:
- Making significant architectural choice
- Choosing between multiple approaches
- Accepting specific trade-offs
- Future-you will wonder "why did we do it this way?"

Template:
```markdown
# Decision: [Title]
**Date:** YYYY-MM-DD
**Status:** Proposed | Implemented | Deprecated
**Impact:** Low | Medium | High

## Context
[What's the situation?]

## Problem
[What are we trying to solve?]

## Options Considered
[What alternatives did we evaluate?]

## Decision
[What did we choose and why?]

## Results
[How did it work out?]

## Trade-offs Accepted
[What compromises did we make?]
```

### Archive (Preserve These)
Don't delete comprehensive docs - move old versions here with date suffix:
- `archive/HealthDataPipelineDesign_v2.3.md`
- `archive/Architecture_v2.2_20241101.md`

## Common Tasks

| Task | Document |
|------|----------|
| Add Concept2 workout | [DataSources.md](docs/DataSources.md#concept2) |
| Query training load | [StorageAndQuery.md](docs/StorageAndQuery.md#common-query-patterns) |
| Fix duplicate data | [decisions/DeduplicationApproaches.md](docs/decisions/DeduplicationApproaches.md) |
| Set up automation | [Deployment.md](docs/Deployment.md#automation) |
| Add new biomarker | [decisions/LabsStandardization.md](docs/decisions/LabsStandardization.md#handling-new-biomarkers) |
| Troubleshoot timestamps | [TimestampHandling.md](docs/TimestampHandling.md#edge-cases--solutions) |
| Optimize queries | [StorageAndQuery.md](docs/StorageAndQuery.md#query-optimization) |

---

**Last Updated:** 2025-11-10  
**Maintained By:** Peter Kahaian
