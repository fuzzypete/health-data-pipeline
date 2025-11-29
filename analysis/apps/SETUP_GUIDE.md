# Interactive Dashboards - Quick Setup Guide

## Installation (5 minutes)

```bash
cd ~/health-data-pipeline  # Or wherever your repo is

# 1. Add dependencies
poetry add plotly streamlit kaleido

# 2. Copy files to correct locations
cp /path/to/correlations_configured.py analysis/scripts/correlations.py
cp /path/to/dashboard_interactive.py analysis/apps/dashboard_interactive.py

# 3. Update Makefile (add targets from setup guide)

# 4. Test it works
poetry run python analysis/scripts/correlations.py --analysis iron
```

## Usage

### Option 1: Quick Correlation Analysis (Plotly)

**Run preset analyses:**
```bash
# Iron repletion analysis
make analysis.iron
# Opens browser with interactive chart
# Saves to analysis/outputs/iron_correlation_YYYYMMDD.html

# HGH → kidney analysis  
make analysis.kidney
# Opens browser with interactive chart
# Saves to analysis/outputs/kidney_correlation_YYYYMMDD.html
```

**Run custom analysis:**
```python
from analysis.scripts.correlations import HealthDashboard
from datetime import datetime

dashboard = HealthDashboard(
    start_date=datetime(2025, 1, 1),
    end_date=datetime.now()
)

metrics = [
    ('Ferritin', 'labs'),
    ('Total Meters', 'training'),
    ('HRV', 'recovery')
]

fig = dashboard.create_overlay_chart(metrics)
fig.show()  # Opens in browser
fig.write_html('analysis/outputs/my_analysis.html')
```

### Option 2: Full Dashboard (Streamlit)

**Launch interactive UI:**
```bash
make dashboard
# Or: poetry run streamlit run analysis/apps/dashboard_interactive.py
# Opens at http://localhost:8501
```

**Features:**
- Checkbox controls for adding/removing datasets
- Date range pickers
- Preset correlation analyses
- Export to HTML/PNG
- Data table views

## Available Metrics

**Labs:**
- Ferritin, Hemoglobin, Hematocrit
- Creatinine, eGFR
- HDL, LDL, Triglycerides
- Testosterone, Free Testosterone, SHBG
- And all others in your labs table

**Training:**
- Total Meters (Concept2)
- Total Volume (JEFIT)
- Average Watts (Concept2)

**Recovery:**
- HRV, Readiness Score, Sleep Score
- Resting HR

**Supplements:**
- Iron, Niacin, Fish Oil, HGH
- Any compound in protocol_history table

## Common Analyses

**1. Iron Repletion Efficacy:**
```bash
make analysis.iron
```
Overlays: Ferritin + Iron dose + Hemoglobin + Training volume

**2. HGH → Kidney Impact:**
```bash
make analysis.kidney
```
Overlays: Creatinine + eGFR + HGH dose

**3. Training Load vs Recovery:**
```python
dashboard = HealthDashboard()
metrics = [
    ('Total Meters', 'training'),
    ('HRV', 'recovery'),
    ('Readiness Score', 'recovery')
]
fig = dashboard.create_overlay_chart(metrics)
fig.show()
```

**4. Lipid Recovery Post-Cycle:**
```python
metrics = [
    ('HDL', 'labs'),
    ('LDL', 'labs'),
    ('Niacin', 'supplements'),
    ('Fish Oil', 'supplements')
]
```

## Troubleshooting

**"No data loaded for X":**
- Check metric name matches exactly (case-sensitive)
- Verify category is correct ('labs', 'training', 'recovery', 'supplements')
- Check date range includes data points
- Run query manually in DuckDB to verify data exists

**"Module not found":**
```bash
poetry install  # Reinstall dependencies
poetry shell    # Activate virtual environment
```

**"Parquet file not found":**
- Verify Data/Parquet/ directory exists
- Check config.yml has correct data_dir settings
- Run `make validate` to check Parquet files

## File Locations

```
health-data-pipeline/
├── analysis/
│   ├── scripts/
│   │   └── correlations.py          # Plotly correlation explorer
│   ├── apps/
│   │   └── dashboard_interactive.py # Streamlit full dashboard
│   └── outputs/
│       ├── iron_correlation_*.html  # Generated charts
│       └── kidney_correlation_*.html
└── Makefile                         # Updated with new targets
```

## Integration with Existing Workflow

**Static reports (existing):**
- Use for documentation
- PCP appointments
- Fixed analysis

**Interactive dashboards (new):**
- Use for exploration
- Discovering correlations
- Ad-hoc investigation

**Workflow:**
1. Use dashboard to discover correlation
2. Generate static chart for documentation
3. Add to reports or presentations

## Next Steps

**After setup:**
1. Run `make analysis.iron` to see your first correlation
2. Launch `make dashboard` to explore interactively
3. Create custom analyses for your specific questions
4. Export findings to share with PCP

**Add to .gitignore:**
```
analysis/outputs/*.html
analysis/outputs/*.png
analysis/outputs/*.csv
```

**Add to Makefile help:**
```makefile
help:
    @echo "Interactive Analysis:"
    @echo "  dashboard        - Launch interactive Streamlit dashboard"
    @echo "  analysis.iron    - Iron repletion correlation analysis"
    @echo "  analysis.kidney  - HGH → kidney correlation analysis"
```
