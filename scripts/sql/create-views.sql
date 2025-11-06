-- Create a logical namespace for views
CREATE SCHEMA IF NOT EXISTS lake;
PRAGMA timezone='UTC';

-- Core tables (Hive-partitioned Parquet under Data/Parquet/*)
CREATE OR REPLACE VIEW lake.minute_facts AS
SELECT * FROM read_parquet('Data/Parquet/minute_facts/**/*.parquet', union_by_name=true);

CREATE OR REPLACE VIEW lake.daily_summary AS
SELECT * FROM read_parquet('Data/Parquet/daily_summary/**/*.parquet', union_by_name=true);

CREATE OR REPLACE VIEW lake.workouts AS
SELECT * FROM read_parquet('Data/Parquet/workouts/**/*.parquet', union_by_name=true);

CREATE OR REPLACE VIEW lake.cardio_splits AS
SELECT * FROM read_parquet('Data/Parquet/cardio_splits/**/*.parquet', union_by_name=true);

CREATE OR REPLACE VIEW lake.cardio_strokes AS
SELECT * FROM read_parquet('Data/Parquet/cardio_strokes/**/*.parquet', union_by_name=true);

CREATE OR REPLACE VIEW lake.resistance_sets AS
SELECT * FROM read_parquet('Data/Parquet/resistance_sets/**/*.parquet', union_by_name=true);

CREATE OR REPLACE VIEW lake.labs AS
SELECT * FROM read_parquet('Data/Parquet/labs/**/*.parquet', union_by_name=true);

-- Optional catch-all for quick ad hoc searches (can be heavy)
-- CREATE OR REPLACE VIEW lake.all_parquet AS
-- SELECT * FROM read_parquet('Data/Parquet/**/*.parquet', union_by_name=true);
