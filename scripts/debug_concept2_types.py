"""
Debug Concept2 workout types from API.

Run this to see what the API actually returns for the type field.
"""
from pipeline.ingest.concept2_api import Concept2Client

client = Concept2Client()

print("Fetching 10 recent workouts to inspect type field...\n")
workouts = client.get_recent_workouts(limit=10)

for i, workout in enumerate(workouts, 1):
    print(f"=== Workout {i} ===")
    print(f"ID: {workout['id']}")
    print(f"Date: {workout['date']}")
    print(f"Distance: {workout.get('distance')} m")
    
    # Check all possible type-related fields
    print(f"Type field value: '{workout.get('type', 'MISSING')}'")
    print(f"Workout_type field: '{workout.get('workout_type', 'MISSING')}'")
    print(f"Stroke_type field: '{workout.get('stroke_type', 'MISSING')}'")
    
    # Show all top-level keys
    print(f"All keys: {list(workout.keys())[:15]}...")  # First 15 keys
    print()
