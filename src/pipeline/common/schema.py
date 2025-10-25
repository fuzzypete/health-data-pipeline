# src/pipeline/common/schema.py
from __future__ import annotations

import pyarrow as pa

SOURCES = {"HAE_CSV", "HAE_JSON", "Concept2"}

# Base fields for wide minute_facts (metric columns are dynamic)
minute_facts_base = pa.schema([
    pa.field("timestamp_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("timestamp_local", pa.timestamp("us"), nullable=True),
    pa.field("tz_name", pa.string(), nullable=True),
    pa.field("source", pa.string(), nullable=False),
    pa.field("ingest_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("ingest_run_id", pa.string(), nullable=True),
])
