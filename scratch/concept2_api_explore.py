#!/usr/bin/env python3
"""
Concept2 API Explorer
Fetches sample workout data to understand available granularity
"""
import requests
import json

API_KEY = "Ph2KW2lznHKNQibKUWS3BvYQsCNSZqKGPn74tMcZ"
BASE_URL = "https://log.concept2.com/api"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

print("=" * 80)
print("CONCEPT2 API EXPLORATION")
print("=" * 80)

# 1. Get user info
print("\n1. Fetching user info...")
try:
    response = requests.get(f"{BASE_URL}/users/me", headers=headers)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        user_data = response.json()
        print(json.dumps(user_data, indent=2))
    else:
        print(f"Error: {response.text}")
except Exception as e:
    print(f"Error: {e}")

# 2. Get recent results (workouts)
print("\n" + "=" * 80)
print("2. Fetching recent workouts...")
print("=" * 80)
try:
    response = requests.get(f"{BASE_URL}/users/me/results", headers=headers, params={"limit": 3})
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        results = response.json()
        print(f"\nFound {len(results.get('data', []))} workouts")
        
        # Show structure of first workout
        if results.get('data'):
            print("\n" + "-" * 80)
            print("First workout summary structure:")
            print("-" * 80)
            print(json.dumps(results['data'][0], indent=2))
            
            # Get the workout ID for detailed fetch
            workout_id = results['data'][0].get('id')
            
            # 3. Get detailed workout data
            print("\n" + "=" * 80)
            print(f"3. Fetching detailed data for workout {workout_id}...")
            print("=" * 80)
            response = requests.get(f"{BASE_URL}/users/me/results/{workout_id}", headers=headers)
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                detailed = response.json()
                print("\nDetailed workout data:")
                print(json.dumps(detailed, indent=2))
                
                # 4. Check for stroke data endpoint
                print("\n" + "=" * 80)
                print(f"4. Checking for stroke/split data...")
                print("=" * 80)
                
                # Try different possible endpoints
                endpoints_to_try = [
                    f"/users/me/results/{workout_id}/strokes",
                    f"/users/me/results/{workout_id}/splits",
                    f"/users/me/results/{workout_id}/data",
                ]
                
                for endpoint in endpoints_to_try:
                    print(f"\nTrying: {endpoint}")
                    response = requests.get(f"{BASE_URL}{endpoint}", headers=headers)
                    print(f"Status: {response.status_code}")
                    if response.status_code == 200:
                        data = response.json()
                        print(f"\n✓ SUCCESS! Found granular data:")
                        print(json.dumps(data, indent=2)[:2000])  # First 2000 chars
                        print("\n... (truncated)")
                    elif response.status_code == 404:
                        print("  → Endpoint not available")
                    else:
                        print(f"  → Error: {response.text[:200]}")
    else:
        print(f"Error: {response.text}")
except Exception as e:
    print(f"Error: {e}")

print("\n" + "=" * 80)
print("EXPLORATION COMPLETE")
print("=" * 80)
print("\nSave this output and share with Claude to design optimal schema.")
