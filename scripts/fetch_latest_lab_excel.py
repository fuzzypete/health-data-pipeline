#!/usr/bin/env python3
"""
Fetch the latest Labs master spreadsheet as .xlsx using the Google Drive API ONLY.
Requires auth via Application Default Credentials (ADC) or a service account JSON.

Setup (choose one):
  A) gcloud auth application-default login
  B) export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
     (or LABS_SERVICE_ACCOUNT_JSON)

Dependencies:
  google-api-python-client google-auth google-auth-httplib2

Note:
  - The Google Sheet must be shared (Viewer) with the authenticated principal.
  - This script uses Drive files.export to convert the native Google Sheet to XLSX.
"""
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime

DEFAULT_SHEET_ID = os.environ.get("LAB_SHEET_ID", "1Ko8Dem0B_Mmqdq83WPtpoXo6i44qUcXY")
DEFAULT_OUT_DIR = os.environ.get("LAB_RAW_DIR", "Data/Raw/labs")
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

def get_credentials():
    creds = None
    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
    # Try ADC
    try:
        import google.auth
        creds, _ = google.auth.default(scopes=SCOPES)
    except Exception as e:
        print(f"[labs.fetch] ADC unavailable: {e}", file=sys.stderr)
    # Fallback to explicit SA JSON
    if creds is None:
        sa_path = os.environ.get("LABS_SERVICE_ACCOUNT_JSON") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not sa_path:
            raise RuntimeError("No credentials found. Run 'gcloud auth application-default login' or set GOOGLE_APPLICATION_CREDENTIALS/LABS_SERVICE_ACCOUNT_JSON to a service-account JSON.")
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
    return creds

def export_sheet_to_xlsx(file_id: str, out_path: Path):
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    creds = get_credentials()
    try:
        service = build("drive", "v3", credentials=creds)
        req = service.files().export(fileId=file_id, mimeType=XLSX_MIME)
        data = req.execute()
    except HttpError as e:
        status = getattr(e, "status_code", getattr(e, "resp", None).status if getattr(e, "resp", None) else "unknown")
        msg = getattr(e, "content", b"")[:400]
        raise RuntimeError(f"Drive API export failed (status={status}): {msg!r}")
    out_path.write_bytes(data)

def main():
    ap = argparse.ArgumentParser(description="Download latest Labs master Google Sheet as .xlsx via Drive API")
    ap.add_argument("--sheet-id", default=DEFAULT_SHEET_ID, help="Google Sheet file ID")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Output directory (default Data/Raw/labs)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"labs-master-{ts}.xlsx"
    latest = out_dir / "latest.xlsx"

    print(f"[labs.fetch] Exporting fileId={args.sheet_id} -> {out_path}")
    export_sheet_to_xlsx(args.sheet_id, out_path)
    print(f"[labs.fetch] Saved {out_path}")

    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(out_path.name)
    except Exception:
        latest.write_bytes(out_path.read_bytes())
        print(f"[labs.fetch] Wrote copy to {latest}")
    return 0

if __name__ == "__main__":
    sys.exit(main())