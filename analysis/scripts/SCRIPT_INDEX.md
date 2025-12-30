# Analysis Scripts Index

Quick reference for all analysis scripts. Run from repo root with `poetry run python analysis/scripts/<script>.py`

---

## Workout Analysis

### `analyze_interval_session.py` - **30/30 Interval Analysis with Trending**
Comprehensive analysis of Concept2 30/30 interval sessions with history tracking.

```bash
# Analyze most recent session
poetry run python analysis/scripts/analyze_interval_session.py

# Analyze specific workout
poetry run python analysis/scripts/analyze_interval_session.py --workout-id 109902972

# List all interval sessions
poetry run python analysis/scripts/analyze_interval_session.py --list

# Show trends across sessions
poetry run python analysis/scripts/analyze_interval_session.py --trend
```

**Outputs:**
- Per-interval power/HR breakdown
- Recovery analysis (HR drop during easy intervals)
- Cardiac efficiency metrics
- Recommendations for next session
- Visualization: `analysis/outputs/interval_session_<id>.png`
- History: `analysis/outputs/interval_session_history.parquet`

---

### `analyze_recent_30_30.py` - Quick 30/30 Analysis (Legacy)
Basic analysis of most recent 30/30 session. Use `analyze_interval_session.py` instead for better accuracy.

```bash
poetry run python analysis/scripts/analyze_recent_30_30.py
```

---

### `analyze_step_test.py` - **Lactate Step Test for Zone 2**
Analyze lactate step tests from Concept2 BikeErg to find Zone 2 ceiling.

```bash
# Analyze most recent BikeErg workout
poetry run python analysis/scripts/analyze_step_test.py

# Analyze specific date
poetry run python analysis/scripts/analyze_step_test.py --date 2025-12-28

# With custom max HR
poetry run python analysis/scripts/analyze_step_test.py --max-hr 155

# Override lactate readings (if not in notes)
poetry run python analysis/scripts/analyze_step_test.py --lactate "1.2,1.4,1.8,2.1"

# Adjust warmup detection (default 8 min)
poetry run python analysis/scripts/analyze_step_test.py --warmup 10
```

**Assumes:**
- Free ride workout with pauses (dips in power) for lactate readings
- Lactate readings in workout notes field, comma-delimited
- Readings align with detected steps in order

**Outputs:**
- Per-step power/HR/lactate table
- Zone 2 ceiling detection (where lactate crosses 2.0 mmol/L)
- Training recommendations
- Follow-up test protocol if ceiling not reached

---

### `analyze_max_hr_workout.py` - Max HR Test Analysis
Analyze max HR test workouts.

```bash
poetry run python analysis/scripts/analyze_max_hr_workout.py
```

---

### `analyze_max_hr_test.py` - Max HR Test (Alternate)
Another max HR analysis script.

```bash
poetry run python analysis/scripts/analyze_max_hr_test.py
```

---

## Weekly Training Coach (A-Series)

### `calculate_progression.py` - **A1: Progression Calculator**
Calculate training progressions based on recent performance.

```bash
poetry run python analysis/scripts/calculate_progression.py
```

---

### `calculate_training_mode.py` - **A2: Recovery-Based Training Mode**
Determine training mode based on recovery metrics.

```bash
poetry run python analysis/scripts/calculate_training_mode.py
```

---

### `generate_weekly_report.py` - **A3: Weekly Report Generator**
Generate comprehensive weekly training report.

```bash
poetry run python analysis/scripts/generate_weekly_report.py
```

---

## Sleep & Recovery

### `calculate_sleep_metrics.py` - **D3: Sleep Debt Calculator**
Calculate sleep debt and recovery metrics.

```bash
poetry run python analysis/scripts/calculate_sleep_metrics.py
```

---

### `run_recovery_analysis.py` - Recovery Analysis
Analyze recovery trends.

```bash
poetry run python analysis/scripts/run_recovery_analysis.py
```

---

## Heart Rate Analysis

### `run_hr_analysis.py` - HR Baseline Analysis
Analyze resting HR trends and recovery.

```bash
poetry run python analysis/scripts/run_hr_analysis.py
poetry run python analysis/scripts/run_hr_analysis.py --output analysis/outputs/recovery_weekly.csv
```

---

## Correlations & Timelines

### `correlations.py` - Cross-Metric Correlations
Analyze correlations between different health metrics.

```bash
poetry run python analysis/scripts/correlations.py
```

---

### `medical_timeline.py` - Medical Event Timeline
Generate timeline of medical events and markers.

```bash
poetry run python analysis/scripts/medical_timeline.py
```

---

### `create_comprehensive_timeline.py` - Full Health Timeline
Create comprehensive timeline visualization.

```bash
poetry run python analysis/scripts/create_comprehensive_timeline.py
```

---

## Makefile Shortcuts

Some scripts have Makefile shortcuts:
```bash
make analysis.hr          # Run HR analysis
make analysis.weekly      # Generate weekly report (if configured)
```

---

## Adding New Scripts

When adding a new script:
1. Follow naming: `{action}_{subject}.py` (e.g., `analyze_lactate_curve.py`)
2. Add entry to this index with:
   - Purpose
   - Usage examples
   - Output files
3. Consider adding Makefile shortcut for frequent use
