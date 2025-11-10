-- Create a logical namespace for views
CREATE SCHEMA IF NOT EXISTS lake;
PRAGMA timezone='UTC';

-- Read Parquet files, inferring Hive partitions
-- Use glob (**) to recursively find all .parquet files
-- and hive_partitioning=true to parse directory names as columns.

CREATE OR REPLACE VIEW lake.minute_facts AS
SELECT * FROM read_parquet('Data/Parquet/minute_facts/**/*.parquet', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.daily_summary AS
SELECT * FROM read_parquet('Data/Parquet/daily_summary/**/*.parquet', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.workouts AS
SELECT * FROM read_parquet('Data/Parquet/workouts/**/*.parquet', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.cardio_splits AS
SELECT * FROM read_parquet('Data/Parquet/cardio_splits/**/*.parquet', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.cardio_strokes AS
SELECT * FROM read_parquet('Data/Parquet/cardio_strokes/**/*.parquet', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.resistance_sets AS
SELECT * FROM read_parquet('Data/Parquet/resistance_sets/**/*.parquet', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.labs AS
SELECT * FROM read_parquet('Data/Parquet/labs/**/*.parquet', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.protocol_history AS
SELECT * FROM read_parquet('Data/Parquet/protocol_history/**/*.parquet', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.lactate AS
SELECT * FROM read_parquet('Data/Parquet/lactate/**/*.parquet', hive_partitioning=true);

CREATE OR REPLACE VIEW lake.oura_summary AS
SELECT * FROM read_parquet('Data/Parquet/oura_summary/**/*.parquet', hive_partitioning=true);