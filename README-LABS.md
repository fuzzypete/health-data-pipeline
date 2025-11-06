# Labs Fetch (Drive API only)

This project now **always** uses the Google Drive API to export the master Google Sheet to `.xlsx`.
Unauthenticated link-export is no longer attempted.

## Auth (choose one)

**A) Application Default Credentials**
```bash
gcloud auth application-default login
```

**B) Service account**
1. Create a service account and download its JSON key.
2. Share the Google Sheet with that service account email (Viewer).
3. Export the credential path:
```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
# or
export LABS_SERVICE_ACCOUNT_JSON=/path/to/sa.json
```

## One-time deps
```bash
poetry add google-api-python-client google-auth google-auth-httplib2
```

## Usage
```bash
make labs.fetch
```

Output is written to `Data/Raw/labs/` and symlinked/copied to `Data/Raw/labs/latest.xlsx`.