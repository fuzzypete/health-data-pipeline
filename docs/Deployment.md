# Deployment

**Version:** 2.3  
**Last Updated:** 2025-11-10

## Overview

HDP supports multiple deployment modes: local development, Docker containerization, and multi-machine workflows. This document covers setup, automation, and production considerations.

---

## Local Development (Current)

### System Requirements
- Python 3.11+
- 8GB+ RAM (16GB recommended)
- 50GB+ free disk space (varies with data volume)
- macOS, Linux, or WSL2

### Setup

**1. Clone Repository:**
```bash
git clone https://github.com/your-repo/health-data-pipeline.git
cd health-data-pipeline
```

**2. Install Dependencies:**
```bash
# Install Poetry if not present
curl -sSL https://install.python-poetry.org | python3 -

# Install project dependencies
poetry install --with dev

# Activate virtual environment
poetry shell
```

**3. Configure Credentials:**
```bash
# Copy template
cp config.example.yml config.yml

# Edit with your credentials
# - Concept2 OAuth tokens
# - Oura Personal Access Token
# - Google Drive API credentials (if using Drive integration)
vim config.yml
```

**4. Initialize Database:**
```bash
# Create directory structure
make init

# Initialize DuckDB
duckdb data/gold/hdp.duckdb < scripts/init_gold.sql
```

### Development Workflow

**Run Ingestion:**
```bash
# Ingest from all sources
make ingest-all

# Or individual sources
make ingest-hae
make ingest-concept2
make ingest-oura
make ingest-labs
```

**Query Data:**
```bash
# Interactive DuckDB shell
duckdb data/gold/hdp.duckdb

# Run analysis script
poetry run python scripts/analyze_training.py
```

**Run Tests:**
```bash
# Unit tests
make test

# Integration tests
make test-integration
```

---

## Docker Deployment

### Why Docker?

- **Consistency:** Same environment everywhere
- **Portability:** Run on any machine with Docker
- **Isolation:** Dependencies don't conflict with system
- **Automation:** Easy to schedule with cron/systemd

### Dockerfile

```dockerfile
# Dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install Python dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction

# Copy application code
COPY . .

# Set default command
CMD ["make", "ingest-all"]
```

### Build & Run

**Build Image:**
```bash
docker build -t hdp:latest .
```

**Run Container:**
```bash
# Mount data directory for persistence
docker run \
    -v $(pwd)/data:/app/data \
    -v $(pwd)/config.yml:/app/config.yml \
    hdp:latest
```

**Interactive Shell:**
```bash
docker run -it \
    -v $(pwd)/data:/app/data \
    -v $(pwd)/config.yml:/app/config.yml \
    hdp:latest \
    /bin/bash
```

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  hdp-ingest:
    build: .
    volumes:
      - ./data:/app/data
      - ./config.yml:/app/config.yml
    environment:
      - TZ=America/Los_Angeles
    command: make ingest-all
    
  hdp-analysis:
    build: .
    volumes:
      - ./data:/app/data
      - ./config.yml:/app/config.yml
    ports:
      - "8888:8888"  # Jupyter notebook
    command: jupyter notebook --ip=0.0.0.0 --no-browser
```

**Run Services:**
```bash
# Start all services
docker-compose up -d

# Run ingestion only
docker-compose run hdp-ingest

# Stop all services
docker-compose down
```

---

## Multi-Machine Deployment

### Architecture

```
[Development Machine (MacBook)]
    ↓ (code changes)
[Git Repository]
    ↓ (git pull)
[Bulk Ingestion Server (Linux)]
    ↓ (generate silver/gold Parquet)
[Shared Storage (NAS/Cloud)]
    ↓ (sync gold layer)
[Analysis Machine (MacBook)]
```

### Use Cases

**Bulk Ingestion Server:**
- Heavy lifting: Process years of historical data
- More RAM/CPU than laptop
- Always-on for scheduled ingestion

**Development/Analysis Machine:**
- Query gold layer
- Develop new scripts
- Run notebooks for analysis

### Setup: Bulk Ingestion Server

**1. Provision Linux Server:**
```bash
# Ubuntu 22.04 LTS recommended
# 16GB+ RAM, 100GB+ disk

ssh user@ingest-server
```

**2. Install Dependencies:**
```bash
# Install Docker
curl -fsSL https://get.docker.com | sh

# Clone repo
git clone https://github.com/your-repo/health-data-pipeline.git
cd health-data-pipeline

# Build Docker image
docker build -t hdp:latest .
```

**3. Configure Cron:**
```bash
# Edit crontab
crontab -e

