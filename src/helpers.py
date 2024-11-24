import pandas as pd
import json
import os
import logging
from bs4 import BeautifulSoup

# Configure logging
if not os.path.exists('logs'):
    os.makedirs('logs')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='logs/scraper.log',
    filemode='a'
)

# Create necessary directories and files
required_dirs = ["scraped-images", "data", "logs"]
required_files = [
    "data/final_results.json",
    "data/links.csv", 
    "logs/scraper.log"
]

# Create directories if they don't exist
for directory in required_dirs:
    if not os.path.exists(directory):
        os.makedirs(directory)
        logging.info(f"Created directory: {directory}")

# Create files if they don't exist
for filepath in required_files:
    if not os.path.exists(filepath):
        with open(filepath, 'w') as f:
            if filepath.endswith('.json'):
                f.write('{}')
            elif filepath.endswith('.csv'):
                f.write('')
        logging.info(f"Created file: {filepath}")

def save_to_csv(data, filepath):
    """Saves data to a CSV file."""
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Convert to DataFrame and save
        df = pd.DataFrame(data)
        df.to_csv(filepath, index=False)
        logging.info(f"Data saved to CSV: {filepath}")
    except Exception as e:
        logging.error(f"Failed to save CSV: {e}")

def save_to_json(data, filepath):
    """Saves data to a JSON file."""
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Save as JSON
        with open(filepath, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
        logging.info(f"Data saved to JSON: {filepath}")
    except Exception as e:
        logging.error(f"Failed to save JSON: {e}")

def parse_html(html_content):
    """Parses HTML/XML content using appropriate parser."""
    try:
        # Use lxml parser with XML features
        soup = BeautifulSoup(html_content, 'lxml-xml')
        return soup
    except Exception as e:
        # Fallback to html.parser if XML parsing fails
        logging.warning(f"XML parsing failed, falling back to HTML parser: {e}")
        return BeautifulSoup(html_content, 'html.parser')
