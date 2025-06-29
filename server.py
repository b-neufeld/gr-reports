from flask import Flask, send_from_directory, render_template_string, redirect, url_for
from pathlib import Path
from datetime import datetime, timedelta
import threading
import time
import subprocess

app = Flask(__name__)
COLLAGE_DIR = Path("collages")
CACHE_DIR = Path("rss_cache")  # directory where rss_*.xml files are cached

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Goodreads Collages</title>
    <style>
        body {
            font-family: sans-serif;
            background: #111;
            color: #eee;
            text-align: center;
        }
        .gallery {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            padding: 20px;
        }
        .gallery a {
            margin: 10px;
        }
        .gallery img {
            width: 200px;
            border: 2px solid #444;
        }
        button {
            margin: 20px;
            padding: 10px 20px;
            font-size: 16px;
            background-color: #444;
            color: #eee;
            border: none;
            cursor: pointer;
        }
        button:hover {
            background-color: #666;
        }
    </style>
</head>
<body>
    <h1>📚 Goodreads Collages</h1>
    <form method="post" action="/refresh">
        <button type="submit">Refresh</button>
    </form>
    <div class="gallery">
    {% for filename in files %}
        <a href="/collages/{{ filename }}">
            <img src="/collages/{{ filename }}" alt="{{ filename }}">
        </a>
    {% endfor %}
    </div>
</body>
</html>
"""

def run_daily_task():
    while True:
        try:
            print("📅 Running app.py task...")
            subprocess.run(["python", "app.py"], check=True)
            print("✅ app.py completed")
        except Exception as e:
            print(f"❌ Error running app.py: {e}")
        time.sleep(24 * 60 * 60)

@app.route("/")
def index():
    COLLAGE_DIR.mkdir(exist_ok=True)
    files = sorted(
        [f.name for f in COLLAGE_DIR.glob("*.jpg")],
        reverse=True
    )
    return render_template_string(HTML_TEMPLATE, files=files)

@app.route("/refresh", methods=["POST"])
def refresh():
    print("🔄 Refresh triggered by user")
    CACHE_DIR.mkdir(exist_ok=True)
    cutoff = datetime.utcnow() - timedelta(hours=24)

    # Delete XML files newer than 24h
    for file in CACHE_DIR.glob("rss_*.xml"):
        mtime = datetime.utcfromtimestamp(file.stat().st_mtime)
        if mtime > cutoff:
            print(f"🗑 Deleting recent cache file: {file}")
            try:
                file.unlink()
            except Exception as e:
                print(f"❌ Failed to delete {file}: {e}")

    # Run app.py once to re-fetch and re-generate collages
    try:
        subprocess.run(["python", "app.py"], check=True)
        print("✅ app.py ran successfully")
    except Exception as e:
        print(f"❌ Error running app.py: {e}")

    # Redirect back to the homepage
    return redirect(url_for("index"))

@app.route("/collages/<path:filename>")
def collage_file(filename):
    return send_from_directory(COLLAGE_DIR, filename)

if __name__ == "__main__":
    threading.Thread(target=run_daily_task, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
