# Health Data Pipeline — Design (Source of Truth)

**Schema Reference**
The canonical storage schema is maintained in `HealthDataPipelineSchema.md`.

## Algorithms
- Column normalization: explicit HAE→canonical mappings + snake_case fallback
- DST-safe UTC conversion using previous-UTC disambiguation
- Idempotent partitioned writes with overwrite_or_ignore
- Lenient daily aggregation (only when inputs exist)

## Validation
- Temporal monotonicity, duplicate detection, DST day counts (fixtures later)

## Paths
- Inputs: Data/Raw/CSV/HealthAutoExport-*.csv
- Outputs: Data/Parquet/{minute_facts,daily_summary}/...
- Archive/Error routing


### Daily Summary (wide)
- Write row if at least one metric exists; skip only if all missing.
- Units: imperial for hydration (`water_fl_oz` INT).

---

## Daily Summary & Header Crosswalk (Implementation Policy)

**Scope:** Behavioral rules only; the actual column renames live in code (`src/pipeline/ingest/csv_delta.py`). This keeps the README high-level.

### Canonical crosswalk intent (HAE → pipeline)
- Maintain a simple dict-based crosswalk in code (`RENAME_MAP`). Only map fields used by the pipeline.
- Examples (non-exhaustive):  
  - `Active Energy (kcal)` → `active_energy_kcal`  
  - `Resting Energy (kcal)` → `basal_energy_kcal`  
  - `Walking + Running Distance (mi)` / `Distance (mi)` → `distance_mi`  
  - `Steps (count)` → `steps`  
  - Sleep totals → `sleep_minutes_asleep`, `sleep_minutes_in_bed`  
  - Body metrics (imperial) → `weight_lb`, `body_fat_pct`, `temperature_degF`

> Hydration is detected separately from any header containing “water” and normalized to `water_fl_oz` (imperial). We do **not** require a specific header name for water.

### Daily summary dataset (behavioral rules)
- **Grain:** 1 row per `date × source` (wide).
- **Write rule:** Write the row if **any** daily metric exists for that date/source; **skip** only if *all* metrics are missing.
- **Derived (guarded):**
  - `energy_total_kcal = active_energy_kcal + basal_energy_kcal` (if both present)
  - `sleep_efficiency_pct = 100 * sleep_minutes_asleep / sleep_minutes_in_bed` (if both present, denom > 0)
  - `net_energy_kcal = calories_kcal - energy_total_kcal` (if both present)
- **Hydration:** `water_fl_oz` (**INT**, U.S. imperial). Conversions handled from `ml`/`L`; values outside ~0..338 fl oz are set NULL.

### Operational logging (ingest)
- **Minutes (per file):**  
  `minutes: <file> → rows=<n>, window=<min_ts>..<max_ts>, non_null_top=[metric:count,...]`
- **Daily summary:**  
  - Written: `daily_summary: rows=<n>, dates=<min>..<max>, sample={steps=..., energy_total_kcal=..., water_fl_oz=...}`  
  - Skipped: `OK: <file> → Data/Parquet/daily_summary (daily_summary skipped: no metrics)`
- **Header crosswalk audit (optional):**  
  `header-xwalk: unmapped=<k> [<examples...>]` — use this to identify any headers that should be mapped next.

_Last updated: 2025-10-25_
