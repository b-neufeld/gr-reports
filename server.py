from flask import Flask, send_from_directory, render_template_string
from pathlib import Path
import threading
import time
import subprocess

app = Flask(__name__)
COLLAGE_DIR = Path("collages")

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
        h1 {
            margin-top: 30px;
        }
    </style>
</head>
<body>
    <h1>📚 Goodreads Collages</h1>
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
        reverse=True  # Show newest first
    )
    return render_template_string(HTML_TEMPLATE, files=files)

@app.route("/collages/<path:filename>")
def collage_file(filename):
    return send_from_directory(COLLAGE_DIR, filename)

if __name__ == "__main__":
    # Start the background thread for the daily task
    threading.Thread(target=run_daily_task, daemon=True).start()
    # Start the Flask app
    app.run(host="0.0.0.0", port=5000)