# src/pipeline/ingest/oura_api.py
"""
Oura API Client - Fetches sleep measurements and scores from Oura Ring API v2

This module handles:
1. OAuth token management (refresh when expired)
2. Data fetching from Oura API
3. Saving raw JSON responses to Raw/Oura/ directories

Fetched endpoints:
- sleep: ALL sleep measurements including:
  * Sleep durations (total, REM, deep, light, awake)
  * Heart rate (average, lowest during sleep = resting baseline)
  * HRV (average during sleep)
  * Temperature deviation (embedded in readiness object)
  * Readiness score
  * Timestamps and sleep stages

- daily_sleep: Sleep score and contributors
  * Sleep score (0-100)
  * Contributor scores showing what drove the score
  * Complements raw measurements with Oura's validated scoring algorithm
"""
import os
import requests
import json
from datetime import date, timedelta
from ..paths import (
    OURA_TOKENS_FILE_PATH,
    RAW_OURA_SLEEP_DIR,
)
from ..common.config import get_oura_client_id, get_oura_client_secret

# Get credentials from central config
CLIENT_ID = get_oura_client_id()
CLIENT_SECRET = get_oura_client_secret()

TOKEN_URL = "https://api.ouraring.com/oauth/token"
API_BASE_URL = "https://api.ouraring.com/v2/usercollection"

# Define the data we want to fetch and where to save it
DATA_ENDPOINTS = {
    "sleep": RAW_OURA_SLEEP_DIR,        # All measurements + embedded readiness
    "daily_sleep": RAW_OURA_SLEEP_DIR,  # Sleep score + contributors
}

class OuraAPIClient:
    """
    Client to handle Oura V2 API authentication, token refreshing,
    and data fetching.
    """
    def __init__(self, token_file=OURA_TOKENS_FILE_PATH):
        self.token_file = token_file
        self.tokens = self._load_tokens()
        self._ensure_directories()

    def _ensure_directories(self):
        """Make sure the raw data directories exist."""
        for path in DATA_ENDPOINTS.values():
            path.mkdir(parents=True, exist_ok=True)

    def _load_tokens(self):
        """Load tokens from the JSON file."""
        if not self.token_file.exists():
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
            print("✅ Successfully refreshed Oura tokens.")
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
                    print(f"  No new data found for {endpoint}.")
                    continue

                for item in items:
                    day = item.get("day")
                    if not day:
                        print(f"  ⚠️  Skipping item with no day: {item}")
                        continue
                    
                    # Use endpoint name in filename to distinguish sleep from daily_sleep
                    filename = f"oura_{endpoint}_{day}.json"
                    filepath = save_dir / filename
                    with open(filepath, 'w') as f:
                        json.dump(item, f, indent=4)
                
                print(f"  ✅ Saved {len(items)} items for {endpoint}")
                
            except requests.exceptions.RequestException as e:
                print(f"  ❌ Error fetching {endpoint}: {e}")
                if hasattr(e, 'response') and e.response:
                    print(f"  Response: {e.response.text}")

def fetch_oura_data(start_date=None):
    """
    Main function to fetch Oura data for a specified start_date.
    If no start_date is provided, fetches the last 7 days.
    """
    if start_date is None:
        start_date = date.today() - timedelta(days=7)
    elif isinstance(start_date, str):
        # Parse string to date
        from datetime import datetime
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()

    end_date = date.today()
    
    client = OuraAPIClient()
    client.fetch_data_by_date(
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d")
    )

if __name__ == "__main__":
    fetch_oura_data()
