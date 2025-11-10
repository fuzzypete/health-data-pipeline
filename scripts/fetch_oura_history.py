# [File: scripts/fetch_oura_history.py]
import argparse
import sys
import os

# Add the project root to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.ingest.oura_api import fetch_oura_data

def main():
    parser = argparse.ArgumentParser(description="Fetch Oura API data.")
    parser.add_argument(
        "--start-date",
        help="Start date in YYYY-MM-DD format. Overrides last processed date."
    )
    
    args = parser.parse_args()
    fetch_oura_data(start_date=args.start_date)

if __name__ == "__main__":
    main()