# Add daily ingestion job (2am)
0 2 * * * cd /home/user/health-data-pipeline && docker run -v $(pwd)/data:/app/data -v $(pwd)/config.yml:/app/config.yml hdp:latest make ingest-all
```

**4. Sync to Shared Storage:**
```bash
# Rsync to NAS after ingestion
5 3 * * * rsync -avz /home/user/health-data-pipeline/data/gold/ user@nas:/hdp/gold/

# Or sync to cloud storage
5 3 * * * gsutil -m rsync -r /home/user/health-data-pipeline/data/gold/ gs://hdp-backup/gold/
```

### Setup: Analysis Machine

**1. Sync Gold Layer:**
```bash
# From NAS
rsync -avz user@nas:/hdp/gold/ ~/health-data-pipeline/data/gold/

# Or from cloud
gsutil -m rsync -r gs://hdp-backup/gold/ ~/health-data-pipeline/data/gold/

# Schedule hourly sync
0 * * * * rsync -avz user@nas:/hdp/gold/ ~/health-data-pipeline/data/gold/
```

**2. Query Locally:**
```bash
# Open DuckDB
duckdb ~/health-data-pipeline/data/gold/hdp.duckdb

# Gold layer is up-to-date with server ingestion
SELECT * FROM integrated_daily ORDER BY date_utc DESC LIMIT 10;
```

---

## Automation

### Scheduling Strategies

**Cron (Linux/Mac):**
```bash
# Edit crontab
crontab -e

# Daily ingestion at 2am
0 2 * * * cd /path/to/hdp && make ingest-all >> logs/cron.log 2>&1

# Weekly full refresh (Sundays at 3am)
0 3 * * 0 cd /path/to/hdp && make refresh-all >> logs/cron.log 2>&1

# Hourly Oura sync
0 * * * * cd /path/to/hdp && make ingest-oura >> logs/oura-cron.log 2>&1
```

**Systemd (Linux):**

`/etc/systemd/system/hdp-ingest.service`:
```ini
[Unit]
Description=Health Data Pipeline Ingestion
After=network.target

[Service]
Type=oneshot
User=hdp-user
WorkingDirectory=/home/hdp-user/health-data-pipeline
ExecStart=/usr/local/bin/make ingest-all
StandardOutput=append:/var/log/hdp/ingest.log
StandardError=append:/var/log/hdp/ingest.log

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/hdp-ingest.timer`:
```ini
[Unit]
Description=Run HDP Ingestion Daily

[Timer]
OnCalendar=daily
OnCalendar=02:00
Persistent=true

[Install]
WantedBy=timers.target
```

**Enable Timer:**
```bash
sudo systemctl enable hdp-ingest.timer
sudo systemctl start hdp-ingest.timer
sudo systemctl status hdp-ingest.timer
```

**Launchd (macOS):**

`~/Library/LaunchAgents/com.hdp.ingest.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hdp.ingest</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/make</string>
        <string>ingest-all</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/you/health-data-pipeline</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>2</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/you/health-data-pipeline/logs/ingest.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/you/health-data-pipeline/logs/ingest.log</string>
</dict>
</plist>
```

**Load Agent:**
```bash
launchctl load ~/Library/LaunchAgents/com.hdp.ingest.plist
launchctl start com.hdp.ingest  # Test run
```

---

## Monitoring & Alerts

### Log Aggregation

**Centralized Logging:**
```bash
# Redirect all output to logs/
make ingest-all 2>&1 | tee -a logs/$(date +%Y%m%d).log

# Rotate logs daily
0 0 * * * find /path/to/hdp/logs -name "*.log" -mtime +30 -delete
```

**Parse Logs for Errors:**
```bash
# Check for failures
grep -i "error\|failed" logs/20241110.log

# Count successful ingestions
grep "Ingestion complete" logs/20241110.log | wc -l
```

### Alerting

**Email Alerts on Failure:**
```bash
#!/bin/bash
# scripts/ingest_with_alert.sh

LOG_FILE="logs/$(date +%Y%m%d).log"

# Run ingestion
make ingest-all >> "$LOG_FILE" 2>&1

# Check exit code
if [ $? -ne 0 ]; then
    # Send email alert
    echo "HDP ingestion failed. Check $LOG_FILE" | \
        mail -s "HDP Alert: Ingestion Failed" you@example.com
fi
```

**Slack Webhook:**
```python
# scripts/notify_slack.py
import requests
import json

def notify_slack(message, webhook_url):
    payload = {
        "text": f"HDP: {message}",
        "username": "Health Data Pipeline"
    }
    requests.post(webhook_url, data=json.dumps(payload))

# Usage
if ingestion_failed:
    notify_slack(
        "⚠️ Ingestion failed - check logs",
        "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
    )
```

### Health Checks

**Check Data Freshness:**
```sql
-- scripts/check_freshness.sql
SELECT 
    'hae' as source,
    MAX(timestamp_utc) as last_data,
    current_timestamp - MAX(timestamp_utc) as lag
