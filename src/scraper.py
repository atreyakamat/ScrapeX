import requests
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin, urlparse
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
from collections import deque
import hashlib
from helpers import save_to_json, save_to_csv, parse_html

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

def download_image(image_url, image_name, base_url):
    """Download an image from a URL and save it locally with error handling."""
    try:
        # Handle relative URLs
        if not image_url.startswith(('http://', 'https://')):
            image_url = urljoin(base_url, image_url)
            
        # Create hash of URL for unique filename
        hash_object = hashlib.md5(image_url.encode())
        file_hash = hash_object.hexdigest()
        
        # Extract extension from original filename or default to .jpg
        ext = os.path.splitext(image_name)[1] or '.jpg'
        safe_filename = f"{file_hash}{ext}"
        
        filepath = os.path.join("scraped-images", safe_filename)
        
        # Check if already downloaded
        if os.path.exists(filepath):
            logging.info(f"Image already exists: {safe_filename}")
            return filepath
            
        response = requests.get(image_url, stream=True, timeout=10)
        response.raise_for_status()

        with open(filepath, "wb") as f:
            for chunk in response.iter_content(8192):
                f.write(chunk)
                
        logging.info(f"Image saved: {safe_filename}")
        return filepath
        
    except Exception as e:
        logging.error(f"Failed to download image {image_url}: {e}")
        return None

def scrape_content(soup, base_url):
    """Extracts all possible content with improved error handling."""
    data = {
        'metadata': {},
        'images': [],
        'links': [],
        'text': []
    }

    try:
        # Get all meta tags
        for meta in soup.find_all('meta'):
            name = meta.get('name') or meta.get('property')
            content = meta.get('content')
            if name and content:
                data['metadata'][name] = content

        # Get all images from img tags
        for img in soup.find_all('img'):
            src = img.get('src')
            if src:
                img_data = {
                    'src': src,
                    'alt': img.get('alt', ''),
                    'title': img.get('title', '')
                }
                img_name = os.path.basename(src)
                local_path = download_image(src, img_name, base_url)
                if local_path:
                    img_data['local_path'] = local_path
                    data['images'].append(img_data)

        # Get background images
        for elem in soup.find_all(style=True):
            style = elem['style']
            if 'background-image' in style:
                try:
                    url = style.split('url(')[-1].split(')')[0].strip('"\'')
                    if url:
                        img_name = os.path.basename(url)
                        local_path = download_image(url, img_name, base_url)
                        if local_path:
                            data['images'].append({
                                'src': url,
                                'type': 'background-image',
                                'local_path': local_path
                            })
                except Exception as e:
                    logging.error(f"Error parsing background image: {e}")

        # Get all links
        for link in soup.find_all('a', href=True):
            href = link['href']
            if not href.startswith(('http://', 'https://', 'mailto:', 'tel:', '#')):
                href = urljoin(base_url, href)
            link_text = link.get_text(strip=True)
            data['links'].append({
                'href': href,
                'text': link_text
            })

        # Get all text content
        for text in soup.stripped_strings:
            cleaned_text = text.strip()
            if cleaned_text:
                data['text'].append(cleaned_text)

    except Exception as e:
        logging.error(f"Error in scrape_content: {e}")

    return data

def is_valid_url(url, base_domain):
    """Check if URL is valid and belongs to same domain with improved validation."""
    try:
        if not url:
            return False
        parsed = urlparse(url)
        return (parsed.netloc == base_domain and 
                bool(parsed.scheme) and 
                parsed.scheme in ['http', 'https'] and
                '#' not in url and
                'javascript:' not in url.lower())
    except Exception as e:
        logging.error(f"Error validating URL {url}: {e}")
        return False

def scrape_website(start_url, max_pages=None):
    """Scrape entire website with improved robustness and atomic operations."""
    logging.info(f"Starting complete website scrape from {start_url}")
    
    base_domain = urlparse(start_url).netloc
    visited_urls = set()
    urls_to_visit = deque([start_url])
    all_data = {
        'metadata': {},
        'images': [],
        'links': [],
        'text': []
    }
    
    # Configure Chrome options
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        page_count = 0
        while urls_to_visit and (max_pages is None or page_count < max_pages):
            current_url = urls_to_visit.popleft()
            
            if current_url in visited_urls:
                continue
                
            logging.info(f"Scraping page {page_count + 1}: {current_url}")
            visited_urls.add(current_url)
            
            try:
                # Static scraping
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36'
                }
                response = requests.get(current_url, headers=headers, timeout=30)
                response.raise_for_status()
                static_soup = parse_html(response.text)
                static_data = scrape_content(static_soup, current_url)
                
                # Dynamic scraping
                driver.get(current_url)
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                time.sleep(3)  # Additional wait for dynamic content
                dynamic_soup = BeautifulSoup(driver.page_source, 'html.parser')
                dynamic_data = scrape_content(dynamic_soup, current_url)
                
                # Merge data atomically
                page_data = {
                    'metadata': {**static_data['metadata'], **dynamic_data['metadata']},
                    'images': list({img['src']: img for img in static_data['images'] + dynamic_data['images']}.values()),
                    'links': list({link['href']: link for link in static_data['links'] + dynamic_data['links']}.values()),
                    'text': list(set(static_data['text'] + dynamic_data['text']))
                }
                
                # Add new URLs to visit
                for link in page_data['links']:
                    url = link['href']
                    if is_valid_url(url, base_domain) and url not in visited_urls:
                        urls_to_visit.append(url)
                
                # Merge page data into all_data
                all_data['metadata'].update(page_data['metadata'])
                all_data['images'].extend(page_data['images'])
                all_data['links'].extend(page_data['links'])
                all_data['text'].extend(page_data['text'])
                
                # Save intermediate results
                if page_count % 10 == 0:
                    save_to_json(all_data, f"data/intermediate_results_{page_count}.json")
                
                page_count += 1
                time.sleep(2)  # Respectful delay
                
            except Exception as e:
                logging.error(f"Error scraping {current_url}: {e}")
                continue
            
    except Exception as e:
        logging.error(f"Critical error during scraping: {e}")
    finally:
        driver.quit()
        
    # Remove duplicates from final data
    all_data['images'] = list({img['src']: img for img in all_data['images']}.values())
    all_data['links'] = list({link['href']: link for link in all_data['links']}.values())
    all_data['text'] = list(set(all_data['text']))
    
    # Save final results
    save_to_json(all_data, "data/final_results.json")
    save_to_csv(all_data['links'], "data/links.csv")
    
    logging.info(f"Completed website scrape. Found {len(visited_urls)} pages, {len(all_data['images'])} images, {len(all_data['links'])} links")
    return all_data

if __name__ == "__main__":
    url = "your-website-url-here"
    scraped_data = scrape_website(url, max_pages=100)  # Limit to 100 pages for safety
    logging.info(f"Scraped {len(scraped_data['images'])} images and {len(scraped_data['metadata'])} metadata items")
