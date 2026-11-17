import os
import threading
import time
from datetime import date, datetime
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from app import (
    COLLAGE_DIR,
    DATABASE_PATH,
    generate_month,
    synchronize_widget,
)
from database import (
    DuplicateReadError,
    confirm_read,
    connect_database,
    delete_read,
    get_books_for_month,
    get_database_counts,
    get_read,
    get_setting,
    list_candidate_reads,
    list_reads,
    set_read_date,
    update_read_date,
)


app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "FLASK_SECRET_KEY",
    "development-only-change-me",
)

SYNC_INTERVAL_HOURS = int(
    os.getenv("SYNC_INTERVAL_HOURS", "24")
)

ENABLE_SCHEDULED_SYNC = (
    os.getenv("ENABLE_SCHEDULED_SYNC", "true").lower()
    in {"1", "true", "yes", "on"}
)

SYNC_ON_STARTUP = (
    os.getenv("SYNC_ON_STARTUP", "true").lower()
    in {"1", "true", "yes", "on"}
)

sync_lock = threading.Lock()


def get_database():
    """Open the application database."""

    return connect_database(DATABASE_PATH)


def parse_date_value(value: str) -> date:
    """Parse an HTML date field."""

    if not value:
        raise ValueError("A read date is required.")

    try:
        return date.fromisoformat(value)

    except ValueError as error:
        raise ValueError(
            "The read date must use YYYY-MM-DD format."
        ) from error


def perform_sync():
    """
    Run one Goodreads synchronization.

    A lock prevents the scheduled task and web interface from
    synchronizing simultaneously.
    """

    if not sync_lock.acquire(blocking=False):
        raise RuntimeError(
            "A Goodreads synchronization is already running."
        )

    connection = get_database()

    try:
        books, new_books = synchronize_widget(connection)

        return {
            "observed": len(books),
            "new": len(new_books),
        }

    finally:
        connection.close()
        sync_lock.release()


def scheduled_sync_worker():
    """Synchronize Goodreads periodically in the background."""

    initial_delay_seconds = 10

    if SYNC_ON_STARTUP:
        time.sleep(initial_delay_seconds)

        try:
            print("Running startup Goodreads synchronization...")
            result = perform_sync()

            print(
                "Startup synchronization complete: "
                f"{result['observed']} observed, "
                f"{result['new']} new."
            )

        except Exception as error:
            print(
                "Startup Goodreads synchronization failed: "
                f"{error}"
            )

    while True:
        time.sleep(SYNC_INTERVAL_HOURS * 60 * 60)

        try:
            print("Running scheduled Goodreads synchronization...")
            result = perform_sync()

            print(
                "Scheduled synchronization complete: "
                f"{result['observed']} observed, "
                f"{result['new']} new."
            )

        except Exception as error:
            print(
                "Scheduled Goodreads synchronization failed: "
                f"{error}"
            )


@app.context_processor
def inject_template_values():
    """Provide common values to all templates."""

    return {
        "application_name": "Goodreads Collages",
        "current_year": datetime.now().year,
    }