FROM hae_heart_rate_minute

UNION ALL

SELECT 
    'concept2',
    MAX(date_utc),
    current_timestamp - MAX(date_utc)
FROM concept2_workouts

UNION ALL

SELECT 
    'oura',
    MAX(date),
    current_timestamp - MAX(date)
FROM oura_readiness_daily;
```

**Alert if Stale:**
```bash
# Run freshness check
duckdb data/gold/hdp.duckdb < scripts/check_freshness.sql > /tmp/freshness.txt

# Alert if any source is >48h stale
if grep -q "2 days" /tmp/freshness.txt; then
    echo "Data is stale!" | mail -s "HDP Alert: Stale Data" you@example.com
fi
```

---

## Backup Strategy

### Local Backup

**Daily Incremental:**
```bash
# Backup silver layer (source of truth)
rsync -avz --delete \
    data/silver/ \
    /backup/hdp/silver/

# Backup gold database
cp data/gold/hdp.duckdb /backup/hdp/gold/hdp-$(date +%Y%m%d).duckdb
```

**Weekly Full Backup:**
```bash
# Tar entire data directory
tar -czf /backup/hdp/full-backup-$(date +%Y%m%d).tar.gz data/

# Keep only last 4 weeks
find /backup/hdp -name "full-backup-*.tar.gz" -mtime +28 -delete
```

### Cloud Backup

**Google Cloud Storage:**
```bash
# Sync to GCS bucket
gsutil -m rsync -r -d data/silver/ gs://hdp-backup/silver/
gsutil -m rsync -r -d data/gold/ gs://hdp-backup/gold/

# Lifecycle policy: Move to Nearline after 30 days
gcloud storage buckets update gs://hdp-backup \
    --lifecycle-policy lifecycle.json
```

`lifecycle.json`:
```json
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
        "condition": {"age": 30}
      }
    ]
  }
}
```

**AWS S3:**
```bash
# Sync to S3
aws s3 sync data/silver/ s3://hdp-backup/silver/ --delete
aws s3 sync data/gold/ s3://hdp-backup/gold/ --delete

# Lifecycle rule: Glacier after 90 days
aws s3api put-bucket-lifecycle-configuration \
    --bucket hdp-backup \
    --lifecycle-configuration file://lifecycle.json
```

---

## Security Considerations

### Credentials Management

**DO NOT commit credentials:**
```bash
# .gitignore
config.yml
*.key
*.pem
.env
```

**Use environment variables:**
```bash
# .env
export OURA_PAT="your_token"
export CONCEPT2_CLIENT_ID="your_client_id"
export CONCEPT2_CLIENT_SECRET="your_secret"

# Load in scripts
source .env
python scripts/ingest_oura.py
```

**Encrypt sensitive config:**
```bash
# Encrypt config file
gpg -c config.yml  # Creates config.yml.gpg

# Decrypt for use
gpg -d config.yml.gpg > config.yml
```

### Data Privacy

**Local-First Architecture:**
- All data stored locally by default
- No external services required
- You control where data lives

**Cloud Export (Optional):**
- Use private GCS/S3 buckets
- Enable encryption at rest
- Set IAM policies for access control

**Anonymization (For Sharing):**
```python
# scripts/anonymize_for_export.py
def anonymize_for_research(df):
    # Remove identifiable info
    df = df.drop(columns=['name', 'email', 'device_id'])
    
    # Shift dates to relative time
    df['days_since_start'] = (df['date'] - df['date'].min()).dt.days
    df = df.drop(columns=['date'])
    
    return df
```

---

## Troubleshooting

### Issue: "Permission denied" on Docker volume
```bash
# Fix permissions
sudo chown -R $(whoami):$(whoami) data/
```

### Issue: Cron job not running
```bash
# Check cron logs
grep CRON /var/log/syslog  # Ubuntu/Debian
grep CRON /var/log/cron     # CentOS/RHEL

# Verify environment
# Add to crontab:
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
```

### Issue: Out of disk space
```bash
# Check usage
df -h

# Clear old logs
find logs/ -name "*.log" -mtime +30 -delete

# Compress old Parquet files
find data/silver -name "*.parquet" -mtime +180 -exec gzip {} \;
```

---

## Next Steps

**Production Readiness Checklist:**
- [ ] Set up automated backups
- [ ] Configure monitoring/alerting
- [ ] Schedule daily ingestion
- [ ] Test disaster recovery
- [ ] Document runbooks for common issues
- [ ] Set up log rotation
- [ ] Enable HTTPS for any web interfaces
- [ ] Implement rate limiting for API calls

---

**See Also:**
- [Architecture.md](Architecture.md) - System design
- [StorageAndQuery.md](StorageAndQuery.md) - DuckDB and Parquet
- [DataSources.md](DataSources.md) - Source-specific setup
