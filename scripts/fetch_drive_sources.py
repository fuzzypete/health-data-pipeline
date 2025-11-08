#!/usr/bin/env python3
"""
Config-Driven Google Drive Fetcher for HDP.

Reads the 'drive_sources' section of config.yaml and fetches files
based on the specified type:
  - 'single_file': Finds a file by name in a parent folder and exports/downloads it.
  - 'folder_sync': Finds a subfolder by name and downloads all files within it.

Authentication is handled via GOOGLE_APPLICATION_CREDENTIALS.
"""

import argparse
import io
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add src to path to allow imports from pipeline.common
sys.path.append(str(Path(__file__).parent.parent))

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build, Resource
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaIoBaseDownload
except ImportError:
    print("Error: Google client libraries not found.", file=sys.stderr)
    print("Please run: poetry add google-api-python-client google-auth", file=sys.stderr)
    sys.exit(1)

from pipeline.common.config import get_drive_source, get_config
# We use RAW_ROOT's parent as the project root for resolving paths
from pipeline.paths import RAW_ROOT

# Configure logging
log = logging.getLogger("fetch_drive_sources")

# --- Constants ---
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

# Mimetypes for G-Suite files that must be *exported*
EXPORT_MIMETYPES = {
    "application/vnd.google-apps.spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.google-apps.document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
# Corresponding extensions
EXPORT_EXTENSIONS = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


class DriveClient:
    """Wrapper for Google Drive API v3 operations."""

    def __init__(self, credentials_path: str | None = None):
        self.service = self._build_service(credentials_path)

    def _build_service(self, credentials_path: str | None) -> Resource:
        """Authenticate and build the Drive v3 service."""
        creds_path = credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not creds_path:
            raise ValueError(
                "No Google credentials found. "
                "Set GOOGLE_APPLICATION_CREDENTIALS in your .env file."
            )
        
        creds_path = os.path.expanduser(creds_path)
        if not os.path.exists(creds_path):
            raise FileNotFoundError(
                f"Service account file not found at: {creds_path}"
            )
        
        log.debug(f"Using credentials from {creds_path}")
        creds = service_account.Credentials.from_service_account_file(
            creds_path, scopes=DRIVE_SCOPES
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def _retry_request(self, request, max_retries=5):
        """Execute a Google API request with exponential backoff."""
        for i in range(max_retries):
            try:
                return request.execute()
            except HttpError as e:
                if e.resp.status in [403, 500, 503] and i < max_retries - 1:
                    wait_time = (2 ** i) + (datetime.now().microsecond / 1000000)
                    log.warning(f"Drive API error (status {e.resp.status}). Retrying in {wait_time:.2f}s...")
                    time.sleep(wait_time)
                else:
                    log.error(f"Drive API request failed: {e}")
                    raise
        raise Exception("Max retries exceeded") # Should be unreachable

    def get_file_by_name(self, file_name: str, parent_folder_id: str) -> Optional[Dict[str, Any]]:
        """Find the most recently modified file by name within a parent folder."""
        q = (
            f"name = '{file_name}' and "
            f"'{parent_folder_id}' in parents and "
            f"mimeType != '{FOLDER_MIME_TYPE}' and "
            "trashed = false"
        )
        request = self.service.files().list(
            q=q,
            spaces="drive",
            fields="files(id, name, mimeType, modifiedTime)",
            orderBy="modifiedTime desc",
            pageSize=1
        )
        response = self._retry_request(request)
        files = response.get("files", [])
        if not files:
            log.warning(f"No file named '{file_name}' found in folder '{parent_folder_id}'")
            return None
        return files[0]

    def get_folder_by_name(self, folder_name: str, parent_folder_id: str) -> Optional[Dict[str, Any]]:
        """Find a subfolder by name within a parent folder."""
        q = (
            f"name = '{folder_name}' and "
            f"'{parent_folder_id}' in parents and "
            f"mimeType = '{FOLDER_MIME_TYPE}' and "
            "trashed = false"
        )
        request = self.service.files().list(
            q=q,
            spaces="drive",
            fields="files(id, name)",
            pageSize=1
        )
        response = self._retry_request(request)
        folders = response.get("files", [])
        if not folders:
            log.warning(f"No folder named '{folder_name}' found in parent '{parent_folder_id}'")
            return None
        return folders[0]
        
    def list_files_in_folder(self, folder_id: str) -> List[Dict[str, Any]]:
        """List all non-folder files in a specific folder."""
        q = (
            f"'{folder_id}' in parents and "
            f"mimeType != '{FOLDER_MIME_TYPE}' and "
            "trashed = false"
        )
        all_files = []
        page_token = None
        while True:
            request = self.service.files().list(
                q=q,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType)",
                pageSize=100,
                pageToken=page_token
            )
            response = self._retry_request(request)
            all_files.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        log.info(f"Found {len(all_files)} files in folder '{folder_id}'")
        return all_files

    def download_file(self, file_id: str, file_name: str, output_path: Path):
        """Download a binary file (e.g., CSV, JSON)."""
        log.debug(f"Downloading binary file '{file_name}' (ID: {file_id})")
        request = self.service.files().get_media(fileId=file_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with io.FileIO(output_path, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                try:
                    status, done = downloader.next_chunk()
                    log.debug(f"Download {file_name}: {int(status.progress() * 100)}%")
                except HttpError as e:
                    log.error(f"Download failed for {file_name}: {e}")
                    # Clean up partial file
                    if output_path.exists():
                        output_path.unlink()
                    raise

    def export_file(self, file_id: str, file_name: str, export_mime: str, output_path: Path):
        """Export a G-Suite file (e.g., GSheet to .xlsx)."""
        log.debug(f"Exporting G-Suite file '{file_name}' (ID: {file_id}) as {export_mime}")
        request = self.service.files().export(fileId=file_id, mimeType=export_mime)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # Note: export() returns the file content directly, not a request object
            response_data = self._retry_request(request)
            with open(output_path, "wb") as f:
                f.write(response_data)
        except Exception as e:
            log.error(f"Export failed for {file_name}: {e}")
            if output_path.exists():
                output_path.unlink()
            raise


# --- THIS IS THE FIX (Part 1) ---
def resolve_path(path_str: str) -> Path:
    """Resolve a path relative to the project root."""
    path = Path(path_str)
    if path.is_absolute():
        return path
    
    # Assumes the script is run from the project root, or that
    # RAW_ROOT.parent correctly points to the project root (e.g., 'Data/..')
    # This resolves to the project root, e.g., '/home/pwickersham/src/health-data-pipeline'
    project_root = Path.cwd() 
    
    # Create the correct absolute path
    # e.g., /home/pwickersham/src/health-data-pipeline / Data/Raw/labs...
    return project_root.joinpath(path).resolve()


def handle_single_file(client: DriveClient, config: Dict[str, Any]):
    """Fetch a single file as defined in config."""
    file_name = config.get("file_name")
    parent_id = config.get("parent_folder_id")
    output_path_str = config.get("output_path")
    
    if not (file_name and parent_id and output_path_str):
        log.error("Config for 'single_file' is missing file_name, parent_folder_id, or output_path")
        return

    # Use the corrected resolve_path function
    output_path = resolve_path(output_path_str)

    log.info(f"Fetching single file: '{file_name}' from parent '{parent_id}'")
    file = client.get_file_by_name(file_name, parent_id)
    if not file:
        return # Error already logged by client

    file_id = file["id"]
    mime_type = file["mimeType"]

    if mime_type in EXPORT_MIMETYPES:
        export_mime = EXPORT_MIMETYPES[mime_type]
        # Add extension if missing
        if not output_path.suffix:
            output_path = output_path.with_suffix(EXPORT_EXTENSIONS[export_mime])
        
        client.export_file(file_id, file_name, export_mime, output_path)
    else:
        client.download_file(file_id, file_name, output_path)
    
    # --- THIS IS THE FIX (Part 2) ---
    # Log the path relative to the project root (Path.cwd())
    log.info(f"✅ Saved -> {output_path.relative_to(Path.cwd())}")


def handle_folder_sync(client: DriveClient, config: Dict[str, Any]):
    """Fetch all files from a folder as defined in config."""
    parent_id = config.get("parent_folder_id")
    folder_name = config.get("folder_name")
    output_dir_str = config.get("output_dir")
    
    if not (parent_id and folder_name and output_dir_str):
        log.error("Config for 'folder_sync' is missing parent_folder_id, folder_name, or output_dir")
        return

    # Use the corrected resolve_path function
    output_dir = resolve_path(output_dir_str)

    log.info(f"Syncing folder: '{folder_name}' from parent '{parent_id}'")
    folder = client.get_folder_by_name(folder_name, parent_id)
    if not folder:
        return # Error already logged by client
    
    files = client.list_files_in_folder(folder["id"])
    if not files:
        log.info("No files to download.")
        return
        
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for file in files:
        file_id = file["id"]
        file_name = file["name"]
        output_path = output_dir / file_name
        
        # Simple skip: if file exists, don't re-download
        if output_path.exists():
            log.debug(f"Skipping existing file: {file_name}")
            continue

        try:
            # G-Suite files (like .gsheet) can't be "downloaded", they are 0-byte
            # links. We only care about binary files (CSV, JSON) in folder sync.
            if file["mimeType"] in EXPORT_MIMETYPES:
                log.warning(f"Skipping G-Suite file '{file_name}'. Folder sync only downloads binary files.")
                continue

            client.download_file(file_id, file_name, output_path)
            log.info(f"  Downloaded: {file_name}")
            count += 1
            # TODO: Add post-download archiving (moving the file on Drive)
        except Exception as e:
            log.error(f"  Failed to download {file_name}: {e}")
            
    # --- THIS IS THE FIX (Part 3) ---
    log.info(f"✅ Synced {count} new files to {output_dir.relative_to(Path.cwd())}")


def main():
    parser = argparse.ArgumentParser(description="HDP Google Drive Fetcher")
    parser.add_argument(
        "sources",
        nargs="*",
        help="Specific sources to fetch from config.yaml (e.g., 'labs', 'hae_csv'). "
             "If empty, fetches ALL sources."
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)-7s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    try:
        # Load the main pipeline config to find drive_sources
        config = get_config()
        all_source_names = config.get('drive_sources', {}).keys()

        sources_to_fetch = args.sources
        if not sources_to_fetch:
            sources_to_fetch = list(all_source_names)
        
        log.info(f"Attempting to fetch {len(sources_to_fetch)} source(s): {', '.join(sources_to_fetch)}")

        client = DriveClient(credentials_path=None)

        for source_name in sources_to_fetch:
            source_config = get_drive_source(source_name)
            if not source_config:
                log.error(f"Source '{source_name}' not found in config.yaml. Skipping.")
                continue

            fetch_type = source_config.get("type")
            log.info(f"--- Processing source: {source_name} (type: {fetch_type}) ---")
            
            if fetch_type == "single_file":
                handle_single_file(client, source_config)
            elif fetch_type == "folder_sync":
                handle_folder_sync(client, source_config)
            else:
                log.error(f"Unknown fetch type '{fetch_type}' for source '{source_name}'. Skipping.")

        log.info("--- Fetch complete ---")

    except Exception as e:
        log.exception(f"Fatal error during fetch process: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()