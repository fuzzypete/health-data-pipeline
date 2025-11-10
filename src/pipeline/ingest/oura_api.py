# [File: src/pipeline/ingest/oura_api.py]
import os
import requests
import json
from datetime import date, timedelta
from ..paths import (
    OURA_TOKENS_FILE,
    RAW_OURA_SLEEP_DIR,
    RAW_OURA_ACTIVITY_DIR,
    RAW_OURA_READINESS_DIR
)
from ..common.timestamps import get_last_processed_timestamp, write_last_processed_timestamp
from dotenv import load_dotenv

# Load credentials from .env
load_dotenv()
CLIENT_ID = os.getenv("OURA_CLIENT_ID")
CLIENT_SECRET = os.getenv("OURA_CLIENT_SECRET")

TOKEN_URL = "https.api.ouraring.com/oauth/token"
API_BASE_URL = "https.api.ouraring.com/v2/usercollection"

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
    def __init__(self, token_file=OURA_TOKENS_FILE):
        self.token_file = token_file
        self.tokens = self._load_tokens()
        self._ensure_directories()

    def _ensure_directories(self):
        """Make sure the raw data directories exist."""
        for path in DATA_ENDPOINTS.values():
            os.makedirs(path, exist_ok=True)

    def _load_tokens(self):
        """Load tokens from the JSON file."""
        if not os.path.exists(self.token_file):
            raise FileNotFoundError(
                f"Token file not found at {self.token_file}. "
                "Please run scripts/setup_oura.py first."
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
                    filepath = os.path.join(save_dir, filename)
                    with open(filepath, 'w') as f:
                        json.dump(item, f, indent=4)
                
                print(f"Successfully saved {len(items)} items for {endpoint} to {save_dir}")
                
            except requests.exceptions.RequestException as e:
                print(f"❌ Error fetching {endpoint}: {e}")
                if e.response:
                    print(f"Response: {e.response.text}")

def fetch_oura_data(start_date=None):
    """
    Main function to fetch Oura data since the last processed date
    or a specified start_date.
    """
    try:
        client = OuraAPIClient()
    except FileNotFoundError as e:
        print(e)
        print("Please run `poetry run python scripts/setup_oura.py` first.")
        return

    # Use the 'oura' namespace for the last processed timestamp
    last_processed = get_last_processed_timestamp(namespace="oura")

    if start_date:
        start = date.fromisoformat(start_date)
        print(f"Using provided start date: {start.isoformat()}")
    elif last_processed:
        start = date.fromisoformat(last_processed) + timedelta(days=1)
        print(f"Resuming from last processed date: {start.isoformat()}")
    else:
        # Default: 5 years back, matching your Concept2 bootstrap
        start = date.fromisoformat("2019-01-01") 
        print(f"No last processed date, bootstrapping from default: {start.isoformat()}")

    end = date.today()

    if start > end:
        print(f"Oura data is already up-to-date. Last processed: {last_processed}")
        return

    client.fetch_data_by_date(start.isoformat(), end.isoformat())

    # Record the new last processed date
    write_last_processed_timestamp(end.isoformat(), namespace="oura")