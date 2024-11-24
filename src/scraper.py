import requests
from bs4 import BeautifulSoup
import time
from selenium import webdriver
import logging
from helpers import save_to_csv, save_to_json

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def scrape_content(soup, base_url):
    """Extracts images, text, and links from a given BeautifulSoup object."""
    data = []

    # Extract images
    for img in soup.find_all("img"):
        img_src = img.get("src")
        if img_src:
            img_src = img_src if img_src.startswith("http") else base_url + img_src
            data.append({"type": "image", "content": img_src})

    # Extract links
    for link in soup.find_all("a", href=True):
        link_url = link["href"]
        link_url = link_url if link_url.startswith("http") else base_url + link_url
        data.append({"type": "link", "content": link_url})

    # Extract text
    for text_element in soup.find_all("p"):
        text_content = text_element.get_text(strip=True)
        if text_content:
            data.append({"type": "text", "content": text_content})

    return data

def scrape_website_with_pagination(base_url):
    """Scrape a website and handle pagination."""
    current_url = base_url
    all_data = []

    while current_url:
        try:
            logging.info(f"Scraping URL: {current_url}")
            response = requests.get(current_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Scrape current page
            page_data = scrape_content(soup, base_url)
            all_data.extend(page_data)

            # Find the "Next" button
            next_button = soup.find("a", text="Next")
            if next_button and next_button.get("href"):
                next_url = next_button["href"]
                current_url = next_url if next_url.startswith("http") else base_url + next_url
            else:
                current_url = None  # No more pages
        except Exception as e:
            logging.error(f"Error scraping {current_url}: {e}")
            break

    return all_data

def scrape_dynamic_content(url):
    """Scrape JavaScript-rendered content using Selenium."""
    logging.info(f"Scraping dynamic content from {url}")
    driver = webdriver.Chrome()  # Ensure ChromeDriver is installed and in PATH
    driver.get(url)

    # Allow JavaScript to load
    time.sleep(5)

    # Get page content
    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    # Scrape content
    return scrape_content(soup, url)

if __name__ == "__main__":
    # Example usage
    base_url = "https://antarman.goadoctor.co.in/"
    static_data = scrape_website_with_pagination(base_url)
    logging.info(f"Scraped {len(static_data)} items from static pages")

    # Save static data
    save_to_csv(static_data, "data/static_data.csv")
    save_to_json(static_data, "data/static_data.json")

    # Example dynamic scraping
    dynamic_url = "https://antarman.goadoctor.co.in/"
    dynamic_data = scrape_dynamic_content(dynamic_url)
    logging.info(f"Scraped {len(dynamic_data)} items from dynamic pages")

    # Save dynamic data
    save_to_csv(dynamic_data, "data/dynamic_data.csv")
    save_to_json(dynamic_data, "data/dynamic_data.json")
