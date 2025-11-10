# [File: src/pipeline/ingest/oura_api.py]
import os
import requests
import json
from datetime import date, timedelta
from ..paths import (
    OURA_TOKENS_FILE_PATH,
    RAW_OURA_SLEEP_DIR,
    RAW_OURA_ACTIVITY_DIR,
    RAW_OURA_READINESS_DIR
)
# Use config for secrets, not dotenv
from ..common.config import get_oura_client_id, get_oura_client_secret

# Get credentials from central config
CLIENT_ID = get_oura_client_id()
CLIENT_SECRET = get_oura_client_secret()

TOKEN_URL = "https://api.ouraring.com/oauth/token"
API_BASE_URL = "https://api.ouraring.com/v2/usercollection"

# Define the data we want to fetch and where to save it
DATA_ENDPOINTS = {
    "daily_sleep": RAW_OURA_SLEEP_DIR,
    "daily_activity": RAW_OURA_ACTIVITY_DIR,
    "daily_readiness": RAW_OURA_READINESS_DIR,
}

class OuraAPIClient:
    """
    Client to handle Oura V2 API authentication, token refreshing,
    and data fetching.
    """
    def __init__(self, token_file=OURA_TOKENS_FILE_PATH): # Use standard path
        self.token_file = token_file
        self.tokens = self._load_tokens()
        self._ensure_directories()

    def _ensure_directories(self):
        """Make sure the raw data directories exist."""
        for path in DATA_ENDPOINTS.values():
            # Use the Path object's mkdir method
            path.mkdir(parents=True, exist_ok=True)

    def _load_tokens(self):
        """Load tokens from the JSON file."""
        if not self.token_file.exists(): # Use Path.exists()
            raise FileNotFoundError(
                f"Token file not found at {self.token_file}. "
                "Please run `poetry run python scripts/setup_oura.py` first."
            )
        with open(self.token_file, 'r') as f:
            return json.load(f)

    def _save_tokens(self):
        """Save updated tokens to the JSON file."""
        with open(self.token_file, 'w') as f:
            json.dump(self.tokens, f, indent=4)

    def _refresh_access_token(self):
        """Use the refresh token to get a new access token."""
        print("Oura access token expired. Refreshing...")
        
        if not CLIENT_ID or not CLIENT_SECRET:
            print("❌ Error: OURA_CLIENT_ID or OURA_CLIENT_SECRET not configured.")
            return None

        token_data = {
            "grant_type": "refresh_token",
            "refresh_token": self.tokens["refresh_token"],
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            response = requests.post(TOKEN_URL, data=token_data, headers=headers)
            response.raise_for_status()
            
            self.tokens = response.json()  # Save new tokens
            self._save_tokens()
            print("Successfully refreshed Oura tokens.")
            return self.tokens["access_token"]

        except requests.exceptions.RequestException as e:
            print(f"❌ Error refreshing Oura token: {e}")
            if e.response:
                print(f"Response: {e.response.text}")
            return None

    def _make_request(self, endpoint_url, params):
        """Make an authenticated request to the Oura API, handling token refresh."""
        headers = {"Authorization": f"Bearer {self.tokens['access_token']}"}
        
        response = requests.get(endpoint_url, headers=headers, params=params)

        if response.status_code == 401:  # Token expired
            if self._refresh_access_token():
                # Retry the request with the new token
                headers["Authorization"] = f"Bearer {self.tokens['access_token']}"
                response = requests.get(endpoint_url, headers=headers, params=params)
            else:
                raise Exception("Failed to refresh Oura token. Aborting.")
        
        response.raise_for_status()  # Raise an error for other bad responses
        return response.json()

    def fetch_data_by_date(self, start_date_str: str, end_date_str: str):
        """
        Fetch data for all endpoints for a specific date range.
        Dates should be in 'YYYY-MM-DD' format.
        """
        print(f"Fetching Oura data from {start_date_str} to {end_date_str}...")

        params = {
            "start_date": start_date_str,
            "end_date": end_date_str,
        }

        for endpoint, save_dir in DATA_ENDPOINTS.items():
            print(f"Fetching {endpoint}...")
            endpoint_url = f"{API_BASE_URL}/{endpoint}"
            
            try:
                data = self._make_request(endpoint_url, params)
                
                # Oura may return data day by day in the 'data' list
                items = data.get("data", [])
                if not items:
                    print(f"No new data found for {endpoint}.")
                    continue

                for item in items:
                    day = item.get("day")
                    if not day:
                        print(f"Skipping item with no day: {item}")
                        continue
                        
                    filename = f"oura_{endpoint}_{day}.json"
                    # Use Path object to join path and write
                    filepath = save_dir / filename
                    with open(filepath, 'w') as f:
                        json.dump(item, f, indent=4)
                
                print(f"Successfully saved {len(items)} items for {endpoint} to {save_dir}")
                
            except requests.exceptions.RequestException as e:
                print(f"❌ Error fetching {endpoint}: {e}")
                if e.response:
                    print(f"Response: {e.response.text}")

def fetch_oura_data(start_date=None):
    """
    Main function to fetch Oura data for a specified start_date.
    Relies on START_DATE from Makefile.
    """
    try:
        client = OuraAPIClient()
    except FileNotFoundError as e:
        print(e)
        print("Please run `poetry run python scripts/setup_oura.py` first.")
        return

    if start_date:
        start = date.fromisoformat(start_date)
        print(f"Using provided start date: {start.isoformat()}")
    else:
        # Default: 3 days back if no start_date is provided (e.g., manual run)
        start = date.today() - timedelta(days=3)
        print(f"No start_date provided. Defaulting to 3 days ago: {start.isoformat()}")

    end = date.today()

    if start > end:
        print(f"Start date {start.isoformat()} is after end date {end.isoformat()}. Nothing to fetch.")
        return

    client.fetch_data_by_date(start.isoformat(), end.isoformat())

    print(f"--- Oura fetch complete for range {start.isoformat()} to {end.isoformat()} ---")