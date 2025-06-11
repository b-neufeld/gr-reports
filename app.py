import os
import requests
from datetime import datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import re
from dateutil import parser as date_parser  # Add to requirements.txt
from calendar import monthrange

# Configuration
FEED_URL = os.getenv("GOODREADS_RSS_URL", "https://www.goodreads.com/review/list_rss/5672051?shelf=read")

CACHE_DIR = Path("rss_cache")
CACHE_DIR.mkdir(exist_ok=True)

COVER_DIR = Path("covers")
COVER_DIR.mkdir(exist_ok=True)

def get_latest_feed_file():
    files = sorted(CACHE_DIR.glob("rss_*.xml"), reverse=True)
    return files[0] if files else None

def is_file_older_than_24_hours(file_path):
    file_time = datetime.utcfromtimestamp(file_path.stat().st_mtime)
    return datetime.utcnow() - file_time > timedelta(hours=24)

def fetch_and_cache_feed():
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; RSSFetcher/1.0; +https://brahm.ca)"
    }

    print(f"Fetching RSS feed from {FEED_URL}")
    response = requests.get(FEED_URL, headers=headers)
    response.raise_for_status()

    filename = f"rss_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.xml"
    filepath = os.path.join(CACHE_DIR, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(response.text)

    print(f"Saved new RSS feed to {filepath}")
    return filepath

def get_feed():
    latest_file = get_latest_feed_file()
    if latest_file and not is_file_older_than_24_hours(latest_file):
        print(f"Using cached feed from {latest_file}")
        return latest_file
    return fetch_and_cache_feed()

def parse_feed(file_path):
    tree = ET.parse(file_path)
    root = tree.getroot()
    return root.findall("channel/item")

def get_books_read_last_month(items):
    now = datetime.now()
    first_of_this_month = datetime(now.year, now.month, 1)
    last_month_end = first_of_this_month - timedelta(days=1)
    last_month_start = datetime(last_month_end.year, last_month_end.month, 1)

    recent_books = []

    for item in items:
        user_read_at = item.findtext("user_read_at")
        if not user_read_at:
            continue
        try:
            read_date = date_parser.parse(user_read_at)
            read_date = read_date.replace(tzinfo=None)  # Strip timezone
        except Exception:
            continue

        if last_month_start <= read_date <= last_month_end:
            recent_books.append(item)

    return recent_books

def sanitize_filename(name):
    return re.sub(r'[^\w\-_.]', '_', name)

def download_cover_if_missing(item):
    image_url = item.findtext("book_large_image_url")
    book_title = item.findtext("title") or "unknown"
    book_id = item.findtext("book_id") or "unknown_id"
    sanitized_id = re.sub(r'[^\w\-_.]', '_', book_id)
    cover_path = COVER_DIR / f"{sanitized_id}.jpg"

    if not cover_path.exists():
        try:
            response = requests.get(image_url, stream=True, timeout=10)
            response.raise_for_status()
            with open(cover_path, "wb") as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            print(f"Downloaded cover for '{book_title}' (ID: {book_id})")
        except Exception as e:
            print(f"Failed to download cover for '{book_title}' (ID: {book_id}): {e}")
    else:
        print(f"Cover for '{book_title}' (ID: {book_id}) already exists.")


# Run logic
if __name__ == "__main__":
    feed_file = get_feed()

    items = parse_feed(feed_file)
    print(f"Feed file: {feed_file}")

    books_last_month = get_books_read_last_month(items)

    print(f"Found {len(books_last_month)} books read last month.")
    for book in books_last_month:
        download_cover_if_missing(book)