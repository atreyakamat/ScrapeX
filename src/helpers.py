import pandas as pd
import json
import os

def save_to_csv(data, filepath):
    """Saves data to a CSV file."""
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Convert to DataFrame and save
        df = pd.DataFrame(data)
        df.to_csv(filepath, index=False)
        print(f"Data saved to CSV: {filepath}")
    except Exception as e:
        print(f"Failed to save CSV: {e}")

def save_to_json(data, filepath):
    """Saves data to a JSON file."""
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Save as JSON
        with open(filepath, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
        print(f"Data saved to JSON: {filepath}")
    except Exception as e:
        print(f"Failed to save JSON: {e}")
