#!/usr/bin/env python3
"""
Concept2 OAuth2 Token Refresh Helper

Usage:
    # Step 1: Get authorization URL
    python scripts/concept2_oauth.py auth

    # Step 2: After authorizing, exchange code for token
    python scripts/concept2_oauth.py token <authorization_code>

    # Step 3: Refresh an expired token
    python scripts/concept2_oauth.py refresh
"""
import os
import sys
import json
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv, set_key

# Load environment
load_dotenv()

AUTH_URL = "https://log.concept2.com/oauth/authorize"
TOKEN_URL = "https://log.concept2.com/oauth/access_token"
REDIRECT_URI = "https://localhost/callback"  # For personal use
SCOPE = "user:read,results:read"

def get_credentials():
    """Get client credentials from environment."""
    client_id = os.getenv("CONCEPT2_CLIENT_ID")
    client_secret = os.getenv("CONCEPT2_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("Error: CONCEPT2_CLIENT_ID and CONCEPT2_CLIENT_SECRET must be set in .env")
        print("\nTo get these:")
        print("1. Go to https://log.concept2.com/developers")
        print("2. Create an application")
        print("3. Copy the client_id and client_secret to your .env file")
        sys.exit(1)

    return client_id, client_secret

def cmd_auth():
    """Generate authorization URL and open in browser."""
    client_id, _ = get_credentials()

    params = {
        "client_id": client_id,
        "scope": SCOPE,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
    }

    url = f"{AUTH_URL}?{urlencode(params)}"

    print("Opening authorization URL in browser...")
    print(f"\nURL: {url}\n")

    webbrowser.open(url)

    print("After authorizing, you'll be redirected to a URL like:")
    print(f"  {REDIRECT_URI}?code=XXXXXXXX")
    print("\nCopy the code from the URL and run:")
    print("  python scripts/concept2_oauth.py token <code>")

def cmd_token(auth_code: str):
    """Exchange authorization code for access token."""
    client_id, client_secret = get_credentials()

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
    }

    print("Exchanging authorization code for access token...")

    response = requests.post(TOKEN_URL, data=data)

    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        print(response.text)
        sys.exit(1)

    tokens = response.json()
    save_tokens(tokens)
    print("\nSuccess! Token saved to .env")

def cmd_refresh():
    """Refresh an expired access token using the refresh token."""
    client_id, client_secret = get_credentials()
    refresh_token = os.getenv("CONCEPT2_REFRESH_TOKEN")

    if not refresh_token:
        print("Error: No refresh token found in .env")
        print("Run 'python scripts/concept2_oauth.py auth' to get a new token")
        sys.exit(1)

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    print("Refreshing access token...")

    response = requests.post(TOKEN_URL, data=data)

    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        print(response.text)
        print("\nRefresh token may have expired. Run 'python scripts/concept2_oauth.py auth' to re-authorize")
        sys.exit(1)

    tokens = response.json()
    save_tokens(tokens)
    print("\nSuccess! Token refreshed and saved to .env")

def save_tokens(tokens: dict):
    """Save tokens to .env file."""
    env_path = Path(".env")

    if "access_token" in tokens:
        set_key(env_path, "CONCEPT2_API_TOKEN", tokens["access_token"])
        print(f"  Access token: {tokens['access_token'][:20]}...")

    if "refresh_token" in tokens:
        set_key(env_path, "CONCEPT2_REFRESH_TOKEN", tokens["refresh_token"])
        print(f"  Refresh token: {tokens['refresh_token'][:20]}...")

    if "expires_in" in tokens:
        print(f"  Expires in: {tokens['expires_in']} seconds")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "auth":
        cmd_auth()
    elif cmd == "token":
        if len(sys.argv) < 3:
            print("Error: Authorization code required")
            print("Usage: python scripts/concept2_oauth.py token <code>")
            sys.exit(1)
        cmd_token(sys.argv[2])
    elif cmd == "refresh":
        cmd_refresh()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)

if __name__ == "__main__":
    main()
