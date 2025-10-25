from health_pipeline.ingest import csv_delta

def test_import_and_noop():
    csv_delta.main()
    assert True
