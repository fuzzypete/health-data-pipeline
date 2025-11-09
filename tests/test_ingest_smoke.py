from importlib import import_module

def test_ingest_modules_import():
    # Ensure key ingestion modules import successfully
    import_module("pipeline.ingest.hae_csv")
    import_module("pipeline.ingest.jefit_csv")
    import_module("pipeline.ingest.labs_excel")
