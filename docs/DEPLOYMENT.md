# HDP Dashboard Deployment Guide

Deploy the HDP Dashboard to Streamlit Community Cloud (free tier).

## Prerequisites

- GitHub account
- Streamlit Community Cloud account (https://share.streamlit.io)

## Data Export

The dashboard needs a subset of parquet data committed to the repo. The full dataset (~235MB) is too large and contains granular data not needed for the dashboard.

### Export Data

```bash
# Export last 12 months of data (~0.2MB)
poetry run python scripts/export_for_deploy.py --months 12

# Or export all time (~12MB without minute-level data)
poetry run python scripts/export_for_deploy.py
```

This creates `data/deploy/` with these tables:
- workouts
- cardio_splits
- resistance_sets
- oura_summary
- labs
- lactate
- protocol_history

### Excluded Tables
- `minute_facts` (152MB) - minute-level heart rate, not used by dashboard
- `cardio_strokes` (19MB) - per-stroke data, only aggregates used
- `daily_summary` (53MB) - optional, add with `--include-daily-summary`

## Deployment Steps

### 1. Commit Data & Push

```bash
git add data/deploy/
git add requirements.txt
git add .streamlit/
git commit -m "Add dashboard deployment files"
git push origin master
```

### 2. Deploy on Streamlit Cloud

1. Go to https://share.streamlit.io
2. Click "New app"
3. Configure:
   - **Repository:** `pwickersham/health-data-pipeline` (or your fork)
   - **Branch:** `master`
   - **Main file path:** `analysis/apps/hdp_dashboard.py`
4. Click "Deploy"

### 3. Configure Password (Required)

1. In Streamlit Cloud, go to your app settings
2. Click "Secrets"
3. Add:
   ```toml
   password = "your-secure-password"
   ```
4. Click "Save"
5. Reboot the app

## Local Testing

Test the deployed data path locally:

```bash
# The dashboard auto-detects data/deploy/ if it exists
streamlit run analysis/apps/hdp_dashboard.py
```

Test with password protection:

```bash
# Create local secrets file
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit .streamlit/secrets.toml with your test password
streamlit run analysis/apps/hdp_dashboard.py
```

## Updating Data

When you want to refresh the deployed data:

```bash
# Re-export
poetry run python scripts/export_for_deploy.py --months 12

# Commit and push
git add data/deploy/
git commit -m "Update dashboard data"
git push

# Streamlit Cloud will auto-redeploy
```

## Troubleshooting

### App won't start
- Check Streamlit Cloud logs for errors
- Verify `requirements.txt` has all dependencies
- Ensure `data/deploy/` was committed (check GitHub)

### "No data" in charts
- Verify parquet files exist in `data/deploy/`
- Check date ranges in the sidebar

### Password not working
- Verify secrets are configured in Streamlit Cloud settings
- Secret key must be exactly `password`

## File Structure

```
health-data-pipeline/
├── analysis/apps/
│   ├── hdp_dashboard.py      # Main app
│   ├── components/           # UI components
│   └── utils/
│       ├── queries.py        # DuckDB queries (auto-detects data path)
│       └── constants.py
├── data/deploy/              # Committed data subset for cloud
├── requirements.txt          # Streamlit Cloud dependencies
├── .streamlit/
│   ├── config.toml           # Theme config
│   └── secrets.toml.example  # Password template
└── scripts/
    └── export_for_deploy.py  # Data export script
```

## Limits

Streamlit Community Cloud free tier:
- 1GB RAM
- Limited CPU
- Public apps only (use password protection)
- Sleeps after inactivity (wakes on request)
