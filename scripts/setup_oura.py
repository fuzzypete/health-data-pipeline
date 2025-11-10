import os
import webbrowser
import requests
import json
from urllib.parse import urlencode
import sys
from pathlib import Path

# Add project root (parent of 'scripts') to sys.path
# This allows us to import from 'src.pipeline'
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

# Now we can import from the pipeline
from src.pipeline.common.config import get_oura_client_id, get_oura_client_secret
from src.pipeline.paths import OURA_TOKENS_FILE_PATH


# --- Configuration ---
# Get secrets from the central config manager
CLIENT_ID = get_oura_client_id()
CLIENT_SECRET = get_oura_client_secret()

# This MUST match the "Redirect URI" you set in the Oura app settings
REDIRECT_URI = "http://localhost:8080/oura_callback"

# The scopes we're requesting
SCOPES = "email personal daily heartrate workout session tag spo2"

# Oura's API endpoints
AUTH_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"

# The file where we'll store the tokens, from paths.py
TOKEN_FILE = OURA_TOKENS_FILE_PATH

def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Error: OURA_CLIENT_ID or OURA_CLIENT_SECRET not found in .env file.")
        print("Please add them before proceeding.")
        return

    # --- Part 1: Get Authorization Code ---
    
    # Build the authorization URL
    auth_params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    }
    auth_url = f"{AUTH_URL}?{urlencode(auth_params)}"

    print("--- Oura OAuth Setup ---")
    print("\nStep 1: Authorize this application")
    print("Your browser will now open. Please log in to Oura and click 'Allow'.")
    print("After allowing, your browser will show a 'This site can’t be reached' error.")
    print("This is EXPECTED.")
    print("\nPress Enter to open the browser...")
    input()
    
    webbrowser.open(auth_url)

    print("-" * 30)
    print("Step 2: Copy the 'code' from your browser")
    print("Look at the URL in your browser's address bar. It will look like:")
    print(f"{REDIRECT_URI}?code=SOME_LONG_CODE_HERE&scope=...")
    print("\nCopy the 'code' value (the long string after 'code=') and paste it here:")
    
    pasted_code = input("Enter code: ").strip()

    if not pasted_code:
        print("No code provided. Exiting.")
        return

    # --- Part 2: Exchange Code for Tokens ---
    print("\nStep 3: Exchanging code for tokens...")
    
    token_data = {
        "grant_type": "authorization_code",
        "code": pasted_code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }

    try:
        response = requests.post(TOKEN_URL, data=token_data)
        response.raise_for_status()  # This will raise an error if the request failed
        
        tokens = response.json()

        # --- Part 3: Save Tokens ---
        with open(TOKEN_FILE, 'w') as f:
            json.dump(tokens, f, indent=4)
        
        print(f"\n✅ Success! Tokens saved to {TOKEN_FILE}")
        print("This file contains your secret tokens. DO NOT commit it to Git.")
        print("Your .gitignore should already cover the Data/ directory.")
        print("\nYou are all set.")

    except requests.exceptions.RequestException as e:
        print(f"\n❌ Error exchanging code: {e}")
        if e.response:
            print(f"Response content: {e.response.text}")

if __name__ == "__main__":
    main()