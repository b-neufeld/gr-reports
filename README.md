# gr-reports

`gr-reports` creates monthly reading collages sized for Instagram Stories using data from a Goodreads Custom Widget.

The project began after my sister posted monthly reading summaries on Instagram Stories by saving book covers to a folder on her phone and taking a screenshot. I liked the idea and wanted to automate it using my Goodreads data.

The original version used Goodreads RSS feeds. Goodreads removed those feeds, so version 2.0 now uses the public Goodreads Custom Widget, a local SQLite database, and a browser-based management interface.

**PLEASE TAKE NOTE!** This project is 100% "AI Slop" but it is lightweight and for-fun. It was developed slowly and interatively with testing along the way instead of being one-shot. 

<img width="734" height="644" alt="Screenshot 2026-11-21 075627" src="https://github.com/user-attachments/assets/25fc97e5-0839-4bf3-a3ba-2f2e84456ea4" />

<img width="731" height="644" alt="Screenshot 2026-11-21 075719" src="https://github.com/user-attachments/assets/1b54be6a-1b11-43cf-b8da-9b951aea76a7" />

## Features

- Reads up to 100 recently completed books from a public Goodreads Custom Widget (since RSS was depreciated in October 2026)
- Does not require Goodreads credentials, cookies, or an authenticated browser session
- Stores book and reading data in SQLite
- Caches cover images locally
- Supports whole-star and half-star Goodreads ratings
- Supports rereads as separate reading events
- Provides a browser interface for:
  - Synchronizing Goodreads
  - Importing dates for baseline books
  - Confirming newly detected reads
  - Correcting read dates
  - Adding rereads
  - Deleting incorrect reading records
  - Generating and downloading monthly collages
- Generates 1080 × 1920 JPEG images suitable for Instagram Stories
- Can synchronize Goodreads automatically every 24 hours
- Runs as a Docker container

## How the Goodreads integration works

Goodreads no longer provides the RSS feed used by earlier versions of this project. Version 2.0 uses Goodreads' Custom Widget instead.

The Custom Widget provides:

- Book title
- Author
- Goodreads review ID
- Cover URL
- Rating, including half-stars
- Review excerpt
- Tags
- Books sorted by Goodreads `date_read`

The Widget does **not** provide the exact `date_read` value. On first installation, `gr-reports` establishes the returned books as a baseline. The Baseline page then lets you assign dates to the recent books that you want included in monthly collages.

After the baseline is established, a previously unseen Goodreads review ID is created as a candidate read the next time it appears in the Widget.

## Getting your Goodreads Custom Widget URL

1. Sign in to Goodreads in a web browser.
2. Open **My Books**.
3. Find **Tools → Widgets** near the bottom-left of the page.
4. Find **Custom Widget**.
5. Configure the Widget:
   - **Shelf:** `read`
   - **Show:** check every available item
   - **Sort:** `date read`
   - **Order:** descending
   - **Number of books:** `100`
   - Cover size can be small or medium. The application attempts to retrieve a larger version of each cover automatically.
6. Select **Save changes**.
7. Copy the generated HTML into Notepad or another text editor.
8. Near the bottom, locate the URL inside the `<script src="...">` element.

The URL will resemble:

```text
https://www.goodreads.com/review/custom_widget/5672051.Brahm's%20bookshelf:%20read?cover_position=left&cover_size=small&num_books=100&order=d&shelf=read&show_author=1&show_cover=1&show_rating=1&show_review=1&show_tags=1&show_title=1&sort=date_read&widget_bg_color=FFFFFF&widget_bg_transparent=&widget_border_width=1&widget_id=1794944134&widget_text_color=000000&widget_title_size=medium&widget_width=medium
```

Copy only the URL, without the surrounding `<script>` element or quotation marks.

The important query parameters are:

```text
num_books=100
order=d
shelf=read
show_author=1
show_cover=1
show_rating=1
show_review=1
show_tags=1
show_title=1
sort=date_read
```

Test the URL in a private browsing window. A working URL returns JavaScript beginning with content similar to:

```javascript
var widget_code = '...';
```

## Docker Compose

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` and provide:

- Your complete Goodreads Custom Widget URL
- Your name for collage headings
- A strong Flask secret
- Persistent host directories for the database, Widget cache, covers, and collages

Generate a Flask secret with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Example `.env`:

```dotenv
GOODREADS_WIDGET_URL=https://www.goodreads.com/review/custom_widget/REPLACE_ME
USER_NAME=Brahm

FLASK_SECRET_KEY=replace-with-a-long-random-value

GR_REPORTS_DATA_PATH=/path/to/gr-reports/data
GR_REPORTS_CACHE_PATH=/path/to/gr-reports/widget_cache
GR_REPORTS_COVERS_PATH=/path/to/gr-reports/covers
GR_REPORTS_COLLAGES_PATH=/path/to/gr-reports/collages