@app.route("/")
def dashboard():
    """Show application status and recent activity."""

    connection = get_database()

    try:
        counts = get_database_counts(connection)
        candidates = list_candidate_reads(connection)
        reads = list_reads(connection)

        generated_collages = sorted(
            COLLAGE_DIR.glob("*.jpg"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

        collages = [
            {
                "filename": path.name,
                "modified_at": datetime.fromtimestamp(
                    path.stat().st_mtime
                ),
            }
            for path in generated_collages[:12]
        ]

        return render_template(
            "dashboard.html",
            counts=counts,
            candidates=candidates[:8],
            recent_reads=reads[:8],
            collages=collages,
            last_sync_at=get_setting(
                connection,
                "last_sync_at",
                "Never",
            ),
        )

    finally:
        connection.close()


@app.post("/sync")
def sync_goodreads():
    """Run a manual Goodreads synchronization."""

    try:
        result = perform_sync()

        flash(
            (
                f"Synchronization complete: "
                f"{result['observed']} books observed and "
                f"{result['new']} new books discovered."
            ),
            "success",
        )

    except Exception as error:
        flash(
            f"Goodreads synchronization failed: {error}",
            "error",
        )

    return redirect(url_for("dashboard"))


@app.route("/reads")
def reads_page():
    """List confirmed and candidate reads."""

    connection = get_database()

    try:
        status_filter = request.args.get(
            "status",
            "all",
        )

        rows = list_reads(connection)

        if status_filter == "confirmed":
            rows = [
                row
                for row in rows
                if row["confirmed"]
            ]

        elif status_filter == "candidate":
            rows = [
                row
                for row in rows
                if not row["confirmed"]
            ]

        elif status_filter != "all":
            abort(400)

        return render_template(
            "reads.html",
            reads=rows,
            status_filter=status_filter,
        )

    finally:
        connection.close()


@app.post("/reads/add")
def add_read():
    """Add a confirmed reading event for a book."""

    review_id = request.form.get(
        "review_id",
        "",
    ).strip()

    date_value = request.form.get(
        "date_read",
        "",
    ).strip()

    connection = get_database()

    try:
        parsed_date = parse_date_value(date_value)

        read_id = set_read_date(
            connection=connection,
            review_id=review_id,
            date_read=parsed_date,
        )

        flash(
            f"Read {read_id} was added.",
            "success",
        )

    except (
        DuplicateReadError,
        ValueError,
    ) as error:
        flash(str(error), "error")

    finally:
        connection.close()

    return redirect(url_for("reads_page"))


@app.post("/reads/<int:read_id>/confirm")
def confirm_read_route(read_id):
    """Confirm a candidate using its proposed date."""

    connection = get_database()

    try:
        confirm_read(
            connection=connection,
            read_id=read_id,
        )

        flash(
            f"Read {read_id} was confirmed.",
            "success",
        )

    except (
        DuplicateReadError,
        ValueError,
    ) as error:
        flash(str(error), "error")

    finally:
        connection.close()

    return redirect(url_for("reads_page"))


@app.post("/reads/<int:read_id>/edit")
def edit_read_route(read_id):
    """Change the date of an existing read."""

    date_value = request.form.get(
        "date_read",
        "",
    ).strip()

    connection = get_database()

    try:
        parsed_date = parse_date_value(date_value)

        update_read_date(
            connection=connection,
            read_id=read_id,
            date_read=parsed_date,
        )

        flash(
            f"Read {read_id} was updated.",
            "success",
        )

    except (
        DuplicateReadError,
        ValueError,
    ) as error:
        flash(str(error), "error")

    finally:
        connection.close()

    return redirect(url_for("reads_page"))


@app.post("/reads/<int:read_id>/delete")
def delete_read_route(read_id):
    """Delete a reading event."""

    connection = get_database()

    try:
        deleted = delete_read(
            connection=connection,
            read_id=read_id,
        )

        flash(
            (
                f"Deleted read {read_id}: "
                f"{deleted['title']}."
            ),
            "success",
        )

    except ValueError as error:
        flash(str(error), "error")

    finally:
        connection.close()

    return redirect(url_for("reads_page"))


@app.route("/collages")
def collages_page():
    """Redirect to the current month."""

    today = date.today()

    return redirect(
        url_for(
            "collage_month",
            year=today.year,
            month=today.month,
        )
    )


@app.route("/collages/<int:year>/<int:month>")
def collage_month(year, month):
    """Preview one month and its generated collage."""

    if month < 1 or month > 12:
        abort(404)

    connection = get_database()

    try:
        books = get_books_for_month(
            connection,
            year,
            month,
        )

    finally:
        connection.close()

    filename = f"{year:04d}-{month:02d}.jpg"
    collage_path = COLLAGE_DIR / filename

    previous_year = year
    previous_month = month - 1

    if previous_month == 0:
        previous_year -= 1
        previous_month = 12

    next_year = year
    next_month = month + 1

    if next_month == 13:
        next_year += 1
        next_month = 1

    return render_template(
        "collage.html",
        year=year,
        month=month,
        month_name=datetime(
            year,
            month,
            1,
        ).strftime("%B"),
        books=books,
        filename=filename,
        collage_exists=collage_path.exists(),
        previous_year=previous_year,
        previous_month=previous_month,
        next_year=next_year,
        next_month=next_month,
    )


@app.post("/collages/<int:year>/<int:month>/generate")
def generate_collage_route(year, month):
    """Generate or regenerate one monthly collage."""

    if month < 1 or month > 12:
        abort(404)

    connection = get_database()

    try:
        output_path = generate_month(
            connection=connection,
            year=year,
            month=month,
        )

        if output_path is None:
            flash(
                (
                    f"No collage was generated for "
                    f"{year:04d}-{month:02d}."
                ),
                "error",
            )

        else:
            flash(
                f"Generated {output_path.name}.",
                "success",
            )

    except Exception as error:
        flash(
            f"Collage generation failed: {error}",
            "error",
        )

    finally:
        connection.close()

    return redirect(
        url_for(
            "collage_month",
            year=year,
            month=month,
        )
    )


@app.route("/collage-files/<path:filename>")
def collage_file(filename):
    """Display or download a generated collage."""

    download = (
        request.args.get("download", "0")
        == "1"
    )

    return send_from_directory(
        directory=COLLAGE_DIR.resolve(),
        path=filename,
        as_attachment=download,
    )


def start_scheduled_sync():
    """Start the single-process background scheduler."""

    if not ENABLE_SCHEDULED_SYNC:
        print("Scheduled Goodreads synchronization is disabled.")
        return

    thread = threading.Thread(
        target=scheduled_sync_worker,
        daemon=True,
        name="goodreads-sync",
    )

    thread.start()


if __name__ == "__main__":
    start_scheduled_sync()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
    )