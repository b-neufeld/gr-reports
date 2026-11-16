import os
import requests
import math
from datetime import date, datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import re
from dateutil import parser as date_parser  
from calendar import monthrange
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from collections import defaultdict
import argparse

from pathlib import Path

from goodreads_widget import (
    calculate_book_hash,
    extract_widget_html,
    fetch_widget,
    parse_widget_books,
    save_books_json,
)

from database import (
    connect_database,
    create_candidate_read,
    get_books_for_month,
    get_database_counts,
    get_setting,
    list_candidate_reads,
    list_undated_books,
    record_observation,
    set_read_date,
    set_setting,
    upsert_book,
)


WIDGET_URL = os.getenv("GOODREADS_WIDGET_URL", "")
DATA_DIR = Path(
    os.getenv("DATA_DIR", "data")
)
DATABASE_PATH = DATA_DIR / "gr-reports.db"

# Configuration
FEED_URL = os.getenv("GOODREADS_RSS_URL", "https://www.goodreads.com/review/list_rss/5672051?shelf=read")
# XML files, limited to one per 24 hours. 
CACHE_DIR = Path("rss_cache")
CACHE_DIR.mkdir(exist_ok=True)
# Cover directory. 
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
        "User-Agent": "Mozilla/5.0 (compatible; RSSFetcher/1.0; +https://github.com/b-neufeld/gr-reports)"
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

def limit_cache_files(max_files=20):
    """Keep only the newest max_files XML files in CACHE_DIR."""
    xml_files = sorted(CACHE_DIR.glob("rss_*.xml"), key=lambda f: f.stat().st_mtime, reverse=True)
    for old_file in xml_files[max_files:]:
        try:
            print(f"🗑 Removing old cache file: {old_file}")
            old_file.unlink()
        except Exception as e:
            print(f"❌ Failed to remove {old_file}: {e}")

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
    return re.sub(r"[^\w\-_.]", "_", str(name))

def get_cover_path(book):
    """Return the local cover path for a Book object."""

    safe_book_id = sanitize_filename(book.book_id or book.review_id)
    return COVER_DIR / f"{safe_book_id}.jpg"


def download_cover_if_missing(book):
    """Download and cache a book cover."""

    cover_path = get_cover_path(book)

    if cover_path.exists():
        print(
            f"Cover for '{book.title}' "
            f"(ID: {book.book_id}) already exists."
        )
        return cover_path

    if not book.cover_url:
        print(f"No cover URL available for '{book.title}'")
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(compatible; gr-reports/2.0; "
            "+https://github.com/b-neufeld/gr-reports)"
        )
    }

    try:
        response = requests.get(
            book.cover_url,
            headers=headers,
            stream=True,
            timeout=30,
        )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")

        if not content_type.startswith("image/"):
            raise ValueError(
                f"Expected an image but received {content_type or 'unknown content'}"
            )

        with cover_path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)

        # Verify that Pillow can open the downloaded file.
        with Image.open(cover_path) as image:
            image.verify()

        print(
            f"Downloaded cover for '{book.title}' "
            f"(ID: {book.book_id})"
        )

        return cover_path

    except Exception as error:
        print(f"Failed to download cover for '{book.title}': {error}")

        # Remove a partial or invalid download.
        if cover_path.exists():
            cover_path.unlink()

        return None