ENABLE_SCHEDULED_SYNC=true
SYNC_ON_STARTUP=true
SYNC_INTERVAL_HOURS=24
```

Example `docker-compose.yml`:

```yaml
services:
  goodreads-collage:
    container_name: goodreads-collage

    image: ghcr.io/b-neufeld/gr-reports:latest

    ports:
      - "8010:5000"

    environment:
      GOODREADS_WIDGET_URL: "${GOODREADS_WIDGET_URL:?Set GOODREADS_WIDGET_URL in .env}"
      USER_NAME: "${USER_NAME:-}"
      FLASK_SECRET_KEY: "${FLASK_SECRET_KEY:?Set FLASK_SECRET_KEY in .env}"

      DATA_DIR: "/app/data"
      WIDGET_CACHE_DIR: "/app/widget_cache"
      COVER_DIR: "/app/covers"
      COLLAGE_DIR: "/app/collages"

      ENABLE_SCHEDULED_SYNC: "${ENABLE_SCHEDULED_SYNC:-true}"
      SYNC_ON_STARTUP: "${SYNC_ON_STARTUP:-true}"
      SYNC_INTERVAL_HOURS: "${SYNC_INTERVAL_HOURS:-24}"

    volumes:
      - "${GR_REPORTS_DATA_PATH:?Set GR_REPORTS_DATA_PATH in .env}:/app/data"
      - "${GR_REPORTS_CACHE_PATH:?Set GR_REPORTS_CACHE_PATH in .env}:/app/widget_cache"
      - "${GR_REPORTS_COVERS_PATH:?Set GR_REPORTS_COVERS_PATH in .env}:/app/covers"
      - "${GR_REPORTS_COLLAGES_PATH:?Set GR_REPORTS_COLLAGES_PATH in .env}:/app/collages"

    restart: unless-stopped
```

Start the application:

```bash
docker compose pull
docker compose up -d
```

Open:

```text
http://YOUR_DOCKER_HOST:8010
```

View logs:

```bash
docker compose logs -f goodreads-collage
```

## First-run setup

On the first synchronization, the application treats all returned Widget books as an existing baseline.

This avoids incorrectly assigning all 100 books to the day the application was installed.

After the first synchronization:

1. Open **Baseline**.
2. Find the recent books that should appear in monthly collages.
3. Enter their actual read dates.
4. Select **Import entered dates**.
5. Open **Collages** and navigate to the applicable month.
6. Generate the collage.

Books without entered dates remain available in the baseline but do not appear in monthly collages.

## Normal operation

The container synchronizes Goodreads shortly after startup and then every 24 hours by default.

You can also select **Sync Goodreads** from the Dashboard at any time.

When a previously unseen Goodreads review ID appears:

1. The application creates a candidate read.
2. The candidate uses its first-seen date as the proposed read date.
3. Confirm or correct the date from the Dashboard or Reads page.
4. Generate or regenerate the appropriate monthly collage.

## Rereads and Goodreads review IDs

Goodreads generally uses one review record per user and book. Rereading a book may update the existing review and move it near the top of the shelf instead of creating a new review ID.

This creates an important limitation:

- A brand-new review ID can be detected automatically.
- A reread that reuses an existing review ID may not be detected automatically.

To add a reread:

1. Open **Reads**.
2. Select the existing book.
3. Enter the new completion date.
4. Add the read.

The database permits multiple reading events for the same Goodreads review ID as long as the dates differ.

If a book was reread several times, each reading event can be assigned separately to the appropriate month.

## Data and backups

Persistent application data is stored in four directories:

| Container path | Contents |
|---|---|
| `/app/data` | SQLite database |
| `/app/widget_cache` | Latest parsed Widget snapshot |
| `/app/covers` | Downloaded book covers |
| `/app/collages` | Generated JPEG files |

The most important file to back up is:

```text
/app/data/gr-reports.db
```

The covers and collages can be downloaded again or regenerated. The SQLite database contains confirmed dates, rereads, candidates, and synchronization history.

Stop the container or otherwise ensure the database is not being written while taking a direct filesystem copy of the SQLite file.

## Updating

To update to a newer container image:

```bash
docker compose pull
docker compose up -d
```

Persistent data remains in the mounted host directories.

For a specific release, replace `latest` with a versioned image tag:

```yaml
image: ghcr.io/b-neufeld/gr-reports:2.0.0
```

Pinning a version is recommended when predictable upgrades are more important than automatically tracking the latest stable release.

## Troubleshooting

### The dashboard shows 100 Widget books but no reads

This is expected after the first synchronization.

Open **Baseline** and assign dates to the recent books that should appear in collages.

### No new candidate appears after rereading a book

Goodreads may have reused the existing review ID. Add the reread manually from the Reads page.

### A collage does not contain a book

Confirm that:

- The book has a confirmed read record.
- The read date is in the selected month.
- A cover was downloaded successfully.
- The collage was regenerated after changing the read date.

### The application creates a new baseline after being recreated

Confirm that the host data directory is correctly mounted to:

```text
/app/data
```

and that the host directory contains:

```text
gr-reports.db
```

### Automatic synchronization does not run

Confirm the container environment contains:

```text
ENABLE_SCHEDULED_SYNC=true
SYNC_ON_STARTUP=true
SYNC_INTERVAL_HOURS=24
```

The supplied Dockerfile uses one Gunicorn worker. Increasing the worker count can create multiple scheduled synchronization threads and is not supported without moving synchronization to an external scheduler.

## Security notes

- The Goodreads Widget URL is public and does not contain your Goodreads password or authenticated session.
- Keep `FLASK_SECRET_KEY` private.
- Do not commit `.env`.
- The web interface does not currently provide user authentication. Expose it only on a trusted network or place it behind an authenticated reverse proxy such as Caddy, Traefik, Nginx, or an identity-aware proxy.
- If publishing the service through Caddy, configure authentication or restrict access to trusted users.

## Development

Run locally:

```bash
python -m pip install -r requirements.txt
python server.py
```

The command-line interface is also available:

```bash
python app.py sync
python app.py status
python app.py list-reads
python app.py list-candidates
python app.py generate 2026 11
```

## Project status

Version 2.0 replaces the removed Goodreads RSS integration with a Custom Widget parser and local reading-history database.

This is a personal project shared without warranty or support. Improvement suggestions and pull requests are welcome.

Repository: https://github.com/b-neufeld/gr-reports
