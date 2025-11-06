#!/usr/bin/env python3
"""
Tiny Google Drive fetcher for HDP.

Fetch by:
  --file-id         (exact file ID)
  --file-name       (exact match)
  --name-contains   (substring match)
Optional:
  --folder-id       (restrict to a Drive folder)
  --out             (output file path)
  --prefer-mime     (override export MIME type)
"""
import argparse, io, os, sys, time
from typing import Optional, Dict, List
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

EXPORT_MAP = {
    "application/vnd.google-apps.spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.google-apps.document":    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.google-apps.presentation":"application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.google-apps.drawing":     "image/png",
    "application/vnd.google-apps.script":      "application/zip",
}
EXT_MAP = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/pdf": ".pdf",
    "text/csv": ".csv",
    "image/png": ".png",
    "application/zip": ".zip",
}

def _drive():
    key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not key or not os.path.exists(key):
        sys.exit("GOOGLE_APPLICATION_CREDENTIALS not set or file missing.")
    creds = service_account.Credentials.from_service_account_file(key, scopes=DRIVE_SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def _retry(fn, *a, **k):
    for i in range(5):
        try:
            return fn(*a, **k)
        except Exception as e:
            if i == 4:
                raise
            time.sleep(0.6 * (2 ** i))

def _get_file(drive, file_id: str) -> Dict:
    return _retry(drive.files().get(fileId=file_id, fields="id,name,mimeType,modifiedTime,parents").execute)

def _query(drive, q: str) -> List[Dict]:
    files, page = [], None
    while True:
        resp = _retry(
            drive.files().list(
                q=q, spaces="drive",
                fields="nextPageToken, files(id,name,mimeType,modifiedTime,parents)",
                orderBy="modifiedTime desc", pageSize=100, pageToken=page
            ).execute
        )
        files += resp.get("files", [])
        page = resp.get("nextPageToken")
        if not page:
            break
    return files

def _ensure_ext(path: str, mime: str) -> str:
    base, ext = os.path.splitext(path)
    return path if ext else base + EXT_MAP.get(mime, "")

def _export(drive, file_id: str, mime: str, out_path: str) -> None:
    req = drive.files().export(fileId=file_id, mimeType=mime)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = _retry(dl.next_chunk)
    with open(out_path, "wb") as f:
        f.write(buf.getvalue())

def _download(drive, file_id: str, out_path: str) -> None:
    req = drive.files().get_media(fileId=file_id)
    with open(out_path, "wb") as f:
        dl = MediaIoBaseDownload(f, req)
        done = False
        while not done:
            _, done = _retry(dl.next_chunk)

def fetch(file_id: Optional[str] = None,
          file_name: Optional[str] = None,
          name_contains: Optional[str] = None,
          folder_id: Optional[str] = None,
          out: Optional[str] = None,
          prefer_mime: Optional[str] = None) -> str:
    """Returns output path."""
    if not (file_id or file_name or name_contains):
        raise ValueError("Provide one of --file-id, --file-name, or --name-contains.")

    drive = _drive()
    f = None

    if file_id:
        f = _get_file(drive, file_id)
    else:
        q = ["trashed = false"]
        if folder_id:
            q.append(f"'{folder_id}' in parents")
        if file_name:
            q.append(f"name = '{file_name}'")
        elif name_contains:
            safe = name_contains.replace("'", "\\'")
            q.append(f"name contains '{safe}'")
        files = _query(drive, " and ".join(q))
        if not files:
            raise SystemExit(f"No files matched: {file_name or name_contains}")
        f = files[0]

    fid, name, mime = f["id"], f["name"], f["mimeType"]
    out_path = out or name
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    if mime.startswith("application/vnd.google-apps."):
        export_mime = prefer_mime or EXPORT_MAP.get(mime)
        if not export_mime:
            raise SystemExit(f"No export mapping for {mime}. Provide --prefer-mime.")
        out_path = _ensure_ext(out_path, export_mime)
        _export(drive, fid, export_mime, out_path)
        return out_path
    else:
        out_path = _ensure_ext(out_path, mime)
        _download(drive, fid, out_path)
        return out_path

def main():
    ap = argparse.ArgumentParser(description="Tiny HDP Drive Fetcher")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--file-id", help="Download by Drive File ID")
    g.add_argument("--file-name", help="Download by exact file name")
    g.add_argument("--name-contains", help="Download latest file whose name contains this substring")
    ap.add_argument("--folder-id", help="Optional folder ID to scope search")
    ap.add_argument("--out", help="Output file path")
    ap.add_argument("--prefer-mime", help="Override export MIME type (e.g., application/pdf)")
    args = ap.parse_args()

    out_path = fetch(args.file_id, args.file_name, args.name_contains, args.folder_id, args.out, args.prefer_mime)
    print(f"✅ Saved → {out_path}")

if __name__ == "__main__":
    main()
