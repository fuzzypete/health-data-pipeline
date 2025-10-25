# Health Data Pipeline — Architecture (Source of Truth)

- Phase 1 scope: HAE CSV minute facts + lenient daily summary
- UTC is canonical; local timestamp retained for display/time-of-day
- Parquet partitioning by date; idempotent writes
- Single docker image; Poetry environment
- Archive processed inputs; move failures to Error/


## Data Flow
HAE Daily CSV -> minute_facts (parquet)
HAE Daily CSV -> daily_summary (parquet, wide)

## Partitioning
- minute_facts: date=DATE(timestamp_utc), source
- daily_summary: date=date_utc, source
