-- Create a logical namespace for views
CREATE SCHEMA IF NOT EXISTS lake;
PRAGMA timezone='UTC';

-- Read Parquet files, inferring Hive partitions
-- This is cleaner than globbing (Data/Parquet/table/**/*.parquet)
-- and lets DuckDB optimize queries based on the partition columns.

CREATE OR REPLACE VIEW lake.minute_facts AS
SELECT * FROM read_parquet('Data/Parquet/minute_facts/', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.daily_summary AS
SELECT * FROM read_parquet('Data/Parquet/daily_summary/', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.workouts AS
SELECT * FROM read_parquet('Data/Parquet/workouts/', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.cardio_splits AS
SELECT * FROM read_parquet('Data/Parquet/cardio_splits/', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.cardio_strokes AS
SELECT * FROM read_parquet('Data/Parquet/cardio_strokes/', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.resistance_sets AS
SELECT * FROM read_parquet('Data/Parquet/resistance_sets/', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.labs AS
SELECT * FROM read_parquet('Data/Parquet/labs/', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.protocol_history AS
SELECT * FROM read_parquet('Data/Parquet/protocol_history/', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.lactate AS
SELECT * FROM read_parquet('Data/Parquet/lactate/', hive_partitioning=true);