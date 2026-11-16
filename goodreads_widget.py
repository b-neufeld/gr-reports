import ast
import html
import json
import re
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse
import hashlib

import requests
from bs4 import BeautifulSoup

from models import Book


def fetch_widget(widget_url: str, timeout: int = 30) -> str:
    """Download a public Goodreads Custom Widget response."""

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(compatible; gr-reports/2.0; "
            "+https://github.com/b-neufeld/gr-reports)"
        )
    }

    print(f"Fetching Goodreads widget from {widget_url}")

    response = requests.get(
        widget_url,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()

    if "var widget_code" not in response.text:
        raise ValueError(
            "The Goodreads response did not contain widget_code. "
            "The endpoint may have changed or returned an error page."
        )

    return response.text


def extract_widget_html(widget_javascript: str) -> str:
    """Extract and decode the HTML stored in Goodreads' widget_code variable."""

    assignment_match = re.search(
        r"var\s+widget_code\s*=",
        widget_javascript,
    )

    if not assignment_match:
        raise ValueError(
            "Could not find the widget_code variable in the Goodreads response"
        )

    position = assignment_match.end()

    # Skip whitespace following the equals sign.
    while (
        position < len(widget_javascript)
        and widget_javascript[position].isspace()
    ):
        position += 1

    if position >= len(widget_javascript):
        raise ValueError("widget_code did not contain a value")

    quote = widget_javascript[position]

    if quote not in ("'", '"'):
        raise ValueError(
            "widget_code did not begin with a quoted JavaScript string"
        )

    start = position
    position += 1
    escaped = False

    while position < len(widget_javascript):
        character = widget_javascript[position]

        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == quote:
            end = position + 1
            break

        position += 1
    else:
        raise ValueError(
            "Could not find the end of the widget_code string"
        )

    quoted_value = widget_javascript[start:end]

    # JavaScript may escape forward slashes as \/.
    # Python does not need forward slashes escaped.
    quoted_value = quoted_value.replace(r"\/", "/")

    try:
        widget_html = ast.literal_eval(quoted_value)
    except (SyntaxError, ValueError) as error:
        raise ValueError(
            "Found widget_code but could not decode its JavaScript string"
        ) from error

    # Goodreads escapes closing tags as <\/div>.
    widget_html = widget_html.replace(r"<\/", "</")

    return widget_html


def extract_review_id(review_url: str) -> str:
    """Extract the Goodreads review ID from a review URL."""

    match = re.search(r"/review/show/(\d+)", review_url)

    if not match:
        return ""

    return match.group(1)


def extract_book_id(cover_url: str) -> str:
    """Extract the Goodreads book ID from a cover-image URL."""

    filename = Path(urlparse(cover_url).path).name

    match = re.search(r"(\d+)(?:\._[^.]*)?\.jpg$", filename)

    if not match:
        return ""

    return match.group(1)


def parse_rating(rating_element) -> float:
    """Calculate the numeric rating from Goodreads star images."""

    if rating_element is None:
        return 0.0

    rating = 0.0

    for image in rating_element.find_all("img"):
        source = image.get("src", "")

        if "star_active" in source:
            rating += 1.0
        elif "star_50pct" in source:
            rating += 0.5

    return rating


def parse_tags(tags_element) -> list[str]:
    """Convert widget tag text into a list of tag names."""

    if tags_element is None:
        return []

    text = tags_element.get_text(" ", strip=True)

    text = re.sub(r"^tagged:\s*", "", text, flags=re.IGNORECASE)

    if not text:
        return []

    # Goodreads formats the final tag using "and".
    text = re.sub(r"\s+and\s+", ", ", text)

    return [
        tag.strip()
        for tag in text.split(",")
        if tag.strip()
    ]


def normalize_cover_url(cover_url: str) -> str:
    """
    Remove Goodreads' small-image resize suffix.

    Example:
    44296243._SX98_.jpg
    becomes:
    44296243.jpg
    """

    return re.sub(
        r"\._S[^.]*_\.jpg$",
        ".jpg",
        cover_url,
    )


def find_by_class_prefix(element, prefix: str):
    """Find a child whose class begins with the supplied prefix."""

    return element.find(
        class_=lambda class_name: (
            class_name
            and any(
                value.startswith(prefix)
                for value in (
                    class_name
                    if isinstance(class_name, list)
                    else [class_name]
                )
            )
        )
    )


def parse_widget_books(widget_html: str) -> list[Book]:
    """Parse book records from decoded Goodreads Widget HTML."""

    soup = BeautifulSoup(widget_html, "html.parser")

    containers = soup.find_all(
        class_=lambda class_name: (
            class_name
            and any(
                value.startswith("gr_custom_each_container_")
                for value in (
                    class_name
                    if isinstance(class_name, list)
                    else [class_name]
                )
            )
        )
    )

    books = []

    for container in containers:
        title_element = find_by_class_prefix(
            container,
            "gr_custom_title_",
        )
        author_element = find_by_class_prefix(
            container,
            "gr_custom_author_",
        )
        rating_element = find_by_class_prefix(
            container,
            "gr_custom_rating_",
        )
        review_element = find_by_class_prefix(
            container,
            "gr_custom_review_",
        )
        tags_element = find_by_class_prefix(
            container,
            "gr_custom_tags_",
        )
        cover_element = find_by_class_prefix(
            container,
            "gr_custom_book_container_",
        )

        if title_element is None or cover_element is None:
            continue

        title_link = title_element.find("a")
        image = cover_element.find("img")

        if title_link is None or image is None:
            continue

        review_url = title_link.get("href", "")
        cover_url = image.get("src", "")

        review_id = extract_review_id(review_url)
        book_id = extract_book_id(cover_url)

        # The review ID is still a stable local fallback if the
        # Goodreads cover URL does not contain a recognizable book ID.
        if not book_id:
            book_id = review_id

        author_link = (
            author_element.find("a")
            if author_element is not None
            else None
        )

        author = (
            author_link.get_text(" ", strip=True)
            if author_link is not None
            else ""
        )

        review = (
            review_element.get_text("\n", strip=True)
            if review_element is not None
            else ""
        )

        books.append(
            Book(
                review_id=review_id,
                book_id=book_id,
                title=html.unescape(
                    title_link.get_text(" ", strip=True)
                ),
                author=html.unescape(author),
                rating=parse_rating(rating_element),
                review=html.unescape(review),
                tags=parse_tags(tags_element),
                cover_url=normalize_cover_url(cover_url),
                read_date=None,
            )
        )

    return books


def save_books_json(books: list[Book], output_path: Path) -> None:
    """Save parsed books for inspection and later processing."""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    records = [asdict(book) for book in books]

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            records,
            file,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

def calculate_book_hash(book: Book) -> str:
    """Create a stable hash of widget-controlled book metadata."""

    hash_input = "\n".join(
        [
            book.review_id,
            book.book_id,
            book.title,
            book.author,
            str(book.rating),
            book.review,
            "\n".join(book.tags),
            book.cover_url,
        ]
    )

    return hashlib.sha256(
        hash_input.encode("utf-8")
    ).hexdigest()