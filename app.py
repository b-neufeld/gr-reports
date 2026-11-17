import argparse
import os
import re
from datetime import date, datetime
from pathlib import Path

import requests
from PIL import Image

from collage_generator import create_collage
from database import (
    DuplicateReadError,
    confirm_read,
    connect_database,
    create_candidate_read,
    delete_read,
    get_books_for_month,
    get_database_counts,
    get_setting,
    list_candidate_reads,
    list_reads,
    list_undated_books,
    record_observation,
    set_read_date,
    set_setting,
    update_read_date,
    upsert_book,
)
from goodreads_widget import (
    calculate_book_hash,
    extract_widget_html,
    fetch_widget,
    parse_widget_books,
    save_books_json,
)


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

WIDGET_URL = os.getenv("GOODREADS_WIDGET_URL", "")

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DATABASE_PATH = DATA_DIR / "gr-reports.db"

CACHE_DIR = Path(os.getenv("WIDGET_CACHE_DIR", "widget_cache"))
COVER_DIR = Path(os.getenv("COVER_DIR", "covers"))
COLLAGE_DIR = Path(os.getenv("COLLAGE_DIR", "collages"))

CACHE_DIR.mkdir(parents=True, exist_ok=True)
COVER_DIR.mkdir(parents=True, exist_ok=True)
COLLAGE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# Cover handling
# ---------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    """Convert an identifier into a safe local filename."""

    return re.sub(r"[^\w\-_.]", "_", str(name))


def get_cover_path(book) -> Path:
    """Return the local cover path for a Book object."""

    identifier = book.book_id or book.review_id
    safe_identifier = sanitize_filename(identifier)

    return COVER_DIR / f"{safe_identifier}.jpg"


def get_cover_download_urls(cover_url: str) -> list[str]:
    """
    Return cover URLs in order of preference.

    Goodreads Widget URLs normally contain a size suffix such as:

        44296243._SX98_.jpg

    The unsized URL often provides a larger image. Keep the original URL
    as a fallback in case the larger version is unavailable.
    """

    if not cover_url:
        return []

    full_size_url = re.sub(
        r"\._S[^.]*_\.jpg$",
        ".jpg",
        cover_url,
    )

    urls = [full_size_url]

    if cover_url != full_size_url:
        urls.append(cover_url)

    return urls


def download_image(url: str, destination: Path) -> None:
    """Download and validate one image."""

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(compatible; gr-reports/2.0; "
            "+https://github.com/b-neufeld/gr-reports)"
        )
    }

    temporary_path = destination.with_suffix(".download")

    try:
        response = requests.get(
            url,
            headers=headers,
            stream=True,
            timeout=30,
        )

        response.raise_for_status()

        content_type = response.headers.get(
            "Content-Type",
            "",
        )

        if not content_type.startswith("image/"):
            raise ValueError(
                "Expected an image but received "
                f"{content_type or 'an unknown content type'}"
            )

        with temporary_path.open("wb") as file:
            for chunk in response.iter_content(
                chunk_size=8192
            ):
                if chunk:
                    file.write(chunk)

        with Image.open(temporary_path) as image:
            image.verify()

        temporary_path.replace(destination)

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def download_cover_if_missing(book) -> Path | None:
    """Download and cache a book cover."""

    cover_path = get_cover_path(book)

    if cover_path.exists():
        try:
            with Image.open(cover_path) as image:
                image.verify()

            print(
                f"Cover for '{book.title}' "
                f"(ID: {book.book_id}) already exists."
            )

            return cover_path

        except Exception:
            print(
                f"Existing cover for '{book.title}' is invalid. "
                "Downloading it again."
            )

            cover_path.unlink()

    download_urls = get_cover_download_urls(
        book.cover_url
    )

    if not download_urls:
        print(
            f"No cover URL is available for "
            f"'{book.title}'."
        )

        return None

    last_error = None

    for url in download_urls:
        try:
            download_image(
                url=url,
                destination=cover_path,
            )

            print(
                f"Downloaded cover for '{book.title}' "
                f"(ID: {book.book_id})"
            )

            return cover_path

        except Exception as error:
            last_error = error

            print(
                f"Could not download '{book.title}' "
                f"from {url}: {error}"
            )

    print(
        f"Failed to download a cover for "
        f"'{book.title}': {last_error}"
    )

    return None


# ---------------------------------------------------------------------
# Goodreads synchronization
# ---------------------------------------------------------------------

