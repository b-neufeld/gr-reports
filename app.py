import os
import requests
from datetime import datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import re
from dateutil import parser as date_parser  # Add to requirements.txt
from calendar import monthrange
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import PIL
from collections import defaultdict


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

def group_books_by_month(items):
    books_by_month = defaultdict(list)
    for item in items:
        user_read_at = item.findtext("user_read_at")
        if not user_read_at:
            continue
        try:
            read_date = date_parser.parse(user_read_at).replace(tzinfo=None)
        except Exception:
            continue
        year, month = read_date.year, read_date.month
        books_by_month[(year, month)].append(item)
    return books_by_month

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

def create_collage(books, year, month):
    canvas_width, canvas_height = 1080, 1920
    margin = 20
    padding = 30
    max_image_width = 300
    max_image_height = 450
    title_font_size = 20

    images = []
    ratings = []
    titles = []

    # Load fonts with fallback
    try:
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", size=title_font_size)
    except Exception:
        title_font = ImageFont.load_default()

    def resize_to_fit_box(img, max_w, max_h):
        w, h = img.size
        scale = min(max_w / w, max_h / h)
        new_size = (int(w * scale), int(h * scale))
        return img.resize(new_size, Image.LANCZOS)

    for book in books:
        book_id = book.findtext("book_id") or "unknown"
        user_rating = int(book.findtext("user_rating") or 0)
        book_title = book.findtext("title") or "Unknown Title"
        image_path = COVER_DIR / f"{book_id}.jpg"
        if not image_path.exists():
            print(f"Missing cover for '{book_title}' ({book_id}) - skipping")
            continue
        try:
            img = Image.open(image_path).convert("RGBA")
            img = resize_to_fit_box(img, max_image_width, max_image_height)
            images.append(img)
            ratings.append(user_rating)
            titles.append(book_title)
        except Exception as e:
            print(f"Failed to load image {image_path}: {e}")

    if not images:
        print("No images found to include in collage.")
        return

    cols = min(3, len(images))
    rows = (len(images) + cols - 1) // cols

    # Calculate total collage size based on images and padding
    total_width = cols * max_image_width + (cols - 1) * padding + 2 * margin
    total_height = rows * (max_image_height + title_font_size + 10) + (rows - 1) * padding + 2 * margin

    collage = Image.new("RGB", (canvas_width, canvas_height), (0, 0, 0))  # black background
    draw = ImageDraw.Draw(collage)

    # Center horizontally and vertically if fewer than max cols
    offset_x = (canvas_width - total_width) // 2
    offset_y = (canvas_height - total_height) // 2

    for idx, img in enumerate(images):
        row = idx // cols
        col = idx % cols
        x = offset_x + col * (max_image_width + padding)
        y = offset_y + row * (max_image_height + title_font_size + 10 + padding)

        # Paste cover image over shadow
        # Center the image in its allocated box
        img_w, img_h = img.size
        img_x = x + (max_image_width - img_w) // 2
        img_y = y + (max_image_height - img_h) // 2

        # Create visible drop shadow (dark gray semi-transparent) behind cover
        shadow = Image.new("RGBA", img.size, (50, 50, 50, 180))  # dark gray shadow
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=5))
        collage.paste(shadow, (x + 10, img_y + 10), shadow)

        collage.paste(img, (img_x, img_y), img)

        # Load star image once
        STAR_PATH = Path("assets/star.png")
        star_img = Image.open(STAR_PATH).convert("RGBA")

        star_spacing = 10
        star_scale = 0.1  # Scale relative to max image height
        scaled_star_size = int(max_image_height * star_scale)
        star_img = star_img.resize((scaled_star_size, scaled_star_size), Image.LANCZOS)

        # Calculate starting X based on number of stars
        stars_w = ratings[idx] * (scaled_star_size + star_spacing)
        stars_x = x + (max_image_width - stars_w) // 2
        stars_y = img_y + img_h - 60 # img_y + 10

        for s in range(ratings[idx]):
            sx = stars_x + s * (scaled_star_size + star_spacing)
            collage.paste(star_img, (sx, stars_y), star_img)

        # Draw title centered below image with shadow for readability
        raw_title = titles[idx]
        title_text = raw_title if len(raw_title) <= 30 else raw_title[:27] + "…"
        bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_w = bbox[2] - bbox[0]
        title_h = bbox[3] - bbox[1]
        title_x = x + (max_image_width - title_w) // 2
        title_y = y + max_image_height + 5
        # Shadow
        draw.text((title_x + 1, title_y + 1), title_text, font=title_font, fill="black")
        # Foreground
        draw.text((title_x, title_y), title_text, font=title_font, fill="white")

    # Add header title
    user_name = os.getenv("USER_NAME", "")
    title_prefix = f"{user_name}'s " if user_name else ""
    header_text = +f"{title_prefix}{datetime(year, month, 1).strftime('%B')} Reads"
    header_font_size = 48
    try:
        header_font = ImageFont.truetype("DejaVuSans-Bold.ttf", size=header_font_size)
    except Exception:
        header_font = ImageFont.load_default()

    header_bbox = draw.textbbox((0, 0), header_text, font=header_font)
    header_w = header_bbox[2] - header_bbox[0]
    header_x = (canvas_width - header_w) // 2
    draw.text((header_x + 1, margin + 1), header_text, font=header_font, fill="black")
    draw.text((header_x, margin), header_text, font=header_font, fill="white")

    # Save the collage with YYYY-MM.jpg format for last month
    collage_filename = f"{year:04d}-{month:02d}.jpg"
    output_path = Path("collages") / collage_filename
    output_path.parent.mkdir(exist_ok=True)

    collage.save(output_path)
    print(f"Collage saved to {output_path}")



# Run logic
if __name__ == "__main__":
    feed_file = get_feed()
    items = parse_feed(feed_file)
    print(f"Feed file: {feed_file}")

    books_by_month = group_books_by_month(items)

    all_books = [book for books in books_by_month.values() for book in books]
    print(f"Total books with read dates: {len(all_books)}")

    # Download covers (once per book)
    seen_ids = set()
    for book in all_books:
        book_id = book.findtext("book_id")
        if book_id and book_id not in seen_ids:
            download_cover_if_missing(book)
            seen_ids.add(book_id)

    # Create a collage per month
    for (year, month), books in sorted(books_by_month.items()):
        print(f"Creating collage for {datetime(year, month, 1).strftime('%B %Y')} ({len(books)} books)")
        create_collage(books, year, month)