def create_collage(
    books,
    output_filename,
    header_text,
):
    """Create an Instagram Story collage from Book objects."""

    canvas_width = 1080
    canvas_height = 1920
    margin = 20
    padding = 30
    review_font_size = 20

    images = []
    ratings = []
    reviews = []
    included_books = []

    try:
        review_font = ImageFont.truetype(
            "DejaVuSans-Bold.ttf",
            size=review_font_size,
        )
    except Exception:
        review_font = ImageFont.load_default()

    def resize_to_fit_box(image, max_width, max_height):
        width, height = image.size

        scale = min(
            max_width / width,
            max_height / height,
        )

        new_size = (
            max(1, int(width * scale)),
            max(1, int(height * scale)),
        )

        return image.resize(new_size, Image.Resampling.LANCZOS)

    for book in books:
        image_path = get_cover_path(book)

        if not image_path.exists():
            print(
                f"Missing cover for '{book.title}' "
                f"({book.book_id}) - skipping"
            )
            continue

        try:
            with Image.open(image_path) as source_image:
                image = source_image.convert("RGBA")

            images.append(image)
            ratings.append(float(book.rating or 0))
            reviews.append(book.review or "")
            included_books.append(book)

        except Exception as error:
            print(
                f"Failed to load cover for "
                f"'{book.title}' from {image_path}: {error}"
            )

    if not images:
        print("No valid cover images found for the collage.")
        return None

    number_of_images = len(images)

    def determine_grid(number):
        if number == 1:
            return 1, 1
        if number == 2:
            return 2, 1
        if number <= 4:
            return 2, 2
        if number <= 6:
            return 3, 2
        if number <= 9:
            return 3, 3
        if number <= 12:
            return 4, 3

        columns = min(4, int(number ** 0.5) + 1)
        rows = math.ceil(number / columns)
        return columns, rows

    columns, rows = determine_grid(number_of_images)

    available_width = (
        canvas_width
        - (2 * margin)
        - ((columns - 1) * padding)
    )

    available_height = (
        canvas_height
        - (2 * margin)
        - ((rows - 1) * padding)
        - 150
    )

    cell_width = available_width // columns

    # Reserve room inside each row for review text.
    review_area_height = 55 if columns < 4 else 0
    cell_height = available_height // rows
    max_image_height = max(1, cell_height - review_area_height)

    resized_images = [
        resize_to_fit_box(
            image,
            cell_width,
            max_image_height,
        )
        for image in images
    ]

    collage = Image.new(
        "RGB",
        (canvas_width, canvas_height),
        (0, 0, 0),
    )

    draw = ImageDraw.Draw(collage)

    star_path = Path("assets/star.png")

    if not star_path.exists():
        raise FileNotFoundError(
            f"Star image was not found at {star_path}"
        )

    star_image = Image.open(star_path).convert("RGBA")

    def get_scaled_star_size(image_height):
        return max(
            20,
            min(48, int(image_height * 0.1)),
        )

    star_spacing = 8

    grid_width = (
        columns * cell_width
        + (columns - 1) * padding
    )

    grid_height = (
        rows * cell_height
        + (rows - 1) * padding
    )

    offset_x = (canvas_width - grid_width) // 2
    offset_y = (
        (canvas_height - grid_height) // 2
        + 60
    )

    def paste_rating_stars(
        rating,
        x,
        y,
        available_width,
        star_size,
    ):
        """
        Draw full and half stars.

        A half-star is rendered by showing only the left half of the
        existing star image, so a second asset is not required.
        """

        rating = max(0.0, min(5.0, float(rating)))

        full_stars = int(rating)
        has_half_star = (rating - full_stars) >= 0.25
        displayed_stars = full_stars + (1 if has_half_star else 0)

        if displayed_stars == 0:
            return

        resized_star = star_image.resize(
            (star_size, star_size),
            Image.Resampling.LANCZOS,
        )

        total_width = (
            displayed_stars * star_size
            + (displayed_stars - 1) * star_spacing
        )

        start_x = x + (available_width - total_width) // 2

        for star_number in range(full_stars):
            star_x = start_x + star_number * (
                star_size + star_spacing
            )

            collage.paste(
                resized_star,
                (star_x, y),
                resized_star,
            )

        if has_half_star:
            star_x = start_x + full_stars * (
                star_size + star_spacing
            )

            half_width = max(1, star_size // 2)

            half_star = resized_star.crop(
                (0, 0, half_width, star_size)
            )

            collage.paste(
                half_star,
                (star_x, y),
                half_star,
            )

    for index, image in enumerate(resized_images):
        row = index // columns
        column = index % columns

        cell_x = offset_x + column * (
            cell_width + padding
        )

        cell_y = offset_y + row * (
            cell_height + padding
        )

        image_width, image_height = image.size

        image_x = (
            cell_x
            + (cell_width - image_width) // 2
        )

        image_y = (
            cell_y
            + (max_image_height - image_height) // 2
        )

        shadow = Image.new(
            "RGBA",
            image.size,
            (50, 50, 50, 180),
        )

        shadow = shadow.filter(
            ImageFilter.GaussianBlur(radius=5)
        )

        collage.paste(
            shadow,
            (image_x + 10, image_y + 10),
            shadow,
        )

        collage.paste(
            image,
            (image_x, image_y),
            image,
        )

        star_size = get_scaled_star_size(image_height)
        star_y = image_y + image_height - star_size - 12

        paste_rating_stars(
            rating=ratings[index],
            x=cell_x,
            y=star_y,
            available_width=cell_width,
            star_size=star_size,
        )

        raw_review = reviews[index]

        if columns >= 4:
            review_text = ""
        else:
            character_limit = {
                1: 80,
                2: 45,
                3: 27,
            }.get(columns, 0)

            if len(raw_review) <= character_limit:
                review_text = raw_review
            else:
                review_text = (
                    raw_review[:character_limit - 1]
                    + "…"
                )

        if review_text:
            bounding_box = draw.textbbox(
                (0, 0),
                review_text,
                font=review_font,
            )

            text_width = (
                bounding_box[2] - bounding_box[0]
            )

            text_x = (
                cell_x
                + (cell_width - text_width) // 2
            )

            text_y = (
                cell_y
                + max_image_height
                + 10
            )

            draw.text(
                (text_x + 1, text_y + 1),
                review_text,
                font=review_font,
                fill="black",
            )

            draw.text(
                (text_x, text_y),
                review_text,
                font=review_font,
                fill="white",
            )

    header_font_size = 48

    try:
        header_font = ImageFont.truetype(
            "DejaVuSans-Bold.ttf",
            size=header_font_size,
        )
    except Exception:
        header_font = ImageFont.load_default()

    header_box = draw.textbbox(
        (0, 0),
        header_text,
        font=header_font,
    )

    header_width = header_box[2] - header_box[0]
    header_x = (canvas_width - header_width) // 2
    header_y = margin

    draw.text(
        (header_x + 1, header_y + 1),
        header_text,
        font=header_font,
        fill="black",
    )

    draw.text(
        (header_x, header_y),
        header_text,
        font=header_font,
        fill="white",
    )

    output_directory = Path("collages")
    output_directory.mkdir(exist_ok=True)

    output_path = output_directory / output_filename

    collage.save(
        output_path,
        quality=95,
        subsampling=0,
    )

    print(
        f"Collage saved to {output_path} "
        f"using {len(included_books)} books"
    )

    return output_path

def fetch_widget_books():
    """Fetch and parse the current Goodreads Custom Widget."""

    if not WIDGET_URL:
        raise ValueError(
            "GOODREADS_WIDGET_URL environment variable is not configured"
        )

    widget_javascript = fetch_widget(WIDGET_URL)
    widget_html = extract_widget_html(widget_javascript)

    return parse_widget_books(widget_html)


def synchronize_widget(connection):
    """Store the latest widget state in SQLite."""

    books = fetch_widget_books()

    if not books:
        raise ValueError(
            "Goodreads Widget returned no parseable books. "
            "The database was not updated."
        )

    now = datetime.now().astimezone()
    observed_at = now.isoformat(timespec="seconds")
    observed_date = now.date().isoformat()
    sync_id = now.strftime("%Y%m%dT%H%M%S%z")

    baseline_complete = (
        get_setting(
            connection,
            "baseline_complete",
            "false",
        )
        == "true"
    )

    new_books = []

    for position, book in enumerate(books, start=1):
        content_hash = calculate_book_hash(book)

        is_new = upsert_book(
            connection=connection,
            book=book,
            observed_at=observed_at,
            position=position,
            content_hash=content_hash,
        )

        record_observation(
            connection=connection,
            sync_id=sync_id,
            observed_at=observed_at,
            review_id=book.review_id,
            position=position,
            content_hash=content_hash,
        )

        if is_new:
            new_books.append(book)

            # The initial 100 books are reference data, not 100 books
            # read today. Only later additions become candidates.
            if baseline_complete:
                create_candidate_read(
                    connection,
                    book.review_id,
                    observed_date,
                )

    if not baseline_complete:
        set_setting(
            connection,
            "baseline_complete",
            "true",
        )

        print(
            f"Established initial baseline with "
            f"{len(books)} books."
        )

        # Baseline books are existing history, not newly detected reads.
        newly_discovered_books = []

    else:
        newly_discovered_books = new_books

        print(
            f"Widget sync complete: {len(books)} observed, "
            f"{len(newly_discovered_books)} newly discovered."
        )

    set_setting(
        connection,
        "last_sync_at",
        observed_at,
    )

    connection.commit()

    save_books_json(
        books,
        Path("widget_cache/latest_books.json"),
    )

    return books, newly_discovered_books


def print_database_status(connection):
    """Print a concise database summary."""

    counts = get_database_counts(connection)

    print(f"Database: {DATABASE_PATH}")
    print(
        f"Last sync: "
        f"{get_setting(connection, 'last_sync_at', 'never')}"
    )
    print(f"Books: {counts['books']}")
    print(f"Read records: {counts['reads']}")
    print(f"Confirmed reads: {counts['confirmed_reads']}")
    print(f"Candidate reads: {counts['candidate_reads']}")
    print(f"Observations: {counts['observations']}")


def print_undated_books(connection):
    """Print baseline books that have no read record."""

    rows = list_undated_books(connection)

    if not rows:
        print("No undated baseline books found.")
        return

    print(
        f"{len(rows)} baseline books do not have a read date:\n"
    )

    for row in rows:
        print(
            f"{row['review_id']} | "
            f"{row['rating']:.1f} | "
            f"{row['title']} | "
            f"{row['author']}"
        )


def print_candidate_reads(connection):
    """Print automatically detected reads awaiting confirmation."""

    rows = list_candidate_reads(connection)

    if not rows:
        print("No candidate reads require confirmation.")
        return

    print(
        f"{len(rows)} candidate reads require confirmation:\n"
    )

    for row in rows:
        print(
            f"{row['review_id']} | "
            f"{row['date_read']} | "
            f"{row['title']} | "
            f"{row['author']}"
        )

def build_argument_parser():
    """Create the command-line interface."""

    parser = argparse.ArgumentParser(
        description=(
            "Create Goodreads reading collages from a "
            "Goodreads Custom Widget."
        )
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    commands.add_parser(
        "sync",
        help="Fetch the Goodreads Widget and update the database.",
    )

    commands.add_parser(
        "status",
        help="Show database and synchronization status.",
    )

    commands.add_parser(
        "list-undated",
        help="List baseline books without a read date.",
    )

    commands.add_parser(
        "list-candidates",
        help="List newly detected reads awaiting confirmation.",
    )

    set_date_parser = commands.add_parser(
        "set-date",
        help="Assign and confirm a read date.",
    )

    set_date_parser.add_argument(
        "review_id",
        help="Goodreads review ID.",
    )

    set_date_parser.add_argument(
        "date_read",
        help="Read date in YYYY-MM-DD format.",
    )

    generate_parser = commands.add_parser(
        "generate",
        help="Generate a collage for one month.",
    )

    generate_parser.add_argument(
        "year",
        type=int,
    )

    generate_parser.add_argument(
        "month",
        type=int,
        choices=range(1, 13),
    )

    return parser


def main():
    """Run the requested command."""

    parser = build_argument_parser()
    arguments = parser.parse_args()

    connection = connect_database(DATABASE_PATH)

    try:
        if arguments.command == "sync":
            books, new_books = synchronize_widget(connection)

            print(
                f"Stored the latest state of "
                f"{len(books)} widget books."
            )

            if new_books:
                print("\nNew books:")

                for book in new_books:
                    print(
                        f"{book.review_id} | "
                        f"{book.title} | "
                        f"{book.author}"
                    )

        elif arguments.command == "status":
            print_database_status(connection)

        elif arguments.command == "list-undated":
            print_undated_books(connection)

        elif arguments.command == "list-candidates":
            print_candidate_reads(connection)

        elif arguments.command == "set-date":
            try:
                parsed_date = date.fromisoformat(
                    arguments.date_read
                )
            except ValueError:
                parser.error(
                    "date_read must use YYYY-MM-DD format"
                )

            read_id = set_read_date(
                connection,
                arguments.review_id,
                parsed_date,
            )

            print(
                f"Confirmed read {read_id}: "
                f"review {arguments.review_id} "
                f"on {parsed_date.isoformat()}."
            )

        elif arguments.command == "generate":
            month_books = get_books_for_month(
                connection,
                arguments.year,
                arguments.month,
            )

            if not month_books:
                print(
                    f"No confirmed reads found for "
                    f"{arguments.year:04d}-"
                    f"{arguments.month:02d}."
                )
                return

            for book in month_books:
                download_cover_if_missing(book)

            user_name = os.getenv("USER_NAME", "")
            title_prefix = (
                f"{user_name}'s "
                if user_name
                else ""
            )

            header_text = (
                f"{title_prefix}"
                f"{datetime(arguments.year, arguments.month, 1):%B} "
                f"Reads"
            )

            create_collage(
                books=month_books,
                output_filename=(
                    f"{arguments.year:04d}-"
                    f"{arguments.month:02d}.jpg"
                ),
                header_text=header_text,
            )

    finally:
        connection.close()


if __name__ == "__main__":
    main()