def fetch_widget_books():
    """Fetch and parse the current Goodreads Custom Widget."""

    if not WIDGET_URL:
        raise ValueError(
            "GOODREADS_WIDGET_URL is not configured."
        )

    widget_javascript = fetch_widget(WIDGET_URL)
    widget_html = extract_widget_html(
        widget_javascript
    )
    books = parse_widget_books(widget_html)

    if not books:
        raise ValueError(
            "The Goodreads Widget returned no "
            "parseable books."
        )

    return books


def synchronize_widget(connection):
    """Store the latest Widget state in SQLite."""

    books = fetch_widget_books()

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

    newly_discovered_books = []

    for position, book in enumerate(
        books,
        start=1,
    ):
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

        if is_new and baseline_complete:
            newly_discovered_books.append(book)

            create_candidate_read(
                connection=connection,
                review_id=book.review_id,
                observed_date=observed_date,
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

    else:
        print(
            f"Widget sync complete: "
            f"{len(books)} observed, "
            f"{len(newly_discovered_books)} "
            "newly discovered."
        )

    set_setting(
        connection,
        "last_sync_at",
        observed_at,
    )

    connection.commit()

    save_books_json(
        books,
        CACHE_DIR / "latest_books.json",
    )

    return books, newly_discovered_books


# ---------------------------------------------------------------------
# Status and list output
# ---------------------------------------------------------------------

def print_database_status(connection) -> None:
    """Print a concise database summary."""

    counts = get_database_counts(connection)

    print(f"Database: {DATABASE_PATH}")

    print(
        "Last sync: "
        f"{get_setting(connection, 'last_sync_at', 'never')}"
    )

    print(f"Books: {counts['books']}")
    print(f"Read records: {counts['reads']}")

    print(
        "Confirmed reads: "
        f"{counts['confirmed_reads']}"
    )

    print(
        "Candidate reads: "
        f"{counts['candidate_reads']}"
    )

    print(
        "Observations: "
        f"{counts['observations']}"
    )


def print_undated_books(connection) -> None:
    """Print baseline books without read records."""

    rows = list_undated_books(connection)

    if not rows:
        print("No undated baseline books found.")
        return

    print(
        f"{len(rows)} baseline books do not "
        "have a read date:\n"
    )

    for row in rows:
        print(
            f"{row['review_id']} | "
            f"{row['rating']:.1f} | "
            f"{row['title']} | "
            f"{row['author']}"
        )


def print_candidate_reads(connection) -> None:
    """Print automatically detected candidate reads."""

    rows = list_candidate_reads(connection)

    if not rows:
        print(
            "No candidate reads require "
            "confirmation."
        )

        return

    print(
        f"{len(rows)} candidate reads require "
        "confirmation:\n"
    )

    for row in rows:
        print(
            f"{row['review_id']} | "
            f"{row['date_read']} | "
            f"{row['title']} | "
            f"{row['author']}"
        )

def print_reads(connection) -> None:
    """Print all stored reading events."""

    rows = list_reads(connection)

    if not rows:
        print("No read records found.")
        return

    print(
        "ID   Date         Status       Rating  Title\n"
        "---- ------------ ------------ ------- ------------------------------"
    )

    for row in rows:
        date_value = row["date_read"] or "undated"

        status = (
            "confirmed"
            if row["confirmed"]
            else "candidate"
        )

        print(
            f"{row['id']:<4} "
            f"{date_value:<12} "
            f"{status:<12} "
            f"{row['rating']:<7.1f} "
            f"{row['title']} | "
            f"{row['author']}"
        )

# ---------------------------------------------------------------------
# Collage generation
# ---------------------------------------------------------------------

def generate_month(
    connection,
    year: int,
    month: int,
) -> Path | None:
    """Generate a collage for one month."""

    books = get_books_for_month(
        connection,
        year,
        month,
    )

    if not books:
        print(
            f"No confirmed reads were found for "
            f"{year:04d}-{month:02d}."
        )

        return None

    available_books = []

    for book in books:
        cover_path = download_cover_if_missing(book)

        if cover_path is not None:
            available_books.append(book)

    if not available_books:
        print(
            "No books with valid covers are "
            "available for this collage."
        )

        return None

    user_name = os.getenv("USER_NAME", "")

    title_prefix = (
        f"{user_name}'s "
        if user_name
        else ""
    )

    month_name = datetime(
        year,
        month,
        1,
    ).strftime("%B")

    header_text = (
        f"{title_prefix}{month_name} Reads"
    )

    output_path = COLLAGE_DIR / (
        f"{year:04d}-{month:02d}.jpg"
    )

    return create_collage(
        books=available_books,
        cover_path_function=get_cover_path,
        output_path=output_path,
        header_text=header_text,
    )


# ---------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------

def build_argument_parser():
    """Create the command-line interface."""

    parser = argparse.ArgumentParser(
        description=(
            "Create Goodreads reading collages "
            "from a Goodreads et."
        )
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    commands.add_parser(
        "sync",
        help=(
            "Fetch the Goodreads Widget and "
            "update the database."
        ),
    )

    commands.add_parser(
        "status",
        help=(
            "Show database and synchronization "
            "status."
        ),
    )

    commands.add_parser(
        "list-undated",
        help=(
            "List baseline books without "
            "a read date."
        ),
    )

    commands.add_parser(
        "list-candidates",
        help=(
            "List newly detected reads awaiting "
            "confirmation."
        ),
    )
    
    commands.add_parser(
        "list-reads",
        help="List all confirmed and candidate read records.",
    )

    set_date_parser = commands.add_parser(
        "set-date",
        help=(
            "Assign and confirm a read date."
        ),
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
        help=(
            "Generate a collage for one month."
        ),
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

    update_read_parser = commands.add_parser(
        "update-read",
        help="Change and confirm the date of an existing read.",
    )

    update_read_parser.add_argument(
        "read_id",
        type=int,
        help="Local read record ID.",
    )

    update_read_parser.add_argument(
        "date_read",
        help="New read date in YYYY-MM-DD format.",
    )

    delete_read_parser = commands.add_parser(
        "delete-read",
        help="Delete an incorrect read record.",
    )

    delete_read_parser.add_argument(
        "read_id",
        type=int,
        help="Local read record ID.",
    )

    confirm_read_parser = commands.add_parser(
        "confirm-read",
        help="Confirm a candidate read using its proposed date.",
    )

    confirm_read_parser.add_argument(
        "read_id",
        type=int,
        help="Local read record ID.",
    )

    return parser

def parse_iso_date(
    parser,
    value: str,
) -> date:
    """Parse a YYYY-MM-DD command-line value."""

    try:
        return date.fromisoformat(value)

    except ValueError:
        parser.error(
            f"Invalid date '{value}'. "
            "Use YYYY-MM-DD format."
        )

def main() -> None:
    """Run the requested command."""

    parser = build_argument_parser()
    arguments = parser.parse_args()

    connection = connect_database(
        DATABASE_PATH
    )

    try:
        if arguments.command == "sync":
            books, new_books = synchronize_widget(
                connection
            )

            print(
                f"Stored the latest state of "
                f"{len(books)} Widget books."
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

        elif arguments.command == "list-reads":
            print_reads(connection)

        elif arguments.command == "set-date":
            parsed_date = parse_iso_date(
                parser,
                arguments.date_read,
            )

            try:
                read_id = set_read_date(
                    connection=connection,
                    review_id=arguments.review_id,
                    date_read=parsed_date,
                )

            except (
                DuplicateReadError,
                ValueError,
            ) as error:
                print(f"Not changed: {error}")
                return

            print(
                f"Confirmed read {read_id}: "
                f"review {arguments.review_id} "
                f"on {parsed_date.isoformat()}."
            )

        elif arguments.command == "update-read":
            parsed_date = parse_iso_date(
                parser,
                arguments.date_read,
            )

            try:
                update_read_date(
                    connection=connection,
                    read_id=arguments.read_id,
                    date_read=parsed_date,
                )

            except (
                DuplicateReadError,
                ValueError,
            ) as error:
                print(f"Not changed: {error}")
                return

            print(
                f"Updated read {arguments.read_id} "
                f"to {parsed_date.isoformat()}."
            )

        elif arguments.command == "confirm-read":
            try:
                confirm_read(
                    connection=connection,
                    read_id=arguments.read_id,
                )

            except (
                DuplicateReadError,
                ValueError,
            ) as error:
                print(f"Not changed: {error}")
                return

            print(
                f"Confirmed read {arguments.read_id}."
            )

        elif arguments.command == "delete-read":
            try:
                deleted = delete_read(
                    connection=connection,
                    read_id=arguments.read_id,
                )

            except ValueError as error:
                print(f"Not changed: {error}")
                return

            print(
                f"Deleted read {deleted['id']}: "
                f"{deleted['title']} on "
                f"{deleted['date_read'] or 'an unknown date'}."
            )

        elif arguments.command == "generate":
            generate_month(
                connection=connection,
                year=arguments.year,
                month=arguments.month,
            )

    finally:
        connection.close()


if __name__ == "__main__":
    main()