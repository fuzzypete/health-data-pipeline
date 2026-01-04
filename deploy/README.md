# Deployment (GCS + BigQuery)

## Storage (GCS)
- Bucket: gs://hdp-data-lake/{Parquet,Raw}
- Partitions: year/month
- Compact: 128–512 MB per file

## BigQuery (External table)
```sql
CREATE OR REPLACE EXTERNAL TABLE `project.dataset.workouts_ext`
OPTIONS (
  format = 'PARQUET',
  uris = ['gs://hdp-data-lake/Parquet/workouts/year=*/month=*/*.parquet'],
  hive_partitioning_mode = 'AUTO',
  hive_partitioning_source_uri_prefix = 'gs://hdp-data-lake/Parquet/workouts/'
);
```

## BigQuery (Native table promotion)
Create a native partitioned table and load/merge on schedule for speed/cost.

## Cloud Run Job
- Container entrypoint: `make all`
- Secrets via Secret Manager
- Service Account: GCS rw + BigQuery data editor
