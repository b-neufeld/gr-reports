import sqlite3
from datetime import date, datetime
from pathlib import Path

from models import Book


SCHEMA_VERSION = 2

class DuplicateReadError(ValueError):
    """Raised when the same book and read date already exist."""

def connect_database(database_path: Path) -> sqlite3.Connection:
    """Open the SQLite database and initialize its schema."""

    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row

    # SQLite does not enforce foreign keys unless enabled per connection.
    connection.execute("PRAGMA foreign_keys = ON")

    initialize_database(connection)

    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    """Create the application tables if they do not already exist."""

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS books (
            review_id TEXT PRIMARY KEY,
            book_id TEXT NOT NULL,
            title TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT '',
            rating REAL NOT NULL DEFAULT 0,
            review TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '',
            cover_url TEXT NOT NULL DEFAULT '',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            latest_position INTEGER,
            content_hash TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS reads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id TEXT NOT NULL,
            date_read TEXT,
            date_source TEXT NOT NULL,
            confirmed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (review_id)
                REFERENCES books(review_id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            review_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            FOREIGN KEY (review_id)
                REFERENCES books(review_id)
                ON DELETE CASCADE,
            UNIQUE(sync_id, review_id)
        );

        CREATE INDEX IF NOT EXISTS idx_reads_date_read
            ON reads(date_read);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_reads_unique_event
            ON reads(review_id, date_read)
            WHERE date_read IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_observations_review
            ON observations(review_id, observed_at);

        CREATE INDEX IF NOT EXISTS idx_observations_sync
            ON observations(sync_id, position);
        """
    )

    connection.execute(
        """
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('schema_version', ?)
        """,
        (str(SCHEMA_VERSION),),
    )

    connection.commit()


def get_setting(
    connection: sqlite3.Connection,
    key: str,
    default: str | None = None,
) -> str | None:
    """Read one application setting."""

    row = connection.execute(
        """
        SELECT value
        FROM settings
        WHERE key = ?
        """,
        (key,),
    ).fetchone()

    return row["value"] if row else default


def set_setting(
    connection: sqlite3.Connection,
    key: str,
    value: str,
) -> None:
    """Create or update one application setting."""

    connection.execute(
        """
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE
        SET value = excluded.value
        """,
        (key, value),
    )

    connection.commit()


def serialize_tags(tags: list[str]) -> str:
    """Store tags using a simple newline-delimited format."""

    return "\n".join(tags)


def deserialize_tags(value: str) -> list[str]:
    """Convert stored tag text back into a list."""

    if not value:
        return []

    return [
        tag.strip()
        for tag in value.splitlines()
        if tag.strip()
    ]


def upsert_book(
    connection: sqlite3.Connection,
    book: Book,
    observed_at: str,
    position: int,
    content_hash: str,
) -> bool:
    """
    Insert or update a book.

    Returns True when this review ID has never been seen before.
    """

    existing = connection.execute(
        """
        SELECT review_id
        FROM books
        WHERE review_id = ?
        """,
        (book.review_id,),
    ).fetchone()

    is_new = existing is None

    connection.execute(
        """
        INSERT INTO books (
            review_id,
            book_id,
            title,
            author,
            rating,
            review,
            tags,
            cover_url,
            first_seen_at,
            last_seen_at,
            latest_position,
            content_hash
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(review_id) DO UPDATE SET
            book_id = excluded.book_id,
            title = excluded.title,
            author = excluded.author,
            rating = excluded.rating,
            review = excluded.review,
            tags = excluded.tags,
            cover_url = excluded.cover_url,
            last_seen_at = excluded.last_seen_at,
            latest_position = excluded.latest_position,
            content_hash = excluded.content_hash
        """,
        (
            book.review_id,
            book.book_id,
            book.title,
            book.author,
            book.rating,
            book.review,
            serialize_tags(book.tags),
            book.cover_url,
            observed_at,
            observed_at,
            position,
            content_hash,
        ),
    )

    return is_new


def record_observation(
    connection: sqlite3.Connection,
    sync_id: str,
    observed_at: str,
    review_id: str,
    position: int,
    content_hash: str,
) -> None:
    """Record one book's position during a widget synchronization."""

    connection.execute(
        """
        INSERT OR IGNORE INTO observations (
            sync_id,
            observed_at,
            review_id,
            position,
            content_hash
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            sync_id,
            observed_at,
            review_id,
            position,
            content_hash,
        ),
    )


def create_candidate_read(
    connection: sqlite3.Connection,
    review_id: str,
    observed_date: str,
) -> None:
    """Create an unconfirmed read when a new book appears after baseline."""

    now = datetime.now().astimezone().isoformat(timespec="seconds")

    connection.execute(
        """
        INSERT INTO reads (
            review_id,
            date_read,
            date_source,
            confirmed,
            created_at,
            updated_at
        )
        VALUES (?, ?, 'first_seen', 0, ?, ?)
        """,
        (
            review_id,
            observed_date,
            now,
            now,
        ),
    )


def set_read_date(
    connection: sqlite3.Connection,
    review_id: str,
    date_read: date,
) -> int:
    """
    Confirm a reading date.

    If an unconfirmed candidate exists, update it. Otherwise create a
    new read. An identical review ID and date cannot be added twice.
    """

    book = connection.execute(
        """
        SELECT review_id
        FROM books
        WHERE review_id = ?
        """,
        (review_id,),
    ).fetchone()

    if book is None:
        raise ValueError(
            f"No book was found with review ID {review_id}."
        )

    date_value = date_read.isoformat()

    duplicate = connection.execute(
        """
        SELECT id
        FROM reads
        WHERE review_id = ?
          AND date_read = ?
        LIMIT 1
        """,
        (
            review_id,
            date_value,
        ),
    ).fetchone()

    if duplicate is not None:
        raise DuplicateReadError(
            f"Read {duplicate['id']} already records "
            f"review {review_id} on {date_value}."
        )

    now = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    candidate = connection.execute(
        """
        SELECT id
        FROM reads
        WHERE review_id = ?
          AND confirmed = 0
        ORDER BY id DESC
        LIMIT 1
        """,
        (review_id,),
    ).fetchone()

    try:
        if candidate is not None:
            read_id = candidate["id"]

            connection.execute(
                """
                UPDATE reads
                SET date_read = ?,
                    date_source = 'manual',
                    confirmed = 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    date_value,
                    now,
                    read_id,
                ),
            )

        else:
            cursor = connection.execute(
                """
                INSERT INTO reads (
                    review_id,
                    date_read,
                    date_source,
                    confirmed,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, 'manual', 1, ?, ?)
                """,
                (
                    review_id,
                    date_value,
                    now,
                    now,
                ),
            )

            read_id = cursor.lastrowid

        connection.commit()

    except sqlite3.IntegrityError as error:
        connection.rollback()

        raise DuplicateReadError(
            f"A read for review {review_id} already exists "
            f"on {date_value}."
        ) from error

    return read_id

def list_reads(
    connection: sqlite3.Connection,
) -> list[sqlite3.Row]:
    """Return all read records, newest first."""

    return connection.execute(
        """
        SELECT
            r.id,
            r.review_id,
            r.date_read,
            r.date_source,
            r.confirmed,
            r.created_at,
            r.updated_at,
            b.title,
            b.author,
            b.rating
        FROM reads r
        JOIN books b
            ON b.review_id = r.review_id
        ORDER BY
            CASE
                WHEN r.date_read IS NULL THEN 1
                ELSE 0
            END,
            r.date_read DESC,
            r.id DESC
        """
    ).fetchall()


def get_read(
    connection: sqlite3.Connection,
    read_id: int,
) -> sqlite3.Row | None:
    """Return one read record."""

    return connection.execute(
        """
        SELECT
            r.id,
            r.review_id,
            r.date_read,
            r.date_source,
            r.confirmed,
            b.title,
            b.author
        FROM reads r
        JOIN books b
            ON b.review_id = r.review_id
        WHERE r.id = ?
        """,
        (read_id,),
    ).fetchone()


def update_read_date(
    connection: sqlite3.Connection,
    read_id: int,
    date_read: date,
) -> None:
    """Change the date of an existing read and confirm it."""

    existing = get_read(
        connection,
        read_id,
    )

    if existing is None:
        raise ValueError(
            f"No read was found with ID {read_id}."
        )

    date_value = date_read.isoformat()

    duplicate = connection.execute(
        """
        SELECT id
        FROM reads
        WHERE review_id = ?
          AND date_read = ?
          AND id != ?
        LIMIT 1
        """,
        (
            existing["review_id"],
            date_value,
            read_id,
        ),
    ).fetchone()

    if duplicate is not None:
        raise DuplicateReadError(
            f"Read {duplicate['id']} already records "
            f"this book on {date_value}."
        )

    now = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    try:
        connection.execute(
            """
            UPDATE reads
            SET date_read = ?,
                date_source = 'manual',
                confirmed = 1,
                updated_at = ?
            WHERE id = ?
            """,
            (
                date_value,
                now,
                read_id,
            ),
        )

        connection.commit()

    except sqlite3.IntegrityError as error:
        connection.rollback()

        raise DuplicateReadError(
            f"This book already has a read on {date_value}."
        ) from error


def confirm_read(
    connection: sqlite3.Connection,
    read_id: int,
) -> None:
    """Confirm a candidate read without changing its proposed date."""

    existing = get_read(
        connection,
        read_id,
    )

    if existing is None:
        raise ValueError(
            f"No read was found with ID {read_id}."
        )

    if existing["date_read"] is None:
        raise ValueError(
            f"Read {read_id} has no proposed date. "
            "Use update-read to assign one."
        )

    duplicate = connection.execute(
        """
        SELECT id
        FROM reads
        WHERE review_id = ?
          AND date_read = ?
          AND id != ?
        LIMIT 1
        """,
        (
            existing["review_id"],
            existing["date_read"],
            read_id,
        ),
    ).fetchone()

    if duplicate is not None:
        raise DuplicateReadError(
            f"Read {duplicate['id']} already records "
            f"this book on {existing['date_read']}."
        )

    now = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    connection.execute(
        """
        UPDATE reads
        SET confirmed = 1,
            updated_at = ?
        WHERE id = ?
        """,
        (
            now,
            read_id,
        ),
    )

    connection.commit()


def delete_read(
    connection: sqlite3.Connection,
    read_id: int,
) -> sqlite3.Row:
    """Delete one read and return its previous details."""

    existing = get_read(
        connection,
        read_id,
    )

    if existing is None:
        raise ValueError(
            f"No read was found with ID {read_id}."
        )

    connection.execute(
        """
        DELETE FROM reads
        WHERE id = ?
        """,
        (read_id,),
    )

    connection.commit()

    return existing


def list_undated_books(
    connection: sqlite3.Connection,
) -> list[sqlite3.Row]:
    """Return baseline books that have no read records."""

    return connection.execute(
        """
        SELECT
            b.review_id,
            b.title,
            b.author,
            b.rating,
            b.first_seen_at,
            b.latest_position
        FROM books b
        LEFT JOIN reads r
            ON r.review_id = b.review_id
        WHERE r.id IS NULL
        ORDER BY b.latest_position
        """
    ).fetchall()


def list_all_books(
    connection: sqlite3.Connection,
) -> list[sqlite3.Row]:
    """Return all known books in current Goodreads Widget order."""

    return connection.execute(
        """
        SELECT
            review_id,
            book_id,
            title,
            author,
            rating,
            first_seen_at,
            last_seen_at,
            latest_position
        FROM books
        ORDER BY
            CASE
                WHEN latest_position IS NULL THEN 1
                ELSE 0
            END,
            latest_position,
            title
        """
    ).fetchall()


def count_undated_books(
    connection: sqlite3.Connection,
) -> int:
    """Count books that do not have any reading event."""

    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM books b
        WHERE NOT EXISTS (
            SELECT 1
            FROM reads r
            WHERE r.review_id = b.review_id
        )
        """
    ).fetchone()

    return row["count"]


def list_candidate_reads(
    connection: sqlite3.Connection,
) -> list[sqlite3.Row]:
    """Return automatically detected reads awaiting confirmation."""

    return connection.execute(
        """
        SELECT
            r.id,
            r.review_id,
            b.title,
            b.author,
            r.date_read,
            r.date_source
        FROM reads r
        JOIN books b
            ON b.review_id = r.review_id
        WHERE r.confirmed = 0
        ORDER BY r.date_read DESC, r.id DESC
        """
    ).fetchall()


def get_books_for_month(
    connection: sqlite3.Connection,
    year: int,
    month: int,
) -> list[Book]:
    """Load confirmed books read during one calendar month."""

    month_start = date(year, month, 1)

    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)

    rows = connection.execute(
        """
        SELECT
            b.review_id,
            b.book_id,
            b.title,
            b.author,
            b.rating,
            b.review,
            b.tags,
            b.cover_url,
            r.date_read
        FROM reads r
        JOIN books b
            ON b.review_id = r.review_id
        WHERE r.confirmed = 1
          AND r.date_read >= ?
          AND r.date_read < ?
        ORDER BY r.date_read, r.id
        """,
        (
            month_start.isoformat(),
            next_month.isoformat(),
        ),
    ).fetchall()

    books = []

    for row in rows:
        books.append(
            Book(
                review_id=row["review_id"],
                book_id=row["book_id"],
                title=row["title"],
                author=row["author"],
                rating=row["rating"],
                review=row["review"],
                tags=deserialize_tags(row["tags"]),
                cover_url=row["cover_url"],
                read_date=date.fromisoformat(row["date_read"]),
            )
        )

    return books


def get_database_counts(
    connection: sqlite3.Connection,
) -> dict[str, int]:
    """Return summary counts for diagnostic output."""

    book_count = connection.execute(
        "SELECT COUNT(*) AS count FROM books"
    ).fetchone()["count"]

    read_count = connection.execute(
        "SELECT COUNT(*) AS count FROM reads"
    ).fetchone()["count"]

    confirmed_count = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM reads
        WHERE confirmed = 1
        """
    ).fetchone()["count"]

    candidate_count = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM reads
        WHERE confirmed = 0
        """
    ).fetchone()["count"]

    observation_count = connection.execute(
        "SELECT COUNT(*) AS count FROM observations"
    ).fetchone()["count"]

    return {
        "books": book_count,
        "reads": read_count,
        "confirmed_reads": confirmed_count,
        "candidate_reads": candidate_count,
        "observations": observation_count,
    }